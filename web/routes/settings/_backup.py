import os
import re
import threading
from datetime import datetime, timedelta

from flask import current_app, flash, redirect, render_template, request, url_for

from web.i18n import t
from ._helpers import _save_app_config
from . import bp

_backup_auto_lock = threading.Lock()
_backup_auto_state: dict = {
    "interval_minutes": 0,
    "next_backup_at": None,
}
_backup_event = threading.Event()
_backup_scheduler_thread: threading.Thread | None = None

_VALID_BACKUP_INTERVALS = frozenset({0, 60, 360, 720, 1440})
_BACKUP_FILENAME_RE = re.compile(r"^bambu_\d{8}_\d{6}\.db$")


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


@bp.route("/restore", methods=["POST"])
def restore_backup():
    from src import backup as backup_mod

    filename = request.form.get("filename", "").strip()

    # Allowlist: only accept filenames produced by run_backup() (bambu_YYYYMMDD_HHMMSS.db).
    # This is stricter than a blacklist and avoids Windows device / ADS edge cases.
    if not filename or not _BACKUP_FILENAME_RE.match(filename):
        flash(t("flash.backup.restore_invalid"), "error")
        return redirect(url_for("settings.index"))

    db_path = current_app.config["DB_PATH"]
    backup_dir = db_path.parent / "backups"
    backup_path = backup_dir / filename
    keep_count = int(current_app.config.get("BACKUP_KEEP_COUNT", 7))

    try:
        backup_mod.run_backup(db_path, backup_dir, keep_count)
    except Exception as exc:
        current_app.logger.error("還原前備份失敗：%s", exc)
        flash(t("flash.backup.pre_restore_backup_error", msg=str(exc)), "error")
        return redirect(url_for("settings.index"))

    try:
        backup_mod.restore_from_backup(db_path, backup_path)
    except Exception as exc:
        current_app.logger.error("還原失敗：%s", exc)
        flash(t("flash.backup.restore_error", msg=str(exc)), "error")
        return redirect(url_for("settings.index"))

    # Refresh in-memory app.config so token / intervals reflect the restored DB.
    from web.routes.settings._config import _reload_app_config
    _reload_app_config(current_app._get_current_object())

    flash(t("flash.backup.restore_done", file=filename), "success")
    return redirect(url_for("settings.index"))
