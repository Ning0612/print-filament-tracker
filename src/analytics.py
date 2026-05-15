import re
import sqlite3
from datetime import date, datetime, timedelta

_HEX_RE = re.compile(r"^[0-9A-Fa-f]{6}$")

from src.db import (
    get_cost_breakdown,
    get_daily_filament_summary,
    get_duration_histogram,
    get_heatmap_available_years,
    get_heatmap_data_for_year,
    get_material_usage_stats,
    get_monthly_trend,
    get_printer_usage_stats,
    get_spool_color_usage_stats,
    get_spool_cost_ranking,
    get_tasks_for_date,
    get_weekday_stats,
)

_MATERIAL_PALETTE = [
    "#3B82F6", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6",
    "#06B6D4", "#F97316", "#84CC16", "#EC4899", "#6366F1",
]

_MONTH_NAMES = ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"]

_DURATION_BUCKET_LABELS = ["<30分", "30分–1時", "1–2時", "2–4時", "4–8時", ">8時"]

_WEEKDAY_NAMES = ["一", "二", "三", "四", "五", "六", "日"]


def _hex6(color_hex: str) -> str:
    h = (color_hex or "").strip().lstrip("#")
    if len(h) == 8:
        h = h[:6]
    if len(h) == 6 and _HEX_RE.match(h):
        return f"#{h.upper()}"
    return "#888888"


def _build_year_grid(year: int, by_date: dict) -> tuple:
    """
    Build heatmap grid for a full calendar year.
    Returns (grid, month_labels):
      grid: list of week-columns (Mon→Sun), each a list of 7 day-dicts
      month_labels: list of str per column (month name at first col of month, else "")
    """
    today = date.today()
    jan1 = date(year, 1, 1)
    dec31 = date(year, 12, 31)

    # Start on the Monday of the week containing Jan 1
    start = jan1 - timedelta(days=jan1.weekday())
    # End on the Sunday of the week containing Dec 31
    end_sunday = dec31 + timedelta(days=(6 - dec31.weekday()))

    grid = []
    month_labels = []
    seen_months: set = set()
    current = start

    while current <= end_sunday:
        col = []
        col_label = ""

        for _ in range(7):
            in_year = (current.year == year)
            is_future = (current > today)
            ds = current.isoformat()

            if in_year and not is_future:
                info = by_date.get(ds, {"count": 0, "weight_g": 0.0})
                col.append({
                    "date": ds, "count": info["count"],
                    "weight_g": info["weight_g"], "in_year": True, "future": False,
                })
            else:
                col.append({
                    "date": ds, "count": 0, "weight_g": 0.0,
                    "in_year": in_year, "future": is_future,
                })

            if in_year and current.month not in seen_months:
                seen_months.add(current.month)
                col_label = _MONTH_NAMES[current.month - 1]

            current += timedelta(days=1)

        month_labels.append(col_label)
        grid.append(col)

    return grid, month_labels


def get_heatmap_year_payload(conn: sqlite3.Connection, year: int) -> dict:
    rows = get_heatmap_data_for_year(conn, year)
    by_date = {
        r["date"]: {"count": r["count"], "weight_g": round(r["weight_g"], 1)}
        for r in rows
    }
    grid, month_labels = _build_year_grid(year, by_date)
    active_days = [d for col in grid for d in col if d["in_year"] and not d["future"]]
    max_count = max((d["count"] for d in active_days), default=1) or 1
    total_tasks = sum(r["count"] for r in rows)
    total_days_active = sum(1 for r in rows if r["count"] > 0)
    return {
        "year": year,
        "grid": grid,
        "month_labels": month_labels,
        "max_count": max_count,
        "total_tasks": total_tasks,
        "total_days_active": total_days_active,
        "has_data": bool(rows),
    }


def get_heatmap_payload(conn: sqlite3.Connection) -> dict:
    """Returns available years list + earliest year's grid for initial render."""
    years = get_heatmap_available_years(conn)
    if not years:
        return {"years": [], "current_year": None, "has_data": False,
                "grid": [], "month_labels": [], "max_count": 1,
                "total_tasks": 0, "total_days_active": 0}

    current_year = years[0]  # default to first (oldest) year with data
    year_data = get_heatmap_year_payload(conn, current_year)
    return {"years": years, "current_year": current_year, **year_data}


def get_material_chart_payload(conn: sqlite3.Connection) -> dict:
    rows = get_material_usage_stats(conn)
    labels = [r["material"] for r in rows]
    data = [round(r["total_g"], 1) for r in rows]
    colors = [_MATERIAL_PALETTE[i % len(_MATERIAL_PALETTE)] for i in range(len(rows))]
    return {"labels": labels, "data": data, "colors": colors, "has_data": bool(rows)}


def get_cost_chart_payload(conn: sqlite3.Connection) -> dict:
    return get_cost_breakdown(conn)


def get_color_swatch_payload(conn: sqlite3.Connection) -> list:
    """Use mapped spool colors (not raw AMS print colors)."""
    rows = get_spool_color_usage_stats(conn, top_n=15)
    return [
        {
            "color_hex": _hex6(r["color_hex"]),
            "color_name": r["color_name"] or "",
            "material": r["material"] or "",
            "total_g": round(r["total_g"], 1),
        }
        for r in rows
    ]


def get_monthly_trend_payload(conn: sqlite3.Connection, months: int = 60) -> dict:
    rows = get_monthly_trend(conn, months=months)
    by_month = {r["month"]: r for r in rows}

    today = date.today()
    labels, counts, weights, durations_h = [], [], [], []
    for i in range(months - 1, -1, -1):
        y = today.year
        m = today.month - i
        while m <= 0:
            m += 12
            y -= 1
        key = f"{y:04d}-{m:02d}"
        labels.append(key)
        r = by_month.get(key)
        counts.append(r["task_count"] if r else 0)
        weights.append(round(r["weight_g"], 1) if r else 0.0)
        durations_h.append(round(r["duration_s"] / 3600, 1) if r else 0.0)

    return {
        "labels": labels, "counts": counts, "weights": weights,
        "durations_h": durations_h, "has_data": bool(rows),
        "has_duration_data": any(v > 0 for v in durations_h),
    }


def get_printer_chart_payload(conn: sqlite3.Connection) -> dict:
    rows = get_printer_usage_stats(conn)
    active = [r for r in rows if r["task_count"] > 0]
    labels = [r["name"] for r in active]
    tasks = [r["task_count"] for r in active]
    weights = [round(r["total_weight_g"], 1) for r in active]
    durations_h = [round(r["total_duration_s"] / 3600, 1) for r in active]
    colors = [_MATERIAL_PALETTE[i % len(_MATERIAL_PALETTE)] for i in range(len(active))]
    return {
        "labels": labels, "tasks": tasks,
        "weights": weights, "durations_h": durations_h,
        "colors": colors,
        "has_data": bool(active),
        "has_duration_data": any(v > 0 for v in durations_h),
    }


def get_duration_histogram_payload(conn: sqlite3.Connection) -> dict:
    rows = get_duration_histogram(conn)
    by_bucket = {r["bucket"]: r["count"] for r in rows}
    counts = [by_bucket.get(i, 0) for i in range(6)]
    return {
        "labels": _DURATION_BUCKET_LABELS,
        "counts": counts,
        "has_data": sum(counts) > 0,
    }


def get_spool_cost_ranking_payload(conn: sqlite3.Connection, top_n: int = 15) -> dict:
    rows = get_spool_cost_ranking(conn)
    spools = []
    for r in rows:
        ratio = min(r["used_g"] / r["initial_weight_g"], 1.0)
        used_cost = r["price"] * ratio
        color_name = r["color_name"] or ""
        material = r["material"] or ""
        if color_name and material:
            label = f"{color_name}({material})"
        elif color_name:
            label = color_name
        elif material:
            label = material
        else:
            label = f"#{r['id']}"
        spools.append({
            "label": label,
            "cost": round(used_cost, 2),
            "color_hex": _hex6(r["color_hex"]) if r["color_hex"] else "#888888",
        })
    spools.sort(key=lambda x: x["cost"], reverse=True)
    spools = spools[:top_n]
    max_cost = spools[0]["cost"] if spools else 1.0
    return {
        "spools": spools,
        "max_cost": max_cost,
        "has_data": bool(spools),
    }


def _build_timeline(tasks: list) -> tuple:
    """Build per-printer timeline segments. Returns (printers, tl_start_label, tl_end_label)."""
    printer_tasks: dict = {}
    all_times: list = []

    for task in tasks:
        start_str = task.get("started_at")
        if not start_str:
            continue
        try:
            start_dt = datetime.fromisoformat(start_str[:19])
        except ValueError:
            continue

        end_str = task.get("ended_at")
        duration_s = task.get("duration_seconds") or 0
        end_dt = None
        if end_str:
            try:
                end_dt = datetime.fromisoformat(end_str[:19])
            except ValueError:
                pass
        if end_dt is None or end_dt <= start_dt:
            end_dt = start_dt + timedelta(seconds=duration_s) if duration_s else start_dt + timedelta(minutes=1)

        printer_name = task.get("printer_name") or "未知"
        printer_id = task.get("printer_id") or 0
        key = (printer_id, printer_name)
        if key not in printer_tasks:
            printer_tasks[key] = []
        printer_tasks[key].append({
            "task_id": task["id"],
            "task_name": task.get("print_name") or "",
            "start_dt": start_dt,
            "end_dt": end_dt,
            "failed": task.get("status") == 3,
        })
        all_times += [start_dt, end_dt]

    if not printer_tasks:
        return [], "", ""

    # Always span the full day 00:00–23:59:59
    sample_dt = all_times[0]
    tl_start = sample_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    tl_end = sample_dt.replace(hour=23, minute=59, second=59, microsecond=0)
    total_s = (tl_end - tl_start).total_seconds()

    def pct(dt: datetime) -> float:
        return round((dt - tl_start).total_seconds() / total_s * 100, 2)

    result = []
    for (_, printer_name), ptasks in sorted(printer_tasks.items(), key=lambda x: x[0][1]):
        ptasks.sort(key=lambda t: t["start_dt"])
        segments = []
        cursor = tl_start

        for pt in ptasks:
            if pt["start_dt"] > cursor:
                segments.append({
                    "type": "idle",
                    "left_pct": pct(cursor),
                    "width_pct": pct(pt["start_dt"]) - pct(cursor),
                    "tooltip": f"{cursor.strftime('%H:%M')}–{pt['start_dt'].strftime('%H:%M')}",
                })
            w = max(pct(pt["end_dt"]) - pct(pt["start_dt"]), 0.5)
            segments.append({
                "type": "printing_failed" if pt["failed"] else "printing",
                "left_pct": pct(pt["start_dt"]),
                "width_pct": w,
                "task_id": pt["task_id"],
                "task_name": pt["task_name"],
                "tooltip": f"{pt['task_name']}  {pt['start_dt'].strftime('%H:%M')}–{pt['end_dt'].strftime('%H:%M')}",
            })
            cursor = max(cursor, pt["end_dt"])

        if cursor < tl_end:
            segments.append({
                "type": "idle",
                "left_pct": pct(cursor),
                "width_pct": 100.0 - pct(cursor),
                "tooltip": f"{cursor.strftime('%H:%M')}–24:00",
            })

        printing_s = sum(
            (pt["end_dt"] - pt["start_dt"]).total_seconds() for pt in ptasks
        )
        utilization_pct = round(printing_s / total_s * 100, 1)

        result.append({
            "printer_name": printer_name,
            "segments": segments,
            "utilization_pct": utilization_pct,
        })

    return result, "00:00", "24:00"


def get_daily_detail_payload(conn: sqlite3.Connection, date_str: str) -> dict:
    tasks = get_tasks_for_date(conn, date_str)
    filament_summary = get_daily_filament_summary(conn, date_str)

    total_duration_s = sum(t.get("duration_seconds") or 0 for t in tasks)
    total_weight_g = sum(t.get("total_weight_g") or 0 for t in tasks)

    filaments = []
    for f in filament_summary:
        filaments.append({
            "label": f["label"] or f["color_hex"] or "—",
            "color_hex": _hex6(f["color_hex"]) if f["color_hex"] else "#888888",
            "material": f["material"] or "",
            "total_g": round(f["total_g"] or 0, 1),
            "spool_id": f["spool_id"],
        })

    # Daily cost (only priced, mapped spools)
    total_cost_day: float | None = None
    for f in filament_summary:
        price = f.get("price")
        init_g = f.get("spool_initial_weight_g")
        used_g = f.get("total_g") or 0
        if price and init_g and init_g > 0 and used_g > 0:
            ratio = min(used_g / init_g, 1.0)
            total_cost_day = (total_cost_day or 0.0) + price * ratio
    if total_cost_day is not None:
        total_cost_day = round(total_cost_day, 2)

    # Material type distribution
    mat_totals: dict = {}
    for f in filament_summary:
        mat = f["material"] or "未知"
        mat_totals[mat] = mat_totals.get(mat, 0.0) + (f.get("total_g") or 0)
    total_mat_g = sum(mat_totals.values()) or 1.0
    material_dist = [
        {
            "material": mat,
            "total_g": round(g, 1),
            "pct": round(g / total_mat_g * 100, 1),
            "color": _MATERIAL_PALETTE[i % len(_MATERIAL_PALETTE)],
        }
        for i, (mat, g) in enumerate(
            sorted(mat_totals.items(), key=lambda x: x[1], reverse=True)
        )
    ]

    timeline, tl_start, tl_end = _build_timeline(tasks)

    return {
        "date": date_str,
        "tasks": tasks,
        "filaments": filaments,
        "total_duration_s": total_duration_s,
        "total_duration_h": round(total_duration_s / 3600, 1),
        "total_weight_g": round(total_weight_g, 1),
        "task_count": len(tasks),
        "total_cost_day": total_cost_day,
        "material_dist": material_dist,
        "timeline": timeline,
        "tl_start": tl_start,
        "tl_end": tl_end,
    }


def get_weekday_stats_payload(conn: sqlite3.Connection) -> dict:
    rows = get_weekday_stats(conn)
    by_weekday = {r["weekday"]: dict(r) for r in rows}
    # SQLite %w: 0=Sun, 1=Mon..6=Sat → reorder to Mon–Sun (1,2,3,4,5,6,0)
    order = [1, 2, 3, 4, 5, 6, 0]
    counts = [by_weekday.get(w, {}).get("task_count", 0) for w in order]
    weights = [round(by_weekday.get(w, {}).get("weight_g", 0.0), 1) for w in order]
    return {
        "labels": _WEEKDAY_NAMES,
        "counts": counts,
        "weights": weights,
        "has_data": sum(counts) > 0,
    }
