from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone


def _calc_filament_cost(
    price: float | None,
    initial_weight_g: float | None,
    used_weight_g: float | None,
) -> float | None:
    if price is None or not initial_weight_g or initial_weight_g <= 0:
        return None
    return (price / initial_weight_g) * (used_weight_g or 0.0)


def _parse_local_date(started_at: str | None, tz_offset_minutes: int) -> str:
    if not started_at:
        return "unknown"
    try:
        s = started_at.strip()
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1]).replace(tzinfo=timezone.utc)
        elif "+" in s[10:] or (s.count("-") > 2 and "T" in s):
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        local_dt = dt + timedelta(minutes=tz_offset_minutes)
        return local_dt.date().isoformat()
    except (ValueError, AttributeError):
        return started_at[:10] if started_at else "unknown"


def get_all_tasks_for_cost(
    conn: sqlite3.Connection,
    search: str | None = None,
    tz_offset_minutes: int = 0,
) -> list[dict]:
    search_param = f"%{search}%" if search else None
    rows = conn.execute(
        """
        SELECT
          pt.id, pt.print_name, pt.started_at, pt.ended_at, pt.duration_seconds,
          pt.status, pt.total_weight_g, pt.cover_url, pt.is_manual,
          p.name AS printer_name
        FROM print_task pt
        LEFT JOIN printer p ON p.id = pt.printer_id
        WHERE (? IS NULL OR pt.print_name LIKE ?)
        ORDER BY pt.started_at DESC, pt.id DESC
        """,
        (search_param, search_param),
    ).fetchall()

    tasks = []
    for row in rows:
        d = dict(row)
        filaments = conn.execute(
            """
            SELECT
              ptf.id AS ptf_id, ptf.slot_id, ptf.used_weight_g,
              ptf.color_hex, ptf.material, ptf.is_ignored,
              ptf.filament_spool_id AS spool_id,
              COALESCE(fs.color_name, ptf.material, ptf.color_hex, '?') AS ptf_label,
              COALESCE(fs.color_hex, ptf.color_hex, '#888888') AS ptf_display_color,
              fs.price AS spool_price,
              fs.initial_weight_g AS spool_initial_g
            FROM print_task_filament ptf
            LEFT JOIN filament_spool fs ON fs.id = ptf.filament_spool_id
            WHERE ptf.print_task_id = ? AND ptf.is_ignored = 0
            ORDER BY ptf.slot_id
            """,
            (d["id"],),
        ).fetchall()

        d["filaments"] = []
        for f in filaments:
            fd = dict(f)
            fd["cost"] = _calc_filament_cost(
                fd["spool_price"], fd["spool_initial_g"], fd["used_weight_g"]
            )
            d["filaments"].append(fd)

        tasks.append(d)

    return tasks


def get_tasks_for_cost_by_ids(
    conn: sqlite3.Connection,
    task_ids: set[int],
    tz_offset_minutes: int = 0,
) -> list[dict]:
    if not task_ids:
        return []
    placeholders = ",".join("?" * len(task_ids))
    rows = conn.execute(
        f"""
        SELECT
          pt.id, pt.print_name, pt.started_at, pt.ended_at, pt.duration_seconds,
          pt.status, pt.total_weight_g, pt.cover_url, pt.is_manual,
          p.name AS printer_name
        FROM print_task pt
        LEFT JOIN printer p ON p.id = pt.printer_id
        WHERE pt.id IN ({placeholders})
        ORDER BY pt.started_at DESC, pt.id DESC
        """,
        list(task_ids),
    ).fetchall()

    tasks = []
    for row in rows:
        d = dict(row)
        filaments = conn.execute(
            """
            SELECT
              ptf.id AS ptf_id, ptf.slot_id, ptf.used_weight_g,
              ptf.color_hex, ptf.material, ptf.is_ignored,
              ptf.filament_spool_id AS spool_id,
              COALESCE(fs.color_name, ptf.material, ptf.color_hex, '?') AS ptf_label,
              COALESCE(fs.color_hex, ptf.color_hex, '#888888') AS ptf_display_color,
              fs.price AS spool_price,
              fs.initial_weight_g AS spool_initial_g
            FROM print_task_filament ptf
            LEFT JOIN filament_spool fs ON fs.id = ptf.filament_spool_id
            WHERE ptf.print_task_id = ? AND ptf.is_ignored = 0
            ORDER BY ptf.slot_id
            """,
            (d["id"],),
        ).fetchall()

        d["filaments"] = []
        for f in filaments:
            fd = dict(f)
            fd["cost"] = _calc_filament_cost(
                fd["spool_price"], fd["spool_initial_g"], fd["used_weight_g"]
            )
            d["filaments"].append(fd)

        tasks.append(d)

    return tasks


def group_tasks_by_date(
    tasks: list[dict],
    tz_offset_minutes: int = 0,
) -> list[tuple[str, list[dict]]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for task in tasks:
        date_key = _parse_local_date(task.get("started_at"), tz_offset_minutes)
        groups[date_key].append(task)
    return sorted(groups.items(), reverse=True)


def compute_cost_report(
    tasks: list[dict],
    selected_task_ids: set[int],
    included_ptf_ids: set[int],
    hourly_rate: float,
) -> dict:
    total_filament_cost = 0.0
    total_time_cost = 0.0
    total_duration_seconds = 0
    per_task: list[dict] = []
    unpriced_count = 0
    unpriced_weight_g = 0.0

    for task in tasks:
        if task["id"] not in selected_task_ids:
            continue

        total_duration_seconds += task.get("duration_seconds") or 0
        task_filament_cost = 0.0
        task_filament_details: list[dict] = []

        for f in task.get("filaments", []):
            ptf_id = f["ptf_id"]
            if ptf_id not in included_ptf_ids:
                continue
            if f["cost"] is not None:
                task_filament_cost += f["cost"]
            else:
                unpriced_count += 1
                unpriced_weight_g += f["used_weight_g"] or 0.0
            task_filament_details.append({
                "ptf_id": ptf_id,
                "label": f["ptf_label"],
                "color": f["ptf_display_color"],
                "weight_g": f["used_weight_g"] or 0.0,
                "cost": f["cost"],
            })

        duration_h = (task.get("duration_seconds") or 0) / 3600.0
        task_time_cost = duration_h * hourly_rate
        total_filament_cost += task_filament_cost
        total_time_cost += task_time_cost

        per_task.append({
            "id": task["id"],
            "print_name": task.get("print_name") or "未命名",
            "started_at": task.get("started_at"),
            "duration_seconds": task.get("duration_seconds"),
            "printer_name": task.get("printer_name"),
            "cover_url": task.get("cover_url"),
            "filament_cost": task_filament_cost,
            "time_cost": task_time_cost,
            "total": task_filament_cost + task_time_cost,
            "filaments": task_filament_details,
        })

    return {
        "filament_cost": total_filament_cost,
        "time_cost": total_time_cost,
        "total": total_filament_cost + total_time_cost,
        "task_count": len(per_task),
        "per_task": per_task,
        "unpriced_count": unpriced_count,
        "unpriced_weight_g": unpriced_weight_g,
        "has_data": len(per_task) > 0,
        "hourly_rate": hourly_rate,
        "total_duration_seconds": total_duration_seconds,
    }
