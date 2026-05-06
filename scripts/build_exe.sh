#!/usr/bin/env bash
# build_exe.sh — PrintFilamentTracker macOS 建置腳本（生成 .app bundle）
#
# 使用方式：
#   bash scripts/build_exe.sh
#   bash scripts/build_exe.sh --skip-install

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="$REPO_ROOT/.venv/bin/python"
PNG_ICON="$REPO_ROOT/web/static/img/print-filament-tracker-icon.png"
ICNS_ICON="$REPO_ROOT/web/static/img/print-filament-tracker-icon.icns"
SPEC_FILE="$REPO_ROOT/PrintFilamentTracker-mac.spec"
OUTPUT_APP="$REPO_ROOT/dist/PrintFilamentTracker.app"

SKIP_INSTALL=false
for arg in "$@"; do
    case "$arg" in --skip-install) SKIP_INSTALL=true ;; esac
done

step() { echo; echo "[STEP] $1"; }
ok()   { echo "  [OK]  $1"; }
fail() { echo "  [FAIL] $1" >&2; exit 1; }

# ── STEP 0：Pre-flight ────────────────────────────────────────────────────────
step "Pre-flight checks"
[[ -f "$VENV_PYTHON" ]] || fail "找不到 venv：$VENV_PYTHON\n請先執行：python3 -m venv .venv && pip install -r requirements.txt"
[[ -f "$SPEC_FILE"   ]] || fail "找不到 spec：$SPEC_FILE"
ok "venv 和 spec 存在"

# ── STEP 1：安裝建置依賴 ──────────────────────────────────────────────────────
if [[ "$SKIP_INSTALL" == false ]]; then
    step "安裝建置依賴"
    "$VENV_PYTHON" -m pip install --quiet --upgrade \
        "waitress>=3.0.0" \
        "pystray>=0.19.5" \
        "Pillow>=10.0.0" \
        "pyinstaller>=6.0.0" \
        "pyobjc-framework-Cocoa>=9.0"
    ok "依賴安裝完成"
fi

# ── STEP 2：PNG → ICNS（macOS 格式，需 iconutil） ─────────────────────────────
step "轉換圖示 PNG → ICNS"
"$VENV_PYTHON" - "$PNG_ICON" "$ICNS_ICON" <<'PYEOF'
import sys
import subprocess
import shutil
import tempfile
from pathlib import Path
from PIL import Image

png_path  = sys.argv[1]
icns_path = sys.argv[2]

iconset_dir = Path(tempfile.mkdtemp()) / "icon.iconset"
iconset_dir.mkdir(parents=True)

img = Image.open(png_path).convert("RGBA")
size_map = {
    "icon_16x16.png":      16,  "icon_16x16@2x.png":    32,
    "icon_32x32.png":      32,  "icon_32x32@2x.png":    64,
    "icon_128x128.png":   128,  "icon_128x128@2x.png": 256,
    "icon_256x256.png":   256,  "icon_256x256@2x.png": 512,
    "icon_512x512.png":   512,  "icon_512x512@2x.png":1024,
}
for filename, size in size_map.items():
    img.resize((size, size), Image.LANCZOS).save(str(iconset_dir / filename))

subprocess.run(
    ["iconutil", "-c", "icns", str(iconset_dir), "-o", icns_path],
    check=True
)
shutil.rmtree(str(iconset_dir.parent))
print(f"ICNS saved: {icns_path}")
PYEOF

ok "ICNS 圖示建立：$ICNS_ICON"

# ── STEP 3：PyInstaller ───────────────────────────────────────────────────────
step "執行 PyInstaller（生成 .app bundle）"
cd "$REPO_ROOT"
"$VENV_PYTHON" -m PyInstaller \
    --clean \
    --noconfirm \
    --distpath "$REPO_ROOT/dist" \
    --workpath "$REPO_ROOT/build" \
    --log-level WARN \
    "$SPEC_FILE"
ok "PyInstaller 完成"

# ── STEP 4：驗證輸出 ──────────────────────────────────────────────────────────
step "驗證輸出"
[[ -d "$OUTPUT_APP" ]] || fail "找不到輸出: $OUTPUT_APP"
SIZE_MB=$(du -sm "$OUTPUT_APP" | cut -f1)
ok "輸出: $OUTPUT_APP (約 ${SIZE_MB} MB)"

echo ""
echo "================================================================"
echo "  建置完成！"
echo "================================================================"
echo ""
echo "  使用方式："
echo "    1. 將 dist/PrintFilamentTracker.app 拖入 /Applications"
echo "    2. 首次啟動：右鍵 → 開啟（允許 Gatekeeper）"
echo "    3. 點選 Menu Bar 圖示「開啟 PrintFilamentTracker」"
echo "    4. 資料庫與設定自動儲存於："
echo "       ~/Library/Application Support/PrintFilamentTracker/"
echo ""
