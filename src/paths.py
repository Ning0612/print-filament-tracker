"""
src/paths.py — 平台感知使用者資料路徑解析

提供統一的使用者資料根目錄解析，供 web.app、src.config、src.main 共用。
確保 Windows / macOS 凍結環境（PyInstaller）與開發模式使用一致的路徑。

平台路徑對應：
  Windows  凍結  → %LOCALAPPDATA%\\PrintFilamentTracker\\
  macOS    凍結  → ~/Library/Application Support/PrintFilamentTracker/
  Linux    凍結  → $XDG_DATA_HOME/PrintFilamentTracker/（fallback: ~/.local/share/）
  開發模式  全平台 → <project_root>/（即 src/paths.py 的兩層上層目錄）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ── APP 名稱（唯一定義，所有模組不得硬編碼） ────────────────────────────────
APP_NAME = "PrintFilamentTracker"


def get_base_dir() -> Path:
    """回傳使用者資料根目錄（唯讀解析，不建立目錄）。

    凍結環境（PyInstaller sys.frozen=True）：
      - Windows  → %LOCALAPPDATA%\\PrintFilamentTracker\\
      - macOS    → ~/Library/Application Support/PrintFilamentTracker/
      - Linux    → $XDG_DATA_HOME/PrintFilamentTracker/
    開發環境：
      - 回傳 <project_root>，即 .env / data/ 的所在位置
    """
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            return _win32_base()
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / APP_NAME
        # Linux / 其他平台 XDG fallback
        xdg = os.environ.get("XDG_DATA_HOME", "").strip()
        base = Path(xdg) if xdg else (Path.home() / ".local" / "share")
        return base / APP_NAME
    # 開發模式：此檔案在 src/paths.py，往上兩層為專案根目錄
    return Path(__file__).parent.parent


def ensure_base_dir() -> Path:
    """回傳使用者資料根目錄，並確保其存在（包含父目錄）。

    若建立失敗（PermissionError 等）會向上拋出，讓呼叫端決定如何處理。
    """
    base = get_base_dir()
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


def _win32_base() -> Path:
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
    return Path(local) / APP_NAME
