"""Colour/speed/monitor choices picked with Ctrl+Shift+S (or ./login.sh): the dialog and
the `settings` file that keeps them. Nothing here imports pygame.

The file sits next to wall.sh as plain `key=value` lines (color=red, speed=4, monitor=2).
wall.sh passes them on as --color / --speed / --monitor, after its own values, so they win."""
import argparse
import subprocess
from pathlib import Path

from .colors import NAMED_COLORS, THEMES, parse_color
from .config import SPEEDS

SETTINGS_FILE = Path(__file__).resolve().parent.parent / "settings"
KEYS = ("color", "speed", "monitor")
CUSTOM = "Custom hex colour…"
TITLE = "Life wallpaper"


def load(path=SETTINGS_FILE):
    values = {}
    try:
        for line in Path(path).read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key in KEYS and value:
                values[key] = value
    except OSError:
        pass
    return values


def save(path=SETTINGS_FILE, **changes):
    """Merge `changes` (color="red", speed=4, monitor=2) into the file. Written whole, then renamed,
    so wall.sh never reads half a file."""
    values = load(path)
    values.update({k: str(v) for k, v in changes.items() if k in KEYS and v is not None})
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(f"{k}={values[k]}\n" for k in KEYS if k in values))
    tmp.replace(path)


# ---------------------------------------------------------------- the dialog (macOS)
# `activate` brings the dialog to the front: it's opened from a background app.
_PICK = """on run argv
    activate
    set opts to items 3 thru -1 of argv
    set d to item 2 of argv
    if opts does not contain d then set d to item 1 of opts
    set r to choose from list opts with title "%s" with prompt (item 1 of argv) default items {d}
    if r is false then return ""
    return item 1 of r
end run""" % TITLE

_ASK = """on run argv
    activate
    try
        return text returned of (display dialog (item 1 of argv) default answer (item 2 of argv) with title "%s")
    on error
        return ""
    end try
end run""" % TITLE

_ALERT = """on run argv
    activate
    display dialog (item 1 of argv) with title "%s" buttons {"OK"} default button 1
end run""" % TITLE


def _osascript(script, *args):
    """Run an AppleScript; its result, or "" if cancelled / not on macOS."""
    try:
        out = subprocess.run(["osascript", "-", *args], input=script, capture_output=True,
                             text=True, check=False)
    except OSError:
        return ""
    return out.stdout.strip()


def monitor_labels():
    """["1: ARZOPA  1920x1080  (primary)", "2: LG ULTRAGEAR  1920x1080"], or [] without pyobjc."""
    try:
        from .mac.window import mac_screens  # noqa: PLC0415 - needs pyobjc
    except ImportError:
        return []
    return [f"{i}: {name}  {int(f.size.width)}x{int(f.size.height)}{'  (primary)' if i == 1 else ''}"
            for i, (name, f) in enumerate(mac_screens() or [], 1)]


def speed_text(speed):
    """2.0 -> "2", 0.5 -> "0.5"."""
    return f"{float(speed):g}"


def speed_label(speed):
    """The speed as shown in the dialog: "2 generations / second"."""
    n = speed_text(speed)
    return f"{n} generation{'' if n == '1' else 's'} / second"


def parse_speed(text):
    """"4", "0.5" or a dialog label -> generations per second (> 0). ValueError otherwise."""
    try:
        value = float(str(text).split()[0])
    except (ValueError, IndexError):
        value = 0.0
    if not 0 < value < float("inf"):
        raise ValueError(f"speed must be a positive number of generations per second, not {text!r}")
    return value


def choose(color, monitor, speed=15, progress=None):
    """Ask for a colour, then a speed, then a monitor (skipped with only one screen).
    `color` is the current colour's text ("multi", "heat", "red", "#ff8800"), `speed` the
    outer generations per second, `monitor` its number. `progress(text)`, if given, is
    told about the pause before the monitor window.
    Returns (color_text, speed, monitor_number), or None if cancelled."""
    progress = progress or (lambda _text: None)
    names = ["multi", *THEMES, *NAMED_COLORS]
    picked = _osascript(_PICK, f"Cell colour (now: {color}):", color, *names, CUSTOM)
    if not picked:
        return None
    if picked == CUSTOM:
        default = color if color not in names else "#ff8800"
        picked = _osascript(_ASK, "Hex colour, like #ff8800:", default)
        if not picked:
            return None
        try:
            parse_color(picked)
        except argparse.ArgumentTypeError as exc:
            _osascript(_ALERT, str(exc))
            return None

    speeds = sorted({*SPEEDS, float(speed)})
    labels = [speed_label(v) for v in speeds]
    line = _osascript(_PICK, f"Speed (now: {speed_label(speed)}):", speed_label(speed), *labels)
    if not line:
        return None
    speed = parse_speed(line)

    progress("Loading monitors…")
    labels = monitor_labels()
    if len(labels) > 1:
        current = next((l for l in labels if l.startswith(f"{monitor}:")), labels[0])
        line = _osascript(_PICK, "Which monitor should it cover?", current, *labels)
        if not line:
            return None
        monitor = int(line.split(":", 1)[0])
    return picked, speed, monitor
