param(
    [Parameter(Mandatory = $true)]
    [string]$Destination
)

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$distRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot 'dist'))
$destinationRoot = if ([IO.Path]::IsPathRooted($Destination)) {
    [IO.Path]::GetFullPath($Destination)
} else {
    [IO.Path]::GetFullPath((Join-Path $repoRoot $Destination))
}

$distPrefix = $distRoot.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
if (-not $destinationRoot.StartsWith($distPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Public data destination must be inside $distRoot"
}

$dataDestination = Join-Path $destinationRoot 'data'
if (Test-Path -LiteralPath $dataDestination) {
    $dataItem = Get-Item -LiteralPath $dataDestination -Force
    if (($dataItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing to replace reparse point: $dataDestination"
    }
    $resolvedData = [IO.Path]::GetFullPath($dataItem.FullName)
    $destinationPrefix = $destinationRoot.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    if (-not $resolvedData.StartsWith($destinationPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to replace data outside $destinationRoot"
    }
    Remove-Item -LiteralPath $dataDestination -Recurse -Force
}
New-Item -ItemType Directory -Path $dataDestination | Out-Null

$allowlistPath = Join-Path $repoRoot 'packaging\public_data_allowlist.txt'
if (-not (Test-Path -LiteralPath $allowlistPath -PathType Leaf)) {
    throw "Public data allowlist is missing: $allowlistPath"
}
$trackedFiles = @(
    Get-Content -LiteralPath $allowlistPath -Encoding UTF8 |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ -and -not $_.StartsWith('#') }
)
if ($trackedFiles.Count -eq 0) {
    throw 'Public data allowlist is empty'
}

$forbiddenContent = [regex]::new(
    '(?i)(?:(?<![a-z0-9])[a-z]:[\\/]|\\\\[^\\\r\n]+\\|/(?:users|home)/|' +
    'wowcombatlog|player-\d+-[a-z0-9-]+|rclone(?:\.conf)?|' +
    'wcl_v2_client_secret|secret_access_key|access_key_id)'
)

$copied = 0
foreach ($relativePath in $trackedFiles) {
    $normalizedPath = $relativePath.Replace('\', '/')
    if (
        -not $normalizedPath.StartsWith('data/', [StringComparison]::Ordinal) -or
        $normalizedPath.Contains('..') -or
        [IO.Path]::IsPathRooted($normalizedPath)
    ) {
        throw "Unsafe public data allowlist path: $relativePath"
    }
    & git -C $repoRoot ls-files --error-unmatch -- $normalizedPath 2>$null >$null
    if ($LASTEXITCODE -ne 0) {
        throw "Public data allowlist entry is not Git-tracked: $relativePath"
    }

    $sourcePath = Join-Path $repoRoot $relativePath
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "Tracked public data file is missing: $relativePath"
    }
    $content = Get-Content -LiteralPath $sourcePath -Raw -Encoding UTF8
    $match = $forbiddenContent.Match($content)
    if ($match.Success) {
        throw "Private marker '$($match.Value)' found in public data: $relativePath"
    }

    $targetPath = Join-Path $destinationRoot $relativePath
    $targetDirectory = Split-Path -Parent $targetPath
    if (-not (Test-Path -LiteralPath $targetDirectory)) {
        New-Item -ItemType Directory -Path $targetDirectory | Out-Null
    }
    Copy-Item -LiteralPath $sourcePath -Destination $targetPath -Force
    $copied++
}

Write-Host "Copied $copied Git-tracked public data files to $dataDestination"
