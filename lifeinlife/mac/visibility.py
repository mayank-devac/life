"""Can anyone see the window right now? If not, the app stops simulating and drawing.

Checked by polling (about once a second), which costs microseconds and needs no
notification observers:
    - the screen is locked, or another user is on the console (fast user switching)
    - the display the window is on is asleep

Not checked: being covered by other windows. NSWindow.occlusionState never reports
"visible" for this window (it runs as a background app with no Dock icon), so trusting
it would freeze the wallpaper for good. Tested on macOS 27 / SDL 2.32.
"""
import ctypes
import ctypes.util
import importlib


class Visibility:
    def __init__(self, nswindow):
        self.win = nswindow
        # pyobjc is optional, so it's imported on use; via importlib because static
        # checkers can't see its lazily created names (objc.objc_object).
        self._objc = importlib.import_module("objc")
        cg = self.cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
        cf = self.cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
        cg.CGSessionCopyCurrentDictionary.restype = ctypes.c_void_p
        cg.CGDisplayIsAsleep.argtypes = [ctypes.c_uint32]
        cg.CGDisplayIsAsleep.restype = ctypes.c_int32
        cf.CFRelease.argtypes = [ctypes.c_void_p]

    def _session(self):
        ptr = self.cg.CGSessionCopyCurrentDictionary()
        if not ptr:
            return {}
        try:
            return self._objc.objc_object(c_void_p=ptr)  # toll-free bridged to NSDictionary
        finally:
            self.cf.CFRelease(ptr)

    def _display_id(self):
        screen = self.win.screen()
        if screen is None:
            return None
        number = screen.deviceDescription().get("NSScreenNumber")
        return int(number) if number is not None else None

    def hidden_reason(self):
        """None when the window may be visible, else a short reason it can't be."""
        try:
            session = self._session()
            if session.get("CGSSessionScreenIsLocked"):
                return "screen locked"
            if session.get("kCGSSessionOnConsoleKey") is False:
                return "another user is active"
            display = self._display_id()
            if display is not None and self.cg.CGDisplayIsAsleep(display):
                return "display asleep"
        except Exception:  # noqa: BLE001 - never let a visibility probe crash the app
            return None
        return None
