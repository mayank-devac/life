#!/usr/bin/env bash
# Run Life in Life as a live wallpaper over your macOS desktop picture.
# Edit the values below, then run:  ./wall.sh
# Stop it with Ctrl+C here, or Ctrl+Shift+Esc. Ctrl+Shift+W unpins it so the other shortcuts work.
# To start it at every login, see login.sh.

# Background darkness behind the cells: 0 = fully clear (your wallpaper shows), 1 = solid black
BG_OPACITY=0

# Opacity of the whole window (cells and the BG_OPACITY backdrop together):
# 1 = solid, 0.1 = faint. With BG_OPACITY=0 this is effectively the cells' opacity.
OPACITY=0.7

# Scale: bigger = larger cells (1 to 8). From 2.2 up, the inner Game of Life shows inside each cell.
# Below 2.2 it uses almost no CPU (it wakes ~2x a second, when the world changes); above, every frame.
ZOOM=1

# World size: how many cells across. Fewer = bigger cells and bigger patterns.
GRID=98

# Frames per second. This also sets the speed: the outer world steps once every 15 frames.
FPS=30

# Cell colour: multi (every cell its own colour), or one colour for all cells:
# white, black, gray, red, orange, yellow, green, cyan, blue, purple, pink, or a hex like #ff8800
COLOR=multi

# Which monitor to cover: 1 = primary (the one with the menu bar), 2 = second, 3 = third ...
# To see the numbers, run:  ./wall.sh --list-monitors
MONITOR=2

cd "$(dirname "$0")" || exit 1

# Started by login.sh: keep its log from growing forever. Trim in place (rewrite the same
# file, not replace it) because launchd already has it open for this run's output.
if [ -n "$LIFE_LOG" ] && [ -f "$LIFE_LOG" ] && [ "$(stat -f %z "$LIFE_LOG")" -gt 1048576 ]; then
    tail -c 262144 "$LIFE_LOG" > "$LIFE_LOG.tmp" && cat "$LIFE_LOG.tmp" > "$LIFE_LOG"
    rm -f "$LIFE_LOG.tmp"
fi

PYTHON=".venv-life/bin/python"
[ -x "$PYTHON" ] || PYTHON="python3"

exec "$PYTHON" "life inside life.py" --wallpaper \
    --bg-opacity "$BG_OPACITY" \
    --opacity "$OPACITY" \
    --zoom "$ZOOM" \
    --grid "$GRID" \
    --fps "$FPS" \
    --color "$COLOR" \
    --monitor "$MONITOR" \
    "$@"
