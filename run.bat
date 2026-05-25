@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 빌드된 .exe가 있으면 그걸 띄우고, 없으면 python serve.py 로 직접
if exist "dist\LogAnalyze\LogAnalyze.exe" (
    start "" "dist\LogAnalyze\LogAnalyze.exe"
) else (
    python serve.py
)
