"""Cells the size of the mouse pointer: when --grid isn't given, the number of cells across
is picked so one cell is about as big as the pointer (System Settings > Accessibility >
Display > Pointer size). Nothing here imports pygame."""
import ctypes
import ctypes.util
import subprocess
import sys

from .config import MAX_POINTER_GRID, MIN_GRID, POINTER_PT


def _saved_scale():
    """The saved Pointer size setting, or None if there is none (never changed) or it can't
    be read. A public, stable read: works on every macOS version."""
    try:
        out = subprocess.run(["defaults", "read", "com.apple.universalaccess",
                              "mouseDriverCursorSize"],
                             capture_output=True, text=True, timeout=2).stdout
        return float(out.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _live_scale():
    """The pointer scale the window server is using right now, or None. CGSGetCursorScale is
    a private call (it may go away in a later macOS), so it's only the fallback."""
    if sys.platform != "darwin":
        return None
    try:
        cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
        cg.CGSMainConnectionID.restype = ctypes.c_int
        cg.CGSGetCursorScale.restype = ctypes.c_int
        cg.CGSGetCursorScale.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_float)]
        scale = ctypes.c_float(0.0)  # it writes a 32-bit float, not a CGFloat
        if cg.CGSGetCursorScale(cg.CGSMainConnectionID(), ctypes.byref(scale)) != 0:
            return None
        return scale.value
    except (OSError, TypeError, AttributeError):
        return None


def pointer_scale():
    """macOS's pointer size: 1.0 (normal) up to 4.0. The saved setting first, then the
    window server's live value, then 1.0 if neither gives a sensible number."""
    for read in (_saved_scale, _live_scale):
        scale = read()
        if scale is not None and 1.0 <= scale <= 4.0:
            return scale
    return 1.0


def pointer_grid(points, scale):
    """Cells across a window `points` wide (its longer side) so each is about pointer-sized,
    kept between MIN_GRID and MAX_POINTER_GRID."""
    return max(MIN_GRID, min(MAX_POINTER_GRID, round(points / (POINTER_PT * scale))))
