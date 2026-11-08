"""Life-like rules in B/S notation ("B3/S23" = born with 3 neighbours, survives with 2 or 3),
the named presets, and stepping a grid with any of them. Pure numpy, no pygame."""
import re
from typing import NamedTuple

import numpy as np

OFFSETS = [(i, j) for i in (-1, 0, 1) for j in (-1, 0, 1) if i or j]


class Rule(NamedTuple):
    name: str          # "Conway", or the notation for a custom rule
    birth: frozenset   # neighbour counts that bring a dead cell to life
    survive: frozenset  # neighbour counts that keep a live cell alive

    @property
    def notation(self):
        return f"B{''.join(map(str, sorted(self.birth)))}/S{''.join(map(str, sorted(self.survive)))}"

    @property
    def table(self):
        """table[alive, neighbours] -> next state, for numpy fancy indexing."""
        t = np.zeros((2, 9), dtype=np.uint8)
        t[0, sorted(self.birth)] = 1
        t[1, sorted(self.survive)] = 1
        return t


def _rule(name, notation):
    b, s = notation.upper().split("/")
    return Rule(name, frozenset(map(int, b[1:])), frozenset(map(int, s[1:])))


# Key -> rule, in the order Ctrl+Shift+L cycles through them.
PRESETS = {
    "conway": _rule("Conway", "B3/S23"),
    "highlife": _rule("HighLife", "B36/S23"),
    "daynight": _rule("Day & Night", "B3678/S34678"),
    "seeds": _rule("Seeds", "B2/S"),
    "maze": _rule("Maze", "B3/S12345"),
    "lifewithoutdeath": _rule("Life without Death", "B3/S012345678"),
    "morley": _rule("Morley", "B368/S245"),
    "diamoeba": _rule("Diamoeba", "B35678/S5678"),
}
CONWAY = PRESETS["conway"]


def parse_rule(text):
    """A preset name ("highlife", "Day & Night") or B/S notation ("B36/S23", "s23/b3").
    Raises ValueError for anything else."""
    key = re.sub(r"[^a-z0-9/]", "", text.lower())
    if key in PRESETS:
        return PRESETS[key]
    m = re.fullmatch(r"b([0-8]*)/s([0-8]*)|s([0-8]*)/b([0-8]*)", key)
    if not m:
        raise ValueError(f"unknown rule {text!r}: use {', '.join(PRESETS)} or B/S notation like B36/S23")
    birth, survive = (m.group(1), m.group(2)) if m.group(1) is not None else (m.group(4), m.group(3))
    if "0" in birth:
        raise ValueError("B0 rules (empty space comes alive) aren't supported")
    rule = Rule("", frozenset(map(int, birth)), frozenset(map(int, survive)))
    for preset in PRESETS.values():  # "B3/S23" is Conway: show its name
        if (preset.birth, preset.survive) == (rule.birth, rule.survive):
            return preset
    return rule._replace(name=rule.notation)


def next_preset(rule):
    """The preset after `rule` (a custom rule goes to the first one)."""
    rules = list(PRESETS.values())
    i = rules.index(rule) + 1 if rule in rules else 0
    return rules[i % len(rules)]


def _box3(a, axis, wrap):
    """Sum of each cell and its two neighbours along `axis`."""
    if wrap:
        return np.roll(a, 1, axis) + a + np.roll(a, -1, axis)
    n = a.shape[axis]
    pad = [(0, 0)] * a.ndim
    pad[axis] = (1, 1)
    p = np.pad(a, pad)

    def part(k):
        idx = [slice(None)] * a.ndim
        idx[axis] = slice(k, k + n)
        return p[tuple(idx)]
    return part(0) + part(1) + part(2)


def neighbor_sum(grid, wrap=True, axes=(0, 1)):
    """Sum of the 8 neighbours of every cell over two `axes` (so a stack of grids can be
    summed at once). wrap=True: edges wrap around; False: beyond the edge is dead."""
    return _box3(_box3(grid, axes[0], wrap), axes[1], wrap) - grid


def step(grid, rule=CONWAY, wrap=True, axes=(0, 1)):
    """Advance a grid (or a stack of grids, over `axes`) one generation."""
    return rule.table[grid, neighbor_sum(grid, wrap, axes)]
