"""Pattern stamps (the Ctrl+Shift+P brushes) and the .rle / .cells file formats.
Pure numpy, no pygame.

A pattern is a 2D uint8 array, 1 = alive. RLE is the standard Life pattern format:
    #N Glider
    x = 3, y = 3, rule = B3/S23
    bo$2bo$3o!
`b` = dead, `o` = alive, `$` = end of row, a number repeats what follows, `!` ends it."""
import re

import numpy as np


def from_picture(text):
    """A pattern drawn with `.` (dead) and `O` (alive), one line per row."""
    rows = [line.strip() for line in text.strip().splitlines()]
    width = max(len(r) for r in rows)
    grid = np.zeros((len(rows), width), dtype=np.uint8)
    for i, row in enumerate(rows):
        for j, ch in enumerate(row):
            grid[i, j] = ch in "O*o"
    return grid


def parse_rle(text):
    """RLE text -> (pattern, rule text or None). Raises ValueError if it isn't RLE."""
    width = height = None
    rule = None
    body = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if width is None and line.lower().startswith("x"):
            header = dict(
                (k.strip().lower(), v.strip())
                for k, _, v in (part.partition("=") for part in line.split(",")))
            try:
                width, height = int(header["x"]), int(header["y"])
            except (KeyError, ValueError):
                raise ValueError(f"bad RLE header: {line!r}") from None
            rule = header.get("rule")
            continue
        body.append(line)
        if "!" in line:
            break
    if width is None:
        raise ValueError("not an RLE file (no 'x = ..., y = ...' line)")

    cells, row, col = [], 0, 0
    for count, tag in re.findall(r"(\d*)([^\d\s])", "".join(body)):
        n = int(count) if count else 1
        if tag == "!":
            break
        if tag == "$":
            row, col = row + n, 0
        elif tag in "b.":
            col += n
        else:  # `o`, or any other letter (a live state in multi-state files)
            cells.extend((row, col + k) for k in range(n))
            col += n
    rows = max([height] + [r + 1 for r, _ in cells])
    cols = max([width] + [c + 1 for _, c in cells])
    grid = np.zeros((rows, cols), dtype=np.uint8)
    for r, c in cells:
        grid[r, c] = 1
    return grid, rule


def parse_cells(text):
    """Plaintext (.cells): `!` comment lines, then `.` / `O` pictures."""
    rows = [line.rstrip() for line in text.splitlines() if not line.startswith("!")]
    while rows and not rows[-1]:
        rows.pop()
    if not rows:
        raise ValueError("empty pattern")
    width = max(len(r) for r in rows) or 1
    grid = np.zeros((len(rows), width), dtype=np.uint8)
    for i, row in enumerate(rows):
        for j, ch in enumerate(row):
            if ch not in ".O* \t":
                raise ValueError(f"not a .cells file (unexpected {ch!r})")
            grid[i, j] = ch in "O*"
    return grid


def load(path):
    """Read a .rle or .cells file -> (pattern, rule text or None). Raises OSError / ValueError."""
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    if str(path).lower().endswith(".cells"):
        return parse_cells(text), None
    return parse_rle(text)


def to_rle(grid, rule="B3/S23", name=None, line_width=70):
    """A pattern as RLE text. Trailing dead cells and empty rows at the end are left out."""
    grid = np.asarray(grid)
    height, width = grid.shape
    tokens = []

    def run(n, tag):
        tokens.append(f"{n if n > 1 else ''}{tag}")

    pending_rows = 0
    for r in range(height):
        row = grid[r]
        alive = np.flatnonzero(row)
        if alive.size == 0:
            pending_rows += 1
            continue
        if tokens:
            run(pending_rows + 1, "$")
        elif pending_rows:
            run(pending_rows, "$")  # empty rows at the top
        pending_rows = 0
        end = alive[-1] + 1
        c = 0
        while c < end:
            v = row[c]
            n = 1
            while c + n < end and row[c + n] == v:
                n += 1
            run(n, "o" if v else "b")
            c += n
    tokens.append("!")

    lines, line = [], ""
    for t in tokens:
        if len(line) + len(t) > line_width:
            lines.append(line)
            line = ""
        line += t
    lines.append(line)
    head = [f"#N {name}"] if name else []
    head.append(f"x = {width}, y = {height}, rule = {rule}")
    return "\n".join(head + lines) + "\n"


# ---------------------------------------------------------------- brushes (Ctrl+Shift+P)
GLIDER = from_picture("""
.O.
..O
OOO
""")

LWSS = from_picture("""
.O..O
O....
O...O
OOOO.
""")

PULSAR = from_picture("""
..OOO...OOO..
.............
O....O.O....O
O....O.O....O
O....O.O....O
..OOO...OOO..
.............
..OOO...OOO..
O....O.O....O
O....O.O....O
O....O.O....O
.............
..OOO...OOO..
""")

GOSPER_GUN = parse_rle("""x = 36, y = 9
24bo$22bobo$12b2o6b2o12b2o$11bo3bo4b2o12b2o$2o8bo5bo3b2o$2o8bo3bob2o4b
obo$10bo5bo7bo$11bo3bo$12b2o!""")[0]

R_PENTOMINO = from_picture("""
.OO
OO.
.O.
""")

ACORN = from_picture("""
.O.....
...O...
OO..OOO
""")

# Name -> pattern, in the order Ctrl+Shift+P cycles through them.
BRUSHES = {
    "cell": np.ones((1, 1), dtype=np.uint8),
    "glider": GLIDER,
    "LWSS": LWSS,
    "pulsar": PULSAR,
    "Gosper glider gun": GOSPER_GUN,
    "R-pentomino": R_PENTOMINO,
    "acorn": ACORN,
}


def rotated(pattern, quarter_turns):
    """The pattern turned clockwise by 90 degrees `quarter_turns` times."""
    return np.rot90(pattern, -(quarter_turns % 4))
