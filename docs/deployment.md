# 部署指南

本文說明如何在 **Windows** 和 **macOS** 上安裝與執行 PrintFilamentTracker。

## 目錄

- [安裝方式概覽](#安裝方式概覽)
- [Windows 安裝](#windows-安裝)
  - [下載與執行](#下載與執行)
  - [SmartScreen 與防毒警告](#smartscreen-與防毒警告)
  - [資料儲存位置](#資料儲存位置)
  - [首次設定](#首次設定)
  - [停止與解除安裝](#停止與解除安裝)
- [macOS 安裝](#macos-安裝)
  - [下載與執行](#下載與執行-1)
  - [Gatekeeper 提示](#gatekeeper-提示)
  - [資料儲存位置](#資料儲存位置-1)
  - [停止與解除安裝](#停止與解除安裝-1)
- [進階設定（.env）](#進階設定env)
- [環境變數參考](#環境變數參考)
- [資料目錄結構](#資料目錄結構)
- [日誌管理](#日誌管理)
- [備份策略](#備份策略)
- [附錄：開發者 / Python 環境啟動](#附錄開發者--python-環境啟動)

---

## 安裝方式概覽

PrintFilamentTracker 提供預先打包的執行檔，**無需安裝 Python**：

| 作業系統 | 安裝方式 |
|---------|---------|
| Windows 10 / 11 | 下載 `.msi`（安裝程式）或 `.exe`（免安裝） |
| macOS 12+（Monterey）| 下載 `.app`，右鍵開啟 |

程式啟動後：
- 在系統托盤（Windows）或 Menu Bar（macOS）顯示常駐圖示
- 自動在背景啟動 Web 伺服器
- 自動開啟瀏覽器並前往 `http://127.0.0.1:7580`

---

## Windows 安裝

### 下載與執行

前往 [GitHub Releases](https://github.com/Ning0612/print-filament-tracker/releases) 下載最新版，有兩種版本可選：

**方式一：MSI 安裝程式（推薦）**

1. 下載 `PrintFilamentTracker-x.x.x.msi`
2. 雙擊執行，依照安裝精靈完成安裝：
   - **選擇功能**：可勾選是否建立「桌面捷徑」（預設勾選）
   - **完成畫面**：可勾選「立即啟動 PrintFilamentTracker」（預設勾選）
3. 安裝後可從「開始選單」或桌面捷徑啟動，並在「設定 → 新增或移除程式」中管理

**方式二：免安裝 .exe**

1. 下載 `PrintFilamentTracker.exe`
2. 將 `.exe` 移至您希望長期存放的目錄，例如：
   ```
   C:\Users\你的名字\PrintFilamentTracker\PrintFilamentTracker.exe
   ```
3. 雙擊 `PrintFilamentTracker.exe` 啟動

啟動後程式會自動：
- 在系統托盤（工作列右下角）顯示圖示
- 於背景啟動 Waitress Web 伺服器
- 開啟預設瀏覽器前往 `http://127.0.0.1:7580`

**再次執行**（程式已在執行中）：重複執行只會開啟瀏覽器，不會建立第二個實例。

### SmartScreen 與防毒警告

**Windows SmartScreen 警告**

首次執行時可能出現「Windows 已保護您的電腦」對話框（因執行檔尚未申請數位簽章）。

處理方式：
1. 點擊「**其他資訊**」
2. 點擊「**仍要執行**」

**防毒軟體誤判**

PyInstaller 打包的執行檔偶爾會被防毒軟體誤報為可疑程式。建議：
- 將 `.exe` 所在目錄加入防毒軟體的排除清單
- 或使用 [自行建置](../docs/development.md#自行建置) 的版本（加入 `-NoUpx` 參數可降低誤報率）

### 資料儲存位置

凍結版（`.exe`）的所有資料儲存於 Windows 標準應用程式資料目錄：

```
%LOCALAPPDATA%\PrintFilamentTracker\
├── .env              ← 設定檔（首次啟動時自動建立）
└── data\
    ├── tracker.db    ← SQLite 資料庫
    ├── covers\       ← 封面圖片
    ├── backups\      ← 資料庫備份
    └── logs\
        └── app.log   ← 應用日誌
```

在 PowerShell 開啟此目錄：

```powershell
explorer "$env:LOCALAPPDATA\PrintFilamentTracker"
```

### 首次設定

1. 啟動程式後，瀏覽器自動開啟 `http://127.0.0.1:7580`
2. 前往「**設定**」頁面
3. 在「Bambu Cloud 登入」區塊輸入 Bambu Lab 帳號與密碼
4. 完成登入後系統自動取得 Access Token，之後即可使用「手動同步」匯入列印歷史

> **Token 安全**：Access Token 以明文儲存於 `data\tracker.db`。請勿將資料目錄分享或同步至公開雲端服務（OneDrive、Dropbox 等）。

### 停止與解除安裝

**停止程式**：右鍵點擊系統托盤圖示 → 選擇「**結束**」

**解除安裝（MSI 安裝版）**：
1. 右鍵系統托盤圖示 → 結束程式
2. 前往「設定」→「應用程式」→「已安裝的應用程式」，找到 PrintFilamentTracker 後解除安裝
3. （可選）刪除資料目錄：`%LOCALAPPDATA%\PrintFilamentTracker\`

**解除安裝（免安裝 .exe 版）**：
1. 右鍵系統托盤圖示 → 結束程式
2. 刪除 `.exe` 檔案
3. （可選）刪除資料目錄：`%LOCALAPPDATA%\PrintFilamentTracker\`

---

## macOS 安裝

### 下載與執行

1. 前往 [GitHub Releases](https://github.com/Ning0612/print-filament-tracker/releases) 下載最新版 `PrintFilamentTracker.app.zip`
2. 解壓縮後，將 `PrintFilamentTracker.app` 移至您希望存放的目錄（如 `~/Applications/`）
3. **首次開啟**（必須使用右鍵開啟以繞過 Gatekeeper）：
   - 右鍵點擊 `PrintFilamentTracker.app`
   - 選擇「**開啟**」
   - 在出現的對話框中點擊「**開啟**」確認

之後可直接雙擊開啟，不需再繞過 Gatekeeper。

啟動後程式會在 Menu Bar（螢幕右上角）顯示圖示，並自動開啟瀏覽器前往 `http://127.0.0.1:7580`。

### Gatekeeper 提示

若出現「PrintFilamentTracker 無法開啟，因為開發者無法驗證」：

1. 前往「**系統設定**」→「**隱私權與安全性**」
2. 在「已封鎖使用 … 因為來自身份不明的開發者」訊息旁點擊「**仍要開啟**」

### 資料儲存位置

凍結版（`.app`）的所有資料儲存於 macOS 標準應用程式資料目錄：

```
~/Library/Application Support/PrintFilamentTracker/
├── .env              ← 設定檔（首次啟動時自動建立）
└── data/
    ├── tracker.db    ← SQLite 資料庫
    ├── covers/       ← 封面圖片
    ├── backups/      ← 資料庫備份
    └── logs/
        └── app.log   ← 應用日誌
```

在 Finder 開啟此目錄：

```bash
open ~/Library/Application\ Support/PrintFilamentTracker
```

### 停止與解除安裝

**停止程式**：點擊 Menu Bar 圖示 → 選擇「**結束**」

**解除安裝**：
1. 點擊 Menu Bar 圖示 → 結束程式
2. 將 `.app` 移至垃圾桶
3. （可選）刪除資料目錄：`~/Library/Application Support/PrintFilamentTracker/`

---

## 進階設定（.env）

程式首次啟動時會在資料目錄自動建立 `.env` 並生成 `SECRET_KEY`。  
若需自訂設定，使用文字編輯器開啟 `.env`：

```
# Windows
%LOCALAPPDATA%\PrintFilamentTracker\.env

# macOS
~/Library/Application Support/PrintFilamentTracker/.env
```

修改後需**重啟程式**才能生效（右鍵托盤圖示 → 結束 → 重新執行）。

---

## 環境變數參考

| 變數名稱 | 預設值 | 說明 |
|---------|--------|------|
| `BAMBU_ACCESS_TOKEN` | — | Bambu Cloud Bearer Token（建議從 Web 設定頁登入取得） |
| `BAMBU_REGION` | `global` | API 區域：`global` 或 `china` |
| `BAMBU_API_BASE` | 自動 | 覆寫 API 端點（可選） |
| `BAMBU_OUTPUT_DIR` | `data` | 資料輸出目錄（相對於資料根目錄） |
| `SECRET_KEY` | 自動生成 | Flask Session 加密金鑰（首次啟動自動寫入） |
| `PORT` | `7580` | Web 伺服器埠號（需重啟生效） |
| `AUTO_SYNC_INTERVAL` | `0` | 自動同步間隔（分鐘），`0` = 停用 |
| `BACKUP_INTERVAL_MINUTES` | `0` | 自動備份間隔（分鐘），`0` = 停用 |
| `SESSION_COOKIE_SECURE` | `false` | 啟用 HTTPS-only cookie（搭配反向代理時設為 `true`） |

> `BAMBU_ACCESS_TOKEN` 也可透過 Web 設定頁登入後自動寫入資料庫。資料庫中的值優先於 `.env`。

---

## 資料目錄結構

首次啟動時自動建立：

```
PrintFilamentTracker/      ← 資料根目錄（依平台不同）
├── .env                   ← 設定檔
└── data/
    ├── tracker.db         ← SQLite 資料庫（自動初始化 Schema）
    ├── covers/            ← 封面圖片
    ├── backups/           ← 資料庫備份
    └── logs/
        └── app.log        ← 應用日誌（每 10 MB 輪轉，保留 5 份）
```

---

## 日誌管理

位置：`<資料目錄>/data/logs/app.log`

- 單檔最大 10 MB，保留最近 5 份
- 格式：`YYYY-MM-DD HH:MM:SS LEVEL name: message`

即時查看：

```powershell
# Windows
Get-Content "$env:LOCALAPPDATA\PrintFilamentTracker\data\logs\app.log" -Wait -Tail 50
```

```bash
# macOS
tail -f ~/Library/Application\ Support/PrintFilamentTracker/data/logs/app.log
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

建議定期將 `data/backups/` 目錄同步至外部儲存（NAS、外接硬碟），防止資料遺失。

---

## 附錄：開發者 / Python 環境啟動

> **此章節僅供開發與除錯使用，一般使用者無需閱讀。**

若需在未打包的 Python 環境中執行（用於開發、功能測試或貢獻程式碼）：

### 環境設定

```powershell
# Windows
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
# 編輯 .env，填入 BAMBU_REGION=global
```

```bash
# macOS
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
# 編輯 .env，填入 BAMBU_REGION=global
```

### 啟動方式

**System Tray 模式**（最接近正式版行為）：

```powershell
# Windows
.venv\Scripts\python.exe tray_main.py
```

```bash
# macOS
.venv/bin/python tray_main.py
```

**Flask 開發伺服器**（支援熱重載，不啟動托盤）：

```powershell
# Windows
.venv\Scripts\python.exe -m flask --app web.app run --debug --host 127.0.0.1 --port 7580
```

```bash
# macOS
.venv/bin/python -m flask --app web.app run --debug --host 127.0.0.1 --port 7580
```

> 開發模式下，資料儲存於**專案根目錄**的 `data/`，而非系統資料目錄。

### 建置執行檔

```powershell
# Windows（輸出：dist\PrintFilamentTracker.exe + dist\PrintFilamentTracker-x.x.x.msi）
.\scripts\build_exe.ps1 -NoUpx -Version "1.2.0"

# 僅建置 .exe，略過 MSI
.\scripts\build_exe.ps1 -NoUpx -SkipMsi
```

```bash
# macOS（輸出：dist/PrintFilamentTracker.app）
bash scripts/build_exe.sh --version=1.2.0
```

詳細說明請參考 [開發指南](development.md)。
