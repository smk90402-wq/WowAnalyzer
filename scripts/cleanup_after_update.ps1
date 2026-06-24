$ErrorActionPreference = 'Continue'

$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $root

function Test-UnderRoot {
  param([Parameter(Mandatory=$true)][string]$Path)
  try {
    $resolved = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
  } catch {
    return $false
  }
  return $resolved.Equals($root, [System.StringComparison]::OrdinalIgnoreCase) -or
    $resolved.StartsWith($root + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)
}

function Test-CanWriteDirectory {
  param([Parameter(Mandatory=$true)][string]$Path)
  $probe = Join-Path $Path ".codex_write_probe_$PID.tmp"
  try {
    Set-Content -LiteralPath $probe -Value 'probe' -NoNewline -ErrorAction Stop
    Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
    return $true
  } catch {
    Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
    return $false
  }
}

Write-Host "Cleaning generated temp files only; v2_cache_*.json is kept local."

if (Get-Command git -ErrorAction SilentlyContinue) {
  git lfs version *> $null
  if ($LASTEXITCODE -eq 0) {
    Write-Host "Pruning Git LFS local cache..."
    git lfs prune --verify-remote
  }

  $gitDir = Join-Path $root '.git'
  if ((Test-Path -LiteralPath $gitDir) -and (Test-CanWriteDirectory -Path $gitDir)) {
    Write-Host "Running Git object cleanup..."
    git gc --prune=now
  } else {
    Write-Host "Skipping Git object cleanup; .git is not writable in this context."
  }
}

Write-Host "Removing generated temp files..."
Get-ChildItem -LiteralPath (Join-Path $root 'data') -Force -File -Filter 'v2_cache_*.json.tmp' -ErrorAction SilentlyContinue |
  Remove-Item -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath (Join-Path $root 'data') -Force -File -Filter '*.tmp' -ErrorAction SilentlyContinue |
  Remove-Item -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath (Join-Path $root 'data') -Force -File -Filter 'tmp_*' -ErrorAction SilentlyContinue |
  Remove-Item -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath $root -Force -File -Filter '*.log' -ErrorAction SilentlyContinue |
  Remove-Item -Force -ErrorAction SilentlyContinue

Get-ChildItem -LiteralPath $root -Force -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
  ForEach-Object {
    if (Test-UnderRoot -Path $_.FullName) {
      Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
    } else {
      Write-Warning "Skipped path outside workspace: $($_.FullName)"
    }
  }

$drive = Get-PSDrive -Name C -ErrorAction SilentlyContinue
if ($null -eq $drive -or $null -eq $drive.Used -or $null -eq $drive.Free -or (($drive.Used -eq 0) -and ($drive.Free -eq 0))) {
  Write-Host "C: total/free space is unavailable in this sandbox."
} else {
  $drive |
    Select-Object Name,
      @{Name='UsedGB';Expression={[math]::Round($_.Used/1GB,2)}},
      @{Name='FreeGB';Expression={[math]::Round($_.Free/1GB,2)}} |
    Format-Table -AutoSize
}
