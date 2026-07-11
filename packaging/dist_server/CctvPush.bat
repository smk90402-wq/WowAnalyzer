@echo off
chcp 65001 >nul
rem Upload E:\cctv replays + WoW combat logs to R2
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\cctv_push.ps1"
pause
