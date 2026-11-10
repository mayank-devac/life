"""The menu bar icon: Start, Stop, Settings… and Quit for Life in Life.

It's its own little process (life --menubar, started by the Life in Life app), not part of the
wallpaper, so it stays in the menu bar while Life is stopped and can start it again.
No Dock icon. The menu is rebuilt each time it opens, so it always shows the current state."""
import importlib

AppKit = importlib.import_module("AppKit")  # ImportError without pyobjc
Foundation = importlib.import_module("Foundation")

# (title, action, enabled when: "running" / "stopped" / None = always)
ITEMS = [
    ("Start", "start", "stopped"),
    ("Stop", "stop", "running"),
    ("Settings…", "settings", "running"),
    None,  # separator
    ("Quit", "quit", None),
]
SYMBOL = "circle.grid.3x3.fill"  # SF Symbol for the icon; FALLBACK where there are none (< 11)
FALLBACK = "▦"


class _MenuTarget(Foundation.NSObject):
    def menuNeedsUpdate_(self, menu):
        self.owner._fill(menu)

    def clicked_(self, sender):
        self.owner._act(ITEMS[sender.tag()][1])


class MenuBar:
    """`is_running()` -> bool; `start()`, `stop()`, `settings()` act on Life. Quit stops Life
    too, then ends this process."""

    def __init__(self, is_running, start, stop, settings):
        self.is_running = is_running
        self.actions = {"start": start, "stop": stop, "settings": settings}
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
        status = menu.addItemWithTitle_action_keyEquivalent_(
            "Life in Life is running" if running else "Life in Life is stopped", None, "")
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
            item.setEnabled_(when is None or (when == "running") == running)

    def _act(self, action):
        if action == "quit":
            if self.is_running():
                self.actions["stop"]()
            AppKit.NSApplication.sharedApplication().terminate_(None)
            return
        self.actions[action]()

    def run(self):
        AppKit.NSApplication.sharedApplication().run()
