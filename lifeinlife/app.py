"""The app: window, input, actions and the main loop.

The main loop is event-driven, not a fixed 30 fps spin:
    - Zoomed out, the picture only changes when the outer world steps (--speed times a
      second, 2 by default), so between steps it sleeps in pygame.event.wait() and
      wakes up for input, a step, or a toast/help timer. About 2 wake-ups a second.
      The inner worlds don't step at all then: nobody can see them.
    - Zoomed in (or while a smooth zoom glides), the inner worlds on screen move every
      frame, so it wakes up every frame.
    - While nobody can see the window (screen locked, display asleep) it stops
      simulating and drawing, and checks again once a second.
Time is kept with a frame clock (`next_tick`), so the speed is the same either way.
"""
import math
import os
import queue
import signal
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pygame
from pygame._sdl2.video import Renderer

from . import patterns, settings
from .colors import THEMES, parse_color
from .config import (CLEAR_BG, CLICKABLE_BG, HIDDEN_WAIT, HOVER_IDLE, MAX_WAIT, MONITOR_GRACE, PINNED_WAIT,
                     SAVE_DIR, SCREEN_POLL, SOLID_BG, SPEEDS, SYSTEM_POLL)
from .render import Painter
from .rules import next_preset, parse_rule
from .view import View
from .world import World

BRUSH_NAMES = list(patterns.BRUSHES)

# Ctrl+Shift + <key> -> action, while the window has focus.
PYGAME_KEYS = {
    pygame.K_ESCAPE: "quit",
    pygame.K_w: "wallpaper",
    pygame.K_h: "help",
    pygame.K_SPACE: "pause",
    pygame.K_r: "reseed",
    pygame.K_s: "settings",
    pygame.K_l: "rule",
    pygame.K_i: "inner-rule",
    pygame.K_e: "edges",
    pygame.K_k: "theme",
    pygame.K_f: "effects",
    pygame.K_p: "brush",
    pygame.K_t: "rotate",
    pygame.K_c: "clear",
    pygame.K_x: "save",
    pygame.K_LEFT: "back",
    pygame.K_RIGHT: "step",
    pygame.K_COMMA: "slower",
    pygame.K_PERIOD: "faster",
    pygame.K_UP: "opacity+",
    pygame.K_DOWN: "opacity-",
    pygame.K_EQUALS: "zoom+",
    pygame.K_PLUS: "zoom+",
    pygame.K_KP_PLUS: "zoom+",
    pygame.K_MINUS: "zoom-",
    pygame.K_KP_MINUS: "zoom-",
}
# Events meaning "the window's pixel size or density may have changed".
SIZE_EVENTS = {getattr(pygame, name) for name in
               ("WINDOWSIZECHANGED", "WINDOWRESIZED", "WINDOWDISPLAYCHANGED") if hasattr(pygame, name)}


class LifeInLife:
    def __init__(self, args):
        pygame.init()
        self.WAKE = pygame.event.custom_type()  # posted by global hotkeys to end a wait early
        self.wallpaper_mode = args.wallpaper
        self.monitor = args.monitor
        self.size = args.size  # window size in points (wallpaper mode: for switching back)
        self.color_name = args.color_name
        # A single colour you picked (Ctrl+Shift+K cycles back to it after the themes)
        self.base_color = args.color_name if args.color_name not in ("multi", *THEMES) else "white"
        self.dialog = None     # thread running the Ctrl+Shift+S settings dialog
        self.picked = queue.SimpleQueue()  # its answer, handed to the main loop thread-safely
        self.woken = threading.Event()     # set by that thread to cut a pinned / hidden sleep short
        self.screen_frame = None  # NSRect of the monitor the wallpaper covers
        if args.wallpaper:
            size, pos = self._pick_monitor(args.monitor), (0, 0)
        else:
            size, pos = (args.size, args.size), pygame.WINDOWPOS_CENTERED
        # borderless: no title bar or buttons. allow_high_dpi: draw at full Retina resolution.
        self.window = pygame.Window("Life in Life", size, pos, borderless=True, allow_high_dpi=True)
        self.renderer = Renderer(self.window)
        self.renderer.draw_blend_mode = pygame.BLENDMODE_BLEND
        # Pixel size of the drawing area vs. window size in points (2.0 on Retina screens)
        px_w, px_h = self.renderer.get_viewport().size
        self.painter = Painter(self.renderer, px_w / size[0])
        self.dt = 1 / max(1, args.fps)
        self.world = World(args.grid, args.color, rule=args.rule, inner_rule=args.inner_rule,
                           wrap=args.edges == "wrap", effects=not args.no_effects)
        self.set_speed(args.speed)
        self.view = View(px_w, px_h, args.grid)
        self.view.zoom_at(args.zoom, px_w / 2, px_h / 2)  # start-up scale

        self.opacity = max(0.1, min(1.0, args.opacity))
        self.window.opacity = self.opacity
        self.bg_alpha = round(max(0.0, min(1.0, args.bg_opacity)) * 255)
        self.next_tick = time.monotonic()

        self.paused = False
        self.running = True
        self.show_help = not args.wallpaper
        self.help_until = time.monotonic() + 6  # start-up help fades away on its own
        self.toast_text, self.toast_until = "", 0.0
        self.drag_mode = None  # None | "move" | "pan" | "paint"
        self.grab = (0, 0)     # where the window was grabbed, for "move"
        self.paint_alive = True  # "paint": bring cells to life, or erase them
        self.paint_last = None   # "paint": the last cell painted, to fill gaps on fast drags
        self.mouse = None      # mouse position in points while it's over the window
        self.brush = 0         # index into BRUSH_NAMES (Ctrl+Shift+P)
        self.turns = 0         # quarter turns clockwise (Ctrl+Shift+T)
        self.hovered = False
        self.hover = False       # hover mode: cells come to life wherever the mouse moves
        self.hover_last = None   # the cell the mouse was last over (hover mode), or None
        self.pending = []      # actions coming from the global hotkeys and the panel

        self.hidden = None     # why nobody can see the window, or None
        self.visibility = None
        self.next_system_poll = 0.0
        self.next_screen_poll = 0.0
        self.follow_monitor = False  # wallpaper mode: keep the window on the chosen monitor
        self.home = None  # normal mode: (monitor name, its frame, dx, dy, w, h) the window belongs at
        self.monitor_missing_since = None  # when the chosen monitor went away, or None
        self.placed = None  # (target frame, frame we actually got) after the last move
        self.hud = None        # the clickable step back / play / pause / speed / pin panel
        self.hud_error = None
        self.hud_key = None    # what it last showed, and where
        self.hud_unsaved: tuple[dict, float] | None = None  # (spots, when to save them): saved once a drag has settled

        # macOS: transparent background + wallpaper mode
        self.mac = None
        self.mac_error = None
        self.transparent = False
        if not args.solid:
            mac = self._get_mac()
            if mac is not None:
                mac.make_transparent()
                self.transparent = True
            else:
                print(f"Note: transparent background {self.mac_error}; using a dark background.")
        if args.wallpaper:
            mac = self._get_mac()
            if mac is None:
                pygame.quit()
                sys.exit(f"--wallpaper: {self.mac_error}")
            mac.pin(frame=self.screen_frame)
            self._start_global_hotkeys()
            self.follow_monitor = True
        elif self._get_mac() is not None:
            target = self._monitor_frame(args.monitor)
            if target is not None:
                self._center_on(target)  # start on the chosen (or saved) monitor
            self._remember_home()  # from now on, stay on that monitor
        if sys.platform == "darwin" and self._get_mac() is not None:
            self._show_hud()  # pinned or not: it has the pin / unpin button
        if args.hover:
            self.set_hover(True, clear=not args.load)
        if args.load:
            if not self.load_file(args.load):
                pygame.quit()
                sys.exit(f"--load: {self.toast_text}")
        if self.mac is not None:
            try:
                from .mac.visibility import Visibility  # noqa: PLC0415 - macOS only
                self.visibility = Visibility(self.mac.win)
            except Exception as exc:  # noqa: BLE001 - it's an optimisation, never fatal
                print(f"Note: can't detect when the window is hidden ({exc}); it keeps running.")

    # ---- helpers
    @property
    def dpr(self):
        return self.painter.dpr

    def _pick_monitor(self, number):
        """Size (in points) of monitor `number` (1 = primary). Remembers its frame for pinning."""
        from .mac.window import mac_screens  # noqa: PLC0415 - None without pyobjc
        screens = mac_screens()
        sizes = ([(int(f.size.width), int(f.size.height)) for _, f in screens] if screens
                 else pygame.display.get_desktop_sizes())
        index = number - 1
        if not 0 <= index < len(sizes):
            print(f"Note: monitor {number} not found ({len(sizes)} connected); using the primary one.\n"
                  f"      It moves there by itself once that monitor is connected.")
            index = 0
        if screens:
            self.screen_frame = screens[index][1]
        return sizes[index]

    def _get_mac(self):
        if self.mac is None and self.mac_error is None:
            if sys.platform != "darwin":
                self.mac_error = "only works on macOS"
            else:
                try:
                    from .mac.window import MacWindow  # noqa: PLC0415 - needs pyobjc
                    self.mac = MacWindow()
                except ImportError:
                    self.mac_error = "needs pyobjc  ->  pip install pyobjc-framework-Cocoa"
                except Exception as exc:  # noqa: BLE001 - report anything pyobjc throws
                    self.mac_error = f"failed ({exc})"
        return self.mac

    def _on_hotkey(self, action):
        """Called from inside SDL's event pump when a global shortcut is pressed."""
        self.pending.append(action)
        try:
            pygame.event.post(pygame.event.Event(self.WAKE))  # end pygame.event.wait() now
        except pygame.error:
            pass  # handled on the next wake-up anyway, at most MAX_WAIT later

    def _start_global_hotkeys(self):
        if self.mac is None:
            return
        try:
            self.mac.watch_hotkeys(self._on_hotkey)
        except (OSError, AttributeError) as exc:
            print(f"Note: global shortcuts unavailable ({exc}); Ctrl+C in this terminal quits.")

    def _show_hud(self):
        """Show the panel: step back / play / pause / step / faster / pin. Pinned, it's the
        only way to click anything (clicks go through the wallpaper to the desktop)."""
        if self.hud is None and self.hud_error is None:
            try:
                from .mac.hud import Hud  # noqa: PLC0415 - macOS only
                spots = settings.hud_spots(settings.load().get("hud"))
                self.hud = Hud(self._on_hotkey, spots,  # clicks arrive like global hotkeys
                               on_moved=self._hud_moved)
            except Exception as exc:  # noqa: BLE001 - nice to have, never fatal
                self.hud_error = exc
                print(f"Note: can't show the control panel ({exc}).")
        if self.hud is not None and self.mac is not None:
            self.hud_key = None  # fill it on the next draw
            self.hud.show(self.mac.win, self.mac.pinned)

    def _hud_moved(self, spots):
        self.hud_unsaved = (spots, time.monotonic() + 1)  # saved once the drag has settled

    def _save_hud_spots(self, now=None):
        """Save where the panel was dragged, a second after the drag (or now, on quit)."""
        if self.hud_unsaved is None:
            return
        spots, when = self.hud_unsaved
        if now is not None and now < when:
            return
        self.hud_unsaved = None
        try:
            settings.save(hud=settings.hud_text(spots))
        except OSError as exc:
            print(f"Note: couldn't save the panel's position ({exc.strerror}).")

    def _update_hud(self):
        if self.hud is None or self.mac is None:
            return
        pinned = self.mac.pinned
        place = (self._frame_key(self.mac.frame()), pinned)
        key = (self.world.generation, self.paused, self.status, self.world.can_step_back, place)
        if key == self.hud_key:
            return
        if self.hud_key is None or self.hud_key[-1] != place:
            self.hud.place(self.mac.win, pinned)  # moved to another monitor, or (un)pinned
        self.hud_key = key
        self.hud.update(self.world.age, self.world.population, self.paused, self.status,
                        pinned, self.world.can_step_back)

    @property
    def help_top(self):
        """Pixels to move the help panel down so the (unpinned) control panel doesn't hide it."""
        if self.hud is None or self.pinned:
            return 0
        from .mac.hud import H, MARGIN  # noqa: PLC0415 - only reached with a panel, so on macOS
        return round((MARGIN + H) * self.dpr)

    @property
    def max_catchup(self):
        """Longest catch-up after a sleep; beyond that, time jumps instead of replaying frames."""
        return self.world.macro_every + math.ceil(MAX_WAIT / self.dt) + 1

    def set_speed(self, speed):
        """Outer generations per second. It steps every so many frames, so the speed you
        get is the nearest one the frame rate allows."""
        self.world.macro_every = max(1, round(1 / (self.dt * speed)))
        self.speed = speed

    def change_speed(self, faster):
        """The next speed up (or down) from SPEEDS, wrapping round at either end, so the
        panel's one "faster" button reaches them all. Saved for the next start."""
        choices = [s for s in SPEEDS if s <= 1 / self.dt] or [1 / self.dt]
        if faster:
            bigger = [s for s in choices if s > self.speed + 1e-9]
            speed = bigger[0] if bigger else choices[0]
        else:
            smaller = [s for s in choices if s < self.speed - 1e-9]
            speed = smaller[-1] if smaller else choices[-1]
        self.set_speed(speed)
        text = settings.speed_text(speed)
        self.toast(f"Speed {text} generation{'' if text == '1' else 's'} / second")
        try:
            settings.save(speed=text)
        except OSError:
            pass  # applied anyway, just not remembered

    @property
    def status(self):
        """Rule and speed, for the pinned panel: "Conway  2/s"."""
        rule = self.world.rule.name
        if self.world.inner_rule != self.world.rule:
            rule += f" / {self.world.inner_rule.name}"
        return f"{rule}  {settings.speed_text(self.speed)}/s"

    @property
    def pinned(self):
        return self.mac is not None and self.mac.pinned

    def toast(self, text, seconds=1.6):
        self.toast_text, self.toast_until = text, time.monotonic() + seconds
        if not self.painter.has_text:
            print(text)

    def _sync_size(self):
        """The window changed size or moved to a monitor with another pixel density."""
        px_w, px_h = self.renderer.get_viewport().size
        pt_w = self.window.size[0]
        if px_w <= 0 or pt_w <= 0:
            return
        self.view.resize(px_w, px_h)
        dpr = px_w / pt_w
        if abs(dpr - self.painter.dpr) > 1e-3:
            self.painter.set_dpr(dpr)  # fonts and panels at the new density
        self.painter.invalidate()

    # ---- actions
    def do(self, action):
        if action == "quit":
            self.running = False
        elif action == "pause":
            self.paused = not self.paused
            self.toast("Paused" if self.paused else "Running")
        elif action in ("run", "hold"):  # the pinned panel's play / pause buttons
            if self.paused != (action == "hold"):
                self.do("pause")
        elif action == "step":  # pause, then advance the outer world one generation
            self.paused = True
            for _ in range(self.world.frames_to_macro_step() + 1):
                self._step_world()
        elif action == "back":  # pause, then go back one generation (or hand-made change)
            self.paused = True
            if self.world.step_back():
                self.toast(f"Back to time {self.world.age}  ({len(self.world.rewind)} more)", 1.2)
            else:
                self.toast("Can't go back any further")
        elif action in ("faster", "slower"):
            self.change_speed(action == "faster")
        elif action == "reseed":
            self.world.checkpoint()  # step back undoes it
            self.world.reseed()
            self.toast("New world")
        elif action == "clear":
            self.world.checkpoint()
            self.world.clear()
            self.toast("Cleared  -  click or drag to draw, Ctrl+Shift+P for patterns", 3)
        elif action == "brush":
            self.brush = (self.brush + 1) % len(BRUSH_NAMES)
            self.turns = 0
            self.toast(f"Brush: {BRUSH_NAMES[self.brush]}"
                       + ("  -  click to place, Ctrl+Shift+T rotates" if self.brush else ""), 2.5)
        elif action == "rotate":
            self.turns = (self.turns + 1) % 4
            self.toast(f"Brush: {BRUSH_NAMES[self.brush]}, turned {self.turns * 90}°")
        elif action == "save":
            self.save_world()
        elif action == "help":
            self.show_help = not self.show_help
            self.help_until = math.inf
        elif action in ("opacity+", "opacity-"):
            step = 0.1 if action == "opacity+" else -0.1
            self.opacity = round(max(0.1, min(1.0, self.opacity + step)), 2)
            self.window.opacity = self.opacity
            self.toast(f"Opacity {round(self.opacity * 100)}%")
        elif action in ("zoom+", "zoom-"):
            self.view.zoom_smooth(1.25 if action == "zoom+" else 0.8, self.view.w / 2, self.view.h / 2)
        elif action == "rule":
            self.world.set_rule(rule=next_preset(self.world.rule))
            r = self.world.rule
            self.toast(f"Rule: {r.name}  ({r.notation})", 2.5)
        elif action == "inner-rule":
            self.world.set_rule(inner_rule=next_preset(self.world.inner_rule))
            r = self.world.inner_rule
            self.toast(f"Inner rule: {r.name}  ({r.notation})", 2.5)
        elif action == "edges":
            self.world.set_rule(wrap=not self.world.wrap)
            self.toast("Edges wrap around" if self.world.wrap else "Edges are dead")
        elif action == "theme":
            # multi -> each theme -> the colour you started with (if it's one colour) -> multi
            cycle = ["multi", *THEMES]
            if self.color_name not in cycle:
                cycle.append(self.base_color)
            i = cycle.index(self.color_name) if self.color_name in cycle else -1
            self.color_name = cycle[(i + 1) % len(cycle)]
            self.world.set_color(parse_color(self.color_name))
            self.toast(f"Colour: {self.color_name}")
        elif action == "effects":
            self.world.set_effects(not self.world.effects)
            self.toast("Effects on" if self.world.effects else "Effects off")
        elif action == "wallpaper":
            self.toggle_wallpaper()
        elif action == "settings":
            self.open_settings()

    def open_settings(self):
        """Show the colour / monitor dialog. It runs in its own thread (osascript blocks
        until it's answered) so the wallpaper keeps going meanwhile."""
        if self.dialog is not None and self.dialog.is_alive():
            return  # already open
        color, monitor, speed, hover = self.color_name, self.monitor, self.speed, self.hover
        mode = settings.WALLPAPER if self.wallpaper_mode else settings.WINDOW
        size = self.size if self.wallpaper_mode else round(self.window.size[0])
        self.toast("Opening settings…", 3)  # osascript takes a moment to show the window

        def tell(kind, value):
            self.picked.put((kind, value))  # the main loop acts on it (pygame isn't thread-safe)
            self.woken.set()                # end a pinned / hidden sleep now
            try:
                pygame.event.post(pygame.event.Event(self.WAKE))  # end event.wait() now
            except pygame.error:
                pass  # still seen on the next wake-up, at most MAX_WAIT later

        def ask():
            picked = settings.choose(color, monitor, speed, mode, size,
                                     progress=lambda text: tell("toast", text), hover=hover)
            if picked is None:
                tell("toast", None)  # cancelled
            else:
                tell("apply", picked)

        self.dialog = threading.Thread(target=ask, name="settings-dialog", daemon=True)
        self.dialog.start()

    def apply_settings(self, picked):
        """Apply a choice from the dialog right away, and save it for the next start.
        `picked` is settings.choose()'s {"color", "speed", "monitor", "mode", "size", "hover"}."""
        color_name, monitor, size = picked["color"], picked["monitor"], picked["size"]
        self.world.set_color(parse_color(color_name))  # the dialog already checked it
        self.color_name = color_name
        if color_name not in ("multi", *THEMES):
            self.base_color = color_name
        self.set_speed(min(picked["speed"], 1 / self.dt))
        hover = picked.get("hover", self.hover)
        if hover != self.hover:
            self.set_hover(hover)
        self.monitor = monitor
        self.size = size
        mode = picked["mode"]
        if self.mac is None:
            if mode == settings.WALLPAPER and not self.wallpaper_mode:
                self.toast(f"Wallpaper mode {self.mac_error}", 3.5)
                mode = settings.WINDOW
            self.window.size = (size, size)  # no monitor control without pyobjc
            self._sync_size()
        else:
            switching = (mode == settings.WALLPAPER) != self.wallpaper_mode
            target = self._monitor_frame(monitor)
            if target is None:
                self.toast(f"Monitor {monitor} isn't connected", 3)
            if mode == settings.WALLPAPER:
                if switching:
                    self._become_wallpaper()
                # Cover the chosen monitor, pinned or not, even if it's the one already chosen:
                # the window may have been moved off it (e.g. by macOS while it was asleep).
                # The frame carries its size and position, so a different resolution is
                # picked up too (via WINDOWSIZECHANGED).
                self.monitor_missing_since = None
                target = target or self._monitor_frame(1)
                if target is not None:
                    self._cover(target, force=True)
            else:
                if switching:
                    self._become_window()
                target = target or self._monitor_frame(1)
                if target is not None:
                    # Normal window: move it over to that monitor, at the chosen size. Coming
                    # out of wallpaper mode, it starts in the monitor's middle.
                    self._center_on(target, size, middle=switching)
        self.painter.invalidate()
        try:
            speed_text = settings.speed_text(self.speed)
            settings.save(color=color_name, speed=speed_text, monitor=monitor, mode=mode, size=size,
                          hover="on" if self.hover else "off")
            shown = "wallpaper" if mode == settings.WALLPAPER else f"window {size}pt"
            if self.hover:
                shown += "  -  hover"
            self.toast(f"Colour {color_name}  -  {speed_text}/s  -  {shown}  -  monitor {monitor}", 2.5)
        except OSError as exc:
            self.toast(f"Applied, but couldn't save it ({exc.strerror})", 3.5)

    def _become_wallpaper(self):
        """Switch from a window to wallpaper mode: pinned, covering the chosen monitor (the
        caller moves it there), following that monitor."""
        mac = self.mac
        if mac is None:
            return
        self.wallpaper_mode = True
        self.home = None  # the window-mode "stay on this monitor" check is off now
        self.drag_mode = None
        if not mac.pinned:
            mac.pin()
            self._start_global_hotkeys()
        self.follow_monitor = True
        self.placed = None
        self.show_help = False
        self._show_hud()

    def _become_window(self):
        """Switch from wallpaper mode to a window: unpinned, clickable, its own size (the
        caller sizes and places it)."""
        mac = self.mac
        if mac is None:
            return
        self.wallpaper_mode = False
        self.follow_monitor = False
        self.monitor_missing_since = None
        if mac.pinned:
            mac.unpin()
            mac.unwatch_hotkeys()
        self._show_hud()

    # ---- brushes, saving and loading
    def brush_pattern(self):
        return patterns.rotated(patterns.BRUSHES[BRUSH_NAMES[self.brush]], self.turns)

    def _brush_cells(self):
        """Cells the brush would cover at the mouse, for the preview: ((row, col), ...)."""
        if not self.brush or self.mouse is None or self.pinned or self.drag_mode is not None:
            return None
        cell = self.view.cell_at(self.mouse[0] * self.dpr, self.mouse[1] * self.dpr)
        if cell is None:
            return None
        pattern = self.brush_pattern()
        pr, pc = np.nonzero(pattern)
        size = self.world.size
        rows = (pr + cell[0] - pattern.shape[0] // 2)
        cols = (pc + cell[1] - pattern.shape[1] // 2)
        if self.world.wrap:
            rows, cols = rows % size, cols % size
        return tuple(zip(rows.tolist(), cols.tolist()))

    def _paint_to(self, cell):
        """Paint (or erase) every cell on the line from the last painted one to `cell`."""
        self._line(self.paint_last, cell, self.paint_alive)
        self.paint_last = cell

    def _line(self, last, cell, alive):
        """Bring to life (or kill) every cell on the line from `last` (None: just `cell`)."""
        last = last or cell
        n = max(abs(cell[0] - last[0]), abs(cell[1] - last[1]))
        t = np.linspace(0, 1, n + 1)
        rows = np.rint(last[0] + (cell[0] - last[0]) * t).astype(int)
        cols = np.rint(last[1] + (cell[1] - last[1]) * t).astype(int)
        self.world.set_cells(rows, cols, alive)

    # ---- hover mode
    def set_hover(self, on, clear=True):
        """Hover mode on: the world empties (unless `clear` is False) and cells come to life
        wherever the mouse moves over the window, pinned or not; a settled world is left
        alone instead of being replaced by a random one. Off: back to normal, with a new
        random world if this one is empty."""
        self.hover = on
        self.hover_last = None
        self.world.reseed_when_settled = not on
        if on and clear:
            if self.world.population:
                self.world.checkpoint()  # step back brings the old world back
            self.world.clear()
            self.world.ghost[:] = 0  # no fading trails of the old world: start really empty
        elif not on and not self.world.population:
            self.world.reseed()

    def _mouse_at(self):
        """The mouse, in points from the window's top-left, or None outside it."""
        if self.mac is not None:
            return self.mac.mouse_at()  # works while pinned too
        return self.mouse if self.hovered else None

    def _hover(self):
        """Hover mode: bring to life the cells the mouse moved over since the last look."""
        if not self.hover:
            return
        pos = self._mouse_at() if self.drag_mode is None else None
        cell = None if pos is None else self.view.cell_at(pos[0] * self.dpr, pos[1] * self.dpr)
        if cell is not None and cell != self.hover_last:
            self._line(self.hover_last, cell, True)
        self.hover_last = cell

    def save_world(self):
        """Save the whole world as .rle in SAVE_DIR (the grid's full size, so loading it
        puts every cell back where it was)."""
        folder = Path(SAVE_DIR).expanduser()
        name = time.strftime("world-%Y%m%d-%H%M%S")
        path = folder / f"{name}.rle"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path.write_text(patterns.to_rle(self.world.macro, self.world.rule.notation,
                                            name=f"Life in Life {name}"))
        except OSError as exc:
            self.toast(f"Couldn't save ({exc.strerror})", 3.5)
            return
        print(f"Saved {path}", flush=True)
        self.toast(f"Saved {SAVE_DIR}/{path.name}", 3)

    def load_file(self, path):
        """Load a .rle / .cells pattern as the whole world. Returns False (and shows why) if
        it couldn't."""
        try:
            grid, rule = patterns.load(path)
        except (OSError, ValueError) as exc:
            self.toast(f"Can't load {Path(path).name}: {getattr(exc, 'strerror', None) or exc}", 4)
            return False
        self.world.checkpoint()  # step back undoes it
        cropped = self.world.load(grid)
        note = ""
        if rule:
            try:
                self.world.set_rule(rule=parse_rule(rule))
            except ValueError:
                note = f"  (rule {rule} not supported: kept {self.world.rule.name})"
        if cropped:
            note += f"  (cropped to {self.world.size}x{self.world.size})"
        self.toast(f"Loaded {Path(path).name}{note}", 3.5)
        return True

    def toggle_wallpaper(self):
        mac = self._get_mac()
        if mac is None:
            self.toast(f"Wallpaper mode {self.mac_error}", 3.5)
            return
        self.drag_mode = None
        if mac.pinned:
            mac.unpin()
            mac.unwatch_hotkeys()
            self._show_hud()  # back onto the window's corner
            self.toast("Interactive  -  Ctrl+Shift+W to pin again", 2.5)
        else:
            mac.pin()
            self._start_global_hotkeys()
            self._show_hud()
            self.show_help = False
            self.toast("Pinned to desktop  -  Ctrl+Shift+W to unpin", 2.5)

    # ---- input
    def handle(self, event):
        if event.type == pygame.QUIT:  # Cmd+Q
            self.running = False

        elif event.type == pygame.KEYDOWN:
            chord = (event.mod & pygame.KMOD_CTRL) and (event.mod & pygame.KMOD_SHIFT)
            if chord and event.key in PYGAME_KEYS:
                self.do(PYGAME_KEYS[event.key])
            elif event.key == pygame.K_ESCAPE and self.show_help:
                self.show_help = False  # plain Esc just closes the help panel
            elif not chord and event.key in PYGAME_KEYS:
                self.toast("Shortcuts use Ctrl+Shift  -  Ctrl+Shift+H for help", 2.5)

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button in (1, 2, 3):
            mods = pygame.key.get_mods()
            if (mods & pygame.KMOD_CTRL) and (mods & pygame.KMOD_SHIFT):
                # Remember where we grabbed; moving the window by event.rel jitters because
                # the window moving under the cursor feeds back into the next rel.
                self.drag_mode, self.grab = "move", event.pos
            elif event.button != 1 or mods & pygame.KMOD_ALT:
                self.drag_mode = "pan"  # right / middle drag, or Option + drag
            else:
                cell = self.view.cell_at(event.pos[0] * self.dpr, event.pos[1] * self.dpr)
                if cell is None:
                    return
                self.world.checkpoint()  # step back undoes the whole stroke / stamp
                if self.brush:
                    self.world.stamp(self.brush_pattern(), *cell)
                else:
                    # Starting on a live cell erases, on a dead one draws, for the whole drag.
                    self.paint_alive = not self.world.macro[cell]
                    self.paint_last = None
                    self.drag_mode = "paint"
                    self._paint_to(cell)

        elif event.type == pygame.MOUSEBUTTONUP and event.button in (1, 2, 3):
            if self.drag_mode == "move":
                self.drag_mode = None
                self._remember_home()  # dragged to a new spot (maybe another monitor): stay there
            self.drag_mode = None

        elif event.type == pygame.MOUSEMOTION:
            self.mouse = event.pos
            if self.drag_mode == "move":
                wx, wy = self.window.position
                self.window.position = (wx + event.pos[0] - self.grab[0],
                                        wy + event.pos[1] - self.grab[1])
            elif self.drag_mode == "pan":
                self.view.pan(event.rel[0] * self.dpr, event.rel[1] * self.dpr)
            elif self.drag_mode == "paint":
                cell = self.view.cell_at(event.pos[0] * self.dpr, event.pos[1] * self.dpr)
                if cell is not None:
                    self._paint_to(cell)

        elif event.type == pygame.DROPFILE:  # a pattern file dropped onto the window
            self.load_file(event.file)

        elif event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            self.view.zoom_smooth(1.12 ** event.precise_y, mx * self.dpr, my * self.dpr)

        elif event.type == pygame.WINDOWENTER:
            self.hovered = True
        elif event.type == pygame.WINDOWLEAVE:
            self.hovered = False
            self.mouse = None  # hide the brush preview
        elif event.type == pygame.WINDOWFOCUSLOST:
            if self.drag_mode == "move":
                self.drag_mode = None
                self._remember_home()
            self.drag_mode = None  # don't get stuck dragging if the button-up happened elsewhere
        elif event.type in SIZE_EVENTS:
            self._sync_size()
        elif event.type == pygame.WINDOWEXPOSED:
            self.painter.invalidate()  # the OS lost our pixels: redraw next frame

    # ---- system state (polled, cheap)
    @staticmethod
    def _monitor_frame(number):
        """NSRect of monitor `number` (1 = primary), or None if it isn't connected."""
        from .mac.window import mac_screens  # noqa: PLC0415
        screens = mac_screens() or []
        return screens[number - 1][1] if 1 <= number <= len(screens) else None

    def _cover(self, target, force=False):
        """Move the window onto `target` (an NSRect) unless it's already there."""
        mac = self.mac
        if mac is None:
            return
        want, have = self._frame_key(target), self._frame_key(mac.frame())
        # Skip when nothing changed since our last move. Comparing with the frame we
        # actually got (not only the target) stops a retry every poll if macOS adjusts it.
        if not force and self.placed == (want, have):
            return
        if have != want:
            mac.set_frame(target)
            self._sync_size()
            self.painter.invalidate()
        self.screen_frame = target
        self.placed = (want, self._frame_key(mac.frame()))

    def _center_on(self, target, size=None, middle=False):
        """Normal (windowed) mode: put the window on monitor frame `target`, `size` points
        square (None: keep its size), shrunk to fit the monitor. Already on that monitor, it
        stays where the user put it (resized around its middle) unless `middle`; otherwise
        it goes to the monitor's middle."""
        mac = self.mac
        if mac is None:
            return
        f, t = mac.frame(), target
        mid_x, mid_y = f.origin.x + f.size.width / 2, f.origin.y + f.size.height / 2
        on_it = (t.origin.x <= mid_x < t.origin.x + t.size.width
                 and t.origin.y <= mid_y < t.origin.y + t.size.height)
        w, h = (f.size.width, f.size.height) if size is None else (size, size)
        w, h = min(w, t.size.width), min(h, t.size.height)
        if on_it and not middle:
            if (w, h) == (f.size.width, f.size.height):
                self._remember_home()
                return  # nothing to change: keep where the user put it
            x, y = mid_x - w / 2, mid_y - h / 2  # resize around its middle...
        else:
            x, y = t.origin.x + (t.size.width - w) / 2, t.origin.y + (t.size.height - h) / 2
        # ...kept inside the monitor
        x = min(max(x, t.origin.x), t.origin.x + t.size.width - w)
        y = min(max(y, t.origin.y), t.origin.y + t.size.height - h)
        mac.set_frame(((x, y), (w, h)))
        self._sync_size()
        self.painter.invalidate()
        self._remember_home()

    # ---- normal mode: stay on its monitor
    @staticmethod
    def _screen_at(frame):
        """(number, name, frame) of the monitor under the middle of `frame`, or None."""
        from .mac.window import mac_screens  # noqa: PLC0415
        mid_x = frame.origin.x + frame.size.width / 2
        mid_y = frame.origin.y + frame.size.height / 2
        for i, (name, s) in enumerate(mac_screens() or [], 1):
            if (s.origin.x <= mid_x < s.origin.x + s.size.width
                    and s.origin.y <= mid_y < s.origin.y + s.size.height):
                return i, name, s
        return None

    def _remember_home(self):
        """Normal mode: the window is where it belongs (the user or we just put it there).
        Remember the monitor (by name, so a reordered monitor list doesn't matter) and the
        window's spot and size on it."""
        if self.wallpaper_mode or self.mac is None:
            return
        f = self.mac.frame()
        here = self._screen_at(f)
        if here is None:
            return
        number, name, s = here
        self.home = (name, self._frame_key(s), f.origin.x - s.origin.x, f.origin.y - s.origin.y,
                     f.size.width, f.size.height)
        self.monitor = number  # what the settings dialog shows as "now"

    def _home_screen(self):
        """The frame of the monitor the window belongs on, or None if it isn't connected.
        Same name and frame first; then the same name (its resolution may have changed)."""
        from .mac.window import mac_screens  # noqa: PLC0415
        if self.home is None:
            return None
        name, key = self.home[:2]
        screens = [s for n, s in mac_screens() or [] if n == name]
        exact = [s for s in screens if self._frame_key(s) == key]
        return (exact or screens or [None])[0]

    def _keep_home(self, now):
        """Normal mode, pinned or not: if macOS moved the window to another monitor (sleep,
        a monitor dropping out), put it back where it was once its monitor is there. Moves
        on the same monitor are taken as the user's. If the monitor is gone, wait
        MONITOR_GRACE seconds, then make sure the window is on some screen."""
        if self.home is None or self.mac is None or self.drag_mode == "move":
            return
        name, _, dx, dy, w, h = self.home
        f = self.mac.frame()
        here = self._screen_at(f)
        screen = self._home_screen()
        if screen is None:
            if self.monitor_missing_since is None:
                self.monitor_missing_since = now
                print(f"Monitor {name} disconnected: waiting for it to come back.", flush=True)
            if now - self.monitor_missing_since >= MONITOR_GRACE and here is None:
                primary = self._monitor_frame(1)
                if primary is not None:  # off every screen: bring it onto the primary one
                    w0, h0 = min(f.size.width, primary.size.width), min(f.size.height, primary.size.height)
                    self.mac.set_frame(((primary.origin.x + (primary.size.width - w0) / 2,
                                         primary.origin.y + (primary.size.height - h0) / 2), (w0, h0)))
                    self._sync_size()
                    self.painter.invalidate()
            return
        if self.monitor_missing_since is not None:
            self.monitor_missing_since = None
            print(f"Monitor {name} is back: moving the window onto it again.", flush=True)
        if here is not None and self._frame_key(here[2]) == self._frame_key(screen):
            self._remember_home()  # on its monitor: any move here is the user's
            return
        # On the wrong monitor (or none): back to its spot, kept inside the screen.
        w, h = min(w, screen.size.width), min(h, screen.size.height)
        x = min(max(screen.origin.x + dx, screen.origin.x), screen.origin.x + screen.size.width - w)
        y = min(max(screen.origin.y + dy, screen.origin.y), screen.origin.y + screen.size.height - h)
        self.mac.set_frame(((x, y), (w, h)))
        self._sync_size()
        self.painter.invalidate()

    def _follow_monitor(self, now):
        """Wallpaper mode: keep the window on the chosen monitor.

        Checks the window itself, not just whether the monitor list changed: after sleep
        a monitor can drop out and come back between two polls (HDMI is slower to wake
        than USB-C). macOS moves the window to a remaining screen meanwhile, and the
        list looks unchanged afterwards. If the chosen monitor is gone, wait
        MONITOR_GRACE seconds for it before settling on the primary one."""
        if not self.pinned:
            return  # unpinned: the user may have moved it on purpose
        target = self._monitor_frame(self.monitor)
        if target is None:
            if self.monitor_missing_since is None:
                self.monitor_missing_since = now
                print(f"Monitor {self.monitor} disconnected: waiting up to "
                      f"{MONITOR_GRACE:g}s for it to come back.", flush=True)
            if now - self.monitor_missing_since < MONITOR_GRACE:
                return
            target = self._monitor_frame(1)
            if target is None:
                return  # no screens at all right now (all asleep)
            if self.placed is None or self.placed[0] != self._frame_key(target):
                print(f"Monitor {self.monitor} still missing: using the primary one until "
                      f"it's back.", flush=True)
        elif self.monitor_missing_since is not None:
            self.monitor_missing_since = None
            print(f"Monitor {self.monitor} is back: covering it again.", flush=True)
        self._cover(target)

    @staticmethod
    def _frame_key(frame):
        from .mac.window import frame_key  # noqa: PLC0415
        return frame_key(frame)

    def _poll_system(self, now):
        if self.visibility is not None and now >= self.next_system_poll:
            self.next_system_poll = now + SYSTEM_POLL
            reason = self.visibility.hidden_reason()
            if reason != self.hidden:
                print(f"Paused: {reason}." if reason else "Visible again: resuming.", flush=True)
                if reason is None:
                    self.painter.invalidate()
                    self.next_tick = now  # carry on from here; don't replay the hidden time
                self.hidden = reason
        if now >= self.next_screen_poll:
            if self.follow_monitor:
                self.next_screen_poll = now + SCREEN_POLL
                self._follow_monitor(now)
            elif self.home is not None:
                self.next_screen_poll = now + SCREEN_POLL
                self._keep_home(now)

    # ---- simulation and drawing
    def update(self):
        if not self.paused:
            self._step_world()

    def _step_world(self):
        # Inner worlds only step while they're on screen.
        region = self.view.visible_cells() if Painter.animates(self.view) else None
        if self.world.step(region):
            self.toast("World settled  -  starting a new one")

    def _background(self):
        if not self.transparent:
            return SOLID_BG
        if self.bg_alpha > 0:
            return (*SOLID_BG[:3], self.bg_alpha)  # tinted see-through backdrop
        return CLEAR_BG if self.pinned else CLICKABLE_BG

    def draw(self):
        now = time.monotonic()
        if self.show_help and now > self.help_until:
            self.show_help = False
        toast = self.toast_text if now < self.toast_until else None
        if self.transparent and self.mac is not None and self.mac.keep_transparent():
            self.painter.invalidate()
        self.painter.draw(self.world, self.view, self._background(), show_help=self.show_help,
                          toast=toast, outline=self.transparent and self.hovered and not self.pinned,
                          brush=self._brush_cells(), help_top=self.help_top)
        self._update_hud()

    def _advance(self, now):
        """Run every frame that is due by `now` (several after a sleep)."""
        steps = 0
        while now >= self.next_tick and steps < self.max_catchup:
            self.view.ease(self.dt)
            self.update()
            self.next_tick += self.dt
            steps += 1
        if now - self.next_tick > 1.0:  # far behind (system sleep, debugger): skip ahead
            self.next_tick = now + self.dt

    def _timeout(self, now):
        """How long to sleep before something on screen could change."""
        if self.hidden:
            return HIDDEN_WAIT
        wait = MAX_WAIT
        if self.view.easing:
            wait = self.next_tick - now  # gliding to a new zoom: every frame matters
        elif not self.paused:
            if Painter.animates(self.view):
                wait = self.next_tick - now  # inner worlds visible: every frame matters
            else:
                due = self.next_tick + self.world.frames_to_macro_step() * self.dt
                wait = min(wait, due - now)
        if self.hover:  # keep looking where the mouse is: often while it's over the window
            wait = min(wait, self.dt if self.hover_last is not None else HOVER_IDLE)
        if now < self.toast_until:
            wait = min(wait, self.toast_until - now)
        if self.show_help and self.help_until != math.inf:
            wait = min(wait, self.help_until - now)
        return max(0.0, wait)

    def _wait(self, timeout):
        if timeout <= 0:
            return
        if self.pinned or self.hidden:
            # No mouse or keyboard input reaches a pinned window, only the global hotkeys,
            # which arrive on the next event pump. A plain sleep costs ~3% less CPU than
            # pygame.event.wait(), which keeps waking up inside SDL (measured, SDL 2.32).
            # An Event wait costs the same as a sleep but the settings dialog can end it early.
            self.woken.wait(min(timeout, PINNED_WAIT if self.pinned else HIDDEN_WAIT))
            self.woken.clear()
            return
        # Round up: waking a hair early would just loop round and wait again.
        event = pygame.event.wait(math.ceil(timeout * 1000))
        if event.type != pygame.NOEVENT:
            self.handle(event)

    # ---- main loop
    def run(self):
        # Ctrl+C in the terminal, or launchctl stopping the login agent: leave the loop
        # cleanly (unregistering the global hotkeys) instead of dying mid-frame.
        def stop(*_):
            self.running = False
        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        # SIGUSR1: the Life in Life app was opened while this runs; show the settings
        # (it answers at the next wake-up, within a second).
        if hasattr(signal, "SIGUSR1"):
            def show_settings(*_):
                self.pending.append("settings")
                self.woken.set()
            signal.signal(signal.SIGUSR1, show_settings)
        running = settings.RUNNING_FILE
        try:
            running.parent.mkdir(parents=True, exist_ok=True)
            running.write_text(str(os.getpid()))
        except OSError:
            running = None  # the app just starts a second copy then
        try:
            while self.running:
                for event in pygame.event.get():
                    self.handle(event)
                while self.pending:
                    self.do(self.pending.pop(0))
                while not self.picked.empty():
                    kind, value = self.picked.get()
                    if kind == "apply":
                        self.toast("Applying…", 3)
                        if not self.hidden:
                            self.draw()  # show it before the (brief) work starts
                        self.apply_settings(value)
                    elif value is None:
                        self.toast_until = 0.0  # cancelled: drop the "…" message
                    else:
                        self.toast(value, 3)
                now = time.monotonic()
                self._save_hud_spots(now)
                self._poll_system(now)
                if not self.hidden:
                    self._hover()
                    self._advance(now)
                    self.draw()
                if self.running:
                    self._wait(self._timeout(time.monotonic()))
        finally:
            if running is not None and settings.live_pid(running) == os.getpid():
                running.unlink(missing_ok=True)  # unless a newer copy has taken it over
            self._save_hud_spots()  # a drag not saved yet (quit, or launchctl restarting it)
            if self.hud is not None:
                self.hud.close()
            if self.mac:
                self.mac.close()
            pygame.quit()
