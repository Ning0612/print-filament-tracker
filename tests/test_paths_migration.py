"""Tests for legacy data-dir migration (src/paths.py migrate_legacy_base)."""

from pathlib import Path

import pytest

import src.paths as paths


@pytest.fixture
def dirs(tmp_path: Path):
    old = tmp_path / "PrintFilamentTracker"
    new = tmp_path / "FilamentLedger"
    return old, new


def _seed_legacy(old: Path):
    """Create a legacy data dir with a db + WAL sidecars and a cover."""
    old.mkdir(parents=True)
    (old / "tracker.db").write_text("DB")
    (old / "tracker.db-wal").write_text("WAL")
    (old / "tracker.db-shm").write_text("SHM")
    (old / "covers").mkdir()
    (old / "covers" / "m1.png").write_bytes(b"\x89PNG")


def test_migrates_whole_dir_when_old_exists_new_missing(dirs, monkeypatch):
    old, new = dirs
    _seed_legacy(old)
    monkeypatch.setattr(paths, "_legacy_base_dir", lambda: old)

    paths.migrate_legacy_base(new)

    assert not old.exists()
    assert (new / "tracker.db").read_text() == "DB"
    # WAL/-shm sidecars moved together, avoiding split state
    assert (new / "tracker.db-wal").read_text() == "WAL"
    assert (new / "tracker.db-shm").read_text() == "SHM"
    assert (new / "covers" / "m1.png").read_bytes() == b"\x89PNG"


def test_noop_when_new_already_exists(dirs, monkeypatch):
    old, new = dirs
    _seed_legacy(old)
    new.mkdir(parents=True)
    (new / "tracker.db").write_text("NEW")
    monkeypatch.setattr(paths, "_legacy_base_dir", lambda: old)

    paths.migrate_legacy_base(new)

    # New data untouched; old left in place (never deleted)
    assert (new / "tracker.db").read_text() == "NEW"
    assert old.exists()


def test_noop_when_no_legacy_dir(dirs, monkeypatch):
    old, new = dirs
    monkeypatch.setattr(paths, "_legacy_base_dir", lambda: old)  # points at nonexistent

    paths.migrate_legacy_base(new)

    assert not new.exists()


def test_dev_mode_returns_none_and_skips(dirs, monkeypatch):
    _, new = dirs
    monkeypatch.setattr(paths, "_legacy_base_dir", lambda: None)

    paths.migrate_legacy_base(new)  # must not raise

    assert not new.exists()


def test_move_failure_does_not_raise_or_delete(dirs, monkeypatch):
    old, new = dirs
    _seed_legacy(old)
    monkeypatch.setattr(paths, "_legacy_base_dir", lambda: old)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(paths.shutil, "move", boom)

    # Failure is swallowed: startup continues, legacy data preserved
    paths.migrate_legacy_base(new)

    assert old.exists()
    assert (old / "tracker.db").read_text() == "DB"
