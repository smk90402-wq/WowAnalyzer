@echo off
chcp 65001 >nul
rem RTV PC: upload Desktop\cctvlog replays/logs to R2
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\cctv_push_RTV.ps1"
pause
