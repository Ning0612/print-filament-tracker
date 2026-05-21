import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

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


def _migrate_add_column(conn: sqlite3.Connection, table: str, column_def: str) -> None:
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
