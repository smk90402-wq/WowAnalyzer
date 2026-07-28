function Get-CctvStartTime {
    param(
        [Parameter(Mandatory = $true)]$JsonFile,
        [Parameter(Mandatory = $true)]$Meta
    )

    if ($Meta.PSObject.Properties.Name -contains 'start') {
        try {
            $startMs = [int64]$Meta.start
            if ($startMs -gt 0) {
                return [DateTimeOffset]::FromUnixTimeMilliseconds($startMs).LocalDateTime
            }
        } catch {
            # 파일명 시각 폴백으로 계속한다.
        }
    }

    $prefix = if ($JsonFile.BaseName.Length -ge 19) {
        $JsonFile.BaseName.Substring(0, 19)
    } else {
        ''
    }
    $parsed = [datetime]::MinValue
    if ([datetime]::TryParseExact(
        $prefix,
        'yyyy-MM-dd HH-mm-ss',
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::None,
        [ref]$parsed
    )) {
        return $parsed
    }
    return $null
}

function Get-WowLogStartTime {
    param([Parameter(Mandatory = $true)]$LogFile)

    $match = [regex]::Match(
        $LogFile.Name,
        'WoWCombatLog-(\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})'
    )
    if (-not $match.Success) {
        return $null
    }
    try {
        return [datetime]::new(
            2000 + [int]$match.Groups[3].Value,
            [int]$match.Groups[1].Value,
            [int]$match.Groups[2].Value,
            [int]$match.Groups[4].Value,
            [int]$match.Groups[5].Value,
            [int]$match.Groups[6].Value
        )
    } catch {
        return $null
    }
}

function Get-LuraP2Pulls {
    param(
        [Parameter(Mandatory = $true)][string]$LogDir,
        [Parameter(Mandatory = $true)][datetime[]]$CaptureStarts
    )

    if (-not (Test-Path -LiteralPath $LogDir) -or $CaptureStarts.Count -eq 0) {
        return @()
    }

    $logFiles = [System.Collections.Generic.List[object]]::new()
    foreach ($root in @($LogDir, (Join-Path $LogDir 'warcraftlogsarchive'))) {
        if (-not (Test-Path -LiteralPath $root)) {
            continue
        }
        foreach (
            $logFile in Get-ChildItem -LiteralPath $root -Filter '*WoWCombatLog-*.txt' -File
        ) {
            if (-not ($logFiles.FullName -contains $logFile.FullName)) {
                [void]$logFiles.Add($logFile)
            }
        }
    }

    $candidateLogs = [System.Collections.Generic.List[object]]::new()
    foreach ($logFile in $logFiles) {
        $fileStart = Get-WowLogStartTime -LogFile $logFile
        if ($null -eq $fileStart) {
            continue
        }
        $endGuess = $logFile.LastWriteTime
        if ($endGuess -lt $fileStart) {
            $endGuess = $fileStart.AddHours(24)
        }
        foreach ($captureStart in $CaptureStarts) {
            if (
                $captureStart -ge $fileStart.AddMinutes(-2) -and
                $captureStart -le $endGuess.AddMinutes(2)
            ) {
                [void]$candidateLogs.Add($logFile)
                break
            }
        }
    }

    $findstr = Join-Path $env:WINDIR 'System32\findstr.exe'
    if (-not (Test-Path -LiteralPath $findstr)) {
        throw "findstr.exe를 찾을 수 없습니다: $findstr"
    }

    $pulls = [System.Collections.Generic.List[object]]::new()
    foreach ($logFile in $candidateLogs) {
        $lines = @(
            & $findstr `
                '/c:ENCOUNTER_START,3183,' `
                '/c:ENCOUNTER_END,3183,' `
                '/c:,1282043,' `
                '/c:,1284528,' `
                '/c:,1284525,' `
                $logFile.FullName
        )
        $findExit = $LASTEXITCODE
        if ($findExit -gt 1) {
            throw "르우라 P2 로그 검색 실패: $($logFile.FullName) (exit $findExit)"
        }

        $current = $null
        foreach ($line in $lines) {
            $lineMatch = [regex]::Match(
                $line,
                '^(?<ts>\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}:\d{2}\.\d+)\s{2}(?<payload>.*)$'
            )
            if (-not $lineMatch.Success) {
                continue
            }
            $timestamp = [datetime]::MinValue
            if (-not [datetime]::TryParse(
                $lineMatch.Groups['ts'].Value,
                [Globalization.CultureInfo]::InvariantCulture,
                [Globalization.DateTimeStyles]::None,
                [ref]$timestamp
            )) {
                continue
            }
            $payload = $lineMatch.Groups['payload'].Value

            if ($payload.StartsWith('ENCOUNTER_START,3183,')) {
                $current = [pscustomobject]@{
                    Start = $timestamp
                    Reached = $false
                }
                continue
            }
            if ($null -eq $current) {
                continue
            }

            $primary = (
                $payload.StartsWith('SPELL_CAST_SUCCESS,') -and
                $payload.Contains(',1282043,')
            )
            $fallback = (
                (
                    $payload.StartsWith('SPELL_CAST_START,') -and
                    $payload.Contains(',1284528,')
                ) -or (
                    $payload.StartsWith('SPELL_CAST_SUCCESS,') -and
                    $payload.Contains(',1284525,')
                )
            )
            if ($primary -or $fallback) {
                $current.Reached = $true
                continue
            }

            if ($payload.StartsWith('ENCOUNTER_END,3183,')) {
                $parts = $payload.Split(',')
                if ($parts.Count -gt 5 -and [int]$parts[5] -eq 1) {
                    $current.Reached = $true
                }
                [void]$pulls.Add($current)
                $current = $null
            }
        }
    }
    return $pulls.ToArray()
}

function New-CctvUploadManifest {
    param(
        [Parameter(Mandatory = $true)][string]$SourceDir,
        [Parameter(Mandatory = $true)][string]$LogDir
    )

    $MinReplaySeconds = 120.0
    $LuraEncounterId = 3183

    $jsonFiles = @(Get-ChildItem -LiteralPath $SourceDir -Filter '*.json' -File)
    $videoFiles = @(Get-ChildItem -LiteralPath $SourceDir -File |
        Where-Object { $_.Extension -ieq '.mp4' })
    $records = [System.Collections.Generic.List[object]]::new()

    foreach ($jsonFile in $jsonFiles) {
        try {
            $meta = Get-Content -LiteralPath $jsonFile.FullName -Raw -Encoding utf8 |
                ConvertFrom-Json
        } catch {
            throw "CCTV JSON 파싱 실패: $($jsonFile.FullName)"
        }
        if (-not ($meta.PSObject.Properties.Name -contains 'duration')) {
            throw "CCTV duration 누락: $($jsonFile.FullName)"
        }
        [void]$records.Add([pscustomobject]@{
            JsonFile = $jsonFile
            Meta = $meta
            Duration = [double]$meta.duration
            EncounterId = [int]$meta.encounterID
            Result = [bool]$meta.result
            StartTime = (Get-CctvStartTime -JsonFile $jsonFile -Meta $meta)
        })
    }

    $luraStarts = @(
        $records |
            Where-Object {
                $_.EncounterId -eq $LuraEncounterId -and
                -not $_.Result -and
                $null -ne $_.StartTime
            } |
            ForEach-Object { $_.StartTime }
    )
    $luraPulls = if ($luraStarts.Count -gt 0) {
        @(Get-LuraP2Pulls -LogDir $LogDir -CaptureStarts $luraStarts)
    } else {
        @()
    }

    $selected = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::Ordinal
    )
    $keptCaptures = 0
    $excludedCaptures = 0
    $luraUnknown = 0

    foreach ($record in $records) {
        $keep = $false
        if ($record.EncounterId -eq $LuraEncounterId) {
            if ($record.Result) {
                $keep = $true
            } elseif ($null -ne $record.StartTime) {
                $nearest = $null
                $nearestDelta = [double]::PositiveInfinity
                foreach ($pull in $luraPulls) {
                    $delta = [math]::Abs(
                        ($pull.Start - $record.StartTime).TotalSeconds
                    )
                    if ($delta -lt $nearestDelta) {
                        $nearest = $pull
                        $nearestDelta = $delta
                    }
                }
                if ($null -ne $nearest -and $nearestDelta -le 8.0) {
                    $keep = [bool]$nearest.Reached
                } else {
                    $luraUnknown++
                }
            } else {
                $luraUnknown++
            }
        } else {
            $keep = $record.Duration -ge $MinReplaySeconds
        }

        if (-not $keep) {
            $excludedCaptures++
            continue
        }

        $keptCaptures++
        [void]$selected.Add($record.JsonFile.Name)
        foreach ($videoFile in $videoFiles) {
            if ($videoFile.BaseName.StartsWith(
                $record.JsonFile.BaseName,
                [System.StringComparison]::Ordinal
            )) {
                [void]$selected.Add($videoFile.Name)
            }
        }
    }

    $manifestPath = Join-Path (
        [System.IO.Path]::GetTempPath()
    ) ("wowanalyzer-cctv-upload-{0}.txt" -f [guid]::NewGuid().ToString('N'))
    [System.IO.File]::WriteAllLines(
        $manifestPath,
        @($selected | Sort-Object),
        [System.Text.UTF8Encoding]::new($false)
    )
    [pscustomobject]@{
        Path = $manifestPath
        Files = $selected.Count
        KeptCaptures = $keptCaptures
        ExcludedCaptures = $excludedCaptures
        LuraUnknown = $luraUnknown
    }
}
