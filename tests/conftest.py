from collections.abc import Iterator
from pathlib import Path
import sqlite3

import pytest

from src.db import get_connection, init_db


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "tracker.db"
    init_db(path)
    return path


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    with get_connection(db_path) as connection:
        yield connection
