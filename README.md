# life 🧬

Conway's Game of Life where every live cell contains another Game of Life — a recursive, colorful cellular automaton rendered with pygame, zoomable in real time.
And you can keep the game as your wallpaper.

<p align="center"><img src="life_running.png" alt="life running" width="600"></p>

## Run

```sh
pip install -r requirements.txt
python "life inside life.py"               # transparent floating window
python "life inside life.py" --wallpaper    # live wallpaper behind desktop icons (macOS)
```

## Live wallpaper

Edit the settings at the top of `wall.sh` (opacity, colour, monitor, zoom…), then:

```sh
./wall.sh                 # run it now (Ctrl+C or Ctrl+Shift+Esc to stop)
./login.sh install        # start it at every login
./login.sh status
./login.sh uninstall
```

`login.sh install` copies the app to `~/Library/Application Support/life-wallpaper` with its own
Python environment, because macOS won't let login items read Downloads, Desktop or Documents.
After editing `wall.sh`, run `./login.sh install` again to apply it. Logs: `~/Library/Logs/life-wallpaper.log`.

## Controls

| Key | Action |
|---|---|
| `Ctrl+Shift + Space` | pause / resume |
| `Ctrl+Shift + R` | new random world |
| `Ctrl+Shift + W` | pin to desktop (wallpaper) / unpin |
| `Ctrl+Shift + Up / Down` | opacity |
| Scroll / `Ctrl+Shift + = -` | zoom |
| `Ctrl+Shift + H` | help |
| `Ctrl+Shift + Esc` | quit |

While pinned as a wallpaper, only `Ctrl+Shift + W` and `Ctrl+Shift + Esc` are captured system-wide,
so other apps keep their shortcuts. Unpin with `Ctrl+Shift + W` to use the rest.
