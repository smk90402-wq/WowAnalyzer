# RTV PC 전용 — 바탕화면 cctvlog 폴더의 리플레이(영상+json)와 전투로그를 R2로 업로드.
# 표준 레이아웃(cctv/, logs/)으로 올라가므로 다른 PC에서는 scripts\cctv_pull.ps1 로 받으면 됨.
# 사용: .\scripts\cctv_push_RTV.ps1  (반복 실행 안전 — 새/갱신 파일만 전송, 삭제 없음)
param(
    [string]$SrcDir = "$env:USERPROFILE\Desktop\cctvlog"
)
$ErrorActionPreference = 'Stop'

$Remote = 'r2:wowanalyzer-cctv'

$rclone = (Get-Command rclone -ErrorAction SilentlyContinue).Source
if (-not $rclone) { $rclone = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Rclone.Rclone_Microsoft.Winget.Source_8wekyb3d8bbwe\rclone-v1.74.4-windows-amd64\rclone.exe" }

if (-not (Test-Path $SrcDir)) { throw "폴더 없음: $SrcDir" }

Write-Host "== 리플레이(영상+json): $SrcDir -> $Remote/cctv"
& $rclone copy $SrcDir "$Remote/cctv" --update --progress --transfers 4 --exclude 'WoWCombatLog*.txt'

Write-Host "== 전투로그: $SrcDir -> $Remote/logs"
& $rclone copy $SrcDir "$Remote/logs" --update --progress --include 'WoWCombatLog*.txt'

Write-Host "완료 — 다른 PC에서 .\scripts\cctv_pull.ps1 로 받기"
