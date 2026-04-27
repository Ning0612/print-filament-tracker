import os
import threading
from datetime import datetime, timedelta

import requests
from flask import Blueprint, current_app, flash, make_response, render_template, request, session, url_for

from web.i18n import t

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

_auto_sync_lock = threading.Lock()
_auto_sync_state: dict = {
    "interval_minutes": 0,
    "last_sync_at": None,
    "next_sync_at": None,
}
_scheduler_event = threading.Event()
_scheduler_thread: threading.Thread | None = None

_VALID_INTERVALS = frozenset({0, 60, 120, 360, 720, 1440})

_backup_auto_lock = threading.Lock()
_backup_auto_state: dict = {
    "interval_minutes": 0,
    "next_backup_at": None,
}
_backup_event = threading.Event()
_backup_scheduler_thread: threading.Thread | None = None

_VALID_BACKUP_INTERVALS = frozenset({0, 60, 360, 720, 1440})


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


def _save_app_config(key: str, value: str) -> None:
    from src.db import get_connection, set_app_config
    with get_connection(current_app.config["DB_PATH"]) as conn:
        set_app_config(conn, key, value)


def _apply_token(token: str, region: str) -> None:
    from src.db import get_connection, set_app_config
    try:
        with get_connection(current_app.config["DB_PATH"]) as conn:
            set_app_config(conn, "bambu_access_token", token)
            set_app_config(conn, "bambu_region", region)
    except Exception as exc:
        current_app.logger.warning("無法儲存 token 到 DB：%s", exc)
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
                "message_key": "flash.sync.done",
                "message_params": {
                    "inserted": stats["inserted"],
                    "skipped": stats["skipped"],
                    "filaments": stats["filaments"],
                },
                "stats": stats,
            }
    except Exception as exc:
        with _sync_lock:
            _sync_state = {"status": "error", "message": str(exc), "stats": None}


def _auto_sync_scheduler(app) -> None:
    """Background daemon thread: wakes every 60 s, syncs when interval elapsed."""
    global _auto_sync_state, _sync_state

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
                _sync_state = {"status": "running", "message_key": "flash.sync.auto_running", "stats": None}
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


def _run_backup_thread(db_path, backup_dir, keep_count) -> None:
    """Run backup in a background thread; errors are captured in _backup_state."""
    from src import backup as backup_mod
    try:
        backup_mod.run_backup(db_path, backup_dir, keep_count)
    except Exception:
        pass


def _backup_scheduler(app) -> None:
    """Background daemon thread: runs auto backup when interval elapsed."""
    global _backup_auto_state
    from pathlib import Path

    with app.app_context():
        interval = int(app.config.get("BACKUP_INTERVAL_MINUTES", 0))
    with _backup_auto_lock:
        _backup_auto_state["interval_minutes"] = interval
        if interval > 0 and _backup_auto_state["next_backup_at"] is None:
            _backup_auto_state["next_backup_at"] = datetime.now() + timedelta(minutes=interval)

    while True:
        _backup_event.wait(timeout=60)
        _backup_event.clear()

        with app.app_context():
            interval = int(app.config.get("BACKUP_INTERVAL_MINUTES", 0))

        with _backup_auto_lock:
            _backup_auto_state["interval_minutes"] = interval
            if interval <= 0:
                _backup_auto_state["next_backup_at"] = None
            elif _backup_auto_state["next_backup_at"] is None:
                _backup_auto_state["next_backup_at"] = datetime.now() + timedelta(minutes=interval)
            next_backup = _backup_auto_state["next_backup_at"]

        if next_backup is None or datetime.now() < next_backup:
            continue

        from src import backup as backup_mod
        if backup_mod.get_backup_state()["status"] == "running":
            continue

        with app.app_context():
            db_path = app.config["DB_PATH"]
            keep_count = int(app.config.get("BACKUP_KEEP_COUNT", 7))

        backup_dir = db_path.parent / "backups"
        threading.Thread(
            target=_run_backup_thread,
            args=(db_path, backup_dir, keep_count),
            daemon=True,
        ).start()

        # Advance the schedule regardless of backup outcome so timing stays consistent.
        # Actual last-backup time is tracked in src/backup._backup_state.
        now = datetime.now()
        with _backup_auto_lock:
            _backup_auto_state["next_backup_at"] = now + timedelta(minutes=interval)


def start_backup_scheduler(app) -> None:
    global _backup_scheduler_thread
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return
    if _backup_scheduler_thread is not None and _backup_scheduler_thread.is_alive():
        return
    _backup_scheduler_thread = threading.Thread(
        target=_backup_scheduler,
        args=(app,),
        daemon=True,
        name="backup-scheduler",
    )
    _backup_scheduler_thread.start()


def _backup_status_context() -> dict:
    """Assemble template context vars for _backup_status.html."""
    from src import backup as backup_mod
    db_path = current_app.config["DB_PATH"]
    backup_dir = db_path.parent / "backups"
    with _backup_auto_lock:
        auto_state = dict(_backup_auto_state)
    return {
        "backup_state": backup_mod.get_backup_state(),
        "backup_list": backup_mod.list_backups(backup_dir),
        "backup_auto_state": auto_state,
    }


@bp.route("/")
def index():
    token = current_app.config.get("BAMBU_TOKEN", "")
    region = current_app.config.get("BAMBU_REGION", "global")
    with _auto_sync_lock:
        auto_sync_interval = _auto_sync_state["interval_minutes"]
        auto_sync_snap = dict(_auto_sync_state)
    backup_ctx = _backup_status_context()
    backup_interval = backup_ctx["backup_auto_state"]["interval_minutes"]
    backup_keep_count = int(current_app.config.get("BACKUP_KEEP_COUNT", 7))
    return render_template(
        "settings/index.html",
        token_masked=_mask_token(token),
        has_token=bool(token),
        region=region,
        sync_state=_sync_state,
        auto_sync_interval=auto_sync_interval,
        auto_sync_state=auto_sync_snap,
        backup_interval=backup_interval,
        backup_keep_count=backup_keep_count,
        **backup_ctx,
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
        return render_template("settings/_login_error.html", error=t("flash.settings.email_password_required"))

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
        flash(t("flash.settings.login_success"), "success")
        resp = make_response("")
        resp.headers["HX-Redirect"] = url_for("settings.index")
        return resp

    if login_type == "verifyCode":
        _, send_err = _api_post(base_url, _SEND_CODE_PATH, {
            "email": email, "type": "codeLogin",
        })
        if send_err:
            return render_template("settings/_login_error.html",
                                   error=t("flash.settings.send_code_failed", err=send_err))
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
                           error=t("flash.settings.unexpected_response", data=data))


@bp.route("/login/step2", methods=["POST"])
def login_step2():
    info = session.get("bambu_login")
    if not info:
        return render_template("settings/_login_error.html",
                               error=t("flash.settings.session_expired"))

    code = request.form.get("code", "").strip()
    if not code:
        return render_template("settings/_login_error.html", error=t("flash.settings.code_empty"))

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
                               error=t("flash.settings.login_failed", data=data))

    session.pop("bambu_login", None)
    _apply_token(token, region)
    flash(t("flash.settings.login_success"), "success")
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
                           "message_key": "flash.sync.no_token",
                           "stats": None}
            return render_template("settings/_sync_status.html", sync_state=_sync_state)

        _sync_state = {"status": "running",
                       "message_key": "flash.sync.running",
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

    try:
        _save_app_config("auto_sync_interval", str(interval))
    except Exception as exc:
        current_app.logger.warning("無法儲存 auto_sync_interval 到 DB：%s", exc)

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


@bp.route("/backup", methods=["POST"])
def start_backup():
    from src import backup as backup_mod

    db_path = current_app.config["DB_PATH"]
    backup_dir = db_path.parent / "backups"
    keep_count = int(current_app.config.get("BACKUP_KEEP_COUNT", 7))

    state = backup_mod.get_backup_state()
    if state["status"] == "running":
        return render_template("settings/_backup_status.html", **_backup_status_context())

    threading.Thread(
        target=_run_backup_thread,
        args=(db_path, backup_dir, keep_count),
        daemon=True,
    ).start()

    # Return optimistic running state immediately for responsive UI
    return render_template(
        "settings/_backup_status.html",
        backup_state={
            "status": "running",
            "last_backup_at": state.get("last_backup_at"),
            "last_backup_file": state.get("last_backup_file"),
            "error": None,
        },
        backup_list=backup_mod.list_backups(backup_dir),
        backup_auto_state=_backup_status_context()["backup_auto_state"],
    )


@bp.route("/backup/status")
def backup_status():
    return render_template("settings/_backup_status.html", **_backup_status_context())


@bp.route("/backup/config", methods=["POST"])
def set_backup_config():
    global _backup_auto_state

    try:
        interval = int(request.form.get("interval_minutes", "0"))
    except (ValueError, TypeError):
        interval = 0
    if interval not in _VALID_BACKUP_INTERVALS:
        interval = 0

    try:
        keep_count = int(request.form.get("keep_count", "7"))
        keep_count = max(1, min(30, keep_count))
    except (ValueError, TypeError):
        keep_count = 7

    current_app.config["BACKUP_INTERVAL_MINUTES"] = interval
    current_app.config["BACKUP_KEEP_COUNT"] = keep_count

    try:
        _save_app_config("backup_interval_minutes", str(interval))
        _save_app_config("backup_keep_count", str(keep_count))
    except Exception as exc:
        current_app.logger.warning("無法儲存備份設定到 DB：%s", exc)

    now = datetime.now()
    with _backup_auto_lock:
        _backup_auto_state["interval_minutes"] = interval
        if interval > 0:
            _backup_auto_state["next_backup_at"] = now + timedelta(minutes=interval)
        else:
            _backup_auto_state["next_backup_at"] = None

    _backup_event.set()

    return render_template("settings/_backup_status.html", **_backup_status_context())
