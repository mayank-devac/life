"""Camera: zoom and pan in pixels over a square grid. The grid always covers the window."""
import math

from .config import MAX_ZOOM, MIN_ZOOM, ZOOM_EASE


class View:
    def __init__(self, w, h, grid):
        self.grid = grid
        self.w, self.h = w, h
        self.base = max(w, h) / grid
        self.zoom = 1.0
        self.target_zoom = 1.0       # smooth zoom heads here (see zoom_smooth / ease)
        self.anchor = (w / 2, h / 2)  # ... keeping this pixel fixed
        self.ox = (w - self.grid_px) / 2
        self.oy = (h - self.grid_px) / 2

    @property
    def cell(self):
        return self.base * self.zoom

    @property
    def grid_px(self):
        return self.cell * self.grid

    def _clamp(self):
        self.ox = min(0.0, max(self.w - self.grid_px, self.ox))
        self.oy = min(0.0, max(self.h - self.grid_px, self.oy))

    def zoom_at(self, factor, mx, my):
        """Zoom right away, keeping the point under (mx, my) fixed."""
        self._zoom_to(self.zoom * factor, mx, my)
        self.target_zoom = self.zoom

    def _zoom_to(self, zoom, mx, my):
        new = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        f = new / self.zoom
        self.ox = mx - (mx - self.ox) * f
        self.oy = my - (my - self.oy) * f
        self.zoom = new
        self._clamp()

    def zoom_smooth(self, factor, mx, my):
        """Start gliding towards zoom * factor around (mx, my); ease() moves it there."""
        self.target_zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.target_zoom * factor))
        self.anchor = (mx, my)

    @property
    def easing(self):
        return self.zoom != self.target_zoom

    def ease(self, dt):
        """Move the zoom part of the way to its target (call once per frame)."""
        if not self.easing:
            return
        if abs(self.target_zoom / self.zoom - 1) < 0.002:
            new = self.target_zoom
        else:
            # Ease in log space, so zooming in and out feel the same.
            k = 1 - math.exp(-ZOOM_EASE * dt)
            new = math.exp(math.log(self.zoom) + (math.log(self.target_zoom) - math.log(self.zoom)) * k)
        self._zoom_to(new, *self.anchor)
        if abs(self.zoom - self.target_zoom) < 1e-9:
            self.zoom = self.target_zoom

    def pan(self, dx, dy):
        self.ox += dx
        self.oy += dy
        self._clamp()

    def resize(self, w, h):
        """The window changed size (monitor swapped, resolution changed): keep the zoom
        and whatever was in the middle of the view in the middle."""
        if (w, h) == (self.w, self.h):
            return
        fx = (self.w / 2 - self.ox) / self.grid_px  # centre, as a fraction of the grid
        fy = (self.h / 2 - self.oy) / self.grid_px
        self.w, self.h = w, h
        self.base = max(w, h) / self.grid
        self.ox = w / 2 - fx * self.grid_px
        self.oy = h / 2 - fy * self.grid_px
        self._clamp()

    def cell_at(self, x, y):
        """(row, col) of the grid cell under pixel (x, y), or None outside the grid."""
        c, r = int((x - self.ox) // self.cell), int((y - self.oy) // self.cell)
        return (r, c) if 0 <= r < self.grid and 0 <= c < self.grid else None

    def visible_cells(self):
        """(r0, r1, c0, c1): the half-open range of grid rows/columns that are on screen."""
        cell = self.cell
        c0, c1 = max(0, int(-self.ox // cell)), min(self.grid, int((self.w - self.ox) // cell) + 1)
        r0, r1 = max(0, int(-self.oy // cell)), min(self.grid, int((self.h - self.oy) // cell) + 1)
        return r0, r1, c0, c1
