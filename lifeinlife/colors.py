"""Colour helpers: --color parsing, gradient themes and vectorised hue -> RGB."""
import argparse
from typing import NamedTuple

import numpy as np

NAMED_COLORS = {
    "white": (255, 255, 255), "black": (0, 0, 0), "gray": (128, 128, 128),
    "red": (235, 64, 52), "orange": (245, 150, 40), "yellow": (245, 220, 60),
    "green": (70, 200, 90), "cyan": (60, 210, 230), "blue": (60, 120, 240),
    "purple": (150, 90, 230), "pink": (240, 110, 180), "mauve": (224, 176, 255),
}


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
