# R2에서 리플레이 원본(영상+json+전투로그) 받기 (새/갱신 파일만, 삭제 없음)
# 사용: .\scripts\cctv_pull.ps1 [-CctvDir E:\cctv] [-LogDir <WoW Logs>]
param(
    [string]$CctvDir = $(if ($env:WARCRAFTCCTV_DIR) { $env:WARCRAFTCCTV_DIR } else { 'E:\cctv' }),
    [string]$LogDir = $(if ($env:WOW_LOG_DIR) { $env:WOW_LOG_DIR } else { 'C:\Program Files (x86)\World of Warcraft\_retail_\Logs' })
)
$ErrorActionPreference = 'Stop'

$Remote = 'r2:wowanalyzer-cctv'

# rclone 탐색: PATH → winget 설치 폴더(버전 무관) — 없으면 설치 안내 후 종료
$rclone = (Get-Command rclone -ErrorAction SilentlyContinue).Source
if (-not $rclone) {
    $rclone = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Rclone.Rclone_*\rclone-*\rclone.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $rclone) {
    Write-Error "rclone이 없습니다. 설치: winget install Rclone.Rclone (설치 후 새 창에서 다시 실행)"
    exit 1
}

New-Item -ItemType Directory -Force $CctvDir | Out-Null
Write-Host "== cctv 다운로드: $Remote/cctv -> $CctvDir"
& $rclone copy "$Remote/cctv" $CctvDir --update --progress --transfers 4

New-Item -ItemType Directory -Force $LogDir | Out-Null
Write-Host "== 전투로그 다운로드: $Remote/logs -> $LogDir"
& $rclone copy "$Remote/logs" $LogDir --update --progress

