# 開發指南

本文說明如何在 PrintFilamentTracker 上進行功能開發、新增翻譯、擴充模組及維護程式碼品質。

## 目錄

- [開發環境設定](#開發環境設定)
- [專案結構](#專案結構)
- [開發指令](#開發指令)
- [新增翻譯 Key](#新增翻譯-key)
- [新增語言](#新增語言)
- [新增資料庫欄位（Schema 遷移）](#新增資料庫欄位schema-遷移)
- [新增 Web 路由](#新增-web-路由)
- [使用 Jinja2 時區 Filter](#使用-jinja2-時區-filter)
- [新增分析圖表](#新增分析圖表)
- [新增 CLI 子指令](#新增-cli-子指令)
- [圖片上傳與驗證](#圖片上傳與驗證)
- [HTMX Fragment 開發](#htmx-fragment-開發)
- [主題樣式客製化](#主題樣式客製化)
- [日誌與除錯](#日誌與除錯)
- [常見問題](#常見問題)

---

## 開發環境設定

### 1. 建立虛擬環境

```bash
cd PrintFilamentTracker
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

### 2. 設定 .env

```bash
copy .env.example .env
```

最低需求的 `.env`：

```env
BAMBU_ACCESS_TOKEN=<your-token>
BAMBU_REGION=global
```

### 3. 驗證環境

```bash
# 語法驗證所有 Python 檔案
.venv/Scripts/python.exe -m compileall src/ web/

# 驗證翻譯 JSON
.venv/Scripts/python.exe -c "
import json
json.load(open('web/translations/zh.json', encoding='utf-8'))
json.load(open('web/translations/en.json', encoding='utf-8'))
print('JSON OK')
"
```

### 4. 啟動開發伺服器

```bash
.venv/Scripts/python.exe -m flask --app web.app run --debug --host 127.0.0.1 --port 7580
```

Debug 模式下：
- Flask reloader 監聽檔案變更自動重啟
- 錯誤時瀏覽器顯示 Traceback（含互動式 Debugger）
- 關閉 HTTPS-only cookie 要求

---

## 專案結構

```
PrintFilamentTracker/
├── src/                    # 業務邏輯（無 Flask 依賴）
│   ├── config.py
│   ├── auth.py
│   ├── cloud_client.py
│   ├── db.py               # 資料庫 CRUD
│   ├── ingestion.py        # 匯入 pipeline
│   ├── filament.py         # 耗材管理
│   ├── printer.py          # 列印機管理
│   ├── analytics.py        # 統計分析
│   ├── backup.py           # 備份還原
│   ├── export_json.py
│   ├── export_csv.py
│   ├── paths.py            # 平台感知路徑解析
│   └── main.py             # CLI 入口
│
├── web/
│   ├── app.py              # Flask 工廠函數
│   ├── i18n.py             # 翻譯系統
│   ├── routes/             # Blueprint 路由
│   ├── templates/          # Jinja2 模板
│   ├── translations/       # 翻譯 JSON
│   └── static/             # CSS/JS 靜態檔案
│
├── tray_main.py            # System Tray 入口點（打包後的主入口）
├── PrintFilamentTracker.spec      # Windows PyInstaller spec
├── PrintFilamentTracker-mac.spec  # macOS PyInstaller spec
├── file_version_info.txt          # Windows PE 版本元數據（嵌入 .exe 標頭）
│
├── installer/
│   └── Product.wxs         # WiX v4 MSI 安裝程式定義
│
├── scripts/
│   ├── build_exe.ps1       # Windows 建置腳本（PyInstaller + WiX MSI）
│   ├── build_exe.sh        # macOS 建置腳本（PyInstaller）
│   └── get_token.py        # Bambu Cloud Token 取得工具（開發用）
│
├── data/                   # 開發模式資料目錄（gitignored）
│   ├── tracker.db
│   ├── covers/
│   ├── backups/
│   └── logs/
│
├── docs/                   # 技術文件
├── requirements.txt
├── .env.example
├── DISCLAIMER.md
└── LICENSE
```

> **注意**：凍結版（`.exe`/`.app`）的資料目錄不在專案根目錄，而在作業系統標準位置（Windows：`%LOCALAPPDATA%\PrintFilamentTracker\`；macOS：`~/Library/Application Support/PrintFilamentTracker/`）。

---

## 開發指令

```bash
# 語法驗證
.venv/Scripts/python.exe -m compileall src/ web/

# 驗證翻譯 JSON 格式
.venv/Scripts/python.exe -c "
import json
json.load(open('web/translations/zh.json', encoding='utf-8'))
json.load(open('web/translations/en.json', encoding='utf-8'))
print('OK')
"

# 啟動 System Tray（最接近正式版行為）
.venv/Scripts/python.exe tray_main.py

# 啟動 Web 開發伺服器（支援熱重載，不啟動托盤）
.venv/Scripts/python.exe -m flask --app web.app run --debug --host 127.0.0.1 --port 7580

# 取得 Bambu Cloud Token
.venv/Scripts/python.exe scripts/get_token.py

# 匯入列印歷史（雲端）
.venv/Scripts/python.exe -m src.main import

# 匯入列印歷史（從本地 raw_tasks.json）
.venv/Scripts/python.exe -m src.main import --from-file

# 查詢未對應耗材
.venv/Scripts/python.exe -m src.main unmapped

# 互動式耗材對應
.venv/Scripts/python.exe -m src.main map


# 匯出資料
.venv/Scripts/python.exe -m src.main export --format=both --output-dir=data
```

### 自行建置執行檔

```powershell
# Windows — 建置 .exe + .msi 安裝程式（需安裝 WiX v4）
.\scripts\build_exe.ps1 -NoUpx -Version "1.2.0"

# 常用參數：
#   -NoUpx       停用 UPX 壓縮（防毒誤報率較低）
#   -SkipMsi     略過 MSI 打包，只產出 .exe
#   -SkipInstall 略過 pip install 步驟
.\scripts\build_exe.ps1 -NoUpx -SkipMsi         # 僅 .exe

# 輸出：
#   dist\PrintFilamentTracker.exe          ← 免安裝版
#   dist\PrintFilamentTracker-1.2.0.msi   ← 含安裝精靈（桌面捷徑、啟動選項）
```

```bash
# macOS
bash scripts/build_exe.sh --version=1.2.0
# 輸出：dist/PrintFilamentTracker.app
```

**版本號管理**：版本號透過 `-Version "x.x.x"`（Windows）或 `--version=x.x.x`（macOS）傳入建置腳本，同時需更新 `file_version_info.txt`（Windows PE 標頭）與 `PrintFilamentTracker-mac.spec` 中的預設值。

**MSI 打包前置需求（Windows）**：

```powershell
# 安裝 WiX v4（需要 .NET SDK）
dotnet tool install --global wix --version "4.*"
# WixToolset.UI.wixext 擴充功能由建置腳本自動安裝，無需手動處理
```

建置腳本流程：PNG 圖示轉換（`.ico`，含 512×512）→ PyInstaller 打包 → 輸出驗證 → WiX MSI 打包（含安裝精靈 UI）。

---

## 新增翻譯 Key

### 標準流程

1. **同時**修改 `web/translations/zh.json` 和 `web/translations/en.json`，Key 路徑、縮排必須完全一致

2. 命名規則：
   - `section.key`：`settings.save_btn`
   - `section.subsection.key`：`flash.backup.done`
   - 常用 section：`nav`, `common`, `status`, `dashboard`, `tasks`, `spools`, `printers`, `mapping`, `analytics`, `settings`, `flash`

3. 支援參數替換：JSON 中使用 `{placeholder}`，呼叫時傳入同名 kwarg

**範例**

```json
// zh.json
{
  "settings": {
    "sync_success": "同步完成，共匯入 {count} 筆任務"
  }
}

// en.json
{
  "settings": {
    "sync_success": "Sync complete, imported {count} tasks"
  }
}
```

```python
# Python 使用
from web.i18n import t
msg = t("settings.sync_success", count=42)

# Jinja2 使用
{{ t('settings.sync_success', count=stats.count) }}
```

4. 驗證 JSON 格式：

```bash
.venv/Scripts/python.exe -c "
import json
json.load(open('web/translations/zh.json', encoding='utf-8'))
json.load(open('web/translations/en.json', encoding='utf-8'))
print('OK')
"
```

---

## 新增語言

1. 在 `web/translations/` 建立 `{lang_code}.json`（如 `ja.json`）

2. 複製 `en.json` 的全部 key 結構，提供譯文

3. `_discover_langs()` 自動掃描目錄，**無需修改任何 Python 程式碼**

4. 語言切換 UI 會自動出現新語言選項（語言名稱取自 key `lang.name`，若無則顯示 lang code）

---

## 新增資料庫欄位（Schema 遷移）

PrintFilamentTracker 使用 `ALTER TABLE ADD COLUMN` 方式遷移，**禁止** DROP TABLE 或重建。

### 流程

1. 在 `src/db.py` 的 `_initialize_schema(conn)` 中加入遷移呼叫：

```python
def _initialize_schema(conn):
    # ... 現有表建立 ...
    
    # 新增欄位遷移（防重複加入）
    _migrate_add_column(conn, "filament_spool", "brand TEXT")
    _migrate_add_column(conn, "print_task", "quality_profile TEXT")
```

2. `_migrate_add_column` 函數簽名：

```python
def _migrate_add_column(conn, table: str, column_def: str):
    """
    column_def 範例:
      "brand TEXT"
      "price REAL DEFAULT 0"
      "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
    """
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # 欄位已存在，跳過
```

3. 在對應的 CRUD 函數中加入新欄位的讀寫邏輯（`src/filament.py`、`src/printer.py` 等）

4. 在 `web/templates/` 更新表單與列表模板

5. 若有翻譯需求，同時更新 `zh.json` 與 `en.json`

---

## 新增 Web 路由

### 新增獨立頁面

1. 在 `web/routes/` 新建 `{feature}.py`：

```python
# web/routes/feature.py
from flask import Blueprint, render_template, request, flash, redirect, url_for
from src.db import get_connection
from web.i18n import t

bp = Blueprint("feature", __name__)

@bp.route("/")
def index():
    conn = get_connection(current_app.config["DB_PATH"])
    items = []  # 查詢邏輯
    return render_template("feature/index.html", items=items)
```

2. 在 `web/app.py` 的 `create_app()` 中註冊：

```python
from web.routes import feature
app.register_blueprint(feature.bp, url_prefix='/feature')
```

3. 在 `web/templates/feature/` 建立 HTML 模板（繼承 `base.html`）：

```html
{% extends "base.html" %}
{% block title %}{{ t('nav.feature') }}{% endblock %}
{% block content %}
<!-- 頁面內容 -->
{% endblock %}
```

4. 在 `web/templates/base.html` 的導覽列加入連結：

```html
<li><a href="{{ url_for('feature.index') }}">{{ t('nav.feature') }}</a></li>
```

5. 在 `zh.json` 與 `en.json` 加入 `nav.feature` 翻譯

### 新增 HTMX Fragment 路由

```python
@bp.route("/<int:item_id>/update", methods=["POST"])
def update_item(item_id):
    # ... 業務邏輯 ...
    # 回傳 HTML fragment，不使用完整模板
    return render_template("feature/_item_row.html", item=updated_item)
```

Fragment 模板不繼承 `base.html`，只包含一行 `<tr>` 或 `<div>`。

---

## 使用 Jinja2 時區 Filter

模板中使用 `tz_format` / `tz_date` 顯示本地化時間：

```html
<!-- 格式化日期時間（預設 %Y-%m-%d %H:%M） -->
{{ task.started_at | tz_format }}

<!-- 自訂格式 -->
{{ task.started_at | tz_format("%Y/%m/%d %H:%M") }}

<!-- 只顯示日期（用於熱力圖、每日報告等） -->
{{ task.started_at | tz_date }}
```

Filter 在 `create_app()` 時依 DB 設定的 `display_tz_offset_minutes`（分鐘）動態注冊，開發環境預設 UTC+0。更改時區設定後，`set_timezone()` 路由會即時呼叫 `_make_tz_filters()` 更新 filter；生產環境無需重啟。

---

## 新增分析圖表

### 1. 後端查詢（src/analytics.py）

```python
def get_xxx_stats(conn) -> list[dict]:
    """回傳圖表所需資料，格式依前端圖表庫決定"""
    rows = conn.execute("""
        SELECT strftime('%Y-%m', started_at) AS month, 
               COUNT(*) AS count,
               SUM(total_weight_g) AS weight
        FROM print_task
        WHERE started_at IS NOT NULL
        GROUP BY month
        ORDER BY month
    """).fetchall()
    return [{"month": r["month"], "count": r["count"], "weight": r["weight"]} for r in rows]
```

### 2. 路由更新（web/routes/analytics.py）

```python
from src.analytics import get_xxx_stats

@bp.route("/")
def index():
    conn = get_connection(current_app.config["DB_PATH"])
    xxx_stats = get_xxx_stats(conn)
    return render_template("analytics/index.html", xxx_stats=xxx_stats, ...)
```

### 3. 前端模板（web/templates/analytics/）

圖表資料透過 Jinja2 注入為 JSON，搭配 Chart.js 等前端圖表庫：

```html
<canvas id="xxxChart"></canvas>
<script>
const xxxData = {{ xxx_stats | tojson }};
new Chart(document.getElementById('xxxChart'), {
    type: 'bar',
    data: {
        labels: xxxData.map(d => d.month),
        datasets: [{
            label: '{{ t("analytics.xxx_label") }}',
            data: xxxData.map(d => d.count)
        }]
    }
});
</script>
```

---

## 新增 CLI 子指令

在 `src/main.py` 的 `main()` 函數中加入新的 subparser：

```python
def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    
    # 現有指令...
    
    # 新增指令
    p_xxx = subparsers.add_parser("xxx", help="執行 xxx 操作")
    p_xxx.add_argument("--option", type=str, default="default", help="選項說明")
    
    args = parser.parse_args()
    
    if args.command == "xxx":
        config = load_config()
        conn = get_connection(config.output_dir / "tracker.db")
        do_xxx(conn, option=args.option)
```

---

## 圖片上傳與驗證

### 驗證邏輯

```python
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

def _is_valid_image(header: bytes) -> bool:
    if header[:8] == b"\x89PNG\r\n\x1a\n":  return True  # PNG
    if header[:3] == b"\xff\xd8\xff":        return True  # JPEG
    if header[:4] in (b"GIF87a", b"GIF89a"): return True  # GIF
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP": return True  # WebP
    return False

# 使用方式
file = request.files["image"]
ext = Path(file.filename).suffix.lower()
if ext not in ALLOWED_EXTENSIONS:
    flash("不支援的圖片格式")
    return redirect(...)

header = file.read(12)
file.seek(0)
if not _is_valid_image(header):
    flash("圖片格式驗證失敗")
    return redirect(...)
```

### 儲存路徑規則

| 類型 | 路徑 | 命名 |
|------|------|------|
| 手動任務封面 | `data/covers/` | `m{task_id}.{ext}` |
| 雲端任務封面 | `data/covers/` | `{external_id}.png` |
| Printer 圖片 | `data/covers/` | `p{printer_id}.{ext}` |

### DB commit 先於檔案寫入

```python
# 正確順序（避免 DB 成功但檔案失敗的不一致）
conn.execute("UPDATE print_task SET cover_url=? WHERE id=?", (cover_url, task_id))
conn.commit()
# DB 已確認，再做檔案 I/O
file.save(cover_path)
```

### 雲端封面圖補圖機制

雲端任務封面圖（`{external_id}.png`）在匯入時可能因網路失敗或 URL 過期而未下載成功。`/covers/` 路由在檔案缺失時會嘗試自動補圖：

1. 確認檔名為純數字 stem + `.png`（雲端封面格式）
2. 查 10 分鐘負快取，近期失敗直接跳過
3. 呼叫 `try_redownload_cover()`：從 `raw_json.cover` 取得原始 URL 重新下載
4. 下載成功後原子寫入（`.tmp` → `.png`），失敗則記入負快取

下載內容與匯入時一致，套用相同的 URL 白名單、10 MB 大小限制與 magic bytes 驗證（`_is_valid_image_bytes()`）。

---

## HTMX Fragment 開發

### 基本模式

```html
<!-- 觸發 HTMX 請求的按鈕 -->
<button hx-post="/mapping/{{ ptf.id }}/map"
        hx-include="[name='spool_id']"
        hx-target="closest tr"
        hx-swap="outerHTML">
  {{ t('common.map') }}
</button>

<!-- 路由回傳 HTML fragment -->
<!-- web/templates/mapping/mapped_row.html -->
<tr>
  <td>{{ task.print_name }}</td>
  <td>{{ spool.color_name }}</td>
  <!-- ... -->
</tr>
```

### CSRF Token（base.html 已全域設定）

```javascript
// base.html 中的全域設定
document.body.addEventListener('htmx:configRequest', (e) => {
    e.detail.headers['X-CSRFToken'] = '{{ csrf_token() }}';
});
```

所有 HTMX POST 請求自動帶上 CSRF token，路由無需額外處理。

### 狀態輪詢（polling）

```html
<!-- 每 2 秒輪詢 -->
<div id="sync-status"
     hx-get="/settings/sync/status"
     hx-trigger="every 2s"
     hx-swap="outerHTML">
  <!-- 初始內容 -->
</div>
```

路由回傳新的 fragment；若想停止輪詢，回傳不帶 `hx-trigger` 的 HTML。

---

## 主題樣式客製化

### CSS 變數系統

`web/static/style.css` 使用 CSS 自訂屬性（CSS Variables）定義設計 token。

```css
:root {
  --card-border-radius: 12px;
  --spacing-section: 2rem;
  --shadow-card: 0 2px 12px rgba(0,0,0,0.08);
  /* ... */
}

[data-theme="dark"] {
  --shadow-card: 0 2px 12px rgba(0,0,0,0.3);
  /* 深色主題覆蓋 */
}
```

### Pico CSS 覆蓋層

Pico CSS 本身也使用大量 CSS Variables，可在 `:root` 中覆蓋：

```css
:root {
  --pico-primary: #1a73e8;           /* 主色 */
  --pico-primary-hover: #1557b0;
  --pico-border-radius: 8px;
  --pico-font-size: 0.9rem;
}
```

### 主題切換邏輯（base.html）

```javascript
// base.html 內聯 JS
const theme = localStorage.getItem('theme') ||
    (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
document.documentElement.setAttribute('data-theme', theme);

document.getElementById('theme-toggle').addEventListener('click', () => {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
});
```

---

## 日誌與除錯

### 日誌等級

```python
# web/app.py
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
```

在任何模組中使用：

```python
import logging
logger = logging.getLogger(__name__)

logger.debug("詳細除錯資訊")
logger.info("一般事件")
logger.warning("警告但不中斷")
logger.error("錯誤，但程式繼續執行")
logger.exception("例外（自動帶 traceback）")
```

### 即時查看日誌

```powershell
Get-Content data\logs\app.log -Wait -Tail 100
```

### SQLite 除錯

```python
# 直接連線資料庫查詢
.venv/Scripts/python.exe -c "
import sqlite3
conn = sqlite3.connect('data/tracker.db')
conn.row_factory = sqlite3.Row
for row in conn.execute('SELECT * FROM print_task LIMIT 5'):
    print(dict(row))
"
```

### Flask Debug Toolbar（選用）

```bash
.venv/Scripts/python.exe -m pip install flask-debugtoolbar
```

```python
# web/app.py（開發環境）
from flask_debugtoolbar import DebugToolbarExtension
toolbar = DebugToolbarExtension(app)
```

---

## 常見問題

### Q: 啟動時提示 `SECRET_KEY not set`

`.env` 中加入：

```env
SECRET_KEY=your-random-32-char-key
```

或讓系統自動生成（每次重啟 Session 失效）。

### Q: Token 過期 / 401 錯誤

Bambu Cloud Token 有效期約 3 個月。到設定頁重新登入，Token 自動更新至資料庫。

### Q: 同步後任務不顯示列印機名稱

Bambu Cloud API 回傳的 `deviceId` 需要與資料庫中 `printer.device_id` 一致。先到 Printer 管理頁新增印表機並填入正確的設備 ID，再執行同步。

### Q: 圖片上傳失敗 `413 Payload Too Large`

Flask 預設最大請求大小為 10 MB（`MAX_CONTENT_LENGTH`）。調整 `web/app.py`：

```python
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB
```

### Q: 如何重置資料庫

```bash
# 備份現有資料庫
cp data/tracker.db data/tracker.db.bak

# 刪除並重新初始化
rm data/tracker.db
.venv/Scripts/python.exe -c "from src.db import get_connection; get_connection('data/tracker.db').close()"
```

### Q: 多語言 key 遺漏（顯示 key 路徑而非翻譯文字）

表示翻譯 JSON 中找不到該 key。`t()` 在找不到時會直接回傳 key 字串作為 fallback。

排查步驟：
1. 確認 `zh.json` 中 key 路徑正確（注意巢狀層級）
2. 驗證 JSON 格式：`.venv/Scripts/python.exe -c "import json; json.load(open('web/translations/zh.json', encoding='utf-8'))"`
3. 重啟 Flask 伺服器（翻譯在啟動時載入）

### Q: HTMX 請求被 CSRF 拒絕（403）

確認 `base.html` 中有以下 JavaScript（HTMX 配置必須在 HTMX 載入後執行）：

```javascript
document.body.addEventListener('htmx:configRequest', (e) => {
    e.detail.headers['X-CSRFToken'] = '{{ csrf_token() }}';
});
```
