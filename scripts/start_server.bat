@echo off
:: PrintFilamentTracker - Production Web Server (Waitress)
:: Usage: Double-click or call from Task Scheduler
:: Requires: pip install waitress
cd /d %~dp0..
echo [INFO] Starting PrintFilamentTracker Web Server...
echo [INFO] URL: http://127.0.0.1:5000
echo [INFO] Press Ctrl+C to stop.
.venv\Scripts\waitress-serve --host 127.0.0.1 --port 5000 --call web.app:create_app
