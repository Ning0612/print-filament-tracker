import sqlite3
from pathlib import Path

from src.backup import cleanup_old_backups, list_backups, restore_from_backup, run_backup


def _insert_marker(db_path: Path, value: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS marker (value TEXT)")
        conn.execute("DELETE FROM marker")
        conn.execute("INSERT INTO marker (value) VALUES (?)", (value,))
        conn.commit()


def _read_marker(db_path: Path) -> str:
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT value FROM marker").fetchone()[0]


def test_run_backup_lists_and_restores_database(db_path: Path, tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    _insert_marker(db_path, "before")

    backup_path = run_backup(db_path, backup_dir, keep_count=3)
    _insert_marker(db_path, "after")

    assert backup_path.exists()
    assert list_backups(backup_dir)[0]["name"] == backup_path.name

    restore_from_backup(db_path, backup_path)
    assert _read_marker(db_path) == "before"


def test_cleanup_old_backups_keeps_newest_file_names(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    for name in (
        "bambu_20260101_010101.db",
        "bambu_20260102_010101.db",
        "bambu_20260103_010101.db",
    ):
        (backup_dir / name).write_bytes(b"backup")

    cleanup_old_backups(backup_dir, keep_count=2)

    assert [item["name"] for item in list_backups(backup_dir)] == [
        "bambu_20260103_010101.db",
        "bambu_20260102_010101.db",
    ]
