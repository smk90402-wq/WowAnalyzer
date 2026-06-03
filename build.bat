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
    --hidden-import "clr_loader" --hidden-import "pythonnet" ^
    --hidden-import "bcrypt" --hidden-import "itsdangerous" ^
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

rem data junction 자동 보정 — frozen exe 가 mkdir 로 빈 data 만들면 junction 깨짐
rem  → junction 이 아니고 비어있으면 삭제 후 mklink 재생성
call :ensure_data_junction
goto :after_data

:ensure_data_junction
fsutil reparsepoint query "dist\LogAnalyze\data" >nul 2>&1
if not errorlevel 1 goto :eof
rem junction 아님. frozen exe 가 부팅 때 auth_secret/users.db 만들어 빈 junction 을
rem 일반폴더로 덮은 경우가 흔함 → 이 둘은 원본 data 에도 있어 안전 삭제.
rem 그 외 파일이 있으면 진짜 데이터일 수 있어 보존(경고).
if exist "dist\LogAnalyze\data\*" (
    for %%F in ("dist\LogAnalyze\data\*") do (
        if /I not "%%~nxF"=="auth_secret" if /I not "%%~nxF"=="users.db" (
            echo *** WARN: dist\LogAnalyze\data 에 예상밖 파일 %%~nxF - 수동 정리 필요
            goto :eof
        )
    )
)
if exist "dist\LogAnalyze\data" rmdir /s /q "dist\LogAnalyze\data" 2>nul
mklink /J "dist\LogAnalyze\data" "%~dp0data" >nul
echo data junction 재생성됨 (auth 임시파일 정리 포함)
goto :eof

:after_data
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
