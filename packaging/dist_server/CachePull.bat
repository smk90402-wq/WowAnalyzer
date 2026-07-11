@echo off
chcp 65001 >nul
rem R2에서 v2 캐시 + 종족 모델 받기 (새/갱신 파일만)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\cache_pull.ps1"
pause
