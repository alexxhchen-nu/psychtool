#!/bin/sh
# Start Psychtool. Double-click in Finder (macOS). This script is also
# runnable with sh on Linux for automated tests; Linux is not a claimed
# double-click deliverable.
set -u

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd) || exit 1
cd "$ROOT" || exit 1

PORT=${PSYCHTOOL_PORT:-8000}
URL="http://127.0.0.1:${PORT}/"
HEALTH="${URL}api/health"

plain_fail() {
  echo "This copy of psychtool isn't ready to start. Ask the person who installed it to check the installation, then try again." >&2
  exit 1
}

health_ok() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -c "import urllib.request,sys; urllib.request.urlopen(sys.argv[1], timeout=1).read()" "$HEALTH" >/dev/null 2>&1
  elif command -v curl >/dev/null 2>&1; then
    curl -sf --max-time 1 "$HEALTH" >/dev/null 2>&1
  else
    return 1
  fi
}

open_browser() {
  if command -v open >/dev/null 2>&1; then
    open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL"
  else
    echo "Open this address in your browser: $URL"
  fi
}

if health_ok; then
  open_browser
  exit 0
fi

if command -v uv >/dev/null 2>&1; then
  uv run psychtool-server &
  SERVER_PID=$!
elif [ -x "$ROOT/.venv/bin/psychtool-server" ]; then
  "$ROOT/.venv/bin/psychtool-server" &
  SERVER_PID=$!
elif [ -x "$ROOT/.venv/bin/python" ]; then
  "$ROOT/.venv/bin/python" -m psychtool.server &
  SERVER_PID=$!
else
  plain_fail
fi

i=0
while [ "$i" -lt 60 ]; do
  if health_ok; then
    open_browser
    wait "$SERVER_PID"
    exit $?
  fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    wait "$SERVER_PID" >/dev/null 2>&1 || true
    plain_fail
  fi
  i=$((i + 1))
  sleep 1
done

echo "The writing workspace did not become ready in time. Ask the person who installed it to check the installation, then try again." >&2
kill "$SERVER_PID" 2>/dev/null || true
wait "$SERVER_PID" 2>/dev/null || true
exit 1
