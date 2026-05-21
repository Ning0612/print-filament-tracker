from datetime import datetime, timedelta

from flask import current_app, flash, redirect, render_template, request, url_for

from web.i18n import t
from ._auth import _mask_token
from ._backup import _backup_auto_lock, _backup_auto_state, _backup_event, _backup_status_context
from ._helpers import _save_app_config
from ._sync import _auto_sync_lock, _auto_sync_state, _scheduler_event, get_sync_state
from . import bp


def _reload_app_config(app) -> None:
    """Re-read app_config from DB and refresh app.config + scheduler states after a restore."""
    from src.db import get_app_config, get_connection
    from web.app import _make_tz_filters
    db_path = app.config["DB_PATH"]
    try:
        with get_connection(db_path) as conn:
            token = get_app_config(conn, "bambu_access_token") or ""
            region = get_app_config(conn, "bambu_region") or "global"
            sync_interval = get_app_config(conn, "auto_sync_interval") or "0"
            backup_interval = get_app_config(conn, "backup_interval_minutes") or "0"
            backup_keep = get_app_config(conn, "backup_keep_count") or "7"
            tz_offset = get_app_config(conn, "display_tz_offset_minutes") or "0"

        app.config["BAMBU_TOKEN"] = token
        app.config["BAMBU_REGION"] = region
        try:
            new_sync = int(sync_interval)
        except (ValueError, TypeError):
            new_sync = 0
        app.config["AUTO_SYNC_INTERVAL_MINUTES"] = new_sync

        try:
            new_backup = int(backup_interval)
        except (ValueError, TypeError):
            new_backup = 0
        app.config["BACKUP_INTERVAL_MINUTES"] = new_backup

        try:
            app.config["BACKUP_KEEP_COUNT"] = max(1, min(30, int(backup_keep)))
        except (ValueError, TypeError):
            app.config["BACKUP_KEEP_COUNT"] = 7

        try:
            new_tz = max(-720, min(840, int(tz_offset)))
        except (ValueError, TypeError):
            new_tz = 480
        app.config["DISPLAY_TZ_OFFSET_MINUTES"] = new_tz
        tz_fmt, tz_d = _make_tz_filters(new_tz)
        app.jinja_env.filters["tz_format"] = tz_fmt
        app.jinja_env.filters["tz_date"] = tz_d

        # Sync in-memory scheduler states so the new intervals take effect immediately.
        now = datetime.now()
        with _auto_sync_lock:
            _auto_sync_state["interval_minutes"] = new_sync
            _auto_sync_state["next_sync_at"] = (
                now + timedelta(minutes=new_sync) if new_sync > 0 else None
            )
        _scheduler_event.set()

        with _backup_auto_lock:
            _backup_auto_state["interval_minutes"] = new_backup
            _backup_auto_state["next_backup_at"] = (
                now + timedelta(minutes=new_backup) if new_backup > 0 else None
            )
        _backup_event.set()

    except Exception as exc:
        app.logger.warning("還原後重新載入設定失敗：%s", exc)


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
    display_tz_offset = int(current_app.config.get("DISPLAY_TZ_OFFSET_MINUTES", 0))
    return render_template(
        "settings/index.html",
        token_masked=_mask_token(token),
        has_token=bool(token),
        region=region,
        sync_state=get_sync_state(),
        auto_sync_interval=auto_sync_interval,
        auto_sync_state=auto_sync_snap,
        backup_interval=backup_interval,
        backup_keep_count=backup_keep_count,
        display_tz_offset=display_tz_offset,
        **backup_ctx,
    )


@bp.route("/timezone", methods=["POST"])
def set_timezone():
    from web.app import _make_tz_filters
    try:
        offset = int(request.form.get("tz_offset_minutes", "0"))
        if not (-720 <= offset <= 840):
            offset = 480
    except (ValueError, TypeError):
        offset = 480

    try:
        _save_app_config("display_tz_offset_minutes", str(offset))
    except Exception as exc:
        current_app.logger.warning("無法儲存 display_tz_offset_minutes 到 DB：%s", exc)

    current_app.config["DISPLAY_TZ_OFFSET_MINUTES"] = offset
    tz_fmt, tz_d = _make_tz_filters(offset)
    current_app.jinja_env.filters["tz_format"] = tz_fmt
    current_app.jinja_env.filters["tz_date"] = tz_d

    flash(t("flash.settings.timezone_saved"), "success")
    return redirect(url_for("settings.index"))
