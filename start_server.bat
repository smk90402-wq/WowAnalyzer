@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === WowAnalyzer 웹서버 + Cloudflare Tunnel ===
echo.

rem 빌드 결과 확인
if not exist "dist\LogAnalyze\LogAnalyze.exe" (
    echo dist\LogAnalyze\LogAnalyze.exe 없음 - build.bat 먼저
    pause
    exit /b 1
)

rem ── data junction 자동 보정 ────────────────────────────────────────
rem  frozen exe 가 첫 실행 시 빈 data 폴더 자동 생성 → junction 깨짐
rem  → 매번 시작할 때 junction 인지 확인하고 아니면 재생성
fsutil reparsepoint query "dist\LogAnalyze\data" >nul 2>&1
if errorlevel 1 (
    if exist "dist\LogAnalyze\data\*" (
        echo *** WARN: dist\LogAnalyze\data 가 junction 아니고 안에 데이터 있음
        echo     수동 처리 필요. 진행 중단.
        pause
        exit /b 1
    )
    if exist "dist\LogAnalyze\data" rmdir /q "dist\LogAnalyze\data" 2>nul
    mklink /J "dist\LogAnalyze\data" "%~dp0data" >nul
    echo [boot] data junction 재생성
)

rem ── .env copy (없으면) ────────────────────────────────────────────
if not exist "dist\LogAnalyze\.env" (
    if exist ".env" copy ".env" "dist\LogAnalyze\.env" >nul
)

rem ── 1) LogAnalyze.exe 백그라운드 실행 ─────────────────────────────
echo [1/2] LogAnalyze.exe 시작 (백그라운드, port 9876)
start "" "dist\LogAnalyze\LogAnalyze.exe"

rem uvicorn ready 대기
echo     uvicorn ready 대기 (5초)
timeout /t 5 /nobreak >nul

rem ── 2) Cloudflare Tunnel ──────────────────────────────────────────
rem  - quick mode: URL 매번 다름 (PC 재시작 시 새 URL)
rem  - named mode (영구 URL): cloudflared login + tunnel create + DNS 매핑 후
rem     cloudflared tunnel run <tunnel-name>
echo [2/2] Cloudflare Tunnel 시작
echo     -> URL 표시되면 친구한테 공유
echo     -> 로그인: rtv / 1234
echo.
cloudflared tunnel --url http://localhost:9876
