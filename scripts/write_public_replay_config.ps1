param(
    [Parameter(Mandatory = $true)]
    [string]$Destination,
    [string]$BaseUrl = $env:WOWANALYZER_PUBLIC_REPLAY_BASE_URL,
    [string]$ManifestUrl = $env:WOWANALYZER_PUBLIC_REPLAY_MANIFEST_URL
)

$ErrorActionPreference = "Stop"

$base = $BaseUrl.Trim().TrimEnd("/")
$baseUri = $null
if (
    -not [Uri]::TryCreate($base, [UriKind]::Absolute, [ref]$baseUri) -or
    $baseUri.Scheme -ne "https" -or
    -not $baseUri.Host -or
    $baseUri.UserInfo -or
    $baseUri.Query -or
    $baseUri.Fragment
) {
    throw "Public replay base URL must be an HTTPS origin/path without credentials, query, or fragment."
}

$config = [ordered]@{ base_url = $base }
if ($ManifestUrl.Trim()) {
    $manifest = $ManifestUrl.Trim()
    $manifestUri = $null
    if (
        -not [Uri]::TryCreate($manifest, [UriKind]::Absolute, [ref]$manifestUri) -or
        $manifestUri.Scheme -ne "https" -or
        -not $manifestUri.Host -or
        $manifestUri.UserInfo -or
        $manifestUri.Fragment
    ) {
        throw "Public replay manifest URL must be HTTPS and contain no credentials or fragment."
    }
    $config.manifest_url = $manifest
}

$destinationPath = [IO.Path]::GetFullPath($Destination)
$parent = Split-Path -Parent $destinationPath
if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
    throw "Public package directory does not exist: $parent"
}

$json = $config | ConvertTo-Json
[IO.File]::WriteAllText(
    $destinationPath,
    $json + [Environment]::NewLine,
    [Text.UTF8Encoding]::new($false)
)
