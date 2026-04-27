import os
import secrets
from pathlib import Path

from dotenv import load_dotenv, set_key as _dotenv_set_key
from flask import Flask, make_response, send_from_directory
from flask_wtf.csrf import CSRFProtect

from src.db import get_app_config, get_connection, get_db_path, init_db, set_app_config

_GLOBAL_BASE = "https://api.bambulab.com"
_CHINA_BASE = "https://api.bambulab.cn"

_VALID_REGIONS = {"global", "china"}


def create_app(db_path: Path | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    env_path = Path(__file__).parent.parent / ".env"

    # Load .env for deployment-time config only (SECRET_KEY, BAMBU_API_BASE, BAMBU_OUTPUT_DIR).
    # Runtime-writable settings (token, region, interval) live in the DB.
    load_dotenv(dotenv_path=env_path, override=False)

    # Deployment-time config from env vars
    output_dir = Path(os.getenv("BAMBU_OUTPUT_DIR", "data"))
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

    app.config["BAMBU_TOKEN"] = db_token or ""
    app.config["BAMBU_REGION"] = db_region or "global"
    app.config["BAMBU_API_BASE"] = api_base
    try:
        app.config["AUTO_SYNC_INTERVAL_MINUTES"] = int(db_interval or "0")
    except (ValueError, TypeError):
        app.config["AUTO_SYNC_INTERVAL_MINUTES"] = 0

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

    from web.routes.settings import start_auto_sync_scheduler
    start_auto_sync_scheduler(app)

    @app.errorhandler(413)
    def request_entity_too_large(e):
        from flask import flash, redirect, request as req, url_for
        from web.i18n import t
        flash(t("flash.app.file_too_large"), "error")
        return redirect(req.referrer or url_for("dashboard.index")), 413

    _COVER_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

    @app.route("/covers/<path:filename>")
    def covers(filename: str):
        from flask import abort
        if Path(filename).suffix.lower() not in _COVER_EXTS:
            abort(404)
        resp = make_response(send_from_directory(app.config["COVERS_DIR"], filename))
        resp.headers["Cache-Control"] = "public, max-age=2592000"
        return resp

    return app
