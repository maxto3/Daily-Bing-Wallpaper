# Daily Bing Wallpaper

A PowerShell script that downloads [Bing daily wallpapers](https://cn.bing.com) in 4K resolution from the [niumoo/bing-wallpaper](https://github.com/niumoo/bing-wallpaper) repository and saves them locally.

## Features

- **4K HD** — Downloads wallpapers at 3840×2160 resolution
- **Batch download** — Fetches wallpapers for the past N days in one run (default: 7)
- **Single date** — Download wallpaper for any past date
- **Auto cleanup** — Automatically deletes expired files based on retention policy
- **Resume-friendly** — Existing files are skipped, no redundant downloads
- **Network check** — Verifies WiFi or Ethernet connectivity before running; aborts with an error if offline

## Requirements

- Windows 8 / Windows Server 2012 or later
- PowerShell 5.1+
- `NetAdapter` module (included with Windows)

## Usage

### Basic

```powershell
# Download wallpapers for the past 7 days to the current directory
.\Save-BingWallpaper.ps1
```

### Custom day range

```powershell
# Download wallpapers for the past 30 days
.\Save-BingWallpaper.ps1 -NumDays 30
```

### Specific date

```powershell
# Download the wallpaper for April 30, 2026
.\Save-BingWallpaper.ps1 -Date "2026-04-30"
```

### Custom output directory

```powershell
# Download to a custom directory
.\Save-BingWallpaper.ps1 -OutputPath "C:\Wallpapers" -Date "2026-05-01"
```

### Retention cleanup

```powershell
# Download and also delete files older than 30 days
.\Save-BingWallpaper.ps1 -NumDays 7 -RetentionDays 30

# Never auto-delete
.\Save-BingWallpaper.ps1 -RetentionDays 0
```

## Parameters

| Parameter | Type | Default | Range | Description |
|-----------|------|---------|-------|-------------|
| `-OutputPath` | string | Current directory | — | Directory where wallpapers are saved |
| `-Date` | string | None | `yyyy-MM-dd`, not in the future | Specifies a single date to download |
| `-NumDays` | int | 7 | 1 ~ 365 | Number of past days to download (ignored when `-Date` is set) |
| `-RetentionDays` | int | 14 | 0 ~ 3650 | Days to retain `.jpg` files; older files are deleted. Set to 0 to disable |

## How It Works

1. **Network check** — Detects active physical network adapters (WiFi / Ethernet); aborts if none are up
2. **Date list** — Builds the list of dates to download based on `-Date` or `-NumDays`
3. **Fetch index** — Pulls the monthly README from GitHub and parses 4K image URLs
4. **Cleanup** — Deletes `.jpg` files older than `-RetentionDays` days
5. **Download** — Downloads each wallpaper one by one, skipping existing files
6. **Summary** — Prints download/skip/fail counts; exits with code 1 on any failure

## File Naming

Wallpapers are named by date in `yyyy-MM-dd.jpg` format, for example:

```
2026-05-31.jpg
2026-05-30.jpg
2026-05-29.jpg
```

## Testing

This project uses [Pester](https://github.com/pester/Pester) for testing:

```powershell
Invoke-Pester -Path .\tests\Save-BingWallpaper.Tests.ps1
```

## Scheduling

Use Windows Task Scheduler to automate daily downloads:

1. Open **Task Scheduler**
2. Create a basic task with a daily trigger
3. Action: Start a program — `powershell.exe`
4. Arguments: `-ExecutionPolicy Bypass -File "C:\path\to\Save-BingWallpaper.ps1" -OutputPath "C:\Wallpapers"`

## License

MIT License


