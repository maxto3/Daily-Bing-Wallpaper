# Daily Bing Wallpaper — Agent Instructions

Dual-implementation wallpaper downloader: Python (cross-platform: Windows/Linux/macOS) & PowerShell (Windows).
Full usage docs: [README.md](README.md)

## Build & Test Commands

```bash
# Python
pip install requests pytest
python save_bing_wallpaper.py              # run
python -m pytest tests/ -v                 # test

# PowerShell
.\Save-BingWallpaper.ps1                   # run
Invoke-Pester -Path .\tests\Save-BingWallpaper.Tests.ps1  # test
```

## Architecture

Two independent implementations sharing identical workflow but using platform-native I/O:

1. Ensure optional deps → 2. Network check → 3. Build date list → 4. Fetch GitHub monthly README → 5. Parse 4K URLs via regex → 6. Cleanup expired → 7. Download (skip existing) → 8. Exit 0/1

**Key files:**
- `save_bing_wallpaper.py` (818 lines) — Python impl, cross-platform
- `Save-BingWallpaper.ps1` (275 lines) — PowerShell impl
- `tests/test_save_bing_wallpaper.py` — pytest unit tests (mocks requests)
- `tests/Save-BingWallpaper.Tests.ps1` — Pester tests (mocks cmdlets)

## Conventions

| Convention | Python | PowerShell |
|-----------|--------|-------------|
| CLI params | `--kebab-case` | `-PascalCase` |
| Logging | `logging.getLogger()` | `Write-Information` |
| Error exit | `sys.exit(1)` on any failure | `exit 1` on any failure |
| Date format | `yyyy-MM-dd` | `yyyy-MM-dd` |
| File naming | `yyyy-MM-dd.jpg` | `yyyy-MM-dd.jpg` |
| Atomic writes | `tempfile.mkstemp()` + rename | Direct write (no temp) |

## Critical Pitfalls

- **Network check is platform-aware**: Python version uses `/sys/class/net` on Linux, falls back to TCP socket probe on Windows/macOS; PS version uses `Get-NetAdapter` (Windows-only). Do NOT port one to the other platform.
- **Regex pattern is shared**: `(\d{4}-\d{2}-\d{2})\s*\[download 4k\]\(([^)]+)\)` — keep identical across both implementations.
- **No config files**: All settings are CLI args/params only. No setup.py, requirements.txt, or pyproject.toml.
- **GitHub raw content URLs**: Uses `niumoo/bing-wallpaper` repo; rate limiting is a concern with batch downloads.
- **Pester test limitation**: Retention cleanup tests are disabled in legacy Pester 3 due to mock restrictions (noted in test file header).
- **cron does not read `~/.bashrc`**: on Debian/Ubuntu cron loads `/etc/environment` through PAM (`pam_env.so` in `/etc/pam.d/cron`), so a SOCKS `http_proxy` defined there reaches scheduled jobs while the interactive shell sees the `.bashrc` value. When debugging "works manually, fails under cron", diff the proxy variables first.
- **Python-only dependency bootstrap**: `ensure_socks_support()` detects SOCKS proxy env vars and auto-installs PySocks (`--no-auto-install` opts out, then it exits 1 with guidance). Do NOT port this to PowerShell — `Invoke-WebRequest` ignores proxy env vars. `_pip_env()` strips SOCKS vars before calling pip, because pip vendors urllib3 and would hit the same missing-dependency error.
- **Proxy-env test isolation**: `tests/test_save_bing_wallpaper.py` has an autouse fixture that strips `*_proxy` so a host with SOCKS proxies cannot trigger installs during a test run.
