"""Life in Life: Conway's Game of Life where every live cell holds another Game of Life.

Modules:
    config   - tunable constants, colours, help text
    colors   - colour parsing and hue -> RGB
    world    - the simulation (pure numpy, no pygame)
    view     - camera: zoom, pan, resize
    render   - drawing the world, help panel and toasts with pygame's GPU renderer
    app      - window, input, actions and the main loop
    cli      - command-line arguments and main()
    mac/     - macOS-only bits: transparent/pinned window, global hotkeys, visibility
"""
import os

# These must be set before pygame is first imported, which is why they live here:
# Python runs a package's __init__ before any of its modules.
# macOS: run as a background app, with no Dock icon and no "Python" menu in the menu bar.
os.environ.setdefault("SDL_MAC_BACKGROUND_APP", "1")
# Nearest-neighbour scaling: the world is drawn as one tiny texture blown up to screen size.
os.environ.setdefault("SDL_RENDER_SCALE_QUALITY", "0")
