import sqlite3

from src.db import (
    delete_manual_task,
    get_cost_breakdown,
    get_heatmap_available_years,
    get_spool_used_weight,
    insert_manual_task,
    insert_print_task_filament,
    insert_spool,
    map_filament_to_spool,
    sync_task_filaments,
    upsert_print_task,
)


def _cloud_task(**overrides: object) -> dict:
    task = {
        "external_id": 1001,
        "print_name": "First print",
        "printer_id": None,
        "started_at": "2026-01-02T03:04:05Z",
        "ended_at": "2026-01-02T04:04:05Z",
        "duration_seconds": 3600,
        "status": 4,
        "total_weight_g": 18.5,
        "cover_url": "/covers/first.png",
        "raw_json": "{}",
        "plate_index": 1,
        "plate_name": "Plate A",
    }
    task.update(overrides)
    return task


def _spool(**overrides: object) -> dict:
    spool = {
        "uid": "spool-001",
        "material": "PLA",
        "color_name": "Blue",
        "color_hex": "#0011FF",
        "initial_weight_g": 1000.0,
        "price": 20.0,
        "purchased_at": "2026-01-01",
        "product_url": None,
        "note": None,
    }
    spool.update(overrides)
    return spool


def test_upsert_print_task_preserves_existing_non_null_values(conn: sqlite3.Connection) -> None:
    task_id, is_new = upsert_print_task(conn, _cloud_task())
    assert is_new is True

    same_id, is_new = upsert_print_task(
        conn,
        _cloud_task(
            print_name=None,
            ended_at=None,
            duration_seconds=None,
            status=None,
            total_weight_g=None,
            cover_url="/covers/replacement.png",
            raw_json='{"partial": true}',
            plate_index=None,
            plate_name=None,
        ),
    )

    row = conn.execute("SELECT * FROM print_task WHERE id=?", (task_id,)).fetchone()
    assert same_id == task_id
    assert is_new is False
    assert row["print_name"] == "First print"
    assert row["ended_at"] == "2026-01-02T04:04:05Z"
    assert row["duration_seconds"] == 3600
    assert row["status"] == 4
    assert row["total_weight_g"] == 18.5
    assert row["cover_url"] == "/covers/first.png"
    assert row["raw_json"] == '{"partial": true}'


def test_sync_task_filaments_preserves_spool_mapping_for_duplicate_slots(
    conn: sqlite3.Connection,
) -> None:
    task_id, _ = upsert_print_task(conn, _cloud_task())
    blue_spool_id = insert_spool(conn, _spool())
    red_spool_id = insert_spool(
        conn,
        _spool(
            uid="spool-002",
            color_name="Red",
            color_hex="#FF1100",
            price=25.0,
        ),
    )
    insert_print_task_filament(
        conn,
        {
            "print_task_id": task_id,
            "filament_spool_id": blue_spool_id,
            "slot_id": 1,
            "used_weight_g": 1.0,
            "color_hex": "#0011FF",
            "material": "PLA",
        },
    )
    insert_print_task_filament(
        conn,
        {
            "print_task_id": task_id,
            "filament_spool_id": red_spool_id,
            "slot_id": 1,
            "used_weight_g": 1.0,
            "color_hex": "#FF1100",
            "material": "PLA",
        },
    )

    inserted = sync_task_filaments(
        conn,
        task_id,
        [
            {
                "print_task_id": task_id,
                "slot_id": 1,
                "used_weight_g": 9.0,
                "color_hex": "#FF1000",
                "material": "PLA",
            },
            {
                "print_task_id": task_id,
                "slot_id": 1,
                "used_weight_g": 7.5,
                "color_hex": "#0010FE",
                "material": "PLA",
            },
        ],
    )

    rows = conn.execute(
        """
        SELECT filament_spool_id, used_weight_g
        FROM print_task_filament
        WHERE print_task_id=?
        ORDER BY filament_spool_id
        """,
        (task_id,),
    ).fetchall()
    assert inserted == 0
    assert [(row["filament_spool_id"], row["used_weight_g"]) for row in rows] == [
        (blue_spool_id, 7.5),
        (red_spool_id, 9.0),
    ]


def test_filament_usage_and_cost_breakdown(conn: sqlite3.Connection) -> None:
    task_id, _ = upsert_print_task(conn, _cloud_task())
    spool_id = insert_spool(conn, _spool(initial_weight_g=100.0, price=30.0))
    insert_print_task_filament(
        conn,
        {
            "print_task_id": task_id,
            "slot_id": 0,
            "used_weight_g": 25.0,
            "color_hex": "#0011FF",
            "material": "PLA",
        },
    )
    ptf_id = conn.execute("SELECT id FROM print_task_filament").fetchone()["id"]
    map_filament_to_spool(conn, ptf_id, spool_id)

    assert get_spool_used_weight(conn, spool_id) == 25.0
    assert get_cost_breakdown(conn) == {
        "known_used": 7.5,
        "known_remaining": 22.5,
        "known_total": 30.0,
        "unpriced_count": 0,
        "unpriced_initial_g": 0.0,
        "priced_spool_count": 1,
    }


def test_manual_task_delete_does_not_delete_cloud_task(conn: sqlite3.Connection) -> None:
    cloud_task_id, _ = upsert_print_task(conn, _cloud_task())
    manual_task_id = insert_manual_task(
        conn,
        {
            "print_name": "Manual print",
            "started_at": "2026-02-03T01:00:00",
            "ended_at": "2026-02-03T02:00:00",
            "duration_seconds": 3600,
            "total_weight_g": 10.0,
        },
    )
    insert_print_task_filament(
        conn,
        {
            "print_task_id": manual_task_id,
            "slot_id": None,
            "used_weight_g": 10.0,
            "color_hex": "#FFFFFF",
            "material": "PLA",
        },
    )

    assert delete_manual_task(conn, cloud_task_id) is False
    assert delete_manual_task(conn, manual_task_id) is True
    assert conn.execute("SELECT COUNT(*) FROM print_task").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM print_task_filament").fetchone()[0] == 0


def test_heatmap_years_apply_timezone_offset_to_cloud_tasks(
    conn: sqlite3.Connection,
) -> None:
    upsert_print_task(
        conn,
        _cloud_task(
            external_id=2002,
            started_at="2025-12-31T16:30:00Z",
            ended_at=None,
            duration_seconds=None,
        ),
    )

    assert get_heatmap_available_years(conn, tz_offset_minutes=0) == [2025]
    assert get_heatmap_available_years(conn, tz_offset_minutes=480) == [2026]
