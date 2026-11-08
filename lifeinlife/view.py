"""Camera: zoom and pan in pixels over a square grid. The grid always covers the window."""
from .config import MAX_ZOOM, MIN_ZOOM


class View:
    def __init__(self, w, h, grid):
        self.grid = grid
        self.w, self.h = w, h
        self.base = max(w, h) / grid
        self.zoom = 1.0
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
        """Zoom while keeping the point under (mx, my) fixed."""
        new = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom * factor))
        f = new / self.zoom
        self.ox = mx - (mx - self.ox) * f
        self.oy = my - (my - self.oy) * f
        self.zoom = new
        self._clamp()

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

    def visible_cells(self):
        """(r0, r1, c0, c1): the half-open range of grid rows/columns that are on screen."""
        cell = self.cell
        c0, c1 = max(0, int(-self.ox // cell)), min(self.grid, int((self.w - self.ox) // cell) + 1)
        r0, r1 = max(0, int(-self.oy // cell)), min(self.grid, int((self.h - self.oy) // cell) + 1)
        return r0, r1, c0, c1
