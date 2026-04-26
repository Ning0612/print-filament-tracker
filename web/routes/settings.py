import os
import threading
from datetime import datetime, timedelta
from pathlib import Path

import requests
from flask import Blueprint, current_app, flash, make_response, render_template, request, session, url_for

bp = Blueprint("settings", __name__, url_prefix="/settings")

_GLOBAL_BASE = "https://api.bambulab.com"
_CHINA_BASE = "https://api.bambulab.cn"
_LOGIN_PATH = "/v1/user-service/user/login"
_SEND_CODE_PATH = "/v1/user-service/user/sendemail/code"
_TFA_PATH = "/api/sign-in/tfa"
_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "bambu_network_agent/01.09.05.01",
}
_TIMEOUT = 20

_sync_lock = threading.Lock()
_sync_state: dict = {"status": "idle", "message": "", "stats": None}

_env_lock = threading.Lock()  # serialises all .env reads + writes

_auto_sync_lock = threading.Lock()
_auto_sync_state: dict = {
    "interval_minutes": 0,
    "last_sync_at": None,
    "next_sync_at": None,
}
_scheduler_event = threading.Event()
_scheduler_thread: threading.Thread | None = None

_VALID_INTERVALS = frozenset({0, 60, 120, 360, 720, 1440})


def _api_post(base_url: str, path: str, payload: dict) -> tuple[dict | None, str | None]:
    try:
        resp = requests.post(base_url + path, json=payload, headers=_HEADERS, timeout=_TIMEOUT)
    except requests.Timeout:
        return None, f"連線逾時（{_TIMEOUT} 秒），請確認網路連線。"
    except requests.RequestException as exc:
        return None, f"網路錯誤：{exc}"
    if not resp.ok:
        return None, f"伺服器回傳 HTTP {resp.status_code}：{resp.text[:200]}"
    try:
        return resp.json(), None
    except ValueError:
        return None, "伺服器回傳非 JSON 格式"


def _write_env(token: str, region: str, env_path: Path) -> None:
    with _env_lock:
        lines = []
        has_token = has_region = False
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                stripped = line.lstrip()
                if stripped.startswith("BAMBU_ACCESS_TOKEN="):
                    lines.append(f"BAMBU_ACCESS_TOKEN={token}")
                    has_token = True
                elif stripped.startswith("BAMBU_REGION="):
                    lines.append(f"BAMBU_REGION={region}")
                    has_region = True
                else:
                    lines.append(line)
        if not has_token:
            lines.append(f"BAMBU_ACCESS_TOKEN={token}")
        if not has_region:
            lines.append(f"BAMBU_REGION={region}")

        # Atomic write: write to temp then rename
        tmp_path = env_path.with_suffix(".env.tmp")
        tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp_path.replace(env_path)


def _write_env_key(key: str, value: str, env_path: Path) -> None:
    """Update or append a single key-value pair in the .env file atomically."""
    with _env_lock:
        lines = []
        found = False
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.lstrip().startswith(f"{key}="):
                    lines.append(f"{key}={value}")
                    found = True
                else:
                    lines.append(line)
        if not found:
            lines.append(f"{key}={value}")
        tmp_path = env_path.with_suffix(".env.tmp")
        tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp_path.replace(env_path)


def _apply_token(token: str, region: str) -> None:
    env_path = current_app.config.get("ENV_PATH")
    if env_path:
        try:
            _write_env(token, region, Path(env_path))
        except OSError as exc:
            current_app.logger.warning("無法寫入 .env：%s", exc)
    # Only update token/region; preserve any custom BAMBU_API_BASE
    current_app.config["BAMBU_TOKEN"] = token
    current_app.config["BAMBU_REGION"] = region


def _mask_token(token: str) -> str:
    if not token:
        return "(未設定)"
    if len(token) <= 8:
        return "***"
    return token[:4] + "..." + token[-4:]


def _run_sync(app) -> None:
    """Execute cloud sync in any thread context. Updates _sync_state on completion."""
    global _sync_state
    try:
        from src.config import AppConfig
        from src.ingestion import run_ingestion_from_cloud

        with app.app_context():
            token = app.config.get("BAMBU_TOKEN", "")
            region = app.config.get("BAMBU_REGION", "global")
            api_base = (
                app.config.get("BAMBU_API_BASE")
                or (_GLOBAL_BASE if region == "global" else _CHINA_BASE)
            )
            db_path = app.config["DB_PATH"]

        config = AppConfig(
            access_token=token,
            region=region,
            api_base=api_base,
            output_dir=db_path.parent,
            request_timeout=30,
        )
        stats = run_ingestion_from_cloud(config, db_path)
        with _sync_lock:
            _sync_state = {
                "status": "done",
                "message": (
                    f"同步完成！新增 {stats['inserted']} 筆，"
                    f"略過 {stats['skipped']} 筆，"
                    f"耗材記錄 {stats['filaments']} 筆。"
                ),
                "stats": stats,
            }
    except Exception as exc:
        with _sync_lock:
            _sync_state = {"status": "error", "message": str(exc), "stats": None}


def _auto_sync_scheduler(app) -> None:
    """Background daemon thread: wakes every 60 s, syncs when interval elapsed."""
    global _auto_sync_state

    with app.app_context():
        interval = int(app.config.get("AUTO_SYNC_INTERVAL_MINUTES", 0))
    with _auto_sync_lock:
        _auto_sync_state["interval_minutes"] = interval
        if interval > 0 and _auto_sync_state["next_sync_at"] is None:
            _auto_sync_state["next_sync_at"] = datetime.now() + timedelta(minutes=interval)

    while True:
        _scheduler_event.wait(timeout=60)
        _scheduler_event.clear()

        with app.app_context():
            interval = int(app.config.get("AUTO_SYNC_INTERVAL_MINUTES", 0))

        with _auto_sync_lock:
            _auto_sync_state["interval_minutes"] = interval
            if interval <= 0:
                _auto_sync_state["next_sync_at"] = None
            elif _auto_sync_state["next_sync_at"] is None:
                _auto_sync_state["next_sync_at"] = datetime.now() + timedelta(minutes=interval)
            next_sync = _auto_sync_state["next_sync_at"]

        if next_sync is None or datetime.now() < next_sync:
            continue

        with app.app_context():
            token = app.config.get("BAMBU_TOKEN", "")
        if not token:
            continue

        should_run = False
        with _sync_lock:
            if _sync_state.get("status") != "running":
                _sync_state = {"status": "running", "message": "自動同步中...", "stats": None}
                should_run = True

        if not should_run:
            continue

        _run_sync(app)

        now = datetime.now()
        with _auto_sync_lock:
            _auto_sync_state["last_sync_at"] = now
            _auto_sync_state["next_sync_at"] = now + timedelta(minutes=interval)


def start_auto_sync_scheduler(app) -> None:
    global _scheduler_thread
    # In debug/reloader mode, only start in the child (actual server) process
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        return
    _scheduler_thread = threading.Thread(
        target=_auto_sync_scheduler,
        args=(app,),
        daemon=True,
        name="auto-sync-scheduler",
    )
    _scheduler_thread.start()


@bp.route("/")
def index():
    token = current_app.config.get("BAMBU_TOKEN", "")
    region = current_app.config.get("BAMBU_REGION", "global")
    with _auto_sync_lock:
        auto_sync_interval = _auto_sync_state["interval_minutes"]
        auto_sync_snap = dict(_auto_sync_state)
    return render_template(
        "settings/index.html",
        token_masked=_mask_token(token),
        has_token=bool(token),
        region=region,
        sync_state=_sync_state,
        auto_sync_interval=auto_sync_interval,
        auto_sync_state=auto_sync_snap,
    )


@bp.route("/login/form")
def login_form():
    return render_template("settings/_login_form.html")


@bp.route("/login/step1", methods=["POST"])
def login_step1():
    email = request.form.get("email", "").strip()
    # Do NOT strip password — leading/trailing spaces may be intentional
    password = request.form.get("password", "")
    region = request.form.get("region", "global")
    if region not in ("global", "china"):
        region = "global"

    if not email or not password:
        return render_template("settings/_login_error.html", error="Email 和密碼不得為空。")

    base_url = _GLOBAL_BASE if region == "global" else _CHINA_BASE
    data, err = _api_post(base_url, _LOGIN_PATH, {
        "account": email, "password": password, "apiError": "",
    })
    if err:
        return render_template("settings/_login_error.html", error=err)

    login_type = data.get("loginType", "")
    token = data.get("accessToken")

    if token and not login_type:
        _apply_token(token, region)
        flash("Bambu Cloud 登入成功，Token 已儲存至 .env。", "success")
        resp = make_response("")
        resp.headers["HX-Redirect"] = url_for("settings.index")
        return resp

    if login_type == "verifyCode":
        _, send_err = _api_post(base_url, _SEND_CODE_PATH, {
            "email": email, "type": "codeLogin",
        })
        if send_err:
            return render_template("settings/_login_error.html",
                                   error=f"驗證碼發送失敗：{send_err}")
        session["bambu_login"] = {
            "email": email, "region": region,
            "base_url": base_url, "type": "verifyCode",
        }
        return render_template("settings/_login_step2.html",
                               login_type="verifyCode", email=email)

    if login_type == "tfa":
        session["bambu_login"] = {
            "email": email, "region": region,
            "base_url": base_url, "type": "tfa",
            "tfa_key": data.get("tfaKey", ""),
        }
        return render_template("settings/_login_step2.html",
                               login_type="tfa", email=email)

    return render_template("settings/_login_error.html",
                           error=f"未預期的登入回應：{data}")


@bp.route("/login/step2", methods=["POST"])
def login_step2():
    info = session.get("bambu_login")
    if not info:
        return render_template("settings/_login_error.html",
                               error="登入工作階段已過期，請重新開始。")

    code = request.form.get("code", "").strip()
    if not code:
        return render_template("settings/_login_error.html", error="驗證碼不得為空。")

    base_url = info["base_url"]
    region = info["region"]

    if info["type"] == "verifyCode":
        data, err = _api_post(base_url, _LOGIN_PATH, {
            "account": info["email"], "code": code,
        })
    else:
        data, err = _api_post(base_url, _TFA_PATH, {
            "tfaKey": info.get("tfa_key", ""), "tfaCode": code,
        })

    if err:
        return render_template("settings/_login_error.html", error=err)

    token = data.get("accessToken") if data else None
    if not token:
        return render_template("settings/_login_error.html",
                               error=f"登入失敗，伺服器回應：{data}")

    session.pop("bambu_login", None)
    _apply_token(token, region)
    flash("Bambu Cloud 登入成功，Token 已儲存至 .env。", "success")
    resp = make_response("")
    resp.headers["HX-Redirect"] = url_for("settings.index")
    return resp


@bp.route("/sync", methods=["POST"])
def start_sync():
    global _sync_state

    with _sync_lock:
        if _sync_state.get("status") == "running":
            return render_template("settings/_sync_status.html", sync_state=_sync_state)

        token = current_app.config.get("BAMBU_TOKEN", "")
        if not token:
            _sync_state = {"status": "error",
                           "message": "尚未設定 Token，請先登入 Bambu 帳號。",
                           "stats": None}
            return render_template("settings/_sync_status.html", sync_state=_sync_state)

        _sync_state = {"status": "running",
                       "message": "正在從 Bambu Cloud 下載列印歷史...",
                       "stats": None}

    app = current_app._get_current_object()
    threading.Thread(target=_run_sync, args=(app,), daemon=True).start()
    return render_template("settings/_sync_status.html", sync_state=_sync_state)


@bp.route("/sync/status")
def sync_status():
    return render_template("settings/_sync_status.html", sync_state=_sync_state)


@bp.route("/auto-sync/status")
def auto_sync_status():
    with _auto_sync_lock:
        snap = dict(_auto_sync_state)
    return render_template("settings/_auto_sync_status.html", auto_sync_state=snap)


@bp.route("/auto-sync", methods=["POST"])
def set_auto_sync():
    global _auto_sync_state

    try:
        interval = int(request.form.get("interval_minutes", "0"))
    except (ValueError, TypeError):
        interval = 0
    if interval not in _VALID_INTERVALS:
        interval = 0

    current_app.config["AUTO_SYNC_INTERVAL_MINUTES"] = interval

    env_path = current_app.config.get("ENV_PATH")
    if env_path:
        try:
            _write_env_key("AUTO_SYNC_INTERVAL", str(interval), Path(env_path))
        except OSError as exc:
            current_app.logger.warning("無法寫入 .env AUTO_SYNC_INTERVAL：%s", exc)

    now = datetime.now()
    with _auto_sync_lock:
        _auto_sync_state["interval_minutes"] = interval
        if interval > 0:
            _auto_sync_state["next_sync_at"] = now + timedelta(minutes=interval)
        else:
            _auto_sync_state["next_sync_at"] = None
        snap = dict(_auto_sync_state)

    _scheduler_event.set()

    return render_template("settings/_auto_sync_status.html", auto_sync_state=snap)
