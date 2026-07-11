@echo off
chcp 65001 >nul
rem RTV PC 전용 — 바탕화면\cctvlog 의 리플레이/전투로그 R2 업로드
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\cctv_push_RTV.ps1"
pause
