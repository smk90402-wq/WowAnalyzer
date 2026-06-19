@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist "LogAnalyze.exe" (
    echo LogAnalyze.exe not found in %CD%
    goto :finish
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$exe=(Resolve-Path '.\LogAnalyze.exe').Path; $p=Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'LogAnalyze.exe' -and $_.ExecutablePath -eq $exe -and $_.CommandLine -match '--api-only' }; if (-not $p) { Write-Host 'No API-only server process found.'; exit 0 }; foreach ($x in $p) { Stop-Process -Id $x.ProcessId -Force; Write-Host ('Stopped PID ' + $x.ProcessId) }"

:finish
if /I not "%~1"=="/nopause" pause
