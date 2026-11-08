# life 🧬

Conway's Game of Life where every live cell contains another Game of Life — a recursive, colorful cellular automaton rendered with pygame, zoomable in real time.
And you can keep the game as your wallpaper.

<p align="center"><img src="life_running.png" alt="life running" width="1000"></p>

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

## As a wallpaper, it stays out of the way

- Zoomed out it wakes about twice a second (when the outer world steps) instead of 30 times,
  and only redraws when something changed.
- It pauses while the screen is locked, the display is asleep, or another user is logged in.
- If the chosen monitor is plugged in later, unplugged, or changes resolution, it moves and
  resizes to cover it again.
- `launchctl` / logout (SIGTERM) shuts it down cleanly; the log trims itself past 1 MB.

## Code layout

```
life inside life.py      launcher (kept so the commands above stay the same)
lifeinlife/
  config.py              constants: sizes, speeds, colours, help text
  colors.py              --color parsing, hue -> RGB
  world.py               the simulation (numpy only, no pygame)
  view.py                zoom / pan / resize maths
  render.py              drawing: world texture, inner worlds, help, toasts
  app.py                 window, input, actions, main loop
  cli.py                 command-line options
  mac/window.py          transparent + pinned window, monitor list
  mac/hotkeys.py         system-wide shortcuts (no permission prompt)
  mac/visibility.py      screen locked / display asleep checks
tests/                   python -m unittest discover -s tests -t .
```
