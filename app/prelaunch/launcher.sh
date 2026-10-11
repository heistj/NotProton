#!/bin/sh
# make app installs this as Contents/MacOS/NotProtonApp, the bundle's executable, and
# the real binary beside it as NotProtonApp.real. It runs prelaunch.py and opens
# NotProton only if the script exits 0.

contents=$(cd -- "$(dirname -- "$0")/.." && pwd)
real="$contents/MacOS/NotProtonApp.real"
script="$contents/Resources/prelaunch.py"

# Removing NotProton must never depend on the script.
for arg in "$@"; do
  [ "$arg" = --remove-everything ] && exec "$real" "$@"
done

logdir="$HOME/Library/Logs/NotProton"
log="$logdir/prelaunch.log"
mkdir -p "$logdir"

# Apps opened from Finder get a bare PATH, which misses Homebrew's python3.
PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export PATH

fail() {
  echo "=== $(date) prelaunch blocked the launch: $1 ===" >> "$log"
  # A quote or backslash would end the AppleScript string early.
  detail=$(printf '%s' "$2" | tr -d '"\\' | tail -c 1500)
  osascript >/dev/null 2>&1 <<APPLESCRIPT
display alert "NotProton did not open" message "$1

$detail

Log: $log" as critical
APPLESCRIPT
  exit 1
}

[ -f "$script" ] || fail "prelaunch.py is missing from the app" ""

# Homebrew's and python.org's go first. /usr/bin/python3 is on every Mac, but it is
# only a stub until the Command Line Tools are installed, so it counts only once
# xcode-select reports a developer directory.
find_python() {
  for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    [ -x "$candidate" ] && "$candidate" -c '' 2>/dev/null && { echo "$candidate"; return 0; }
  done
  xcode-select -p >/dev/null 2>&1 && [ -x /usr/bin/python3 ] \
    && /usr/bin/python3 -c '' 2>/dev/null && { echo /usr/bin/python3; return 0; }
  return 1
}

if ! python=$(find_python); then
  echo "=== $(date) no python3, asking macOS to install the Command Line Tools ===" >> "$log"
  # Apple's installer asks before it installs anything, and runs on its own after this exits.
  xcode-select --install >> "$log" 2>&1
  fail "NotProton needs Python, which comes with Apple's Command Line Tools" \
    "Click Install in the window macOS opened. When it finishes, open NotProton again."
fi

errfile=$(mktemp -t notproton-prelaunch) || fail "could not create a temporary file" ""
echo "=== $(date) prelaunch with $python ===" >> "$log"
"$python" "$script" >> "$log" 2> "$errfile"
status=$?
cat "$errfile" >> "$log"
err=$(cat "$errfile")
rm -f "$errfile"
[ "$status" -eq 0 ] || fail "prelaunch.py exited with status $status" "$err"

exec "$real" "$@"
