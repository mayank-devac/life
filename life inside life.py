"""Life in Life: Conway's Game of Life where every live cell holds another Game of Life.

Run:
    python "life inside life.py"              # transparent floating window: only the cells show
    python "life inside life.py" --wallpaper  # live wallpaper behind your desktop icons (macOS)

Needs pygame-ce and numpy. On macOS, pyobjc-framework-Cocoa adds the transparent
background and wallpaper mode. Shortcuts: see HELP below, or Ctrl+Shift+H in the window.
"""
import argparse
import ctypes
import ctypes.util
import importlib
import math
import os
import signal
import sys
import time

import numpy as np

# macOS: run as a background app, with no Dock icon and no "Python" menu in the menu bar.
# SDL reads this hint before it creates the app, so the icon never appears.
os.environ.setdefault("SDL_MAC_BACKGROUND_APP", "1")
import pygame  # noqa: E402 - must come after the hint above
from pygame._sdl2.video import Renderer, Texture

# ---------------------------------------------------------------- settings
MACRO_SIZE = 64        # outer grid is MACRO_SIZE x MACRO_SIZE
MICRO_SIZE = 16        # inner grid inside every live outer cell
MACRO_EVERY = 15       # outer grid steps once every N frames
DETAIL_ZOOM = 2.2      # zoom level where the inner grids become visible
MIN_ZOOM, MAX_ZOOM = 1.0, 8.0
STALE_STEPS = 40       # reseed after this many outer steps with no real change
TEMPLATE_PX = 8        # pixels per inner cell in the inner-grid texture
MUTATION = 0.04        # how far a newborn's hue may drift from its parents'

SOLID_BG = (12, 12, 16, 255)
# Near-invisible background (alpha 3/255). macOS sends clicks on fully transparent
# pixels to whatever is behind the window, so this keeps drag/scroll working everywhere.
CLICKABLE_BG = (0, 0, 0, 3)
CLEAR_BG = (0, 0, 0, 0)
TEXT = (225, 230, 240)
TEXT_DIM = (140, 150, 170)

HELP = [
    ("Ctrl+Shift + drag", "move window"),
    ("Drag", "pan (when zoomed in)"),
    ("Scroll  /  Ctrl+Shift + = -", "zoom"),
    ("Ctrl+Shift + Up / Down", "opacity"),
    ("Ctrl+Shift + Space", "pause / resume"),
    ("Ctrl+Shift + R", "new random world"),
    ("Ctrl+Shift + W", "pin to desktop (wallpaper)"),
    ("Ctrl+Shift + H", "show / hide help"),
    ("Ctrl+Shift + Esc", "quit"),
]

# Ctrl+Shift + <key> -> action. pygame keys are used while the window has focus.
PYGAME_KEYS = {
    pygame.K_ESCAPE: "quit",
    pygame.K_w: "wallpaper",
    pygame.K_h: "help",
    pygame.K_SPACE: "pause",
    pygame.K_r: "reseed",
    pygame.K_UP: "opacity+",
    pygame.K_DOWN: "opacity-",
    pygame.K_EQUALS: "zoom+",
    pygame.K_PLUS: "zoom+",
    pygame.K_KP_PLUS: "zoom+",
    pygame.K_MINUS: "zoom-",
    pygame.K_KP_MINUS: "zoom-",
}
# The same shortcuts as macOS key codes, used while pinned (the window never has focus then).
MAC_KEYCODES = {53: "quit", 13: "wallpaper", 4: "help", 49: "pause", 15: "reseed",
                126: "opacity+", 125: "opacity-", 24: "zoom+", 27: "zoom-"}


# ---------------------------------------------------------------- life
def neighbor_sum(grid):
    """Sum of the 8 neighbours of every cell (edges wrap around)."""
    return sum(
        np.roll(np.roll(grid, i, 0), j, 1)
        for i in (-1, 0, 1) for j in (-1, 0, 1)
        if (i != 0 or j != 0)
    )


def step_life(grid):
    """Advance a 2D grid one generation."""
    n = neighbor_sum(grid)
    return ((n == 3) | ((grid == 1) & (n == 2))).astype(np.uint8)


def step_colored(grid, hue):
    """Step the outer grid. Every cell has its own hue; a newborn takes the
    average hue of its three parents plus a small random mutation, so colour
    families spread, mix and drift as the world evolves."""
    n = neighbor_sum(grid)
    new = ((n == 3) | ((grid == 1) & (n == 2))).astype(np.uint8)
    born = (new == 1) & (grid == 0)
    if born.any():
        angle = hue * 2 * np.pi
        cx = neighbor_sum(np.cos(angle) * grid)
        cy = neighbor_sum(np.sin(angle) * grid)
        parent_hue = (np.arctan2(cy, cx) / (2 * np.pi)) % 1.0
        drift = np.random.uniform(-MUTATION, MUTATION, hue.shape)
        hue = np.where(born, (parent_hue + drift) % 1.0, hue)
    return new, hue


def hue_to_rgb(hue, s=0.7, v=1.0):
    """Vectorised HSV -> RGB (uint8) for an array of hues in [0, 1)."""
    h6 = hue * 6.0
    i = np.floor(h6).astype(int) % 6
    f = h6 - np.floor(h6)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return (np.stack([r, g, b], axis=-1) * 255).astype(np.uint8)


NAMED_COLORS = {
    "white": (255, 255, 255), "black": (0, 0, 0), "gray": (128, 128, 128),
    "red": (235, 64, 52), "orange": (245, 150, 40), "yellow": (245, 220, 60),
    "green": (70, 200, 90), "cyan": (60, 210, 230), "blue": (60, 120, 240),
    "purple": (150, 90, 230), "pink": (240, 110, 180),
}


def parse_color(text):
    """'multi' -> None (every cell its own hue), a name like 'white', or a hex like '#ff8800'."""
    text = text.strip().lower()
    if text in ("multi", "multicolor", "rainbow", ""):
        return None
    if text in NAMED_COLORS:
        return NAMED_COLORS[text]
    hexa = text.lstrip("#")
    if len(hexa) == 6:
        try:
            return tuple(int(hexa[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            pass
    raise argparse.ArgumentTypeError(
        f"unknown colour {text!r}: use multi, {', '.join(NAMED_COLORS)}, or a hex like #ff8800")


def random_macro():
    grid = np.random.choice([0, 1], size=(MACRO_SIZE, MACRO_SIZE), p=[0.7, 0.3]).astype(np.uint8)
    hue = np.random.random((MACRO_SIZE, MACRO_SIZE))
    return grid, hue


def seed_micro():
    """Two gliders travelling side by side, so the inner world never dies out."""
    grid = np.zeros((MICRO_SIZE, MICRO_SIZE), dtype=np.uint8)
    for r, c in [(1, 2), (2, 3), (3, 1), (3, 2), (3, 3)]:
        grid[r, c] = 1
        grid[r + 7, c + 7] = 1
    return grid


def micro_surface(micro):
    """The inner grid as a white image with transparent gaps; tinted per cell when drawn."""
    k = TEMPLATE_PX
    mask = np.kron(micro, np.ones((k, k), dtype=np.uint8))
    mask[k - 1::k, :] = 0
    mask[:, k - 1::k] = 0
    surf = pygame.Surface(mask.shape[::-1], pygame.SRCALPHA)
    surf.fill((255, 255, 255, 0))
    alpha = pygame.surfarray.pixels_alpha(surf)
    alpha[:] = mask.T * 255  # surfarray is (x, y)
    del alpha  # unlock the surface
    return surf


# ---------------------------------------------------------------- camera
class View:
    """Zoom + pan in pixels. The grid always covers the whole window."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.base = max(w, h) / MACRO_SIZE
        self.zoom = 1.0
        self.ox = (w - self.grid_px) / 2
        self.oy = (h - self.grid_px) / 2

    @property
    def cell(self):
        return self.base * self.zoom

    @property
    def grid_px(self):
        return self.cell * MACRO_SIZE

    def _clamp(self):
        self.ox = min(0.0, max(self.w - self.grid_px, self.ox))
        self.oy = min(0.0, max(self.h - self.grid_px, self.oy))

    def zoom_at(self, factor, mx, my):
        """Zoom while keeping the point under (mx, my) fixed."""
        new = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom * factor))
        f = new / self.zoom
        self.ox = mx - (mx - self.ox) * f
        self.oy = my - (my - self.oy) * f
        self.zoom = new
        self._clamp()

    def pan(self, dx, dy):
        self.ox += dx
        self.oy += dy
        self._clamp()


# ---------------------------------------------------------------- macOS window tweaks
def _desktop_level():
    """CGWindowLevelForKey(kCGDesktopWindowLevelKey): just above the wallpaper, below the icons."""
    try:
        cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
        cg.CGWindowLevelForKey.restype = ctypes.c_int32
        cg.CGWindowLevelForKey.argtypes = [ctypes.c_int32]
        return cg.CGWindowLevelForKey(2)
    except (OSError, TypeError, AttributeError):
        return -2147483623


def _fourcc(code):
    return int.from_bytes(code.encode(), "big")


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


_HOTKEY_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)


class CarbonHotkeys:
    """System-wide Ctrl+Shift shortcuts via Carbon's RegisterEventHotKey.
    Unlike an NSEvent global monitor, this needs no Accessibility permission."""

    CONTROL, SHIFT = 0x1000, 0x0200  # Carbon modifier bits (controlKey, shiftKey)

    def __init__(self, on_action):
        c = self.carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
        c.GetApplicationEventTarget.restype = ctypes.c_void_p
        c.InstallEventHandler.argtypes = [ctypes.c_void_p, _HOTKEY_HANDLER, ctypes.c_ulong,
                                          ctypes.POINTER(_EventTypeSpec), ctypes.c_void_p,
                                          ctypes.POINTER(ctypes.c_void_p)]
        c.InstallEventHandler.restype = ctypes.c_int32
        c.RemoveEventHandler.argtypes = [ctypes.c_void_p]
        c.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, _EventHotKeyID,
                                          ctypes.c_void_p, ctypes.c_uint32,
                                          ctypes.POINTER(ctypes.c_void_p)]
        c.RegisterEventHotKey.restype = ctypes.c_int32
        c.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
        c.GetEventParameter.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p,
                                        ctypes.c_void_p]
        c.GetEventParameter.restype = ctypes.c_int32

        self.target = c.GetApplicationEventTarget()
        self.signature = _fourcc("LiLf")
        self.keycodes = list(MAC_KEYCODES)
        self.refs = []

        def handler(_call, event, _data):
            hk = _EventHotKeyID()
            if c.GetEventParameter(event, _fourcc("----"), _fourcc("hkid"), None,
                                   ctypes.sizeof(hk), None, ctypes.byref(hk)) == 0:
                if hk.signature == self.signature and hk.id < len(self.keycodes):
                    on_action(MAC_KEYCODES[self.keycodes[hk.id]])
            return 0

        self._handler = _HOTKEY_HANDLER(handler)  # keep a reference so it isn't freed
        spec = _EventTypeSpec(_fourcc("keyb"), 5)  # kEventClassKeyboard, kEventHotKeyPressed
        self.handler_ref = ctypes.c_void_p()
        if c.InstallEventHandler(self.target, self._handler, 1, ctypes.byref(spec), None,
                                 ctypes.byref(self.handler_ref)) != 0:
            raise OSError("InstallEventHandler failed")

    def register(self):
        if self.refs:
            return
        for i, code in enumerate(self.keycodes):
            ref = ctypes.c_void_p()
            if self.carbon.RegisterEventHotKey(code, self.CONTROL | self.SHIFT,
                                               _EventHotKeyID(self.signature, i), self.target,
                                               0, ctypes.byref(ref)) == 0:
                self.refs.append(ref)

    def unregister(self):
        for ref in self.refs:
            self.carbon.UnregisterEventHotKey(ref)
        self.refs = []

    def close(self):
        self.unregister()
        if self.handler_ref:
            self.carbon.RemoveEventHandler(self.handler_ref)
            self.handler_ref = ctypes.c_void_p()


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


def list_monitors():
    screens = mac_screens()
    if screens:
        for i, (name, f) in enumerate(screens, 1):
            tag = "  (primary)" if i == 1 else ""
            print(f"  {i}: {name}  {int(f.size.width)}x{int(f.size.height)}{tag}")
        return
    pygame.init()
    for i, (w, h) in enumerate(pygame.display.get_desktop_sizes(), 1):
        print(f"  {i}: {w}x{h}{'  (primary)' if i == 1 else ''}")
    pygame.quit()


class MacWindow:
    """Uses pyobjc to set the NSWindow properties pygame can't reach."""

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
        Called every frame; it only does work when that layer has been (re)created."""
        root = self.win.contentView().layer()
        if not force and (root is None or root is self._fixed_layer):
            return
        self._fixed_layer = root

        def walk(view):
            layer = view.layer()
            if layer is not None:
                layer.setOpaque_(False)  # SDL's Metal layer is opaque by default
                layer.setBackgroundColor_(None)
            for sub in view.subviews():
                walk(sub)

        walk(self.win.contentView())

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
            w.setFrame_display_(frame, True)
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
        """Catch Ctrl+Shift shortcuts typed in other apps while pinned. No permission needed."""
        if self.hotkeys is None:
            self.hotkeys = CarbonHotkeys(on_action)
        self.hotkeys.register()

    def unwatch_hotkeys(self):
        """Release the shortcuts so other apps get Ctrl+Shift+R etc. back."""
        if self.hotkeys is not None:
            self.hotkeys.unregister()

    def close(self):
        if self.hotkeys is not None:
            self.hotkeys.close()
            self.hotkeys = None


# ---------------------------------------------------------------- app
class LifeInLife:
    def __init__(self, args):
        pygame.init()
        self.screen_frame = None  # NSRect of the monitor the wallpaper covers
        if args.wallpaper:
            size, pos = self._pick_monitor(args.monitor), (0, 0)
        else:
            size, pos = (args.size, args.size), pygame.WINDOWPOS_CENTERED
        # borderless: no title bar or buttons. allow_high_dpi: draw at full Retina resolution.
        self.window = pygame.Window("Life in Life", size, pos, borderless=True, allow_high_dpi=True)
        self.renderer = Renderer(self.window)
        self.renderer.draw_blend_mode = pygame.BLENDMODE_BLEND
        # Pixel size of the drawing area vs. window size in points (2.0 on Retina screens)
        px_w, px_h = self.renderer.get_viewport().size
        self.dpr = px_w / size[0]
        self.view = View(px_w, px_h)
        self.view.zoom_at(args.zoom, px_w / 2, px_h / 2)  # start-up scale

        self.opacity = max(0.1, min(1.0, args.opacity))
        self.window.opacity = self.opacity
        self.bg_alpha = round(max(0.0, min(1.0, args.bg_opacity)) * 255)
        self.clock = pygame.time.Clock()
        self.fps = args.fps

        self.font = self.font_big = None
        try:
            self.font = pygame.font.Font(None, round(20 * self.dpr))
            self.font_big = pygame.font.Font(None, round(24 * self.dpr))
        except (NotImplementedError, ImportError, pygame.error):
            print("Note: pygame's font module is unavailable, so on-screen help is off.\n"
                  "      Fix: pip uninstall pygame && pip install pygame-ce")
        self.help_tex = None
        self.toast_tex, self.toast_tex_text = None, None

        self.color = args.color  # None = multicolour, else one (r, g, b) for every cell
        self.macro, self.hue = random_macro()
        self.rgb = self.colors()
        self.micro = seed_micro()
        self.history = []  # last two outer generations, for stall detection
        self.stale = 0
        self.tick = 0
        self.paused = False
        self.running = True
        self.show_help = not args.wallpaper
        self.help_until = time.monotonic() + 6  # start-up help fades away on its own
        self.toast_text, self.toast_until = "", 0.0
        self.drag_mode = None  # None | "move" | "pan"
        self.grab = (0, 0)     # where the window was grabbed, for "move"
        self.hovered = False
        self.pending = []      # actions coming from the global hotkey monitor

        # macOS: transparent background + wallpaper mode
        self.mac = None
        self.mac_error = None
        self.transparent = False
        if not args.solid:
            mac = self._get_mac()
            if mac is not None:
                mac.make_transparent()
                self.transparent = True
            else:
                print(f"Note: transparent background {self.mac_error}; using a dark background.")
        if args.wallpaper:
            mac = self._get_mac()
            if mac is None:
                pygame.quit()
                sys.exit(f"--wallpaper: {self.mac_error}")
            mac.pin(frame=self.screen_frame)
            self._start_global_hotkeys()

    # ---- helpers
    def _pick_monitor(self, number):
        """Size (in points) of monitor `number` (1 = primary). Remembers its frame for pinning."""
        screens = mac_screens()
        sizes = ([(int(f.size.width), int(f.size.height)) for _, f in screens] if screens
                 else pygame.display.get_desktop_sizes())
        index = number - 1
        if not 0 <= index < len(sizes):
            print(f"Note: monitor {number} not found ({len(sizes)} connected); using the primary one.\n"
                  f"      Run with --list-monitors to see them.")
            index = 0
        if screens:
            self.screen_frame = screens[index][1]
        return sizes[index]

    def _get_mac(self):
        if self.mac is None and self.mac_error is None:
            if sys.platform != "darwin":
                self.mac_error = "only works on macOS"
            else:
                try:
                    self.mac = MacWindow()
                except ImportError:
                    self.mac_error = "needs pyobjc  ->  pip install pyobjc-framework-Cocoa"
                except Exception as exc:  # noqa: BLE001 - report anything pyobjc throws
                    self.mac_error = f"failed ({exc})"
        return self.mac

    def _start_global_hotkeys(self):
        if self.mac is None:
            return
        try:
            self.mac.watch_hotkeys(self.pending.append)
        except (OSError, AttributeError) as exc:
            print(f"Note: global shortcuts unavailable ({exc}); Ctrl+C in this terminal quits.")

    @property
    def pinned(self):
        return self.mac is not None and self.mac.pinned

    def colors(self):
        """Per-cell RGB: from each cell's hue, or one fixed colour if --color was given."""
        if self.color is None:
            return hue_to_rgb(self.hue)
        return np.broadcast_to(np.array(self.color, dtype=np.uint8), (*self.hue.shape, 3))

    def toast(self, text, seconds=1.6):
        self.toast_text, self.toast_until = text, time.monotonic() + seconds
        if self.font is None:
            print(text)

    def reseed(self):
        self.macro, self.hue = random_macro()
        self.rgb = self.colors()
        self.micro = seed_micro()
        self.history.clear()
        self.stale = 0

    # ---- actions
    def do(self, action):
        if action == "quit":
            self.running = False
        elif action == "pause":
            self.paused = not self.paused
            self.toast("Paused" if self.paused else "Running")
        elif action == "reseed":
            self.reseed()
            self.toast("New world")
        elif action == "help":
            self.show_help = not self.show_help
            self.help_until = math.inf
        elif action in ("opacity+", "opacity-"):
            step = 0.1 if action == "opacity+" else -0.1
            self.opacity = round(max(0.1, min(1.0, self.opacity + step)), 2)
            self.window.opacity = self.opacity
            self.toast(f"Opacity {round(self.opacity * 100)}%")
        elif action in ("zoom+", "zoom-"):
            self.view.zoom_at(1.25 if action == "zoom+" else 0.8, self.view.w / 2, self.view.h / 2)
        elif action == "wallpaper":
            self.toggle_wallpaper()

    def toggle_wallpaper(self):
        mac = self._get_mac()
        if mac is None:
            self.toast(f"Wallpaper mode {self.mac_error}", 3.5)
            return
        self.drag_mode = None
        if mac.pinned:
            mac.unpin()
            mac.unwatch_hotkeys()
            self.toast("Interactive  -  Ctrl+Shift+W to pin again", 2.5)
        else:
            mac.pin()
            self._start_global_hotkeys()
            self.show_help = False
            self.toast("Pinned to desktop  -  Ctrl+Shift+W to unpin", 2.5)

    # ---- input
    def handle(self, event):
        if event.type == pygame.QUIT:  # Cmd+Q
            self.running = False

        elif event.type == pygame.KEYDOWN:
            chord = (event.mod & pygame.KMOD_CTRL) and (event.mod & pygame.KMOD_SHIFT)
            if chord and event.key in PYGAME_KEYS:
                self.do(PYGAME_KEYS[event.key])
            elif event.key == pygame.K_ESCAPE and self.show_help:
                self.show_help = False  # plain Esc just closes the help panel
            elif not chord and event.key in PYGAME_KEYS:
                self.toast("Shortcuts use Ctrl+Shift  -  Ctrl+Shift+H for help", 2.5)

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button in (1, 3):
            mods = pygame.key.get_mods()
            if (mods & pygame.KMOD_CTRL) and (mods & pygame.KMOD_SHIFT):
                # Remember where we grabbed; moving the window by event.rel jitters because
                # the window moving under the cursor feeds back into the next rel.
                self.drag_mode, self.grab = "move", event.pos
            elif event.button == 1:
                self.drag_mode = "pan"

        elif event.type == pygame.MOUSEBUTTONUP and event.button in (1, 3):
            self.drag_mode = None

        elif event.type == pygame.MOUSEMOTION and self.drag_mode == "move":
            wx, wy = self.window.position
            self.window.position = (wx + event.pos[0] - self.grab[0], wy + event.pos[1] - self.grab[1])

        elif event.type == pygame.MOUSEMOTION and self.drag_mode == "pan":
            self.view.pan(event.rel[0] * self.dpr, event.rel[1] * self.dpr)

        elif event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            self.view.zoom_at(1.12 ** event.precise_y, mx * self.dpr, my * self.dpr)

        elif event.type == pygame.WINDOWENTER:
            self.hovered = True
        elif event.type == pygame.WINDOWLEAVE:
            self.hovered = False
        elif event.type == pygame.WINDOWFOCUSLOST:
            self.drag_mode = None  # don't get stuck dragging if the button-up happened elsewhere

    # ---- simulation
    def update(self):
        if self.paused:
            return
        self.micro = step_life(self.micro)
        if self.tick % MACRO_EVERY == 0:
            self.macro, self.hue = step_colored(self.macro, self.hue)
            self.rgb = self.colors()
            snapshot = self.macro.tobytes()
            # Empty, frozen, or blinking in place (period 1 or 2): count it as stalled.
            self.stale = self.stale + 1 if (not self.macro.any() or snapshot in self.history) else 0
            self.history = (self.history + [snapshot])[-2:]
            if self.stale >= STALE_STEPS:
                self.reseed()
                self.toast("World settled  -  starting a new one")
        self.tick += 1

    # ---- drawing
    def draw(self):
        v, ren = self.view, self.renderer
        if not self.transparent:
            ren.draw_color = SOLID_BG
        elif self.bg_alpha > 0:
            ren.draw_color = (*SOLID_BG[:3], self.bg_alpha)  # tinted see-through backdrop
        elif self.pinned:
            ren.draw_color = CLEAR_BG
        else:
            ren.draw_color = CLICKABLE_BG
        ren.clear()

        cell = v.cell
        detail = v.zoom >= DETAIL_ZOOM
        # Only visit cells that are on screen
        c0, c1 = max(0, int(-v.ox // cell)), min(MACRO_SIZE, int((v.w - v.ox) // cell) + 1)
        r0, r1 = max(0, int(-v.oy // cell)), min(MACRO_SIZE, int((v.h - v.oy) // cell) + 1)

        if detail:
            inner = Texture.from_surface(ren, micro_surface(self.micro))
            inner.blend_mode = pygame.BLENDMODE_BLEND
            gap = max(1.0, self.dpr)
            for r in range(r0, r1):
                y = v.oy + r * cell
                for c in range(c0, c1):
                    if self.macro[r, c]:
                        x = v.ox + c * cell
                        rgb = self.rgb[r, c]
                        inner.color = rgb  # tint the inner life with its cell's colour
                        inner.draw(dstrect=(x, y, cell, cell))
                        ren.draw_color = (int(rgb[0]), int(rgb[1]), int(rgb[2]), 90)
                        ren.draw_rect((x, y, cell - gap, cell - gap))
        else:
            size = cell - max(1.0, self.dpr)  # leave a hairline gap between cells
            for r in range(r0, r1):
                y = v.oy + r * cell
                for c in range(c0, c1):
                    if self.macro[r, c]:
                        rgb = self.rgb[r, c]
                        ren.draw_color = (int(rgb[0]), int(rgb[1]), int(rgb[2]), 255)
                        ren.fill_rect((v.ox + c * cell, y, size, size))

        if self.transparent and self.hovered and not self.pinned:
            ren.draw_color = (255, 255, 255, 40)  # faint outline so you can see the window's edges
            ren.draw_rect((0, 0, v.w, v.h))

        now = time.monotonic()
        if self.show_help and now > self.help_until:
            self.show_help = False
        if self.font is not None:
            if self.show_help:
                self._draw_help()
            if now < self.toast_until:
                self._draw_toast()

        if self.transparent and self.mac is not None:
            self.mac.keep_transparent()
        ren.present()

    def _panel_surface(self, w, h):
        panel = pygame.Surface((w, h), pygame.SRCALPHA)
        radius = round(10 * self.dpr)
        pygame.draw.rect(panel, (8, 9, 14, 225), panel.get_rect(), border_radius=radius)
        pygame.draw.rect(panel, (70, 80, 100, 255), panel.get_rect(), max(1, round(self.dpr)),
                         border_radius=radius)
        return panel

    def _draw_help(self):
        font, font_big = self.font, self.font_big
        if font is None or font_big is None:
            return
        if self.help_tex is None:
            d = self.dpr
            pad, line_h, gap = round(16 * d), round(22 * d), round(24 * d)
            title = font_big.render("Life in Life", True, TEXT)
            keys = [font.render(k, True, TEXT) for k, _ in HELP]
            descs = [font.render(t, True, TEXT_DIM) for _, t in HELP]
            key_w = max(s.get_width() for s in keys)
            w = pad * 2 + key_w + gap + max(s.get_width() for s in descs)
            h = pad * 2 + title.get_height() + round(10 * d) + line_h * len(HELP)
            panel = self._panel_surface(w, h)
            panel.blit(title, (pad, pad))
            ty = pad + title.get_height() + round(10 * d)
            for i, (k, t) in enumerate(zip(keys, descs)):
                panel.blit(k, (pad, ty + i * line_h))
                panel.blit(t, (pad + key_w + gap, ty + i * line_h))
            self.help_tex = Texture.from_surface(self.renderer, panel)
        m = round(20 * self.dpr)
        self.help_tex.draw(dstrect=(m, m, self.help_tex.width, self.help_tex.height))

    def _draw_toast(self):
        if self.font_big is None:
            return
        if self.toast_tex is None or self.toast_tex_text != self.toast_text:
            d = self.dpr
            text = self.font_big.render(self.toast_text, True, TEXT)
            px, py = round(14 * d), round(8 * d)
            panel = self._panel_surface(text.get_width() + 2 * px, text.get_height() + 2 * py)
            panel.blit(text, (px, py))
            self.toast_tex = Texture.from_surface(self.renderer, panel)
            self.toast_tex_text = self.toast_text
        tw, th = self.toast_tex.width, self.toast_tex.height
        x, y = (self.view.w - tw) // 2, self.view.h - th - round(28 * self.dpr)
        self.toast_tex.draw(dstrect=(x, y, tw, th))

    # ---- main loop
    def run(self):
        # Ctrl+C in the terminal: exit the loop cleanly instead of a traceback
        signal.signal(signal.SIGINT, lambda *_: setattr(self, "running", False))
        try:
            while self.running:
                for event in pygame.event.get():  # also delivers the macOS global hotkeys
                    self.handle(event)
                while self.pending:
                    self.do(self.pending.pop(0))
                self.update()
                self.draw()
                self.clock.tick(self.fps)
        finally:
            if self.mac:
                self.mac.close()
            pygame.quit()


def parse_args():
    p = argparse.ArgumentParser(description="Conway's Game of Life inside Conway's Game of Life.")
    p.add_argument("--wallpaper", action="store_true",
                   help="macOS: run as a live wallpaper (behind desktop icons, on all Spaces, "
                        "click-through). Needs pyobjc-framework-Cocoa.")
    p.add_argument("--monitor", type=int, default=1,
                   help="with --wallpaper: which monitor to cover, 1 = primary (default), "
                        "2 = second, ... (see --list-monitors)")
    p.add_argument("--list-monitors", action="store_true",
                   help="print the connected monitors and their numbers, then exit")
    p.add_argument("--solid", action="store_true",
                   help="dark background instead of a transparent one")
    p.add_argument("--bg-opacity", type=float, default=0.0,
                   help="darkness of the background behind the cells, 0-1 "
                        "(default 0 = fully clear, your wallpaper shows through)")
    p.add_argument("--opacity", type=float, default=1.0,
                   help="opacity of the whole window, 0.1-1.0 (default 1.0)")
    p.add_argument("--size", type=int, default=800,
                   help="window size in points (default 800; --wallpaper always fills the screen)")
    p.add_argument("--zoom", type=float, default=1.0,
                   help=f"start-up scale {MIN_ZOOM:g}-{MAX_ZOOM:g}: bigger = larger cells "
                        f"(inner life shows from {DETAIL_ZOOM})")
    p.add_argument("--grid", type=int, default=MACRO_SIZE,
                   help=f"cells across the world (default {MACRO_SIZE}); fewer = bigger cells")
    p.add_argument("--fps", type=int, default=30, help="frames per second (default 30)")
    p.add_argument("--color", type=parse_color, default=None,
                   help=f"cell colour: multi (default, every cell its own hue), "
                        f"{', '.join(NAMED_COLORS)}, or a hex like #ff8800")
    return p.parse_args()


def main():
    global MACRO_SIZE
    args = parse_args()
    if args.list_monitors:
        print("Monitors:")
        list_monitors()
        return
    MACRO_SIZE = max(8, args.grid)
    print("Life in Life  -  shortcuts:")
    for keys, what in HELP:
        print(f"  {keys:<30} {what}")
    print("  Ctrl+C (in this terminal)      quit")
    LifeInLife(args).run()


if __name__ == "__main__":
    main()
