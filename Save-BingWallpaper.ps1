<#
.SYNOPSIS
    Downloads Bing daily wallpapers from GitHub-hosted wallpaper index.
.DESCRIPTION
    Fetches Bing wallpapers in 4K resolution from the niumoo/bing-wallpaper
    GitHub repository and saves them to a local directory.
    Without -Date, downloads wallpapers for the past N days (default: 7).
    With -Date, downloads wallpaper for a specific date only.
.PARAMETER OutputPath
    Destination directory for the downloaded wallpapers.
    Default: current working directory.
.PARAMETER Date
    Target date in yyyy-MM-dd format.
    If not provided, downloads wallpapers for the past NumDays days (default: 7).
    If provided, downloads that date's wallpaper and saves as yyyy-MM-dd.jpg.
.PARAMETER NumDays
    Number of past days to download when -Date is not specified.
    Default: 7. Valid range: 1 to 365.
.PARAMETER RetentionDays
    Number of days to retain downloaded files. Files older than this
    will be deleted before downloading. Set to 0 to never delete.
    Default: 14. Valid range: 0 to 3650.
.EXAMPLE
    .\Save-BingWallpaper.ps1
    Downloads wallpapers for the past 7 days.
.EXAMPLE
    .\Save-BingWallpaper.ps1 -NumDays 30
    Downloads wallpapers for the past 30 days.
.EXAMPLE
    .\Save-BingWallpaper.ps1 -Date "2026-04-30"
    Downloads wallpaper for April 30, 2026 only.
.EXAMPLE
    .\Save-BingWallpaper.ps1 -OutputPath "C:\MyWallpapers" -Date "2026-05-01"
    Downloads wallpaper for May 1, 2026 to C:\MyWallpapers.
#>

[CmdletBinding()]
param(
    [string]$OutputPath = $PWD.Path,
    [ValidateScript({
        if ($_ -match '^\d{4}-\d{2}-\d{2}$') {
            $parsed = [datetime]::ParseExact($_, 'yyyy-MM-dd', $null)
            if ($parsed -le [datetime]::Today) {
                $true
            } else {
                throw "Date cannot be in the future."
            }
        } else {
            throw "Date must be in yyyy-MM-dd format."
        }
    })]
    [string]$Date = $null,
    [ValidateRange(1, 365)]
    [int]$NumDays = 7,
    [ValidateRange(0, 3650)]
    [int]$RetentionDays = 14
)

# ============================================================
#  Network connectivity check
# ============================================================
$activeAdapters = Get-NetAdapter -Physical -ErrorAction SilentlyContinue |
    Where-Object { $_.Status -eq 'Up' }

if (-not $activeAdapters) {
    throw "No active network connection detected. Please connect to WiFi or Ethernet and try again."
}

$adapterNames = ($activeAdapters | ForEach-Object { "$($_.Name) ($($_.InterfaceDescription))" }) -join '; '
Write-Information "Network OK - active adapter(s): ${adapterNames}" -InformationAction Continue

# ============================================================
#  Helper: Fetch wallpaper 4K URLs from GitHub monthly READMEs
# ============================================================
function Get-WallpaperData {
    param(
        [string[]]$Dates,
        [int]$TimeoutSec = 30
    )

    # Determine which months to fetch based on requested dates
    $months = [System.Collections.Generic.HashSet[string]]::new()
    foreach ($dateStr in $Dates) {
        if ($dateStr -match '^(\d{4})-(\d{2})-\d{2}$') {
            $yearMonth = "$($Matches[1])-$($Matches[2])"
            [void]$months.Add($yearMonth)
        }
    }

    $dateUrlMap = @{}

    foreach ($yearMonth in $months) {
        $readmeUrl = "https://github.com/niumoo/bing-wallpaper/raw/refs/heads/main/zh-cn/picture/${yearMonth}/README.md"
        Write-Information "Fetching wallpaper index for ${yearMonth}..." -InformationAction Continue

        try {
            $readmeResponse = Invoke-WebRequest -Uri $readmeUrl -TimeoutSec $TimeoutSec -UseBasicParsing
            $readmeText = $readmeResponse.Content
        } catch {
            Write-Warning "Failed to fetch README for ${yearMonth}: $_"
            continue
        }

        # Parse date + 4K URL pairs from markdown table
        # Pattern: YYYY-MM-DD [download 4k](URL)
        $pattern = '(\d{4}-\d{2}-\d{2})\s*\[download 4k\]\(([^)]+)\)'
        $regexMatches = [regex]::Matches($readmeText, $pattern)

        foreach ($m in $regexMatches) {
            $parsedDate = $m.Groups[1].Value
            $url = $m.Groups[2].Value
            # Keep only the first occurrence in case of duplicates
            if (-not $dateUrlMap.ContainsKey($parsedDate)) {
                $dateUrlMap[$parsedDate] = $url
            }
        }

        Write-Information "  Found $($regexMatches.Count) wallpaper entries for ${yearMonth}." -InformationAction Continue
    }

    return $dateUrlMap
}

# ============================================================
#  Main logic
# ============================================================
$today = [datetime]::Today

# Build list of date strings to download
if ($Date) {
    $dateStrings = @($Date)
} else {
    $dateStrings = @()
    for ($i = 0; $i -lt $NumDays; $i++) {
        $d = $today.AddDays(-$i)
        $dateStrings += $d.ToString('yyyy-MM-dd')
    }
}

# Fetch 4K URL index from GitHub
Write-Information "Fetching wallpaper index for $($dateStrings.Count) date(s)..." -InformationAction Continue
$dateUrlMap = Get-WallpaperData -Dates $dateStrings

if ($dateUrlMap.Count -eq 0) {
    throw "No wallpaper data found for the requested date(s)."
}

# Build download tasks
$downloadTasks = @()
foreach ($dateStr in $dateStrings) {
    if ($dateUrlMap.ContainsKey($dateStr)) {
        $downloadTasks += @{
            DateStr    = $dateStr
            OutputFile = Join-Path -Path $OutputPath -ChildPath "${dateStr}.jpg"
            DownloadUrl = $dateUrlMap[$dateStr]
        }
    } else {
        Write-Warning "No wallpaper data found for ${dateStr}. Skipping."
    }
}

if ($downloadTasks.Count -eq 0) {
    throw "No valid download tasks to process."
}

# Ensure output directory exists
try {
    if (-not (Test-Path -Path $OutputPath -PathType Container)) {
        New-Item -Path $OutputPath -ItemType Directory -Force | Out-Null
    }
} catch {
    Write-Error "Failed to create output directory '${OutputPath}': $_"
    exit 1
}

# Remove expired wallpapers (files older than RetentionDays)
if ($RetentionDays -gt 0) {
    $cutoffDate = $today.AddDays(-$RetentionDays)
    Write-Information "Removing wallpapers older than ${RetentionDays} day(s) (before $($cutoffDate.ToString('yyyy-MM-dd')))..." -InformationAction Continue
    $deletedCount = 0
    Get-ChildItem -Path $OutputPath -Filter '*.jpg' -File | ForEach-Object {
        if ($_.Name -match '^(\d{4})-(\d{2})-(\d{2})\.jpg$') {
            $fY = $Matches[1]; $fM = $Matches[2]; $fD = $Matches[3]
            $fileDate = [datetime]::ParseExact("${fY}${fM}${fD}", 'yyyyMMdd', $null)
            if ($fileDate -lt $cutoffDate) {
                try {
                    Remove-Item -LiteralPath $_.FullName -Force
                    Write-Information "  Deleted: $($_.Name)" -InformationAction Continue
                    $deletedCount++
                } catch {
                    Write-Error "Failed to delete $($_.Name): $_"
                }
            }
        }
    }
    Write-Information "Expired files cleaned: ${deletedCount} deleted." -InformationAction Continue
}

# Download each wallpaper
$downloadCount = 0
$failCount = 0
$skipCount = 0

foreach ($task in $downloadTasks) {
    $dateStr = $task.DateStr
    $outputFile = $task.OutputFile
    $downloadUrl = $task.DownloadUrl

    # Skip if file already exists
    if (Test-Path -Path $outputFile) {
        Write-Information "Skipping ${dateStr}: file already exists." -InformationAction Continue
        $skipCount++
        continue
    }

    Write-Information "Downloading ${dateStr}: ${downloadUrl}" -InformationAction Continue
    Write-Information "Saving to: ${outputFile}" -InformationAction Continue

    try {
        Invoke-WebRequest -Uri $downloadUrl -OutFile $outputFile -TimeoutSec 120 -UseBasicParsing
    } catch {
        Write-Error "Download failed for ${dateStr}: $_"
        # Clean up partial file if any
        if (Test-Path -Path $outputFile) {
            Remove-Item -Path $outputFile -Force
        }
        $failCount++
        continue
    }

    if (Test-Path -Path $outputFile) {
        $size = (Get-Item -Path $outputFile).Length
        Write-Information "Download complete: ${outputFile} (Size: $([math]::Round($size/1KB, 1)) KB)" -InformationAction Continue
        $downloadCount++
    } else {
        Write-Error "Download appeared to succeed for ${dateStr} but output file not found."
        $failCount++
    }
}

Write-Information "Finished: ${downloadCount} downloaded, ${skipCount} skipped, ${failCount} failed, $($downloadTasks.Count) total." -InformationAction Continue

if ($failCount -gt 0) {
    exit 1
}
