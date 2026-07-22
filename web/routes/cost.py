from datetime import datetime as _datetime, timedelta as _td, timezone as _tz

from flask import Blueprint, current_app, render_template, request

from src.cost import (
    compute_cost_report,
    get_all_tasks_for_cost,
    get_tasks_for_cost_by_ids,
    group_tasks_by_date,
)
from src.db import get_connection

bp = Blueprint("cost", __name__)


def _parse_int_set(form_key: str, source=None) -> set[int]:
    src = source or request.form
    result: set[int] = set()
    for v in src.getlist(form_key):
        try:
            result.add(int(v))
        except (ValueError, TypeError):
            pass
    return result


@bp.route("/")
def index():
    db_path = current_app.config["DB_PATH"]
    tz = current_app.config.get("DISPLAY_TZ_OFFSET_MINUTES", 0)
    search = request.args.get("q", "").strip() or None
    with get_connection(db_path) as conn:
        tasks = get_all_tasks_for_cost(conn, search=search, tz_offset_minutes=tz)
    date_groups = group_tasks_by_date(tasks, tz_offset_minutes=tz)
    voucher_no = (_datetime.now(_tz.utc) + _td(minutes=tz)).date().strftime("%Y%m%d")
    return render_template(
        "cost/index.html",
        date_groups=date_groups,
        search=search or "",
        voucher_no=voucher_no,
    )


@bp.route("/_tasks")
def tasks_fragment():
    db_path = current_app.config["DB_PATH"]
    tz = current_app.config.get("DISPLAY_TZ_OFFSET_MINUTES", 0)
    search = request.args.get("q", "").strip() or None
    with get_connection(db_path) as conn:
        tasks = get_all_tasks_for_cost(conn, search=search, tz_offset_minutes=tz)
    date_groups = group_tasks_by_date(tasks, tz_offset_minutes=tz)
    return render_template("cost/_tasks.html", date_groups=date_groups)


@bp.route("/recalc", methods=["POST"])
def recalc():
    db_path = current_app.config["DB_PATH"]
    tz = current_app.config.get("DISPLAY_TZ_OFFSET_MINUTES", 0)

    selected_task_ids = _parse_int_set("task_ids[]")
    included_ptf_ids = _parse_int_set("ptf_ids[]")

    try:
        hourly_rate = float(request.form.get("hourly_rate") or 0)
    except (ValueError, TypeError):
        hourly_rate = 0.0

    if not selected_task_ids:
        return render_template("cost/_cost_summary.html", report=None, hourly_rate=hourly_rate)

    with get_connection(db_path) as conn:
        tasks = get_tasks_for_cost_by_ids(conn, selected_task_ids, tz_offset_minutes=tz)

    report = compute_cost_report(tasks, selected_task_ids, included_ptf_ids, hourly_rate)
    return render_template("cost/_cost_summary.html", report=report, hourly_rate=hourly_rate)


@bp.route("/print_view")
def print_view():
    db_path = current_app.config["DB_PATH"]
    tz = current_app.config.get("DISPLAY_TZ_OFFSET_MINUTES", 0)

    selected_task_ids: set[int] = set()
    for v in request.args.getlist("task_ids[]"):
        try:
            selected_task_ids.add(int(v))
        except (ValueError, TypeError):
            pass

    included_ptf_ids: set[int] = set()
    for v in request.args.getlist("ptf_ids[]"):
        try:
            included_ptf_ids.add(int(v))
        except (ValueError, TypeError):
            pass

    try:
        hourly_rate = float(request.args.get("hourly_rate") or 0)
    except (ValueError, TypeError):
        hourly_rate = 0.0

    if not selected_task_ids:
        return render_template("cost/print_view.html", report=None, hourly_rate=0.0)

    with get_connection(db_path) as conn:
        tasks = get_tasks_for_cost_by_ids(conn, selected_task_ids, tz_offset_minutes=tz)

    report = compute_cost_report(tasks, selected_task_ids, included_ptf_ids, hourly_rate)
    generated_on = (_datetime.now(_tz.utc) + _td(minutes=tz)).date().isoformat()
    return render_template(
        "cost/print_view.html",
        report=report,
        hourly_rate=hourly_rate,
        generated_on=generated_on,
    )
