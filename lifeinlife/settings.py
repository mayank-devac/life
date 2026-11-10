"""Colour / speed / mode / window size / monitor choices picked with Ctrl+Shift+S (or
./login.sh): the dialog and the `settings` file that keeps them. Nothing here imports pygame.

The file sits next to wall.sh as plain `key=value` lines (color=red, speed=4, monitor=2,
mode=window, size=600). wall.sh passes them on as --color / --speed / --monitor / --window
or --wallpaper / --size, after its own values, so they win.
It also keeps where the control panel was dragged on each monitor (hud=ARZOPA@20,20;LG@40,120),
which only the app reads."""
import argparse
import json
import os
import subprocess
from pathlib import Path

from .colors import NAMED_COLORS, THEMES, parse_color, preview_stops
from .config import SPEEDS, WINDOW_SIZES


def _settings_file():
    """Where the settings live: $LIFE_SETTINGS if set; next to wall.sh when the package sits
    beside it (a clone, or login.sh's copy); otherwise (installed with pip/pipx) in the same
    folder login.sh uses, so `life` and the login wallpaper share one file."""
    if os.environ.get("LIFE_SETTINGS"):
        return Path(os.environ["LIFE_SETTINGS"]).expanduser()
    beside = Path(__file__).resolve().parent.parent
    if (beside / "wall.sh").exists():
        return beside / "settings"
    return Path.home() / "Library" / "Application Support" / "life-wallpaper" / "settings"


SETTINGS_FILE = _settings_file()
# The pid of the copy that's running (any way it was started), so opening the Life in Life app
# again can ask it to show this dialog (SIGUSR1) instead of starting a second one.
RUNNING_FILE = Path.home() / "Library" / "Caches" / "lifeinlife-running.pid"


def live_pid(path):
    """The pid in `path` if that process is still running and is Life in Life, else None."""
    try:
        pid = int(Path(path).read_text().strip())
        os.kill(pid, 0)  # raises if it's gone
    except (OSError, ValueError):
        return None
    if os.name != "nt":
        # The pid may have been reused by something else since: only trust it if it's us.
        out = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                             capture_output=True, text=True).stdout
        if "life" not in out:
            return None
    return pid
KEYS = ("color", "speed", "monitor", "mode", "size", "hud")
WALLPAPER, WINDOW = "wallpaper", "window"   # the two modes (saved as mode=...)
MODE_LABELS = {WALLPAPER: "Wallpaper  (fills the monitor, behind your icons)",
               WINDOW: "Window  (a square you can move, draw in and resize)"}
MIN_SIZE = 200  # smallest window, in points
CUSTOM = "Custom hex colour…"
CUSTOM_SIZE = "Custom size…"
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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(f"{k}={values[k]}\n" for k in KEYS if k in values))
    tmp.replace(path)


def hud_spots(text):
    """"ARZOPA@20,20;LG@40,120" -> {"ARZOPA": (20.0, 20.0), "LG": (40.0, 120.0)}: where the
    control panel sits on each monitor, from its top-left corner. Bad entries are skipped."""
    spots = {}
    for entry in (text or "").split(";"):
        name, sep, xy = entry.rpartition("@")
        try:
            dx, dy = (float(v) for v in xy.split(","))
        except ValueError:
            continue
        if sep and name:
            spots[name] = (dx, dy)
    return spots


def hud_text(spots):
    """The other way round: {"ARZOPA": (20, 20)} -> "ARZOPA@20,20"."""
    return ";".join(f"{name}@{dx:g},{dy:g}" for name, (dx, dy) in spots.items()
                    if ";" not in name and "\n" not in name)


# ---------------------------------------------------------------- the dialog (macOS)
# `activate` brings the dialogs to the front: they're opened from a background app.
# The list window is our own (JavaScript for Automation + AppKit), because `choose from list`
# only allows two buttons. argv: prompt, default, flags ("first" greys out Back, "last" drops
# Next), swatches (JSON {option: ["#rrggbb", ...]}, "{}" for none), options... With swatches,
# each option gets a little gradient beside it and a cell-grid preview of the selected one
# sits above the list. An option "value\tshown" shows only the part after the tab (and prints
# the whole thing); "#\tTitle" is a section heading, which can't be picked. Save is on the left, Back and Next on the right; cancelling is the title
# bar's close button (or Esc). Prints "next\n<option>", "save\n<option>" or "back\n<option>",
# nothing if cancelled. Return = Next (Save in the last window), double-click = Return.
_PICK = r"""ObjC.import('Cocoa');
function run(argv) {
    var prompt = argv[0], def = argv[1], flags = argv[2].split(','), opts = argv.slice(4);
    var swatches = JSON.parse(argv[3] || '{}'), hasSwatches = Object.keys(swatches).length > 0;
    var first = flags.indexOf('first') >= 0, hasNext = flags.indexOf('last') < 0;
    var app = $.NSApplication.sharedApplication;
    app.setActivationPolicy(1);
    function nsColor(hex) {
        var n = parseInt(hex.slice(1), 16);
        return $.NSColor.colorWithSRGBRedGreenBlueAlpha((n >> 16 & 255) / 255, (n >> 8 & 255) / 255, (n & 255) / 255, 1);
    }
    // The option's colours as a left-to-right gradient; `cell` > 0 draws a grid of
    // cell-sized squares over it, like the wallpaper. null if the option has no colours.
    function gradientImage(opt, w, h, cell) {
        var hexes = swatches[opt];
        if (!hexes || !hexes.length) return null;
        var img = $.NSImage.alloc.initWithSize($.NSMakeSize(w, h));
        img.lockFocus;
        var rect = $.NSMakeRect(0, 0, w, h);
        $.NSGradient.alloc.initWithColors($(hexes.map(nsColor))).drawInRectAngle(rect, 0);
        if (cell > 0) {
            $.NSColor.colorWithSRGBRedGreenBlueAlpha(0.07, 0.07, 0.08, 1).setFill;
            for (var x = 0; x < w; x += cell) $.NSRectFill($.NSMakeRect(x, 0, 1, h));
            for (var y = 0; y < h; y += cell) $.NSRectFill($.NSMakeRect(0, y, w, 1));
        }
        img.unlockFocus;
        return img;
    }
    function shown(opt) { var t = opt.indexOf('\t'); return t < 0 ? opt : opt.slice(t + 1); }
    function heading(row) { return row >= 0 && opts[row].indexOf('#\t') === 0; }
    var rowImages = {};
    function rowImage(opt) {
        if (!(opt in rowImages)) rowImages[opt] = gradientImage(opt, 34, 12, 0);
        return rowImages[opt];
    }
    var preview = null;
    function showPreview(row) {
        if (!preview) return;
        var img = row >= 0 ? gradientImage(opts[row], W - 40, 28, 7) : null;
        preview.image = img || $();
        preview.hidden = !img;
    }
    ObjC.registerSubclass({
        name: 'LifePicker',
        methods: {
            'numberOfRowsInTableView:': {types: ['long', ['id']], implementation: function (t) { return opts.length; }},
            'tableView:objectValueForTableColumn:row:': {types: ['id', ['id', 'id', 'long']],
                implementation: function (t, c, row) {
                    if (c.identifier.js === 's') return rowImage(opts[row]) || $();
                    return $(shown(opts[row])); }},
            'tableView:isGroupRow:': {types: ['bool', ['id', 'long']], implementation: function (t, row) {
                return heading(row); }},
            'tableView:shouldSelectRow:': {types: ['bool', ['id', 'long']], implementation: function (t, row) {
                return !heading(row); }},
            'tableViewSelectionDidChange:': {types: ['void', ['id']], implementation: function (n) {
                showPreview(n.object.selectedRow); }},
            'clicked:': {types: ['void', ['id']], implementation: function (b) { $.NSApp.stopModalWithCode(b.tag); }},
            'doubleClicked:': {types: ['void', ['id']], implementation: function (t) {
                if (t.clickedRow >= 0 && !heading(t.clickedRow)) $.NSApp.stopModalWithCode(hasNext ? 1 : 2); }},
            'windowWillClose:': {types: ['void', ['id']], implementation: function (n) { $.NSApp.stopModalWithCode(3); }}
        }
    });
    var me = $.LifePicker.alloc.init;
    var W = 380, H = hasSwatches ? 396 : 360, top = hasSwatches ? 36 : 0;
    var win = $.NSPanel.alloc.initWithContentRectStyleMaskBackingDefer($.NSMakeRect(0, 0, W, H), 3, 2, false);  // titled + close button
    win.delegate = me;
    win.title = '%s';
    var view = win.contentView;
    var label = $.NSTextField.labelWithString(prompt);
    label.frame = $.NSMakeRect(20, H - 36, W - 40, 18);
    view.addSubview(label);
    if (hasSwatches) {
        preview = $.NSImageView.alloc.initWithFrame($.NSMakeRect(20, H - 72, W - 40, 28));
        preview.imageScaling = 1;  // fill the frame: drawn at this size, so the grid lines stay crisp
        view.addSubview(preview);
    }
    var scroll = $.NSScrollView.alloc.initWithFrame($.NSMakeRect(20, 60, W - 40, H - 104 - top));
    scroll.hasVerticalScroller = true;
    scroll.borderType = 2;
    var table = $.NSTableView.alloc.initWithFrame($.NSMakeRect(0, 0, W - 44, 100));
    if (hasSwatches) {
        var scol = $.NSTableColumn.alloc.initWithIdentifier('s');
        scol.width = 40;
        scol.dataCell = $.NSImageCell.alloc.init;
        table.addTableColumn(scol);
    }
    var col = $.NSTableColumn.alloc.initWithIdentifier('v');
    col.width = hasSwatches ? W - 104 : W - 60;
    table.addTableColumn(col);
    table.headerView = $();
    table.dataSource = me;
    table.delegate = me;
    table.target = me;
    table.doubleAction = 'doubleClicked:';
    scroll.documentView = table;
    view.addSubview(scroll);
    function button(title, tag, x, key) {
        var b = $.NSButton.buttonWithTitleTargetAction(title, me, 'clicked:');
        b.tag = tag;
        b.keyEquivalent = key;
        b.frame = $.NSMakeRect(x, 16, 88, 32);
        view.addSubview(b);
        return b;
    }
    button('Save', 2, 16, hasNext ? '' : '\r');
    button('Back', 4, hasNext ? W - 192 : W - 104, '').enabled = !first;
    if (hasNext) button('Next', 1, W - 104, '\r');
    button('Cancel', 3, -200, '\u001b');  // out of sight: just for Esc
    var i = opts.indexOf(def);
    while (i < 0 || heading(i)) i++;  // not found: the first row that isn't a heading
    table.reloadData;
    table.selectRowIndexesByExtendingSelection($.NSIndexSet.indexSetWithIndex(i), false);
    table.scrollRowToVisible(i);
    showPreview(i);
    win.initialFirstResponder = table;
    win.center;
    app.activateIgnoringOtherApps(true);
    win.makeKeyAndOrderFront(null);
    var r = Number(app.runModalForWindow(win));
    var row = table.selectedRow;
    win.orderOut(null);
    if (r === 3 || row < 0 || heading(row)) return '';
    return ({1: 'next', 2: 'save', 4: 'back'})[r] + '\n' + opts[row];
}""" % TITLE
NEXT, SAVE, BACK = "next", "save", "back"

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


def _osascript(script, *args, lang="AppleScript"):
    """Run an AppleScript (or JavaScript); its result, or "" if cancelled / not on macOS."""
    try:
        out = subprocess.run(["osascript", "-l", lang, "-", *args], input=script,
                             capture_output=True, text=True, check=False)
    except OSError:
        return ""
    return out.stdout.strip()


def _pick(prompt, default, options, first=False, last=False, swatches=None):
    """Show the list window: Save on the left, Back and Next on the right (Back greyed out
    when `first`, no Next when `last`). `swatches` ({option: ["#rrggbb", ...]}) adds a colour
    preview: a little gradient by each option and a bigger one of the selected. Returns (NEXT, SAVE or BACK, chosen option), or
    (None, None) if cancelled / not on macOS."""
    flags = ",".join(f for f, on in (("first", first), ("last", last)) if on)
    button, _, value = _osascript(_PICK, prompt, default, flags, json.dumps(swatches or {}),
                                  *options, lang="JavaScript").partition("\n")
    if button not in (NEXT, SAVE, BACK) or not value:
        return None, None
    return button, value


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


def size_label(size):
    """800 -> "800 × 800 points"."""
    return f"{int(size)} × {int(size)} points"


def parse_size(text):
    """"800" or a dialog label -> window size in points (>= MIN_SIZE). ValueError otherwise."""
    try:
        value = int(str(text).split()[0])
    except (ValueError, IndexError):
        value = 0
    if value < MIN_SIZE:
        raise ValueError(f"window size must be a whole number of points, at least {MIN_SIZE}, "
                         f"not {text!r}")
    return value


STEPS = ("color", "speed", "place", "size")


HEADING = "#"  # place_options(): a section heading row, not something to pick


def place_options(monitors, monitor):
    """The one window that asks wallpaper or window, and on which monitor: [(option, mode,
    monitor number)]. With 2+ monitors, a section per mode (a heading row, mode None) listing
    every monitor; with one monitor (or none found) just the two modes, on `monitor`."""
    if len(monitors) < 2:
        return [(label, mode, monitor) for mode, label in MODE_LABELS.items()]
    rows = []
    for mode, label in MODE_LABELS.items():
        rows.append((f"{HEADING}\t{label}", None, None))
        for screen in monitors:
            n = int(screen.split(":", 1)[0])
            rows.append((f"{mode}:{n}\t{screen}", mode, n))
    return rows


def choose(color, monitor, speed=15, mode=WINDOW, size=800, progress=None):
    """Ask for a colour, a speed, wallpaper or window and on which monitor (one window), then
    the window's size (only for a window).
    Each window has Next (go on to the next one), Save (stop here, keeping the current
    values of the later windows) and Back (what you picked in it is kept); closing it cancels.
    `color` is the current colour's text ("multi", "heat", "red", "#ff8800"), `speed` the
    outer generations per second, `monitor` its number, `mode` WALLPAPER or WINDOW, `size`
    the window's size in points. `progress(text)`, if given, is told about the pause before
    the wallpaper / window window (finding the monitors).
    Returns {"color", "speed", "monitor", "mode", "size"}, or None if cancelled."""
    progress = progress or (lambda _text: None)
    names = ["multi", *THEMES, *NAMED_COLORS]
    speed_labels = [speed_label(v) for v in sorted({*SPEEDS, float(speed)})]
    size_labels = [size_label(v) for v in sorted({*WINDOW_SIZES, int(size)})]
    mode = mode if mode in MODE_LABELS else WINDOW
    now = {"color": color, "speed": speed_label(speed), "mode": mode, "size": size_label(size),
           "monitor": monitor}
    picked = {"color": color, "speed": float(speed), "monitor": monitor, "mode": mode,
              "size": int(size)}
    places = None  # loaded on the way to that window (finding the monitors takes a moment)

    def wanted(step):
        return step != "size" or picked["mode"] == WINDOW

    i = 0
    while True:
        step = STEPS[i]
        if step == "color":
            default = picked["color"] if picked["color"] in names else CUSTOM
            swatches = {name: preview_stops(name) for name in names}
            if default == CUSTOM:
                swatches[CUSTOM] = preview_stops(picked["color"])  # the hex colour in use
            button, value = _pick(f"Cell colour (now: {now['color']}):", default, [*names, CUSTOM],
                                  first=True, swatches=swatches)
            if value == CUSTOM and button in (NEXT, SAVE):
                hex_default = picked["color"] if picked["color"] not in names else "#ff8800"
                value = _osascript(_ASK, "Hex colour, like #ff8800:", hex_default)
                if not value:
                    continue  # cancelled the hex box: back to the colour list
                try:
                    parse_color(value)
                except argparse.ArgumentTypeError as exc:
                    _osascript(_ALERT, str(exc))
                    continue
            if value and value != CUSTOM:
                picked["color"] = value
        elif step == "speed":
            button, value = _pick(f"Speed (now: {now['speed']}):", speed_label(picked["speed"]),
                                  speed_labels)
            if value:
                picked["speed"] = parse_speed(value)
        elif step == "place":
            if places is None:
                progress("Loading monitors…")
                monitors = monitor_labels()
                places = place_options(monitors, picked["monitor"])
                several = len(monitors) > 1
            current = next((opt for opt, m, n in places
                            if m == picked["mode"] and n == picked["monitor"]),
                           next(opt for opt, m, _n in places if m == picked["mode"]))
            where = f"{now['mode']} on monitor {now['monitor']}" if several else now["mode"]
            button, value = _pick(f"Show it as{', and where' if several else ''} (now: {where}):",
                                  current, [opt for opt, _m, _n in places])
            place = next((p for p in places if p[0] == value and p[1] is not None), None)
            if place:
                _opt, picked["mode"], picked["monitor"] = place
        else:
            button, value = _pick(f"Window size (now: {now['size']}):", size_label(picked["size"]),
                                  [*size_labels, CUSTOM_SIZE], last=True)
            if value == CUSTOM_SIZE and button in (NEXT, SAVE):
                value = _osascript(_ASK, f"Window size in points (at least {MIN_SIZE}), like 900:",
                                   str(picked["size"]))
                if not value:
                    continue  # cancelled the size box: back to the size list
                try:
                    parse_size(value)
                except ValueError as exc:
                    _osascript(_ALERT, str(exc))
                    continue
                size_labels = [size_label(v) for v in sorted({*WINDOW_SIZES, int(size),
                                                              parse_size(value)})]
            if value and value != CUSTOM_SIZE:
                picked["size"] = parse_size(value)

        if button is None:
            return None
        if button == SAVE:
            return picked
        move = -1 if button == BACK else 1
        i += move
        while 0 <= i < len(STEPS) and not wanted(STEPS[i]):
            i += move
        if i >= len(STEPS):
            return picked  # no more windows to show
        i = max(i, 0)
