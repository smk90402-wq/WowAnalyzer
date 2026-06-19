@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo === WowAnalyzer safe pull ===

if not exist ".git" (
    echo *** This folder is not a git repository.
    exit /b 1
)

git lfs install --local >nul 2>&1
git config pull.ff only
git config fetch.prune true

if exist ".git\index.lock" (
    tasklist /FI "IMAGENAME eq git.exe" 2>nul | find /I "git.exe" >nul
    if not errorlevel 1 (
        echo *** .git\index.lock exists and git.exe is running.
        echo Close the other git process, then run this again.
        exit /b 1
    )
    echo Removing stale .git\index.lock
    del /F ".git\index.lock"
    if errorlevel 1 (
        echo *** Failed to remove .git\index.lock
        exit /b 1
    )
)

for /f "delims=" %%S in ('git status --porcelain') do (
    echo *** Local changes found. Commit, stash, or discard them before pulling.
    git status --short
    exit /b 1
)

git fetch --prune origin
if errorlevel 1 exit /b 1

git pull --ff-only origin main
if errorlevel 1 exit /b 1

git lfs pull
if errorlevel 1 exit /b 1

git lfs status
if errorlevel 1 exit /b 1

echo === Pull complete ===
exit /b 0
