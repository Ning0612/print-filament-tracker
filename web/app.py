import os
import secrets
from pathlib import Path

from flask import Flask, make_response, send_from_directory

from src.config import ConfigError, load_config
from src.db import get_db_path, init_db

_GLOBAL_BASE = "https://api.bambulab.com"


def create_app(db_path: Path | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    env_path = Path(__file__).parent.parent / ".env"
    app.config["ENV_PATH"] = str(env_path)

    bambu_cfg = None
    try:
        bambu_cfg = load_config(env_path)
    except ConfigError:
        pass

    if bambu_cfg:
        app.config["BAMBU_TOKEN"] = bambu_cfg.access_token
        app.config["BAMBU_REGION"] = bambu_cfg.region
        app.config["BAMBU_API_BASE"] = bambu_cfg.api_base
        output_dir = bambu_cfg.output_dir
    else:
        app.config["BAMBU_TOKEN"] = ""
        app.config["BAMBU_REGION"] = "global"
        app.config["BAMBU_API_BASE"] = _GLOBAL_BASE
        output_dir = Path(__file__).parent.parent / "data"

    try:
        app.config["AUTO_SYNC_INTERVAL_MINUTES"] = int(os.getenv("AUTO_SYNC_INTERVAL", "0"))
    except (ValueError, TypeError):
        app.config["AUTO_SYNC_INTERVAL_MINUTES"] = 0

    if db_path is None:
        output_dir.mkdir(parents=True, exist_ok=True)
        db_path = get_db_path(output_dir)

    init_db(db_path)
    app.config["DB_PATH"] = db_path
    app.config["COVERS_DIR"] = (db_path.parent / "covers").resolve()
    app.secret_key = secrets.token_hex(32)
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB

    from web.routes.dashboard import bp as dashboard_bp
    from web.routes.mapping import bp as mapping_bp
    from web.routes.settings import bp as settings_bp
    from web.routes.spools import bp as spools_bp
    from web.routes.tasks import bp as tasks_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(spools_bp, url_prefix="/spools")
    app.register_blueprint(tasks_bp, url_prefix="/tasks")
    app.register_blueprint(mapping_bp, url_prefix="/mapping")
    app.register_blueprint(settings_bp)

    from web.routes.settings import start_auto_sync_scheduler
    start_auto_sync_scheduler(app)

    @app.errorhandler(413)
    def request_entity_too_large(e):
        from flask import flash, redirect, request as req, url_for
        flash("檔案過大，請上傳 10 MB 以內的檔案。", "error")
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
