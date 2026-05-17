@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === LogAnalyze .exe 빌드 시작 ===
echo.
pyinstaller --noconfirm --windowed ^
    --name LogAnalyze ^
    --collect-all PySide6 ^
    gui.py
if errorlevel 1 (
    echo.
    echo *** 빌드 실패 — 위 메시지 확인 ***
    pause
    exit /b 1
)
echo.
echo === 빌드 완료 ===
echo 실행파일: dist\LogAnalyze\LogAnalyze.exe
echo.
pause
