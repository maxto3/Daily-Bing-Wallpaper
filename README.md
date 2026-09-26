# Daily Bing Wallpaper

Downloads [Bing daily wallpapers](https://cn.bing.com) in 4K resolution from the [niumoo/bing-wallpaper](https://github.com/niumoo/bing-wallpaper) repository and saves them locally.

Two implementations are available:
- **PowerShell** — for Windows
- **Python** — cross-platform (Windows / Linux / macOS)

## Features

- **4K HD** — Downloads wallpapers at 3840×2160 resolution
- **Batch download** — Fetches wallpapers for the past N days in one run (default: 7)
- **Single date** — Download wallpaper for any past date
- **Auto cleanup** — Automatically deletes expired files based on retention policy
- **Resume-friendly** — Existing files are skipped, no redundant downloads
- **Network check** — Verifies network connectivity before running; aborts with an error if offline
- **Dependency self-healing** — Detects SOCKS proxies and auto-installs PySocks when missing (opt out with `--no-auto-install`)

---

## Python (Windows / Linux / macOS)

### Requirements

- Python 3.8+
- `requests` library

```bash
pip install requests
```

If the environment routes traffic through a **SOCKS proxy** (`http_proxy` / `https_proxy` / `all_proxy` set to `socks5://…` or `socks5h://…`), `requests` additionally needs **PySocks**. The script detects this at start-up and installs it on the fly (user site first, then `--break-system-packages` for PEP 668 hosts such as Debian 12+). If the install is not possible it stops with an actionable error instead of silently downloading nothing. Use `--no-auto-install` to fail fast without trying.

### Usage

#### Basic

```bash
# Download wallpapers for the past 7 days to the current directory
python save_bing_wallpaper.py
```

#### Custom day range

```bash
# Download wallpapers for the past 30 days
python save_bing_wallpaper.py --num-days 30
```

#### Specific date

```bash
# Download the wallpaper for April 30, 2026
python save_bing_wallpaper.py --date "2026-04-30"
```

#### Custom output directory

```bash
# Download to a custom directory
python save_bing_wallpaper.py --output-path ~/Pictures/Wallpapers --date "2026-05-01"
```

#### Retention cleanup

```bash
# Download and also delete files older than 30 days
python save_bing_wallpaper.py --num-days 7 --retention-days 30

# Never auto-delete
python save_bing_wallpaper.py --retention-days 0
```

### Parameters

| Parameter | Type | Default | Range | Description |
|-----------|------|---------|-------|-------------|
| `--output-path` | string | Current directory | — | Directory where wallpapers are saved |
| `--date` | string | None | `yyyy-MM-dd`, not in the future | Specifies a single date to download |
| `--num-days` | int | 7 | 1 ~ 365 | Number of past days to download (ignored when `--date` is set) |
| `--retention-days` | int | 14 | 0 ~ 3650 | Days to retain `.jpg` files; older files are deleted. Set to 0 to disable |
| `--no-auto-install` | flag | off | — | Do not auto-install a missing optional dependency (PySocks); fail fast instead |
| `--verbose`, `-v` | flag | off | — | Enable debug-level logging |

### Testing

```bash
pip install pytest
python -m pytest tests/ -v
```

### Scheduling

**Linux / macOS** — Use **cron** to automate daily downloads:

```bash
# Run daily at 8:00 AM
0 8 * * * cd /path/to/Daily-Bing-Wallpaper && python save_bing_wallpaper.py --output-path ~/Pictures/Wallpapers >> /tmp/bing-wallpaper.log 2>&1
```

> **Note — cron and proxy variables**: cron never reads `~/.bashrc`, but on Debian/Ubuntu it does load `/etc/environment` through PAM (`pam_env.so` in `/etc/pam.d/cron`). A `http_proxy` / `https_proxy` defined there applies to scheduled jobs, while your interactive shell may see a completely different value — so the very same command can behave differently under cron. If the job needs a specific proxy, declare it at the top of the crontab (`http_proxy=http://127.0.0.1:1081`); clear an inherited one with `http_proxy=`.

**Windows** — Use **Task Scheduler** (with `pythonw.exe` for no console window):

1. Open **Task Scheduler**
2. Create a basic task with a daily trigger
3. Action: Start a program — `C:\path\to\pythonw.exe`
4. Arguments: `d:\path\to\save_bing_wallpaper.py --output-path "C:\Wallpapers"`
5. General tab: select "Run whether user is logged on or not"

---

## PowerShell (Windows)

### Requirements

- Windows 8 / Windows Server 2012 or later
- PowerShell 5.1+
- `NetAdapter` module (included with Windows)

### Usage

#### Basic

```powershell
# Download wallpapers for the past 7 days to the current directory
.\Save-BingWallpaper.ps1
```

#### Custom day range

```powershell
# Download wallpapers for the past 30 days
.\Save-BingWallpaper.ps1 -NumDays 30
```

#### Specific date

```powershell
# Download the wallpaper for April 30, 2026
.\Save-BingWallpaper.ps1 -Date "2026-04-30"
```

#### Custom output directory

```powershell
# Download to a custom directory
.\Save-BingWallpaper.ps1 -OutputPath "C:\Wallpapers" -Date "2026-05-01"
```

#### Retention cleanup

```powershell
# Download and also delete files older than 30 days
.\Save-BingWallpaper.ps1 -NumDays 7 -RetentionDays 30

# Never auto-delete
.\Save-BingWallpaper.ps1 -RetentionDays 0
```

### Parameters

| Parameter | Type | Default | Range | Description |
|-----------|------|---------|-------|-------------|
| `-OutputPath` | string | Current directory | — | Directory where wallpapers are saved |
| `-Date` | string | None | `yyyy-MM-dd`, not in the future | Specifies a single date to download |
| `-NumDays` | int | 7 | 1 ~ 365 | Number of past days to download (ignored when `-Date` is set) |
| `-RetentionDays` | int | 14 | 0 ~ 3650 | Days to retain `.jpg` files; older files are deleted. Set to 0 to disable |

### Testing

```powershell
Invoke-Pester -Path .\tests\Save-BingWallpaper.Tests.ps1
```

### Scheduling

Use Windows Task Scheduler:

1. Open **Task Scheduler**
2. Create a basic task with a daily trigger
3. Action: Start a program — `powershell.exe`
4. Arguments: `-ExecutionPolicy Bypass -File "C:\path\to\Save-BingWallpaper.ps1" -OutputPath "C:\Wallpapers"`

---

## How It Works

1. **Network check** — Verifies network connectivity; aborts if offline
2. **Date list** — Builds the list of dates to download based on `-Date`/`--date` or `-NumDays`/`--num-days`
3. **Fetch index** — Pulls the monthly README from GitHub and parses 4K image URLs
4. **Cleanup** — Deletes `.jpg` files older than the retention threshold
5. **Download** — Downloads each wallpaper one by one, skipping existing files
6. **Summary** — Prints download/skip/fail counts; exits with code 1 on any failure

## File Naming

Wallpapers are named by date in `yyyy-MM-dd.jpg` format, for example:

```
2026-05-31.jpg
2026-05-30.jpg
2026-05-29.jpg
```

## License

MIT License


