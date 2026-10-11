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

python=$(command -v python3) || fail "python3 was not found" ""
[ -f "$script" ] || fail "prelaunch.py is missing from the app" ""

errfile=$(mktemp -t notproton-prelaunch) || fail "could not create a temporary file" ""
echo "=== $(date) prelaunch with $python ===" >> "$log"
"$python" "$script" >> "$log" 2> "$errfile"
status=$?
cat "$errfile" >> "$log"
err=$(cat "$errfile")
rm -f "$errfile"
[ "$status" -eq 0 ] || fail "prelaunch.py exited with status $status" "$err"

exec "$real" "$@"
