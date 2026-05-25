@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === LogAnalyze .exe 빌드 시작 (slim — serve.py + FastAPI + pywebview) ===
echo.

rem 기존 실행 인스턴스 종료 (PyInstaller .exe 덮어쓰기 차단 회피)
taskkill /F /IM LogAnalyze.exe >nul 2>&1

rem slim 빌드 — PyQt5/torch/scipy/matplotlib exclude (Looking-for-libs 행 회피)
python -m PyInstaller --noconfirm --windowed --name LogAnalyze ^
    --add-data "app/static;app/static" ^
    --collect-submodules uvicorn ^
    --hidden-import "uvicorn.loops.auto" ^
    --hidden-import "uvicorn.protocols.http.auto" ^
    --hidden-import "uvicorn.protocols.websockets.auto" ^
    --hidden-import "uvicorn.lifespan.on" ^
    --hidden-import "webview.platforms.edgechromium" ^
    --exclude-module "PyQt5" --exclude-module "PyQt6" --exclude-module "PySide6" ^
    --exclude-module "torch" --exclude-module "tensorflow" ^
    --exclude-module "matplotlib" --exclude-module "scipy" ^
    serve.py

if errorlevel 1 (
    echo.
    echo *** 빌드 실패 — 위 메시지 확인 ***
    pause
    exit /b 1
)

rem data 폴더 + .env junction/copy — 처음 빌드면 자동 셋업
if not exist "dist\LogAnalyze\data" (
    mklink /J "dist\LogAnalyze\data" "%~dp0data" >nul
    echo data junction 생성됨
)
if not exist "dist\LogAnalyze\.env" (
    if exist ".env" (
        copy ".env" "dist\LogAnalyze\.env" >nul
        echo .env 복사됨
    )
)

echo.
echo === 빌드 완료 ===
echo 실행파일: dist\LogAnalyze\LogAnalyze.exe
echo.
pause
