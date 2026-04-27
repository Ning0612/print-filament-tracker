# 部署指南

本文說明如何在 Windows 上部署 PrintFilamentTracker。

## 目錄

- [環境需求](#環境需求)
- [一鍵部署（推薦）](#一鍵部署推薦)
- [本機開發模式](#本機開發模式)
- [手動啟動伺服器](#手動啟動伺服器)
- [環境變數參考](#環境變數參考)
- [資料目錄結構](#資料目錄結構)
- [日誌管理](#日誌管理)
- [備份策略](#備份策略)

---

## 環境需求

| 項目 | 最低需求 |
|------|---------|
| Python | 3.10+ |
| 作業系統 | Windows 10 / 11 |
| 磁碟空間 | 500 MB（含封面圖快取） |
| 記憶體 | 256 MB |

---

## 一鍵部署（推薦）

`scripts/setup_deployment.ps1` 自動完成所有生產環境設定步驟。

### 前置作業

1. 建立虛擬環境並安裝依賴：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

2. 建立 `.env`：

```powershell
Copy-Item .env.example .env
```

編輯 `.env`，填入 `BAMBU_REGION`（`global` 或 `china`）。Bambu Token 可稍後在 Web 設定頁登入取得，不需要預先填入。

### 執行部署腳本

**建議以系統管理員身份執行 PowerShell**（Task Scheduler 需要管理員權限）：

```powershell
.\scripts\setup_deployment.ps1
```

腳本執行的步驟：

| 步驟 | 說明 |
|------|------|
| 1. 環境驗證 | 檢查 `.venv`、`.env` 存在 |
| 2. SECRET_KEY | 若 `.env` 尚未設定，自動生成 64 字元 hex 金鑰並寫入 |
| 3. Waitress 安裝 | 若尚未安裝，執行 `pip install waitress` |
| 4. Task Scheduler | 建立 `PrintFilamentTracker-Web` 任務，於使用者登入時自動啟動 Web 伺服器 |

### 腳本參數

```powershell
# 指定埠號（預設 5000）
.\scripts\setup_deployment.ps1 -WebPort 8080

# 略過 SECRET_KEY 步驟（.env 已有有效金鑰）
.\scripts\setup_deployment.ps1 -SkipSecretKey

# 略過 Task Scheduler 步驟（只安裝 Waitress、設定 SECRET_KEY）
.\scripts\setup_deployment.ps1 -SkipTaskScheduler
```

### 部署後啟動

```powershell
# 立即啟動（無需重新登入）
Start-ScheduledTask -TaskName "PrintFilamentTracker-Web"
```

或直接雙擊 `scripts\start_server.bat`。

瀏覽器開啟 `http://127.0.0.1:5000`。

### 管理排程任務

```powershell
# 查看任務狀態
Get-ScheduledTask -TaskName "PrintFilamentTracker-Web"

# 停止伺服器
Stop-ScheduledTask -TaskName "PrintFilamentTracker-Web"

# 重新啟動
Stop-ScheduledTask -TaskName "PrintFilamentTracker-Web"
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName "PrintFilamentTracker-Web"

# 移除任務
Unregister-ScheduledTask -TaskName "PrintFilamentTracker-Web" -Confirm:$false
```

---

## 本機開發模式

不需要 Waitress，使用 Flask 內建伺服器，支援熱重載。

```powershell
.venv\Scripts\python.exe -m flask --app web.app run --debug --host 127.0.0.1 --port 5000
```

> 開發模式啟用 Flask Debugger，**不可用於生產環境**。

---

## 手動啟動伺服器

若不想使用 Task Scheduler，可直接執行：

```powershell
# 雙擊或在 PowerShell 中執行
.\scripts\start_server.bat
```

`start_server.bat` 使用 Waitress 在 `http://127.0.0.1:5000` 啟動生產伺服器，關閉視窗即停止。

---

## 環境變數參考

所有設定透過 `.env` 提供，部分設定也可在 **Web 設定頁**直接調整。

| 變數名稱 | 預設值 | 說明 |
|---------|--------|------|
| `BAMBU_ACCESS_TOKEN` | — | Bambu Cloud Bearer Token（可在 Web 設定頁登入取得） |
| `BAMBU_REGION` | `global` | API 區域：`global` 或 `china` |
| `BAMBU_API_BASE` | 自動 | 覆寫 API 端點（可選） |
| `BAMBU_OUTPUT_DIR` | `data` | 資料輸出目錄 |
| `SECRET_KEY` | 自動生成 | Flask Session 加密金鑰（`setup_deployment.ps1` 自動處理） |
| `AUTO_SYNC_INTERVAL` | `0` | 自動同步間隔（分鐘），`0` = 停用；建議在 Web 設定頁設定 |
| `BACKUP_INTERVAL_MINUTES` | `0` | 自動備份間隔（分鐘），`0` = 停用；建議在 Web 設定頁設定 |
| `SESSION_COOKIE_SECURE` | `false` | 啟用 HTTPS-only cookie（搭配反向代理時設為 `true`） |

> `BAMBU_ACCESS_TOKEN` 也可透過 Web 設定頁登入後自動寫入資料庫。資料庫中的值優先於 `.env`。

---

## 資料目錄結構

首次啟動時自動建立：

```
data/
├── bambu.db          # SQLite 資料庫（自動初始化 Schema）
├── covers/           # 封面圖片
├── backups/          # 資料庫備份
└── logs/
    └── app.log       # 應用日誌（每 10 MB 輪轉，保留 5 份）
```

---

## 日誌管理

日誌位置：`data/logs/app.log`

- 單檔最大 10 MB，保留最近 5 份
- 格式：`YYYY-MM-DD HH:MM:SS LEVEL name: message`

即時查看：

```powershell
Get-Content data\logs\app.log -Wait -Tail 50
```

---

## 備份策略

### 自動備份（推薦）

在 **Web 設定頁 → 資料庫備份** 設定備份間隔與保留份數，無需修改設定檔。

### 手動備份

在 Web 設定頁點擊「立即備份」即可，備份儲存至 `data/backups/`。

### 還原備份

在 Web 設定頁的備份列表中，點擊任一備份旁的「還原」按鈕。

> 還原操作會先驗證備份完整性再執行，但操作不可逆，請確認備份檔案正確。

### 異地備份

建議定期將 `data/backups/` 目錄同步至外部儲存（NAS、雲端硬碟），防止硬碟故障導致資料遺失。
