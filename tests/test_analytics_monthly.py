"""每日頁「本月至今」摘要與前後日翻頁的 helper 測試。

核心不變式：月摘要 = Σ 該月每日 payload（口徑一致，起訖日 started-date only）。
"""
import sqlite3
from datetime import date, timedelta

from src.analytics import get_daily_detail_payload, get_month_to_date_summary
from src.db import (
    get_adjacent_task_dates,
    get_month_to_date_stats,
    insert_print_task_filament,
    insert_spool,
    upsert_print_task,
)


def _task(**overrides: object) -> dict:
    task = {
        "external_id": 1,
        "print_name": "p",
        "printer_id": None,
        "started_at": "2026-03-05T10:00:00Z",
        "ended_at": "2026-03-05T11:00:00Z",
        "duration_seconds": 3600,
        "status": 4,
        "total_weight_g": 100.0,
        "cover_url": None,
        "raw_json": "{}",
        "plate_index": 1,
        "plate_name": "A",
    }
    task.update(overrides)
    return task


def _spool(**overrides: object) -> dict:
    s = {
        "uid": "spool-1",
        "material": "PLA",
        "color_name": "Blue",
        "color_hex": "#0011FF",
        "initial_weight_g": 1000.0,
        "price": 20.0,
        "purchased_at": "2026-01-01",
        "product_url": None,
        "note": None,
    }
    s.update(overrides)
    return s


def _add_task(conn, ext, started_at, weight, spool_id=None, used=None):
    task_id, _ = upsert_print_task(
        conn, _task(external_id=ext, started_at=started_at, total_weight_g=weight)
    )
    if used is not None:
        insert_print_task_filament(
            conn,
            {
                "print_task_id": task_id,
                "filament_spool_id": spool_id,
                "slot_id": 1,
                "used_weight_g": used,
                "color_hex": "#0011FF",
                "material": "PLA",
            },
        )
    return task_id


def _sum_daily(conn, y, m, upto_day):
    """Σ 每日 payload（口徑基準），從月初到 upto_day（含）。"""
    tc = wt = 0
    cost = None
    d = date(y, m, 1)
    while d.day <= upto_day and d.month == m:
        p = get_daily_detail_payload(conn, d.isoformat(), 0)
        tc += p["task_count"]
        wt += p["total_weight_g"]
        if p["total_cost_day"] is not None:
            cost = (cost or 0.0) + p["total_cost_day"]
        d += timedelta(days=1)
    return tc, round(wt, 1), (round(cost, 2) if cost is not None else None)


def test_month_to_date_equals_sum_of_daily(conn: sqlite3.Connection) -> None:
    spool_id = insert_spool(conn, _spool())
    _add_task(conn, 1, "2026-02-28T10:00:00Z", 50.0, spool_id, 50.0)   # 上月，排除
    _add_task(conn, 2, "2026-03-02T10:00:00Z", 100.0, spool_id, 100.0)
    _add_task(conn, 3, "2026-03-05T09:00:00Z", 30.0, spool_id, 30.0)
    _add_task(conn, 4, "2026-03-05T14:00:00Z", 70.0, spool_id, 70.0)   # 同日第二筆
    _add_task(conn, 5, "2026-03-10T10:00:00Z", 40.0, spool_id, 40.0)
    _add_task(conn, 6, "2026-03-20T10:00:00Z", 999.0, spool_id, 999.0)  # 查詢日之後，排除

    summary = get_month_to_date_summary(conn, "2026-03-10", 0)
    tc, wt, cost = _sum_daily(conn, 2026, 3, 10)

    assert summary["year_month"] == "2026-03"
    assert summary["task_count"] == tc == 4
    assert summary["total_weight_g"] == wt == 240.0
    assert summary["total_cost"] == cost


def test_month_to_date_matches_daily_under_weight_rounding(conn: sqlite3.Connection) -> None:
    # 兩天各 0.04g：每日各 round→0.0g，月摘要須為 Σ 逐日 round = 0.0g（非原始 0.08→0.1）
    _add_task(conn, 1, "2026-03-03T10:00:00Z", 0.04)
    _add_task(conn, 2, "2026-03-04T10:00:00Z", 0.04)
    summary = get_month_to_date_summary(conn, "2026-03-10", 0)
    tc, wt, _ = _sum_daily(conn, 2026, 3, 10)
    assert summary["total_weight_g"] == wt == 0.0
    assert summary["task_count"] == tc == 2


def test_month_to_date_matches_daily_under_cost_rounding(conn: sqlite3.Connection) -> None:
    # price*ratio = 8 * (0.5/1000) = 0.004；每日各 round(2)→0.00，月成本須為 Σ 逐日 = 0.00
    spool_id = insert_spool(conn, _spool(price=8.0, initial_weight_g=1000.0))
    _add_task(conn, 1, "2026-03-03T10:00:00Z", 0.5, spool_id, 0.5)
    _add_task(conn, 2, "2026-03-04T10:00:00Z", 0.5, spool_id, 0.5)
    summary = get_month_to_date_summary(conn, "2026-03-10", 0)
    _, _, cost = _sum_daily(conn, 2026, 3, 10)
    assert summary["total_cost"] == cost == 0.0


def test_month_to_date_cost_caps_at_initial_weight(conn: sqlite3.Connection) -> None:
    # used > initial：ratio 上限 1.0，成本 = 整捲價
    spool_id = insert_spool(conn, _spool(price=20.0, initial_weight_g=1000.0))
    _add_task(conn, 1, "2026-03-03T10:00:00Z", 1500.0, spool_id, 1500.0)
    summary = get_month_to_date_summary(conn, "2026-03-10", 0)
    assert summary["total_cost"] == 20.0


def test_month_to_date_negative_tz_excludes_prev_month(conn: sqlite3.Connection) -> None:
    # UTC 03-01 01:00，tz=-120 → local 02-28 23:00，屬 2 月，不計入 3 月至今
    _add_task(conn, 1, "2026-03-01T01:00:00Z", 50.0)
    summary = get_month_to_date_summary(conn, "2026-03-05", -120)
    assert summary["task_count"] == 0
    assert summary["total_weight_g"] == 0.0


def test_month_to_date_stats_month_start_inclusive(conn: sqlite3.Connection) -> None:
    _add_task(conn, 1, "2026-03-01T00:30:00Z", 10.0)
    stats = get_month_to_date_stats(conn, "2026-03-01", 0)
    assert stats["task_count"] == 1
    assert stats["total_weight_g"] == 10.0


def test_month_to_date_cost_none_when_unpriced(conn: sqlite3.Connection) -> None:
    unpriced = insert_spool(conn, _spool(uid="s-np", price=None))
    _add_task(conn, 1, "2026-03-03T10:00:00Z", 50.0, unpriced, 50.0)
    summary = get_month_to_date_summary(conn, "2026-03-10", 0)
    assert summary["task_count"] == 1
    assert summary["total_cost"] is None


def test_adjacent_task_dates_prev_next(conn: sqlite3.Connection) -> None:
    for i, d in enumerate(["2026-02-28", "2026-03-02", "2026-03-05", "2026-03-10", "2026-03-20"]):
        _add_task(conn, i + 1, f"{d}T10:00:00Z", 10.0)

    prev, nxt = get_adjacent_task_dates(conn, "2026-03-05", 0, max_date="2026-04-01")
    assert prev == "2026-03-02"
    assert nxt == "2026-03-10"


def test_adjacent_task_dates_no_prev_at_earliest(conn: sqlite3.Connection) -> None:
    _add_task(conn, 1, "2026-03-05T10:00:00Z", 10.0)
    _add_task(conn, 2, "2026-03-10T10:00:00Z", 10.0)
    prev, nxt = get_adjacent_task_dates(conn, "2026-03-05", 0, max_date="2026-04-01")
    assert prev is None
    assert nxt == "2026-03-10"


def test_adjacent_task_dates_next_capped_at_max_date(conn: sqlite3.Connection) -> None:
    _add_task(conn, 1, "2026-03-05T10:00:00Z", 10.0)
    _add_task(conn, 2, "2026-03-20T10:00:00Z", 10.0)
    # max_date（本地今天）早於 03-20，故無 next
    prev, nxt = get_adjacent_task_dates(conn, "2026-03-10", 0, max_date="2026-03-15")
    assert prev == "2026-03-05"
    assert nxt is None


def test_adjacent_task_dates_cross_month(conn: sqlite3.Connection) -> None:
    _add_task(conn, 1, "2026-02-27T10:00:00Z", 10.0)
    _add_task(conn, 2, "2026-03-03T10:00:00Z", 10.0)
    prev, nxt = get_adjacent_task_dates(conn, "2026-03-01", 0, max_date="2026-04-01")
    assert prev == "2026-02-27"
    assert nxt == "2026-03-03"
