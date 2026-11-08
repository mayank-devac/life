"""A small clickable panel: step back, play / pause (one toggle), faster and pin buttons,
plus time and population. Shown both pinned and unpinned.

Pinned, the wallpaper window ignores the mouse (clicks go through to the desktop), so the
panel is its own little window in the screen's top-left corner, one level above the
desktop icons: clickable, but still below every normal app window, like a desktop widget.
Unpinned, it's attached to the game window's top-left corner and moves along with it."""
import ctypes
import ctypes.util
import importlib

# pyobjc loads these names lazily, so static checkers can't see them in a `from AppKit
# import ...`; importing the modules this way (as window.py does) keeps them quiet.
AppKit = importlib.import_module("AppKit")  # ImportError without pyobjc
Foundation = importlib.import_module("Foundation")
NSButton, NSColor, NSScreen = AppKit.NSButton, AppKit.NSColor, AppKit.NSScreen
NSMakeRect = AppKit.NSMakeRect

MARGIN = 20        # gap to the screen's top-left corner (pinned), below the menu bar
BUTTON_W, BUTTON_GAP = 28, 4
BUTTONS = [        # (action, SF Symbol, fallback title, tooltip)
    ("back", "backward.end", "◀❙", "Step back one generation"),
    ("pause", "play", "▶", "Play"),  # one toggle: its face follows the state (see PLAY / PAUSE)
    ("faster", "forward", "▶▶", "Faster  (Option-click: slower)"),
    ("wallpaper", "pin", "📌", "Pin to desktop"),
    ("toggle", "xmark", "✕", "Hide panel"),  # pinned: eye-slash hides the panel; unpinned: ✕ (see _layout)
]
PLAY = ("play", "▶", "Play")
PAUSE = ("pause", "❚❚", "Pause")
UNPIN = ("pin.slash", "⊘", "Unpin from desktop")
LINES = 2          # Time, Population
LINE_H = 18
W = 8 + len(BUTTONS) * (BUTTON_W + BUTTON_GAP) - BUTTON_GAP + 8
H = 8 + LINES * LINE_H + 6 + 26 + 6
SMALL_W, SMALL_H = 44, 40   # unpinned with the panel hidden: just the eye button


def _screen_of(win):
    """The monitor under the middle of `win` (the wallpaper's monitor). Not just
    win.screen(): that can be None while macOS moves the window around (sleep, a monitor
    reconnecting), and NSScreen.mainScreen() is the monitor you're working on, not the
    wallpaper's."""
    f = win.frame()
    mid = (f.origin.x + f.size.width / 2, f.origin.y + f.size.height / 2)
    for screen in NSScreen.screens() or []:
        s = screen.frame()
        if (s.origin.x <= mid[0] < s.origin.x + s.size.width
                and s.origin.y <= mid[1] < s.origin.y + s.size.height):
            return screen
    return win.screen() or NSScreen.mainScreen()


def _screen_name(screen):
    """"LG ULTRAGEAR": the key for the panel's spot on that monitor."""
    try:
        return str(screen.localizedName())  # macOS 10.15+
    except AttributeError:
        f = screen.frame()
        return f"screen {int(f.origin.x)},{int(f.origin.y)}"


def _icon_level():
    """One above kCGDesktopIconWindowLevel: over the desktop icons, under app windows."""
    try:
        cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
        cg.CGWindowLevelForKey.restype = ctypes.c_int32
        cg.CGWindowLevelForKey.argtypes = [ctypes.c_int32]
        return cg.CGWindowLevelForKey(18) + 1
    except (OSError, TypeError, AttributeError):
        return -2147483603 + 1


class _HudButton(NSButton):
    def acceptsFirstMouse_(self, _event):
        return True  # act on the first click, without activating the app first


class _HudTarget(Foundation.NSObject):
    def clicked_(self, sender):
        action = BUTTONS[sender.tag()][0]
        if action == "toggle":
            self.hud.toggle()
            return
        if action == "faster" and AppKit.NSEvent.modifierFlags() & AppKit.NSEventModifierFlagOption:
            action = "slower"
        self.on_action(action)


class _HudMoved(Foundation.NSObject):
    def moved_(self, _note):
        self.hud._moved()


class Hud:
    """`on_action(name)` is called with "back", "pause", "faster", "slower"
    or "wallpaper" (on the main thread, while SDL pumps events, like the global hotkeys).
    `spots` is where the user left the panel on each monitor ({monitor name: (dx, dy)}
    from its top-left corner, as saved in the settings file); `on_moved(spots)` is told
    after every drag, to save them."""

    def __init__(self, on_action, spots=None, on_moved=None):
        self.panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H),
            AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel,
            AppKit.NSBackingStoreBuffered, False)
        p = self.panel
        p.setLevel_(_icon_level())
        p.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                                 | AppKit.NSWindowCollectionBehaviorStationary
                                 | AppKit.NSWindowCollectionBehaviorIgnoresCycle)
        p.setHidesOnDeactivate_(False)  # the app is (almost) never active
        p.setBecomesKeyOnlyIfNeeded_(True)
        p.setOpaque_(False)
        p.setBackgroundColor_(NSColor.clearColor())
        p.setHasShadow_(False)
        p.setReleasedWhenClosed_(False)
        p.setMovableByWindowBackground_(True)  # drag the panel by its background / labels

        self.spots = dict(spots or {})  # where the user dragged it, per monitor: {name: (dx, dy)} from its top-left
        self.on_moved = on_moved or (lambda _spots: None)
        self.screen_name = None  # the monitor it was last placed on
        self.placing = False   # True while we move it ourselves, so that isn't taken for a drag
        self.pinned = False
        self.hidden = False    # the user hid the panel: pinned, it vanishes; unpinned, only the eye stays
        self.w, self.h = W, H
        self.area = None       # the screen area the pinned panel was last placed in
        self.watcher = _HudMoved.alloc().init()
        self.watcher.hud = self
        Foundation.NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self.watcher, "moved:", AppKit.NSWindowDidMoveNotification, p)

        frame = AppKit.NSBox.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))
        frame.setBoxType_(4)        # NSBoxCustom: our own fill, border and corners
        frame.setTitlePosition_(0)  # NSNoTitle
        frame.setContentViewMargins_((0, 0))
        frame.setFillColor_(NSColor.colorWithWhite_alpha_(0.1, 0.72))
        frame.setBorderColor_(NSColor.colorWithWhite_alpha_(1.0, 0.55))
        frame.setBorderWidth_(1.0)
        frame.setCornerRadius_(6.0)
        p.setContentView_(frame)
        self.frame = frame
        box = frame.contentView()

        self.target = _HudTarget.alloc().init()
        self.target.on_action = on_action
        self.target.hud = self
        white = NSColor.whiteColor()
        self.buttons = {}
        for i, (action, symbol, title, tip) in enumerate(BUTTONS):
            b = _HudButton.alloc().initWithFrame_(
                NSMakeRect(8 + i * (BUTTON_W + BUTTON_GAP), H - 32, BUTTON_W, 26))
            b.setBordered_(False)
            self._set_face(b, symbol, title, tip)
            if hasattr(b, "setContentTintColor_"):
                b.setContentTintColor_(white)
            b.setTag_(i)
            b.setTarget_(self.target)
            b.setAction_("clicked:")
            box.addSubview_(b)
            self.buttons[action] = b

        font = AppKit.NSFont.monospacedDigitSystemFontOfSize_weight_(13, 0.0)
        self.labels = []
        for k in range(LINES):  # top to bottom
            label = AppKit.NSTextField.labelWithString_("")
            label.setFrame_(NSMakeRect(10, 8 + (LINES - 1 - k) * LINE_H, W - 16, LINE_H))
            label.setFont_(font)
            label.setTextColor_(white)
            box.addSubview_(label)
            self.labels.append(label)
        self.shown = None     # what the panel shows
        self.parent = None    # the game window, while attached to it (unpinned)

    @staticmethod
    def _set_face(button, symbol, title, tip):
        image = None
        if hasattr(AppKit.NSImage, "imageWithSystemSymbolName_accessibilityDescription_"):
            image = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, tip)
        if image is not None:
            button.setImage_(image)
            button.setImagePosition_(1)  # NSImageOnly
            button.setTitle_("")
        else:
            button.setTitle_(title)
        button.setToolTip_(tip)

    def place(self, win, pinned):
        """Pinned: the top-left corner of `win`'s screen, below the menu bar, above the
        desktop icons. Unpinned: the top-left corner of `win` (the game window), riding
        along with it as a child window."""
        # The same spot pinned or not: the screen's top-left corner, below the menu bar
        # (or wherever the user dragged it).
        screen = _screen_of(win)
        if screen is None:
            return
        # Each monitor keeps its own spot, so a trip to another monitor (macOS moves the
        # wallpaper while one is slow to wake) doesn't lose it.
        self.area = screen.visibleFrame()
        self.screen_name = _screen_name(screen)
        if pinned:
            self._detach()
            self.panel.setLevel_(_icon_level())
        else:
            self.panel.setLevel_(win.level())
            if self.parent is not win:
                self._detach()
                win.addChildWindow_ordered_(self.panel, AppKit.NSWindowAbove)
                self.parent = win
        self.pinned = pinned
        self._layout()
        self._position()

    def _position(self):
        if self.area is None:
            return
        dx, dy = self.spots.get(self.screen_name, (MARGIN, MARGIN))
        # Still fully on screen if the monitor is now smaller, or the Dock / menu bar grew.
        dx = max(0, min(dx, self.area.size.width - self.w))
        dy = max(0, min(dy, self.area.size.height - self.h))
        origin = (self.area.origin.x + dx, self.area.origin.y + self.area.size.height - dy - self.h)
        self.placing = True
        try:
            self.panel.setFrameOrigin_(origin)
        finally:
            self.placing = False

    def _moved(self):
        """The user dragged the pinned panel: remember where, relative to the screen's top-left."""
        if self.placing or self.area is None:
            return
        o = self.panel.frame().origin
        self.spots[self.screen_name] = (round(o.x - self.area.origin.x),
                                        round(self.area.origin.y + self.area.size.height - o.y - self.h))
        self.on_moved(dict(self.spots))

    def _detach(self):
        if self.parent is not None:
            self.parent.removeChildWindow_(self.panel)
            self.parent = None

    def toggle(self):
        """The ✕ (pinned) or eye (unpinned) button: hide the panel, or bring it back."""
        self.hidden = not self.hidden
        self._layout()
        self._position()
        self._order()
        self.panel.displayIfNeeded()

    def _order(self):
        if self.pinned and self.hidden:
            self.panel.orderOut_(None)
        else:
            self.panel.orderFrontRegardless()

    def _layout(self):
        """Full panel, or just the eye button (unpinned and hidden); sets the toggle's face."""
        small = self.hidden and not self.pinned
        self.w, self.h = (SMALL_W, SMALL_H) if small else (W, H)
        self.placing = True  # resizing moves the window's origin: not a drag
        try:
            self.panel.setContentSize_((self.w, self.h))
        finally:
            self.placing = False
        self.frame.setFrame_(NSMakeRect(0, 0, self.w, self.h))
        for action, b in self.buttons.items():
            if action != "toggle":
                b.setHidden_(small)
        for label in self.labels:
            label.setHidden_(small)
        t = self.buttons["toggle"]
        i = len(BUTTONS) - 1
        if small:
            t.setFrame_(NSMakeRect((SMALL_W - BUTTON_W) / 2, (SMALL_H - 26) / 2, BUTTON_W, 26))
            self._set_face(t, "eye", "👁", "Show panel")
        else:
            t.setFrame_(NSMakeRect(8 + i * (BUTTON_W + BUTTON_GAP), H - 32, BUTTON_W, 26))
            if self.pinned:
                self._set_face(t, "eye.slash", "👁", "Hide panel")
            else:
                self._set_face(t, "xmark", "✕", "Hide panel")

    def show(self, win, pinned):
        self.place(win, pinned)
        self._order()

    def hide(self):
        self._detach()
        self.panel.orderOut_(None)

    def update(self, time, population, paused, status, pinned, can_back):
        state = (time, population, paused, status, pinned, can_back)
        if state == self.shown:
            return
        if self.shown is None or self.shown[4] != pinned:
            self._set_face(self.buttons["wallpaper"], *(UNPIN if pinned else BUTTONS[3][1:]))
        if self.shown is None or self.shown[2] != paused:
            self._set_face(self.buttons["pause"], *(PLAY if paused else PAUSE))
        self.shown = state
        self.labels[0].setStringValue_(f"Time: {time}")
        self.labels[1].setStringValue_(f"Population: {population}")
        self.buttons["back"].setEnabled_(can_back)
        self.panel.displayIfNeeded()  # the main thread sleeps between pumps: draw now

    def close(self):
        Foundation.NSNotificationCenter.defaultCenter().removeObserver_(self.watcher)
        self._detach()
        self.panel.orderOut_(None)
        self.panel.close()
