"""Tunable constants. Nothing here imports pygame, so tests can use it freely."""

# ---------------------------------------------------------------- world
DEFAULT_GRID = 96      # outer grid is GRID x GRID (overridable with --grid)
MIN_GRID = 8
MICRO_SIZE = 16        # inner grid inside every live outer cell
MACRO_EVERY = 15       # outer grid steps once every N frames
STALE_STEPS = 40       # reseed after this many outer steps with no real change
MUTATION = 0.04        # how far a newborn's hue may drift from its parents'
DENSITY = 0.3          # share of cells alive in a new random world

# ---------------------------------------------------------------- view
DETAIL_ZOOM = 2.2      # zoom level where the inner grids become visible
MIN_ZOOM, MAX_ZOOM = 1.0, 8.0
CLICK_SLOP = 4         # points the mouse may move and still count as a click (not a pan)
TEMPLATE_PX = 8        # pixels per inner cell in the inner-grid texture

# ---------------------------------------------------------------- main loop timing (seconds)
MAX_WAIT = 0.5         # longest sleep between wake-ups, so Ctrl+C / SIGTERM stay responsive
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
    ("Ctrl+Shift + drag", "move window"),
    ("Click", "add / remove a cell"),
    ("Drag", "pan (when zoomed in)"),
    ("Scroll  /  Ctrl+Shift + = -", "zoom"),
    ("Ctrl+Shift + Up / Down", "opacity"),
    ("Ctrl+Shift + Space", "pause / resume"),
    ("Ctrl+Shift + R", "new random world"),
    ("Ctrl+Shift + S", "settings: colour and monitor"),
    ("Ctrl+Shift + W", "pin to desktop (wallpaper) / unpin"),
    ("Ctrl+Shift + H", "show / hide help"),
    ("Ctrl+Shift + Esc", "quit"),
    ("While pinned", "only Ctrl+Shift + W, S and Esc work,"),
    ("", "plus the play / pause / step panel"),
]

# While pinned the window never has focus, so shortcuts must be grabbed system-wide, which
# takes them away from every other app. Only grab the few needed while pinned: quit (Esc),
# unpin (W) and settings (S). Everything else works again once unpinned.
# Keys are macOS virtual key codes.
MAC_KEYCODES = {53: "quit", 13: "wallpaper", 1: "settings"}
