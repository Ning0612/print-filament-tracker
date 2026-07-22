import logging
import os
import secrets
import sys as _sys
import threading
import time
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv, set_key as _dotenv_set_key
from flask import Flask, make_response, send_from_directory
from flask_wtf.csrf import CSRFProtect

from src.db import get_app_config, get_connection, get_db_path, init_db, set_app_config
from src.paths import ensure_base_dir, get_base_dir, resolve_output_dir

_GLOBAL_BASE = "https://api.bambulab.com"
_CHINA_BASE = "https://api.bambulab.cn"

_VALID_REGIONS = {"global", "china"}


def _make_tz_filters(tz_minutes: int):
    """Build tz_format and tz_date Jinja2 filters for the given UTC offset in minutes."""
    _delta = timedelta(minutes=tz_minutes)

    def tz_format(dt_str, fmt="%Y-%m-%d %H:%M"):
        if not dt_str:
            return "-"
        s = str(dt_str).strip()
        try:
            if s.endswith("Z"):
                dt = datetime.fromisoformat(s[:-1]) + _delta
            elif len(s) > 19 and s[19] in ("+", "-"):
                dt = datetime.fromisoformat(s[:19]) + _delta
            else:
                dt = datetime.fromisoformat(s[:19])
            return dt.strftime(fmt)
        except ValueError:
            return s[:16].replace("T", " ")

    def tz_date(dt_str):
        return tz_format(dt_str, "%Y-%m-%d")

    return tz_format, tz_date


def _to_float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fmt_int(v) -> str:
    """千分位整數；無效值回 '-'。"""
    f = _to_float(v)
    return "-" if f is None else f"{int(round(f)):,}"


def fmt_weight(v, unit: str = "g", digits: int = 1) -> str:
    """重量格式化：千分位＋固定小數＋單位，如 '3,200.0 g'。"""
    f = _to_float(v)
    return "-" if f is None else f"{f:,.{digits}f} {unit}"


def fmt_money(v, digits: int = 2) -> str:
    """金額格式化，貨幣符號位置由 i18n key cost.money_format 決定。"""
    f = _to_float(v)
    if f is None:
        return "-"
    from web.i18n import t
    return t("cost.money_format", amount=f"{f:,.{digits}f}")


def fmt_duration(seconds) -> str:
    """秒數轉 '3 h 12 m'（不足 1 小時只顯示分鐘）；無效值回 '-'。"""
    f = _to_float(seconds)
    if f is None:
        return "-"
    total = int(f)
    h, m = total // 3600, (total % 3600) // 60
    return f"{h} h {m} m" if h else f"{m} m"


def ledger_amount(text, kind: str = "neutral"):
    """把已格式化的數值字串包成帳目金額 span（.amount--debit / .amount--credit）。

    用法：{{ used_g | fmt_weight | ledger_amount('debit') }}
    """
    from markupsafe import Markup, escape
    cls = {
        "debit": "amount amount--debit",
        "credit": "amount amount--credit",
    }.get(kind, "amount")
    return Markup(f'<span class="{cls}">{escape(text)}</span>')


def _register_number_filters(app: Flask) -> None:
    app.jinja_env.filters["fmt_int"] = fmt_int
    app.jinja_env.filters["fmt_weight"] = fmt_weight
    app.jinja_env.filters["fmt_money"] = fmt_money
    app.jinja_env.filters["fmt_duration"] = fmt_duration
    app.jinja_env.filters["ledger_amount"] = ledger_amount


def _get_resource_dir() -> Path:
    """捆綁資源根目錄（templates / static / translations 的父目錄 web/）。
    凍結時：sys._MEIPASS/web/。開發時：web/ 目錄。
    """
    if getattr(_sys, "frozen", False):
        return Path(_sys._MEIPASS) / "web"  # type: ignore[attr-defined]
    return Path(__file__).parent


def create_app(db_path: Path | None = None) -> Flask:
    _res = _get_resource_dir()
    app = Flask(
        __name__,
        template_folder=str(_res / "templates"),
        static_folder=str(_res / "static"),
    )

    # 確保使用者資料根目錄存在（首次啟動自動建立）
    base_dir = ensure_base_dir()
    env_path = base_dir / ".env"

    # Load .env for deployment-time config only (SECRET_KEY, BAMBU_API_BASE, BAMBU_OUTPUT_DIR).
    # Runtime-writable settings (token, region, interval) live in the DB.
    load_dotenv(dotenv_path=env_path, override=False)

    # Deployment-time config from env vars
    # resolve_output_dir 確保相對路徑相對於資料根，而非 process CWD
    output_dir = resolve_output_dir(os.getenv("BAMBU_OUTPUT_DIR", "").strip() or None)
    api_base = (os.getenv("BAMBU_API_BASE", "").strip().rstrip("/") or _GLOBAL_BASE)

    if db_path is None:
        output_dir.mkdir(parents=True, exist_ok=True)
        db_path = get_db_path(output_dir)

    init_db(db_path)
    app.config["DB_PATH"] = db_path
    app.config["COVERS_DIR"] = (db_path.parent / "covers").resolve()

    # Load runtime config from DB, migrating from .env on first run.
    with get_connection(db_path) as conn:
        db_token = get_app_config(conn, "bambu_access_token")
        db_region = get_app_config(conn, "bambu_region")
        db_interval = get_app_config(conn, "auto_sync_interval")

        if not db_token:
            env_token = os.getenv("BAMBU_ACCESS_TOKEN", "").strip()
            if env_token:
                set_app_config(conn, "bambu_access_token", env_token)
                db_token = env_token

        if db_region is None:
            env_region = os.getenv("BAMBU_REGION", "global").strip().lower()
            if env_region not in _VALID_REGIONS:
                env_region = "global"
            set_app_config(conn, "bambu_region", env_region)
            db_region = env_region

        if db_interval is None:
            try:
                env_interval = str(int(os.getenv("AUTO_SYNC_INTERVAL", "0")))
            except (ValueError, TypeError):
                env_interval = "0"
            set_app_config(conn, "auto_sync_interval", env_interval)
            db_interval = env_interval

        db_backup_interval = get_app_config(conn, "backup_interval_minutes")
        if db_backup_interval is None:
            set_app_config(conn, "backup_interval_minutes", "0")
            db_backup_interval = "0"

        db_backup_keep = get_app_config(conn, "backup_keep_count")
        if db_backup_keep is None:
            set_app_config(conn, "backup_keep_count", "7")
            db_backup_keep = "7"

        db_tz_offset = get_app_config(conn, "display_tz_offset_minutes")
        if db_tz_offset is None:
            set_app_config(conn, "display_tz_offset_minutes", "0")
            db_tz_offset = "0"

    app.config["BAMBU_TOKEN"] = db_token or ""
    app.config["BAMBU_REGION"] = db_region or "global"
    app.config["BAMBU_API_BASE"] = api_base
    try:
        app.config["AUTO_SYNC_INTERVAL_MINUTES"] = int(db_interval or "0")
    except (ValueError, TypeError):
        app.config["AUTO_SYNC_INTERVAL_MINUTES"] = 0
    try:
        app.config["BACKUP_INTERVAL_MINUTES"] = int(db_backup_interval or "0")
    except (ValueError, TypeError):
        app.config["BACKUP_INTERVAL_MINUTES"] = 0
    try:
        app.config["BACKUP_KEEP_COUNT"] = max(1, min(30, int(db_backup_keep or "7")))
    except (ValueError, TypeError):
        app.config["BACKUP_KEEP_COUNT"] = 7
    try:
        tz_offset_minutes = max(-720, min(840, int(db_tz_offset or "480")))
    except (ValueError, TypeError):
        tz_offset_minutes = 480
    app.config["DISPLAY_TZ_OFFSET_MINUTES"] = tz_offset_minutes

    tz_fmt, tz_d = _make_tz_filters(tz_offset_minutes)
    app.jinja_env.filters["tz_format"] = tz_fmt
    app.jinja_env.filters["tz_date"] = tz_d
    _register_number_filters(app)

    # SECRET_KEY: read from env, generate and persist to .env if absent.
    _secret_key = os.getenv("SECRET_KEY", "").strip()
    if not _secret_key:
        _secret_key = secrets.token_hex(32)
        try:
            _dotenv_set_key(str(env_path), "SECRET_KEY", _secret_key)
        except OSError:
            pass
    app.secret_key = _secret_key

    CSRFProtect(app)
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB

    # Session cookie hardening (works for both HTTP and HTTPS local deployments)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # SESSION_COOKIE_SECURE intentionally left False for local HTTP deployment

    # File logging: co-locate with DB/covers under db_path.parent (consistent
    # with COVERS_DIR = db_path.parent / "covers").
    log_dir = db_path.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    _file_handler = RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=10_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    _file_handler.setLevel(logging.INFO)
    _file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    app.logger.addHandler(_file_handler)
    app.logger.setLevel(logging.INFO)

    from web.i18n import register_i18n
    from web.routes.analytics import bp as analytics_bp
    from web.routes.cost import bp as cost_bp
    from web.routes.dashboard import bp as dashboard_bp
    from web.routes.lang import bp as lang_bp
    from web.routes.mapping import bp as mapping_bp
    from web.routes.printers import bp as printers_bp
    from web.routes.settings import bp as settings_bp
    from web.routes.spools import bp as spools_bp
    from web.routes.tasks import bp as tasks_bp

    register_i18n(app)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(lang_bp)
    app.register_blueprint(spools_bp, url_prefix="/spools")
    app.register_blueprint(printers_bp, url_prefix="/printers")
    app.register_blueprint(tasks_bp, url_prefix="/tasks")
    app.register_blueprint(mapping_bp, url_prefix="/mapping")
    app.register_blueprint(analytics_bp, url_prefix="/analytics")
    app.register_blueprint(cost_bp, url_prefix="/cost")
    app.register_blueprint(settings_bp)

    from web.routes.settings import start_auto_sync_scheduler, start_backup_scheduler
    start_auto_sync_scheduler(app)
    start_backup_scheduler(app)

    @app.errorhandler(413)
    def request_entity_too_large(e):
        from flask import flash, redirect, request as req, url_for
        from web.i18n import t
        flash(t("flash.app.file_too_large"), "error")
        return redirect(req.referrer or url_for("dashboard.index")), 413

    _COVER_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    _cover_retry_cache: dict[int, float] = {}   # external_id -> failed_at (monotonic)
    _cover_retry_lock = threading.Lock()
    _COVER_RETRY_TTL = 600.0   # 10 分鐘內不重試同一 id
    _COVER_RETRY_MAX = 500     # 防止 dict 無限增長

    @app.route("/covers/<path:filename>")
    def covers(filename: str):
        from flask import abort
        # 拒絕含子路徑的請求（如 ../secret 或 subdir/x.png）
        if Path(filename).name != filename:
            abort(404)
        suffix = Path(filename).suffix.lower()
        if suffix not in _COVER_EXTS:
            abort(404)
        covers_dir = app.config["COVERS_DIR"]
        file_path = covers_dir / filename
        # 雲端任務封面格式：純數字 stem + .png
        if not file_path.exists():
            stem = Path(filename).stem
            if stem.isdigit() and suffix == ".png":
                ext_id = int(stem)
                now = time.monotonic()
                should_retry = False
                with _cover_retry_lock:
                    last_fail = _cover_retry_cache.get(ext_id)
                    if last_fail is None or (now - last_fail) > _COVER_RETRY_TTL:
                        should_retry = True
                        _cover_retry_cache.pop(ext_id, None)
                if should_retry:
                    from src.ingestion import try_redownload_cover
                    result = try_redownload_cover(ext_id, covers_dir, app.config["DB_PATH"])
                    if result is None:
                        with _cover_retry_lock:
                            if len(_cover_retry_cache) >= _COVER_RETRY_MAX:
                                # 清除最舊的一批避免無限增長
                                oldest = sorted(_cover_retry_cache, key=_cover_retry_cache.get)
                                for k in oldest[: _COVER_RETRY_MAX // 2]:
                                    del _cover_retry_cache[k]
                            _cover_retry_cache[ext_id] = now
        resp = make_response(send_from_directory(covers_dir, filename))
        resp.headers["Cache-Control"] = "public, max-age=2592000"
        return resp

    return app
