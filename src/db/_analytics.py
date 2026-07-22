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


def get_cross_day_ranges_for_year(conn: sqlite3.Connection, year: int, tz_offset_minutes: int = 0) -> list:
    """Return (start_date, end_date) string pairs for all multi-day tasks overlapping the given year.
    Used to mark intermediate/end days in the heatmap as navigable.
    """
    tz_s = _tz_mod("pt.started_at", tz_offset_minutes)
    if tz_offset_minutes == 0:
        local_eff_end = (
            "CASE WHEN pt.ended_at IS NOT NULL THEN pt.ended_at "
            "WHEN pt.duration_seconds > 0 THEN DATETIME(pt.started_at, '+' || pt.duration_seconds || ' seconds') "
            "ELSE NULL END"
        )
    else:
        mod = f"+{tz_offset_minutes} minutes" if tz_offset_minutes >= 0 else f"{tz_offset_minutes} minutes"
        local_eff_end = (
            f"CASE WHEN pt.ended_at IS NOT NULL THEN "
            f"CASE WHEN pt.ended_at LIKE '%Z' THEN DATETIME(pt.ended_at, '{mod}') ELSE pt.ended_at END "
            f"WHEN pt.duration_seconds > 0 THEN "
            f"CASE WHEN pt.started_at LIKE '%Z' "
            f"THEN DATETIME(pt.started_at, '+' || pt.duration_seconds || ' seconds', '{mod}') "
            f"ELSE DATETIME(pt.started_at, '+' || pt.duration_seconds || ' seconds') END "
            f"ELSE NULL END"
        )
    rows = conn.execute(
        f"""
        WITH ranges AS (
            SELECT DATE({tz_s}) AS start_date,
                   DATE({local_eff_end}) AS end_date
            FROM print_task pt
            WHERE pt.started_at IS NOT NULL
        )
        SELECT start_date, end_date FROM ranges
        WHERE end_date IS NOT NULL
          AND start_date != end_date
          AND start_date < ?
          AND end_date   >= ?
        ORDER BY start_date
        """,
        (f"{year + 1}-01-01", f"{year}-01-01"),
    ).fetchall()
    return [(r["start_date"], r["end_date"]) for r in rows]


def get_cross_day_tasks_for_date(conn: sqlite3.Connection, date_str: str, tz_offset_minutes: int = 0) -> list:
    """Return tasks that started before date_str (local) but whose print range overlaps date_str.
    Used for timeline display only; excluded from statistics.
    """
    tz_s = _tz_mod("pt.started_at", tz_offset_minutes)
    tz_e = _tz_mod("pt.ended_at", tz_offset_minutes)

    if tz_offset_minutes == 0:
        eff_end_expr = "DATETIME(pt.started_at, '+' || pt.duration_seconds || ' seconds')"
    else:
        mod = f"+{tz_offset_minutes} minutes" if tz_offset_minutes >= 0 else f"{tz_offset_minutes} minutes"
        eff_end_expr = (
            f"CASE WHEN pt.started_at LIKE '%Z' "
            f"THEN DATETIME(pt.started_at, '+' || pt.duration_seconds || ' seconds', '{mod}') "
            f"ELSE DATETIME(pt.started_at, '+' || pt.duration_seconds || ' seconds') END"
        )

    rows = conn.execute(
        f"""
        SELECT pt.*, p.name AS printer_name
        FROM print_task pt LEFT JOIN printer p ON p.id = pt.printer_id
        WHERE pt.started_at IS NOT NULL
          AND DATE({tz_s}) < ?
          AND (
            (pt.ended_at IS NOT NULL AND DATE({tz_e}) >= ?)
            OR (pt.ended_at IS NULL AND pt.duration_seconds > 0 AND DATE({eff_end_expr}) >= ?)
          )
        ORDER BY {tz_s}
        """,
        (date_str, date_str, date_str),
    ).fetchall()
    tasks = []
    for row in rows:
        d = dict(row)
        d["filaments"] = []
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


def _month_start(date_str: str) -> str:
    """'YYYY-MM-DD' -> 'YYYY-MM-01' (該日所屬月份的第一天)。"""
    return date_str[:7] + "-01"


def get_adjacent_task_dates(
    conn: sqlite3.Connection,
    date_str: str,
    tz_offset_minutes: int = 0,
    max_date: str | None = None,
) -> tuple:
    """Return (prev_date, next_date) — 最近一個「有任務於當日開始」的相鄰日期。

    以 started-date 為錨點：這些日期一定含 tasks，day_view 永不 404。
    只有跨日 timeline 覆蓋（當日無任務開始）的日期不納入前後翻頁，
    但仍可從熱力圖進入（day_view 的 404 predicate 為 tasks 與 timeline 皆空）。
    next_date 以 max_date（本地今天）為上限；無相鄰日回 None。
    """
    tz = _tz_mod("started_at", tz_offset_minutes)
    prev_row = conn.execute(
        f"""
        SELECT MAX(DATE({tz})) AS d FROM print_task
        WHERE started_at IS NOT NULL AND DATE({tz}) < ?
        """,
        (date_str,),
    ).fetchone()
    if max_date is not None:
        next_row = conn.execute(
            f"""
            SELECT MIN(DATE({tz})) AS d FROM print_task
            WHERE started_at IS NOT NULL AND DATE({tz}) > ? AND DATE({tz}) <= ?
            """,
            (date_str, max_date),
        ).fetchone()
    else:
        next_row = conn.execute(
            f"""
            SELECT MIN(DATE({tz})) AS d FROM print_task
            WHERE started_at IS NOT NULL AND DATE({tz}) > ?
            """,
            (date_str,),
        ).fetchone()
    return (prev_row["d"], next_row["d"])


def get_month_to_date_stats(
    conn: sqlite3.Connection, date_str: str, tz_offset_minutes: int = 0
) -> dict:
    """月初至 date_str（含）started-date tasks 的 task_count 與 total_weight_g。

    口徑與每日卡片一致（started-date only）。total_weight_g 以「Σ 逐日 round(0.1g)」
    計算——每日卡片顯示的正是逐日四捨五入值，故月摘要嚴格等於各日顯示值之和
    （帳本語意：月結＝各日已記帳值之和，而非原始值一次加總後才進位）。
    """
    tz = _tz_mod("started_at", tz_offset_minutes)
    ms = _month_start(date_str)
    count_row = conn.execute(
        f"""
        SELECT COUNT(*) AS task_count
        FROM print_task
        WHERE started_at IS NOT NULL
          AND DATE({tz}) >= ? AND DATE({tz}) <= ?
        """,
        (ms, date_str),
    ).fetchone()
    weight_row = conn.execute(
        f"""
        SELECT COALESCE(SUM(day_weight), 0.0) AS total_weight_g
        FROM (
            SELECT ROUND(SUM(total_weight_g), 1) AS day_weight
            FROM print_task
            WHERE started_at IS NOT NULL
              AND DATE({tz}) >= ? AND DATE({tz}) <= ?
            GROUP BY DATE({tz})
        )
        """,
        (ms, date_str),
    ).fetchone()
    return {
        "task_count": count_row["task_count"],
        "total_weight_g": weight_row["total_weight_g"],
    }


def get_month_to_date_filament_rows(
    conn: sqlite3.Connection, date_str: str, tz_offset_minutes: int = 0
) -> list:
    """月初至 date_str（含）逐 (日, spool) 的 used_g / price / initial_weight。

    分組粒度與每日 filament summary 相同（day × spool × color × material），
    payload 層對每組套用相同 capped price*min(used/init,1) 再加總，
    結果等於「Σ 每日成本」。
    """
    tz = _tz_mod("pt.started_at", tz_offset_minutes)
    rows = conn.execute(
        f"""
        SELECT DATE({tz}) AS d,
               ptf.filament_spool_id AS spool_id,
               SUM(ptf.used_weight_g) AS used_g,
               fs.price AS price,
               fs.initial_weight_g AS init_g
        FROM print_task_filament ptf
        JOIN print_task pt ON pt.id = ptf.print_task_id
        LEFT JOIN filament_spool fs ON fs.id = ptf.filament_spool_id
        WHERE ptf.is_ignored = 0
          AND DATE({tz}) >= ? AND DATE({tz}) <= ?
        GROUP BY DATE({tz}), ptf.filament_spool_id,
                 COALESCE(fs.color_hex, ptf.color_hex),
                 COALESCE(fs.material, ptf.material)
        """,
        (_month_start(date_str), date_str),
    ).fetchall()
    return [dict(r) for r in rows]
