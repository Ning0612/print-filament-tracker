# -*- mode: python ; coding: utf-8 -*-
# PrintFilamentTracker.spec — Windows 打包規格（--onefile --windowed）
#
# 使用方式：
#   .\scripts\build_exe.ps1
#   或手動：.venv\Scripts\python.exe -m PyInstaller PrintFilamentTracker.spec --clean

import os
from pathlib import Path

block_cipher = None
project_root = Path(SPECPATH)
use_upx = os.environ.get('PYINSTALLER_NO_UPX') != '1'

datas = [
    (str(project_root / "web" / "templates"),    "web/templates"),
    (str(project_root / "web" / "static"),       "web/static"),
    (str(project_root / "web" / "translations"), "web/translations"),
    # .env 和 data/ 不捆綁（敏感資料 / 執行時自動建立）
]

hiddenimports = [
    # Flask 生態系（動態載入，靜態分析會遺漏）
    "flask", "flask.json", "flask.sessions", "flask.helpers",
    "flask.wrappers", "flask.ctx", "flask.globals", "flask.signals",
    "flask.json.provider",
    "jinja2", "jinja2.ext", "jinja2.compiler", "jinja2.runtime",
    "jinja2.defaults", "jinja2.filters", "jinja2.tests",
    "werkzeug", "werkzeug.routing", "werkzeug.exceptions",
    "werkzeug.middleware.proxy_fix", "werkzeug.sansio.utils",
    "flask_wtf", "flask_wtf.csrf",
    "wtforms", "wtforms.validators", "wtforms.fields", "wtforms.widgets",
    "click", "click.exceptions",
    # Waitress（無 hook，全部手動宣告）
    "waitress", "waitress.server", "waitress.task", "waitress.channel",
    "waitress.buffers", "waitress.receiver", "waitress.parser",
    "waitress.trigger", "waitress.wasyncore", "waitress.adjustments",
    "waitress.utilities", "waitress.compat", "waitress.runner",
    # pystray（Windows backend）
    "pystray", "pystray._win32",
    # Pillow
    "PIL", "PIL.Image", "PIL.PngImagePlugin", "PIL.IcoImagePlugin",
    # python-dotenv
    "dotenv",
    # 應用程式模組（藍圖動態 import）
    "web.app", "web.i18n",
    "web.routes.analytics", "web.routes.dashboard", "web.routes.lang",
    "web.routes.mapping",   "web.routes.printers",  "web.routes.settings",
    "web.routes.spools",    "web.routes.tasks",
    "src.analytics", "src.auth",         "src.backup",      "src.cloud_client",
    "src.config",    "src.db",           "src.export_csv",  "src.export_json",
    "src.filament",  "src.ingestion",    "src.normalize",   "src.printer",
    # 標準函式庫
    "logging.handlers", "sqlite3",
]

excludes = [
    "tkinter", "unittest", "distutils", "setuptools", "pkg_resources",
    "matplotlib", "numpy", "pandas", "scipy",
    "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
]

a = Analysis(
    ["tray_main.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name    = "PrintFilamentTracker",
    debug   = False,
    bootloader_ignore_signals = False,
    strip   = False,
    upx     = use_upx,
    upx_exclude = [],
    runtime_tmpdir = None,
    console = False,
    disable_windowed_traceback = False,
    argv_emulation = False,
    target_arch = None,
    codesign_identity = None,
    entitlements_file = None,
    icon    = str(project_root / "web" / "static" / "img" / "print-filament-tracker-icon.ico"),
)
