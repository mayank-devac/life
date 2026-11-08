"""Colour helpers: --color parsing and vectorised hue -> RGB."""
import argparse

import numpy as np

NAMED_COLORS = {
    "white": (255, 255, 255), "black": (0, 0, 0), "gray": (128, 128, 128),
    "red": (235, 64, 52), "orange": (245, 150, 40), "yellow": (245, 220, 60),
    "green": (70, 200, 90), "cyan": (60, 210, 230), "blue": (60, 120, 240),
    "purple": (150, 90, 230), "pink": (240, 110, 180),
}


def parse_color(text):
    """'multi' -> None (every cell its own hue), a name like 'white', or a hex like '#ff8800'."""
    text = text.strip().lower()
    if text in ("multi", "multicolor", "rainbow", ""):
        return None
    if text in NAMED_COLORS:
        return NAMED_COLORS[text]
    hexa = text.lstrip("#")
    if len(hexa) == 6:
        try:
            return tuple(int(hexa[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            pass
    raise argparse.ArgumentTypeError(
        f"unknown colour {text!r}: use multi, {', '.join(NAMED_COLORS)}, or a hex like #ff8800")


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
