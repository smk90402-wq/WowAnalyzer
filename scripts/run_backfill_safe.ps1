$ErrorActionPreference = 'Stop'

$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $root

$env:LOGANALYZE_MIN_FREE_GB = if ($env:LOGANALYZE_MIN_FREE_GB) {
  $env:LOGANALYZE_MIN_FREE_GB
} else {
  '50'
}

try {
  $pythonCandidates = @(
    $env:LOGANALYZE_PYTHON,
    (Join-Path $root '.venv\Scripts\python.exe'),
    'python',
    'py'
  ) | Where-Object { $_ }

  $python = $null
  foreach ($candidate in $pythonCandidates) {
    if ($candidate -eq 'python' -or $candidate -eq 'py') {
      $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
      if ($cmd) {
        $python = $cmd.Source
        break
      }
    } elseif (Test-Path -LiteralPath $candidate) {
      $python = $candidate
      break
    }
  }

  if (-not $python) {
    throw 'Python executable not found. Set LOGANALYZE_PYTHON or create .venv.'
  }

  & $python backfill_v2.py @args
} finally {
  powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'cleanup_after_update.ps1')
}
