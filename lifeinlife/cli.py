"""Command-line arguments and main()."""
import argparse

from .colors import NAMED_COLORS, THEMES, parse_color
from .config import DEFAULT_GRID, DEFAULT_SPEED, DETAIL_ZOOM, HELP, MAX_ZOOM, MIN_GRID, MIN_ZOOM
from .rules import PRESETS, parse_rule
from .settings import parse_speed


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Conway's Game of Life inside Conway's Game of Life.")
    p.add_argument("--wallpaper", action="store_true",
                   help="macOS: run as a live wallpaper (behind desktop icons, on all Spaces, "
                        "click-through). Needs pyobjc-framework-Cocoa.")
    p.add_argument("--monitor", type=int, default=1,
                   help="with --wallpaper: which monitor to cover, 1 = primary (default), "
                        "2 = second, ... (see --list-monitors)")
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
                   help="window size in points (default 800; --wallpaper always fills the screen)")
    p.add_argument("--zoom", type=float, default=1.0,
                   help=f"start-up scale {MIN_ZOOM:g}-{MAX_ZOOM:g}: bigger = larger cells "
                        f"(inner life shows from {DETAIL_ZOOM})")
    p.add_argument("--grid", type=int, default=DEFAULT_GRID,
                   help=f"cells across the world (default {DEFAULT_GRID}, min {MIN_GRID}); "
                        f"fewer = bigger cells")
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
    p.add_argument("--settings", action="store_true",
                   help="open the colour / speed / monitor picker, save the choice for wall.sh, "
                        "then exit (Ctrl+Shift+S does the same while it runs)")
    args = p.parse_args(argv)
    args.grid = max(MIN_GRID, args.grid)
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


def main(argv=None):
    args = parse_args(argv)
    if args.list_monitors:
        print("Monitors:")
        list_monitors()
        return
    if args.settings:
        from . import settings  # noqa: PLC0415
        print("Opening settings…", flush=True)
        picked = settings.choose(args.color_name, args.monitor, args.speed,
                                 progress=lambda text: print(text, flush=True))
        if picked is None:
            print("Cancelled.")
            raise SystemExit(1)
        color, speed, monitor = picked
        print("Saving…", flush=True)
        settings.save(color=color, speed=settings.speed_text(speed), monitor=monitor)
        print(f"Saved: colour {color}, speed {settings.speed_text(speed)}/s, monitor {monitor}")
        return
    print("Life in Life  -  shortcuts:")
    for keys, what in HELP:
        print(f"  {keys:<30} {what}")
    print("  Ctrl+C (in this terminal)      quit")
    from .app import LifeInLife  # noqa: PLC0415 - imports pygame
    LifeInLife(args).run()
