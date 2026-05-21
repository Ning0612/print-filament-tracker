import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

DB_FILENAME = "tracker.db"

# RGB Euclidean distance squared threshold for automatic filament color matching.
# 8100 = 90^2 means each channel can differ by up to ~52 out of 255.
_COLOR_DIST_THRESHOLD_SQ = 90 * 90

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS printer (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  device_id TEXT UNIQUE,
  model TEXT,
  purchased_at DATETIME,
  image_url TEXT,
  note TEXT
);

CREATE TABLE IF NOT EXISTS filament_spool (
  id INTEGER PRIMARY KEY,
  uid TEXT UNIQUE NOT NULL,
  material TEXT,
  color_name TEXT,
  color_hex TEXT,
  initial_weight_g REAL NOT NULL,
  price REAL,
  purchased_at DATETIME,
  opened_at DATETIME,
  product_url TEXT,
  note TEXT
);

CREATE TABLE IF NOT EXISTS print_task (
  id INTEGER PRIMARY KEY,
  external_id INTEGER UNIQUE NOT NULL,
  print_name TEXT,
  printer_id INTEGER,
  started_at DATETIME,
  ended_at DATETIME,
  duration_seconds INTEGER,
  status INTEGER,
  total_weight_g REAL,
  cover_url TEXT,
  raw_json TEXT,
  is_manual INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS print_task_filament (
  id INTEGER PRIMARY KEY,
  print_task_id INTEGER NOT NULL,
  filament_spool_id INTEGER NULL,
  slot_id INTEGER,
  used_weight_g REAL,
  color_hex TEXT,
  material TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_print_task_external_id
  ON print_task(external_id);

CREATE INDEX IF NOT EXISTS idx_ptf_spool
  ON print_task_filament(filament_spool_id);

CREATE INDEX IF NOT EXISTS idx_ptf_task
  ON print_task_filament(print_task_id);

CREATE TABLE IF NOT EXISTS app_config (
  key   TEXT PRIMARY KEY NOT NULL,
  value TEXT NOT NULL
);
"""


class DatabaseError(Exception):
    pass


# ── Schema & Migration ──────────────────────────────────────────────────────


def get_db_path(output_dir: Path) -> Path:
    return output_dir / DB_FILENAME


def _migrate_add_column(conn: sqlite3.Connection, table: str, column_def: str) -> None:
    col_name = column_def.split()[0]
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
        conn.commit()
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise


def init_db(db_path: Path) -> None:
    old_db = db_path.parent / "bambu.db"
    if old_db.exists() and not db_path.exists():
        try:
            old_db.rename(db_path)
        except OSError as exc:
            logger.warning("無法自動遷移 bambu.db → tracker.db：%s，請手動重新命名後重啟。", exc)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        # Production pragmas: WAL for concurrent read/write, busy timeout to
        # prevent "database is locked" when sync and web requests overlap.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executescript(_SCHEMA_SQL)
        _migrate_add_column(conn, "print_task", "cover_url TEXT")
        _migrate_add_column(conn, "print_task", "is_manual INTEGER NOT NULL DEFAULT 0")
        _migrate_add_column(conn, "print_task", "plate_index INTEGER")
        _migrate_add_column(conn, "print_task", "plate_name TEXT")
        _migrate_add_column(conn, "print_task", "status INTEGER")
        _migrate_add_column(conn, "print_task_filament", "is_ignored INTEGER NOT NULL DEFAULT 0")
        _migrate_add_column(conn, "print_task_filament", "mapped_at DATETIME")
        _migrate_add_column(conn, "printer", "image_url TEXT")
        try:
            conn.execute(
                """
                UPDATE print_task
                SET status = json_extract(raw_json, '$.status')
                WHERE status IS NULL AND raw_json IS NOT NULL AND is_manual = 0
                """
            )
            conn.execute(
                """
                UPDATE print_task
                SET plate_index = json_extract(raw_json, '$.plateIndex'),
                    plate_name  = NULLIF(TRIM(json_extract(raw_json, '$.plateName')), '')
                WHERE raw_json IS NOT NULL AND is_manual = 0
                """
            )
            conn.execute(
                """
                UPDATE print_task
                SET print_name = COALESCE(
                    NULLIF(TRIM(json_extract(raw_json, '$.designTitle')), ''),
                    NULLIF(TRIM(json_extract(raw_json, '$.title')),       ''),
                    NULLIF(TRIM(json_extract(raw_json, '$.name')),        ''),
                    print_name
                )
                WHERE raw_json IS NOT NULL AND is_manual = 0
                """
            )
            conn.commit()
        except Exception as exc:
            logger.warning("欄位回填失敗，已略過：%s", exc)
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_print_task_started_at ON print_task(started_at);
            CREATE INDEX IF NOT EXISTS idx_print_task_printer ON print_task(printer_id);
        """)


# ── Connection & App Config ─────────────────────────────────────────────────


def get_app_config(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_config WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_app_config(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_config (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


@contextmanager
def get_connection(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Printer CRUD ────────────────────────────────────────────────────────────

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


# ── Print Task CRUD ─────────────────────────────────────────────────────────

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


# ── Filament Spool CRUD ─────────────────────────────────────────────────────

def insert_spool(conn: sqlite3.Connection, spool: dict) -> int:
    cursor = conn.execute(
        """
        INSERT INTO filament_spool
          (uid, material, color_name, color_hex, initial_weight_g,
           price, purchased_at, product_url, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            spool["uid"],
            spool.get("material"),
            spool.get("color_name"),
            spool.get("color_hex"),
            spool["initial_weight_g"],
            spool.get("price"),
            spool.get("purchased_at"),
            spool.get("product_url"),
            spool.get("note"),
        ),
    )
    return cursor.lastrowid


def update_spool(conn: sqlite3.Connection, spool_id: int, spool: dict) -> None:
    conn.execute(
        """
        UPDATE filament_spool SET
          material=?, color_name=?, color_hex=?, initial_weight_g=?,
          price=?, purchased_at=?, product_url=?, note=?
        WHERE id=?
        """,
        (
            spool.get("material"),
            spool.get("color_name"),
            spool.get("color_hex"),
            spool["initial_weight_g"],
            spool.get("price"),
            spool.get("purchased_at"),
            spool.get("product_url"),
            spool.get("note"),
            spool_id,
        ),
    )


def delete_spool(conn: sqlite3.Connection, spool_id: int) -> None:
    conn.execute(
        "UPDATE print_task_filament SET filament_spool_id=NULL WHERE filament_spool_id=?",
        (spool_id,),
    )
    conn.execute("DELETE FROM filament_spool WHERE id=?", (spool_id,))


def get_all_spools(conn: sqlite3.Connection) -> list:
    return conn.execute("SELECT * FROM filament_spool ORDER BY id").fetchall()


def get_spool_by_id(conn: sqlite3.Connection, spool_id: int):
    return conn.execute(
        "SELECT * FROM filament_spool WHERE id=?", (spool_id,)
    ).fetchone()


def get_spool_used_weight(conn: sqlite3.Connection, spool_id: int) -> float:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(used_weight_g), 0.0) AS total
        FROM print_task_filament
        WHERE filament_spool_id=?
        """,
        (spool_id,),
    ).fetchone()
    return row["total"]


# --- Unmapped queries ---

def get_unmapped_filaments(conn: sqlite3.Connection) -> list:
    return conn.execute(
        """
        SELECT
          ptf.id, ptf.print_task_id, ptf.slot_id,
          ptf.used_weight_g, ptf.color_hex, ptf.material,
          pt.print_name, pt.started_at, pt.external_id, pt.cover_url,
          pt.status, pt.is_manual
        FROM print_task_filament ptf
        JOIN print_task pt ON pt.id = ptf.print_task_id
        WHERE ptf.filament_spool_id IS NULL AND ptf.is_ignored = 0
        ORDER BY pt.started_at DESC
        """
    ).fetchall()


def get_ignored_filaments(conn: sqlite3.Connection) -> list:
    return conn.execute(
        """
        SELECT
          ptf.id, ptf.print_task_id, ptf.slot_id,
          ptf.used_weight_g, ptf.color_hex, ptf.material,
          pt.print_name, pt.started_at, pt.external_id, pt.cover_url,
          pt.status, pt.is_manual
        FROM print_task_filament ptf
        JOIN print_task pt ON pt.id = ptf.print_task_id
        WHERE ptf.filament_spool_id IS NULL AND ptf.is_ignored = 1
        ORDER BY pt.started_at DESC
        """
    ).fetchall()


def ignore_filament(conn: sqlite3.Connection, ptf_id: int) -> None:
    cursor = conn.execute(
        "UPDATE print_task_filament SET is_ignored=1 WHERE id=? AND filament_spool_id IS NULL AND is_ignored=0",
        (ptf_id,),
    )
    if cursor.rowcount == 0:
        raise DatabaseError(f"print_task_filament id={ptf_id} 不存在、已對照或已忽略。")


def unignore_filament(conn: sqlite3.Connection, ptf_id: int) -> None:
    cursor = conn.execute(
        "UPDATE print_task_filament SET is_ignored=0 WHERE id=? AND is_ignored=1",
        (ptf_id,),
    )
    if cursor.rowcount == 0:
        raise DatabaseError(f"print_task_filament id={ptf_id} 不存在或未被忽略。")


def update_task_cover_if_null(conn: sqlite3.Connection, external_id: int, cover_url: str) -> bool:
    cursor = conn.execute(
        "UPDATE print_task SET cover_url=? WHERE external_id=? AND cover_url IS NULL",
        (cover_url, external_id),
    )
    return cursor.rowcount > 0


def get_ptf_by_id(conn: sqlite3.Connection, ptf_id: int):
    return conn.execute(
        "SELECT id FROM print_task_filament WHERE id=?", (ptf_id,)
    ).fetchone()


def get_ptf_row_with_spool(conn: sqlite3.Connection, ptf_id: int):
    return conn.execute(
        """
        SELECT ptf.id, ptf.slot_id, ptf.material, ptf.color_hex,
               ptf.used_weight_g, ptf.filament_spool_id,
               fs.color_name
        FROM print_task_filament ptf
        LEFT JOIN filament_spool fs ON fs.id = ptf.filament_spool_id
        WHERE ptf.id = ?
        """,
        (ptf_id,),
    ).fetchone()


def get_ptf_material(conn: sqlite3.Connection, ptf_id: int):
    return conn.execute(
        "SELECT material FROM print_task_filament WHERE id=?", (ptf_id,)
    ).fetchone()


def get_spool_last_used_map(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        """
        SELECT filament_spool_id, MAX(mapped_at) AS last_used_at
        FROM print_task_filament
        WHERE filament_spool_id IS NOT NULL AND mapped_at IS NOT NULL
        GROUP BY filament_spool_id
        """
    ).fetchall()
    return {r["filament_spool_id"]: r["last_used_at"] for r in rows}


def get_mapped_filaments(conn: sqlite3.Connection) -> list:
    return conn.execute(
        """
        SELECT
          ptf.id, ptf.print_task_id, ptf.slot_id,
          ptf.used_weight_g, ptf.color_hex, ptf.material,
          ptf.filament_spool_id,
          pt.print_name, pt.started_at, pt.cover_url,
          pt.status, pt.is_manual,
          fs.color_name AS spool_color_name,
          fs.color_hex AS spool_color_hex,
          fs.material AS spool_material,
          fs.initial_weight_g AS spool_initial_weight_g
        FROM print_task_filament ptf
        JOIN print_task pt ON pt.id = ptf.print_task_id
        JOIN filament_spool fs ON fs.id = ptf.filament_spool_id
        WHERE ptf.filament_spool_id IS NOT NULL
        ORDER BY pt.started_at DESC
        """
    ).fetchall()


def update_ptf_material(conn: sqlite3.Connection, ptf_id: int, material) -> int:
    cursor = conn.execute(
        "UPDATE print_task_filament SET material=? WHERE id=? AND filament_spool_id IS NULL",
        (material, ptf_id),
    )
    return cursor.rowcount


def get_mapped_filament_by_id(conn: sqlite3.Connection, ptf_id: int):
    return conn.execute(
        """
        SELECT
          ptf.id, ptf.print_task_id, ptf.slot_id,
          ptf.used_weight_g, ptf.color_hex, ptf.material,
          ptf.filament_spool_id,
          pt.print_name, pt.started_at, pt.cover_url,
          pt.status, pt.is_manual,
          fs.color_name AS spool_color_name,
          fs.color_hex AS spool_color_hex,
          fs.material AS spool_material
        FROM print_task_filament ptf
        JOIN print_task pt ON pt.id = ptf.print_task_id
        JOIN filament_spool fs ON fs.id = ptf.filament_spool_id
        WHERE ptf.id = ? AND ptf.filament_spool_id IS NOT NULL
        """,
        (ptf_id,),
    ).fetchone()


def unmap_filament(conn: sqlite3.Connection, ptf_id: int) -> None:
    cursor = conn.execute(
        "UPDATE print_task_filament SET filament_spool_id=NULL WHERE id=? AND filament_spool_id IS NOT NULL",
        (ptf_id,),
    )
    if cursor.rowcount == 0:
        raise DatabaseError(f"print_task_filament id={ptf_id} 不存在或已是未對照狀態。")


# ── Mapping & PTF Operations ────────────────────────────────────────────────


def map_filament_to_spool(conn: sqlite3.Connection, ptf_id: int, spool_id: int) -> None:
    cursor = conn.execute(
        "UPDATE print_task_filament SET filament_spool_id=?, is_ignored=0, mapped_at=CURRENT_TIMESTAMP WHERE id=?",
        (spool_id, ptf_id),
    )
    if cursor.rowcount == 0:
        raise DatabaseError(f"print_task_filament id={ptf_id} 不存在或更新失敗。")


# --- Web query helpers ---

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


# --- Manual task CRUD ---

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


def update_task_cover_url(conn: sqlite3.Connection, task_id: int, cover_url: str | None) -> None:
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


def get_all_mappings_for_export(conn: sqlite3.Connection) -> list:
    """Fetch all mapped/ignored ptf records using stable cross-system identifiers."""
    return conn.execute(
        """
        SELECT
          ptf.id, ptf.slot_id, ptf.is_ignored, ptf.mapped_at,
          ptf.color_hex, ptf.material, ptf.used_weight_g,
          pt.external_id AS print_task_external_id,
          fs.uid AS spool_uid
        FROM print_task_filament ptf
        JOIN print_task pt ON pt.id = ptf.print_task_id
        LEFT JOIN filament_spool fs ON fs.id = ptf.filament_spool_id
        WHERE ptf.filament_spool_id IS NOT NULL OR ptf.is_ignored = 1
        ORDER BY pt.external_id, ptf.slot_id, ptf.color_hex, ptf.material, ptf.used_weight_g, ptf.id
        """
    ).fetchall()


def get_task_id_by_external_id(conn: sqlite3.Connection, external_id: int) -> int | None:
    row = conn.execute(
        "SELECT id FROM print_task WHERE external_id = ?", (external_id,)
    ).fetchone()
    return row["id"] if row else None


def get_spool_id_by_uid(conn: sqlite3.Connection, uid: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM filament_spool WHERE uid = ?", (uid,)
    ).fetchone()
    return row["id"] if row else None


def get_ptf_row_by_task_and_slot(conn: sqlite3.Connection, print_task_id: int, slot_id) -> sqlite3.Row | None:
    if slot_id is None:
        # Fallback case: empty amsDetailMapping creates exactly one ptf with slot_id NULL
        return conn.execute(
            "SELECT id, filament_spool_id, is_ignored FROM print_task_filament "
            "WHERE print_task_id = ? AND slot_id IS NULL LIMIT 1",
            (print_task_id,),
        ).fetchone()
    return conn.execute(
        "SELECT id, filament_spool_id, is_ignored FROM print_task_filament "
        "WHERE print_task_id = ? AND slot_id = ? LIMIT 1",
        (print_task_id, slot_id),
    ).fetchone()


def get_ptf_row_for_mapping(conn: sqlite3.Connection, print_task_id: int, mapping: dict) -> sqlite3.Row | None:
    slot_id = mapping.get("slot_id")
    color_hex = mapping.get("color_hex")
    material = mapping.get("material")
    used_weight_g = mapping.get("used_weight_g")

    if color_hex is not None or material is not None or used_weight_g is not None:
        clauses = ["print_task_id = ?"]
        params: list = [print_task_id]
        if slot_id is None:
            clauses.append("slot_id IS NULL")
        else:
            clauses.append("slot_id = ?")
            params.append(slot_id)
        if color_hex is None:
            clauses.append("color_hex IS NULL")
        else:
            clauses.append("color_hex = ?")
            params.append(color_hex)
        if material is None:
            clauses.append("material IS NULL")
        else:
            clauses.append("material = ?")
            params.append(material)
        if used_weight_g is not None:
            clauses.append("ABS(COALESCE(used_weight_g, 0) - ?) < 0.01")
            params.append(float(used_weight_g))

        matches = conn.execute(
            "SELECT id, filament_spool_id, is_ignored FROM print_task_filament "
            f"WHERE {' AND '.join(clauses)} ORDER BY id",
            params,
        ).fetchall()
        occurrence = mapping.get("occurrence_index")
        if occurrence is not None:
            try:
                idx = int(occurrence)
            except (TypeError, ValueError):
                return None
            return matches[idx] if 0 <= idx < len(matches) else None
        return matches[0] if len(matches) == 1 else None

    if slot_id is None:
        rows = conn.execute(
            "SELECT id, filament_spool_id, is_ignored FROM print_task_filament "
            "WHERE print_task_id = ? AND slot_id IS NULL",
            (print_task_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, filament_spool_id, is_ignored FROM print_task_filament "
            "WHERE print_task_id = ? AND slot_id = ?",
            (print_task_id, slot_id),
        ).fetchall()
    return rows[0] if len(rows) == 1 else None


def set_ptf_ignored(conn: sqlite3.Connection, ptf_id: int) -> None:
    """Force-set ptf to ignored state, clearing any existing spool mapping."""
    conn.execute(
        "UPDATE print_task_filament SET filament_spool_id=NULL, is_ignored=1, mapped_at=NULL WHERE id=?",
        (ptf_id,),
    )


def get_tasks_grouped_by_spool(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        """
        SELECT
          pt.id, pt.print_name, pt.started_at, pt.cover_url,
          pt.status, pt.is_manual,
          SUM(ptf.used_weight_g) AS used_weight_g,
          ptf.filament_spool_id
        FROM print_task pt
        JOIN print_task_filament ptf ON ptf.print_task_id = pt.id
        WHERE ptf.filament_spool_id IS NOT NULL
        GROUP BY ptf.filament_spool_id, pt.id
        ORDER BY ptf.filament_spool_id, pt.started_at DESC
        """
    ).fetchall()
    result: dict = {}
    for r in rows:
        sid = r["filament_spool_id"]
        if sid not in result:
            result[sid] = []
        result[sid].append(dict(r))
    return result


def get_tasks_for_spool(conn: sqlite3.Connection, spool_id: int) -> list:
    rows = conn.execute(
        """
        SELECT
          pt.id, pt.print_name, pt.started_at, pt.cover_url,
          pt.status, pt.is_manual,
          SUM(ptf.used_weight_g) AS used_weight_g
        FROM print_task pt
        JOIN print_task_filament ptf ON ptf.print_task_id = pt.id
        WHERE ptf.filament_spool_id = ?
        GROUP BY pt.id
        ORDER BY pt.started_at DESC
        """,
        (spool_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# --- Analytics queries ---

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


# ── Analytics Queries ───────────────────────────────────────────────────────


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
