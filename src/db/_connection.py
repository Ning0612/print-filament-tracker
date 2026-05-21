import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DB_FILENAME = "tracker.db"


class DatabaseError(Exception):
    pass


def get_db_path(output_dir: Path) -> Path:
    return output_dir / DB_FILENAME


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
