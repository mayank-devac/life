"""The simulation: an outer Game of Life whose every cell holds its own inner Game of Life.
Pure numpy, no pygame, so it can be tested and reasoned about on its own."""
from collections import deque

import numpy as np

from .colors import Theme, colorize
from .config import (AGE_DIM, AGE_FULL, DENSITY, FLASH, HISTORY, INNER_DENSITY, INNER_MUTATION,
                     MACRO_EVERY, MICRO_SIZE, MUTATION, REWIND, STALE_STEPS, TRAIL_ALPHA,
                     TRAIL_DECAY, TRAIL_MIN)
from .rules import CONWAY, OFFSETS, neighbor_sum, step

__all__ = ["World", "neighbor_sum", "step_life", "step_colored", "random_grid", "random_inner"]


def step_life(grid, rule=CONWAY, wrap=True):
    """Advance a 2D grid one generation."""
    return step(grid, rule, wrap)


def step_colored(grid, hue, rule=CONWAY, wrap=True):
    """Step the outer grid. Every cell has its own hue; a newborn takes the
    average hue of its parents plus a small random mutation, so colour
    families spread, mix and drift as the world evolves."""
    new = step(grid, rule, wrap)
    born = (new == 1) & (grid == 0)
    if born.any():
        # Average hues as angles, so 0.95 and 0.05 average to 0.0 (red), not 0.5 (cyan).
        angle = hue * 2 * np.pi
        cx = neighbor_sum(np.cos(angle) * grid, wrap)
        cy = neighbor_sum(np.sin(angle) * grid, wrap)
        parent_hue = (np.arctan2(cy, cx) / (2 * np.pi)) % 1.0
        drift = np.random.uniform(-MUTATION, MUTATION, hue.shape)
        hue = np.where(born, (parent_hue + drift) % 1.0, hue)
    return new, hue


def random_grid(size, density=DENSITY):
    return (np.random.random((size, size)) < density).astype(np.uint8)


def random_inner(count, m=MICRO_SIZE):
    """`count` random inner worlds, shape (count, m, m)."""
    return (np.random.random((count, m, m)) < INNER_DENSITY).astype(np.uint8)


def find_parents(old, rows, cols, wrap=True):
    """For newborn cells (rows, cols), one live neighbour each in `old` (picked in a random
    direction, so lineages don't all drift the same way). -1 where there is none."""
    size = old.shape[0]
    pr, pc = np.full(rows.shape, -1), np.full(cols.shape, -1)
    for k in np.random.permutation(len(OFFSETS)):
        di, dj = OFFSETS[k]
        r, c = rows + di, cols + dj
        if wrap:
            r, c, inside = r % size, c % size, True
        else:
            inside = (r >= 0) & (r < size) & (c >= 0) & (c < size)
            r, c = np.clip(r, 0, size - 1), np.clip(c, 0, size - 1)
        hit = inside & (old[r, c] == 1) & (pr < 0)
        pr[hit], pc[hit] = r[hit], c[hit]
    return pr, pc


class World:
    """The outer grid (`macro`, size x size, with a colour per cell) and an inner grid per
    outer cell (`inner`, size x size x m x m). Call step() once per frame.

    `rule` / `inner_rule` are rules.Rule, `wrap` whether the outer edges wrap around,
    `macro_every` how many frames per outer step (the speed).

    A newborn outer cell inherits a copy of one parent's inner world, with a few cells
    flipped: lineages carry their own little worlds around. Inner worlds only step while
    they're on screen (see step()), so zoomed out they cost nothing.

    `generation` goes up whenever the outer world (or how it looks) changes, so the
    renderer knows when its cached texture is out of date."""

    def __init__(self, size, color=None, rule=CONWAY, inner_rule=CONWAY, wrap=True,
                 macro_every=MACRO_EVERY, effects=True):
        self.size = size
        self.color = color  # None = rainbow hues, a Theme = hues along it, (r, g, b) = one colour
        self.rule, self.inner_rule, self.wrap = rule, inner_rule, wrap
        self.macro_every = max(1, int(macro_every))
        self.effects = effects  # fading trails, age brightness, birth flashes
        self.tick = 0
        self.generation = 0
        self._rgba, self._rgba_gen = None, None
        self.rewind = deque(maxlen=REWIND)  # snapshots of earlier generations, newest last
        # Emptied by hand (clear()): don't replace the empty world with a random one
        # until it has live cells again.
        self.cleared = False
        self.reseed()

    # ---- setup and settings
    def reseed(self):
        shape = (self.size, self.size)
        self.cleared = False
        self.macro = random_grid(self.size)
        self.age = 0  # outer generations since this world was seeded ("Time")
        # Generations each cell has been alive (1 = just born). Starting cells count as
        # middle-aged, so a new world doesn't open with every cell flashing.
        self.alive_for = self.macro.astype(np.uint16) * (AGE_FULL // 2)
        self.ghost = np.zeros(shape, dtype=np.float32)  # 1 = just died, fades to 0
        self.inner = random_inner(self.size * self.size).reshape(*shape, MICRO_SIZE, MICRO_SIZE)
        self.hue = None
        self.set_color(self.color)  # also bumps generation (once per reseed)
        self._forget_history()

    def _forget_history(self):
        self.history = []  # hashes of recent outer generations, for stall detection
        self.stale = 0

    def set_color(self, color):
        """Recolour the world as it is (no reseed). Hues are kept when switching between
        rainbow and themes, so colour families stay where they are."""
        self.color = color
        if color is None or isinstance(color, Theme):
            if self.hue is None:
                self.hue = np.random.random((self.size, self.size))
            self.rgb = colorize(self.hue, color)
        else:
            # One colour for everything: no hues to track or blend, and rgb never changes.
            self.hue = None
            self.rgb = np.broadcast_to(np.array(color, dtype=np.uint8), (self.size, self.size, 3))
        self.generation += 1  # the renderer's cached texture is out of date

    def set_rule(self, rule=None, inner_rule=None, wrap=None):
        """Change the rules or edges mid-run. The world carries on from where it is."""
        if rule is not None:
            self.rule = rule
        if inner_rule is not None:
            self.inner_rule = inner_rule
        if wrap is not None:
            self.wrap = wrap
        self._forget_history()  # a new rule deserves a fresh chance

    def set_effects(self, on):
        self.effects = on
        self.generation += 1

    def toggle(self, row, col):
        """Make a cell alive (with a random hue and inner world) or kill it. Returns True
        if it's now alive."""
        alive = not self.macro[row, col]
        self.set_cells([row], [col], alive)
        return alive

    def set_cells(self, rows, cols, alive, hue=None):
        """Bring the cells (rows[i], cols[i]) to life (each with a fresh inner world and
        `hue`, or a random one) or kill them. Cells already in that state are left alone."""
        rows, cols = np.asarray(rows, dtype=int), np.asarray(cols, dtype=int)
        change = self.macro[rows, cols] != alive
        rows, cols = rows[change], cols[change]
        if hue is not None and np.ndim(hue):
            hue = np.asarray(hue)[change]
        if rows.size == 0:
            return
        self.macro[rows, cols] = 1 if alive else 0
        if alive:
            self.alive_for[rows, cols] = 1
            self.ghost[rows, cols] = 0
            self.inner[rows, cols] = random_inner(rows.size, self.micro_size)
            if self.hue is not None:
                self.hue[rows, cols] = np.random.random(rows.size) if hue is None else hue
                self.rgb[rows, cols] = colorize(self.hue[rows, cols], self.color)
        else:
            self.alive_for[rows, cols] = 0
            self.ghost[rows, cols] = 1.0
        # A hand-made change isn't a stall: give the new pattern a fresh chance.
        self._forget_history()
        self.generation += 1  # the renderer's cached texture is out of date

    def stamp(self, pattern, row, col):
        """Bring a pattern's live cells to life with its centre at (row, col), all in one
        colour (a random hue). Off the edge it wraps around, or is cut off without wrap.
        Returns how many of its cells landed on the grid."""
        pr, pc = np.nonzero(pattern)
        rows = pr + row - pattern.shape[0] // 2
        cols = pc + col - pattern.shape[1] // 2
        if self.wrap:
            rows, cols = rows % self.size, cols % self.size
        else:
            inside = (rows >= 0) & (rows < self.size) & (cols >= 0) & (cols < self.size)
            rows, cols = rows[inside], cols[inside]
        self.set_cells(rows, cols, True, hue=np.random.random())
        return int(rows.size)

    def clear(self):
        """Kill every cell (they fade out as ghosts). The empty world isn't replaced by a
        random one until it has live cells again."""
        self.ghost = np.where(self.macro == 1, 1.0, self.ghost).astype(np.float32)
        self.macro = np.zeros_like(self.macro)
        self.alive_for = np.zeros_like(self.alive_for)
        self.age = 0
        self.cleared = True
        self._forget_history()
        self.generation += 1

    def load(self, pattern):
        """Replace the world with `pattern`, centred (one the grid's size lands exactly as
        saved; a bigger one is cropped around its centre). Returns True if it was cropped."""
        h, w = pattern.shape
        top, left = (h - self.size) // 2, (w - self.size) // 2
        cropped = top > 0 or left > 0
        pattern = pattern[max(0, top):max(0, top) + self.size, max(0, left):max(0, left) + self.size]
        self.clear()
        self.ghost[:] = 0  # a loaded world starts clean, without the old one fading out
        rows, cols = np.nonzero(pattern)
        rows += max(0, -top)
        cols += max(0, -left)
        if self.hue is not None:
            self.hue = np.random.random((self.size, self.size))  # fresh colours everywhere
            self.rgb = colorize(self.hue, self.color)
        self.set_cells(rows, cols, True, hue=self.hue[rows, cols] if self.hue is not None else None)
        self.alive_for[rows, cols] = AGE_FULL // 2  # like a new random world: no flash
        return cropped

    # ---- rewind
    def checkpoint(self):
        """Remember the world as it is now, so step_back() can return to it. Called before
        every outer step, and before hand-made changes (clear, stamp, paint, load)."""
        packed = np.packbits(self.macro)
        if self.rewind and self.rewind[-1]["age"] == self.age \
                and np.array_equal(self.rewind[-1]["macro"], packed):
            return  # nothing changed since the last one
        # Compact: ~85 KB per snapshot on a 144 x 144 grid. Inner worlds aren't kept
        # (they'd be 256x bigger); they carry on as they are.
        self.rewind.append({
            "macro": packed,
            "hue": None if self.hue is None else (self.hue * 65535).astype(np.uint16),
            "alive_for": np.minimum(self.alive_for, 255).astype(np.uint8),
            "ghost": (self.ghost * 255).astype(np.uint8),
            "age": self.age,
            "cleared": self.cleared,
        })

    @property
    def can_step_back(self):
        return bool(self.rewind)

    def step_back(self):
        """Go back to the last snapshot. Returns False if there's none left."""
        if not self.rewind:
            return False
        snap = self.rewind.pop()
        n = self.size * self.size
        self.macro = np.unpackbits(snap["macro"], count=n).reshape(self.size, self.size)
        self.alive_for = snap["alive_for"].astype(np.uint16)
        self.ghost = snap["ghost"].astype(np.float32) / 255
        self.age, self.cleared = snap["age"], snap["cleared"]
        if snap["hue"] is not None and self.hue is not None:
            self.hue = snap["hue"].astype(np.float64) / 65535
            self.rgb = colorize(self.hue, self.color)
        self.tick = 1  # the next outer step is a full interval away
        self._forget_history()
        self.generation += 1
        return True

    # ---- reading
    @property
    def population(self):
        """Live outer cells."""
        return int(self.macro.sum())

    @property
    def micro_size(self):
        return self.inner.shape[-1]

    def rgba(self):
        """What every outer cell looks like: (size, size, 4) uint8. Live cells are opaque;
        with effects on, young cells are dimmer, newborns flash and the recently dead leave
        a fading ghost. Computed once per generation."""
        if self._rgba_gen == self.generation:
            return self._rgba
        out = np.empty((self.size, self.size, 4), dtype=np.uint8)
        if not self.effects:
            out[..., :3] = self.rgb
            out[..., 3] = self.macro * np.uint8(255)
        else:
            maturity = np.minimum(self.alive_for, AGE_FULL) / AGE_FULL
            light = np.where(self.macro == 1, AGE_DIM + (1 - AGE_DIM) * maturity, 1.0)
            rgb = self.rgb * light[..., None].astype(np.float32)
            newborn = (self.alive_for == 1)[..., None]
            rgb = np.where(newborn, rgb + (255 - rgb) * FLASH, rgb)
            out[..., :3] = rgb
            out[..., 3] = np.where(self.macro == 1, 255, self.ghost * (TRAIL_ALPHA * 255))
        self._rgba, self._rgba_gen = out, self.generation
        return out

    def frames_to_macro_step(self):
        """How many step() calls happen before the one that also steps the outer world.
        0 means the very next step() changes it."""
        return (-self.tick) % self.macro_every

    # ---- stepping
    def step(self, region=None):
        """One frame. The inner worlds of the live cells in `region` (r0, r1, c0, c1: the
        cells on screen) step, or none if it's None; every macro_every frames the outer
        world steps too. Returns True when the outer world had settled and was replaced
        by a new random one."""
        if region is not None:
            self._step_inner(region)
        settled = False
        if self.tick % self.macro_every == 0:
            settled = self._step_macro()
        self.tick += 1
        return settled

    def _step_inner(self, region):
        r0, r1, c0, c1 = region
        sub = self.inner[r0:r1, c0:c1]  # a view: writing to it writes self.inner
        idx = np.nonzero(self.macro[r0:r1, c0:c1])
        if idx[0].size == 0:
            return
        worlds = step(sub[idx], self.inner_rule, wrap=True, axes=(1, 2))
        empty = ~worlds.any(axis=(1, 2))
        if empty.any():  # a world that died out starts again, so live cells never look empty
            worlds[empty] = random_inner(int(empty.sum()), self.micro_size)
        sub[idx] = worlds

    def _step_macro(self):
        self.checkpoint()
        old = self.macro
        if self.hue is None:
            new = step(old, self.rule, self.wrap)
        else:
            new, self.hue = step_colored(old, self.hue, self.rule, self.wrap)
            self.rgb = colorize(self.hue, self.color)
        born = (new == 1) & (old == 0)
        died = (new == 0) & (old == 1)
        if born.any():
            self._inherit_inner(old, born)
        self.macro = new
        self.alive_for = np.where(new == 1, np.minimum(self.alive_for + 1, 60000), 0).astype(np.uint16)
        ghost = np.where(died, 1.0, self.ghost * TRAIL_DECAY).astype(np.float32)
        ghost[(ghost < TRAIL_MIN) | (new == 1)] = 0
        self.ghost = ghost
        self.generation += 1
        self.age += 1

        # Settled: empty, or back to a state seen in the last HISTORY generations (still
        # lifes, blinkers, pulsars, pentadecathlons, any mix of them). Gliders still on
        # the move never repeat that soon, so a world with traffic left lives on.
        # Emptied by hand: an empty world is the point, so it isn't "settled" until it has
        # had live cells again.
        if self.cleared and new.any():
            self.cleared = False
        if self.cleared:
            return False
        key = hash(new.tobytes())
        self.stale = self.stale + 1 if (not new.any() or key in self.history) else 0
        self.history = (self.history + [key])[-HISTORY:]
        if self.stale >= STALE_STEPS:
            self.reseed()
            return True
        return False

    def _inherit_inner(self, old, born):
        """Each newborn copies one parent's inner world, with a few cells flipped."""
        rows, cols = np.nonzero(born)
        pr, pc = find_parents(old, rows, cols, self.wrap)
        has = pr >= 0
        worlds = random_inner(rows.size, self.micro_size)  # only kept where there's no parent
        worlds[has] = self.inner[pr[has], pc[has]]
        flips = np.random.random(worlds.shape) < INNER_MUTATION
        self.inner[rows, cols] = worlds ^ flips.astype(np.uint8)
