#!/usr/bin/env bash
# Start the Life wallpaper (wall.sh) automatically when you log in to macOS.
#
#   ./login.sh install     start at every login (and start it right now)
#   ./login.sh uninstall   stop starting at login (and stop it now)
#   ./login.sh status      show whether it is installed / running, and its settings
#
# Change it without editing wall.sh (applies right away, and at every login):
#   Ctrl+Shift+S           while it runs: pick colour, speed and monitor in a small window (live)
#   ./login.sh             the same window from the terminal (same as: settings)
#   ./login.sh color red   cell colour: multi, white, black, gray, red, orange, yellow,
#                          green, cyan, blue, purple, pink, mauve, or a hex like ff8800,
#                          or a theme: heat, ocean, neon, forest, sunset, ice
#   ./login.sh speed 4     outer generations per second (0.5, 1, 2, 4 ...)
#   ./login.sh monitor 2   which monitor to cover (1 = the one with the menu bar)
#   ./login.sh monitors    list the monitors and their numbers
#   ./login.sh reset       forget those choices, use wall.sh's values again
#
# Everything else (opacity, zoom, ...) comes from wall.sh: edit that file, then
# run  ./login.sh install  again. Colour/speed/monitor choices made here are kept.
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
PY="$APP/.venv-life/bin/python"
SETTINGS="$APP/settings"   # lines like  color=red, speed=4; wall.sh reads it and passes  --color red
DOMAIN="gui/$(id -u)"
FILES=("life inside life.py" "wall.sh" "requirements.txt")
PACKAGE="lifeinlife"   # the code; copied whole, minus __pycache__

# Escape text for use inside the plist's XML (& < > in a path would break it).
xml() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }

install() {
    for f in "${FILES[@]}"; do
        [ -f "$SRC/$f" ] || { echo "$f not found in $SRC"; exit 1; }
    done
    [ -d "$SRC/$PACKAGE" ] || { echo "$PACKAGE/ not found in $SRC"; exit 1; }
    mkdir -p "$APP" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"

    # Stop the running copy before replacing its files.
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null

    echo "Copying app to $APP"
    for f in "${FILES[@]}"; do
        cp "$SRC/$f" "$APP/$f" || { echo "Couldn't copy $f"; exit 1; }
    done
    # Replace the package whole, so files deleted from the repo don't linger in the copy.
    rm -rf "${APP:?}/$PACKAGE"
    cp -R "$SRC/$PACKAGE" "$APP/$PACKAGE" || { echo "Couldn't copy $PACKAGE/"; exit 1; }
    find "$APP/$PACKAGE" -name __pycache__ -type d -prune -exec rm -rf {} +
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

    start
    echo "Installed: Life wallpaper will start at every login (running now)."
    echo "Log: $LOG"
}

# Write the LaunchAgent plist and (re)start the wallpaper with it.
start() {
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null
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
        <!-- wall.sh trims this log when it grows past 1 MB -->
        <key>LIFE_LOG</key>
        <string>$(xml "$LOG")</string>
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

    # Right after a bootout launchd can still be tearing the old one down; retry briefly.
    local try
    for try in 1 2 3 4 5; do
        launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null && return 0
        sleep 1
    done
    launchctl bootstrap "$DOMAIN" "$PLIST" || { echo "Failed to load $PLIST"; exit 1; }
}

# Restart the running wallpaper so wall.sh reads $SETTINGS again (or start it if it isn't loaded).
restart() {
    launchctl kickstart -k "$DOMAIN/$LABEL" >/dev/null 2>&1 || start
}

need_install() {
    [ -f "$PLIST" ] && [ -x "$PY" ] && return 0
    echo "Not installed yet, installing first."
    install
}

# Save key=value in $SETTINGS (the same file Ctrl+Shift+S writes), replacing any earlier
# value. Call restart afterwards to apply.
write_setting() {
    local key="$1" value="$2"
    { [ -f "$SETTINGS" ] && grep -v "^$key=" "$SETTINGS"; echo "$key=$value"; } > "$SETTINGS.tmp"
    mv "$SETTINGS.tmp" "$SETTINGS"
}

# Check a colour with the app's own parser, so the list of names never goes out of date.
# Prints the error and fails if it's not a colour.
check_color() {
    local err
    err="$(cd "$APP" && "$PY" -c 'import sys; from lifeinlife.colors import parse_color; parse_color(sys.argv[1])' "$1" 2>&1)" \
        || { err="$(tail -n 1 <<<"$err")"; echo "${err#*Error: }"; return 1; }
}

set_color() {
    [ -n "$1" ] || { echo "Usage: $0 color <multi|white|red|...|ff8800>"; exit 1; }
    need_install
    check_color "$1" || exit 1
    write_setting color "$1"
    restart
    echo "Colour set to $1 (running now, and at every login)."
}

set_speed() {
    [[ "$1" =~ ^([0-9]+\.?[0-9]*|\.[0-9]+)$ ]] && awk "BEGIN{exit !($1 > 0)}" \
        || { echo "Usage: $0 speed <generations per second, like 0.5, 2 or 8>"; exit 1; }
    need_install
    write_setting speed "$1"
    restart
    echo "Speed set to $1/s (running now, and at every login)."
}

# The same colour / speed / monitor window as Ctrl+Shift+S (the dialog lives in lifeinlife/settings.py).
# Going through wall.sh means the dialog starts from the values in use right now.
gui() {
    need_install
    bash "$WALL" --settings || return 0   # cancelled
    echo "Applying… (restarting the wallpaper)"
    restart
    echo "Applied (running now, and at every login)."
}

list_monitors() {
    # wall.sh handles --list-monitors (prints and exits). Use the installed copy if there is one.
    local wall="$WALL"
    [ -f "$wall" ] || wall="$SRC/wall.sh"
    bash "$wall" --list-monitors
}

set_monitor() {
    [[ "$1" =~ ^[1-9][0-9]*$ ]] || { echo "Usage: $0 monitor <1|2|3...>   (see: $0 monitors)"; exit 1; }
    need_install
    local count
    count="$(list_monitors | grep -cE '^[[:space:]]+[0-9]+:')"
    if [ "$count" -gt 0 ] && [ "$1" -gt "$count" ]; then
        echo "Note: only $count monitor(s) connected now; it will cover monitor $1 when it's plugged in."
    fi
    write_setting monitor "$1"
    restart
    echo "Monitor set to $1 (running now, and at every login)."
}

reset_settings() {
    need_install
    rm -f "$SETTINGS"
    restart
    echo "Cleared: colour, speed and monitor come from wall.sh again."
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
    if [ -s "$SETTINGS" ]; then
        echo "Settings (override wall.sh):"
        sed 's/^/  /; s/=/: /' "$SETTINGS"
    elif [ -d "$APP" ]; then
        echo "Settings: all from wall.sh"
    fi
}

case "$1" in
    install)   install ;;
    uninstall) uninstall ;;
    status)    status ;;
    color|colour) set_color "$2" ;;
    speed)     set_speed "$2" ;;
    monitor)   set_monitor "$2" ;;
    monitors)  list_monitors ;;
    reset)     reset_settings ;;
    ""|settings|gui) gui ;;
    *) echo "Usage: $0 [settings|install|uninstall|status|color <name>|speed <n>|monitor <n>|monitors|reset]"; exit 1 ;;
esac
