from flask import Blueprint, current_app, render_template

from src.db import get_connection, get_recent_tasks
from src.filament import list_spools, list_unmapped

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    db_path = current_app.config["DB_PATH"]
    spools = list_spools(db_path)
    unmapped_count = len(list_unmapped(db_path))

    stats = {
        "total": len(spools),
        "active": sum(1 for s in spools if s["status"] == "active"),
        "low": sum(1 for s in spools if s["status"] == "low"),
        "sealed": sum(1 for s in spools if s["status"] == "sealed"),
        "empty": sum(1 for s in spools if s["status"] == "empty"),
    }

    with get_connection(db_path) as conn:
        recent_tasks = get_recent_tasks(conn, limit=10)
        row = conn.execute(
            """
            SELECT COUNT(*) AS cnt,
                   COALESCE(SUM(total_weight_g), 0.0) AS weight_g,
                   COALESCE(SUM(duration_seconds), 0) AS duration_s
            FROM print_task
            """
        ).fetchone()
        print_stats = {
            "total_tasks": row["cnt"],
            "total_weight_g": row["weight_g"],
            "total_duration_seconds": row["duration_s"],
        }

    return render_template(
        "dashboard.html",
        spools=spools,
        stats=stats,
        unmapped_count=unmapped_count,
        recent_tasks=recent_tasks,
        print_stats=print_stats,
    )
