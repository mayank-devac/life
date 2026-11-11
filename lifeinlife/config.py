"""Tunable constants. Nothing here imports pygame, so tests can use it freely."""

# ---------------------------------------------------------------- world
DEFAULT_GRID = 96      # outer grid is GRID x GRID (overridable with --grid)
MIN_GRID = 8
MICRO_SIZE = 16        # inner grid inside every outer cell (each cell has its own)
MACRO_EVERY = 15       # outer grid steps once every N frames (default: --speed 2 at 30 fps)
DEFAULT_SPEED = 15.0    # outer generations per second
SPEEDS = (0.5, 1, 2, 4, 8, 15, 30)  # choices in the Ctrl+Shift+S dialog
WINDOW_SIZES = (400, 500, 600, 700, 800, 1000, 1200, 1400, 1600)  # window sizes there, in points
STALE_STEPS = 40       # reseed after this many outer steps with no real change
HISTORY = 30           # a world repeating itself with any period up to this counts as settled
REWIND = 200           # outer generations you can step back through (and hand-made changes)
MUTATION = 0.04        # how far a newborn's hue may drift from its parents'
DENSITY = 0.3          # share of cells alive in a new random world
INNER_DENSITY = 0.35   # share of cells alive in a new random inner world
INNER_MUTATION = 0.02  # chance each inner cell flips when a newborn copies its parent's world

# ---------------------------------------------------------------- effects (Ctrl+Shift+F)
TRAIL_ALPHA = 0.45     # opacity of a cell's ghost right after it dies
TRAIL_DECAY = 0.6      # the ghost keeps this share of its opacity each outer step
TRAIL_MIN = 0.06       # below this the ghost is gone
AGE_DIM = 0.6          # brightness of a newborn cell; it brightens to 1.0 ...
AGE_FULL = 20          # ... over this many outer generations alive
FLASH = 0.5            # newborns are mixed this far towards white for one generation

# ---------------------------------------------------------------- view
DETAIL_ZOOM = 2.2      # zoom level where the inner grids become visible
MIN_ZOOM, MAX_ZOOM = 1.0, 8.0
ZOOM_EASE = 14.0       # smooth zoom: how fast it closes in on the target (1/s)
CLICK_SLOP = 4         # points the mouse may move and still count as a click (not a pan)
SAVE_DIR = "~/life-worlds"  # where Ctrl+Shift+X saves the world as .rle

# ---------------------------------------------------------------- main loop timing (seconds)
MAX_WAIT = 0.5         # longest sleep between wake-ups, so Ctrl+C / SIGTERM stay responsive
HOVER_IDLE = 0.1       # hover mode, mouse outside the window: how often to look for it
PINNED_WAIT = 0.25     # pinned: sleep slices, so global hotkeys answer within this long
HIDDEN_WAIT = 1.0      # how often to check again while nobody can see the window
SYSTEM_POLL = 1.0      # how often to check visibility (screen locked, display asleep)
SCREEN_POLL = 2.0      # how often to check for monitors being plugged in / resized
MONITOR_GRACE = 10.0   # chosen monitor gone (e.g. waking from sleep): wait this long for it
                       # to come back before falling back to the primary one

# ---------------------------------------------------------------- colours
SOLID_BG = (12, 12, 16, 255)
# Near-invisible background (alpha 3/255). macOS sends clicks on fully transparent
# pixels to whatever is behind the window, so this keeps drag/scroll working everywhere.
CLICKABLE_BG = (0, 0, 0, 3)
CLEAR_BG = (0, 0, 0, 0)
TEXT = (225, 230, 240)
TEXT_DIM = (140, 150, 170)
OUTLINE_ALPHA = 90     # outline around each outer cell when zoomed in

# ---------------------------------------------------------------- shortcuts
HELP = [
    ("Click  /  drag", "draw cells (start on a live one to erase)"),
    ("Right-drag  /  Option + drag", "pan (when zoomed in)"),
    ("Ctrl+Shift + drag", "move window"),
    ("Scroll  /  Ctrl+Shift + = -", "zoom"),
    ("Ctrl+Shift + P  /  T", "next brush (glider, gun...)  /  rotate it"),
    ("Ctrl+Shift + C", "clear the world"),
    ("Ctrl+Shift + Space", "pause / resume"),
    ("Ctrl+Shift + Left / Right", "step back / forward one generation"),
    ("Ctrl+Shift + ,  /  .", "slower / faster"),
    ("Ctrl+Shift + R", "new random world"),
    ("Ctrl+Shift + X", "save as .rle (drop a file here to load)"),
    ("Ctrl+Shift + L  /  I", "next rule: outer / inner worlds"),
    ("Ctrl+Shift + E", "edges: wrap around / dead"),
    ("Ctrl+Shift + K", "next colour theme"),
    ("Ctrl+Shift + F", "effects: trails, age glow, flashes"),
    ("Ctrl+Shift + Up / Down", "opacity"),
    ("Ctrl+Shift + S", "settings: colour, speed, wallpaper / window, hover, size, monitor"),
    ("Ctrl+Shift + W", "pin to desktop (wallpaper) / unpin"),
    ("Ctrl+Shift + H", "show / hide help"),
    ("Ctrl+Shift + Esc", "quit"),
    ("Panel (top left)", "step back, play, pause, faster, pin / unpin"),
]

# While pinned the window never has focus, so shortcuts must be grabbed system-wide, which
# takes them away from every other app. Only grab the few needed while pinned: quit (Esc),
# unpin (W) and settings (S). Everything else works again once unpinned.
# Keys are macOS virtual key codes.
MAC_KEYCODES = {53: "quit", 13: "wallpaper", 1: "settings"}
