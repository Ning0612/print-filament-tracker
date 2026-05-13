import logging
import os
import secrets
import sys as _sys
import threading
import time
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
