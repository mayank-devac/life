import tempfile
import unittest
from pathlib import Path

import numpy as np

from lifeinlife import patterns
from lifeinlife.config import REWIND, STALE_STEPS
from lifeinlife.rules import step
from lifeinlife.world import World


def run(grid, n, wrap=False):
    for _ in range(n):
        grid = step(grid, wrap=wrap)
    return grid


def padded(pattern, size, at=(0, 0)):
    g = np.zeros((size, size), dtype=np.uint8)
    h, w = pattern.shape
    g[at[0]:at[0] + h, at[1]:at[1] + w] = pattern
    return g


class Brushes(unittest.TestCase):
    def test_glider_moves(self):
        g = padded(patterns.GLIDER, 12, (2, 2))
        np.testing.assert_array_equal(run(g, 4), np.roll(np.roll(g, 1, 0), 1, 1))

    def test_lwss_moves_two_cells_in_four_generations(self):
        g = padded(patterns.LWSS, 20, (8, 8))
        moved = run(g, 4)
        self.assertEqual(int(moved.sum()), int(g.sum()))
        self.assertTrue(np.array_equal(moved, np.roll(g, 2, 1)) or
                        np.array_equal(moved, np.roll(g, -2, 1)))

    def test_pulsar_has_period_three(self):
        g = padded(patterns.PULSAR, 21, (4, 4))
        np.testing.assert_array_equal(run(g, 3), g)
        self.assertFalse(np.array_equal(run(g, 1), g))

    def test_gosper_gun_fires_gliders(self):
        g = padded(patterns.GOSPER_GUN, 80, (2, 2))
        self.assertEqual(patterns.GOSPER_GUN.shape, (9, 36))
        self.assertEqual(int(g.sum()), 36)
        # Period 30: every cycle adds one glider (5 cells) to the gun's population.
        self.assertEqual(int(run(g, 120).sum()), 36 + 4 * 5)

    def test_methuselahs_keep_going(self):
        self.assertGreater(int(run(padded(patterns.R_PENTOMINO, 120, (58, 58)), 100).sum()), 20)
        self.assertGreater(int(run(padded(patterns.ACORN, 120, (58, 56)), 100).sum()), 20)

    def test_rotation(self):
        r = patterns.rotated(patterns.GLIDER, 1)
        np.testing.assert_array_equal(r, np.rot90(patterns.GLIDER, -1))
        np.testing.assert_array_equal(patterns.rotated(patterns.GLIDER, 4), patterns.GLIDER)
        self.assertEqual(patterns.rotated(patterns.GOSPER_GUN, 1).shape, (36, 9))


class Rle(unittest.TestCase):
    def test_parse_glider(self):
        grid, rule = patterns.parse_rle("#N Glider\nx = 3, y = 3, rule = B3/S23\nbo$2bo$3o!")
        np.testing.assert_array_equal(grid, patterns.GLIDER)
        self.assertEqual(rule, "B3/S23")

    def test_round_trip(self):
        g = np.random.default_rng(1).random((40, 40)) < 0.3
        g = g.astype(np.uint8)
        g[-3:] = 0  # trailing empty rows are left out of the body but kept in the header
        g[:2] = 0   # and leading ones written as "$"
        text = patterns.to_rle(g, "B36/S23", name="test")
        back, rule = patterns.parse_rle(text)
        np.testing.assert_array_equal(back, g)
        self.assertEqual(rule, "B36/S23")
        self.assertTrue(all(len(line) <= 70 for line in text.splitlines()))

    def test_bad_files(self):
        with self.assertRaises(ValueError):
            patterns.parse_rle("hello")
        with self.assertRaises(ValueError):
            patterns.parse_cells("!comment\nabc")

    def test_cells_and_load(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "glider.cells"
            p.write_text("!Name: Glider\n.O\n..O\nOOO\n")
            grid, rule = patterns.load(p)
            np.testing.assert_array_equal(grid, patterns.GLIDER)
            self.assertIsNone(rule)


class WorldEditing(unittest.TestCase):
    def test_stamp_centres_and_wraps(self):
        w = World(16)
        w.clear()
        self.assertEqual(w.stamp(patterns.GLIDER, 0, 0), 5)
        self.assertEqual(w.population, 5)
        self.assertEqual(w.macro[15, 0], 1)  # top row of the glider wrapped to the bottom

    def test_stamp_is_cut_off_without_wrap(self):
        w = World(16, wrap=False)
        w.clear()
        self.assertEqual(w.stamp(patterns.GLIDER, 0, 0), 3)

    def test_stamp_one_colour(self):
        w = World(16)
        w.clear()
        w.stamp(patterns.PULSAR, 8, 8)
        hues = w.hue[w.macro == 1]
        self.assertTrue(np.allclose(hues, hues[0]))

    def test_paint_and_erase(self):
        w = World(16)
        w.clear()
        w.set_cells([1, 2, 3], [1, 1, 1], True)
        self.assertEqual(w.population, 3)
        w.set_cells([2], [1], False)
        self.assertEqual(w.population, 2)

    def test_cleared_world_is_not_reseeded(self):
        w = World(16)
        w.clear()
        for _ in range(STALE_STEPS + 5):
            self.assertFalse(w._step_macro())
        self.assertEqual(w.population, 0)

    def test_reseeds_again_once_it_had_cells(self):
        w = World(16)
        w.clear()
        w.set_cells([5, 5, 6, 6], [5, 6, 5, 6], True)  # a block: still life
        settled = any(w._step_macro() for _ in range(STALE_STEPS + 5))
        self.assertTrue(settled)

    def test_load_places_a_full_size_world_exactly(self):
        w = World(20)
        g = (np.random.default_rng(2).random((20, 20)) < 0.3).astype(np.uint8)
        self.assertFalse(w.load(g))
        np.testing.assert_array_equal(w.macro, g)

    def test_load_centres_small_and_crops_big(self):
        w = World(20)
        w.load(patterns.GLIDER)
        self.assertEqual(w.population, 5)
        self.assertEqual(w.macro[9:12, 9:12].sum(), 5)
        self.assertTrue(w.load(np.ones((30, 30), dtype=np.uint8)))
        self.assertEqual(w.population, 400)


class Rewind(unittest.TestCase):
    def test_step_back_restores_earlier_generations(self):
        w = World(24)
        states = []
        for _ in range(10):
            states.append((w.macro.copy(), w.age))
            w._step_macro()
        for macro, age in reversed(states):
            self.assertTrue(w.step_back())
            np.testing.assert_array_equal(w.macro, macro)
            self.assertEqual(w.age, age)
        self.assertFalse(w.step_back())

    def test_keeps_only_the_last_few_hundred(self):
        w = World(12)
        w.clear()
        w.set_cells([1, 1, 1], [1, 2, 3], True)  # a blinker: changes every step
        for _ in range(REWIND + 50):
            w._step_macro()
        self.assertEqual(len(w.rewind), REWIND)

    def test_undo_clear(self):
        w = World(16)
        before = w.macro.copy()
        w.checkpoint()
        w.clear()
        w.step_back()
        np.testing.assert_array_equal(w.macro, before)

    def test_checkpoint_skips_duplicates(self):
        w = World(16)
        w.checkpoint()
        w.checkpoint()
        self.assertEqual(len(w.rewind), 1)


if __name__ == "__main__":
    unittest.main()
