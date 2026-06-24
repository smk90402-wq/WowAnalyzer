$ErrorActionPreference = 'Continue'

$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path

function Measure-PathSize {
  param([Parameter(Mandatory=$true)][string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) {
    return
  }
  $sum = Get-ChildItem -LiteralPath $Path -Force -Recurse -File -ErrorAction SilentlyContinue |
    Measure-Object Length -Sum
  [PSCustomObject]@{
    Path = $Path
    Files = $sum.Count
    GB = [math]::Round(($sum.Sum / 1GB), 2)
    MB = [math]::Round(($sum.Sum / 1MB), 1)
  }
}

@(
  $root
  (Join-Path $root 'data')
  (Join-Path $root '.git')
  (Join-Path $root '.git\lfs')
  (Join-Path $root '.git\lfs\tmp')
  (Join-Path $root '.git\lfs\objects')
  'C:\$Recycle.Bin'
  'C:\OneDriveTemp'
) | ForEach-Object { Measure-PathSize -Path $_ } | Format-Table -AutoSize

Write-Host ""
Write-Host "Largest generated data files:"
Get-ChildItem -LiteralPath (Join-Path $root 'data') -Force -File -ErrorAction SilentlyContinue |
  Sort-Object Length -Descending |
  Select-Object -First 12 Name,
    @{Name='GB';Expression={[math]::Round($_.Length/1GB, 2)}},
    @{Name='MB';Expression={[math]::Round($_.Length/1MB, 1)}},
    LastWriteTime |
  Format-Table -AutoSize

Write-Host ""
$drive = Get-PSDrive -Name C -ErrorAction SilentlyContinue
if ($null -eq $drive -or $null -eq $drive.Used -or $null -eq $drive.Free -or (($drive.Used -eq 0) -and ($drive.Free -eq 0))) {
  Write-Host "C: total/free space is unavailable in this sandbox; folder sizes above are still measured directly."
} else {
  $drive |
    Select-Object Name,
      @{Name='UsedGB';Expression={[math]::Round($_.Used/1GB,2)}},
      @{Name='FreeGB';Expression={[math]::Round($_.Free/1GB,2)}} |
    Format-Table -AutoSize
}
