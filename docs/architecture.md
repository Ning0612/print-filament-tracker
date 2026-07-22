# 架構說明

本文說明 FilamentLedger 的模組設計、資料流、資料庫 Schema 與 API 介接。

## 目錄

- [整體架構](#整體架構)
- [模組職責](#模組職責)
- [資料庫 Schema](#資料庫-schema)
- [Bambu Cloud API](#bambu-cloud-api)
- [資料流](#資料流)
- [Web 路由架構](#web-路由架構)
- [後台排程](#後台排程)
- [多語言系統](#多語言系統)
- [安全機制](#安全機制)
- [關鍵設計決策](#關鍵設計決策)
- [欄位對應（Cloud → DB）](#欄位對應cloud--db)

---

## 整體架構

```
┌─────────────────────────────────────────────────────────────┐
│                        Browser / CLI                         │
└──────────┬────────────────────────────────────┬─────────────┘
           │ HTTP                               │ CLI
           ▼                                    ▼
┌──────────────────────┐              ┌─────────────────────┐
│   Flask Web App      │              │   src/main.py       │
│   web/app.py         │              │   (argparse CLI)    │
│   web/routes/*.py    │              └────────┬────────────┘
│   web/templates/     │                       │
│   web/i18n.py        │                       │
└──────────┬───────────┘                       │
           │ imports                            │ imports
           ▼                                    ▼
┌─────────────────────────────────────────────────────────────┐
│                     Business Logic  (src/)                   │
│                                                              │
│  config.py ─ auth.py ─ cloud_client.py ─ ingestion.py       │
│       │                                         │            │
│       ▼                                         ▼            │
│  db.py (SQLite CRUD)    filament.py   analytics.py          │
│       │                 printer.py    backup.py              │
│       ▼                                         ▼            │
│  data/tracker.db        data/covers/  data/backups/         │
└─────────────────────────────────────────────────────────────┘
```

### 核心設計原則

- **業務邏輯與 Web 框架分離**：`src/` 目錄中無任何 Flask 依賴，可獨立測試與在 CLI 使用
- **SQLite 作為唯一持久層**：無需額外資料庫服務，適合單機部署
- **HTMX 輕量互動**：僅在耗材對應頁面與設定頁面使用 HTMX，其餘為標準表單提交
- **計算欄位不落地**：`remaining_g`、`usage_ratio`、`status` 皆為動態計算，不存入資料庫

---

## 模組職責

### src/ — 業務邏輯

| 檔案 | 職責 | 主要 API |
|------|------|---------|
| `config.py` | 讀取 `.env` 與 OS 環境變數，驗證必填欄位，返回 `AppConfig` dataclass | `load_config()` |
| `auth.py` | 組裝 Bearer Authorization header；Token 前 8 字遮罩（用於日誌） | `build_auth_headers(token)`, `mask_token(token)` |
| `cloud_client.py` | 分頁拉取 Bambu Cloud API，儲存原始回應至 `raw_tasks.json`；處理 401/429/逾時 | `BambuCloudClient.fetch_all_tasks()` |
| `normalize.py` | 歷史遺留，目前轉換邏輯已移入 `ingestion.py` | — |
| `db.py` | SQLite 連線工廠、Schema 初始化與遷移、全部表的 CRUD | `get_connection(db_path)`, `_migrate_add_column()` |
| `ingestion.py` | Cloud hits → DB pipeline：printer upsert、task insert、filament 建立、封面圖下載與補圖 | `ingest_raw_tasks(hits, db_path, covers_dir)`, `run_ingestion_from_file(raw_file, db_path)`, `run_ingestion_from_cloud(config, db_path)`, `try_redownload_cover(external_id, covers_dir, db_path)` |
| `filament.py` | Spool CRUD、計算欄位（remaining、status）、Mapping 流程、JSON/CSV 匯入匯出 | `read_spool(db_path, id)`, `list_spools(db_path)`, `do_map(db_path, ptf_id, spool_id)` |
| `printer.py` | Printer CRUD、統計資訊（任務數、總重量、總時長） | `read_printer(db_path, printer_id)`, `list_printers_with_stats(db_path)` |
| `analytics.py` | 熱力圖、材料分布、月度趨勢、Printer 使用率、成本分析、時長分布、週間活動分布、每日報告摘要 | `get_heatmap_payload()`, `get_material_chart_payload()`, `get_monthly_trend_payload()`, `get_daily_detail_payload()`, `get_weekday_stats_payload()`, `get_spool_cost_ranking_payload()` |
| `export_json.py` | 匯出 `data/print_history.json` | `export_json(records: list[dict], output_path: Path)` |
| `export_csv.py` | 匯出 `data/print_history.csv`（扁平化） | `export_csv(records: list[dict], output_path: Path)` |
| `backup.py` | SQLite 備份（`sqlite3.Connection.backup()`）、還原、舊檔清理 | `run_backup()`, `restore_from_backup()` |
| `paths.py` | 跨平台使用者資料目錄解析，凍結/開發模式二態支援 | `get_base_dir()`, `ensure_base_dir()`, `resolve_output_dir()` |
| `main.py` | CLI 入口：`import`, `unmapped`, `map`, `export`, `filament status`, `web` 子指令 | `main()` |

### web/ — Flask 應用

| 檔案 | 職責 |
|------|------|
| `app.py` | `create_app(db_path)` 工廠：Blueprint 註冊、後台排程啟動、CSRF 初始化、Session 設定、413 handler、封面圖缺失自動補圖（含負快取） |
| `i18n.py` | 翻譯系統：`t(key, **kwargs)`、語言自動落回、`_discover_langs()`、Jinja2 context 注入 |
| `routes/dashboard.py` | `GET /` |
| `routes/tasks.py` | `GET/POST /tasks/`，手動任務 CRUD，圖片上傳驗證 |
| `routes/spools.py` | `GET/POST /spools/`，JSON/CSV 匯入匯出 |
| `routes/printers.py` | `GET/POST /printers/`，圖片上傳 |
| `routes/mapping.py` | `GET /mapping/`，HTMX map/unmap/unignore、material inline edit、remap fragment |
| `routes/analytics.py` | `GET /analytics/`、`GET /analytics/day/<date>`（每日報告）、`GET /analytics/heatmap`（年份切換 fragment） |
| `routes/settings.py` | 登入流程、Token 管理、同步觸發、備份/還原、後台排程控制、時區設定 |
| `routes/lang.py` | `POST /set-lang`，語言切換存 Session |

---

## 資料庫 Schema

### 表結構

#### printer
```sql
CREATE TABLE printer (
    id          INTEGER PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    device_id   TEXT UNIQUE,
    model       TEXT,
    purchased_at DATETIME,
    image_url   TEXT,
    note        TEXT
);
```

#### filament_spool
```sql
CREATE TABLE filament_spool (
    id               INTEGER PRIMARY KEY,
    uid              TEXT UNIQUE NOT NULL,
    material         TEXT,
    color_name       TEXT,
    color_hex        TEXT,            -- #RRGGBB
    initial_weight_g REAL NOT NULL,
    price            REAL,
    purchased_at     DATETIME,
    opened_at        DATETIME,
    product_url      TEXT,
    note             TEXT
);
```

> `remaining_weight_g`、`usage_ratio`、`status` 均為動態計算，**不儲存**於此表。

#### print_task
```sql
CREATE TABLE print_task (
    id               INTEGER PRIMARY KEY,
    external_id      INTEGER UNIQUE NOT NULL,  -- 雲端 id；手動任務為負整數
    print_name       TEXT,
    printer_id       INTEGER REFERENCES printer(id),
    started_at       DATETIME,
    ended_at         DATETIME,
    duration_seconds INTEGER,
    total_weight_g   REAL,
    cover_url        TEXT,                     -- 如 /covers/m42.jpg
    raw_json         TEXT,                     -- API 原始回應（JSON 字串）
    is_manual        INTEGER NOT NULL DEFAULT 0,  -- 1 = 手動新增
    plate_index      INTEGER,                  -- 板片編號（多板列印）
    plate_name       TEXT,                     -- 板片名稱
    status           INTEGER                   -- 列印狀態：2=completed, 3=failed, 其他=in progress
);
```

> 手動任務的 `plate_index`、`plate_name`、`status` 皆為 NULL。

#### print_task_filament
```sql
CREATE TABLE print_task_filament (
    id                INTEGER PRIMARY KEY,
    print_task_id     INTEGER NOT NULL REFERENCES print_task(id),
    filament_spool_id INTEGER REFERENCES filament_spool(id),  -- NULL = 未對應
    slot_id           INTEGER,
    used_weight_g     REAL,
    color_hex         TEXT,
    material          TEXT,
    is_ignored        INTEGER NOT NULL DEFAULT 0,  -- 1 = 忽略此耗材
    mapped_at         DATETIME
);
```

#### app_config
```sql
CREATE TABLE app_config (
    key   TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
);
```

儲存可透過 UI 調整的設定值（Token、同步間隔等）。

### 索引

```sql
CREATE UNIQUE INDEX idx_print_task_external_id ON print_task(external_id);
CREATE INDEX idx_ptf_spool   ON print_task_filament(filament_spool_id);
CREATE INDEX idx_ptf_task    ON print_task_filament(print_task_id);
CREATE INDEX idx_pt_started  ON print_task(started_at);
CREATE INDEX idx_pt_printer  ON print_task(printer_id);
```

### Schema 遷移規則

新增欄位**一律**透過 `_migrate_add_column(conn, table, column_def)` 以 `ALTER TABLE ADD COLUMN` 方式進行，並使用 `try/except OperationalError` 防止重複加入。

**嚴禁** DROP TABLE 或重建 Schema（避免破壞現有資料）。

### 計算欄位邏輯（Python）

```python
used_weight_g  = SUM(ptf.used_weight_g WHERE filament_spool_id = spool.id)
remaining_g    = spool.initial_weight_g - used_weight_g

if spool.opened_at is None and used_weight_g == 0:
    status = "sealed"
elif remaining_g <= 0:
    status = "empty"
elif remaining_g / spool.initial_weight_g < 0.1:
    status = "low"
else:
    status = "active"
```

---

## Bambu Cloud API

### 端點

```
GET https://api.bambulab.com/v1/user-service/my/tasks
Authorization: Bearer {token}
User-Agent: FilamentLedger/1.0 (community; unofficial Bambu Lab integration)
?limit=500&after={cursor}
```

`BAMBU_REGION=china` 時使用不同的 API Base URL。

### 回應結構

```json
{
  "total": 1234,
  "hits": [
    {
      "id": 12345,
      "title": "列印名稱",
      "deviceId": "00M03XXXXXX",
      "deviceName": "My X1C",
      "deviceModel": "X1 Carbon",
      "startTime": "2024-04-15T10:30:00",
      "endTime": "2024-04-15T12:45:30",
      "costTime": 8130,
      "weight": 45.2,
      "cover": "https://cdn.bambulab.com/cover/...",
      "amsDetailMapping": [
        {
          "position": 0,
          "filamentType": "PLA",
          "sourceColor": "FF6B35FF",
          "weight": 45.2
        }
      ]
    }
  ],
  "nextCursor": "eyJpZCI6..."
}
```

### 欄位對應

| Cloud 欄位 | DB 欄位 | 備注 |
|-----------|---------|------|
| `id` | `print_task.external_id` | |
| `title` | `print_task.print_name` | fallback: `design_title` → `name` |
| `startTime` | `print_task.started_at` | |
| `endTime` | `print_task.ended_at` | |
| `costTime` | `print_task.duration_seconds` | 秒 |
| `weight` | `print_task.total_weight_g` | 克 |
| `status` | `print_task.status` | 整數：2=completed, 3=failed, 其他=in progress |
| `plateIndex` | `print_task.plate_index` | 多板列印時的板片編號 |
| `plateName` | `print_task.plate_name` | 板片名稱，去除空白後為空則存 NULL |
| `deviceId` | 查 `printer.device_id` 取 `printer_id` | |
| 完整物件 | `print_task.raw_json` | 序列化為 JSON 字串 |
| `amsDetailMapping[i].position` | `print_task_filament.slot_id` | |
| `amsDetailMapping[i].filamentType` | `print_task_filament.material` | |
| `amsDetailMapping[i].sourceColor` | `print_task_filament.color_hex` | RRGGBBAA → #RRGGBB |
| `amsDetailMapping[i].weight` | `print_task_filament.used_weight_g` | |

### 分頁邏輯

```python
# cloud_client.py 核心邏輯
cursor = None
all_hits = []
while True:
    params = {"limit": 500}
    if cursor:
        params["after"] = cursor
    data = http_get(endpoint, params=params, headers=auth_headers)
    all_hits.extend(data["hits"])
    cursor = data.get("nextCursor")
    if not cursor or len(data["hits"]) == 0:
        break
```

### 錯誤處理

| HTTP 狀態碼 | 異常類 | 處理方式 |
|------------|--------|---------|
| 401 | `AuthError` | 提示重新登入取得新 Token |
| 429 | `RateLimitError` | 等待並重試（指數退避） |
| 其他 4xx/5xx | `NetworkError` | 記錄日誌，拋出異常 |
| 逾時 | `NetworkError` | 使用 `requests.Session` timeout=30s |

---

## 資料流

### 雲端同步流程

```
Browser/CLI
    │
    ├─ web/routes/settings.py (POST /settings/sync)
    │      └─ _run_sync_job()
    │              │
    │              ├─ src/config.py : load_config()
    │              ├─ src/cloud_client.py : fetch_all_tasks() → raw_tasks.json
    │              └─ src/ingestion.py : ingest_raw_tasks(hits, db_path, covers_dir)
    │                      │
    │                      ├─ printer upsert (INSERT OR IGNORE on device_id)
    │                      ├─ print_task UPSERT：新任務 INSERT；已存在任務更新 ended_at/duration/status 等可變欄位
    │                      ├─ print_task_filament 批次同步（sync_task_filaments）：補齊 NULL slot；當雲端已提供真實 slot 資料時，刪除同一任務中 slot_id IS NULL 且 filament_spool_id IS NULL 的舊 fallback rows
    │                      └─ cover image download → data/covers/{external_id}.png（原子寫入 .tmp → .png）
    │
    └─ HTMX polling every 2s → /settings/sync/status fragment
```

### 耗材對應流程

```
Browser
    │
    ├─ GET /mapping/ → unmapped list (filament_spool_id IS NULL AND is_ignored=0)
    │
    ├─ User selects spool + POST /mapping/<ptf_id>/map
    │      └─ UPDATE print_task_filament SET filament_spool_id=X, mapped_at=NOW
    │      └─ HTMX 回傳 mapped_row.html fragment → 替換該行
    │
    └─ User clicks ignore + POST /mapping/<ptf_id>/map（spool_id="__ignore__"）
           └─ UPDATE print_task_filament SET is_ignored=1
           └─ HTMX 回傳 ignored_row.html fragment
```

### 手動任務封面圖流程

```
POST /tasks/new (multipart/form-data)
    │
    ├─ 1. 驗證副檔名白名單 (.png/.jpg/.jpeg/.webp/.gif)
    ├─ 2. 讀取前 12 bytes，驗證 magic bytes
    ├─ 3. 計算預期路徑 covers/m{task_id}.{ext}（尚未知 task_id）
    ├─ 4. INSERT print_task → 取得 task_id
    ├─ 5. cover_url = /covers/m{task_id}.{ext}
    ├─ 6. UPDATE print_task SET cover_url = ...
    └─ 7. 寫入檔案（DB 已 commit，確保原子性）
```

---

## Web 路由架構

### Blueprint 組織

```python
# web/app.py
from web.routes import dashboard, tasks, spools, printers, mapping, analytics, settings, lang

app.register_blueprint(dashboard.bp)
app.register_blueprint(lang.bp)                           # /set-lang（無 prefix）
app.register_blueprint(tasks.bp,     url_prefix='/tasks')
app.register_blueprint(spools.bp,    url_prefix='/spools')
app.register_blueprint(printers.bp,  url_prefix='/printers')
app.register_blueprint(mapping.bp,   url_prefix='/mapping')
app.register_blueprint(analytics.bp, url_prefix='/analytics')
app.register_blueprint(settings.bp)                       # prefix 定義於 blueprint 內部
```

### 路由完整清單

| 路由 | 方法 | 說明 |
|------|------|------|
| `/` | GET | Dashboard |
| `/tasks/` | GET | 任務列表（搜尋、分頁） |
| `/tasks/<id>` | GET | 任務詳情 |
| `/tasks/new` | GET/POST | 新增手動任務 |
| `/tasks/<id>/edit` | GET/POST | 編輯手動任務 |
| `/tasks/<id>/delete` | POST | 刪除手動任務 |
| `/spools/` | GET | Spool 列表 |
| `/spools/<id>` | GET | Spool 詳情（用量統計與列印歷史） |
| `/spools/new` | GET/POST | 新增 Spool |
| `/spools/<id>/edit` | GET/POST | 編輯 Spool |
| `/spools/<id>/delete` | POST | 刪除 Spool |
| `/spools/import` | POST | 匯入 Spool (JSON/CSV) |
| `/spools/export/json` | GET | 匯出 Spool（JSON） |
| `/spools/export/csv` | GET | 匯出 Spool（CSV） |
| `/printers/` | GET | Printer 列表 |
| `/printers/new` | GET/POST | 新增 Printer |
| `/printers/<id>/edit` | GET/POST | 編輯 Printer |
| `/printers/<id>/delete` | POST | 刪除 Printer |
| `/mapping/` | GET | 耗材對應（三頁籤） |
| `/mapping/<ptf_id>/map` | POST | 對應耗材，或傳入 `__ignore__` 值以忽略（HTMX） |
| `/mapping/<ptf_id>/unmap` | POST | 解除對應（HTMX） |
| `/mapping/<ptf_id>/unignore` | POST | 恢復忽略（HTMX） |
| `/mapping/<ptf_id>/mapped-row` | GET | 已對應列 fragment（HTMX） |
| `/mapping/<ptf_id>/remap-form` | GET | 重新對應選擇器 fragment（HTMX） |
| `/mapping/<ptf_id>/remap` | POST | 重新對應（HTMX） |
| `/mapping/<ptf_id>/material-edit` | GET | material inline 編輯表單（HTMX） |
| `/mapping/<ptf_id>/material` | POST | 儲存 material 異動（HTMX） |
| `/mapping/<ptf_id>/material-cancel` | GET | 取消 material 編輯（HTMX） |
| `/mapping/<ptf_id>/detail-remap-form` | GET | 任務詳情頁重新對應表單（HTMX） |
| `/mapping/<ptf_id>/detail-remap` | POST | 任務詳情頁重新對應（HTMX） |
| `/mapping/<ptf_id>/detail-unmap` | POST | 任務詳情頁解除對應（HTMX） |
| `/mapping/<ptf_id>/detail-row` | GET | 任務詳情頁耗材列 fragment（HTMX） |
| `/analytics/` | GET | 分析頁面 |
| `/analytics/day/<date>` | GET | 每日報告（任務圖庫、時間軸、耗材摘要） |
| `/analytics/heatmap` | GET | 熱力圖 fragment（HTMX，按年份） |
| `/settings/` | GET | 設定主頁 |
| `/settings/login/form` | GET | 登入表單 fragment |
| `/settings/login/step1` | POST | 登入第一步（帳密） |
| `/settings/login/step2` | POST | 登入第二步（2FA / 驗證碼） |
| `/settings/sync` | POST | 手動同步 |
| `/settings/sync/status` | GET | 同步狀態 fragment（HTMX polling） |
| `/settings/auto-sync` | POST | 設定自動同步間隔 |
| `/settings/auto-sync/status` | GET | 自動同步設定狀態 fragment |
| `/settings/backup` | POST | 手動備份 |
| `/settings/backup/status` | GET | 備份狀態 fragment（HTMX polling） |
| `/settings/backup/config` | POST | 設定備份間隔與保留份數 |
| `/settings/restore` | POST | 還原備份（還原前自動備份當前資料庫，需輸入確認字詞） |
| `/settings/timezone` | POST | 設定時區偏移（UTC offset，分鐘） |
| `/set-lang` | POST | 切換語言 |
| `/covers/<filename>` | GET | 取得封面圖靜態檔案；雲端封面缺失時自動從 raw_json 重新下載（含 10 分鐘負快取） |

---

## 後台排程

### 自動同步（settings.py）

```python
_sync_state  = {"status": "idle", ...}   # 全域共享狀態（dict）
_sync_lock   = threading.Lock()           # 防止並行觸發

def _run_sync_job():
    with _sync_lock:
        _sync_state["status"] = "running"
        try:
            ...  # fetch + ingest
            _sync_state["status"] = "done"
        except Exception as e:
            _sync_state["status"] = "error"

def _scheduler_thread():
    while True:
        time.sleep(interval_minutes * 60)
        _run_sync_job()
```

### 自動備份（settings.py）

類似同步排程，使用 `_backup_lock`（非阻塞 `acquire(blocking=False)`）確保：
- 手動備份與自動備份不並行執行
- 若無法取鎖，跳過本次自動備份（不等待）

### 生命週期

- 排程執行緒在 `create_app()` 時啟動（`daemon=True`，隨主程序終止）
- 僅在 `AUTO_SYNC_INTERVAL > 0` 或 `BACKUP_INTERVAL_MINUTES > 0` 時啟動對應執行緒
- Waitress 多執行緒模式下，排程執行緒與 Worker 執行緒共用同一進程

---

## 多語言系統

### 翻譯載入

```python
# web/i18n.py
def _load_translations():
    langs = {}
    for f in Path("web/translations").glob("*.json"):
        lang_code = f.stem
        langs[lang_code] = json.loads(f.read_text(encoding="utf-8"))
    return langs
```

翻譯在 `create_app()` 時一次性載入至記憶體。

### 翻譯查找

```python
def t(key: str, **kwargs) -> str:
    lang = session.get("lang", "zh")
    data = _translations.get(lang, _translations["zh"])
    
    # 支援巢狀 key：section.subsection.key
    value = data
    for part in key.split("."):
        value = value.get(part, key)
        if not isinstance(value, dict):
            break
    
    # 參數替換：{placeholder}
    if kwargs and isinstance(value, str):
        value = value.format(**kwargs)
    return value
```

### Jinja2 注入

```python
@app.context_processor
def inject_i18n():
    return {
        "t": t,
        "current_lang": session.get("lang", "zh"),
        "supported_langs": get_supported_langs()
    }
```

所有 template 皆可直接使用 `{{ t('key') }}`。

### Jinja2 時區 Filter

`create_app()` 依 `app_config` 中的 `display_tz_offset_minutes`（分鐘）動態注冊兩個 filter：

```python
# web/app.py
tz_fmt, tz_d = _make_tz_filters(tz_offset_minutes)
app.jinja_env.filters["tz_format"] = tz_fmt  # 回傳格式化字串
app.jinja_env.filters["tz_date"]   = tz_d    # 只回傳日期部分
```

模板使用方式：

```html
{{ task.started_at | tz_format }}           {# → "2025-03-01 14:30" #}
{{ task.started_at | tz_format("%Y/%m/%d") }} {# 自訂格式 #}
{{ task.started_at | tz_date }}             {# → "2025-03-01" #}
```

UTC 偏移從 DB `app_config`（key: `display_tz_offset_minutes`）讀取，預設為 0（UTC）。使用者在設定頁變更時區後，`web/routes/settings.py` 的 `set_timezone()` 即時重新呼叫 `_make_tz_filters()` 更新 filter，無需重啟。

---

## 安全機制

### CSRF 保護

使用 `Flask-WTF` 的 `CSRFProtect`，所有 POST/PUT/DELETE 請求自動驗證。

HTMX 請求在 `base.html` 中注入 CSRF token：

```html
<script>
document.body.addEventListener('htmx:configRequest', (e) => {
    e.detail.headers['X-CSRFToken'] = '{{ csrf_token() }}';
});
</script>
```

### Session 安全

```python
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "false") == "true"
)
```

### 圖片上傳驗證

```python
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAGIC_BYTES = {
    "png":  b"\x89PNG\r\n\x1a\n",
    "jpeg": b"\xff\xd8\xff",
    "gif":  b"GIF8",
    "webp": b"RIFF"     # 需同時驗證 offset 8 的 "WEBP"
}

def _is_valid_image(header: bytes) -> bool:
    return (header[:8] == MAGIC_BYTES["png"] or
            header[:3] == MAGIC_BYTES["jpeg"] or
            header[:4] == MAGIC_BYTES["gif"] or
            (header[:4] == MAGIC_BYTES["webp"] and header[8:12] == b"WEBP"))
```

### Token 遮罩

Token 在日誌與 UI 中僅顯示前 8 字元：

```python
def mask_token(token: str) -> str:
    return token[:8] + "..." if token and len(token) > 8 else "***"
```

### 封面圖 URL 白名單

從 Cloud API 下載封面圖時，驗證 URL 網域：

```python
ALLOWED_COVER_DOMAINS = {".bambulab.com", ".amazonaws.com"}
```

### 雲端封面圖自動補圖（on-demand re-download）

`/covers/<filename>` 路由在檔案不存在時，對純數字 stem 的 `.png` 請求觸發補圖流程：

```
GET /covers/12345678.png  →  file_path.exists() == False
    │
    ├─ 查負快取（in-memory dict，TTL 10 分鐘）
    │      ├─ 近期失敗 → 直接 send_from_directory（返回 404）
    │      └─ 未失敗或已過期 → 進入補圖
    │
    ├─ try_redownload_cover(external_id=12345678, ...)
    │      ├─ 查 DB raw_json WHERE external_id=? AND is_manual=0
    │      ├─ 解析 raw_json.cover 取得原始 URL
    │      ├─ _is_allowed_cover_url() 白名單驗證
    │      ├─ requests.get(url, timeout=15)
    │      ├─ 大小驗證（≤ 10 MB）
    │      ├─ _is_valid_image_bytes() magic bytes 驗證
    │      └─ 原子寫入：.tmp → .png（replace）
    │
    └─ 成功 → send_from_directory 正常返回
       失敗 → 記入負快取，send_from_directory 返回 404
```

**負快取**：以 `dict[external_id → failed_at]` 記錄失敗，上限 500 筆（超出清除最舊一半），TTL 10 分鐘。防止 URL 過期時每次請求都觸發 DB + 網路阻塞。

**安全防護**：路由入口驗證 `Path(filename).name == filename`，拒絕含子路徑或 `..` 的請求。

---

## 關鍵設計決策

### 為何使用 SQLite 而非 PostgreSQL？

此系統設計為本地單機部署，無並行寫入需求。SQLite 無需額外服務，備份只需複製單一檔案，符合「開箱即用」的設計目標。

### 為何計算欄位不存入 DB？

`remaining_g`、`status` 等屬於衍生資料，存入 DB 會帶來一致性風險（每次 mapping 更動都需同步更新）。動態計算雖稍慢，但資料保證正確。

### 為何手動任務使用負整數 external_id？

手動任務需要 `external_id NOT NULL UNIQUE` 約束（與雲端任務共用同一索引）。使用 `-time.time_ns()` 確保：
- 絕不與正整數的雲端 ID 衝突
- 單機環境下幾乎不可能重複（奈秒精度）
- 無需額外欄位區分類型（已有 `is_manual` flag）

### 為何不使用 SQLAlchemy？

專案體積小，直接使用 `sqlite3` 模組效能更高、依賴更少。Schema 遷移透過 `ALTER TABLE ADD COLUMN` 手動管理，足夠應對需求。

### HTMX 的使用邊界

HTMX 用於以下場景：
1. **Mapping 頁面的 Inline 編輯**（避免整頁重載破壞表格狀態）：對應、解除對應、忽略、material 編輯、重新對應
2. **任務詳情頁 Inline Spool Remap**（`/mapping/<id>/detail-*` 路由）：在任務詳情頁直接更換耗材對應，不必跳轉至 Mapping 頁面
3. **設定頁的同步/備份狀態輪詢**（long-polling 替代方案）：每 2 秒輪詢 `/settings/sync/status`、`/settings/backup/status`

其餘頁面均使用標準表單提交（Post-Redirect-Get 模式），降低複雜度。
