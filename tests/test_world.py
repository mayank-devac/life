import unittest

import numpy as np

from lifeinlife.colors import THEMES
from lifeinlife.config import AGE_DIM, HISTORY, MACRO_EVERY, MICRO_SIZE, STALE_STEPS, TRAIL_ALPHA
from lifeinlife.rules import CONWAY, PRESETS, next_preset, parse_rule, step
from lifeinlife.world import World, find_parents, neighbor_sum, step_colored, step_life


def grid_with(cells, size=8):
    g = np.zeros((size, size), dtype=np.uint8)
    for r, c in cells:
        g[r, c] = 1
    return g


def empty_world(size=16, **kw):
    w = World(size, **kw)
    w.macro[:] = 0
    w.alive_for[:] = 0
    return w


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

    def test_dead_edges_dont_wrap(self):
        g = grid_with([(0, 0)], size=5)
        n = neighbor_sum(g, wrap=False)
        self.assertEqual(n[4, 4], 0)
        self.assertEqual((n[0, 1], n[1, 1], n[0, 0]), (1, 1, 0))

    def test_glider_dies_into_a_dead_edge_but_lives_on_a_torus(self):
        glider = grid_with([(0, 1), (1, 2), (2, 0), (2, 1), (2, 2)], size=10)
        wrapped = dead = glider
        for _ in range(80):
            wrapped, dead = step_life(wrapped, wrap=True), step_life(dead, wrap=False)
        self.assertEqual(int(wrapped.sum()), 5)
        self.assertNotEqual(int(dead.sum()), 5)  # it hit the corner and became a block

    def test_neighbor_sum_over_a_stack_matches_one_at_a_time(self):
        rng = np.random.default_rng(0)
        stack = (rng.random((5, 7, 9, 9)) < 0.4).astype(np.uint8)
        together = neighbor_sum(stack, axes=(2, 3))
        for i in range(5):
            for j in range(7):
                np.testing.assert_array_equal(together[i, j], neighbor_sum(stack[i, j]))


class RuleParsing(unittest.TestCase):
    def test_presets_and_notation(self):
        self.assertIs(parse_rule("conway"), CONWAY)
        self.assertIs(parse_rule("B3/S23"), CONWAY)       # known notation -> its name
        self.assertIs(parse_rule("s23/b3"), CONWAY)       # either order, any case
        self.assertIs(parse_rule("Day & Night"), PRESETS["daynight"])
        custom = parse_rule("B36/S125")
        self.assertEqual((custom.name, custom.birth, custom.survive), ("B36/S125", {3, 6}, {1, 2, 5}))
        self.assertEqual(parse_rule("seeds").notation, "B2/S")

    def test_rejects_garbage_and_b0(self):
        for bad in ("nope", "B9/S2", "B3S23", "B03/S23"):
            with self.assertRaises(ValueError):
                parse_rule(bad)

    def test_highlife_replicator_differs_from_conway(self):
        # B6: a dead cell with six live neighbours is born in HighLife, not in Conway.
        g = grid_with([(1, 1), (1, 2), (1, 3), (3, 1), (3, 2), (3, 3)])
        self.assertEqual(step(g, PRESETS["highlife"])[2, 2], 1)
        self.assertEqual(step(g, CONWAY)[2, 2], 0)

    def test_next_preset_cycles(self):
        rules = list(PRESETS.values())
        self.assertIs(next_preset(rules[0]), rules[1])
        self.assertIs(next_preset(rules[-1]), rules[0])
        self.assertIs(next_preset(parse_rule("B1/S1")), rules[0])


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

    def test_switching_to_a_theme_keeps_hues(self):
        np.random.seed(2)
        w = World(16)
        hue = w.hue.copy()
        w.set_color(THEMES["ocean"])
        np.testing.assert_array_equal(w.hue, hue)
        w.set_color((1, 2, 3))
        self.assertIsNone(w.hue)


class InnerWorlds(unittest.TestCase):
    def setUp(self):
        np.random.seed(5)

    def test_every_cell_has_its_own_inner_world(self):
        w = World(8)
        self.assertEqual(w.inner.shape, (8, 8, MICRO_SIZE, MICRO_SIZE))
        self.assertFalse((w.inner[0, 0] == w.inner[0, 1]).all())

    def test_inner_worlds_step_only_in_the_region(self):
        w = World(8)
        w.macro[:] = 1
        before = w.inner.copy()
        w.step(region=(0, 4, 0, 4))
        self.assertFalse((w.inner[:4, :4] == before[:4, :4]).all())
        np.testing.assert_array_equal(w.inner[4:], before[4:])   # off screen: frozen
        before = w.inner.copy()
        w.step()                                                 # zoomed out: nothing
        np.testing.assert_array_equal(w.inner, before)

    def test_inner_world_follows_its_rule(self):
        w = World(4, inner_rule=PRESETS["seeds"])
        w.macro[:] = 1
        w.inner[0, 0] = 0
        w.inner[0, 0, 5, 5] = w.inner[0, 0, 5, 6] = 1   # Seeds: B2 births around the pair
        w._step_inner((0, 1, 0, 1))
        expected = step(grid_with([(5, 5), (5, 6)], MICRO_SIZE), PRESETS["seeds"])
        np.testing.assert_array_equal(w.inner[0, 0], expected)

    def test_empty_inner_world_is_reseeded(self):
        w = World(4)
        w.macro[:] = 1
        w.inner[1, 2] = 0
        w._step_inner((0, 4, 0, 4))
        self.assertGreater(int(w.inner[1, 2].sum()), 0)

    def test_newborn_inherits_a_parents_world(self):
        w = empty_world(8)
        for r, c in [(2, 2), (2, 3), (3, 2)]:   # an L: (3, 3) is born
            w.macro[r, c] = 1
        w.inner[2, 2] = w.inner[2, 3] = w.inner[3, 2] = 0
        w.inner[2, 2, :, :8] = 1                 # three distinct parent worlds
        w.inner[2, 3, :8, :] = 1
        w.inner[3, 2, ::2] = 1
        parents = [w.inner[p].copy() for p in [(2, 2), (2, 3), (3, 2)]]
        w._step_macro()
        child = w.inner[3, 3]
        diffs = [int((child != p).sum()) for p in parents]
        self.assertLess(min(diffs), MICRO_SIZE * MICRO_SIZE * 0.1)  # a copy, a few cells flipped

    def test_find_parents_respects_edges(self):
        old = grid_with([(0, 0)], size=5)
        rows, cols = np.array([4]), np.array([4])
        self.assertEqual(find_parents(old, rows, cols, wrap=True), ([0], [0]))
        pr, _ = find_parents(old, rows, cols, wrap=False)
        self.assertEqual(int(pr[0]), -1)


class Effects(unittest.TestCase):
    def setUp(self):
        np.random.seed(1)

    def test_dead_cell_leaves_a_fading_ghost(self):
        w = empty_world(color=(200, 100, 50))
        w.macro[5, 5] = 1          # alone: dies next step
        w._step_macro()
        a1 = int(w.rgba()[5, 5, 3])
        self.assertAlmostEqual(a1, TRAIL_ALPHA * 255, delta=1)
        w._step_macro()
        a2 = int(w.rgba()[5, 5, 3])
        self.assertTrue(0 < a2 < a1)
        for _ in range(10):
            w._step_macro()
        self.assertEqual(int(w.rgba()[5, 5, 3]), 0)

    def test_newborns_flash_and_cells_brighten_with_age(self):
        w = empty_world(color=(200, 0, 0))
        block = [(2, 2), (2, 3), (3, 2), (3, 3)]
        for r, c in block:
            w.macro[r, c] = 1
        w.alive_for[w.macro == 1] = 1          # just born
        flash = w.rgba()[2, 2].copy()
        self.assertGreater(int(flash[1]), 0)   # mixed towards white
        w.alive_for[w.macro == 1] = 2
        w.generation += 1
        young = w.rgba()[2, 2].copy()
        self.assertAlmostEqual(int(young[0]), 200 * (AGE_DIM + (1 - AGE_DIM) * 2 / 20), delta=1)
        for _ in range(30):
            w._step_macro()                    # the block is still: it ages
        self.assertEqual(tuple(w.rgba()[2, 2]), (200, 0, 0, 255))

    def test_effects_off_is_plain(self):
        w = World(16, color=(10, 20, 30), effects=False)
        for _ in range(3 * MACRO_EVERY):
            w.step()
        rgba = w.rgba()
        self.assertTrue((rgba[w.macro == 1] == (10, 20, 30, 255)).all())
        self.assertTrue((rgba[w.macro == 0][:, 3] == 0).all())

    def test_toggling_effects_redraws(self):
        w = World(16)
        gen = w.generation
        w.set_effects(False)
        self.assertGreater(w.generation, gen)


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

    def test_speed_sets_frames_per_step(self):
        w = World(16, macro_every=4)
        for _ in range(8):
            w.step()
        self.assertEqual(w.age, 2)

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

    def test_long_period_oscillator_counts_as_settled(self):
        # A pulsar (period 3) next to a blinker (period 2): the world repeats every 6.
        w = empty_world(24)
        pulsar = [(r, c) for r in (0, 5, 7, 12) for c in (2, 3, 4, 8, 9, 10)] + \
                 [(r, c) for r in (2, 3, 4, 8, 9, 10) for c in (0, 5, 7, 12)]
        for r, c in pulsar:
            w.macro[r + 2, c + 2] = 1
        for c in (19, 20, 21):
            w.macro[20, c] = 1
        self.assertLess(6, HISTORY)
        settled = any(w._step_macro() for _ in range(STALE_STEPS + 6))
        self.assertTrue(settled)

    def test_moving_glider_is_not_settled(self):
        w = empty_world(32)
        for r, c in [(0, 1), (1, 2), (2, 0), (2, 1), (2, 2)]:
            w.macro[r, c] = 1
        self.assertFalse(any(w._step_macro() for _ in range(STALE_STEPS + 20)))

    def test_rule_change_carries_on(self):
        w = World(16)
        macro = w.macro.copy()
        w.set_rule(rule=PRESETS["seeds"], wrap=False)
        np.testing.assert_array_equal(w.macro, macro)
        self.assertEqual((w.rule, w.wrap, w.stale, w.history), (PRESETS["seeds"], False, 0, []))

    def test_single_colour_skips_hues(self):
        w = World(16, color=(10, 20, 30))
        self.assertIsNone(w.hue)
        for _ in range(MACRO_EVERY * 2):
            w.step()
        self.assertTrue((w.rgb == (10, 20, 30)).all())

    def test_themes_track_hues(self):
        w = World(16, color=THEMES["heat"])
        self.assertIsNotNone(w.hue)
        for _ in range(MACRO_EVERY * 2):
            w.step()
        self.assertEqual(w.rgb.shape, (16, 16, 3))

    def test_toggle_adds_and_removes_a_cell(self):
        for color in (None, (10, 20, 30), THEMES["neon"]):
            w = World(16, color=color)
            w.macro[:] = 0
            gen = w.generation
            self.assertTrue(w.toggle(3, 5))
            self.assertEqual((w.population, int(w.macro[3, 5])), (1, 1))
            self.assertGreater(w.inner[3, 5].sum(), 0)
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
