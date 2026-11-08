"""Command-line arguments and main()."""
import argparse

from .colors import NAMED_COLORS, parse_color
from .config import DEFAULT_GRID, DETAIL_ZOOM, HELP, MAX_ZOOM, MIN_GRID, MIN_ZOOM


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
    p.add_argument("--fps", type=int, default=30, help="frames per second (default 30)")
    p.add_argument("--color", default="multi",
                   help=f"cell colour: multi (default, every cell its own hue), "
                        f"{', '.join(NAMED_COLORS)}, or a hex like #ff8800")
    p.add_argument("--settings", action="store_true",
                   help="open the colour / monitor picker, save the choice for wall.sh, then exit "
                        "(Ctrl+Shift+S does the same while it runs)")
    args = p.parse_args(argv)
    args.grid = max(MIN_GRID, args.grid)
    args.color_name = args.color  # the text, to show and save; args.color is the parsed value
    try:
        args.color = parse_color(args.color)
    except argparse.ArgumentTypeError as exc:
        p.error(f"argument --color: {exc}")
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
        picked = settings.choose(args.color_name, args.monitor)
        if picked is None:
            print("Cancelled.")
            raise SystemExit(1)
        settings.save(color=picked[0], monitor=picked[1])
        print(f"Saved: colour {picked[0]}, monitor {picked[1]}")
        return
    print("Life in Life  -  shortcuts:")
    for keys, what in HELP:
        print(f"  {keys:<30} {what}")
    print("  Ctrl+C (in this terminal)      quit")
    from .app import LifeInLife  # noqa: PLC0415 - imports pygame
    LifeInLife(args).run()
