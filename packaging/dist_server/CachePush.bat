@echo off
chcp 65001 >nul
rem Upload v2 caches + race models to R2 (new/updated only)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\cache_push.ps1"
pause
