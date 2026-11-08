#!/usr/bin/env bash
# Run Life in Life as a live wallpaper over your macOS desktop picture.
# Edit the values below, then run:  ./wall.sh
# Stop it with Ctrl+C here, or Ctrl+Shift+Esc. Ctrl+Shift+W unpins it so the other shortcuts work.
# Ctrl+Shift+S picks colour, speed and monitor in a small window, live (and remembers it).
# To start it at every login, see login.sh.

# Background darkness behind the cells: 0 = fully clear (your wallpaper shows), 1 = solid black
BG_OPACITY=0

# Opacity of the whole window (cells and the BG_OPACITY backdrop together):
# 1 = solid, 0.1 = faint. With BG_OPACITY=0 this is effectively the cells' opacity.
OPACITY=1

# Scale: bigger = larger cells (1 to 8). From 2.2 up, the inner Game of Life shows inside each cell.
# Below 2.2 it uses almost no CPU (it wakes ~2x a second, when the world changes); above, every frame.
ZOOM=1

# World size: how many cells across. Fewer = bigger cells and bigger patterns.
GRID=144

# Frames per second: how smooth zooming and the inner worlds are.
FPS=30

# Speed: outer generations per second (0.5, 1, 2, 4, 8 ... at most FPS).
SPEED=15

# Rules: conway, highlife, daynight, seeds, maze, lifewithoutdeath, morley, diamoeba,
# or B/S notation like B36/S23. INNER_RULE is for the little worlds inside each cell.
RULE=conway
INNER_RULE=conway

# Edges of the world: wrap (around, like a donut) or dead (nothing beyond them).
EDGES=wrap

# Fading trails, age glow and birth flashes: 1 = on, 0 = off.
EFFECTS=1

# Cell colour: multi (every cell its own colour), a theme (heat, ocean, neon, forest,
# sunset, ice: like multi, but along that gradient), or one colour for all cells: white, black, gray, red, orange, yellow, green, cyan, blue, purple, pink, mauve, or a hex like #ff8800
COLOR=multi

# Which monitor to cover: 1 = primary (the one with the menu bar), 2 = second, 3 = third ...
# To see the numbers, run:  ./wall.sh --list-monitors
MONITOR=1

cd "$(dirname "$0")" || exit 1

# Started by login.sh: keep its log from growing forever. Trim in place (rewrite the same
# file, not replace it) because launchd already has it open for this run's output.
if [ -n "$LIFE_LOG" ] && [ -f "$LIFE_LOG" ] && [ "$(stat -f %z "$LIFE_LOG")" -gt 1048576 ]; then
    tail -c 262144 "$LIFE_LOG" > "$LIFE_LOG.tmp" && cat "$LIFE_LOG.tmp" > "$LIFE_LOG"
    rm -f "$LIFE_LOG.tmp"
fi

# Colour / speed / monitor picked with Ctrl+Shift+S (or ./login.sh) are saved in ./settings and
# passed after the values above, so they win. ./login.sh reset (or deleting it) undoes that.
SAVED=()
if [ -f settings ]; then
    while IFS='=' read -r key value; do
        case "$key" in color|speed|monitor) [ -n "$value" ] && SAVED+=("--$key" "$value") ;; esac
    done < settings
fi

EXTRA=()
[ "$EFFECTS" = 0 ] && EXTRA+=(--no-effects)

# Run the code next to this file if it's here (a clone, or login.sh's copy); otherwise the
# installed `life` command (pipx / uv tool install), or $LIFE_BIN, which login.sh sets.
if [ -f "life inside life.py" ]; then
    PYTHON=".venv-life/bin/python"
    [ -x "$PYTHON" ] || PYTHON="python3"
    RUN=("$PYTHON" "life inside life.py")
else
    RUN=("${LIFE_BIN:-life}")
fi

# Note: it can take a few seconds for the wallpaper to appear on screen.

exec "${RUN[@]}" --wallpaper \
    --bg-opacity "$BG_OPACITY" \
    --opacity "$OPACITY" \
    --zoom "$ZOOM" \
    --grid "$GRID" \
    --fps "$FPS" \
    --speed "$SPEED" \
    --rule "$RULE" \
    --inner-rule "$INNER_RULE" \
    --edges "$EDGES" \
    --color "$COLOR" \
    --monitor "$MONITOR" \
    "${EXTRA[@]}" \
    "${SAVED[@]}" \
    "$@"
