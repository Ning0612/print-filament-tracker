import sqlite3

from ._connection import DatabaseError


def upsert_printer(conn: sqlite3.Connection, device_id: str, name: str, model: str | None) -> int:
    conn.execute(
        "INSERT OR IGNORE INTO printer (name, device_id, model) VALUES (?, ?, ?)",
        (name, device_id, model),
    )
    row = conn.execute(
        "SELECT id FROM printer WHERE device_id = ?", (device_id,)
    ).fetchone()
    if row is not None:
        return row["id"]
    # INSERT was ignored due to name collision with a different device_id.
    # Disambiguate name and insert again.
    unique_name = f"{name} ({device_id})"
    conn.execute(
        "INSERT OR IGNORE INTO printer (name, device_id, model) VALUES (?, ?, ?)",
        (unique_name, device_id, model),
    )
    row = conn.execute(
        "SELECT id FROM printer WHERE device_id = ?", (device_id,)
    ).fetchone()
    if row is None:
        raise DatabaseError(f"無法建立或找到 printer（device_id={device_id}）。")
    return row["id"]


def get_printer_id_by_device_id(conn: sqlite3.Connection, device_id: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM printer WHERE device_id = ?", (device_id,)
    ).fetchone()
    return row["id"] if row else None


def get_all_printers(conn: sqlite3.Connection) -> list:
    return conn.execute(
        "SELECT id, name FROM printer ORDER BY name"
    ).fetchall()


def get_printer_by_id(conn: sqlite3.Connection, printer_id: int):
    return conn.execute(
        "SELECT * FROM printer WHERE id=?", (printer_id,)
    ).fetchone()


def get_all_printers_full(conn: sqlite3.Connection) -> list:
    return conn.execute("SELECT * FROM printer ORDER BY name").fetchall()


def insert_printer(conn: sqlite3.Connection, data: dict) -> int:
    cur = conn.execute(
        "INSERT INTO printer (name, device_id, model, purchased_at, image_url, note) VALUES (?,?,?,?,?,?)",
        (data["name"], data.get("device_id"), data.get("model"),
         data.get("purchased_at"), data.get("image_url"), data.get("note")),
    )
    return cur.lastrowid


def update_printer(conn: sqlite3.Connection, printer_id: int, data: dict) -> None:
    conn.execute(
        "UPDATE printer SET name=?, device_id=?, model=?, purchased_at=?, image_url=?, note=? WHERE id=?",
        (data["name"], data.get("device_id"), data.get("model"),
         data.get("purchased_at"), data.get("image_url"), data.get("note"), printer_id),
    )


def update_printer_image_url(conn: sqlite3.Connection, printer_id: int, image_url: "str | None") -> None:
    conn.execute("UPDATE printer SET image_url=? WHERE id=?", (image_url, printer_id))


def delete_printer_record(conn: sqlite3.Connection, printer_id: int) -> None:
    conn.execute("UPDATE print_task SET printer_id=NULL WHERE printer_id=?", (printer_id,))
    conn.execute("DELETE FROM printer WHERE id=?", (printer_id,))


def get_printer_stats_all(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        """
        SELECT p.id,
               COUNT(pt.id) AS task_count,
               COALESCE(SUM(pt.duration_seconds), 0) AS total_duration_seconds,
               COALESCE(SUM(pt.total_weight_g), 0.0) AS total_weight_g
        FROM printer p
        LEFT JOIN print_task pt ON pt.printer_id = p.id
        GROUP BY p.id
        """
    ).fetchall()
    return {r["id"]: dict(r) for r in rows}


def get_existing_device_ids(conn: sqlite3.Connection) -> list:
    rows = conn.execute(
        "SELECT device_id FROM printer WHERE device_id IS NOT NULL ORDER BY device_id"
    ).fetchall()
    return [r["device_id"] for r in rows]
