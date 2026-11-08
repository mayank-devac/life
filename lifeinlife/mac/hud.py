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
INSET = 12         # gap to the game window's top-left corner (unpinned)
BUTTON_W, BUTTON_GAP = 28, 4
BUTTONS = [        # (action, SF Symbol, fallback title, tooltip)
    ("back", "backward.end", "◀❙", "Step back one generation"),
    ("pause", "play", "▶", "Play"),  # one toggle: its face follows the state (see PLAY / PAUSE)
    ("faster", "forward", "▶▶", "Faster  (Option-click: slower)"),
    ("wallpaper", "pin", "📌", "Pin to desktop"),
]
PLAY = ("play", "▶", "Play")
PAUSE = ("pause", "❚❚", "Pause")
UNPIN = ("pin.slash", "✕", "Unpin from desktop")
LINES = 2          # Time, Population
LINE_H = 18
W = 8 + len(BUTTONS) * (BUTTON_W + BUTTON_GAP) - BUTTON_GAP + 8
H = 8 + LINES * LINE_H + 6 + 26 + 6


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
        if action == "faster" and AppKit.NSEvent.modifierFlags() & AppKit.NSEventModifierFlagOption:
            action = "slower"
        self.on_action(action)


class Hud:
    """`on_action(name)` is called with "back", "pause", "faster", "slower"
    or "wallpaper" (on the main thread, while SDL pumps events, like the global hotkeys)."""

    def __init__(self, on_action):
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

        frame = AppKit.NSBox.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))
        frame.setBoxType_(4)        # NSBoxCustom: our own fill, border and corners
        frame.setTitlePosition_(0)  # NSNoTitle
        frame.setContentViewMargins_((0, 0))
        frame.setFillColor_(NSColor.colorWithWhite_alpha_(0.1, 0.72))
        frame.setBorderColor_(NSColor.colorWithWhite_alpha_(1.0, 0.55))
        frame.setBorderWidth_(1.0)
        frame.setCornerRadius_(6.0)
        p.setContentView_(frame)
        box = frame.contentView()

        self.target = _HudTarget.alloc().init()
        self.target.on_action = on_action
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
        if pinned:
            self._detach()
            self.panel.setLevel_(_icon_level())
            screen = win.screen() or NSScreen.mainScreen()
            if screen is None:
                return
            area, margin = screen.visibleFrame(), MARGIN
        else:
            area, margin = win.frame(), INSET
            self.panel.setLevel_(win.level())
            if self.parent is not win:
                self._detach()
                win.addChildWindow_ordered_(self.panel, AppKit.NSWindowAbove)
                self.parent = win
        self.panel.setFrameOrigin_((area.origin.x + margin,
                                    area.origin.y + area.size.height - margin - H))

    def _detach(self):
        if self.parent is not None:
            self.parent.removeChildWindow_(self.panel)
            self.parent = None

    def show(self, win, pinned):
        self.place(win, pinned)
        self.panel.orderFrontRegardless()

    def hide(self):
        self._detach()
        self.panel.orderOut_(None)

    def update(self, time, population, paused, status, pinned, can_back):
        state = (time, population, paused, status, pinned, can_back)
        if state == self.shown:
            return
        if self.shown is None or self.shown[4] != pinned:
            self._set_face(self.buttons["wallpaper"], *(UNPIN if pinned else BUTTONS[-1][1:]))
        if self.shown is None or self.shown[2] != paused:
            self._set_face(self.buttons["pause"], *(PLAY if paused else PAUSE))
        self.shown = state
        self.labels[0].setStringValue_(f"Time: {time}")
        self.labels[1].setStringValue_(f"Population: {population}")
        self.buttons["back"].setEnabled_(can_back)
        self.panel.displayIfNeeded()  # the main thread sleeps between pumps: draw now

    def close(self):
        self._detach()
        self.panel.orderOut_(None)
        self.panel.close()
