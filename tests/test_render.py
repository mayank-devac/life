"""Pixel tests: the fast renderer must draw exactly what a plain per-cell loop draws.
Needs a display (they open a hidden window); skipped where there is none."""
import unittest

import numpy as np

import lifeinlife  # noqa: F401 - sets SDL hints before pygame loads
import pygame
from pygame._sdl2.video import Renderer, Texture

from lifeinlife.config import CLEAR_BG, OUTLINE_ALPHA, SOLID_BG
from lifeinlife.render import Painter, micro_surface
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
    """The original zoomed-in renderer: nested loops over every visible cell."""
    ren.draw_color = bg
    ren.clear()
    inner = Texture.from_surface(ren, micro_surface(world.micro))
    inner.blend_mode = pygame.BLENDMODE_BLEND
    gap, cell = max(1.0, dpr), view.cell
    r0, r1, c0, c1 = view.visible_cells()
    for r in range(r0, r1):
        for c in range(c0, c1):
            if world.macro[r, c]:
                x, y = view.ox + c * cell, view.oy + r * cell
                rgb = world.rgb[r, c]
                inner.color = rgb
                inner.draw(dstrect=(x, y, cell, cell))
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

    def compare(self, zoom, pan, bg, reference, grid=98, color=None):
        np.random.seed(7)
        world = World(grid, color)
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
        self.assertEqual(int((diff > 0).sum()), 0,
                         f"{int((diff > 0).sum())} pixels differ (max {diff.max()})")

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

    def test_zoomed_in(self):
        self.compare(3.0, 210.6, SOLID_BG, reference_detail)

    def test_zoomed_in_max(self):
        self.compare(8.0, 1234.5, CLEAR_BG, reference_detail, grid=40)

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
