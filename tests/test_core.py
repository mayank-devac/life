"""The C core (_core.c) must give exactly what the numpy code gives. Skipped if it isn't built
(python setup.py build_ext --inplace)."""
import unittest

import numpy as np

from lifeinlife import world as world_mod
from lifeinlife.render import inner_pixels
from lifeinlife.rules import PRESETS, step
from lifeinlife.world import INNER_THRESHOLD, World

core = world_mod._core


@unittest.skipIf(core is None, "C core not built")
class CoreMatchesNumpy(unittest.TestCase):
    def setUp(self):
        np.random.seed(7)
        self.w = World(20)

    def test_step_inner_every_rule(self):
        w, region = self.w, (2, 15, 3, 18)
        for rule in PRESETS.values():
            before = w.inner.copy()
            r0, r1, c0, c1 = region
            live = w.macro[r0:r1, c0:c1] == 1
            want = before.copy()
            sub = want[r0:r1, c0:c1]
            sub[live] = step(sub[live], rule, wrap=True, axes=(1, 2))
            core.step_inner(w.inner, w.macro, w.size, w.micro_size, region, *rule.masks,
                            INNER_THRESHOLD)
            got = w.inner
            # Worlds that died out are reseeded randomly: compare all the others exactly.
            keep = want.reshape(w.size, w.size, -1).any(axis=2)
            self.assertTrue(np.array_equal(got[keep], want[keep]), rule.name)
            reseeded = ~keep
            self.assertTrue(got[reseeded].reshape(-1, w.micro_size ** 2).any(axis=1).all())

    def test_step_inner_leaves_dead_and_offscreen_cells(self):
        w = self.w
        before = w.inner.copy()
        core.step_inner(w.inner, w.macro, w.size, w.micro_size, (5, 10, 5, 10),
                        *w.inner_rule.masks, INNER_THRESHOLD)
        changed = (w.inner != before).reshape(w.size, w.size, -1).any(axis=2)
        mask = np.zeros_like(changed)
        mask[5:10, 5:10] = w.macro[5:10, 5:10] == 1
        self.assertFalse((changed & ~mask).any())

    def test_inner_pixels(self):
        w = self.w
        w.step((0, 20, 0, 20))
        for region in [(0, 20, 0, 20), (3, 9, 11, 17), (0, 1, 0, 1)]:
            want = inner_pixels(w, region)
            h, wd = want.shape[:2]
            buf = bytearray(h * wd * 4 + 100)  # bigger than needed, like the reused buffer
            size = core.inner_pixels(buf, np.ascontiguousarray(w.rgba()), w.inner, w.size,
                                     w.micro_size, region)
            self.assertEqual(size, (wd, h))
            got = np.frombuffer(buf, np.uint8, h * wd * 4).reshape(h, wd, 4)
            self.assertTrue(np.array_equal(got[..., [2, 1, 0, 3]], want))  # BGRA -> RGBA

    def test_inherit_inner(self):
        size, m = 6, 16
        inner = np.zeros((size, size, m, m), np.uint8)
        old = np.zeros((size, size), np.uint8)
        old[0, 0] = 1
        inner[0, 0] = 1                      # the only parent: a full world
        born = np.zeros((size, size), np.uint8)
        born[0, 1] = born[5, 5] = born[3, 3] = 1
        core.inherit_inner(inner, old, born, size, m, True, 90, round(0.02 * 65536))
        child = inner[0, 1]
        self.assertGreater(child.sum(), m * m * 0.9)  # a copy, a few cells flipped
        self.assertLess(child.sum(), m * m)
        self.assertGreater(inner[5, 5].sum(), m * m * 0.9)  # (0, 0) is its neighbour across the edge
        orphan = inner[3, 3].sum()                   # no live neighbour: random, ~35% alive
        self.assertTrue(0.15 * m * m < orphan < 0.55 * m * m)
        self.assertEqual(inner[2, 2].sum(), 0)       # not born: untouched
        inner[5, 5] = 0
        core.inherit_inner(inner, old, born, size, m, False, 90, 0)
        self.assertLess(inner[5, 5].sum(), m * m * 0.6)  # no wrap: no parent, random world
        self.assertTrue(np.array_equal(inner[0, 1], inner[0, 0]))  # flip 0: an exact copy

    def test_bad_buffers_raise(self):
        w = self.w
        with self.assertRaises(ValueError):
            core.inner_pixels(bytearray(10), w.rgba(), w.inner, w.size, w.micro_size, (0, 5, 0, 5))
        with self.assertRaises(ValueError):
            core.step_inner(w.inner[:2], w.macro, w.size, w.micro_size, (0, 5, 0, 5), 8, 12, 90)

    def test_world_uses_it_and_keeps_live_cells_busy(self):
        w = self.w
        for _ in range(50):
            w.step((0, 20, 0, 20))
        alive = w.macro == 1
        self.assertTrue(w.inner[alive].reshape(-1, w.micro_size ** 2).any(axis=1).all())


if __name__ == "__main__":
    unittest.main()
