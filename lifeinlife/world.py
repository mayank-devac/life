"""The simulation: an outer Game of Life whose live cells each show a shared inner one.
Pure numpy, no pygame, so it can be tested and reasoned about on its own."""
import numpy as np

from .colors import hue_to_rgb
from .config import DENSITY, MACRO_EVERY, MICRO_SIZE, MUTATION, STALE_STEPS


def neighbor_sum(grid):
    """Sum of the 8 neighbours of every cell (edges wrap around)."""
    return sum(
        np.roll(np.roll(grid, i, 0), j, 1)
        for i in (-1, 0, 1) for j in (-1, 0, 1)
        if (i != 0 or j != 0)
    )


def step_life(grid):
    """Advance a 2D grid one generation."""
    n = neighbor_sum(grid)
    return ((n == 3) | ((grid == 1) & (n == 2))).astype(np.uint8)


def step_colored(grid, hue):
    """Step the outer grid. Every cell has its own hue; a newborn takes the
    average hue of its three parents plus a small random mutation, so colour
    families spread, mix and drift as the world evolves."""
    n = neighbor_sum(grid)
    new = ((n == 3) | ((grid == 1) & (n == 2))).astype(np.uint8)
    born = (new == 1) & (grid == 0)
    if born.any():
        # Average hues as angles, so 0.95 and 0.05 average to 0.0 (red), not 0.5 (cyan).
        angle = hue * 2 * np.pi
        cx = neighbor_sum(np.cos(angle) * grid)
        cy = neighbor_sum(np.sin(angle) * grid)
        parent_hue = (np.arctan2(cy, cx) / (2 * np.pi)) % 1.0
        drift = np.random.uniform(-MUTATION, MUTATION, hue.shape)
        hue = np.where(born, (parent_hue + drift) % 1.0, hue)
    return new, hue


def random_grid(size):
    return np.random.choice([0, 1], size=(size, size), p=[1 - DENSITY, DENSITY]).astype(np.uint8)


def seed_micro():
    """Two gliders travelling side by side, so the inner world never dies out."""
    grid = np.zeros((MICRO_SIZE, MICRO_SIZE), dtype=np.uint8)
    for r, c in [(1, 2), (2, 3), (3, 1), (3, 2), (3, 3)]:
        grid[r, c] = 1
        grid[r + 7, c + 7] = 1
    return grid


class World:
    """The outer grid (`macro`, size x size, with a colour per cell) and the inner grid
    (`micro`) that every live outer cell shows. Call step() once per frame.

    `generation` goes up whenever the outer world changes, so the renderer knows when
    its cached texture is out of date."""

    def __init__(self, size, color=None):
        self.size = size
        self.color = color  # None = every cell its own hue, else one (r, g, b) for all
        self.tick = 0
        self.generation = 0
        self.reseed()

    def reseed(self):
        self.macro = random_grid(self.size)
        self.age = 0  # outer generations since this world was seeded ("Time")
        self.set_color(self.color)  # also bumps generation (once per reseed)
        self.micro = seed_micro()
        self.history = []  # last two outer generations, for stall detection
        self.stale = 0

    def set_color(self, color):
        """Recolour the world as it is (no reseed): None = every cell its own hue."""
        self.color = color
        if color is None:
            self.hue = np.random.random((self.size, self.size))
            self.rgb = hue_to_rgb(self.hue)
        else:
            # One colour for everything: no hues to track or blend, and rgb never changes.
            self.hue = None
            self.rgb = np.broadcast_to(np.array(color, dtype=np.uint8), (self.size, self.size, 3))
        self.generation += 1  # the renderer's cached texture is out of date

    def toggle(self, row, col):
        """Make a cell alive (with a random hue, in multicolour) or kill it. Returns True
        if it's now alive."""
        alive = not self.macro[row, col]
        self.macro[row, col] = alive
        if alive and self.hue is not None:
            self.hue[row, col] = np.random.random()
            self.rgb[row, col] = hue_to_rgb(self.hue[row:row + 1, col:col + 1])[0, 0]
        # A hand-made change isn't a stall: give the new pattern a fresh chance.
        self.stale, self.history = 0, []
        self.generation += 1  # the renderer's cached texture is out of date
        return alive

    @property
    def population(self):
        """Live outer cells."""
        return int(self.macro.sum())

    def frames_to_macro_step(self):
        """How many step() calls happen before the one that also steps the outer world.
        0 means the very next step() changes it."""
        return (-self.tick) % MACRO_EVERY

    def step(self):
        """One frame: the inner world steps; every MACRO_EVERY frames the outer one does too.
        Returns True when the outer world had settled and was replaced by a new random one."""
        self.micro = step_life(self.micro)
        settled = False
        if self.tick % MACRO_EVERY == 0:
            settled = self._step_macro()
        self.tick += 1
        return settled

    def _step_macro(self):
        if self.hue is None:
            self.macro = step_life(self.macro)
        else:
            self.macro, self.hue = step_colored(self.macro, self.hue)
            self.rgb = hue_to_rgb(self.hue)
        self.generation += 1
        self.age += 1
        snapshot = self.macro.tobytes()
        # Empty, frozen, or blinking in place (period 1 or 2): count it as stalled.
        self.stale = self.stale + 1 if (not self.macro.any() or snapshot in self.history) else 0
        self.history = (self.history + [snapshot])[-2:]
        if self.stale >= STALE_STEPS:
            self.reseed()
            return True
        return False
