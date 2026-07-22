"""
src/paths.py — 平台感知使用者資料路徑解析

提供統一的使用者資料根目錄解析，供 web.app、src.config、src.main 共用。
確保 Windows / macOS 凍結環境（PyInstaller）與開發模式使用一致的路徑。

平台路徑對應：
  Windows  凍結  → %LOCALAPPDATA%\\FilamentLedger\\
  macOS    凍結  → ~/Library/Application Support/FilamentLedger/
  Linux    凍結  → $XDG_DATA_HOME/FilamentLedger/（fallback: ~/.local/share/）
  開發模式  全平台 → <project_root>/（即 src/paths.py 的兩層上層目錄）

改名遷移：舊版使用 APP_NAME="PrintFilamentTracker"。凍結環境首次以新名啟動時，
ensure_base_dir() 會將舊目錄整體搬移到新目錄（見 migrate_legacy_base）。
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

# ── APP 名稱（唯一定義，所有模組不得硬編碼） ────────────────────────────────
APP_NAME = "FilamentLedger"
# 舊版名稱，僅供資料目錄遷移偵測用（改名前為 PrintFilamentTracker）
LEGACY_APP_NAME = "PrintFilamentTracker"

_log = logging.getLogger(__name__)


def _frozen_base_for(app_name: str) -> Path:
    """凍結環境下、指定 app 名稱的使用者資料根目錄（平台感知）。"""
    if sys.platform == "win32":
        return _win32_base(app_name)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_name
    # Linux / 其他平台 XDG fallback
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(xdg) if xdg else (Path.home() / ".local" / "share")
    return base / app_name


def get_base_dir() -> Path:
    """回傳使用者資料根目錄（唯讀解析，不建立目錄）。

    凍結環境（PyInstaller sys.frozen=True）：
      - Windows  → %LOCALAPPDATA%\\FilamentLedger\\
      - macOS    → ~/Library/Application Support/FilamentLedger/
      - Linux    → $XDG_DATA_HOME/FilamentLedger/
    開發環境：
      - 回傳 <project_root>，即 .env / data/ 的所在位置
    """
    if getattr(sys, "frozen", False):
        return _frozen_base_for(APP_NAME)
    # 開發模式：此檔案在 src/paths.py，往上兩層為專案根目錄
    return Path(__file__).parent.parent


def _legacy_base_dir() -> Path | None:
    """舊版資料根目錄（凍結環境才有意義；開發模式回 None）。

    開發模式的資料放在專案根，不隨產品改名而變動，故無需遷移。
    """
    if getattr(sys, "frozen", False):
        return _frozen_base_for(LEGACY_APP_NAME)
    return None


def migrate_legacy_base(new_base: Path) -> None:
    """凍結環境首次以新名啟動時，將舊資料目錄整體搬移到新目錄。

    僅在「舊目錄存在且新目錄不存在」時執行；使用整目錄 shutil.move，
    連同 SQLite 的 -wal/-shm 與 covers/logs/backups/.env 一併搬移，
    避免只搬 .db 而遺留 WAL 造成資料不一致。

    遷移必須在任何 DB 連線、tray 單例 lock、.env 載入之前完成
    （由 ensure_base_dir 保證）。失敗時只記錄、絕不刪除舊資料、
    不中斷啟動（降級為以新空目錄啟動）。
    """
    old = _legacy_base_dir()
    if old is None:
        return
    try:
        if old.exists() and old.is_dir() and not new_base.exists():
            new_base.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(new_base))
            _log.info("Migrated legacy data dir %s → %s", old, new_base)
    except OSError as exc:
        # 遷移失敗不可中斷啟動；保留舊資料，讓 app 以新空目錄啟動。
        _log.warning("Legacy data migration failed (%s → %s): %s", old, new_base, exc)


def ensure_base_dir() -> Path:
    """回傳使用者資料根目錄，並確保其存在（包含父目錄）。

    首次以新名啟動時先嘗試遷移舊目錄（見 migrate_legacy_base），
    再建立目錄。若建立失敗（PermissionError 等）會向上拋出。
    """
    base = get_base_dir()
    migrate_legacy_base(base)
    base.mkdir(parents=True, exist_ok=True)
    return base


def resolve_output_dir(raw: str | None = None) -> Path:
    """解析輸出目錄（BAMBU_OUTPUT_DIR 或預設值）。

    - 若 raw 為絕對路徑，直接使用。
    - 若 raw 為相對路徑（或 None），視為相對於 get_base_dir() / "data"。
    - 確保相對路徑解析至使用者資料根，而非 process CWD。
    """
    if raw:
        p = Path(raw)
        if p.is_absolute():
            return p
        # 相對路徑：相對於資料根，而非 CWD
        return get_base_dir() / p
    return get_base_dir() / "data"


def _win32_base(app_name: str = APP_NAME) -> Path:
    """Windows 凍結環境路徑解析。

    優先順序：LOCALAPPDATA → USERPROFILE/AppData/Local → Path.home()/AppData/Local
    使用 LOCALAPPDATA（本機非漫遊）而非 APPDATA（Roaming），
    避免 SQLite、covers、logs 等大型二進位檔被 Windows 漫遊設定檔同步。
    """
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if not local:
        userprofile = os.environ.get("USERPROFILE", "").strip()
        if userprofile:
            local = str(Path(userprofile) / "AppData" / "Local")
        else:
            local = str(Path.home() / "AppData" / "Local")
    return Path(local) / app_name
