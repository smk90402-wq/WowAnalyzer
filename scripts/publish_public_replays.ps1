# 공개 리플레이 산출물을 private R2 버킷의 허용 prefix에 게시한다.
# 원본 로그/자격정보는 올리지 않으며, 공개 manifest는 항상 마지막에 교체한다.
param(
    [string]$OutputDir = "",
    [string]$PrivateVideoMap = "",
    [int]$Limit = 80,
    [string]$Remote = "r2:wowanalyzer-cctv",
    [switch]$NoTerrain
)
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $OutputDir) {
    $OutputDir = Join-Path $repoRoot "data\public_replay_publish"
}
if (-not $PrivateVideoMap) {
    $PrivateVideoMap = Join-Path $repoRoot "data\public_replay_private\video_map.json"
}

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) {
    throw "python 실행 파일이 없습니다."
}

$rclone = (Get-Command rclone -ErrorAction SilentlyContinue).Source
if (-not $rclone) {
    $rclone = Get-ChildItem `
        "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Rclone.Rclone_*\rclone-*\rclone.exe" `
        -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $rclone) {
    throw "rclone이 없습니다. 설치: winget install Rclone.Rclone"
}
$remoteMatch = [regex]::Match($Remote, '^([A-Za-z0-9_.-]+):[^/\\].*$')
if (-not $remoteMatch.Success) {
    throw "rclone remote 형식 오류: $Remote"
}
$remoteName = $remoteMatch.Groups[1].Value + ":"
$savedErrorAction = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    $configuredRemotes = @(& $rclone listremotes 2>$null)
    $listRemotesExit = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $savedErrorAction
}
if ($listRemotesExit -ne 0 -or $configuredRemotes -notcontains $remoteName) {
    throw "rclone remote '$remoteName' 설정이 없습니다. 관리자 PC에서 rclone config를 먼저 실행하세요."
}

# export 전에 R2 원본 영상 목록을 한 번만 읽고, 같은 snapshot을 exporter와
# 게시 직전 private map 검증에서 함께 사용한다.
$videoListJson = & $rclone lsjson "$Remote/cctv" --files-only 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "R2 영상 목록 확인 실패: $($videoListJson -join [Environment]::NewLine)"
}
try {
    # ConvertFrom-Json returns a JSON root array as one pipeline object when it
    # is wrapped directly in @(...).  Assign first, then enumerate the array.
    $parsedVideoList = $videoListJson -join [Environment]::NewLine |
        ConvertFrom-Json
    $videoList = @($parsedVideoList)
} catch {
    throw "R2 영상 목록 JSON 오류: $($_.Exception.Message)"
}
$remoteVideos = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::Ordinal
)
foreach ($item in $videoList) {
    if ($item.IsDir -eq $true -or -not $item.Path) {
        continue
    }
    $videoName = [string]$item.Path
    if ($videoName -match '^[^/\\]+\.mp4$' -and -not $videoName.Contains("..")) {
        [void]$remoteVideos.Add("cctv/$videoName")
    }
}
if ($remoteVideos.Count -eq 0) {
    throw "R2에 게시 가능한 원본 영상이 없습니다."
}

$videoAllowlistPath = [IO.Path]::GetTempFileName()
try {
    $videoAllowlist = [ordered]@{
        schemaVersion = 1
        videoKeys = [string[]]@($remoteVideos | Sort-Object)
    } | ConvertTo-Json -Depth 3
    [IO.File]::WriteAllText(
        $videoAllowlistPath,
        $videoAllowlist + [Environment]::NewLine,
        [Text.UTF8Encoding]::new($false)
    )

    $exportArgs = @(
        (Join-Path $repoRoot "scripts\export_public_replays.py"),
        "--output", $OutputDir,
        "--private-video-map", $PrivateVideoMap,
        "--available-video-keys", $videoAllowlistPath,
        "--limit", "$Limit"
    )
    if ($NoTerrain) {
        $exportArgs += "--no-terrain"
    }

    Write-Host "== 공개 리플레이 정제 산출물 생성"
    & $python @exportArgs
    if ($LASTEXITCODE -ne 0) {
        throw "공개 리플레이 export 실패 (exit $LASTEXITCODE)"
    }
} finally {
    Remove-Item -LiteralPath $videoAllowlistPath -Force -ErrorAction SilentlyContinue
}

$replaysDir = Join-Path $OutputDir "replays"
$manifestPath = Join-Path $OutputDir "manifest.json"
if (-not (Test-Path -LiteralPath $replaysDir -PathType Container)) {
    throw "공개 replay 디렉터리 없음: $replaysDir"
}
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "공개 manifest 없음: $manifestPath"
}
if (-not (Test-Path -LiteralPath $PrivateVideoMap -PathType Leaf)) {
    throw "private video map 없음: $PrivateVideoMap"
}
try {
    $localManifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 |
        ConvertFrom-Json
} catch {
    throw "공개 manifest JSON 오류: $($_.Exception.Message)"
}
if (
    $localManifest.schema_version -ne 1 -or
    -not $localManifest.generated_at -or
    $null -eq $localManifest.rows
) {
    throw "공개 manifest schema 오류"
}

try {
    $newVideoMap = Get-Content -LiteralPath $PrivateVideoMap -Raw -Encoding UTF8 |
        ConvertFrom-Json
} catch {
    throw "private video map JSON 오류: $($_.Exception.Message)"
}
if ($newVideoMap.schemaVersion -ne 1 -or $null -eq $newVideoMap.videos) {
    throw "private video map schema 오류"
}

$newVideos = [ordered]@{}
foreach ($property in $newVideoMap.videos.PSObject.Properties) {
    $publicId = [string]$property.Name
    $objectKey = [string]$property.Value
    if ($publicId -notmatch '^[a-f0-9]{24}$') {
        throw "private video map ID 오류"
    }
    if ($objectKey -notmatch '^cctv/[^/\\]+\.mp4$' -or $objectKey.Contains("..")) {
        throw "private video map object key 오류"
    }
    if (-not $remoteVideos.Contains($objectKey)) {
        throw "R2 원본 영상 없음"
    }
    $newVideos[$publicId] = $objectKey
}

# 구 manifest를 캐시한 클라이언트가 새 map 게시 도중 404가 되지 않도록,
# 기존 map과 새 map의 합집합을 먼저 올린다. 오래된 항목 정리는 manifest
# 캐시 만료 뒤 별도 작업으로 수행한다.
$mergedVideos = [ordered]@{}
$internalList = & $rclone lsf "$Remote/_internal" --files-only `
    --include "public_video_map.json" 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "기존 private video map 확인 실패: $($internalList -join [Environment]::NewLine)"
}
if (@($internalList) -contains "public_video_map.json") {
    $oldMapJson = & $rclone cat "$Remote/_internal/public_video_map.json" 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "기존 private video map 다운로드 실패: $($oldMapJson -join [Environment]::NewLine)"
    }
    try {
        $oldVideoMap = $oldMapJson -join [Environment]::NewLine | ConvertFrom-Json
    } catch {
        throw "기존 private video map JSON 오류: $($_.Exception.Message)"
    }
    if ($oldVideoMap.schemaVersion -ne 1 -or $null -eq $oldVideoMap.videos) {
        throw "기존 private video map schema 오류"
    }
    foreach ($property in $oldVideoMap.videos.PSObject.Properties) {
        $publicId = [string]$property.Name
        $objectKey = [string]$property.Value
        if (
            $publicId -match '^[a-f0-9]{24}$' -and
            $objectKey -match '^cctv/[^/\\]+\.mp4$' -and
            -not $objectKey.Contains("..")
        ) {
            $mergedVideos[$publicId] = $objectKey
        }
    }
}
foreach ($entry in $newVideos.GetEnumerator()) {
    $mergedVideos[$entry.Key] = $entry.Value
}
$mergedMapPath = [IO.Path]::GetTempFileName()
$oldManifestPath = [IO.Path]::GetTempFileName()
$hadOldManifest = $false
$manifestPublished = $false
try {
    $publicList = & $rclone lsf "$Remote/public" --files-only `
        --include "manifest.json" 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "기존 공개 manifest 확인 실패: $($publicList -join [Environment]::NewLine)"
    }
    if (@($publicList) -contains "manifest.json") {
        & $rclone copyto "$Remote/public/manifest.json" $oldManifestPath
        if ($LASTEXITCODE -ne 0) {
            throw "기존 공개 manifest 백업 실패 (exit $LASTEXITCODE)"
        }
        $hadOldManifest = $true
    }

    $mergedMap = [ordered]@{
        schemaVersion = 1
        videos = $mergedVideos
    } | ConvertTo-Json -Depth 4
    [IO.File]::WriteAllText(
        $mergedMapPath,
        $mergedMap + [Environment]::NewLine,
        [Text.UTF8Encoding]::new($false)
    )

    Write-Host "== 공개 상세/프레임 업로드"
    & $rclone copy $replaysDir "$Remote/public/replays" `
        --checksum --transfers 4 --checkers 8
    if ($LASTEXITCODE -ne 0) {
        throw "공개 replay 업로드 실패 (exit $LASTEXITCODE)"
    }
    & $rclone check $replaysDir "$Remote/public/replays" --one-way
    if ($LASTEXITCODE -ne 0) {
        throw "공개 replay checksum 검증 실패 (exit $LASTEXITCODE)"
    }

    Write-Host "== 비공개 영상 매핑 업로드"
    & $rclone copyto $mergedMapPath "$Remote/_internal/public_video_map.json"
    if ($LASTEXITCODE -ne 0) {
        throw "private video map 업로드 실패 (exit $LASTEXITCODE)"
    }

    # manifest가 먼저 보이면 아직 없는 artifact/video를 사용자가 누를 수 있으므로 마지막에 게시.
    Write-Host "== 공개 manifest 게시"
    & $rclone copyto $manifestPath "$Remote/public/manifest.json"
    if ($LASTEXITCODE -ne 0) {
        throw "공개 manifest 업로드 실패 (exit $LASTEXITCODE)"
    }
    $manifestPublished = $true

    $remoteManifestJson = & $rclone cat "$Remote/public/manifest.json" 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "게시 manifest 재확인 실패: $($remoteManifestJson -join [Environment]::NewLine)"
    }
    try {
        $remoteManifest = $remoteManifestJson -join [Environment]::NewLine |
            ConvertFrom-Json
    } catch {
        throw "게시 manifest JSON 오류: $($_.Exception.Message)"
    }
    if (
        $remoteManifest.schema_version -ne 1 -or
        $remoteManifest.generated_at -ne $localManifest.generated_at -or
        @($remoteManifest.rows).Count -ne @($localManifest.rows).Count
    ) {
        throw "게시 manifest 검증 불일치"
    }
} catch {
    $publishError = $_
    if ($manifestPublished) {
        if ($hadOldManifest) {
            & $rclone copyto $oldManifestPath "$Remote/public/manifest.json"
        } else {
            & $rclone deletefile "$Remote/public/manifest.json"
        }
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "이전 manifest 복원에도 실패했습니다. 관리자 확인이 필요합니다."
        }
    }
    throw $publishError
} finally {
    Remove-Item -LiteralPath $mergedMapPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $oldManifestPath -Force -ErrorAction SilentlyContinue
}

Write-Host "완료: 공개 리플레이 $Remote/public"
