# R2에서 무거운 캐시 받기 (새 파일 + 원격이 더 최신인 파일만 전송)
# 사용: .\scripts\cache_pull.ps1
$ErrorActionPreference = 'Stop'

$Remote = 'r2:wowanalyzer-cache/data'
$Include = @('v2_cache_*.json', 'cache.db', 'models/race_*.json', 'models/race_*.png', 'models/manifest.json')

$rclone = (Get-Command rclone -ErrorAction SilentlyContinue).Source
if (-not $rclone) { $rclone = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Rclone.Rclone_Microsoft.Winget.Source_8wekyb3d8bbwe\rclone-v1.74.4-windows-amd64\rclone.exe" }

$dataDir = Join-Path $PSScriptRoot '..\data'
$args = @('copy', $Remote, $dataDir, '--update', '--progress')
foreach ($pat in $Include) { $args += @('--include', $pat) }
& $rclone @args
