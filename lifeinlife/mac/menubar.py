"""The menu bar icon: Start, Stop, Settings…, Upgrade… and Quit for Life in Life.

It's its own little process (life --menubar, started by the Life in Life app), not part of the
wallpaper, so it stays in the menu bar while Life is stopped and can start it again.
No Dock icon. The menu is rebuilt each time it opens, so it always shows the current state."""
import importlib
import threading

AppKit = importlib.import_module("AppKit")  # ImportError without pyobjc
Foundation = importlib.import_module("Foundation")

# (title, action, enabled when: "running" / "stopped" / "upgrade" / None = always)
ITEMS = [
    ("Start", "start", "stopped"),
    ("Stop", "stop", "running"),
    ("Settings…", "settings", "running"),
    None,  # separator
    ("Upgrade…", "upgrade", "upgrade"),
    None,
    ("Quit", "quit", None),
]
SYMBOL = "circle.grid.3x3.fill"  # SF Symbol for the icon; FALLBACK where there are none (< 11)
FALLBACK = "▦"
OUTPUT_TAIL = 600  # characters of a failed upgrade's output shown in the window
RELAUNCH_DELAY = 1.5  # seconds "Updated" stays on screen before the icon restarts


class _MenuTarget(Foundation.NSObject):
    def menuNeedsUpdate_(self, menu):
        self.owner._fill(menu)

    def clicked_(self, sender):
        self.owner._act(ITEMS[sender.tag()][1])

    # Back on the main thread after work done on another one (AppKit only works here).
    def checkDone_(self, _ignored):
        self.owner.upgrader.check_done()

    def upgradeDone_(self, _ignored):
        self.owner.upgrader.upgrade_done()

    def relaunch_(self, _ignored):
        self.owner._relaunch()

    # The upgrade window's buttons.
    def primary_(self, _sender):
        self.owner.upgrader.primary()

    def secondary_(self, _sender):
        self.owner.upgrader.panel.orderOut_(None)


class _Upgrader:
    """The small Upgrade window: checks GitHub, shows "1.0.1 → 1.0.2", updates on a click,
    then restarts Life and the menu bar icon on the new version."""
    W, H = 380, 150

    def __init__(self, owner):
        self.owner = owner
        self.busy = False  # checking or updating
        self.updating = False
        self.current = self.latest = None
        self.next_step = None  # what the primary button does now: "upgrade" or "close"
        target = owner.target
        style = AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable
        panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            Foundation.NSMakeRect(0, 0, self.W, self.H), style, AppKit.NSBackingStoreBuffered,
            False)
        panel.setTitle_("Upgrade Life in Life")
        panel.setReleasedWhenClosed_(False)
        panel.setLevel_(AppKit.NSFloatingWindowLevel)
        view = panel.contentView()
        pad = 20
        self.title = AppKit.NSTextField.labelWithString_("")
        self.title.setFont_(AppKit.NSFont.boldSystemFontOfSize_(13))
        self.title.setFrame_(Foundation.NSMakeRect(pad, self.H - 40, self.W - 2 * pad - 24, 20))
        self.spinner = AppKit.NSProgressIndicator.alloc().initWithFrame_(
            Foundation.NSMakeRect(self.W - pad - 16, self.H - 38, 16, 16))
        self.spinner.setStyle_(AppKit.NSProgressIndicatorStyleSpinning)
        self.spinner.setControlSize_(AppKit.NSControlSizeSmall)
        self.spinner.setDisplayedWhenStopped_(False)
        self.detail = AppKit.NSTextField.wrappingLabelWithString_("")
        self.detail.setFont_(AppKit.NSFont.systemFontOfSize_(12))
        self.detail.setTextColor_(AppKit.NSColor.secondaryLabelColor())
        self.detail.setFrame_(Foundation.NSMakeRect(pad, 52, self.W - 2 * pad, self.H - 98))
        self.detail.setSelectable_(True)  # so an error can be copied
        self.primary_button = AppKit.NSButton.buttonWithTitle_target_action_(
            "Update", target, "primary:")
        self.primary_button.setKeyEquivalent_("\r")
        self.secondary_button = AppKit.NSButton.buttonWithTitle_target_action_(
            "Later", target, "secondary:")
        self.secondary_button.setKeyEquivalent_("\x1b")  # Esc
        for button in (self.primary_button, self.secondary_button):
            button.setFrame_(Foundation.NSMakeRect(0, 14, 96, 30))
        self.primary_button.setFrameOrigin_((self.W - pad - 96, 14))
        self.secondary_button.setFrameOrigin_((self.W - pad - 196, 14))
        for v in (self.title, self.spinner, self.detail, self.primary_button,
                  self.secondary_button):
            view.addSubview_(v)
        self.panel = panel

    def _show(self, title, detail, primary=None, secondary=None, spinning=False):
        """Set what the window says. primary / secondary: button titles, None hides one."""
        self.title.setStringValue_(title)
        self.detail.setStringValue_(detail)
        for button, text in ((self.primary_button, primary), (self.secondary_button, secondary)):
            button.setHidden_(text is None)
            if text is not None:
                button.setTitle_(text)
        if spinning:
            self.spinner.startAnimation_(None)
        else:
            self.spinner.stopAnimation_(None)

    def _on_thread(self, work, done_selector):
        def run():
            work()
            self.owner.target.performSelectorOnMainThread_withObject_waitUntilDone_(
                done_selector, None, False)
        threading.Thread(target=run, daemon=True).start()

    def open(self):
        """The menu's Upgrade…: show the window and check what's on GitHub."""
        AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        if not self.panel.isVisible():
            self.panel.center()
        self.panel.makeKeyAndOrderFront_(None)
        if self.busy:
            return  # already checking / updating: just bring the window back
        self.busy = True
        self._show("Checking for updates…", "", secondary="Cancel", spinning=True)

        def check():
            self.current, self.latest = self.owner.versions()
        self._on_thread(check, "checkDone:")

    def check_done(self):
        self.busy = False
        current, latest = self.current or "unknown", self.latest
        if latest is None:
            self.next_step = "upgrade"
            self._show("Couldn't check for updates",
                       f"Current version: {current}\nLatest version: couldn't reach GitHub.",
                       primary="Update anyway", secondary="Close")
        elif self.current is None or self.owner.is_newer(latest, self.current):
            self.next_step = "upgrade"
            self._show(f"Version {latest} is available",
                       f"Current version: {current}\nLatest version: {latest}",
                       primary="Update", secondary="Later")
        else:
            self.next_step = "close"
            self._show("Life in Life is up to date", f"Current version: {current}",
                       primary="OK")

    def primary(self):
        if self.next_step != "upgrade":
            self.panel.orderOut_(None)
            return
        self.busy = self.updating = True
        self.next_step = None
        self._show(f"Updating to {self.latest or 'the latest version'}…",
                   f"Current version: {self.current or 'unknown'}\n"
                   "Downloading and installing. This can take a minute.", spinning=True)

        def upgrade():
            self.result = self.owner.upgrade()
            if self.result[0] and self.owner.is_running():
                self.owner.restart()  # Life runs the new code from here on
        self._on_thread(upgrade, "upgradeDone:")

    def upgrade_done(self):
        self.busy = self.updating = False
        ok, output = self.result
        if not ok:
            self.next_step = "close"
            self._show("Update failed", output[-OUTPUT_TAIL:] or "No output.", primary="Close")
            return
        version = self.latest or "the latest version"
        self._show(f"Updated to {version}", "Restarting Life in Life…", spinning=True)
        self.owner.target.performSelector_withObject_afterDelay_(
            "relaunch:", None, RELAUNCH_DELAY)


class MenuBar:
    """`is_running()` -> bool; `start()`, `stop()`, `settings()` act on Life. Quit stops Life
    too, then ends this process. Upgrade…: `can_upgrade()` -> bool, `versions()` ->
    (current, latest or None), `is_newer(a, b)`, `upgrade()` -> (ok, output); after it worked,
    `restart()` restarts Life if it was running and `relaunch()` replaces this process with
    one on the new code."""

    def __init__(self, is_running, start, stop, settings, can_upgrade, upgrade, versions,
                 is_newer, restart, relaunch):
        self.is_running = is_running
        self.actions = {"start": start, "stop": stop, "settings": settings}
        self.can_upgrade, self.upgrade = can_upgrade, upgrade
        self.versions, self.is_newer = versions, is_newer
        self.restart, self.relaunch = restart, relaunch
        app = AppKit.NSApplication.sharedApplication()
        app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)  # no Dock icon
        self.target = _MenuTarget.alloc().init()
        self.target.owner = self
        self.upgrader = _Upgrader(self)
        self.item = AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(
            AppKit.NSVariableStatusItemLength)
        button = self.item.button()
        image = None
        if hasattr(AppKit.NSImage, "imageWithSystemSymbolName_accessibilityDescription_"):
            image = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                SYMBOL, "Life in Life")
        if image is not None:
            image.setTemplate_(True)  # follows the menu bar's light / dark look
            button.setImage_(image)
        else:
            button.setTitle_(FALLBACK)
        button.setToolTip_("Life in Life")
        menu = AppKit.NSMenu.alloc().init()
        menu.setAutoenablesItems_(False)
        menu.setDelegate_(self.target)
        self.item.setMenu_(menu)

    def _fill(self, menu):
        running = self.is_running()
        updating = self.upgrader.updating
        menu.removeAllItems()
        if updating:
            text = "Updating Life in Life…"
        else:
            text = "Life in Life is running" if running else "Life in Life is stopped"
        status = menu.addItemWithTitle_action_keyEquivalent_(text, None, "")
        status.setEnabled_(False)
        menu.addItem_(AppKit.NSMenuItem.separatorItem())
        for tag, entry in enumerate(ITEMS):
            if entry is None:
                menu.addItem_(AppKit.NSMenuItem.separatorItem())
                continue
            title, _action, when = entry
            item = menu.addItemWithTitle_action_keyEquivalent_(title, "clicked:", "")
            item.setTarget_(self.target)
            item.setTag_(tag)
            if when == "upgrade":
                item.setEnabled_(self.can_upgrade())  # while busy it brings the window back
            else:
                item.setEnabled_(not updating
                                 and (when is None or (when == "running") == running))

    def _act(self, action):
        if action == "quit":
            if self.is_running():
                self.actions["stop"]()
            AppKit.NSApplication.sharedApplication().terminate_(None)
            return
        if action == "upgrade":
            self.upgrader.open()
            return
        self.actions[action]()

    def _relaunch(self):
        """After an upgrade: remove this icon, then start a fresh menu bar process on the new
        code (see relaunch_menubar in cli.py for why not os.execv)."""
        self.upgrader.panel.orderOut_(None)
        AppKit.NSStatusBar.systemStatusBar().removeStatusItem_(self.item)
        self.relaunch()

    def run(self):
        AppKit.NSApplication.sharedApplication().run()
