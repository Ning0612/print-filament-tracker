#!/usr/bin/env bash
#
# PrintFilamentTracker deployment setup script for macOS.
#
# Usage:
#   bash scripts/setup_deployment.sh
#   bash scripts/setup_deployment.sh --web-port 8080
#   bash scripts/setup_deployment.sh --skip-secret-key
#   bash scripts/setup_deployment.sh --skip-launchd
#
set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
WEB_PORT=5000
SKIP_SECRET_KEY=false
SKIP_LAUNCHD=false

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --web-port)
            WEB_PORT="$2"
            if ! [[ "$WEB_PORT" =~ ^[0-9]+$ ]] || (( WEB_PORT < 1024 || WEB_PORT > 65535 )); then
                echo "[FAIL] --web-port must be between 1024 and 65535" >&2; exit 1
            fi
            shift 2 ;;
        --skip-secret-key) SKIP_SECRET_KEY=true; shift ;;
        --skip-launchd)    SKIP_LAUNCHD=true;    shift ;;
        *)
            echo "[FAIL] Unknown option: $1" >&2
            echo "Usage: $0 [--web-port PORT] [--skip-secret-key] [--skip-launchd]" >&2
            exit 1 ;;
    esac
done

# ── Constants ─────────────────────────────────────────────────────────────────
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
VENV_PYTHON="$REPO_ROOT/.venv/bin/python"
VENV_WAITRESS="$REPO_ROOT/.venv/bin/waitress-serve"
PLIST_LABEL="com.printfilamenttracker.web"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"
LAUNCHD_TARGET="gui/$(id -u)"
SEPARATOR="============================================================"

# ── Helpers ───────────────────────────────────────────────────────────────────
step() { printf '\n\033[36m[STEP] %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m[OK]  \033[0m %s\n' "$*"; }
warn() { printf '  \033[33m[WARN]\033[0m %s\n' "$*"; }
fail() { printf '  \033[31m[FAIL]\033[0m %s\n' "$*" >&2; exit 1; }

# ── STEP 0: Pre-flight ────────────────────────────────────────────────────────
step "Pre-flight checks"

[[ "$OSTYPE" == darwin* ]] || fail "This script is for macOS only. Use setup_deployment.ps1 on Windows."

if [[ "$REPO_ROOT" =~ [[:space:]] ]]; then
    fail "Repository path contains spaces, which is not supported: $REPO_ROOT"
fi

[[ -f "$VENV_PYTHON" ]] || fail "venv Python not found: $VENV_PYTHON
  Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
[[ -f "$ENV_FILE" ]] || fail ".env not found: $ENV_FILE
  Copy .env.example to .env first."

ok "Repo, venv and .env verified"

# ── STEP 1: SECRET_KEY ────────────────────────────────────────────────────────
if [[ "$SKIP_SECRET_KEY" == false ]]; then
    step "SECRET_KEY check"

    # Use Python for reliable .env parsing (avoids BSD grep/sed compatibility issues)
    KEY_STATUS=$("$VENV_PYTHON" -c "
import re, sys
with open(sys.argv[1]) as f:
    content = f.read()
print('exists' if re.search(r'^SECRET_KEY\s*=\s*.+', content, re.MULTILINE) else 'missing')
" "$ENV_FILE")

    if [[ "$KEY_STATUS" == "exists" ]]; then
        ok "SECRET_KEY already set, skipping generation"
    else
        echo "  Generating new SECRET_KEY..."
        NEW_KEY=$("$VENV_PYTHON" -c "import secrets; print(secrets.token_hex(32))")
        [[ -n "$NEW_KEY" ]] || fail "Failed to generate SECRET_KEY"

        "$VENV_PYTHON" -c "
import re, sys
path, key = sys.argv[1], sys.argv[2]
with open(path) as f:
    content = f.read()
content = re.sub(r'^SECRET_KEY\s*=.*\n?', '', content, flags=re.MULTILINE)
if not content.endswith('\n'):
    content += '\n'
content += 'SECRET_KEY=' + key + '\n'
with open(path, 'w') as f:
    f.write(content)
" "$ENV_FILE" "$NEW_KEY"

        chmod 600 "$ENV_FILE"
        ok "SECRET_KEY written to .env (64-char hex)"
        warn "Keep .env backed up — losing SECRET_KEY invalidates all sessions."
    fi
fi

# ── STEP 2: Waitress ──────────────────────────────────────────────────────────
step "Waitress WSGI server"

if [[ -f "$VENV_WAITRESS" ]]; then
    ok "Waitress already installed"
else
    echo "  Installing..."
    "$VENV_PYTHON" -m pip install waitress --quiet
    [[ -f "$VENV_WAITRESS" ]] || fail "waitress-serve not found after installation"
    ok "Waitress installed"
fi

# ── STEP 3: Launch Agent ──────────────────────────────────────────────────────
if [[ "$SKIP_LAUNCHD" == true ]]; then
    warn "Skipping Launch Agent setup (--skip-launchd)"
else
    step "macOS Launch Agent - Web Server auto-start"

    # Log directory must exist before launchd tries to open stdio log files
    mkdir -p "$REPO_ROOT/data/logs"
    mkdir -p "$HOME/Library/LaunchAgents"

    # Unload existing agent if running
    if launchctl print "$LAUNCHD_TARGET/$PLIST_LABEL" &>/dev/null; then
        launchctl bootout "$LAUNCHD_TARGET/$PLIST_LABEL" 2>/dev/null || true
        sleep 1
        echo "  Removed existing Launch Agent"
    fi

    # Kill any lingering waitress processes for this app
    pkill -f "waitress-serve.*web\\.app:create_app" 2>/dev/null || true

    # Write plist (variables expanded: PLIST_LABEL, VENV_WAITRESS, WEB_PORT, REPO_ROOT)
    cat > "$PLIST_PATH" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${VENV_WAITRESS}</string>
        <string>--host</string>
        <string>127.0.0.1</string>
        <string>--port</string>
        <string>${WEB_PORT}</string>
        <string>--call</string>
        <string>web.app:create_app</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${REPO_ROOT}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string>${REPO_ROOT}</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>StandardOutPath</key>
    <string>${REPO_ROOT}/data/logs/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>${REPO_ROOT}/data/logs/launchd-error.log</string>
    <key>ThrottleInterval</key>
    <integer>60</integer>
</dict>
</plist>
PLIST_EOF

    plutil -lint "$PLIST_PATH" || fail "Plist validation failed — check $PLIST_PATH"
    ok "Launch Agent plist written and validated: $PLIST_PATH"

    launchctl bootstrap "$LAUNCHD_TARGET" "$PLIST_PATH"
    ok "Launch Agent '$PLIST_LABEL' bootstrapped — server starting in background"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
printf '\n%s\n' "$SEPARATOR"
printf '  PrintFilamentTracker deployment setup complete!\n'
printf '%s\n\n' "$SEPARATOR"
printf '  Completed:\n'
printf '    OK  SECRET_KEY check\n'
printf '    OK  Waitress check\n'
if [[ "$SKIP_LAUNCHD" == false ]]; then
    printf '    OK  Launch Agent: %s (at login, port %s)\n' "$PLIST_LABEL" "$WEB_PORT"
    printf '    OK  Web server triggered (background, no terminal window)\n'
fi
printf '\n  Auto-sync and DB backup are managed by the app itself.\n'
printf '  Configure intervals in the Web UI Settings page.\n'
printf '\n  To stop the server:\n'
printf '    launchctl bootout %s/%s\n' "$LAUNCHD_TARGET" "$PLIST_LABEL"
printf '\n  Web UI: http://127.0.0.1:%s\n\n' "$WEB_PORT"
