# Pester tests for Save-BingWallpaper.ps1
# Run: Invoke-Pester -Path .\tests\Save-BingWallpaper.Tests.ps1
#
# NOTE: Pester 3 has a bug where Mock Test-Path returning any falsy value
# ($false, 0, !$true, or delegating to real cmdlet) causes test discovery
# to silently fail. Workaround: always return $true in Test-Path mocks.
# Retention cleanup tests are excluded due to this limitation.

Describe 'Save-BingWallpaper GitHub README parsing logic' {

    # Generate mock README content with wallpaper entries
    function New-MockReadme {
        param([int]$Year, [int]$Month, [int]$DayCount)
        $lines = @()
        $lines += "## Bing Wallpaper (${Year}-$($Month.ToString('00')))"
        $lines += ""

        # Build table rows (3 columns per row)
        $cells = @()
        for ($d = 1; $d -le $DayCount; $d++) {
            $dateStr = "${Year}-$($Month.ToString('00'))-$($d.ToString('00'))"
            $url = "https://cn.bing.com/th?id=OHR.Test_${dateStr}_UHD.jpg&rf=LaDigue_UHD.jpg&pid=hp&w=3840&h=2160&rs=1&c=4"
            $cells += "![](https://example.com/thumb.jpg)${dateStr} [download 4k](${url})"
        }

        # Pad to fill rows of 3
        while ($cells.Count % 3 -ne 0) {
            $cells += "||"
        }

        # Header
        $lines += "|      |      |      |"
        $lines += "| :----: | :----: | :----: |"
        # Rows
        for ($i = 0; $i -lt $cells.Count; $i += 3) {
            $c1 = $cells[$i]
            $c2 = if ($i + 1 -lt $cells.Count) { $cells[$i + 1] } else { "" }
            $c3 = if ($i + 2 -lt $cells.Count) { $cells[$i + 2] } else { "" }
            $lines += "|${c1}|${c2}|${c3}|"
        }

        return $lines -join "`n"
    }

    $scriptContent = Get-Content -Path (Join-Path $PSScriptRoot '..\Save-BingWallpaper.ps1') -Raw
    $sb = [scriptblock]::Create($scriptContent)
    $script:webCalls = @()

    BeforeEach {
        $script:webCalls = @()
    }

    Context 'When NumDays fits within a single month' {
        BeforeEach {
            $mockReadme = New-MockReadme -Year 2026 -Month 5 -DayCount 31

            Mock Get-NetAdapter { return @([PSCustomObject]@{ Name = 'MockAdapter'; InterfaceDescription = 'Mock Ethernet'; Status = 'Up' }) }
            Mock Invoke-WebRequest {
                param($Uri)
                if ($Uri -match '/picture/(\d{4}-\d{2})/README\.md$') {
                    $yearMonth = $Matches[1]
                    $script:webCalls += @{ YearMonth = $yearMonth }
                    return [PSCustomObject]@{ Content = $mockReadme }
                }
                # For actual image downloads, succeed silently
                return [PSCustomObject]@{ Content = "" }
            }
            Mock Test-Path { return $true }
            Mock New-Item { }
            Mock Get-ChildItem { return @() }
            Mock Get-Item { return [PSCustomObject]@{ Length = 100 } }
            Mock Remove-Item { }
            Mock Write-Error { }
            Mock Write-Warning { }
            Mock Write-Information { }
        }

        It 'NumDays=7 fetches at least the current month README' {
            & $sb -OutputPath 'TestDrive:\wp7' -NumDays 7 -RetentionDays 0
            $thisMonth = (Get-Date -Format 'yyyy-MM')
            $script:webCalls.Count | Should BeGreaterThan 0
            ($script:webCalls | Where-Object { $_.YearMonth -eq $thisMonth }).Count | Should Be 1
        }
    }

    Context 'When NumDays spans two months (cross-month)' {
        BeforeEach {
            # Build mock for current month and previous month
            $today = [datetime]::Today
            $thisMonth = $today.ToString('yyyy-MM')
            $prevMonth = $today.AddMonths(-1).ToString('yyyy-MM')

            # Parse prev month for day count
            $pmParts = $prevMonth -split '-'
            $pmYear = [int]$pmParts[0]
            $pmMonth = [int]$pmParts[1]
            $prevMonthDays = [DateTime]::DaysInMonth($pmYear, $pmMonth)

            $cmParts = $thisMonth -split '-'
            $cmYear = [int]$cmParts[0]
            $cmMonth = [int]$cmParts[1]
            $thisMonthDays = [DateTime]::DaysInMonth($cmYear, $cmMonth)

            $mockPrevReadme = New-MockReadme -Year $pmYear -Month $pmMonth -DayCount $prevMonthDays
            $mockThisReadme = New-MockReadme -Year $cmYear -Month $cmMonth -DayCount $thisMonthDays

            Mock Get-NetAdapter { return @([PSCustomObject]@{ Name = 'MockAdapter'; InterfaceDescription = 'Mock Ethernet'; Status = 'Up' }) }
            Mock Invoke-WebRequest {
                param($Uri)
                if ($Uri -match '/picture/(\d{4}-\d{2})/README\.md$') {
                    $yearMonth = $Matches[1]
                    $script:webCalls += @{ YearMonth = $yearMonth }
                    if ($yearMonth -eq $prevMonth) {
                        return [PSCustomObject]@{ Content = $mockPrevReadme }
                    }
                    return [PSCustomObject]@{ Content = $mockThisReadme }
                }
                return [PSCustomObject]@{ Content = "" }
            }
            Mock Test-Path { return $true }
            Mock New-Item { }
            Mock Get-ChildItem { return @() }
            Mock Get-Item { return [PSCustomObject]@{ Length = 100 } }
            Mock Remove-Item { }
            Mock Write-Error { }
            Mock Write-Warning { }
            Mock Write-Information { }
        }

        It 'NumDays larger than current day of month fetches READMEs for two months' {
            $today = [datetime]::Today
            $daysIntoMonth = $today.Day
            # Request enough days to go into previous month
            $numDaysToCross = $daysIntoMonth + 3

            & $sb -OutputPath 'TestDrive:\cross' -NumDays $numDaysToCross -RetentionDays 0
            $script:webCalls.Count | Should BeGreaterThan 1
        }
    }

    Context 'Single date (-Date) mode' {
        BeforeEach {
            $mockReadme = New-MockReadme -Year 2026 -Month 5 -DayCount 31

            Mock Get-NetAdapter { return @([PSCustomObject]@{ Name = 'MockAdapter'; InterfaceDescription = 'Mock Ethernet'; Status = 'Up' }) }
            Mock Invoke-WebRequest {
                param($Uri)
                if ($Uri -match '/picture/(\d{4}-\d{2})/README\.md$') {
                    $script:webCalls += @{ YearMonth = $Matches[1] }
                    return [PSCustomObject]@{ Content = $mockReadme }
                }
                return [PSCustomObject]@{ Content = "" }
            }
            Mock Test-Path { return $true }
            Mock New-Item { }
            Mock Get-ChildItem { return @() }
            Mock Get-Item { return [PSCustomObject]@{ Length = 100 } }
            Mock Remove-Item { }
            Mock Write-Error { }
            Mock Write-Warning { }
            Mock Write-Information { }
        }

        It 'Fetches the correct monthly README for a single date' {
            & $sb -OutputPath 'TestDrive:\single' -Date '2026-05-15' -RetentionDays 0
            $script:webCalls.Count | Should Be 1
            $script:webCalls[0].YearMonth | Should Be '2026-05'
        }
    }

    Context 'README fetch failure handling' {
        BeforeEach {
            Mock Get-NetAdapter { return @([PSCustomObject]@{ Name = 'MockAdapter'; InterfaceDescription = 'Mock Ethernet'; Status = 'Up' }) }
            Mock Invoke-WebRequest {
                param($Uri)
                if ($Uri -match '/picture/(\d{4}-\d{2})/README\.md$') {
                    $script:webCalls += @{ YearMonth = $Matches[1] }
                    throw "404 Not Found"
                }
                return [PSCustomObject]@{ Content = "" }
            }
            Mock Test-Path { return $true }
            Mock New-Item { }
            Mock Get-ChildItem { return @() }
            Mock Get-Item { return [PSCustomObject]@{ Length = 100 } }
            Mock Remove-Item { }
            Mock Write-Warning { }
            Mock Write-Information { }
        }

        It 'Exits with error when no READMEs can be fetched' {
            # Use a fixed set of dates to avoid mock conflicts
            { & $sb -OutputPath 'TestDrive:\fail' -Date '2025-01-15' -RetentionDays 0 } |
                Should Throw
        }
    }
}
