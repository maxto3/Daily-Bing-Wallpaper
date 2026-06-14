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

1. Network check → 2. Build date list → 3. Fetch GitHub monthly README → 4. Parse 4K URLs via regex → 5. Cleanup expired → 6. Download (skip existing) → 7. Exit 0/1

**Key files:**
- `save_bing_wallpaper.py` (482 lines) — Python impl, cross-platform
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
