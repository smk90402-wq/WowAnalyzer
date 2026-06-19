@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if "%HOST%"=="" set "HOST=127.0.0.1"
if "%PORT%"=="" set "PORT=9876"

if not exist "LogAnalyze.exe" (
    echo LogAnalyze.exe not found in %CD%
    echo Run build.bat first.
    goto :finish
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$exe=(Resolve-Path '.\LogAnalyze.exe').Path; $p=Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'LogAnalyze.exe' -and $_.ExecutablePath -eq $exe -and $_.CommandLine -match '--api-only' }; if ($p) { Write-Host ('Already running: PID ' + (($p | ForEach-Object ProcessId) -join ', ')); exit 10 }"

if errorlevel 10 (
    echo URL: http://%HOST%:%PORT%/
    goto :finish
)

echo Starting WowAnalyzer API server...
start "WowAnalyzer API Server" /min "%~dp0LogAnalyze.exe" --api-only --host "%HOST%" --port "%PORT%"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$url='http://%HOST%:%PORT%/api/ping'; for ($i=0; $i -lt 40; $i++) { try { Invoke-RestMethod -Uri $url -TimeoutSec 1 | Out-Null; exit 0 } catch { Start-Sleep -Milliseconds 250 } }; exit 1"

if errorlevel 1 (
    echo Server process started, but /api/ping did not answer yet.
) else (
    echo Server ready.
)
echo URL: http://%HOST%:%PORT%/
echo Use CloseServer.bat to stop the API server.

:finish
if /I not "%~1"=="/nopause" pause
