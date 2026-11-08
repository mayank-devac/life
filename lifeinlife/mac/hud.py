"""A small clickable panel shown while pinned: play / pause / step, time and population.

The pinned wallpaper window ignores the mouse (clicks go through to the desktop), so the
buttons live in their own little window, one level above the desktop icons: clickable,
but still below every normal app window, like a desktop widget."""
import ctypes
import ctypes.util
import importlib

# pyobjc loads these names lazily, so static checkers can't see them in a `from AppKit
# import ...`; importing the modules this way (as window.py does) keeps them quiet.
AppKit = importlib.import_module("AppKit")  # ImportError without pyobjc
Foundation = importlib.import_module("Foundation")
NSButton, NSColor, NSScreen = AppKit.NSButton, AppKit.NSColor, AppKit.NSScreen
NSMakeRect = AppKit.NSMakeRect

W, H = 140, 84     # panel size in points
MARGIN = 20        # gap to the screen's top-left corner (below the menu bar)
BUTTONS = [        # (action, SF Symbol, fallback title, tooltip)
    ("run", "play", "▶", "Play"),
    ("hold", "pause", "❚❚", "Pause"),
    ("step", "forward.end", "▶❙", "Step one generation"),
]


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
        self.on_action(BUTTONS[sender.tag()][0])


class Hud:
    """`on_action(name)` is called with "run", "hold" or "step" (on the main thread, while
    SDL pumps events, like the global hotkeys)."""

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
        self.buttons = []
        for i, (_, symbol, title, tip) in enumerate(BUTTONS):
            b = _HudButton.alloc().initWithFrame_(NSMakeRect(8 + i * 32, H - 32, 28, 26))
            b.setBordered_(False)
            image = None
            if hasattr(AppKit.NSImage, "imageWithSystemSymbolName_accessibilityDescription_"):
                image = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, tip)
            if image is not None:
                b.setImage_(image)
                b.setImagePosition_(1)  # NSImageOnly
                b.setTitle_("")
            else:
                b.setTitle_(title)
            if hasattr(b, "setContentTintColor_"):
                b.setContentTintColor_(white)
            b.setToolTip_(tip)
            b.setTag_(i)
            b.setTarget_(self.target)
            b.setAction_("clicked:")
            box.addSubview_(b)
            self.buttons.append(b)

        font = AppKit.NSFont.monospacedDigitSystemFontOfSize_weight_(14, 0.0)
        self.labels = []
        for y in (28, 8):
            label = AppKit.NSTextField.labelWithString_("")
            label.setFrame_(NSMakeRect(10, y, W - 16, 20))
            label.setFont_(font)
            label.setTextColor_(white)
            box.addSubview_(label)
            self.labels.append(label)
        self.shown = None  # what the panel shows: (time, population, paused)

    def place(self, screen=None):
        """Put the panel in the top-left corner of `screen` (an NSScreen), below the menu bar."""
        screen = screen or NSScreen.mainScreen()
        if screen is None:
            return
        area = screen.visibleFrame()
        self.panel.setFrameOrigin_((area.origin.x + MARGIN,
                                    area.origin.y + area.size.height - MARGIN - H))

    def show(self, screen=None):
        self.place(screen)
        self.panel.orderFrontRegardless()

    def hide(self):
        self.panel.orderOut_(None)

    def update(self, time, population, paused):
        state = (time, population, paused)
        if state == self.shown:
            return
        self.shown = state
        self.labels[0].setStringValue_(f"Time: {time}")
        self.labels[1].setStringValue_(f"Population: {population}")
        self.buttons[0].setEnabled_(paused)       # play: only when paused
        self.buttons[1].setEnabled_(not paused)   # pause: only when running
        self.panel.displayIfNeeded()  # the main thread sleeps between pumps: draw now

    def close(self):
        self.panel.orderOut_(None)
        self.panel.close()
