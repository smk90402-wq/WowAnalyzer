@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo === Lura pair mining refresh (own logs, multi-report) ===
echo.

python tmp_mine_lura_own_pair.py
if errorlevel 1 (
    echo.
    echo *** Mining failed. Check the messages above. ***
    pause
    exit /b 1
)

echo.
python analyze_lura_spec_compare.py
if errorlevel 1 (
    echo.
    echo *** Compare synthesis failed. Check the messages above. ***
    pause
    exit /b 1
)

echo.
echo === Done: data\lura_own_pair_mining.json + data\lura_spec_compare.json refreshed ===
pause
exit /b 0
