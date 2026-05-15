import re
from datetime import date as _date, datetime as _datetime, timedelta as _td, timezone as _tz

from flask import Blueprint, abort, current_app, render_template, request

from src.analytics import (
    get_color_swatch_payload,
    get_cost_chart_payload,
    get_daily_detail_payload,
    get_duration_histogram_payload,
    get_heatmap_payload,
    get_heatmap_year_payload,
    get_material_chart_payload,
    get_monthly_trend_payload,
    get_printer_chart_payload,
    get_spool_cost_ranking_payload,
    get_weekday_stats_payload,
)
from src.db import get_connection

bp = Blueprint("analytics", __name__)


@bp.route("/")
def index():
    db_path = current_app.config["DB_PATH"]
    tz = current_app.config.get("DISPLAY_TZ_OFFSET_MINUTES", 0)
    with get_connection(db_path) as conn:
        heatmap = get_heatmap_payload(conn, tz)
        material = get_material_chart_payload(conn)
        cost = get_cost_chart_payload(conn)
        colors = get_color_swatch_payload(conn)
        trend = get_monthly_trend_payload(conn, months=60, tz_offset_minutes=tz)
        printers = get_printer_chart_payload(conn)
        duration_hist = get_duration_histogram_payload(conn)
        spool_cost = get_spool_cost_ranking_payload(conn)
        weekday = get_weekday_stats_payload(conn, tz_offset_minutes=tz)

    return render_template(
        "analytics/index.html",
        heatmap=heatmap,
        material=material,
        cost=cost,
        colors=colors,
        trend=trend,
        printers=printers,
        duration_hist=duration_hist,
        spool_cost=spool_cost,
        weekday=weekday,
    )


@bp.route("/day/<date_str>")
def day_view(date_str: str):
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        abort(400)
    try:
        day = _date.fromisoformat(date_str)
    except ValueError:
        abort(400)

    tz = current_app.config.get("DISPLAY_TZ_OFFSET_MINUTES", 0)
    local_today = (_datetime.now(_tz.utc) + _td(minutes=tz)).date()
    if day > local_today:
        abort(404)

    db_path = current_app.config["DB_PATH"]
    with get_connection(db_path) as conn:
        daily = get_daily_detail_payload(conn, date_str, tz)

    if not daily["tasks"]:
        abort(404)

    return render_template("analytics/day.html", daily=daily)


@bp.route("/heatmap")
def heatmap_fragment():
    year = request.args.get("year", type=int)
    if not year or year < 2000 or year > 2100:
        abort(400)
    db_path = current_app.config["DB_PATH"]
    tz = current_app.config.get("DISPLAY_TZ_OFFSET_MINUTES", 0)
    with get_connection(db_path) as conn:
        heatmap = get_heatmap_year_payload(conn, year, tz)
    return render_template("analytics/_heatmap.html", heatmap=heatmap)
