@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === WowAnalyzer 웹서버 + Cloudflare Tunnel ===
echo.

rem 1) LogAnalyze.exe (pywebview 윈도우 + FastAPI uvicorn port 9876) 실행
rem    - 본인 PC 에서 직접 확인할 때는 윈도우 닫지 말 것
rem    - 친구만 접속할 거면 LogAnalyze.exe 대신 --api-only 모드:
rem        python serve.py --api-only --port 9876
if exist "dist\LogAnalyze\LogAnalyze.exe" (
    echo [1/2] LogAnalyze.exe 시작 (백그라운드)
    start "" "dist\LogAnalyze\LogAnalyze.exe"
) else (
    echo [1/2] dist\LogAnalyze\LogAnalyze.exe 없음 - build.bat 먼저
    pause
    exit /b 1
)

rem 2) FastAPI ready 까지 5초 대기
echo     uvicorn ready 대기 (5초)
timeout /t 5 /nobreak >nul

rem 3) Cloudflare Tunnel - 임시 URL 발급 (PC 켜져있는 동안 유지)
echo [2/2] Cloudflare Tunnel 시작
echo     -> 잠시 후 "https://xxxxx.trycloudflare.com" URL 표시됨
echo     -> 이 URL 을 친구한테 공유 (rtv / 1234 로 로그인)
echo     -> Ctrl+C 누르면 Tunnel 종료 (LogAnalyze.exe 는 계속 실행)
echo.
cloudflared tunnel --url http://localhost:9876
