import argparse
import unittest

import numpy as np

from lifeinlife.cli import parse_args
from lifeinlife.colors import hue_to_rgb, parse_color
from lifeinlife.config import MAX_ZOOM, MIN_GRID
from lifeinlife.view import View


class ParseColor(unittest.TestCase):
    def test_values(self):
        self.assertIsNone(parse_color("multi"))
        self.assertEqual(parse_color("White"), (255, 255, 255))
        self.assertEqual(parse_color("mauve"), (224, 176, 255))
        self.assertEqual(parse_color("#ff8800"), (255, 136, 0))
        self.assertEqual(parse_color("00ff00"), (0, 255, 0))

    def test_rejects_garbage(self):
        for bad in ("nope", "#ff88", "#gggggg"):
            with self.assertRaises(argparse.ArgumentTypeError):
                parse_color(bad)

    def test_hue_to_rgb_primaries(self):
        rgb = hue_to_rgb(np.array([0.0, 1 / 3, 2 / 3]), s=1.0)
        np.testing.assert_array_equal(rgb, [[255, 0, 0], [0, 255, 0], [0, 0, 255]])


class Args(unittest.TestCase):
    def test_grid_has_a_minimum(self):
        self.assertEqual(parse_args(["--grid", "2"]).grid, MIN_GRID)


class ViewMaths(unittest.TestCase):
    def test_grid_covers_window(self):
        v = View(800, 600, 64)
        self.assertGreaterEqual(v.grid_px, 800)
        v.pan(10_000, 10_000)
        self.assertEqual((v.ox, v.oy), (0.0, 0.0))
        v.pan(-10_000, -10_000)
        self.assertAlmostEqual(v.ox + v.grid_px, 800)

    def test_zoom_keeps_point_under_cursor(self):
        v = View(1000, 1000, 50)
        v.zoom_at(2.0, 300, 400)
        before = ((300 - v.ox) / v.cell, (400 - v.oy) / v.cell)
        v.zoom_at(1.5, 300, 400)
        after = ((300 - v.ox) / v.cell, (400 - v.oy) / v.cell)
        np.testing.assert_allclose(before, after)

    def test_zoom_is_clamped(self):
        v = View(100, 100, 10)
        v.zoom_at(1000, 50, 50)
        self.assertEqual(v.zoom, MAX_ZOOM)

    def test_resize_keeps_zoom_and_centre(self):
        v = View(1000, 1000, 50)
        v.zoom_at(4.0, 250, 250)
        centre = ((500 - v.ox) / v.grid_px, (500 - v.oy) / v.grid_px)
        v.resize(2000, 1000)
        self.assertEqual(v.zoom, 4.0)
        np.testing.assert_allclose(((1000 - v.ox) / v.grid_px, (500 - v.oy) / v.grid_px),
                                   centre, atol=1e-9)

    def test_visible_cells_zoomed_out_is_everything(self):
        self.assertEqual(View(640, 640, 64).visible_cells(), (0, 64, 0, 64))


if __name__ == "__main__":
    unittest.main()
