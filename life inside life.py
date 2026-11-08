"""Life in Life: Conway's Game of Life where every live cell holds another Game of Life.

Run:
    python "life inside life.py"              # transparent floating window: only the cells show
    python "life inside life.py" --wallpaper  # live wallpaper behind your desktop icons (macOS)
    python "life inside life.py" --help       # every option

Needs pygame-ce and numpy. On macOS, pyobjc-framework-Cocoa adds the transparent
background and wallpaper mode. The code lives in the lifeinlife/ package next to this file.
"""
from lifeinlife.cli import main

if __name__ == "__main__":
    main()
