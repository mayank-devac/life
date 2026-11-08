"""Drawing with pygame's GPU renderer: the world, the help panel and toasts."""
import numpy as np
import pygame
from pygame._sdl2.video import Texture

from .config import DETAIL_ZOOM, HELP, OUTLINE_ALPHA, TEXT, TEXT_DIM


def cells_surface(world):
    """The whole outer world as a size x size RGBA image: one pixel per cell, dead = clear
    (or a fading ghost)."""
    return pygame.image.frombuffer(world.rgba().tobytes(), (world.size, world.size), "RGBA")


def inner_pixels(world, region):
    """The inner worlds of the outer cells in `region` (r0, r1, c0, c1) as one RGBA array,
    one pixel per inner cell: (rows * m, cols * m, 4). Each inner cell takes its outer
    cell's colour and opacity, so ghosts of dead cells fade along with their world."""
    r0, r1, c0, c1 = region
    look = world.rgba()[r0:r1, c0:c1]           # (R, C, 4)
    bits = world.inner[r0:r1, c0:c1]            # (R, C, m, m)
    rows, cols, m = bits.shape[0], bits.shape[1], bits.shape[2]
    img = np.empty((rows, m, cols, m, 4), dtype=np.uint8)
    img[...] = look[:, None, :, None, :]
    img[..., 3] = bits.transpose(0, 2, 1, 3) * look[:, None, :, None, 3]
    return img.reshape(rows * m, cols * m, 4)


class Painter:
    """Owns every texture and font. draw() returns False when it skipped an identical frame."""

    _font_warned = False

    def __init__(self, renderer, dpr):
        self.ren = renderer
        self.cells_tex = None   # the outer world as one texture, one texel per cell
        self.cells_gen = None   # world.generation that cells_tex shows
        self.inner_tex = None   # the inner worlds on screen, updated in place every frame
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
    def draw(self, world, view, bg, show_help=False, toast=None, outline=False, present=True,
             brush=None, help_top=0):
        """Draw one frame. `bg` is the clear colour, `toast` a message or None,
        `outline` a faint border showing the window's edges, `brush` the cells a pattern
        stamp would cover ((row, col), ...) or None, `help_top` how far down (pixels) to
        move the help panel. `present=False` leaves the frame in the back buffer (tests
        read it from there)."""
        detail = self.animates(view)
        # Skip identical frames: the window keeps showing the last one. Zoomed out, the
        # picture only changes when the outer world steps (every world.macro_every frames) or you
        # interact; zoomed in, also whenever the inner world steps (every frame, unpaused).
        state = (world.generation, world.tick if detail else None, view.ox, view.oy,
                 view.zoom, view.w, view.h, bg, show_help, toast, outline, brush, help_top)
        if state == self.drawn_state:
            return False
        self.drawn_state = state

        ren = self.ren
        ren.draw_color = bg
        ren.clear()
        if detail:
            self._draw_detail(world, view, bg)
        else:
            self._draw_cells(world, view, bg)

        if brush:
            self._draw_brush(brush, view)
        if outline:
            ren.draw_color = (255, 255, 255, 40)
            ren.draw_rect((0, 0, view.w, view.h))
        if self.has_text:
            if show_help:
                self._draw_help(help_top)
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

    def _draw_detail(self, world, view, bg):
        """Zoomed in: every visible cell shows its own inner world, in its colour. numpy
        builds one image of everything on screen (a pixel per inner cell), the GPU scales
        it up, and thin background lines are cut between the inner cells."""
        ren, v = self.ren, view
        r0, r1, c0, c1 = region = v.visible_cells()
        if r1 <= r0 or c1 <= c0:
            return
        pixels = inner_pixels(world, region)
        h, w = pixels.shape[:2]
        surf = pygame.image.frombuffer(pixels.tobytes(), (w, h), "RGBA")
        if self.inner_tex is None or (self.inner_tex.width, self.inner_tex.height) != (w, h):
            self.inner_tex = Texture.from_surface(ren, surf)
            self.inner_tex.blend_mode = pygame.BLENDMODE_BLEND
        else:
            self.inner_tex.update(surf)
        cell, m = v.cell, world.micro_size
        nudge = 1 / 64  # see _draw_cells
        x0, y0 = v.ox + c0 * cell, v.oy + r0 * cell
        self.inner_tex.draw(dstrect=(x0 - nudge, y0 - nudge, (c1 - c0) * cell, (r1 - r0) * cell))

        # Gaps: between outer cells as zoomed out, and between inner cells once they're
        # big enough for a line not to swallow them (1/8 of an inner cell, like a grid).
        gap = max(1.0, self.dpr)
        inner = cell / m
        inner_gap = max(1.0, inner / 8) if inner >= 4 * max(1.0, self.dpr) else 0.0
        ren.draw_blend_mode = pygame.BLENDMODE_NONE
        ren.draw_color = bg
        top, height = y0, (r1 - r0) * cell
        left, width = x0, (c1 - c0) * cell
        for c in range(c0, c1):
            x = v.ox + c * cell
            ren.fill_rect((x + cell - gap, top, gap, height))
            if inner_gap:
                for k in range(1, m):
                    ren.fill_rect((x + k * inner - inner_gap, top, inner_gap, height))
        for r in range(r0, r1):
            y = v.oy + r * cell
            ren.fill_rect((left, y + cell - gap, width, gap))
            if inner_gap:
                for k in range(1, m):
                    ren.fill_rect((left, y + k * inner - inner_gap, width, inner_gap))
        ren.draw_blend_mode = pygame.BLENDMODE_BLEND

        # A faint outline in each live cell's colour shows where the cells are.
        rows, cols = np.nonzero(world.macro[r0:r1, c0:c1])
        if rows.size == 0:
            return
        colors = world.rgba()[r0:r1, c0:c1][rows, cols, :3].tolist()
        xs = (v.ox + (cols + c0) * cell).tolist()
        ys = (v.oy + (rows + r0) * cell).tolist()
        side = cell - gap
        for x, y, (r, g, b) in zip(xs, ys, colors):
            ren.draw_color = (r, g, b, OUTLINE_ALPHA)
            ren.draw_rect((x, y, side, side))

    # ---- overlays
    def _draw_brush(self, cells, view):
        """A see-through preview of where a pattern stamp would land."""
        ren, cell = self.ren, view.cell
        side = max(1.0, cell - max(1.0, self.dpr))
        ren.draw_color = (255, 255, 255, 110)
        for r, c in cells:
            ren.fill_rect((view.ox + c * cell, view.oy + r * cell, side, side))

    def _panel_surface(self, w, h):
        panel = pygame.Surface((w, h), pygame.SRCALPHA)
        radius = round(10 * self.dpr)
        pygame.draw.rect(panel, (8, 9, 14, 225), panel.get_rect(), border_radius=radius)
        pygame.draw.rect(panel, (70, 80, 100, 255), panel.get_rect(), max(1, round(self.dpr)),
                         border_radius=radius)
        return panel

    def _draw_help(self, top=0):
        if self.help_tex is None:
            d, font, font_big = self.dpr, self.font, self.font_big
            if font is None or font_big is None:
                return  # no font module: draw() already skips text, this is a safety net
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
        self.help_tex.draw(dstrect=(m, m + top, self.help_tex.width, self.help_tex.height))

    def _draw_toast(self, message, view):
        if self.toast_tex is None or self.toast_tex_text != message:
            if self.font_big is None:
                return
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
