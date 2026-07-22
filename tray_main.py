"""
tray_main.py — 材料帳本 Filament Ledger System Tray 入口點

執行緒模型：
  主執行緒：pystray icon.run() event loop（pystray 要求在主執行緒）
  背景執行緒：_ServerThread（daemon=True）—— Waitress WSGI server

生命週期：
  啟動 → tray 圖示出現，伺服器未啟動
  點「開啟」→ 啟動伺服器 → 等待就緒 → 開啟瀏覽器
  再點「開啟」→ 直接開啟瀏覽器
  點「結束」→ server.close() → thread.join(5s) → icon.stop()

Port 選擇：
  預設 7580，避開 macOS Monterey+ AirPlay Receiver（port 5000）。
  可在使用者資料目錄的 .env 中設定 PORT=<port> 覆寫（需重啟）。
"""

from __future__ import annotations

import os
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Optional


# ── 路徑輔助（必須在所有 src/web import 之前執行） ──────────────────────────

def _get_resource_dir() -> Path:
    """捆綁資源根目錄：凍結時為 sys._MEIPASS；開發時為專案根。"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).parent


# ── .env 預先載入（僅為讀取 PORT；app.py 內的 load_dotenv 以 override=False 重複載入無副作用） ──

def _load_env_for_port() -> None:
    """在確定使用者資料目錄後載入 .env，使 PORT 設定生效。"""
    try:
        from dotenv import load_dotenv
        from src.paths import get_base_dir
        env_path = get_base_dir() / ".env"
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=False)
    except Exception:
        pass  # dotenv / paths 尚未可用時跳過，使用預設值

_load_env_for_port()


# ── 常數 ─────────────────────────────────────────────────────────────────────

HOST = "127.0.0.1"
# 預設 7580：避開 macOS Monterey+ AirPlay Receiver（port 5000）與其他常見開發工具。
# 可在使用者資料目錄的 .env 中設定 PORT=<port> 覆寫（需重啟生效）。
_DEFAULT_PORT = 7580
try:
    PORT = int(os.environ.get("PORT", "") or _DEFAULT_PORT)
    if not (1024 <= PORT <= 65535):
        PORT = _DEFAULT_PORT
except (ValueError, TypeError):
    PORT = _DEFAULT_PORT
URL  = f"http://{HOST}:{PORT}"


# ── Server Thread ─────────────────────────────────────────────────────────────

class _ServerThread(threading.Thread):
    """Waitress WSGI 伺服器背景執行緒。"""

    def __init__(self) -> None:
        super().__init__(name="waitress-server", daemon=True)
        self._server = None
        self._ready  = threading.Event()
        self._error: Optional[Exception] = None

    def run(self) -> None:
        try:
            from waitress import create_server
            from web.app import create_app

            app = create_app()
            self._server = create_server(app, host=HOST, port=PORT)
            self._ready.set()    # 通知主執行緒：socket 已就緒（_server 已賦值）
            self._server.run()   # 阻塞直到 close()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("伺服器啟動失敗: %s", exc, exc_info=True)
            self._error = exc
            self._ready.set()    # 即使失敗也解除等待，避免死鎖

    def wait_ready(self, timeout: float = 10.0) -> bool:
        """等待伺服器就緒。回傳 True 表示成功啟動，False 表示逾時或啟動失敗。"""
        self._ready.wait(timeout=timeout)
        return self._error is None and self._server is not None

    def stop(self) -> None:
        # 等待 _server 確實被賦值後再呼叫 close()，
        # 避免在啟動空窗期呼叫 stop() 時 _server 為 None 而被略過
        # timeout 縮短為 3s：若啟動失敗 _ready 已被 set，不會真的等 3 秒
        self._ready.wait(timeout=3.0)
        if self._server is not None:
            try:
                self._server.close()
            except Exception:
                pass
            self._server = None


# ── Tray App ──────────────────────────────────────────────────────────────────

class _TrayApp:

    def __init__(self) -> None:
        self._server_thread: Optional[_ServerThread] = None
        self._lock = threading.Lock()

    def _is_server_running(self) -> bool:
        return (
            self._server_thread is not None
            and self._server_thread.is_alive()
        )

    def _start_server(self) -> bool:
        """啟動伺服器執行緒（若已在執行則跳過），並等待就緒。回傳 True 表示伺服器可用。"""
        with self._lock:
            if self._is_server_running():
                thread = self._server_thread  # type: ignore[assignment]
            else:
                thread = _ServerThread()
                thread.start()
                self._server_thread = thread
        # wait_ready() 已在 Event 設定後立即回傳，不會重複等待
        return thread.wait_ready(timeout=10.0)

    def _on_open(self, icon, item) -> None:  # noqa: ARG002
        if not self._start_server():
            # 優先顯示真實錯誤訊息；若無，回退到 port 衝突提示
            with self._lock:
                thread = self._server_thread
            error_msg = str(getattr(thread, "_error", None) or "")
            if error_msg:
                notice = f"啟動失敗：{error_msg[:200]}"
            else:
                notice = f"無法啟動伺服器，請確認 port {PORT} 未被其他程式佔用。"
            if getattr(icon, "HAS_NOTIFICATION", False):
                try:
                    icon.notify(notice, "材料帳本")
                except Exception:
                    pass
            return
        webbrowser.open(URL)

    def _on_quit(self, icon, item) -> None:  # noqa: ARG002
        with self._lock:
            thread = self._server_thread
            self._server_thread = None

        if thread is not None:
            thread.stop()
            thread.join(timeout=5.0)

        icon.stop()

    def run(self) -> None:
        import pystray
        from PIL import Image

        icon_path = (
            _get_resource_dir()
            / "web" / "static" / "img"
            / "print-filament-tracker-icon.png"
        )
        # 預先縮至 256×256 LANCZOS：pystray 內部會建立臨時 ICO，
        # 較大的 base image 可讓 Pillow 嵌入更多尺寸（至 256），高 DPI 顯示更清晰。
        image = Image.open(str(icon_path)).convert("RGBA").resize((256, 256), Image.LANCZOS)

        menu = pystray.Menu(
            pystray.MenuItem("開啟材料帳本", self._on_open, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("結束", self._on_quit),
        )
        icon = pystray.Icon(
            name  = "FilamentLedger",
            icon  = image,
            title = "材料帳本 Filament Ledger",
            menu  = menu,
        )

        def setup(icon):
            icon.visible = True
            # 程式啟動時自動啟動伺服器並開啟瀏覽器
            self._on_open(icon, None)

        icon.run(setup=setup)


# ── Single Instance Check ─────────────────────────────────────────────────────

def _check_single_instance() -> object:
    """確保程式只有單一實例執行。回傳一個 lock 物件；若已在執行則回傳 None。"""
    if sys.platform == "win32":
        import ctypes
        mutex_name = "FilamentLedger_Mutex_9e3c5"
        mutex = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
        if not mutex:
            return None
        if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            return None
        return mutex
    else:
        import fcntl
        import tempfile
        lock_file = Path(tempfile.gettempdir()) / "filamentledger.lock"
        fp = open(lock_file, "w")
        try:
            fcntl.lockf(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fp
        except IOError:
            return None


# ── Entry Point ────────────────────────────────────────────────────────────────────────────────

def main() -> None:
    lock = _check_single_instance()
    if lock is None:
        import webbrowser
        webbrowser.open(URL)
        return
    _TrayApp().run()
    # icon.run() 已返回（icon.stop() 被呼叫）
    # 使用 os._exit(0) 強制終止：確保 Waitress wasyncore 等
    # daemon 執行緒不殘留在後台。托盤應用程式標準做法。
    # ⚠️ 注意：os._exit() 會跳過 atexit、finally、GC，
    #    若未來需要在程式結束前執行清理，請放在 _on_quit() 而非此處。
    os._exit(0)


if __name__ == "__main__":
    main()
