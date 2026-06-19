@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "DIST_DIR=dist\LogAnalyze"

echo === LogAnalyze exe build start ===
echo.

taskkill /F /IM LogAnalyze.exe >nul 2>&1

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
    --hidden-import "make_cache_manifest" ^
    --exclude-module "PyQt5" --exclude-module "PyQt6" --exclude-module "PySide6" ^
    --exclude-module "torch" --exclude-module "tensorflow" ^
    --exclude-module "matplotlib" --exclude-module "scipy" ^
    serve.py

if errorlevel 1 (
    echo.
    echo *** Build failed. Check the messages above. ***
    exit /b 1
)

call :ensure_data_junction || exit /b 1
call :copy_runtime_files || exit /b 1

echo.
echo === Build complete ===
echo exe: %DIST_DIR%\LogAnalyze.exe
echo.
exit /b 0

:ensure_data_junction
fsutil reparsepoint query "%DIST_DIR%\data" >nul 2>&1
if not errorlevel 1 exit /b 0

if exist "%DIST_DIR%\data\*" (
    for %%F in ("%DIST_DIR%\data\*") do (
        if /I not "%%~nxF"=="auth_secret" if /I not "%%~nxF"=="users.db" (
            echo *** WARN: unexpected file in %DIST_DIR%\data: %%~nxF
            echo Clean it manually before recreating the data junction.
            exit /b 1
        )
    )
)

if exist "%DIST_DIR%\data" rmdir /s /q "%DIST_DIR%\data" 2>nul
mklink /J "%DIST_DIR%\data" "%~dp0data" >nul
if errorlevel 1 (
    echo *** Failed to create data junction: %DIST_DIR%\data
    exit /b 1
)
echo data junction ready
exit /b 0

:copy_runtime_files
if not exist "%DIST_DIR%" (
    echo *** Missing dist folder: %DIST_DIR%
    exit /b 1
)

if not exist "%DIST_DIR%\.env" (
    if exist ".env" (
        copy ".env" "%DIST_DIR%\.env" >nul
        if errorlevel 1 exit /b 1
        echo .env copied
    )
)

if exist "packaging\dist_server\OpenServer.bat" (
    copy /Y "packaging\dist_server\OpenServer.bat" "%DIST_DIR%\OpenServer.bat" >nul
    if errorlevel 1 exit /b 1
)

if exist "packaging\dist_server\CloseServer.bat" (
    copy /Y "packaging\dist_server\CloseServer.bat" "%DIST_DIR%\CloseServer.bat" >nul
    if errorlevel 1 exit /b 1
)

echo runtime files copied
exit /b 0
