"""Colour helpers: --color parsing, gradient themes and vectorised hue -> RGB."""
import argparse
from typing import NamedTuple

import numpy as np

NAMED_COLORS = {
    "white": (255, 255, 255), "black": (0, 0, 0), "gray": (128, 128, 128),
    "red": (235, 64, 52), "orange": (245, 150, 40), "yellow": (245, 220, 60),
    "green": (70, 200, 90), "cyan": (60, 210, 230), "blue": (60, 120, 240),
    "purple": (150, 90, 230), "pink": (240, 110, 180), "mauve": (224, 176, 255),
    # reds
    "crimson": (220, 20, 60), "scarlet": (255, 36, 0), "ruby": (224, 17, 95),
    "maroon": (150, 20, 40), "burgundy": (140, 20, 55), "cherry": (210, 30, 70),
    "brick": (190, 65, 50), "rust": (183, 65, 14), "salmon": (250, 128, 114),
    "coral": (255, 127, 80), "tomato": (255, 99, 71), "rose": (255, 90, 120),
    # oranges / yellows / browns
    "amber": (255, 191, 0), "gold": (255, 200, 30), "tangerine": (255, 140, 0),
    "peach": (255, 190, 150), "apricot": (251, 206, 177), "copper": (200, 120, 70),
    "bronze": (205, 127, 50), "caramel": (200, 140, 60), "mustard": (225, 175, 30),
    "lemon": (255, 245, 90), "cream": (255, 245, 205), "sand": (225, 200, 150),
    "tan": (210, 180, 140), "brown": (140, 90, 55), "chocolate": (110, 60, 30),
    "coffee": (120, 85, 60),
    # greens
    "lime": (175, 255, 50), "mint": (150, 255, 200), "emerald": (40, 190, 120),
    "jade": (0, 168, 107), "olive": (128, 140, 40), "sage": (155, 180, 140),
    "moss": (110, 140, 60), "pine": (30, 100, 70), "chartreuse": (127, 255, 0),
    "neongreen": (57, 255, 20), "seafoam": (130, 230, 190), "teal": (0, 150, 150),
    "forestgreen": (34, 120, 60),
    # blues / cyans
    "aqua": (0, 255, 230), "turquoise": (64, 224, 208), "azure": (0, 140, 255),
    "sky": (135, 206, 250), "navy": (20, 40, 120), "royal": (65, 105, 225),
    "cobalt": (0, 71, 171), "sapphire": (30, 70, 190), "indigo": (75, 40, 160),
    "denim": (60, 100, 160), "steel": (110, 150, 190), "powder": (176, 224, 230),
    "electric": (30, 180, 255), "midnight": (25, 25, 90),
    # purples / pinks
    "violet": (138, 43, 226), "lavender": (200, 180, 255), "lilac": (200, 162, 200),
    "plum": (142, 69, 133), "magenta": (255, 0, 200), "fuchsia": (255, 60, 220),
    "orchid": (218, 112, 214), "grape": (110, 40, 150), "amethyst": (153, 102, 204),
    "bubblegum": (255, 150, 200), "hotpink": (255, 70, 150), "blush": (255, 190, 200),
    "raspberry": (200, 30, 100),
    # neutrals
    "silver": (192, 192, 192), "charcoal": (60, 65, 70), "slate": (110, 120, 135),
    "ash": (170, 170, 165), "ivory": (255, 255, 235), "smoke": (210, 210, 215),
}


def _add_shades():
    """Add light / dark / pale versions of every named colour above (except black and
    white, which have no useful shades): "lightblue", "darkred", "palemint", ..."""
    def mix(rgb, target, amount):
        r, g, b = (round(c + (target - c) * amount) for c in rgb)
        return (r, g, b)
    for name, rgb in list(NAMED_COLORS.items()):
        if name in ("black", "white"):
            continue
        NAMED_COLORS["light" + name] = mix(rgb, 255, 0.40)
        NAMED_COLORS["dark" + name] = mix(rgb, 0, 0.45)
        NAMED_COLORS["pale" + name] = mix(rgb, 255, 0.70)


_add_shades()


class Theme(NamedTuple):
    """A looping gradient. Like "multi", every cell has its own hue (inherited from its
    parents), but the hue picks a colour along these stops instead of the rainbow."""
    name: str
    stops: tuple


THEMES = {t.name: t for t in (
    Theme("heat", ((120, 12, 12), (225, 60, 20), (255, 165, 30), (255, 235, 140))),
    Theme("ocean", ((15, 45, 120), (20, 115, 200), (40, 200, 220), (150, 240, 225))),
    Theme("neon", ((255, 40, 200), (125, 60, 255), (40, 220, 255), (80, 255, 140))),
    Theme("forest", ((35, 95, 45), (85, 165, 65), (175, 205, 85), (60, 135, 105))),
    Theme("sunset", ((255, 95, 100), (255, 150, 100), (255, 205, 120), (175, 90, 200))),
    Theme("ice", ((210, 235, 255), (120, 175, 255), (90, 120, 230), (175, 215, 255))),
)}


def parse_color(text):
    """'multi' -> None (every cell its own hue), a theme like 'heat' -> Theme,
    a name like 'white' or a hex like '#ff8800' -> (r, g, b)."""
    text = text.strip().lower()
    if text in ("multi", "multicolor", "rainbow", ""):
        return None
    if text in THEMES:
        return THEMES[text]
    if text in NAMED_COLORS:
        return NAMED_COLORS[text]
    hexa = text.lstrip("#")
    if len(hexa) == 6:
        try:
            return tuple(int(hexa[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            pass
    raise argparse.ArgumentTypeError(
        f"unknown colour {text!r}: use multi, {', '.join(THEMES)}, {', '.join(NAMED_COLORS)}, or a hex like #ff8800")


def hue_to_rgb(hue, s=0.7, v=1.0):
    """Vectorised HSV -> RGB (uint8) for an array of hues in [0, 1)."""
    h6 = hue * 6.0
    i = np.floor(h6).astype(int) % 6
    f = h6 - np.floor(h6)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return (np.stack([r, g, b], axis=-1) * 255).astype(np.uint8)


def theme_to_rgb(hue, theme):
    """Vectorised hue in [0, 1) -> RGB (uint8) along a theme's looping gradient."""
    stops = np.array(theme.stops, dtype=np.float32)
    x = (hue % 1.0) * len(stops)
    i = np.floor(x).astype(int) % len(stops)
    f = (x - np.floor(x))[..., None]
    return (stops[i] * (1 - f) + stops[(i + 1) % len(stops)] * f).astype(np.uint8)


def colorize(hue, color):
    """RGB for an array of hues: `color` is None (rainbow) or a Theme (its gradient)."""
    if color is None:
        return hue_to_rgb(hue)
    return theme_to_rgb(hue, color)
