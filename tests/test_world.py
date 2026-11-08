import unittest

import numpy as np

from lifeinlife.config import MACRO_EVERY, STALE_STEPS
from lifeinlife.world import World, neighbor_sum, seed_micro, step_colored, step_life


def grid_with(cells, size=8):
    g = np.zeros((size, size), dtype=np.uint8)
    for r, c in cells:
        g[r, c] = 1
    return g


class LifeRules(unittest.TestCase):
    def test_block_is_still(self):
        block = grid_with([(2, 2), (2, 3), (3, 2), (3, 3)])
        np.testing.assert_array_equal(step_life(block), block)

    def test_blinker_has_period_two(self):
        horizontal = grid_with([(3, 2), (3, 3), (3, 4)])
        vertical = grid_with([(2, 3), (3, 3), (4, 3)])
        np.testing.assert_array_equal(step_life(horizontal), vertical)
        np.testing.assert_array_equal(step_life(vertical), horizontal)

    def test_glider_moves_one_cell_diagonally_every_four_steps(self):
        glider = grid_with([(0, 1), (1, 2), (2, 0), (2, 1), (2, 2)], size=10)
        g = glider
        for _ in range(4):
            g = step_life(g)
        np.testing.assert_array_equal(g, np.roll(np.roll(glider, 1, 0), 1, 1))

    def test_edges_wrap_around(self):
        g = grid_with([(0, 0)], size=5)
        n = neighbor_sum(g)
        self.assertEqual(n[4, 4], 1)  # opposite corner touches (0, 0) across both edges
        self.assertEqual(n[0, 0], 0)  # a cell is not its own neighbour

    def test_inner_seed_never_dies(self):
        g = seed_micro()
        for _ in range(500):
            g = step_life(g)
        self.assertGreater(int(g.sum()), 0)


class Colours(unittest.TestCase):
    def test_newborn_takes_parents_hue(self):
        # An L of three parents all with hue 0.25 gives birth to the fourth corner.
        g = grid_with([(2, 2), (2, 3), (3, 2)])
        hue = np.zeros(g.shape)
        hue[g == 1] = 0.25
        new, new_hue = step_colored(g, hue)
        self.assertEqual(new[3, 3], 1)
        self.assertAlmostEqual(new_hue[3, 3], 0.25, delta=0.041)  # MUTATION = 0.04

    def test_hue_average_wraps_around_red(self):
        # 0.95 and 0.05 are both near red: the average must be red (0), not cyan (0.5).
        g = grid_with([(2, 2), (2, 3), (3, 2)])
        hue = np.zeros(g.shape)
        hue[2, 2], hue[2, 3], hue[3, 2] = 0.95, 0.05, 0.0
        _, new_hue = step_colored(g, hue)
        self.assertLess(min(new_hue[3, 3], 1 - new_hue[3, 3]), 0.05)


class WorldBehaviour(unittest.TestCase):
    def setUp(self):
        np.random.seed(1)

    def test_outer_world_steps_every_macro_every_frames(self):
        w = World(16)
        gens = []
        for _ in range(3 * MACRO_EVERY):
            w.step()
            gens.append(w.generation)
        # generation bumps on frames 0, MACRO_EVERY, 2*MACRO_EVERY (unless it reseeded)
        self.assertEqual(len(set(gens)), 3)

    def test_frames_to_macro_step_counts_down(self):
        w = World(16)
        self.assertEqual(w.frames_to_macro_step(), 0)
        w.step()
        self.assertEqual(w.frames_to_macro_step(), MACRO_EVERY - 1)

    def test_dead_world_is_reseeded(self):
        w = World(16)
        w.macro[:] = 0
        settled = False
        for _ in range((STALE_STEPS + 1) * MACRO_EVERY):
            settled = settled or w.step()
        self.assertTrue(settled)
        self.assertGreater(int(w.macro.sum()), 0)

    def test_single_colour_skips_hues(self):
        w = World(16, color=(10, 20, 30))
        self.assertIsNone(w.hue)
        for _ in range(MACRO_EVERY * 2):
            w.step()
        self.assertTrue((w.rgb == (10, 20, 30)).all())

    def test_toggle_adds_and_removes_a_cell(self):
        for color in (None, (10, 20, 30)):  # multicolour and single colour
            w = World(16, color=color)
            w.macro[:] = 0
            gen = w.generation
            self.assertTrue(w.toggle(3, 5))
            self.assertEqual((w.population, int(w.macro[3, 5])), (1, 1))
            self.assertGreater(w.generation, gen)  # renderer must redraw
            self.assertFalse(w.toggle(3, 5))
            self.assertEqual(w.population, 0)

    def test_age_counts_outer_steps_and_resets_on_reseed(self):
        w = World(16)
        for _ in range(2 * MACRO_EVERY):
            w.step()
        self.assertEqual(w.age, 2)
        w.reseed()
        self.assertEqual(w.age, 0)


if __name__ == "__main__":
    unittest.main()
