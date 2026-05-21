import sqlite3


def _tz_mod(col: str, tz_minutes: int) -> str:
    """Return SQLite expression that shifts UTC timestamps by tz_minutes.

    For the 'now' literal (always UTC): returns DATETIME('now', modifier).
    For column references: uses CASE to only shift strings ending in 'Z'
    (cloud tasks), leaving manual task local-time strings untouched.
    """
    if tz_minutes == 0:
        return col
    mod = f"+{tz_minutes} minutes" if tz_minutes >= 0 else f"{tz_minutes} minutes"
    if col.startswith("'") and col.endswith("'"):
        return f"DATETIME({col}, '{mod}')"
    return (
        f"CASE WHEN {col} LIKE '%Z' "
        f"THEN DATETIME({col}, '{mod}') "
        f"ELSE {col} END"
    )


def get_heatmap_available_years(conn: sqlite3.Connection, tz_offset_minutes: int = 0) -> list:
    tz = _tz_mod("started_at", tz_offset_minutes)
    rows = conn.execute(
        f"""
        SELECT DISTINCT STRFTIME('%Y', {tz}) AS year
        FROM print_task
        WHERE started_at IS NOT NULL
        ORDER BY year
        """
    ).fetchall()
    return [int(r["year"]) for r in rows]


def get_heatmap_data_for_year(conn: sqlite3.Connection, year: int, tz_offset_minutes: int = 0) -> list:
    tz = _tz_mod("started_at", tz_offset_minutes)
    return conn.execute(
        f"""
        SELECT DATE({tz}) AS date,
               COUNT(*) AS count,
               COALESCE(SUM(total_weight_g), 0.0) AS weight_g
        FROM print_task
        WHERE DATE({tz}) >= ? AND DATE({tz}) < ?
          AND started_at IS NOT NULL
        GROUP BY DATE({tz})
        ORDER BY date
        """,
        (f"{year}-01-01", f"{year + 1}-01-01"),
    ).fetchall()


def get_spool_color_usage_stats(conn: sqlite3.Connection, top_n: int = 15) -> list:
    return conn.execute(
        """
        SELECT fs.color_hex,
               fs.color_name,
               fs.material,
               COALESCE(SUM(ptf.used_weight_g), 0.0) AS total_g
        FROM print_task_filament ptf
        JOIN filament_spool fs ON fs.id = ptf.filament_spool_id
        WHERE ptf.is_ignored = 0
          AND fs.color_hex IS NOT NULL AND fs.color_hex != ''
        GROUP BY fs.color_hex, fs.color_name, fs.product_url, fs.material
        ORDER BY total_g DESC
        LIMIT ?
        """,
        (top_n,),
    ).fetchall()


def get_material_usage_stats(conn: sqlite3.Connection) -> list:
    return conn.execute(
        """
        SELECT ptf.material,
               COALESCE(SUM(ptf.used_weight_g), 0.0) AS total_g,
               COUNT(DISTINCT ptf.print_task_id) AS task_count
        FROM print_task_filament ptf
        WHERE ptf.is_ignored = 0 AND ptf.material IS NOT NULL AND ptf.material != ''
        GROUP BY ptf.material
        ORDER BY total_g DESC
        """
    ).fetchall()


def get_heatmap_data(conn: sqlite3.Connection, weeks: int = 52, tz_offset_minutes: int = 0) -> list:
    # Query 7 extra days so the grid's left-edge weeks are always fully covered.
    days = weeks * 7 + 7
    tz = _tz_mod("started_at", tz_offset_minutes)
    tz_now = _tz_mod("'now'", tz_offset_minutes)
    return conn.execute(
        f"""
        SELECT DATE({tz}) AS date,
               COUNT(*) AS count,
               COALESCE(SUM(total_weight_g), 0.0) AS weight_g
        FROM print_task
        WHERE DATE({tz}) >= DATE({tz_now}, '-{days} days')
          AND started_at IS NOT NULL
        GROUP BY DATE({tz})
        ORDER BY date
        """
    ).fetchall()


def get_color_usage_stats(conn: sqlite3.Connection, top_n: int = 20) -> list:
    return conn.execute(
        """
        SELECT ptf.color_hex,
               MAX(ptf.material) AS material,
               COALESCE(SUM(ptf.used_weight_g), 0.0) AS total_g
        FROM print_task_filament ptf
        WHERE ptf.is_ignored = 0
          AND ptf.color_hex IS NOT NULL AND ptf.color_hex != ''
        GROUP BY ptf.color_hex
        ORDER BY total_g DESC
        LIMIT ?
        """,
        (top_n,),
    ).fetchall()


def get_cost_breakdown(conn: sqlite3.Connection) -> dict:
    priced = conn.execute(
        """
        SELECT fs.id,
               fs.initial_weight_g,
               fs.price,
               COALESCE(SUM(ptf.used_weight_g), 0.0) AS used_g
        FROM filament_spool fs
        LEFT JOIN print_task_filament ptf ON ptf.filament_spool_id = fs.id AND ptf.is_ignored = 0
        WHERE fs.price IS NOT NULL AND fs.initial_weight_g > 0
        GROUP BY fs.id
        """
    ).fetchall()

    unpriced = conn.execute(
        """
        SELECT COUNT(*) AS cnt,
               COALESCE(SUM(fs.initial_weight_g), 0.0) AS total_initial_g
        FROM filament_spool fs
        WHERE fs.price IS NULL
        """
    ).fetchone()

    known_used = 0.0
    known_remaining = 0.0
    for r in priced:
        ratio_used = min(r["used_g"] / r["initial_weight_g"], 1.0)
        known_used += r["price"] * ratio_used
        known_remaining += r["price"] * (1.0 - ratio_used)

    return {
        "known_used": round(known_used, 2),
        "known_remaining": round(known_remaining, 2),
        "known_total": round(known_used + known_remaining, 2),
        "unpriced_count": unpriced["cnt"],
        "unpriced_initial_g": unpriced["total_initial_g"],
        "priced_spool_count": len(priced),
    }


def get_monthly_trend(conn: sqlite3.Connection, months: int = 12, tz_offset_minutes: int = 0) -> list:
    tz = _tz_mod("started_at", tz_offset_minutes)
    tz_now = _tz_mod("'now'", tz_offset_minutes)
    return conn.execute(
        f"""
        SELECT STRFTIME('%Y-%m', {tz}) AS month,
               COUNT(*) AS task_count,
               COALESCE(SUM(total_weight_g), 0.0) AS weight_g,
               COALESCE(SUM(duration_seconds), 0) AS duration_s
        FROM print_task
        WHERE {tz} >= DATE({tz_now}, '-{months} months')
          AND started_at IS NOT NULL
        GROUP BY month
        ORDER BY month
        """
    ).fetchall()


def get_printer_usage_stats(conn: sqlite3.Connection) -> list:
    return conn.execute(
        """
        SELECT p.id, p.name, p.model,
               COUNT(pt.id) AS task_count,
               COALESCE(SUM(pt.duration_seconds), 0) AS total_duration_s,
               COALESCE(SUM(pt.total_weight_g), 0.0) AS total_weight_g
        FROM printer p
        LEFT JOIN print_task pt ON pt.printer_id = p.id
        GROUP BY p.id
        ORDER BY task_count DESC
        """
    ).fetchall()


def get_duration_histogram(conn: sqlite3.Connection) -> list:
    return conn.execute(
        """
        SELECT
          CASE
            WHEN duration_seconds < 1800  THEN 0
            WHEN duration_seconds < 3600  THEN 1
            WHEN duration_seconds < 7200  THEN 2
            WHEN duration_seconds < 14400 THEN 3
            WHEN duration_seconds < 28800 THEN 4
            ELSE 5
          END AS bucket,
          COUNT(*) AS count
        FROM print_task
        WHERE duration_seconds IS NOT NULL AND duration_seconds > 0
        GROUP BY bucket
        ORDER BY bucket
        """
    ).fetchall()


def get_spool_cost_ranking(conn: sqlite3.Connection) -> list:
    return conn.execute(
        """
        SELECT fs.id,
               fs.material,
               fs.color_name,
               fs.color_hex,
               fs.initial_weight_g,
               fs.price,
               COALESCE(SUM(ptf.used_weight_g), 0.0) AS used_g
        FROM filament_spool fs
        LEFT JOIN print_task_filament ptf
               ON ptf.filament_spool_id = fs.id AND ptf.is_ignored = 0
        WHERE fs.price IS NOT NULL AND fs.initial_weight_g > 0
        GROUP BY fs.id
        HAVING used_g > 0
        """
    ).fetchall()


def get_weekday_stats(conn: sqlite3.Connection, tz_offset_minutes: int = 0) -> list:
    tz = _tz_mod("started_at", tz_offset_minutes)
    return conn.execute(
        f"""
        SELECT CAST(STRFTIME('%w', {tz}) AS INTEGER) AS weekday,
               COUNT(*) AS task_count,
               COALESCE(SUM(total_weight_g), 0.0) AS weight_g
        FROM print_task
        WHERE started_at IS NOT NULL
        GROUP BY weekday
        ORDER BY weekday
        """
    ).fetchall()


def get_tasks_for_date(conn: sqlite3.Connection, date_str: str, tz_offset_minutes: int = 0) -> list:
    tz = _tz_mod("pt.started_at", tz_offset_minutes)
    rows = conn.execute(
        f"""
        SELECT pt.*, p.name AS printer_name
        FROM print_task pt LEFT JOIN printer p ON p.id = pt.printer_id
        WHERE DATE({tz}) = ?
        ORDER BY {tz}
        """,
        (date_str,),
    ).fetchall()
    tasks = []
    for row in rows:
        d = dict(row)
        filaments = conn.execute(
            """
            SELECT ptf.*, fs.color_name, fs.color_hex AS spool_color_hex,
                   fs.material AS spool_material, fs.uid AS spool_uid
            FROM print_task_filament ptf
            LEFT JOIN filament_spool fs ON fs.id = ptf.filament_spool_id
            WHERE ptf.print_task_id = ? AND ptf.is_ignored = 0
            ORDER BY ptf.slot_id
            """,
            (d["id"],),
        ).fetchall()
        d["filaments"] = [dict(f) for f in filaments]
        tasks.append(d)
    return tasks


def get_daily_filament_summary(conn: sqlite3.Connection, date_str: str, tz_offset_minutes: int = 0) -> list:
    tz = _tz_mod("pt.started_at", tz_offset_minutes)
    rows = conn.execute(
        f"""
        SELECT
            ptf.filament_spool_id,
            fs.id AS spool_id,
            COALESCE(fs.color_name, ptf.color_hex) AS label,
            COALESCE(fs.color_hex, ptf.color_hex) AS color_hex,
            COALESCE(fs.material, ptf.material) AS material,
            SUM(ptf.used_weight_g) AS total_g,
            fs.price,
            fs.initial_weight_g AS spool_initial_weight_g
        FROM print_task_filament ptf
        JOIN print_task pt ON pt.id = ptf.print_task_id
        LEFT JOIN filament_spool fs ON fs.id = ptf.filament_spool_id
        WHERE DATE({tz}) = ? AND ptf.is_ignored = 0
        GROUP BY ptf.filament_spool_id, COALESCE(fs.color_hex, ptf.color_hex), COALESCE(fs.material, ptf.material)
        ORDER BY total_g DESC
        """,
        (date_str,),
    ).fetchall()
    return [dict(r) for r in rows]
