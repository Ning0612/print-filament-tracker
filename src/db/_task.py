import sqlite3
import time

# RGB Euclidean distance squared threshold for automatic filament color matching.
# 8100 = 90^2 means each channel can differ by up to ~52 out of 255.
_COLOR_DIST_THRESHOLD_SQ = 90 * 90


def upsert_print_task(conn: sqlite3.Connection, task: dict) -> tuple[int, bool]:
    """Insert or update a cloud print task. Returns (task_db_id, is_new).

    Mutable fields (ended_at, duration_seconds, status, total_weight_g,
    raw_json, print_name, plate_index, plate_name) are updated when a record
    already exists. COALESCE ensures existing non-NULL values are never
    overwritten by NULL — this protects completed records from partial
    in-progress snapshots. cover_url uses reverse COALESCE (keep existing)
    so user-uploaded covers are never replaced by auto-downloaded paths.
    """
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO print_task
          (external_id, print_name, printer_id, started_at, ended_at,
           duration_seconds, status, total_weight_g, cover_url, raw_json,
           plate_index, plate_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task["external_id"],
            task.get("print_name"),
            task.get("printer_id"),
            task.get("started_at"),
            task.get("ended_at"),
            task.get("duration_seconds"),
            task.get("status"),
            task.get("total_weight_g"),
            task.get("cover_url"),
            task.get("raw_json"),
            task.get("plate_index"),
            task.get("plate_name"),
        ),
    )
    if cursor.rowcount > 0:
        return cursor.lastrowid, True

    # Row already exists — update mutable cloud-authoritative fields.
    # COALESCE(incoming, existing) means: only overwrite if incoming is non-NULL.
    conn.execute(
        """
        UPDATE print_task SET
          ended_at         = COALESCE(?, ended_at),
          duration_seconds = COALESCE(?, duration_seconds),
          status           = COALESCE(?, status),
          total_weight_g   = COALESCE(?, total_weight_g),
          raw_json         = ?,
          print_name       = COALESCE(?, print_name),
          plate_index      = COALESCE(?, plate_index),
          plate_name       = COALESCE(?, plate_name),
          cover_url        = COALESCE(cover_url, ?)
        WHERE external_id = ? AND is_manual = 0
        """,
        (
            task.get("ended_at"),
            task.get("duration_seconds"),
            task.get("status"),
            task.get("total_weight_g"),
            task.get("raw_json"),
            task.get("print_name"),
            task.get("plate_index"),
            task.get("plate_name"),
            task.get("cover_url"),
            task["external_id"],
        ),
    )
    row = conn.execute(
        "SELECT id FROM print_task WHERE external_id = ?", (task["external_id"],)
    ).fetchone()
    return row["id"], False


def _hex_color_distance(left: str | None, right: str | None) -> int | None:
    if not left or not right:
        return None
    left = left.lstrip("#")
    right = right.lstrip("#")
    if len(left) != 6 or len(right) != 6:
        return None
    try:
        l_rgb = tuple(int(left[i:i + 2], 16) for i in (0, 2, 4))
        r_rgb = tuple(int(right[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None
    return sum((a - b) ** 2 for a, b in zip(l_rgb, r_rgb))


def sync_task_filaments(conn: sqlite3.Connection, print_task_id: int, rows: list[dict]) -> int:
    """Synchronize all cloud filament rows for a task while preserving mappings.

    Bambu Cloud can report several colors with the same slot_id for one plate.
    Matching rows one by one by slot_id would update the same database row
    repeatedly, corrupting color/weight data. Batch matching lets existing
    spool mappings win by color proximity first, then falls back to exact
    color/material and row order for remaining duplicate-slot rows.
    """
    existing = conn.execute(
        """
        SELECT ptf.id, ptf.slot_id, ptf.used_weight_g, ptf.color_hex, ptf.material,
               ptf.filament_spool_id, ptf.is_ignored,
               fs.color_hex AS spool_color_hex
        FROM print_task_filament ptf
        LEFT JOIN filament_spool fs ON fs.id = ptf.filament_spool_id
        WHERE ptf.print_task_id = ?
        ORDER BY
          CASE WHEN ptf.slot_id IS NULL THEN 1 ELSE 0 END,
          ptf.slot_id,
          ptf.id
        """,
        (print_task_id,),
    ).fetchall()

    matched_existing: set[int] = set()
    assignments: list[tuple[dict, sqlite3.Row | None]] = []

    for row in rows:
        match = None
        closest_distance = None
        for candidate in existing:
            if candidate["id"] in matched_existing:
                continue
            if candidate["slot_id"] != row.get("slot_id"):
                continue
            if candidate["material"] != row.get("material"):
                continue
            distance = _hex_color_distance(
                candidate["spool_color_hex"],
                row.get("color_hex"),
            )
            if distance is None or distance > _COLOR_DIST_THRESHOLD_SQ:
                continue
            if closest_distance is None or distance < closest_distance:
                match = candidate
                closest_distance = distance
        if match is not None:
            matched_existing.add(match["id"])
            assignments.append((row, match))
            continue

        for candidate in existing:
            if candidate["id"] in matched_existing:
                continue
            if candidate["slot_id"] != row.get("slot_id"):
                continue
            if candidate["color_hex"] != row.get("color_hex"):
                continue
            if candidate["material"] != row.get("material"):
                continue
            match = candidate
            break
        if match is not None:
            matched_existing.add(match["id"])
        assignments.append((row, match))

    unmatched_by_slot: dict[int | None, list[sqlite3.Row]] = {}
    for candidate in existing:
        if candidate["id"] in matched_existing:
            continue
        unmatched_by_slot.setdefault(candidate["slot_id"], []).append(candidate)

    inserted_count = 0
    for idx, (row, match) in enumerate(assignments):
        if match is None:
            candidates = unmatched_by_slot.get(row.get("slot_id"), [])
            if candidates:
                match = candidates.pop(0)
                matched_existing.add(match["id"])
                assignments[idx] = (row, match)

        if match is None:
            insert_print_task_filament(conn, row)
            inserted_count += 1
            continue

        conn.execute(
            """
            UPDATE print_task_filament SET
              used_weight_g = COALESCE(?, used_weight_g),
              color_hex     = COALESCE(?, color_hex),
              material      = COALESCE(?, material)
            WHERE id = ?
            """,
            (
                row.get("used_weight_g"),
                row.get("color_hex"),
                row.get("material"),
                match["id"],
            ),
        )

    return inserted_count


def delete_unmapped_null_slot_ptf(conn: sqlite3.Connection, print_task_id: int) -> int:
    """Remove the NULL-slot fallback PTF row if the task now has real slot data.

    When a print is synced mid-job, amsDetailMapping may be empty, creating a
    single row with slot_id=NULL. After the print completes, real slot rows are
    inserted. The stale NULL-slot row should be cleaned up — but only if it
    has no user mapping (filament_spool_id IS NULL) so we never destroy
    mappings the user already confirmed.
    """
    cursor = conn.execute(
        """
        DELETE FROM print_task_filament
        WHERE print_task_id = ? AND slot_id IS NULL AND filament_spool_id IS NULL
        """,
        (print_task_id,),
    )
    return cursor.rowcount


def insert_print_task_filament(conn: sqlite3.Connection, ptf: dict) -> None:
    conn.execute(
        """
        INSERT INTO print_task_filament
          (print_task_id, filament_spool_id, slot_id, used_weight_g, color_hex, material)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            ptf["print_task_id"],
            ptf.get("filament_spool_id"),
            ptf.get("slot_id"),
            ptf.get("used_weight_g"),
            ptf.get("color_hex"),
            ptf.get("material"),
        ),
    )


def update_task_cover_if_null(conn: sqlite3.Connection, external_id: int, cover_url: str) -> bool:
    cursor = conn.execute(
        "UPDATE print_task SET cover_url=? WHERE external_id=? AND cover_url IS NULL",
        (cover_url, external_id),
    )
    return cursor.rowcount > 0


def get_tasks_page(conn: sqlite3.Connection, page: int, per_page: int, search: str = "") -> tuple:
    offset = (page - 1) * per_page
    if search:
        like = f"%{search}%"
        rows = conn.execute(
            """
            SELECT pt.*, p.name AS printer_name
            FROM print_task pt LEFT JOIN printer p ON p.id = pt.printer_id
            WHERE pt.print_name LIKE ?
            ORDER BY pt.started_at DESC LIMIT ? OFFSET ?
            """,
            (like, per_page, offset),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM print_task WHERE print_name LIKE ?", (like,)
        ).fetchone()[0]
    else:
        rows = conn.execute(
            """
            SELECT pt.*, p.name AS printer_name
            FROM print_task pt LEFT JOIN printer p ON p.id = pt.printer_id
            ORDER BY pt.started_at DESC LIMIT ? OFFSET ?
            """,
            (per_page, offset),
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM print_task").fetchone()[0]
    return [dict(r) for r in rows], total


def get_task_with_filaments(conn: sqlite3.Connection, task_id: int) -> dict | None:
    task = conn.execute(
        """
        SELECT pt.*, p.name AS printer_name
        FROM print_task pt LEFT JOIN printer p ON p.id = pt.printer_id
        WHERE pt.id = ?
        """,
        (task_id,),
    ).fetchone()
    if not task:
        return None
    d = dict(task)
    filaments = conn.execute(
        """
        SELECT ptf.*, fs.color_name, fs.uid AS spool_uid
        FROM print_task_filament ptf
        LEFT JOIN filament_spool fs ON fs.id = ptf.filament_spool_id
        WHERE ptf.print_task_id = ?
        ORDER BY ptf.slot_id
        """,
        (task_id,),
    ).fetchall()
    d["filaments"] = [dict(f) for f in filaments]
    return d


def get_recent_tasks(conn: sqlite3.Connection, limit: int = 10) -> list:
    rows = conn.execute(
        """
        SELECT pt.*, p.name AS printer_name
        FROM print_task pt LEFT JOIN printer p ON p.id = pt.printer_id
        ORDER BY pt.started_at DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def insert_manual_task(conn: sqlite3.Connection, task: dict) -> int:
    # Use negative nanosecond timestamp as a unique external_id that never
    # conflicts with positive Bambu Cloud IDs.
    external_id = -time.time_ns()
    cursor = conn.execute(
        """
        INSERT INTO print_task
          (external_id, print_name, printer_id, started_at, ended_at,
           duration_seconds, total_weight_g, is_manual)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            external_id,
            task.get("print_name"),
            task.get("printer_id"),
            task.get("started_at"),
            task.get("ended_at"),
            task.get("duration_seconds"),
            task.get("total_weight_g"),
        ),
    )
    return cursor.lastrowid


def update_manual_task(conn: sqlite3.Connection, task_id: int, task: dict) -> bool:
    cursor = conn.execute(
        """
        UPDATE print_task SET
          print_name=?, printer_id=?, started_at=?, ended_at=?,
          duration_seconds=?, total_weight_g=?, cover_url=?
        WHERE id=? AND is_manual=1
        """,
        (
            task.get("print_name"),
            task.get("printer_id"),
            task.get("started_at"),
            task.get("ended_at"),
            task.get("duration_seconds"),
            task.get("total_weight_g"),
            task.get("cover_url"),
            task_id,
        ),
    )
    return cursor.rowcount > 0


def update_task_cover_url(conn: sqlite3.Connection, task_id: int, cover_url: "str | None") -> None:
    conn.execute(
        "UPDATE print_task SET cover_url=? WHERE id=?", (cover_url, task_id)
    )


def delete_manual_task(conn: sqlite3.Connection, task_id: int) -> bool:
    # Check is_manual BEFORE touching filaments — prevents accidental data
    # loss if a non-manual task_id is submitted.
    row = conn.execute(
        "SELECT id FROM print_task WHERE id=? AND is_manual=1", (task_id,)
    ).fetchone()
    if row is None:
        return False
    conn.execute(
        "DELETE FROM print_task_filament WHERE print_task_id=?", (task_id,)
    )
    conn.execute("DELETE FROM print_task WHERE id=?", (task_id,))
    return True


def replace_task_filaments(conn: sqlite3.Connection, task_id: int, filaments: list[dict]) -> None:
    conn.execute("SAVEPOINT replace_filaments")
    try:
        conn.execute(
            "DELETE FROM print_task_filament WHERE print_task_id=?", (task_id,)
        )
        for f in filaments:
            conn.execute(
                """
                INSERT INTO print_task_filament
                  (print_task_id, filament_spool_id, slot_id, used_weight_g, color_hex, material)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    f.get("filament_spool_id"),
                    f.get("slot_id"),
                    f.get("used_weight_g"),
                    f.get("color_hex"),
                    f.get("material"),
                ),
            )
        conn.execute("RELEASE SAVEPOINT replace_filaments")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT replace_filaments")
        raise
