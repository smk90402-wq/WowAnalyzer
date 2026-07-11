@echo off
chcp 65001 >nul
rem Download replays + combat logs from R2
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\cctv_pull.ps1"
pause
