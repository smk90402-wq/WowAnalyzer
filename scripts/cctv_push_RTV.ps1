# RTV PC 전용 — 바탕화면 cctvlog 폴더의 리플레이(영상+json)와 전투로그를 R2로 업로드.
# 표준 레이아웃(cctv/, logs/)으로 올라가므로 다른 PC에서는 scripts\cctv_pull.ps1 로 받으면 됨.
# 사용: .\scripts\cctv_push_RTV.ps1  (반복 실행 안전 — 새/갱신 파일만 전송, 삭제 없음)
param(
    [string]$SrcDir = "$env:USERPROFILE\Desktop\cctvlog"
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

if (-not (Test-Path $SrcDir)) { throw "폴더 없음: $SrcDir" }

Write-Host "== 리플레이(영상+json): $SrcDir -> $Remote/cctv"
& $rclone copy $SrcDir "$Remote/cctv" --update --progress --transfers 4 --exclude 'WoWCombatLog*.txt'

Write-Host "== 전투로그: $SrcDir -> $Remote/logs"
& $rclone copy $SrcDir "$Remote/logs" --update --progress --include 'WoWCombatLog*.txt'

Write-Host "완료 — 다른 PC에서 .\scripts\cctv_pull.ps1 로 받기"

