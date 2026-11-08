"""Drawing with pygame's GPU renderer: the world, the help panel and toasts."""
import numpy as np
import pygame
from pygame._sdl2.video import Texture

from .config import DETAIL_ZOOM, HELP, OUTLINE_ALPHA, TEMPLATE_PX, TEXT, TEXT_DIM


def micro_surface(micro):
    """The inner grid as a white image with transparent gaps; tinted per cell when drawn."""
    k = TEMPLATE_PX
    mask = np.kron(micro, np.ones((k, k), dtype=np.uint8))
    mask[k - 1::k, :] = 0
    mask[:, k - 1::k] = 0
    surf = pygame.Surface(mask.shape[::-1], pygame.SRCALPHA)
    surf.fill((255, 255, 255, 0))
    alpha = pygame.surfarray.pixels_alpha(surf)
    alpha[:] = mask.T * 255  # surfarray is (x, y)
    del alpha  # unlock the surface
    return surf


def cells_surface(world):
    """The whole outer world as a size x size RGBA image: one pixel per cell, dead = clear."""
    rgba = np.dstack([world.rgb, world.macro * np.uint8(255)])  # (rows, cols, 4)
    return pygame.image.frombuffer(rgba.tobytes(), (world.size, world.size), "RGBA")


class Painter:
    """Owns every texture and font. draw() returns False when it skipped an identical frame."""

    _font_warned = False

    def __init__(self, renderer, dpr):
        self.ren = renderer
        self.cells_tex = None   # the outer world as one texture, one texel per cell
        self.cells_gen = None   # world.generation that cells_tex shows
        self.inner_tex = None   # the inner world, updated in place every frame
        self.drawn_state = None  # what the last frame showed; same again -> skip drawing
        self.set_dpr(dpr)

    def set_dpr(self, dpr):
        """(Re)load fonts for a pixel density: 2.0 on Retina. Called again when the window
        moves to a monitor with a different density."""
        self.dpr = dpr
        self.font = self.font_big = None
        try:
            self.font = pygame.font.Font(None, round(20 * dpr))
            self.font_big = pygame.font.Font(None, round(24 * dpr))
        except (NotImplementedError, ImportError, pygame.error):
            if not Painter._font_warned:
                Painter._font_warned = True
                print("Note: pygame's font module is unavailable, so on-screen help is off.\n"
                      "      Fix: pip uninstall pygame && pip install pygame-ce")
        self.help_tex = None
        self.toast_tex, self.toast_tex_text = None, None
        self.invalidate()

    @property
    def has_text(self):
        return self.font is not None and self.font_big is not None

    def invalidate(self):
        """Forget what's on screen, so the next draw() really draws."""
        self.drawn_state = None

    @staticmethod
    def animates(view):
        """Zoomed in, the inner worlds move every frame, so every frame must be drawn."""
        return view.zoom >= DETAIL_ZOOM

    # ---- frame
    def draw(self, world, view, bg, show_help=False, toast=None, outline=False, present=True):
        """Draw one frame. `bg` is the clear colour, `toast` a message or None,
        `outline` a faint border showing the window's edges. `present=False` leaves the
        frame in the back buffer (tests read it from there)."""
        detail = self.animates(view)
        # Skip identical frames: the window keeps showing the last one. Zoomed out, the
        # picture only changes when the outer world steps (every MACRO_EVERY frames) or you
        # interact; zoomed in, also whenever the inner world steps (every frame, unpaused).
        state = (world.generation, world.tick if detail else None, view.ox, view.oy,
                 view.zoom, view.w, view.h, bg, show_help, toast, outline)
        if state == self.drawn_state:
            return False
        self.drawn_state = state

        ren = self.ren
        ren.draw_color = bg
        ren.clear()
        if detail:
            self._draw_detail(world, view)
        else:
            self._draw_cells(world, view, bg)

        if outline:
            ren.draw_color = (255, 255, 255, 40)
            ren.draw_rect((0, 0, view.w, view.h))
        if self.has_text:
            if show_help:
                self._draw_help()
            if toast is not None:
                self._draw_toast(toast, view)
        if present:
            ren.present()
        return True

    def _draw_cells(self, world, view, bg):
        """Zoomed out: the world as one texture scaled up, plus hairline gaps."""
        ren, v = self.ren, view
        if self.cells_tex is None or self.cells_tex.width != world.size:
            self.cells_tex = Texture.from_surface(ren, cells_surface(world))
            self.cells_tex.blend_mode = pygame.BLENDMODE_BLEND
            self.cells_gen = world.generation
        elif self.cells_gen != world.generation:
            self.cells_tex.update(cells_surface(world))
            self.cells_gen = world.generation
        # When a cell edge lands exactly on a pixel centre, fill_rect gives that pixel to the
        # cell on the right/below while texture sampling may round it to the left/above.
        # Shifting by 1/64 px breaks such ties the fill_rect way (GPUs snap vertices to a
        # sub-pixel grid, so much smaller shifts vanish) and is hidden under the gap lines.
        nudge = 1 / 64
        self.cells_tex.draw(dstrect=(v.ox - nudge, v.oy - nudge, v.grid_px, v.grid_px))

        # Cut a hairline gap between cells by painting background over each cell's
        # right/bottom edge (blend off, so it also "erases" to a transparent background).
        r0, r1, c0, c1 = v.visible_cells()
        cell, gap = v.cell, max(1.0, self.dpr)
        ren.draw_blend_mode = pygame.BLENDMODE_NONE
        ren.draw_color = bg
        for c in range(c0, c1):
            ren.fill_rect((v.ox + (c + 1) * cell - gap, 0, gap, v.h))
        for r in range(r0, r1):
            ren.fill_rect((0, v.oy + (r + 1) * cell - gap, v.w, gap))
        ren.draw_blend_mode = pygame.BLENDMODE_BLEND

    def _draw_detail(self, world, view):
        """Zoomed in: every visible live cell shows the inner world, tinted its colour.
        numpy finds the live cells and their positions; Python only issues the draw calls
        (SDL batches them, since the tint is per-vertex colour, not a state change)."""
        ren, v = self.ren, view
        surf = micro_surface(world.micro)
        if self.inner_tex is None:
            self.inner_tex = Texture.from_surface(ren, surf)
            self.inner_tex.blend_mode = pygame.BLENDMODE_BLEND
        else:
            self.inner_tex.update(surf)
        inner = self.inner_tex

        r0, r1, c0, c1 = v.visible_cells()
        rows, cols = np.nonzero(world.macro[r0:r1, c0:c1])
        if rows.size == 0:
            return
        cell, gap = v.cell, max(1.0, self.dpr)
        colors = world.rgb[r0:r1, c0:c1][rows, cols].tolist()
        xs = (v.ox + (cols + c0) * cell).tolist()
        ys = (v.oy + (rows + r0) * cell).tolist()
        side = cell - gap
        for x, y, (r, g, b) in zip(xs, ys, colors):
            inner.color = (r, g, b)  # tint the inner life with its cell's colour
            inner.draw(dstrect=(x, y, cell, cell))
            ren.draw_color = (r, g, b, OUTLINE_ALPHA)
            ren.draw_rect((x, y, side, side))

    # ---- overlays
    def _panel_surface(self, w, h):
        panel = pygame.Surface((w, h), pygame.SRCALPHA)
        radius = round(10 * self.dpr)
        pygame.draw.rect(panel, (8, 9, 14, 225), panel.get_rect(), border_radius=radius)
        pygame.draw.rect(panel, (70, 80, 100, 255), panel.get_rect(), max(1, round(self.dpr)),
                         border_radius=radius)
        return panel

    def _draw_help(self):
        if self.help_tex is None:
            d, font, font_big = self.dpr, self.font, self.font_big
            pad, line_h, gap = round(16 * d), round(22 * d), round(24 * d)
            title = font_big.render("Life in Life", True, TEXT)
            keys = [font.render(k, True, TEXT) for k, _ in HELP]
            descs = [font.render(t, True, TEXT_DIM) for _, t in HELP]
            key_w = max(s.get_width() for s in keys)
            w = pad * 2 + key_w + gap + max(s.get_width() for s in descs)
            h = pad * 2 + title.get_height() + round(10 * d) + line_h * len(HELP)
            panel = self._panel_surface(w, h)
            panel.blit(title, (pad, pad))
            ty = pad + title.get_height() + round(10 * d)
            for i, (k, t) in enumerate(zip(keys, descs)):
                panel.blit(k, (pad, ty + i * line_h))
                panel.blit(t, (pad + key_w + gap, ty + i * line_h))
            self.help_tex = Texture.from_surface(self.ren, panel)
        m = round(20 * self.dpr)
        self.help_tex.draw(dstrect=(m, m, self.help_tex.width, self.help_tex.height))

    def _draw_toast(self, message, view):
        if self.toast_tex is None or self.toast_tex_text != message:
            d = self.dpr
            text = self.font_big.render(message, True, TEXT)
            px, py = round(14 * d), round(8 * d)
            panel = self._panel_surface(text.get_width() + 2 * px, text.get_height() + 2 * py)
            panel.blit(text, (px, py))
            self.toast_tex = Texture.from_surface(self.ren, panel)
            self.toast_tex_text = message
        tw, th = self.toast_tex.width, self.toast_tex.height
        x, y = (view.w - tw) // 2, view.h - th - round(28 * self.dpr)
        self.toast_tex.draw(dstrect=(x, y, tw, th))
