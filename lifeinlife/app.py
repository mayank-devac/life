"""The app: window, input, actions and the main loop.

The main loop is event-driven, not a fixed 30 fps spin:
    - Zoomed out, the picture only changes when the outer world steps (every MACRO_EVERY
      frames, ~0.5 s at 30 fps), so between steps it sleeps in pygame.event.wait() and
      wakes up for input, a step, or a toast/help timer. About 2 wake-ups a second.
    - Zoomed in, the inner worlds move every frame, so it wakes up every frame.
    - While nobody can see the window (screen locked, display asleep) it stops
      simulating and drawing, and checks again once a second.
Time is kept with a frame clock (`next_tick`), so the speed is the same either way.
"""
import math
import queue
import signal
import sys
import threading
import time

import pygame
from pygame._sdl2.video import Renderer

from . import settings
from .colors import parse_color
from .config import (CLEAR_BG, CLICK_SLOP, CLICKABLE_BG, HIDDEN_WAIT, MACRO_EVERY, MAX_WAIT, MONITOR_GRACE,
                     PINNED_WAIT, SCREEN_POLL, SOLID_BG, SYSTEM_POLL)
from .render import Painter
from .view import View
from .world import World

# Ctrl+Shift + <key> -> action, while the window has focus.
PYGAME_KEYS = {
    pygame.K_ESCAPE: "quit",
    pygame.K_w: "wallpaper",
    pygame.K_h: "help",
    pygame.K_SPACE: "pause",
    pygame.K_r: "reseed",
    pygame.K_s: "settings",
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
        self.color_name = args.color_name
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
        self.world = World(args.grid, args.color)
        self.view = View(px_w, px_h, args.grid)
        self.view.zoom_at(args.zoom, px_w / 2, px_h / 2)  # start-up scale

        self.opacity = max(0.1, min(1.0, args.opacity))
        self.window.opacity = self.opacity
        self.bg_alpha = round(max(0.0, min(1.0, args.bg_opacity)) * 255)
        self.dt = 1 / max(1, args.fps)
        # Longest catch-up after a sleep; beyond that, time jumps instead of replaying frames.
        self.max_catchup = MACRO_EVERY + math.ceil(MAX_WAIT / self.dt) + 1
        self.next_tick = time.monotonic()

        self.paused = False
        self.running = True
        self.show_help = not args.wallpaper
        self.help_until = time.monotonic() + 6  # start-up help fades away on its own
        self.toast_text, self.toast_until = "", 0.0
        self.drag_mode = None  # None | "move" | "pan"
        self.grab = (0, 0)     # where the window was grabbed, for "move"
        self.dragged = 0.0     # how far (points) the mouse moved during this "pan"
        self.hovered = False
        self.pending = []      # actions coming from the global hotkeys

        self.hidden = None     # why nobody can see the window, or None
        self.visibility = None
        self.next_system_poll = 0.0
        self.next_screen_poll = 0.0
        self.follow_monitor = False  # wallpaper mode: keep the window on the chosen monitor
        self.monitor_missing_since = None  # when the chosen monitor went away, or None
        self.placed = None  # (target frame, frame we actually got) after the last move
        self.hud = None        # pinned: the clickable play / pause / step panel
        self.hud_error = None
        self.hud_key = None    # (generation, paused, window frame) it last showed

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
            self._show_hud()
            self.follow_monitor = True
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
        """Pinned: show the play / pause / step panel (clicks can't reach the wallpaper)."""
        if self.hud is None and self.hud_error is None:
            try:
                from .mac.hud import Hud  # noqa: PLC0415 - macOS only
                self.hud = Hud(self._on_hotkey)  # clicks arrive like global hotkeys
            except Exception as exc:  # noqa: BLE001 - nice to have, never fatal
                self.hud_error = exc
                print(f"Note: can't show the play / pause panel ({exc}).")
        if self.hud is not None and self.mac is not None:
            self.hud_key = None  # place and fill it on the next draw
            self.hud.show(self.mac.win.screen())

    def _update_hud(self):
        if self.hud is None or self.mac is None or not self.mac.pinned:
            return
        frame = self._frame_key(self.mac.frame())
        key = (self.world.generation, self.paused, frame)
        if key == self.hud_key:
            return
        if self.hud_key is None or self.hud_key[2] != frame:
            self.hud.place(self.mac.win.screen())  # the wallpaper moved to another monitor
        self.hud_key = key
        self.hud.update(self.world.age, self.world.population, self.paused)

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
        elif action == "reseed":
            self.world.reseed()
            self.toast("New world")
        elif action == "help":
            self.show_help = not self.show_help
            self.help_until = math.inf
        elif action in ("opacity+", "opacity-"):
            step = 0.1 if action == "opacity+" else -0.1
            self.opacity = round(max(0.1, min(1.0, self.opacity + step)), 2)
            self.window.opacity = self.opacity
            self.toast(f"Opacity {round(self.opacity * 100)}%")
        elif action in ("zoom+", "zoom-"):
            self.view.zoom_at(1.25 if action == "zoom+" else 0.8, self.view.w / 2, self.view.h / 2)
        elif action == "wallpaper":
            self.toggle_wallpaper()
        elif action == "settings":
            self.open_settings()

    def open_settings(self):
        """Show the colour / monitor dialog. It runs in its own thread (osascript blocks
        until it's answered) so the wallpaper keeps going meanwhile."""
        if self.dialog is not None and self.dialog.is_alive():
            return  # already open
        color, monitor = self.color_name, self.monitor
        self.toast("Opening settings…", 3)  # osascript takes a moment to show the window

        def tell(kind, value):
            self.picked.put((kind, value))  # the main loop acts on it (pygame isn't thread-safe)
            self.woken.set()                # end a pinned / hidden sleep now
            try:
                pygame.event.post(pygame.event.Event(self.WAKE))  # end event.wait() now
            except pygame.error:
                pass  # still seen on the next wake-up, at most MAX_WAIT later

        def ask():
            picked = settings.choose(color, monitor, progress=lambda text: tell("toast", text))
            if picked is None:
                tell("toast", None)  # cancelled
            else:
                tell("apply", picked)

        self.dialog = threading.Thread(target=ask, name="settings-dialog", daemon=True)
        self.dialog.start()

    def apply_settings(self, color_name, monitor):
        """Apply a choice from the dialog right away, and save it for the next start."""
        self.world.set_color(parse_color(color_name))  # the dialog already checked it
        self.color_name = color_name
        self.monitor = monitor
        if self.wallpaper_mode and self.mac is not None:
            # Cover the chosen monitor, pinned or not, even if it's the one already chosen:
            # the window may have been moved off it (e.g. by macOS while it was asleep).
            # The frame carries its size and position, so a different resolution is
            # picked up too (via WINDOWSIZECHANGED).
            self.monitor_missing_since = None
            target = self._monitor_frame(monitor)
            if target is not None:
                self._cover(target, force=True)
        self.painter.invalidate()
        try:
            settings.save(color=color_name, monitor=monitor)
            self.toast(f"Colour {color_name}  -  monitor {monitor}", 2.5)
        except OSError as exc:
            self.toast(f"Applied, but couldn't save it ({exc.strerror})", 3.5)

    def toggle_wallpaper(self):
        mac = self._get_mac()
        if mac is None:
            self.toast(f"Wallpaper mode {self.mac_error}", 3.5)
            return
        self.drag_mode = None
        if mac.pinned:
            mac.unpin()
            mac.unwatch_hotkeys()
            if self.hud is not None:
                self.hud.hide()
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

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button in (1, 3):
            mods = pygame.key.get_mods()
            if (mods & pygame.KMOD_CTRL) and (mods & pygame.KMOD_SHIFT):
                # Remember where we grabbed; moving the window by event.rel jitters because
                # the window moving under the cursor feeds back into the next rel.
                self.drag_mode, self.grab = "move", event.pos
            elif event.button == 1:
                self.drag_mode, self.dragged = "pan", 0.0

        elif event.type == pygame.MOUSEBUTTONUP and event.button in (1, 3):
            # A press that (almost) didn't move is a click, not a pan: toggle that cell.
            if event.button == 1 and self.drag_mode == "pan" and self.dragged < CLICK_SLOP:
                cell = self.view.cell_at(event.pos[0] * self.dpr, event.pos[1] * self.dpr)
                if cell is not None:
                    self.world.toggle(*cell)
            self.drag_mode = None

        elif event.type == pygame.MOUSEMOTION and self.drag_mode == "move":
            wx, wy = self.window.position
            self.window.position = (wx + event.pos[0] - self.grab[0], wy + event.pos[1] - self.grab[1])

        elif event.type == pygame.MOUSEMOTION and self.drag_mode == "pan":
            self.dragged += abs(event.rel[0]) + abs(event.rel[1])
            self.view.pan(event.rel[0] * self.dpr, event.rel[1] * self.dpr)

        elif event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            self.view.zoom_at(1.12 ** event.precise_y, mx * self.dpr, my * self.dpr)

        elif event.type == pygame.WINDOWENTER:
            self.hovered = True
        elif event.type == pygame.WINDOWLEAVE:
            self.hovered = False
        elif event.type == pygame.WINDOWFOCUSLOST:
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
        if self.follow_monitor and now >= self.next_screen_poll:
            self.next_screen_poll = now + SCREEN_POLL
            self._follow_monitor(now)

    # ---- simulation and drawing
    def update(self):
        if not self.paused:
            self._step_world()

    def _step_world(self):
        if self.world.step():
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
                          toast=toast, outline=self.transparent and self.hovered and not self.pinned)
        self._update_hud()

    def _advance(self, now):
        """Run every frame that is due by `now` (several after a sleep)."""
        steps = 0
        while now >= self.next_tick and steps < self.max_catchup:
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
        if not self.paused:
            if Painter.animates(self.view):
                wait = self.next_tick - now  # inner worlds visible: every frame matters
            else:
                due = self.next_tick + self.world.frames_to_macro_step() * self.dt
                wait = min(wait, due - now)
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
                        self.apply_settings(*value)
                    elif value is None:
                        self.toast_until = 0.0  # cancelled: drop the "…" message
                    else:
                        self.toast(value, 3)
                now = time.monotonic()
                self._poll_system(now)
                if not self.hidden:
                    self._advance(now)
                    self.draw()
                if self.running:
                    self._wait(self._timeout(time.monotonic()))
        finally:
            if self.hud is not None:
                self.hud.close()
            if self.mac:
                self.mac.close()
            pygame.quit()
