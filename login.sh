#!/usr/bin/env bash
# Start the Life wallpaper (wall.sh) automatically when you log in to macOS.
#
#   ./login.sh install     start at every login (and start it right now)
#   ./login.sh uninstall   stop starting at login (and stop it now)
#   ./login.sh status      show whether it is installed / running
#
# Settings (opacity, colour, monitor...) still come from wall.sh: edit that file,
# then run  ./login.sh install  again to restart with the new settings.
# Output and errors go to ~/Library/Logs/life-wallpaper.log
#
# Why it copies itself: macOS blocks programs started at login from reading
# Downloads, Desktop, Documents and iCloud Drive, which is where a cloned repo
# usually lives. So install copies the app (and builds its own Python
# environment) into ~/Library/Application Support/life-wallpaper, and runs it
# from there. The repo can live anywhere, or even be deleted afterwards.

LABEL="com.$(id -un).life-wallpaper"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/life-wallpaper.log"
SRC="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/Library/Application Support/life-wallpaper"
WALL="$APP/wall.sh"
DOMAIN="gui/$(id -u)"
FILES=("life inside life.py" "wall.sh" "requirements.txt")

# Escape text for use inside the plist's XML (& < > in a path would break it).
xml() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }

install() {
    for f in "${FILES[@]}"; do
        [ -f "$SRC/$f" ] || { echo "$f not found in $SRC"; exit 1; }
    done
    mkdir -p "$APP" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"

    # Stop the running copy before replacing its files.
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null

    echo "Copying app to $APP"
    for f in "${FILES[@]}"; do
        cp "$SRC/$f" "$APP/$f" || { echo "Couldn't copy $f"; exit 1; }
    done
    chmod +x "$WALL"

    # wall.sh looks for .venv-life next to itself.
    local venv="$APP/.venv-life"
    if [ ! -x "$venv/bin/python" ]; then
        local py="${PYTHON:-python3}"
        command -v "$py" >/dev/null || { echo "python3 not found (set PYTHON=/path/to/python3)"; exit 1; }
        echo "Creating Python environment with $("$py" --version 2>&1)"
        "$py" -m venv "$venv" || { echo "Couldn't create $venv"; exit 1; }
    fi
    echo "Installing requirements (first time takes a minute)"
    "$venv/bin/python" -m pip install -q --disable-pip-version-check -r "$APP/requirements.txt" \
        || { echo "pip install failed"; exit 1; }

    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$(xml "$LABEL")</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$(xml "$WALL")</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$(xml "$APP")</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <!-- Restart only if it crashes; quitting it yourself (Ctrl+Shift+Esc) keeps it closed. -->
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>ProcessType</key>
    <string>Interactive</string>
    <key>StandardOutPath</key>
    <string>$(xml "$LOG")</string>
    <key>StandardErrorPath</key>
    <string>$(xml "$LOG")</string>
</dict>
</plist>
EOF
    plutil -lint -s "$PLIST" || { echo "Generated plist is invalid: $PLIST"; exit 1; }

    launchctl bootstrap "$DOMAIN" "$PLIST" || { echo "Failed to load $PLIST"; exit 1; }
    echo "Installed: Life wallpaper will start at every login (running now)."
    echo "Log: $LOG"
}

uninstall() {
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null
    rm -f "$PLIST"
    rm -rf "$APP"
    echo "Uninstalled: it will no longer start at login."
}

status() {
    if [ -f "$PLIST" ]; then echo "Installed: $PLIST"; else echo "Not installed."; fi
    [ -d "$APP" ] && echo "App copy:  $APP"
    if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
        launchctl print "$DOMAIN/$LABEL" | grep -E '^[[:space:]]*(state|pid|last exit code)' \
            | sed 's/^[[:space:]]*/  /'
    fi
}

case "$1" in
    install)   install ;;
    uninstall) uninstall ;;
    status)    status ;;
    *) echo "Usage: $0 {install|uninstall|status}"; exit 1 ;;
esac
