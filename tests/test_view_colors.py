import argparse
import contextlib
import io
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import numpy as np

from lifeinlife.cli import parse_args
from lifeinlife import settings
from lifeinlife.colors import THEMES, hue_to_rgb, parse_color, preview_stops, theme_to_rgb
from lifeinlife.config import MAX_POINTER_GRID, MAX_ZOOM, MIN_GRID, POINTER_PT
from lifeinlife.pointer import pointer_grid, pointer_scale
from lifeinlife.rules import PRESETS
from lifeinlife.view import View


class ParseColor(unittest.TestCase):
    def test_values(self):
        self.assertIsNone(parse_color("multi"))
        self.assertEqual(parse_color("White"), (255, 255, 255))
        self.assertEqual(parse_color("mauve"), (224, 176, 255))
        self.assertEqual(parse_color("#ff8800"), (255, 136, 0))
        self.assertEqual(parse_color("00ff00"), (0, 255, 0))

    def test_preview_stops(self):
        self.assertEqual(preview_stops("red"), ["#eb4034", "#eb4034"])
        self.assertEqual(preview_stops("#FF8800"), ["#ff8800", "#ff8800"])
        heat = preview_stops("heat")
        self.assertEqual(len(heat), len(THEMES["heat"].stops) + 1)
        self.assertEqual(heat[0], heat[-1])  # loops back, like the theme
        self.assertEqual(len(preview_stops("multi")), 7)
        self.assertEqual(preview_stops("nope"), [])

    def test_rejects_garbage(self):
        for bad in ("nope", "#ff88", "#gggggg"):
            with self.assertRaises(argparse.ArgumentTypeError):
                parse_color(bad)

    def test_themes(self):
        self.assertIs(parse_color("Heat"), THEMES["heat"])
        stops = THEMES["ocean"].stops
        rgb = theme_to_rgb(np.array([0.0, 0.25, 0.999999]), THEMES["ocean"])
        np.testing.assert_array_equal(rgb[:2], stops[:2])  # 4 stops: 0.25 is the second
        np.testing.assert_allclose(rgb[2], stops[0], atol=1)  # it loops back to the first

    def test_hue_to_rgb_primaries(self):
        rgb = hue_to_rgb(np.array([0.0, 1 / 3, 2 / 3]), s=1.0)
        np.testing.assert_array_equal(rgb, [[255, 0, 0], [0, 255, 0], [0, 0, 255]])


class Args(unittest.TestCase):
    def test_grid_has_a_minimum(self):
        self.assertEqual(parse_args(["--grid", "2"]).grid, MIN_GRID)

    def test_no_grid_means_pointer_sized(self):
        self.assertIsNone(parse_args([]).grid)  # the app picks it from the pointer size


class PointerCells(unittest.TestCase):
    def test_grid_follows_pointer_size(self):
        self.assertEqual(pointer_grid(900, 1.0), 900 // POINTER_PT)   # 50 cells, 18pt each
        self.assertEqual(pointer_grid(900, 2.0), 25)                   # bigger pointer, fewer cells
        self.assertEqual(pointer_grid(100, 4.0), MIN_GRID)             # never below the minimum
        self.assertEqual(pointer_grid(10000, 1.0), MAX_POINTER_GRID)   # nor above the cap

    def test_reads_the_macos_setting(self):
        def run(out, live=None):
            done = mock.Mock(stdout=out)
            with mock.patch("lifeinlife.pointer.subprocess.run", return_value=done), \
                    mock.patch("lifeinlife.pointer._live_scale", return_value=live):
                return pointer_scale()
        self.assertEqual(run("1.507943628533569\n"), 1.507943628533569)
        self.assertEqual(run("1.5\n", live=3.0), 1.5)  # the saved setting wins
        self.assertEqual(run(""), 1.0)       # never changed: no value saved
        self.assertEqual(run("99\n"), 1.0)   # out of range
        self.assertEqual(run("", live=2.0), 2.0)      # nothing saved: the live value
        self.assertEqual(run("99\n", live=2.0), 2.0)
        self.assertEqual(run("", live=99.0), 1.0)     # both unusable
        with mock.patch("lifeinlife.pointer.subprocess.run", side_effect=OSError), \
                mock.patch("lifeinlife.pointer._live_scale", return_value=None):
            self.assertEqual(pointer_scale(), 1.0)  # no `defaults` (not macOS)

    def test_rules_speed_and_edges(self):
        a = parse_args(["--rule", "highlife", "--inner-rule", "B2/S", "--speed", "4", "--edges", "dead"])
        self.assertEqual((a.rule, a.inner_rule.notation, a.speed, a.edges),
                         (PRESETS["highlife"], "B2/S", 4.0, "dead"))
        self.assertEqual(parse_args(["--speed", "100", "--fps", "30"]).speed, 30)  # at most fps
        self.assertIs(parse_args([]).color, None)
        self.assertIs(parse_args(["--color", "neon"]).color, THEMES["neon"])

    def test_bad_values_are_errors(self):
        for argv in (["--rule", "nope"], ["--speed", "0"], ["--speed", "fast"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit), \
                    contextlib.redirect_stderr(io.StringIO()):
                parse_args(argv)


class SettingsFile(unittest.TestCase):
    def test_speed_is_saved_with_colour_and_monitor(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings"
            settings.save(path, color="heat", monitor=2)
            settings.save(path, speed=settings.speed_text(4.0))
            self.assertEqual(settings.load(path), {"color": "heat", "speed": "4", "monitor": "2"})
            self.assertEqual(path.read_text(), "color=heat\nspeed=4\nmonitor=2\n")

    def test_hud_spots_round_trip(self):
        spots = {"ARZOPA": (20.0, 20.0), "LG ULTRAGEAR": (40.0, 120.5)}
        self.assertEqual(settings.hud_text(spots), "ARZOPA@20,20;LG ULTRAGEAR@40,120.5")
        self.assertEqual(settings.hud_spots(settings.hud_text(spots)), spots)
        self.assertEqual(settings.hud_spots("junk;A@1,2;B@x,y;@3,4"), {"A": (1.0, 2.0)})
        self.assertEqual(settings.hud_spots(None), {})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings"
            settings.save(path, color="red", hud="A@1,2")
            settings.save(path, speed="4")
            self.assertEqual(settings.load(path), {"color": "red", "speed": "4", "hud": "A@1,2"})

    def test_speed_labels_round_trip(self):
        for speed in (0.5, 1, 2, 30):
            self.assertEqual(settings.parse_speed(settings.speed_label(speed)), speed)
        self.assertEqual(settings.speed_label(1), "1 generation / second")
        with self.assertRaises(ValueError):
            settings.parse_speed("-1")


class SettingsDialog(unittest.TestCase):
    """choose() with the windows faked: each answer is what osascript would print."""
    WALL = "next\n" + settings.MODE_LABELS[settings.WALLPAPER]   # one monitor
    WIN = "next\n" + settings.MODE_LABELS[settings.WINDOW]
    SPEED2 = "next\n2 generations / second"
    WALL_B, WIN_B = "wallpaper:2\t2: B", "window:2\t2: B"   # two monitors: the option printed

    def run_choose(self, *answers, monitors=("1: A", "2: B"), mode=settings.WALLPAPER):
        replies, prompts = iter(answers), []

        def fake(_script, *args, **_k):
            prompts.append(args)
            return next(replies)
        with mock.patch.object(settings, "_osascript", fake), \
             mock.patch.object(settings, "monitor_labels", lambda: list(monitors)):
            picked = settings.choose("heat", 1, 4.0, mode, 800)
        self.prompts = prompts
        if picked is None:
            return None
        return tuple(picked[k] for k in ("color", "speed", "monitor", "mode", "size"))

    def test_save_on_colour_keeps_the_rest(self):
        self.assertEqual(self.run_choose("save\nred"), ("red", 4.0, 1, "wallpaper", 800))

    def test_save_on_speed_keeps_monitor(self):
        self.assertEqual(self.run_choose("next\nred", "save\n2 generations / second"),
                         ("red", 2.0, 1, "wallpaper", 800))

    def test_mode_and_monitor_are_one_window(self):
        self.assertEqual(self.run_choose("next\nred", self.SPEED2, "save\n" + self.WALL_B),
                         ("red", 2.0, 2, "wallpaper", 800))
        # A section per mode, each listing every monitor; the current one selected.
        options = self.prompts[2][4:]
        self.assertEqual(options, ("#\t" + settings.MODE_LABELS[settings.WALLPAPER],
                                   "wallpaper:1\t1: A", "wallpaper:2\t2: B",
                                   "#\t" + settings.MODE_LABELS[settings.WINDOW],
                                   "window:1\t1: A", "window:2\t2: B"))
        self.assertEqual(self.prompts[2][1], "wallpaper:1\t1: A")

    def test_a_heading_is_never_picked(self):
        heading = "#\t" + settings.MODE_LABELS[settings.WINDOW]
        self.assertEqual(self.run_choose("next\nred", self.SPEED2, "save\n" + heading),
                         ("red", 2.0, 1, "wallpaper", 800))

    def test_wallpaper_ends_after_where(self):
        self.assertEqual(self.run_choose("next\nred", self.SPEED2, "next\n" + self.WALL_B),
                         ("red", 2.0, 2, "wallpaper", 800))

    def test_window_mode_asks_for_a_size(self):
        self.assertEqual(self.run_choose("next\nred", self.SPEED2, "next\n" + self.WIN_B,
                                         "save\n" + settings.size_label(600)),
                         ("red", 2.0, 2, "window", 600))

    def test_back_from_size_keeps_the_place(self):
        self.assertEqual(self.run_choose("next\nred", self.SPEED2, "next\n" + self.WIN_B,
                                         "back\n" + settings.size_label(600), "save\n" + self.WIN_B),
                         ("red", 2.0, 2, "window", 600))
        self.assertEqual(self.prompts[4][1], self.WIN_B)  # shown selected on the way back

    def test_one_monitor_asks_only_the_mode(self):
        self.assertEqual(self.run_choose("next\nred", self.SPEED2, self.WIN,
                                         "next\n" + settings.size_label(1000), monitors=("1: A",)),
                         ("red", 2.0, 1, "window", 1000))
        self.assertEqual(self.run_choose("next\nred", self.SPEED2, self.WALL, monitors=()),
                         ("red", 2.0, 1, "wallpaper", 800))

    def test_back_keeps_what_was_picked(self):
        self.assertEqual(self.run_choose("next\nred", "back\n2 generations / second",
                                         "next\nblue", self.SPEED2, "save\n" + self.WALL_B),
                         ("blue", 2.0, 2, "wallpaper", 800))

    def test_custom_size(self):
        to_size = ("next\nred", self.SPEED2, "next\n" + self.WIN_B)
        custom = "save\n" + settings.CUSTOM_SIZE
        self.assertEqual(self.run_choose(*to_size, custom, "950"),
                         ("red", 2.0, 2, "window", 950))
        self.assertEqual(self.prompts[3][-1], settings.CUSTOM_SIZE)  # last in the size list
        # Cancelling the box, or a size too small, goes back to the size list.
        self.assertEqual(self.run_choose(*to_size, custom, "", "save\n" + settings.size_label(600)),
                         ("red", 2.0, 2, "window", 600))
        self.assertEqual(self.run_choose(*to_size, custom, "50", "", custom, "300"),
                         ("red", 2.0, 2, "window", 300))

    def test_hover_tick_box(self):
        to_place = ("next\nred", self.SPEED2)
        self.run_choose(*to_place, "save\n" + self.WALL_B + "\n1")
        self.assertIn("check:" + settings.HOVER_LABEL, self.prompts[2][2].split(","))
        self.assertNotIn("checked", self.prompts[2][2].split(","))  # off now: not ticked

    def test_hover_ticked_and_unticked(self):
        def hover(*answers, now=False):
            replies, flags = iter(answers), []

            def fake(_script, *args, **_k):
                flags.append(args[2])
                return next(replies)
            with mock.patch.object(settings, "_osascript", fake), \
                 mock.patch.object(settings, "monitor_labels", lambda: ["1: A", "2: B"]):
                picked = settings.choose("red", 1, 4.0, settings.WALLPAPER, 800, hover=now)
            return picked["hover"], flags
        self.assertEqual(hover("next\nred", self.SPEED2, "save\n" + self.WALL_B + "\n1")[0], True)
        on, flags = hover("next\nred", self.SPEED2, "save\n" + self.WALL_B + "\n0", now=True)
        self.assertFalse(on)
        self.assertIn("checked", flags[2].split(","))  # on now: shown ticked
        # Saved before reaching that window: unchanged.
        self.assertEqual(hover("save\nred", now=True)[0], True)

    def test_cancel(self):
        self.assertIsNone(self.run_choose("next\nred", ""))
        self.assertIsNone(self.run_choose(""))
        self.assertIsNone(self.run_choose("next\nred", self.SPEED2, ""))

    def test_parse_size(self):
        self.assertEqual(settings.parse_size("600"), 600)
        self.assertEqual(settings.parse_size(settings.size_label(1200)), 1200)
        for bad in ("", "abc", "50"):
            with self.assertRaises(ValueError):
                settings.parse_size(bad)


class ViewMaths(unittest.TestCase):
    def test_grid_covers_window(self):
        v = View(800, 600, 64)
        self.assertGreaterEqual(v.grid_px, 800)
        v.pan(10_000, 10_000)
        self.assertEqual((v.ox, v.oy), (0.0, 0.0))
        v.pan(-10_000, -10_000)
        self.assertAlmostEqual(v.ox + v.grid_px, 800)

    def test_cell_at_finds_the_cell_under_a_pixel(self):
        v = View(640, 640, 64)  # 10 px cells, no offset
        self.assertEqual(v.cell_at(0, 0), (0, 0))
        self.assertEqual(v.cell_at(55, 21), (2, 5))
        self.assertIsNone(v.cell_at(640, 10))  # just past the right edge
        v.zoom_at(2.0, 0, 0)  # 20 px cells, still anchored top-left
        self.assertEqual(v.cell_at(55, 21), (1, 2))

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

    def test_smooth_zoom_glides_to_target_around_anchor(self):
        v = View(1000, 1000, 50)
        v.zoom_smooth(2.0, 300, 400)
        self.assertEqual(v.zoom, 1.0)  # nothing yet
        self.assertTrue(v.easing)
        before = ((300 - v.ox) / v.cell, (400 - v.oy) / v.cell)
        v.ease(1 / 30)
        self.assertTrue(1.0 < v.zoom < 2.0)
        for _ in range(60):
            v.ease(1 / 30)
        self.assertEqual(v.zoom, 2.0)
        self.assertFalse(v.easing)
        np.testing.assert_allclose(((300 - v.ox) / v.cell, (400 - v.oy) / v.cell), before)

    def test_smooth_zoom_is_clamped_and_instant_zoom_cancels_it(self):
        v = View(100, 100, 10)
        for _ in range(30):
            v.zoom_smooth(2.0, 50, 50)
        self.assertEqual(v.target_zoom, MAX_ZOOM)
        v.zoom_at(1.5, 50, 50)
        self.assertFalse(v.easing)

    def test_visible_cells_zoomed_out_is_everything(self):
        self.assertEqual(View(640, 640, 64).visible_cells(), (0, 64, 0, 64))


if __name__ == "__main__":
    unittest.main()
