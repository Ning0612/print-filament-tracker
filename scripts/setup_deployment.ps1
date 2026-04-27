#Requires -Version 5.1
<#
.SYNOPSIS
    BambuPrintManager deployment setup script.

.DESCRIPTION
    Automates the following steps:
      1. Validate / generate SECRET_KEY in .env
      2. Install Waitress WSGI server
      3. Register ONE Windows Task Scheduler task:
           BambuPrintManager-Web - start web server at user logon

    Auto-sync and DB backup are handled by the app itself (in-process scheduler).

.PARAMETER WebPort
    Web server port. Default 5000.

.PARAMETER SkipSecretKey
    Skip SECRET_KEY check (use when .env already has a valid key).

.PARAMETER SkipTaskScheduler
    Skip Task Scheduler setup (only run SECRET_KEY and Waitress steps).

.EXAMPLE
    .\scripts\setup_deployment.ps1
    .\scripts\setup_deployment.ps1 -WebPort 8080
    .\scripts\setup_deployment.ps1 -SkipTaskScheduler
#>

[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$WebPort = 5000,

    [switch]$SkipSecretKey,
    [switch]$SkipTaskScheduler
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Constants ────────────────────────────────────────────────────────────────
$RepoRoot     = Split-Path -Parent $PSScriptRoot
$EnvFile      = Join-Path $RepoRoot ".env"
$VenvPython   = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$VenvPip      = Join-Path $RepoRoot ".venv\Scripts\pip.exe"
$VenvWaitress = Join-Path $RepoRoot ".venv\Scripts\waitress-serve.exe"
$StartBat     = Join-Path $PSScriptRoot "start_server.bat"

# ── Helpers ───────────────────────────────────────────────────────────────────
function Write-Step([string]$msg) { Write-Host "`n[STEP] $msg" -ForegroundColor Cyan }
function Write-OK([string]$msg)   { Write-Host "  [OK]   $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Write-Fail([string]$msg) {
    Write-Host "  [FAIL] $msg" -ForegroundColor Red
    throw $msg
}

# ── STEP 0: Pre-flight check ──────────────────────────────────────────────────
Write-Step "Pre-flight checks"

if (-not (Test-Path $RepoRoot))   { Write-Fail "Repo root not found: $RepoRoot" }
if (-not (Test-Path $VenvPython)) { Write-Fail "venv Python not found: $VenvPython`nRun: python -m venv .venv" }
if (-not (Test-Path $EnvFile))    { Write-Fail ".env not found: $EnvFile`nCopy .env.example to .env first." }
Write-OK "Repo, venv and .env verified"

# ── STEP 1: SECRET_KEY ────────────────────────────────────────────────────────
if (-not $SkipSecretKey) {
    Write-Step "SECRET_KEY check"

    $envContent = Get-Content $EnvFile -Raw -Encoding UTF8

    # Accept any non-empty value after SECRET_KEY= (quoted or unquoted)
    if ($envContent -match '(?m)^SECRET_KEY\s*=\s*[''"]?.+[''"]?\s*$') {
        Write-OK "SECRET_KEY already set, skipping generation"
    } else {
        Write-Host "  Generating new SECRET_KEY..." -ForegroundColor Yellow

        $newKey = & $VenvPython -c "import secrets; print(secrets.token_hex(32))"
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($newKey)) {
            Write-Fail "Failed to generate SECRET_KEY"
        }

        # Remove any blank SECRET_KEY line, append new one; preserve LF line endings
        $envLines = (Get-Content $EnvFile -Encoding UTF8) | Where-Object { $_ -notmatch '^\s*SECRET_KEY\s*=' }
        $newContent = ($envLines + "SECRET_KEY=$newKey") -join "`n"
        [System.IO.File]::WriteAllText($EnvFile, ($newContent + "`n"), [System.Text.Encoding]::UTF8)

        Write-OK "SECRET_KEY written to .env (64-char hex)"
        Write-Warn "Keep .env backed up. Losing SECRET_KEY invalidates all sessions."
    }
}

# ── STEP 2: Waitress ──────────────────────────────────────────────────────────
Write-Step "Waitress WSGI server"

if (Test-Path $VenvWaitress) {
    Write-OK "Waitress already installed"
} else {
    Write-Host "  Installing..." -ForegroundColor Yellow
    & $VenvPip install waitress --quiet
    if ($LASTEXITCODE -ne 0) { Write-Fail "waitress installation failed" }
    Write-OK "Waitress installed"
}

# Sync WebPort into start_server.bat
if (Test-Path $StartBat) {
    $batContent = Get-Content $StartBat -Raw -Encoding UTF8
    $batUpdated = $batContent -replace '--port\s+\d+', "--port $WebPort"
    if ($batUpdated -ne $batContent) {
        [System.IO.File]::WriteAllText($StartBat, $batUpdated, [System.Text.UTF8Encoding]::new($false))
        Write-OK "start_server.bat port updated to $WebPort"
    }
}

# ── STEP 3: Task Scheduler (Web Server only) ──────────────────────────────────
if ($SkipTaskScheduler) {
    Write-Warn "Skipping Task Scheduler setup (-SkipTaskScheduler)"
} else {
    Write-Step "Windows Task Scheduler - Web Server auto-start"

    $currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    Write-Host "  Task will run as: $currentUser" -ForegroundColor DarkGray

    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )
    if (-not $isAdmin) {
        Write-Warn "Not running as Administrator - Task Scheduler may fail"
        Write-Warn "Re-run as Administrator for best results"
        $resp = Read-Host "  Continue anyway? (y/N)"
        if ($resp -notmatch '^[Yy]') {
            Write-Host "  Aborted Task Scheduler setup" -ForegroundColor Yellow
            $SkipTaskScheduler = $true
        }
    }
}

if (-not $SkipTaskScheduler) {
    $currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )
    $runLevel = if ($isAdmin) { "Highest" } else { "Limited" }

    $taskWeb = "BambuPrintManager-Web"

    # Stop and remove existing task
    $existing = Get-ScheduledTask -TaskName $taskWeb -ErrorAction SilentlyContinue
    if ($existing) {
        if ($existing.State -eq 'Running') {
            Stop-ScheduledTask -TaskName $taskWeb
            Start-Sleep -Seconds 2
        }
        Unregister-ScheduledTask -TaskName $taskWeb -Confirm:$false
        Write-Host "  Removed existing task" -ForegroundColor DarkGray
    }

    # Kill any lingering waitress/web processes on the port
    Get-Process -Name "python" -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -like "*$RepoRoot*" } |
        ForEach-Object {
            Write-Host "  Stopping process PID $($_.Id)" -ForegroundColor DarkGray
            Stop-Process $_ -Force
        }
    Start-Sleep -Milliseconds 500

    $webAction   = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$StartBat`"" -WorkingDirectory $RepoRoot
    $webTrigger  = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
    $webSettings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -MultipleInstances IgnoreNew `
        -StartWhenAvailable

    Register-ScheduledTask `
        -TaskName $taskWeb `
        -Action $webAction `
        -Trigger $webTrigger `
        -Settings $webSettings `
        -Description "BambuPrintManager Web Server (Waitress port $WebPort)" `
        -RunLevel $runLevel `
        | Out-Null

    Write-OK "Task '$taskWeb' created - triggers at logon for $currentUser (port $WebPort)"
}

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host ("=" * 60) -ForegroundColor Cyan
Write-Host "  BambuPrintManager deployment setup complete!" -ForegroundColor Cyan
Write-Host ("=" * 60) -ForegroundColor Cyan
Write-Host ""
Write-Host "  Completed:" -ForegroundColor White
Write-Host "    OK  SECRET_KEY check" -ForegroundColor White
Write-Host "    OK  Waitress check" -ForegroundColor White

if (-not $SkipTaskScheduler) {
    Write-Host "    OK  Task Scheduler:" -ForegroundColor White
    Write-Host "          BambuPrintManager-Web (at logon, port $WebPort)" -ForegroundColor White
}

Write-Host ""
Write-Host "  Auto-sync and DB backup are managed by the app itself." -ForegroundColor DarkGray
Write-Host "  Configure intervals in the Web UI Settings page." -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Start web server now:" -ForegroundColor Cyan
Write-Host "    Start-ScheduledTask -TaskName `"BambuPrintManager-Web`"" -ForegroundColor White
Write-Host "    or run: .\scripts\start_server.bat" -ForegroundColor White
Write-Host ""
Write-Host ("  Web UI: http://127.0.0.1:{0}" -f $WebPort) -ForegroundColor Cyan
Write-Host ""
