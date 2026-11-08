# life

Conway's Game of Life where every live cell contains another Game of Life — a recursive, colorful cellular automaton rendered with pygame, zoomable in real time.

## Run

```sh
pip install -r requirements.txt
python "life inside life.py"               # transparent floating window
python "life inside life.py" --wallpaper    # live wallpaper behind desktop icons (macOS)
```

## Controls

| Key | Action |
|---|---|
| `Ctrl+Shift + Space` | pause / resume |
| `Ctrl+Shift + R` | new random world |
| `Ctrl+Shift + W` | pin to desktop (wallpaper) |
| Scroll / `Ctrl+Shift + = -` | zoom |
| `Ctrl+Shift + H` | help |
| `Ctrl+Shift + Esc` | quit |
