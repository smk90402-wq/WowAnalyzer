@echo off
chcp 65001 >nul
rem v2 캐시 + 종족 모델 R2 업로드 (새/갱신 파일만)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\cache_push.ps1"
pause
