# -*- mode: python ; coding: utf-8 -*-
# PrintFilamentTracker-mac.spec — macOS 打包規格（生成 .app bundle）
#
# 使用方式：
#   bash scripts/build_exe.sh
#   或手動：.venv/bin/python -m PyInstaller PrintFilamentTracker-mac.spec --clean

from pathlib import Path

block_cipher = None
project_root = Path(SPECPATH)

datas = [
    (str(project_root / "web" / "templates"),    "web/templates"),
    (str(project_root / "web" / "static"),       "web/static"),
    (str(project_root / "web" / "translations"), "web/translations"),
    # .env 和 data/ 不捆綁（敏感資料 / 執行時自動建立）
]

hiddenimports = [
    # Flask 生態系（與 Windows spec 相同）
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
    # Waitress（與 Windows spec 相同）
    "waitress", "waitress.server", "waitress.task", "waitress.channel",
    "waitress.buffers", "waitress.receiver", "waitress.parser",
    "waitress.trigger", "waitress.wasyncore", "waitress.adjustments",
    "waitress.utilities", "waitress.compat", "waitress.runner",
    # pystray（macOS backend，替換 _win32）
    "pystray", "pystray._darwin",
    # Pillow
    "PIL", "PIL.Image", "PIL.PngImagePlugin",
    # python-dotenv
    "dotenv",
    # 應用程式模組（與 Windows spec 相同）
    "web.app", "web.i18n",
    "web.routes.analytics", "web.routes.dashboard", "web.routes.lang",
    "web.routes.mapping",   "web.routes.printers",  "web.routes.settings",
    "web.routes.spools",    "web.routes.tasks",
    "src.analytics", "src.auth",         "src.backup",      "src.cloud_client",
    "src.config",    "src.db",           "src.export_csv",  "src.export_json",
    "src.filament",  "src.ingestion",    "src.normalize",   "src.paths",
    "src.printer",
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

# macOS：先建立 EXE（exclude_binaries=True），再由 COLLECT + BUNDLE 組裝
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries = True,
    name    = "PrintFilamentTracker",
    debug   = False,
    strip   = False,
    upx     = False,
    console = False,
    argv_emulation  = False,
    target_arch     = None,
    codesign_identity  = None,
    entitlements_file  = None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip = False,
    upx   = False,
    name  = "PrintFilamentTracker",
)

app = BUNDLE(
    coll,
    name              = "PrintFilamentTracker.app",
    icon              = str(project_root / "web" / "static" / "img" / "print-filament-tracker-icon.icns"),
    bundle_identifier = "com.printfilamenttracker.app",
    info_plist        = {
        "CFBundleDisplayName":        "PrintFilamentTracker",
        "CFBundleShortVersionString": "1.1.0",
        "NSHighResolutionCapable":    True,
        "LSUIElement":                True,
        "NSHumanReadableCopyright":   "Copyright © 2026 Ning0612",
    },
)
