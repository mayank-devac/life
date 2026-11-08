"""macOS-only features. Everything here needs pyobjc-framework-Cocoa and is imported lazily
(see app.LifeInLife._get_mac), so the game still runs without it, just with fewer features.

    window      - transparent, pinned-to-desktop window; monitor list
    hotkeys     - system-wide Ctrl+Shift shortcuts (Carbon, no permission prompt)
    visibility  - is anyone able to see the window? (screen locked, display asleep)
"""
