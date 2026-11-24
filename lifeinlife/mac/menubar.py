"""The menu bar icon: Start, Stop, Settings…, Upgrade and Quit for Life in Life.

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
    ("Upgrade", "upgrade", "upgrade"),
    None,
    ("Quit", "quit", None),
]
SYMBOL = "circle.grid.3x3.fill"  # SF Symbol for the icon; FALLBACK where there are none (< 11)
FALLBACK = "▦"
OUTPUT_TAIL = 1500  # characters of the upgrade's output shown when it fails


class _MenuTarget(Foundation.NSObject):
    def menuNeedsUpdate_(self, menu):
        self.owner._fill(menu)

    def clicked_(self, sender):
        self.owner._act(ITEMS[sender.tag()][1])

    def upgradeDone_(self, _ignored):
        self.owner._upgrade_done()


class MenuBar:
    """`is_running()` -> bool; `start()`, `stop()`, `settings()` act on Life. Quit stops Life
    too, then ends this process. `can_upgrade()` -> bool; `upgrade()` -> (ok, output) runs
    off the main thread; after it worked, `restart()` restarts Life if it was running and
    `relaunch()` replaces this process with one on the new code."""

    def __init__(self, is_running, start, stop, settings, can_upgrade, upgrade, restart,
                 relaunch):
        self.is_running = is_running
        self.actions = {"start": start, "stop": stop, "settings": settings}
        self.can_upgrade, self.upgrade = can_upgrade, upgrade
        self.restart, self.relaunch = restart, relaunch
        self.upgrading = False
        self.result = None
        app = AppKit.NSApplication.sharedApplication()
        app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)  # no Dock icon
        self.target = _MenuTarget.alloc().init()
        self.target.owner = self
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
        menu.removeAllItems()
        if self.upgrading:
            text = "Upgrading Life in Life…"
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
                item.setEnabled_(not self.upgrading and self.can_upgrade())
            else:
                item.setEnabled_(not self.upgrading
                                 and (when is None or (when == "running") == running))

    def _act(self, action):
        if action == "quit":
            if self.is_running():
                self.actions["stop"]()
            AppKit.NSApplication.sharedApplication().terminate_(None)
            return
        if action == "upgrade":
            self._start_upgrade()
            return
        self.actions[action]()

    def _start_upgrade(self):
        """Run the upgrade on a thread (it downloads, so it takes a while) and come back to
        the main thread when it's done: AppKit only works there."""
        self.upgrading = True

        def work():
            self.result = self.upgrade()
            self.target.performSelectorOnMainThread_withObject_waitUntilDone_(
                "upgradeDone:", None, False)

        threading.Thread(target=work, daemon=True).start()

    def _upgrade_done(self):
        self.upgrading = False
        ok, output = self.result
        if not ok:
            self._alert("Upgrade failed", output[-OUTPUT_TAIL:] or "No output.")
            return
        if self.is_running():
            self.restart()
        self._alert("Life in Life is up to date",
                    "Upgraded. Life in Life was restarted on the new version if it was running.")
        AppKit.NSStatusBar.systemStatusBar().removeStatusItem_(self.item)  # before the new one
        self.relaunch()

    def _alert(self, title, text):
        AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(text)
        alert.runModal()

    def run(self):
        AppKit.NSApplication.sharedApplication().run()
