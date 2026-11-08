#!/usr/bin/env bash
# Run Life in Life as a live wallpaper over your macOS desktop picture.
# Edit the values below, then run:  ./wallpaper.sh
# Stop it with Ctrl+C here, or Ctrl+Shift+Esc (needs Accessibility permission for your terminal).

# Background darkness behind the cells: 0 = fully clear (your wallpaper shows), 1 = solid black
BG_OPACITY=0

# Opacity of the cells themselves: 1 = solid, 0.1 = faint (0 would hide everything)
OPACITY=1

# Scale: bigger = larger cells (1 to 8). From 2.2 up, the inner Game of Life shows inside each cell.
ZOOM=3.0

# World size: how many cells across. Fewer = bigger cells and bigger patterns.
GRID=68

FPS=30

cd "$(dirname "$0")" || exit 1
PYTHON=".venv-life/bin/python"
[ -x "$PYTHON" ] || PYTHON="python3"

exec "$PYTHON" "life inside life.py" --wallpaper \
    --bg-opacity "$BG_OPACITY" \
    --opacity "$OPACITY" \
    --zoom "$ZOOM" \
    --grid "$GRID" \
    --fps "$FPS" \
    "$@"
