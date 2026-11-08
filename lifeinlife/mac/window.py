"""The NSWindow properties pygame can't reach: per-pixel transparency, pinning behind the
desktop icons, and the list of monitors."""
import ctypes
import ctypes.util
import importlib

from ..config import MAC_KEYCODES
from .hotkeys import CarbonHotkeys


def _desktop_level():
    """CGWindowLevelForKey(kCGDesktopWindowLevelKey): just above the wallpaper, below the icons."""
    try:
        cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
        cg.CGWindowLevelForKey.restype = ctypes.c_int32
        cg.CGWindowLevelForKey.argtypes = [ctypes.c_int32]
        return cg.CGWindowLevelForKey(2)
    except (OSError, TypeError, AttributeError):
        return -2147483623


def mac_screens():
    """macOS monitors as [(name, NSRect frame in points)], primary (menu-bar) screen first.
    Returns None when AppKit (pyobjc) isn't available."""
    try:
        AppKit = importlib.import_module("AppKit")
    except ImportError:
        return None
    screens = []
    for i, s in enumerate(AppKit.NSScreen.screens()):
        try:
            name = s.localizedName()  # macOS 10.15+
        except AttributeError:
            name = f"Display {i + 1}"
        screens.append((name, s.frame()))
    return screens


def frame_key(frame):
    """An NSRect as a plain tuple, so frames can be compared."""
    return (frame.origin.x, frame.origin.y, frame.size.width, frame.size.height)


class MacWindow:
    def __init__(self):
        self.AppKit = importlib.import_module("AppKit")  # ImportError without pyobjc
        self.app = self.AppKit.NSApplication.sharedApplication()
        # Backup for SDL builds that ignore SDL_MAC_BACKGROUND_APP: no Dock icon, no app menu.
        self.app.setActivationPolicy_(self.AppKit.NSApplicationActivationPolicyAccessory)
        windows = [w for w in self.app.windows() if w.isVisible()] or list(self.app.windows())
        if not windows:
            raise RuntimeError("couldn't find the game window")
        self.win = windows[0]
        self.normal = (self.win.level(), self.win.collectionBehavior(), self.win.hasShadow())
        self.hotkeys = None
        self.pinned = False
        self._fixed_layer = None

    def make_transparent(self):
        """Let pixels with alpha < 255 show the desktop through (per-pixel transparency)."""
        self.win.setOpaque_(False)
        self.win.setBackgroundColor_(self.AppKit.NSColor.clearColor())
        self.win.setHasShadow_(False)
        self.normal = (self.normal[0], self.normal[1], False)

        self.keep_transparent(force=True)

    def keep_transparent(self, force=False):
        """macOS creates the content view's backing layer lazily, after the first frame,
        and gives it an opaque black background, which hides the wallpaper behind it.
        Called every frame; it only does work when that layer has been (re)created.
        Returns True when it did, so the caller knows to redraw."""
        root = self.win.contentView().layer()
        if not force and (root is None or root is self._fixed_layer):
            return False
        self._fixed_layer = root

        def walk(view):
            layer = view.layer()
            if layer is not None:
                layer.setOpaque_(False)  # SDL's Metal layer is opaque by default
                layer.setBackgroundColor_(None)
            for sub in view.subviews():
                walk(sub)

        walk(self.win.contentView())
        return True

    def frame(self):
        return self.win.frame()

    def set_frame(self, frame):
        """Move/resize the window to `frame` (an NSRect in points). SDL notices and sends
        a WINDOWSIZECHANGED event, which is where the app picks up the new size."""
        self.win.setFrame_display_(frame, True)

    def pin(self, frame=None):
        """Pin behind the desktop icons. `frame` (an NSRect) resizes the window to cover a screen."""
        A, w = self.AppKit, self.win
        w.setLevel_(_desktop_level())
        w.setCollectionBehavior_(
            A.NSWindowCollectionBehaviorCanJoinAllSpaces    # show on every Space
            | A.NSWindowCollectionBehaviorStationary        # don't move in Mission Control
            | A.NSWindowCollectionBehaviorIgnoresCycle      # skip in Cmd+`
        )
        w.setIgnoresMouseEvents_(True)  # clicks go straight through to the desktop
        w.setHasShadow_(False)
        if frame is not None:
            self.set_frame(frame)
        w.orderFrontRegardless()
        self.pinned = True

    def unpin(self):
        level, behavior, shadow = self.normal
        w = self.win
        w.setLevel_(level)
        w.setCollectionBehavior_(behavior)
        w.setIgnoresMouseEvents_(False)
        w.setHasShadow_(shadow)
        try:
            self.app.activate()
        except AttributeError:  # macOS < 14
            self.app.activateIgnoringOtherApps_(True)
        w.makeKeyAndOrderFront_(None)
        self.pinned = False

    def watch_hotkeys(self, on_action):
        """Catch Ctrl+Shift+Esc / Ctrl+Shift+W typed in other apps while pinned. No permission needed."""
        if self.hotkeys is None:
            self.hotkeys = CarbonHotkeys(MAC_KEYCODES, on_action)
        self.hotkeys.register()

    def unwatch_hotkeys(self):
        """Release the shortcuts so other apps get them back."""
        if self.hotkeys is not None:
            self.hotkeys.unregister()

    def close(self):
        if self.hotkeys is not None:
            self.hotkeys.close()
            self.hotkeys = None
