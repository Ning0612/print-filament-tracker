import logging
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_backup_lock = threading.Lock()
_backup_state: dict = {
    "status": "idle",           # idle / running / done / error
    "last_backup_at": None,     # "YYYY-MM-DD HH:MM:SS" or None
    "last_backup_file": None,   # filename only, or None
    "error": None,              # error message string, or None
}


def run_backup(db_path: Path, backup_dir: Path, keep_count: int) -> Path:
    """Execute one backup. Returns the final backup Path on success; raises on failure.

    Uses non-blocking lock acquisition so concurrent calls (manual + scheduler)
    never produce two simultaneous backups. If already running, raises RuntimeError
    without touching _backup_state.
    """
    global _backup_state

    if not _backup_lock.acquire(blocking=False):
        raise RuntimeError("備份正在進行中，請稍後再試。")

    # Preserve previous success info so UI can show it during 'running'
    prev_last_at = _backup_state.get("last_backup_at")
    prev_last_file = _backup_state.get("last_backup_file")
    _backup_state = {
        "status": "running",
        "last_backup_at": prev_last_at,
        "last_backup_file": prev_last_file,
        "error": None,
    }

    tmp_path: Path | None = None

    try:
        backup_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        tmp_path = backup_dir / f"bambu_{ts}.db.tmp"
        final_path = backup_dir / f"bambu_{ts}.db"

        # Both connections are freshly opened — required for WAL-safe backup.
        src_conn = sqlite3.connect(str(db_path))
        dst_conn = sqlite3.connect(str(tmp_path))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()

        # Verify the copy before committing the rename.
        verify_conn = sqlite3.connect(str(tmp_path))
        try:
            row = verify_conn.execute("PRAGMA quick_check").fetchone()
            if row is None or row[0] != "ok":
                raise RuntimeError(f"備份驗證失敗：PRAGMA quick_check 返回 {row}")
        finally:
            verify_conn.close()

        # Atomic rename — avoids leaving a partial file on crash.
        os.replace(str(tmp_path), str(final_path))
        tmp_path = None  # rename succeeded; no cleanup needed

        cleanup_old_backups(backup_dir, keep_count)

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _backup_state = {
            "status": "done",
            "last_backup_at": now_str,
            "last_backup_file": final_path.name,
            "error": None,
        }
        logger.info("備份完成：%s", final_path.name)
        return final_path

    except Exception as exc:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

        _backup_state = {
            "status": "error",
            "last_backup_at": prev_last_at,
            "last_backup_file": prev_last_file,
            "error": str(exc),
        }
        logger.error("備份失敗：%s", exc)
        raise

    finally:
        _backup_lock.release()


def cleanup_old_backups(backup_dir: Path, keep_count: int) -> None:
    """Delete oldest bambu_*.db files, keeping the newest keep_count copies."""
    keep_count = max(1, keep_count)
    try:
        files = sorted(backup_dir.glob("bambu_*.db"), key=lambda f: f.name)
        to_delete = files[:-keep_count] if len(files) > keep_count else []
        for old_file in to_delete:
            try:
                old_file.unlink()
                logger.info("已刪除舊備份：%s", old_file.name)
            except OSError as exc:
                logger.warning("無法刪除舊備份 %s：%s", old_file.name, exc)
    except Exception as exc:
        logger.warning("清理舊備份時發生錯誤：%s", exc)


def list_backups(backup_dir: Path) -> list[dict]:
    """Return backup file info list, newest first."""
    if not backup_dir.exists():
        return []
    files = sorted(backup_dir.glob("bambu_*.db"), key=lambda f: f.name, reverse=True)
    result = []
    for f in files:
        try:
            stat = f.stat()
            result.append({
                "name": f.name,
                "size_kb": round(stat.st_size / 1024, 1),
                "created_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            })
        except OSError:
            pass
    return result


def get_backup_state() -> dict:
    """Return a shallow copy of the current backup state (CPython-GIL-safe)."""
    return dict(_backup_state)
