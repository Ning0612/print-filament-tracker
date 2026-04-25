import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DB_FILENAME = "bambu.db"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS printer (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  device_id TEXT UNIQUE,
  model TEXT,
  purchased_at DATETIME,
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
  total_weight_g REAL,
  cover_url TEXT,
  raw_json TEXT
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
"""


class DatabaseError(Exception):
    pass


def get_db_path(output_dir: Path) -> Path:
    return output_dir / DB_FILENAME


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA_SQL)
        try:
            conn.execute("ALTER TABLE print_task ADD COLUMN cover_url TEXT")
            conn.commit()
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise


@contextmanager
def get_connection(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# --- Printer helpers ---

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


# --- Print task helpers ---

def insert_print_task_ignore(conn: sqlite3.Connection, task: dict) -> int | None:
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO print_task
          (external_id, print_name, printer_id, started_at, ended_at,
           duration_seconds, total_weight_g, cover_url, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task["external_id"],
            task.get("print_name"),
            task.get("printer_id"),
            task.get("started_at"),
            task.get("ended_at"),
            task.get("duration_seconds"),
            task.get("total_weight_g"),
            task.get("cover_url"),
            task.get("raw_json"),
        ),
    )
    return cursor.lastrowid if cursor.rowcount > 0 else None


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


# --- Filament spool helpers ---

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
          pt.print_name, pt.started_at, pt.external_id, pt.cover_url
        FROM print_task_filament ptf
        JOIN print_task pt ON pt.id = ptf.print_task_id
        WHERE ptf.filament_spool_id IS NULL
        ORDER BY pt.started_at DESC
        """
    ).fetchall()


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


def get_ptf_material(conn: sqlite3.Connection, ptf_id: int):
    return conn.execute(
        "SELECT material FROM print_task_filament WHERE id=?", (ptf_id,)
    ).fetchone()


def get_mapped_filaments(conn: sqlite3.Connection) -> list:
    return conn.execute(
        """
        SELECT
          ptf.id, ptf.print_task_id, ptf.slot_id,
          ptf.used_weight_g, ptf.color_hex, ptf.material,
          ptf.filament_spool_id,
          pt.print_name, pt.started_at, pt.cover_url,
          fs.color_name AS spool_color_name,
          fs.color_hex AS spool_color_hex,
          fs.material AS spool_material
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


def map_filament_to_spool(conn: sqlite3.Connection, ptf_id: int, spool_id: int) -> None:
    cursor = conn.execute(
        "UPDATE print_task_filament SET filament_spool_id=? WHERE id=?",
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
