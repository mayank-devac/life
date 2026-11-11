"""Command-line arguments and main()."""
import argparse
import importlib
import os
import shutil
import shlex
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from .colors import NAMED_COLORS, THEMES, parse_color
from .config import DEFAULT_SPEED, DETAIL_ZOOM, HELP, MAX_ZOOM, MIN_GRID, MIN_ZOOM
from .rules import PRESETS, parse_rule
from . import settings
from .settings import parse_speed

APP_NAME = "Life in Life"


def saved_defaults():
    """Colour / speed / monitor saved by the settings window (Ctrl+Shift+S), as argparse
    defaults, so a plain `life` starts with them too, not only wall.sh. Bad values are skipped."""
    saved, defaults = settings.load(), {}
    if "color" in saved:
        try:
            parse_color(saved["color"])
            defaults["color"] = saved["color"]
        except argparse.ArgumentTypeError:
            pass
    if "speed" in saved:
        try:
            parse_speed(saved["speed"])
            defaults["speed"] = saved["speed"]
        except ValueError:
            pass
    if saved.get("monitor", "").isdigit() and int(saved["monitor"]) >= 1:
        defaults["monitor"] = int(saved["monitor"])
    if saved.get("mode") in (settings.WALLPAPER, settings.WINDOW):
        defaults["mode"] = saved["mode"]
    if "size" in saved:
        try:
            defaults["size"] = settings.parse_size(saved["size"])
        except ValueError:
            pass
    if saved.get("hover") in ("on", "off"):
        defaults["hover"] = saved["hover"] == "on"
    return defaults


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Conway's Game of Life inside Conway's Game of Life.")
    # --wallpaper / --window: the last one given wins (wall.sh puts the saved mode after its own).
    p.add_argument("--wallpaper", dest="mode", action="store_const", const=settings.WALLPAPER,
                   help="macOS: run as a live wallpaper (behind desktop icons, on all Spaces, "
                        "click-through). Needs pyobjc-framework-Cocoa.")
    p.add_argument("--window", dest="mode", action="store_const", const=settings.WINDOW,
                   help="run in a window (the default, unless Ctrl+Shift+S saved wallpaper mode)")
    p.set_defaults(mode=settings.WINDOW)
    p.add_argument("--monitor", type=int, default=1,
                   help="which monitor to use, 1 = primary (default), 2 = second, ... "
                        "(see --list-monitors). --wallpaper covers it; otherwise the window "
                        "opens in its middle")
    p.add_argument("--hover", action=argparse.BooleanOptionalAction, default=False,
                   help="start with an empty world and bring cells to life wherever the mouse "
                        "moves over it, pinned or not (--no-hover: off, the default)")
    p.add_argument("--list-monitors", action="store_true",
                   help="print the connected monitors and their numbers, then exit")
    p.add_argument("--solid", action="store_true",
                   help="dark background instead of a transparent one")
    p.add_argument("--bg-opacity", type=float, default=0.0,
                   help="darkness of the background behind the cells, 0-1 "
                        "(default 0 = fully clear, your wallpaper shows through)")
    p.add_argument("--opacity", type=float, default=1.0,
                   help="opacity of the whole window, 0.1-1.0 (default 1.0)")
    p.add_argument("--size", type=int, default=800,
                   help=f"window size in points (default 800, min {settings.MIN_SIZE}; "
                        f"--wallpaper always fills the screen)")
    p.add_argument("--zoom", type=float, default=1.0,
                   help=f"start-up scale {MIN_ZOOM:g}-{MAX_ZOOM:g}: bigger = larger cells "
                        f"(inner life shows from {DETAIL_ZOOM})")
    p.add_argument("--grid", type=int, default=None,
                   help=f"cells across the world (min {MIN_GRID}); fewer = bigger cells. "
                        f"Default: as many as make each cell about the size of the mouse pointer "
                        f"(follows macOS's pointer size setting)")
    p.add_argument("--fps", type=int, default=30,
                   help="frames per second (default 30): how smooth zooming and the inner worlds are")
    p.add_argument("--speed", default=str(DEFAULT_SPEED),
                   help=f"outer generations per second (default {DEFAULT_SPEED:g}, at most --fps)")
    p.add_argument("--rule", default="conway",
                   help=f"outer world's rule: {', '.join(PRESETS)}, or B/S notation like B36/S23")
    p.add_argument("--inner-rule", default="conway", help="the inner worlds' rule (same choices)")
    p.add_argument("--edges", choices=("wrap", "dead"), default="wrap",
                   help="wrap: the outer edges wrap around (default); dead: beyond them is empty")
    p.add_argument("--no-effects", action="store_true",
                   help="no fading trails, age glow or birth flashes (Ctrl+Shift+F toggles them)")
    p.add_argument("--color", default="multi",
                   help=f"cell colour: multi (default, every cell its own hue), a theme "
                        f"({', '.join(THEMES)}), {', '.join(NAMED_COLORS)}, or a hex like #ff8800")
    p.add_argument("--load", metavar="FILE",
                   help="start from a pattern file (.rle, or .cells) instead of a random world; "
                        "you can also drop one onto the window")
    p.add_argument("-d", "--detach", action="store_true",
                   help="run in the background and give the terminal back (you can close it); "
                        "with --wallpaper it also hides the terminal app so the wallpaper shows "
                        "(Cmd+Tab brings it back). Stop it with Ctrl+Shift+Esc or life --stop")
    p.add_argument("--stop", action="store_true",
                   help="stop a copy started with --detach, then exit")
    p.add_argument("--make-app", action="store_true",
                   help=f"macOS: put a '{APP_NAME}' app in ~/Applications, so you can open it again "
                        "from Spotlight, Launchpad, Finder or the Dock without a terminal, then exit")
    p.add_argument("--from-app", action="store_true", help=argparse.SUPPRESS)  # the app's script
    p.add_argument("--menubar", action="store_true",
                   help="macOS: show a menu bar icon to start, stop and quit Life in Life, and open "
                        "its settings (the Life in Life app from --make-app starts it for you)")
    p.add_argument("--settings", action="store_true",
                   help="open the colour / speed / mode / size / monitor picker, save the choice for wall.sh, "
                        "then exit (Ctrl+Shift+S does the same while it runs)")
    p.add_argument("--login", nargs="*", metavar="COMMAND",
                   help="macOS: start the wallpaper at every login. --login install | uninstall | "
                        "status | color <name> | speed <n> | monitor <n> | monitors | reset "
                        "(no command: the settings window). Must come first.")
    p.set_defaults(**saved_defaults())  # what the settings window saved; flags still win
    args = p.parse_args(argv)
    args.wallpaper = args.mode == settings.WALLPAPER
    args.size = max(settings.MIN_SIZE, args.size)
    if args.grid is not None:
        args.grid = max(MIN_GRID, args.grid)  # None: pointer-sized cells (the app picks it)
    args.fps = max(1, args.fps)
    args.color_name = args.color  # the text, to show and save; args.color is the parsed value
    try:
        args.color = parse_color(args.color)
    except argparse.ArgumentTypeError as exc:
        p.error(f"argument --color: {exc}")
    for name in ("rule", "inner_rule"):
        try:
            setattr(args, name, parse_rule(getattr(args, name)))
        except ValueError as exc:
            p.error(f"argument --{name.replace('_', '-')}: {exc}")
    try:
        args.speed = min(parse_speed(args.speed), args.fps)
    except ValueError as exc:
        p.error(f"argument --speed: {exc}")
    return args


def list_monitors():
    from .mac.window import mac_screens  # noqa: PLC0415 - None without pyobjc
    screens = mac_screens()
    if screens:
        for i, (name, f) in enumerate(screens, 1):
            tag = "  (primary)" if i == 1 else ""
            print(f"  {i}: {name}  {int(f.size.width)}x{int(f.size.height)}{tag}")
        return
    import pygame  # noqa: PLC0415
    pygame.init()
    for i, (w, h) in enumerate(pygame.display.get_desktop_sizes(), 1):
        print(f"  {i}: {w}x{h}{'  (primary)' if i == 1 else ''}")
    pygame.quit()


PID_FILE = Path(tempfile.gettempdir()) / "lifeinlife-detached.pid"
DETACHED_ENV = "LIFE_DETACHED"  # set in the background copy, so it doesn't detach again
DETACH_LOG = (Path.home() / "Library" / "Logs" / "life-detached.log" if sys.platform == "darwin"
              else Path(tempfile.gettempdir()) / "life-detached.log")


def _detached_pid():
    """The pid of a copy started with --detach that is still running, else None."""
    return settings.live_pid(PID_FILE)


def stop_detached():
    pid = _detached_pid()
    if pid is None:
        print("No detached Life in Life is running.")
        PID_FILE.unlink(missing_ok=True)
        return False
    os.kill(pid, signal.SIGTERM)  # app.py leaves its loop cleanly on SIGTERM
    PID_FILE.unlink(missing_ok=True)
    print(f"Stopped Life in Life (pid {pid}).")
    return True


def _frontmost_app():
    """macOS: the app in front right now (the terminal this was typed in), or None."""
    if sys.platform != "darwin":
        return None
    try:
        appkit = importlib.import_module("AppKit")
    except ImportError:  # pyobjc is optional
        return None
    workspace = getattr(appkit, "NSWorkspace")
    return workspace.sharedWorkspace().frontmostApplication()


def _background(args):
    """Run `life <args>` as a background process, free of this terminal; its output goes to
    DETACH_LOG. Returns the Popen."""
    package_root = str(Path(__file__).resolve().parent.parent)  # so a clone imports too
    env = dict(os.environ, **{DETACHED_ENV: "1"})
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [package_root, env.get("PYTHONPATH")]))
    DETACH_LOG.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-c", "from lifeinlife.cli import main; main()", *args]
    with open(DETACH_LOG, "ab") as log:
        if sys.platform == "win32":
            return subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=env,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                env=env, start_new_session=True)


def detach(argv, hide_terminal):
    """Start this same command again in the background, free of the terminal, and return.
    Closing the terminal afterwards doesn't stop it (it's in its own session, so no SIGHUP)."""
    if _detached_pid() is not None:
        stop_detached()  # one at a time: the new one replaces it
    terminal = _frontmost_app() if hide_terminal else None
    child = _background([a for a in argv if a not in ("-d", "--detach")])
    PID_FILE.write_text(str(child.pid))
    print(f"Life in Life is running in the background (pid {child.pid}).")
    print("You can close this terminal. Stop it with Ctrl+Shift+Esc, or:  life --stop")
    print(f"Log: {DETACH_LOG}")
    if terminal is not None and terminal.processIdentifier() != child.pid:
        terminal.hide()  # Cmd+Tab (or clicking it in the Dock) brings it back


APP_SCRIPT = """#!/bin/bash
# Opens {name}. Written by  life --make-app  (run it again to rewrite this).
# Running already: shows its settings. Otherwise starts it (see open_from_app in cli.py).
export PYTHONPATH={pythonpath}${{PYTHONPATH:+:$PYTHONPATH}}
exec {python} -c 'from lifeinlife.cli import main; main()' --from-app
"""

APP_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>{name}</string>
    <key>CFBundleDisplayName</key><string>{name}</string>
    <key>CFBundleIdentifier</key><string>io.github.lifeinlife.launcher</string>
    <key>CFBundleExecutable</key><string>life</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleVersion</key><string>1</string>
    <!-- The script only starts life and exits: no Dock icon of its own. -->
    <key>LSUIElement</key><true/>
</dict>
</plist>
"""


def make_app():
    """life --make-app: write ~/Applications/Life in Life.app, a launcher that needs no terminal."""
    if sys.platform != "darwin":
        raise SystemExit("--make-app is macOS only.")
    app = Path.home() / "Applications" / f"{APP_NAME}.app"
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)
    (app / "Contents" / "Info.plist").write_text(APP_PLIST.format(name=APP_NAME))
    exe = macos / "life"
    package_root = str(Path(__file__).resolve().parent.parent)  # so a clone imports too
    exe.write_text(APP_SCRIPT.format(name=APP_NAME, python=shlex.quote(sys.executable),
                                     pythonpath=shlex.quote(package_root)))
    exe.chmod(0o755)
    # Tell Launch Services / Spotlight about it now, instead of whenever they next look.
    lsregister = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/"
                  "LaunchServices.framework/Support/lsregister")
    if os.path.exists(lsregister):
        subprocess.run([lsregister, "-f", str(app)], capture_output=True)
    print(f"Made {app}")
    print(f"Open it from Spotlight (Cmd+Space, type \"{APP_NAME}\"), Launchpad or Finder;")
    print("drag it to the Dock to keep it one click away.")
    if "/Downloads/" in package_root or "/Desktop/" in package_root or "/Documents/" in package_root:
        print(f"Note: it runs the code in {package_root}; don't move or delete that folder.")


MENUBAR_FILE = Path.home() / "Library" / "Caches" / "lifeinlife-menubar.pid"


def running_pid():
    """The pid of the Life in Life that's running (however it was started), or None."""
    return settings.live_pid(settings.RUNNING_FILE) or _detached_pid()


def start_life():
    """Start it the way it's set up: the login wallpaper if that's installed (with wall.sh's
    settings), else a background copy like  life -d  (with the saved colour, mode, ...)."""
    import pwd  # noqa: PLC0415 - Unix only, like the rest of this
    label = f"com.{pwd.getpwuid(os.getuid()).pw_name}.life-wallpaper"  # login.sh's LABEL
    plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    if plist.is_file():
        domain = f"gui/{os.getuid()}"
        subprocess.run(["launchctl", "bootstrap", domain, str(plist)], capture_output=True)
        subprocess.run(["launchctl", "kickstart", f"{domain}/{label}"])
        return
    # No terminal to hide: the app in front now is Finder, the Dock or similar.
    detach([], hide_terminal=False)


def stop_life():
    """Stop the running copy. It quits cleanly on SIGTERM, and launchd doesn't restart the
    login wallpaper after a clean quit."""
    pid = running_pid()
    if pid is not None:
        os.kill(pid, signal.SIGTERM)


def show_settings():
    """Ask the running copy to open its settings window (app.py handles SIGUSR1)."""
    pid = settings.live_pid(settings.RUNNING_FILE)  # only copies new enough to handle it
    if pid is not None:
        os.kill(pid, signal.SIGUSR1)


def open_from_app():
    """What opening the Life in Life app does. Already running: show its settings window,
    like Ctrl+Shift+S. Otherwise start it. Either way, make sure the menu bar icon is there."""
    if settings.live_pid(settings.RUNNING_FILE) is not None:
        show_settings()
    else:
        start_life()
    if settings.live_pid(MENUBAR_FILE) is None:
        _background(["--menubar"])


def run_menubar():
    """life --menubar: the menu bar icon (one at a time)."""
    if sys.platform != "darwin":
        raise SystemExit("--menubar is macOS only.")
    if settings.live_pid(MENUBAR_FILE) not in (None, os.getpid()):
        print("The Life in Life menu bar icon is already there.")
        return
    from .mac.menubar import MenuBar  # noqa: PLC0415 - needs pyobjc
    MENUBAR_FILE.parent.mkdir(parents=True, exist_ok=True)
    MENUBAR_FILE.write_text(str(os.getpid()))
    try:
        MenuBar(is_running=lambda: running_pid() is not None, start=start_life,
                stop=stop_life, settings=show_settings).run()
    finally:
        MENUBAR_FILE.unlink(missing_ok=True)


def run_login(commands):
    """life --login ...: run login.sh, which ships inside the package, using this `life`."""
    if sys.platform != "darwin":
        raise SystemExit("--login is macOS only.")
    script = Path(__file__).resolve().parent / "login.sh"
    if not script.is_file():
        raise SystemExit(f"login.sh is missing from {script.parent}")
    env = dict(os.environ, LIFE_LOGIN_CMD="life --login")
    env.pop("LIFE_FROM_SOURCE", None)  # there's no source to copy here, only this installed `life`
    if "LIFE_BIN" not in env:
        # The command that was typed (e.g. ~/.local/bin/life, a stable link), not the venv it points into.
        me = Path(sys.argv[0])
        bin_path = str(me.absolute()) if me.name == "life" and me.exists() else shutil.which("life")
        if not bin_path:
            raise SystemExit("Can't find the `life` command on PATH; set LIFE_BIN=/path/to/life")
        env["LIFE_BIN"] = bin_path
    raise SystemExit(subprocess.call(["/bin/bash", str(script), *commands], env=env))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["--login"]:
        run_login(argv[1:])
    args = parse_args(argv)
    if args.login is not None:
        raise SystemExit("--login must come first:  life --login install")
    if args.list_monitors:
        print("Monitors:")
        list_monitors()
        return
    if args.settings:
        from . import settings  # noqa: PLC0415
        print("Opening settings…", flush=True)
        picked = settings.choose(args.color_name, args.monitor, args.speed, args.mode, args.size,
                                 progress=lambda text: print(text, flush=True), hover=args.hover)
        if picked is None:
            print("Cancelled.")
            raise SystemExit(1)
        print("Saving…", flush=True)
        speed = settings.speed_text(picked["speed"])
        settings.save(color=picked["color"], speed=speed, monitor=picked["monitor"],
                      mode=picked["mode"], size=picked["size"],
                      hover="on" if picked["hover"] else "off")
        print(f"Saved: colour {picked['color']}, speed {speed}/s, {picked['mode']}"
              + (f" {picked['size']}pt" if picked["mode"] == settings.WINDOW else "")
              + f", monitor {picked['monitor']}" + (", hover on" if picked["hover"] else ""))
        return
    if args.stop:
        raise SystemExit(0 if stop_detached() else 1)
    if args.make_app:
        make_app()
        return
    if args.from_app:
        open_from_app()
        return
    if args.menubar:
        run_menubar()
        return
    if args.detach and not os.environ.get(DETACHED_ENV):
        detach(argv, hide_terminal=args.wallpaper)
        return
    print("Life in Life  -  shortcuts:")
    for keys, what in HELP:
        print(f"  {keys:<30} {what}")
    print("  Ctrl+C (in this terminal)      quit")
    from .app import LifeInLife  # noqa: PLC0415 - imports pygame
    LifeInLife(args).run()
