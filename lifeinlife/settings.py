"""Colour/speed/monitor choices picked with Ctrl+Shift+S (or ./login.sh): the dialog and
the `settings` file that keeps them. Nothing here imports pygame.

The file sits next to wall.sh as plain `key=value` lines (color=red, speed=4, monitor=2).
wall.sh passes them on as --color / --speed / --monitor, after its own values, so they win.
It also keeps where the control panel was dragged on each monitor (hud=ARZOPA@20,20;LG@40,120),
which only the app reads."""
import argparse
import json
import subprocess
from pathlib import Path

from .colors import NAMED_COLORS, THEMES, parse_color, preview_stops
from .config import SPEEDS

SETTINGS_FILE = Path(__file__).resolve().parent.parent / "settings"
KEYS = ("color", "speed", "monitor", "hud")
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
# sits above the list. Save is on the left, Back and Next on the right; cancelling is the title
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
    var rowImages = {};
    function rowImage(opt) {
        if (!(opt in rowImages)) rowImages[opt] = gradientImage(opt, 34, 12, 0);
        return rowImages[opt];
    }
    var preview = null;
    function showPreview(row) {
        if (!preview) return;
        var img = row >= 0 ? gradientImage(opts[row], 280, 28, 7) : null;
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
                    return $(opts[row]); }},
            'tableViewSelectionDidChange:': {types: ['void', ['id']], implementation: function (n) {
                showPreview(n.object.selectedRow); }},
            'clicked:': {types: ['void', ['id']], implementation: function (b) { $.NSApp.stopModalWithCode(b.tag); }},
            'doubleClicked:': {types: ['void', ['id']], implementation: function (t) {
                if (t.clickedRow >= 0) $.NSApp.stopModalWithCode(hasNext ? 1 : 2); }},
            'windowWillClose:': {types: ['void', ['id']], implementation: function (n) { $.NSApp.stopModalWithCode(3); }}
        }
    });
    var me = $.LifePicker.alloc.init;
    var W = 320, H = hasSwatches ? 396 : 360, top = hasSwatches ? 36 : 0;
    var win = $.NSPanel.alloc.initWithContentRectStyleMaskBackingDefer($.NSMakeRect(0, 0, W, H), 3, 2, false);  // titled + close button
    win.delegate = me;
    win.title = '%s';
    var view = win.contentView;
    var label = $.NSTextField.labelWithString(prompt);
    label.frame = $.NSMakeRect(20, H - 36, W - 40, 18);
    view.addSubview(label);
    if (hasSwatches) {
        preview = $.NSImageView.alloc.initWithFrame($.NSMakeRect(20, H - 72, W - 40, 28));
        preview.imageScaling = 1;  // fill the frame: the grid lines stay crisp at 280x28
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
    if (i < 0) i = 0;
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
    if (r === 3 || row < 0) return '';
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


def choose(color, monitor, speed=15, progress=None):
    """Ask for a colour, then a speed, then a monitor (skipped with only one screen).
    Each window has Next (go on to the next one), Save (stop here, keeping the current
    values of the later windows) and Back (what you picked in it is kept); closing it cancels.
    `color` is the current colour's text ("multi", "heat", "red", "#ff8800"), `speed` the
    outer generations per second, `monitor` its number. `progress(text)`, if given, is
    told about the pause before the monitor window.
    Returns (color_text, speed, monitor_number), or None if cancelled."""
    progress = progress or (lambda _text: None)
    names = ["multi", *THEMES, *NAMED_COLORS]
    speed_labels = [speed_label(v) for v in sorted({*SPEEDS, float(speed)})]
    now = f"(now: {color})", f"(now: {speed_label(speed)})"
    picked, monitors, step = [color, float(speed), monitor], [], 0  # monitors: loaded on the way to that window
    while True:
        if step == 0:
            default = picked[0] if picked[0] in names else CUSTOM
            swatches = {name: preview_stops(name) for name in names}
            if default == CUSTOM:
                swatches[CUSTOM] = preview_stops(picked[0])  # the hex colour in use
            button, value = _pick(f"Cell colour {now[0]}:", default, [*names, CUSTOM], first=True,
                                  swatches=swatches)
            if value == CUSTOM and button in (NEXT, SAVE):
                hex_default = picked[0] if picked[0] not in names else "#ff8800"
                value = _osascript(_ASK, "Hex colour, like #ff8800:", hex_default)
                if not value:
                    continue  # cancelled the hex box: back to the colour list
                try:
                    parse_color(value)
                except argparse.ArgumentTypeError as exc:
                    _osascript(_ALERT, str(exc))
                    continue
            if value and value != CUSTOM:
                picked[0] = value
        elif step == 1:
            button, value = _pick(f"Speed {now[1]}:", speed_label(picked[1]), speed_labels)
            if value:
                picked[1] = parse_speed(value)
        else:
            current = next((l for l in monitors if l.startswith(f"{picked[2]}:")), monitors[0])
            button, value = _pick("Which monitor should it cover?", current, monitors, last=True)
            if value:
                picked[2] = int(value.split(":", 1)[0])

        if button is None:
            return None
        if button == SAVE:
            return tuple(picked)
        step += -1 if button == BACK else 1
        if step == 2:
            if not monitors:
                progress("Loading monitors…")
                monitors = monitor_labels()
            if len(monitors) <= 1:
                return tuple(picked)  # only one screen: nothing to ask
