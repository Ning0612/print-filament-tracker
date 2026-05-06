#Requires -Version 5.1
<#
.SYNOPSIS
    PrintFilamentTracker Windows 建置腳本 — 打包成單一 .exe

.DESCRIPTION
    步驟：
      1. Pre-flight：確認 venv 與 spec 存在
      2. 安裝建置依賴（pystray、Pillow、waitress、pyinstaller）
      3. 轉換 PNG 圖示為多解析度 .ico
      4. 執行 PyInstaller（--onefile --windowed）
      5. 驗證輸出

.PARAMETER SkipInstall
    略過 pip install 步驟（已確認依賴正確時使用）

.PARAMETER NoUpx
    停用 UPX 壓縮（系統未安裝 UPX 時使用）

.EXAMPLE
    .\scripts\build_exe.ps1
    .\scripts\build_exe.ps1 -NoUpx
    .\scripts\build_exe.ps1 -SkipInstall -NoUpx
#>

[CmdletBinding()]
param(
    [switch]$SkipInstall,
    [switch]$NoUpx
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# 修正 PowerShell 5.1 中文亂碼（UTF-8 code page）
chcp 65001 | Out-Null
[Console]::InputEncoding  = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding           = [System.Text.Encoding]::UTF8

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$PngIcon    = Join-Path $RepoRoot "web\static\img\print-filament-tracker-icon.png"
$IcoIcon    = Join-Path $RepoRoot "web\static\img\print-filament-tracker-icon.ico"
$SpecFile   = Join-Path $RepoRoot "PrintFilamentTracker.spec"
$OutputExe  = Join-Path $RepoRoot "dist\PrintFilamentTracker.exe"

function Write-Step([string]$msg) { Write-Host "`n[STEP] $msg" -ForegroundColor Cyan }
function Write-OK([string]$msg)   { Write-Host "  [OK]   $msg" -ForegroundColor Green }
function Write-Fail([string]$msg) { Write-Host "  [FAIL] $msg" -ForegroundColor Red; throw $msg }

# ── STEP 0：Pre-flight ────────────────────────────────────────────────────────
Write-Step "Pre-flight checks"
if (-not (Test-Path $VenvPython)) { Write-Fail "找不到 venv：$VenvPython`n請先執行：python -m venv .venv && pip install -r requirements.txt" }
if (-not (Test-Path $SpecFile))   { Write-Fail "找不到 spec：$SpecFile" }
Write-OK "venv 和 spec 存在"

# ── STEP 1：安裝建置依賴 ──────────────────────────────────────────────────────
if (-not $SkipInstall) {
    Write-Step "安裝建置依賴"
    & $VenvPython -m pip install --quiet --upgrade `
        "waitress>=3.0.0" `
        "pystray>=0.19.5" `
        "Pillow>=10.0.0" `
        "pyinstaller>=6.0.0"
    if ($LASTEXITCODE -ne 0) { Write-Fail "pip install 失敗" }
    Write-OK "依賴安裝完成"
}

# ── STEP 2：PNG → ICO（多解析度） ─────────────────────────────────────────────
Write-Step "轉換圖示 PNG → ICO"
# 使用暫存 .py 檔避免 PowerShell 5.1 在 -c 參數中吞掉 Python 字串的雙引號
$tmpPy = [System.IO.Path]::ChangeExtension([System.IO.Path]::GetTempFileName(), '.py')
Set-Content -Path $tmpPy -Encoding UTF8 -Value @'
from PIL import Image
import sys
img = Image.open(sys.argv[1]).convert("RGBA")
sizes = [(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)]
imgs = [img.resize(s, Image.LANCZOS) for s in sizes]
imgs[0].save(sys.argv[2], format='ICO', append_images=imgs[1:])
print("ICO saved:", sys.argv[2])
'@
& $VenvPython $tmpPy $PngIcon $IcoIcon
Remove-Item $tmpPy -ErrorAction SilentlyContinue
if ($LASTEXITCODE -ne 0) { Write-Fail "ICO 轉換失敗" }
Write-OK "ICO 圖示建立：$IcoIcon"

# ── STEP 3：PyInstaller ───────────────────────────────────────────────────────
Write-Step "執行 PyInstaller（onefile + windowed）"
$distPath  = Join-Path $RepoRoot "dist"
$buildPath = Join-Path $RepoRoot "build"

# 若舊版 .exe 仍在執行（系統托盤常駐），先強制結束以釋放檔案鎖
$running = Get-Process -Name "PrintFilamentTracker" -ErrorAction SilentlyContinue
if ($running) {
    Write-Host "  [INFO] 偵測到程式執行中，正在終止舊版本..." -ForegroundColor Yellow
    $running | Stop-Process -Force
    Start-Sleep -Milliseconds 500   # 等待 OS 釋放檔案鎖
    Write-Host "  [INFO] 已終止舊版本" -ForegroundColor Yellow
}

Push-Location $RepoRoot
try {
    if ($NoUpx) {
        $env:PYINSTALLER_NO_UPX = "1"
    } else {
        $env:PYINSTALLER_NO_UPX = "0"
    }
    
    & $VenvPython -m PyInstaller `
        --clean --noconfirm `
        --distpath $distPath --workpath $buildPath `
        --log-level WARN $SpecFile
    if ($LASTEXITCODE -ne 0) { Write-Fail "PyInstaller 失敗，請查看上方錯誤訊息" }
} finally {
    Pop-Location
}
Write-OK "PyInstaller 完成"

# ── STEP 4：驗證輸出 ──────────────────────────────────────────────────────────
Write-Step "驗證輸出"
if (-not (Test-Path $OutputExe)) { Write-Fail "找不到輸出：$OutputExe" }
$sizeMB = [math]::Round((Get-Item $OutputExe).Length / 1MB, 1)
Write-OK "輸出：$OutputExe（$sizeMB MB）"

Write-Host ""
Write-Host ("=" * 60) -ForegroundColor Cyan
Write-Host "  建置完成！" -ForegroundColor Cyan
Write-Host ("=" * 60) -ForegroundColor Cyan
Write-Host ""
Write-Host "  使用方式：" -ForegroundColor White
Write-Host "    1. 將 dist\PrintFilamentTracker.exe 複製至任意目錄後執行"
Write-Host "    2. 點擊系統托盤圖示「開啟 PrintFilamentTracker」"
Write-Host "    3. 資料庫與設定自動儲存於："
Write-Host '       %LOCALAPPDATA%\PrintFilamentTracker\' -ForegroundColor Yellow
Write-Host ""
Write-Host "  遇到防毒誤判時，嘗試：.\scripts\build_exe.ps1 -NoUpx" -ForegroundColor Yellow
