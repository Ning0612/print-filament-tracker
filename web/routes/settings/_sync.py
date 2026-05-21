import os
import threading
from datetime import datetime, timedelta

from flask import current_app, render_template, request

from web.i18n import t
from ._auth import _CHINA_BASE, _GLOBAL_BASE
from ._helpers import _save_app_config
from . import bp

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
                    "updated": stats["updated"],
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


def get_sync_state() -> dict:
    """Return the current sync state dict (always the latest reference)."""
    return _sync_state


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
