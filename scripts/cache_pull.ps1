# R2에서 무거운 캐시 받기 (새 파일 + 원격이 더 최신인 파일만 전송)
# 사용: .\scripts\cache_pull.ps1
$ErrorActionPreference = 'Stop'

$Remote = 'r2:wowanalyzer-cache/data'
$Include = @('v2_cache_*.json', 'cache.db', 'models/race_*.json', 'models/race_*.png', 'models/manifest.json',
              'maps/*_hd.png')   # AI 업스케일 지도 (Real-ESRGAN 4x — 재생성 비용 커서 공유)

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

$dataDir = Join-Path $PSScriptRoot '..\data'
$args = @('copy', $Remote, $dataDir, '--update', '--progress')
foreach ($pat in $Include) { $args += @('--include', $pat) }
& $rclone @args

