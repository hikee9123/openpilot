#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

HOST="127.0.0.1"
PORT="${1:-8765}"
URL="http://$HOST:$PORT/"

cd "$REPO_ROOT"

PYTHON_BIN="${PYTHON:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "$PYTHON_BIN was not found in PATH." >&2
  echo "Set PYTHON=/path/to/python or install python3." >&2
  exit 1
fi

echo "Starting OSM roads web UI at $URL"
echo "Repo: $REPO_ROOT"
echo "Press Ctrl+C to stop the server."
echo

if [[ -z "${OSM_ROADS_WEBUI_NO_BROWSER:-}" ]] && command -v xdg-open >/dev/null 2>&1; then
  (sleep 1; xdg-open "$URL" >/dev/null 2>&1 || true) &
fi

exec "$PYTHON_BIN" tools/scripts/osm_roads_webui.py --host "$HOST" --port "$PORT"
