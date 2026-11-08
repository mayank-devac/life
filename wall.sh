#!/usr/bin/env bash
# Run Life in Life as a live wallpaper over your macOS desktop picture.
# Edit the values below, then run:  ./wall.sh
# Stop it with Ctrl+C here, or Ctrl+Shift+Esc.

# Background darkness behind the cells: 0 = fully clear (your wallpaper shows), 1 = solid black
BG_OPACITY=0

# Opacity of the cells themselves: 1 = solid, 0.1 = faint (0 would hide everything)
OPACITY=0.5

# Scale: bigger = larger cells (1 to 8). From 2.2 up, the inner Game of Life shows inside each cell.
ZOOM=0

# World size: how many cells across. Fewer = bigger cells and bigger patterns.
GRID=98

FPS=30

# Cell colour: multi (every cell its own colour), or one colour for all cells:
# white, black, gray, red, orange, yellow, green, cyan, blue, purple, pink, or a hex like #ff8800
COLOR=multi

# Which monitor to cover: 1 = primary (the one with the menu bar), 2 = second, 3 = third ...
# To see the numbers, run:  ./wall.sh --list-monitors
MONITOR=1

cd "$(dirname "$0")" || exit 1
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
