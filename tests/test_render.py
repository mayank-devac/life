"""Pixel tests: the fast renderer must draw exactly what a plain per-cell loop draws.
Needs a display (they open a hidden window); skipped where there is none."""
import unittest

import numpy as np

import lifeinlife  # noqa: F401 - sets SDL hints before pygame loads
import pygame
from pygame._sdl2.video import Renderer, Texture

from lifeinlife.config import CLEAR_BG, OUTLINE_ALPHA, SOLID_BG
from lifeinlife.render import Painter
from lifeinlife.view import View
from lifeinlife.world import World

SIZE = 600


def reference_cells(ren, world, view, bg, dpr=1.0):
    """The original renderer: one fill_rect per live cell."""
    ren.draw_color = bg
    ren.clear()
    size = view.cell - max(1.0, dpr)
    r0, r1, c0, c1 = view.visible_cells()
    for r in range(r0, r1):
        for c in range(c0, c1):
            if world.macro[r, c]:
                rgb = world.rgb[r, c]
                ren.draw_color = (int(rgb[0]), int(rgb[1]), int(rgb[2]), 255)
                ren.fill_rect((view.ox + c * view.cell, view.oy + r * view.cell, size, size))


def reference_detail(ren, world, view, bg, dpr=1.0):
    """Zoomed in, the slow way: one fill_rect per live inner cell of every live outer cell,
    each inner cell inset by the same gaps the fast renderer cuts."""
    ren.draw_color = bg
    ren.clear()
    gap, cell, m = max(1.0, dpr), view.cell, world.micro_size
    inner = cell / m
    inner_gap = max(1.0, inner / 8) if inner >= 4 * max(1.0, dpr) else 0.0
    r0, r1, c0, c1 = view.visible_cells()
    for r in range(r0, r1):
        for c in range(c0, c1):
            if world.macro[r, c]:
                x, y = view.ox + c * cell, view.oy + r * cell
                rgb = world.rgb[r, c]
                ren.draw_color = (int(rgb[0]), int(rgb[1]), int(rgb[2]), 255)
                for i in range(m):
                    for j in range(m):
                        if world.inner[r, c, i, j]:
                            w = inner - (gap if j == m - 1 else inner_gap)
                            h = inner - (gap if i == m - 1 else inner_gap)
                            ren.fill_rect((x + j * inner, y + i * inner, w, h))
    for r in range(r0, r1):
        for c in range(c0, c1):
            if world.macro[r, c]:
                x, y = view.ox + c * cell, view.oy + r * cell
                rgb = world.rgb[r, c]
                ren.draw_color = (int(rgb[0]), int(rgb[1]), int(rgb[2]), OUTLINE_ALPHA)
                ren.draw_rect((x, y, cell - gap, cell - gap))


class RenderMatchesReference(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        try:
            cls.window = pygame.Window("test", (SIZE, SIZE), hidden=True)
            cls.ren = Renderer(cls.window)
        except pygame.error as exc:
            pygame.quit()
            raise unittest.SkipTest(f"no display: {exc}")
        cls.ren.draw_blend_mode = pygame.BLENDMODE_BLEND

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def pixels(self):
        return pygame.surfarray.array3d(self.ren.to_surface()).astype(int)

    def compare(self, zoom, pan, bg, reference, grid=98, color=None, tolerance=0):
        np.random.seed(7)
        world = World(grid, color, effects=False)  # the references draw plain cells
        for _ in range(3):
            world.step()
        view = View(SIZE, SIZE, grid)
        view.zoom_at(zoom, SIZE / 2, SIZE / 2)
        view.pan(-pan, -pan * 0.7)

        Painter(self.ren, 1.0).draw(world, view, bg, present=False)
        fast = self.pixels()
        reference(self.ren, world, view, bg)
        slow = self.pixels()
        diff = np.abs(fast - slow).max(-1)
        bad = int((diff > 0).sum())
        self.assertLessEqual(bad, tolerance * diff.size,
                             f"{bad} pixels differ (max {diff.max()})")

    def test_zoomed_out(self):
        self.compare(1.0, 0, SOLID_BG, reference_cells)

    def test_zoomed_out_fractional_pan(self):
        self.compare(1.7, 133.3, SOLID_BG, reference_cells)

    def test_zoomed_out_transparent_single_colour(self):
        self.compare(1.3, 40.5, CLEAR_BG, reference_cells, color=(240, 110, 180))

    def test_zoomed_out_many_positions(self):
        # Sweep zooms and pans, including ones where cell edges land exactly on pixel centres.
        rng = np.random.default_rng(0)
        for zoom, pan in [(1.3, 40.5), (1.0, 0.5), (2.0, 99.5)] + \
                         [(rng.uniform(1, 2.19), rng.uniform(0, 300)) for _ in range(12)]:
            with self.subTest(zoom=zoom, pan=pan):
                self.compare(zoom, pan, CLEAR_BG, reference_cells)

    # Zoomed in, a scaled texture and fill_rects round a few edge pixels differently.
    def test_zoomed_in(self):
        self.compare(3.0, 210.6, SOLID_BG, reference_detail, tolerance=0.01)

    def test_zoomed_in_max(self):
        self.compare(8.0, 1234.5, CLEAR_BG, reference_detail, grid=40, tolerance=0.01)

    def test_zoomed_in_shows_each_cells_own_world(self):
        np.random.seed(4)
        world, view = World(32, (255, 255, 255), effects=False), View(SIZE, SIZE, 32)
        world.macro[:] = 1
        view.zoom_at(8.0, 0, 0)
        cell = view.cell
        world.inner[0, 0] = 1   # top-left cell full, its neighbour empty
        world.inner[0, 1] = 0
        Painter(self.ren, 1.0).draw(world, view, SOLID_BG, present=False)
        px = self.pixels()
        mid = int(cell / 2)
        self.assertEqual(tuple(px[mid, mid]), (255, 255, 255))           # surfarray is (x, y)
        self.assertEqual(tuple(px[int(cell) + mid, mid]), SOLID_BG[:3])

    def test_ghosts_are_drawn_faintly(self):
        np.random.seed(4)
        world, view = World(32, (255, 255, 255)), View(SIZE, SIZE, 32)
        world.macro[:] = 0
        world.ghost[:] = 1.0
        world.generation += 1
        Painter(self.ren, 1.0).draw(world, view, (0, 0, 0, 255), present=False)
        level = int(self.pixels()[5, 5, 0])
        self.assertTrue(60 < level < 200, level)

    def test_identical_frame_is_skipped(self):
        np.random.seed(3)
        world, view = World(32), View(SIZE, SIZE, 32)
        painter = Painter(self.ren, 1.0)
        self.assertTrue(painter.draw(world, view, SOLID_BG))
        self.assertFalse(painter.draw(world, view, SOLID_BG))   # nothing changed
        for _ in range(15):
            world.step()                                         # outer world stepped
        self.assertTrue(painter.draw(world, view, SOLID_BG))
        painter.invalidate()
        self.assertTrue(painter.draw(world, view, SOLID_BG))


if __name__ == "__main__":
    unittest.main()
