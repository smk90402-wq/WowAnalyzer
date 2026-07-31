@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PUBLIC_BUILD=0"
set "PYINSTALLER_DIST=dist"
set "DIST_DIR=dist\LogAnalyze"

if "%~1"=="" goto :args_ready
if /I "%~1"=="--public" (
    set "PUBLIC_BUILD=1"
    set "PYINSTALLER_DIST=dist\_public_build"
    set "DIST_DIR=dist\LogAnalyzePublic"
    goto :args_ready
)

echo Usage: build.bat [--public]
exit /b 2

:args_ready
if "%PUBLIC_BUILD%"=="1" (
    echo === Public release build mode ===
    fsutil reparsepoint query "dist\_public_build" >nul 2>&1
    if not errorlevel 1 (
        echo *** Refusing to replace reparse point: dist\_public_build
        exit /b 1
    )
    fsutil reparsepoint query "dist\LogAnalyzePublic" >nul 2>&1
    if not errorlevel 1 (
        echo *** Refusing to replace reparse point: dist\LogAnalyzePublic
        exit /b 1
    )
    if exist "dist\_public_build" rmdir /s /q "dist\_public_build"
    if exist "dist\LogAnalyzePublic" rmdir /s /q "dist\LogAnalyzePublic"
)

echo === LogAnalyze exe build start ===
echo.

taskkill /F /IM LogAnalyze.exe >nul 2>&1

python -m PyInstaller --noconfirm --windowed --name LogAnalyze --distpath "%PYINSTALLER_DIST%" ^
    --icon "app\static\wow.ico" ^
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
    --hidden-import "blizzard" ^
    --hidden-import "app.cctv_sync" --hidden-import "app.char_race" ^
    --exclude-module "PyQt5" --exclude-module "PyQt6" --exclude-module "PySide6" ^
    --exclude-module "torch" --exclude-module "tensorflow" ^
    --exclude-module "matplotlib" --exclude-module "scipy" ^
    serve.py

if errorlevel 1 (
    echo.
    echo *** Build failed. Check the messages above. ***
    exit /b 1
)

if "%PUBLIC_BUILD%"=="1" (
    move "%PYINSTALLER_DIST%\LogAnalyze" "%DIST_DIR%" >nul
    if errorlevel 1 (
        echo *** Failed to finalize public build folder: %DIST_DIR%
        exit /b 1
    )
    if exist "%PYINSTALLER_DIST%" rmdir /s /q "%PYINSTALLER_DIST%"

    powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\copy_public_data.ps1" -Destination "%DIST_DIR%"
    if errorlevel 1 exit /b 1
) else (
    call :ensure_data_junction || exit /b 1
)

call :copy_runtime_files || exit /b 1
if "%PUBLIC_BUILD%"=="1" call :verify_public_package || exit /b 1

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

if "%PUBLIC_BUILD%"=="1" goto :copy_public_runtime_files

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

rem R2 동기화 스크립트 (ps1) + 더블클릭용 bat 래퍼
if not exist "%DIST_DIR%\scripts" mkdir "%DIST_DIR%\scripts"
copy /Y "scripts\*.ps1" "%DIST_DIR%\scripts\" >nul
for %%B in (CachePush CachePull CctvPush CctvPull CctvPushRTV) do (
    if exist "packaging\dist_server\%%B.bat" copy /Y "packaging\dist_server\%%B.bat" "%DIST_DIR%\%%B.bat" >nul
)

echo runtime files copied
exit /b 0

:copy_public_runtime_files
if exist "packaging\public_replay.json.example" (
    copy /Y "packaging\public_replay.json.example" "%DIST_DIR%\public_replay.json.example" >nul
    if errorlevel 1 exit /b 1
)

if defined WOWANALYZER_PUBLIC_REPLAY_BASE_URL (
    powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\write_public_replay_config.ps1" ^
        -Destination "%DIST_DIR%\public_replay.json"
    if errorlevel 1 exit /b 1
) else (
    echo NOTE: public replay URL is not embedded. Set WOWANALYZER_PUBLIC_REPLAY_BASE_URL before the release build.
)

if exist "packaging\dist_server\OpenServer.bat" (
    copy /Y "packaging\dist_server\OpenServer.bat" "%DIST_DIR%\OpenServer.bat" >nul
    if errorlevel 1 exit /b 1
)

if exist "packaging\dist_server\CloseServer.bat" (
    copy /Y "packaging\dist_server\CloseServer.bat" "%DIST_DIR%\CloseServer.bat" >nul
    if errorlevel 1 exit /b 1
)

echo public runtime files copied
exit /b 0

:verify_public_package
if exist "%DIST_DIR%\.env" goto :public_package_leak
if exist "%DIST_DIR%\scripts" goto :public_package_leak
if exist "%DIST_DIR%\CachePush.bat" goto :public_package_leak
if exist "%DIST_DIR%\CachePull.bat" goto :public_package_leak
if exist "%DIST_DIR%\CctvPush.bat" goto :public_package_leak
if exist "%DIST_DIR%\CctvPull.bat" goto :public_package_leak
if exist "%DIST_DIR%\CctvPushRTV.bat" goto :public_package_leak
if exist "%DIST_DIR%\data\user_characters.json" goto :public_package_leak
if exist "%DIST_DIR%\data\char_race_cache.json" goto :public_package_leak
if exist "%DIST_DIR%\data\users.db" goto :public_package_leak
if exist "%DIST_DIR%\data\auth_secret" goto :public_package_leak
if exist "%DIST_DIR%\data\cache.db" goto :public_package_leak
if exist "%DIST_DIR%\data\cctv_r2" goto :public_package_leak
if exist "%DIST_DIR%\data\maps" goto :public_package_leak
if exist "%DIST_DIR%\data\icons" goto :public_package_leak
if exist "%DIST_DIR%\data\boss_stats.json" goto :public_package_leak
if exist "%DIST_DIR%\data\rankings_zone46_*" goto :public_package_leak
if exist "%DIST_DIR%\data\lura_trials_*" goto :public_package_leak
if exist "%DIST_DIR%\PUBLIC_R2_DEPLOYMENT.md" goto :public_package_leak
if not exist "%DIST_DIR%\public_replay.json.example" (
    echo *** Public config template is missing.
    exit /b 1
)
if not exist "%DIST_DIR%\data" (
    echo *** Public data folder is missing.
    exit /b 1
)
fsutil reparsepoint query "%DIST_DIR%\data" >nul 2>&1
if not errorlevel 1 (
    echo *** Public data folder must not be a junction.
    exit /b 1
)
echo public package safety check passed
exit /b 0

:public_package_leak
echo *** Public package contains an administrator or private file.
exit /b 1
