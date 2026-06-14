#!/usr/bin/env python3
"""
Downloads Bing daily wallpapers from GitHub-hosted wallpaper index.

Fetches Bing wallpapers in 4K resolution from the niumoo/bing-wallpaper
GitHub repository and saves them to a local directory.

Cross-platform: Windows, Linux, and macOS.
Without --date, downloads wallpapers for the past N days (default: 7).
With --date, downloads wallpaper for a specific date only.
"""

import argparse
import logging
import os
import re
import socket
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

README_URL_TEMPLATE = (
    "https://github.com/niumoo/bing-wallpaper/raw/refs/heads/main/"
    "zh-cn/picture/{year_month}/README.md"
)
README_FETCH_TIMEOUT = 30  # seconds
DOWNLOAD_TIMEOUT = 120  # seconds
CONNECTIVITY_CHECK_HOST = "github.com"
CONNECTIVITY_CHECK_PORT = 443
CONNECTIVITY_CHECK_TIMEOUT = 5  # seconds

# Regex to extract date + 4K URL from markdown table rows
# Pattern: YYYY-MM-DD [download 4k](URL)
URL_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})\s*\[download 4k\]\(([^)]+)\)")

# Regex to extract date from filename: yyyy-MM-dd.jpg
FILENAME_DATE_PATTERN = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.jpg$")

log = logging.getLogger("save_bing_wallpaper")

# ---------------------------------------------------------------------------
# Cross-platform network connectivity check
# ---------------------------------------------------------------------------


def _get_active_interfaces() -> list[str]:
    """Return names of active non-loopback network interfaces.

    On Linux: reads /sys/class/net/ to enumerate interfaces with operstate 'up'.
    On other platforms (Windows/macOS): returns an empty list — connectivity is
    verified solely via the TCP socket probe in check_network_connectivity().
    """
    if sys.platform != "linux":
        return []

    active = []
    net_dir = Path("/sys/class/net")
    if not net_dir.is_dir():
        return active

    for iface_dir in net_dir.iterdir():
        if not iface_dir.is_dir():
            continue
        iface_name = iface_dir.name
        if iface_name == "lo":
            continue

        operstate_file = iface_dir / "operstate"
        try:
            operstate = operstate_file.read_text().strip()
        except OSError:
            continue

        if operstate == "up":
            active.append(iface_name)

    return active


def check_network_connectivity() -> None:
    """Verify network connectivity; raise SystemExit if offline.

    Checks:
    1. (Linux only) At least one non-loopback interface is UP (via /sys/class/net/).
    2. A TCP socket can connect to github.com:443 (all platforms).
    """
    active_ifaces = _get_active_interfaces()

    if active_ifaces:
        log.info(
            "Network OK - active adapter(s): %s",
            "; ".join(active_ifaces),
        )
    elif sys.platform == "linux":
        raise RuntimeError(
            "No active network connection detected. "
            "Please connect to WiFi or Ethernet and try again."
        )

    # Also verify we can actually reach the internet
    try:
        sock = socket.create_connection(
            (CONNECTIVITY_CHECK_HOST, CONNECTIVITY_CHECK_PORT),
            timeout=CONNECTIVITY_CHECK_TIMEOUT,
        )
        sock.close()
    except OSError as exc:
        raise RuntimeError(
            f"Cannot reach {CONNECTIVITY_CHECK_HOST}:{CONNECTIVITY_CHECK_PORT} - {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# README fetcher & parser
# ---------------------------------------------------------------------------


def fetch_wallpaper_data(dates: list[str]) -> dict[str, str]:
    """Fetch wallpaper 4K URLs from GitHub monthly README pages.

    Args:
        dates: List of date strings in yyyy-MM-dd format.

    Returns:
        Dict mapping date string -> 4K download URL.
    """
    # Determine which year-months to fetch
    year_months: set[str] = set()
    for date_str in dates:
        m = re.match(r"^(\d{4})-(\d{2})-\d{2}$", date_str)
        if m:
            year_months.add(f"{m.group(1)}-{m.group(2)}")

    date_url_map: dict[str, str] = {}

    for year_month in sorted(year_months):
        readme_url = README_URL_TEMPLATE.format(year_month=year_month)
        log.info("Fetching wallpaper index for %s...", year_month)

        try:
            resp = requests.get(readme_url, timeout=README_FETCH_TIMEOUT)
            resp.raise_for_status()
            readme_text = resp.text
        except requests.RequestException as exc:
            log.warning("Failed to fetch README for %s: %s", year_month, exc)
            continue

        # Parse date + 4K URL pairs from markdown table
        matches = URL_PATTERN.findall(readme_text)
        for parsed_date, url in matches:
            # Keep only the first occurrence in case of duplicates
            if parsed_date not in date_url_map:
                date_url_map[parsed_date] = url

        log.info("  Found %d wallpaper entries for %s.", len(matches), year_month)

    return date_url_map


# ---------------------------------------------------------------------------
# Retention cleanup
# ---------------------------------------------------------------------------


def cleanup_expired(
    output_dir: Path, retention_days: int, *, dry_run: bool = False
) -> int:
    """Delete .jpg files in output_dir whose embedded date is older than retention_days.

    Args:
        output_dir: Directory containing wallpaper .jpg files.
        retention_days: Delete files older than this many days.  0 disables.
        dry_run: If True, only log what would be deleted without actually removing.

    Returns:
        Number of files deleted.
    """
    if retention_days <= 0:
        return 0

    cutoff = date.today() - timedelta(days=retention_days)
    log.info(
        "Removing wallpapers older than %d day(s) (before %s)...",
        retention_days,
        cutoff.isoformat(),
    )

    deleted = 0
    for filepath in output_dir.glob("*.jpg"):
        match = FILENAME_DATE_PATTERN.match(filepath.name)
        if not match:
            continue
        try:
            file_date = date(
                int(match.group(1)), int(match.group(2)), int(match.group(3))
            )
        except ValueError:
            continue

        if file_date < cutoff:
            if dry_run:
                log.info("  Would delete: %s", filepath.name)
            else:
                try:
                    filepath.unlink()
                    log.info("  Deleted: %s", filepath.name)
                except OSError as exc:
                    log.error("Failed to delete %s: %s", filepath.name, exc)
                    continue
            deleted += 1

    log.info("Expired files cleaned: %d deleted.", deleted)
    return deleted


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def download_wallpapers(
    download_tasks: list[dict],
    output_dir: Path,
) -> tuple[int, int, int]:
    """Download wallpaper files.

    Each task is a dict with keys: date_str, download_url.
    The output filename is derived as {date_str}.jpg.

    Returns:
        Tuple of (downloaded_count, skipped_count, failed_count).
    """
    downloaded = 0
    skipped = 0
    failed = 0

    for task in download_tasks:
        date_str = task["date_str"]
        download_url = task["download_url"]
        output_file = output_dir / f"{date_str}.jpg"

        # Skip if file already exists
        if output_file.exists():
            log.info("Skipping %s: file already exists.", date_str)
            skipped += 1
            continue

        log.info("Downloading %s: %s", date_str, download_url)
        log.info("Saving to: %s", output_file)

        # Download to a temporary file, then rename atomically
        try:
            _download_to_file(download_url, output_file)
        except Exception as exc:
            log.error("Download failed for %s: %s", date_str, exc)
            # Clean up temp file if it exists
            if output_file.exists():
                try:
                    output_file.unlink()
                except OSError:
                    pass
            failed += 1
            continue

        # Verify and report
        if output_file.exists():
            size_kb = output_file.stat().st_size / 1024
            log.info(
                "Download complete: %s (Size: %.1f KB)", output_file, size_kb
            )
            downloaded += 1
        else:
            log.error(
                "Download appeared to succeed for %s but output file not found.",
                date_str,
            )
            failed += 1

    return downloaded, skipped, failed


def _download_to_file(url: str, dest: Path) -> None:
    """Download URL content to dest via a temp file (atomic rename)."""
    # Write to a temp file in the same directory so rename is atomic
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=dest.parent, prefix=f".{dest.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "wb") as tmp_file:
            with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT) as resp:
                resp.raise_for_status()
                for chunk in resp.iter_content(chunk_size=8192):
                    tmp_file.write(chunk)
        # Atomic rename to final destination
        os.rename(tmp_path, dest)
    except Exception:
        # Clean up temp file on any error
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Date list builder
# ---------------------------------------------------------------------------


def build_date_list(single_date: str | None, num_days: int) -> list[str]:
    """Build the list of date strings to download.

    Args:
        single_date: Specific date in yyyy-MM-dd format, or None.
        num_days: Number of past days to include when single_date is None.

    Returns:
        List of date strings in yyyy-MM-dd format.
    """
    today = date.today()
    if single_date:
        return [single_date]

    dates = []
    for i in range(num_days):
        d = today - timedelta(days=i)
        dates.append(d.strftime("%Y-%m-%d"))
    return dates


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def validate_date(value: str) -> str:
    """Validate date is in yyyy-MM-dd format and not in the future."""
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        raise argparse.ArgumentTypeError("Date must be in yyyy-MM-dd format.")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid date: {value}. Use yyyy-MM-dd format."
        )
    if parsed > date.today():
        raise argparse.ArgumentTypeError("Date cannot be in the future.")
    return value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Download Bing daily wallpapers in 4K resolution.",
    )
    parser.add_argument(
        "--output-path",
        default=str(Path.cwd()),
        help="Destination directory for downloaded wallpapers (default: current directory).",
    )
    parser.add_argument(
        "--date",
        type=validate_date,
        default=None,
        help="Target date in yyyy-MM-dd format. If provided, downloads that date only.",
    )
    parser.add_argument(
        "--num-days",
        type=int,
        default=7,
        help="Number of past days to download when --date is not specified (default: 7, range: 1-365).",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=14,
        help="Days to retain downloaded files; older files are deleted (default: 14, 0=never).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose (DEBUG) logging.",
    )

    args = parser.parse_args(argv)

    # Validate ranges
    if not 1 <= args.num_days <= 365:
        parser.error("--num-days must be between 1 and 365.")
    if not 0 <= args.retention_days <= 3650:
        parser.error("--retention-days must be between 0 and 3650.")

    return args


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Run the wallpaper download workflow.  Returns exit code (0 or 1)."""
    args = parse_args(argv)

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    output_dir = Path(args.output_path)

    # 1. Network check
    try:
        check_network_connectivity()
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1

    # 2. Build date list
    date_strings = build_date_list(args.date, args.num_days)

    # 3. Fetch wallpaper index from GitHub
    log.info("Fetching wallpaper index for %d date(s)...", len(date_strings))
    date_url_map = fetch_wallpaper_data(date_strings)

    if not date_url_map:
        log.error("No wallpaper data found for the requested date(s).")
        return 1

    # 4. Build download tasks
    download_tasks: list[dict] = []
    for date_str in date_strings:
        if date_str in date_url_map:
            download_tasks.append(
                {"date_str": date_str, "download_url": date_url_map[date_str]}
            )
        else:
            log.warning(
                "No wallpaper data found for %s. Skipping.", date_str
            )

    if not download_tasks:
        log.error("No valid download tasks to process.")
        return 1

    # 5. Ensure output directory exists
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.error("Failed to create output directory '%s': %s", output_dir, exc)
        return 1

    # 6. Retention cleanup
    cleanup_expired(output_dir, args.retention_days)

    # 7. Download wallpapers
    downloaded, skipped, failed = download_wallpapers(download_tasks, output_dir)

    # 8. Summary
    log.info(
        "Finished: %d downloaded, %d skipped, %d failed, %d total.",
        downloaded,
        skipped,
        failed,
        len(download_tasks),
    )

    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
