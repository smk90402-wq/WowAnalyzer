@echo off
chcp 65001 >nul
rem Download v2 caches + race models from R2
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\cache_pull.ps1"
pause
