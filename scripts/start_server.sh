#!/usr/bin/env bash
# PrintFilamentTracker - Production Web Server (Waitress)
# Usage:
#   ./scripts/start_server.sh
#   WEB_PORT=8080 ./scripts/start_server.sh
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
WEB_PORT="${WEB_PORT:-5000}"
echo "[INFO] Starting PrintFilamentTracker Web Server..."
echo "[INFO] URL: http://127.0.0.1:${WEB_PORT}"
echo "[INFO] Press Ctrl+C to stop."
exec .venv/bin/waitress-serve --host 127.0.0.1 --port "${WEB_PORT}" --call web.app:create_app
