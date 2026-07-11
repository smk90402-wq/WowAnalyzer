@echo off
chcp 65001 >nul
rem E:\cctv 리플레이(영상+json) + WoW 전투로그 R2 업로드
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\cctv_push.ps1"
pause
