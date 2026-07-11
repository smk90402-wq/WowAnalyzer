@echo off
chcp 65001 >nul
rem R2에서 리플레이(영상+json)와 전투로그 받기 → E:\cctv + WoW Logs
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\cctv_pull.ps1"
pause
