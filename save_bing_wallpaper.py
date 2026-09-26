#!/usr/bin/env python3
"""
Downloads Bing daily wallpapers from GitHub-hosted wallpaper index.

Fetches Bing wallpapers in 4K resolution from the niumoo/bing-wallpaper
GitHub repository and saves them to a local directory.

Cross-platform: Windows, Linux, and macOS.
Without --date, downloads wallpapers for the past N days (default: 7).
With --date, downloads wallpaper for a specific date only.
Installs PySocks automatically when a SOCKS proxy is detected in the
environment (disable with --no-auto-install).
"""

import argparse
import logging
import os
import re
import socket
import subprocess
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

# Optional dependency bootstrap (requests needs PySocks for SOCKS proxies)
PYSOCKS_PACKAGE = "PySocks"
SOCKS_SCHEMES = frozenset({"socks4", "socks4a", "socks5", "socks5h"})
PIP_INSTALL_TIMEOUT = 180  # seconds
# Proxy env vars are only acted upon when requests would really use them
PROXY_PROBE_URLS = (
    "https://github.com/",
    "https://cn.bing.com/",
)
# pip strategies tried in order until `import socks` succeeds. The
# --break-system-packages variants cover PEP 668 environments (Debian 12+,
# Ubuntu 23.04+) where a plain `pip install` is refused.
PIP_INSTALL_STRATEGIES = (
    ("--user", PYSOCKS_PACKAGE),
    ("--user", "--break-system-packages", PYSOCKS_PACKAGE),
    ("--break-system-packages", PYSOCKS_PACKAGE),
)

# Regex to extract date + 4K URL from markdown table rows
# Pattern: YYYY-MM-DD [download 4k](URL)
URL_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})\s*\[download 4k\]\(([^)]+)\)")

# Regex to extract date from filename: yyyy-MM-dd.jpg
FILENAME_DATE_PATTERN = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.jpg$")

log = logging.getLogger("save_bing_wallpaper")

# ---------------------------------------------------------------------------
# Optional dependency bootstrap (PySocks / SOCKS proxies)
# ---------------------------------------------------------------------------


def _proxy_scheme(value: str) -> str:
    """Return the lower-cased scheme of a proxy value.

    requests prepends 'http://' to schemeless values ('localhost:1080'), so
    they are reported as HTTP proxies.
    """
    value = value.strip()
    if "://" not in value:
        return "http"
    return value.split("://", 1)[0].strip().lower()


def _proxy_env_entries() -> dict[str, str]:
    """Map environment variable name -> value for proxy variables.

    Excludes no_proxy (which lists hosts that must bypass the proxy).
    """
    entries: dict[str, str] = {}
    for name, value in os.environ.items():
        lowered = name.lower()
        if not lowered.endswith("_proxy") or lowered.startswith("no_"):
            continue
        value = value.strip()
        if value:
            entries[name] = value
    return entries


def detect_socks_proxies(
    urls: tuple[str, ...] = PROXY_PROBE_URLS,
) -> dict[str, str]:
    """Return the SOCKS proxy env vars that requests would actually use.

    Plain HTTP(S) proxies need no extra dependency and are ignored, as are
    variables that no_proxy exempts for every probe URL.

    Returns:
        Dict mapping environment variable name -> proxy value (may be empty).
    """
    entries = {
        name: value
        for name, value in _proxy_env_entries().items()
        if _proxy_scheme(value) in SOCKS_SCHEMES
    }
    if not entries:
        return {}

    from requests.utils import should_bypass_proxies

    for url in urls:
        try:
            if not should_bypass_proxies(url, no_proxy=None):
                return entries  # at least one probe URL goes through the proxy
        except Exception:  # pragma: no cover - defensive
            return entries
    return {}


def _can_import(module_name: str) -> bool:
    """Return True if module_name can be imported in this process.

    A freshly installed '--user' module may live in a site directory that was
    absent from sys.path when the interpreter started, so that location is
    added before giving up.
    """
    import importlib
    import site

    for attempt in (0, 1):
        try:
            importlib.import_module(module_name)
            return True
        except ImportError:
            if attempt:
                return False
            try:
                user_site = site.getusersitepackages()
            except Exception:
                return False
            if user_site and user_site not in sys.path and Path(user_site).is_dir():
                sys.path.append(user_site)
            importlib.invalidate_caches()
        except Exception:
            return False
    return False


def _pip_env() -> dict[str, str]:
    """Environment for the pip subprocess.

    SOCKS proxy variables are removed: pip vendors its own urllib3 and would
    fail with the very same 'Missing dependencies for SOCKS support.' error
    that this bootstrap is trying to fix.
    """
    env = os.environ.copy()
    for name in list(env):
        lowered = name.lower()
        if (
            lowered.endswith("_proxy")
            and not lowered.startswith("no_")
            and _proxy_scheme(env[name]) in SOCKS_SCHEMES
        ):
            del env[name]
    return env


def _run_pip(cmd: list[str], env: dict[str, str]) -> bool:
    """Run a pip command; return True when it exits with code 0."""
    log.debug("Running: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=PIP_INSTALL_TIMEOUT,
            check=False,
        )
    except FileNotFoundError:
        log.warning("pip is unavailable for %s - cannot auto-install.", sys.executable)
        return False
    except subprocess.TimeoutExpired:
        log.warning("pip timed out after %d seconds.", PIP_INSTALL_TIMEOUT)
        return False
    except OSError as exc:
        log.warning("Could not run pip: %s", exc)
        return False

    if proc.returncode != 0:
        detail = " | ".join((proc.stderr or proc.stdout or "").strip().splitlines()[-3:])
        log.warning("pip failed with exit code %d: %s", proc.returncode, detail)
        return False
    return True


def _in_virtualenv() -> bool:
    """True when running inside a virtual environment (venv/virtualenv)."""
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def _pip_strategies() -> tuple[tuple[str, ...], ...]:
    """pip install strategies that make sense for this interpreter.

    '--user' is rejected inside a virtual environment ("User site-packages are
    not visible in this virtualenv"), so those strategies are dropped there.
    """
    if _in_virtualenv():
        return tuple(s for s in PIP_INSTALL_STRATEGIES if "--user" not in s)
    return PIP_INSTALL_STRATEGIES


def _pip_install_hint() -> str:
    """Actionable pip command for the interpreter that is currently running."""
    if _in_virtualenv():
        return f"{sys.executable} -m pip install {PYSOCKS_PACKAGE}"
    return f"{sys.executable} -m pip install --user {PYSOCKS_PACKAGE}"


def install_pysocks() -> bool:
    """Try to install PySocks; return True once `socks` becomes importable."""
    env = _pip_env()
    strategies = _pip_strategies()
    for index, strategy in enumerate(strategies, start=1):
        log.info(
            "Auto-installing '%s' (attempt %d/%d: %s)...",
            PYSOCKS_PACKAGE,
            index,
            len(strategies),
            " ".join(flag for flag in strategy if flag != PYSOCKS_PACKAGE),
        )
        cmd = [sys.executable, "-m", "pip", "install", *strategy]
        if _run_pip(cmd, env) and _can_import("socks"):
            return True
    return False


def ensure_socks_support(auto_install: bool = True) -> None:
    """Fail fast when a SOCKS proxy is configured but PySocks is missing.

    requests can only use SOCKS proxies when PySocks (`socks`) is installed.
    Without it every request raises 'Missing dependencies for SOCKS support.',
    which upstream code turns into an empty result set. When that combination
    is detected and auto_install is True, PySocks is installed on the fly.

    Raises:
        RuntimeError: A SOCKS proxy is required but PySocks is unavailable.
    """
    socks_entries = detect_socks_proxies()
    if not socks_entries:
        return

    described = ", ".join(
        f"{name}={value}" for name, value in sorted(socks_entries.items())
    )

    if _can_import("socks"):
        log.info("SOCKS proxy in use (%s); PySocks is installed.", described)
        return

    log.warning(
        "SOCKS proxy in use (%s) but PySocks is missing - requests cannot use it.",
        described,
    )
    if auto_install and install_pysocks():
        log.info("PySocks installed - SOCKS proxy support enabled.")
        return

    raise RuntimeError(
        f"SOCKS proxy is configured ({described}) but the Python module 'socks' "
        f"({PYSOCKS_PACKAGE}) is missing. Fix with one of: "
        f"'sudo apt install python3-socks' (Debian/Ubuntu), "
        f"'{_pip_install_hint()}', "
        f"or unset the SOCKS proxy variables (http_proxy/https_proxy/all_proxy) "
        f"for this run."
    )


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
# URL safety validator
# ---------------------------------------------------------------------------


def is_safe_url(url: str) -> bool:
    """Verify URL points to a trusted Bing domain (bing.com or bing.net).

    Prevents SSRF and malicious download from hijacked upstream README files.
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        domain = parsed.netloc.lower()
        return (
            domain == "bing.com"
            or domain.endswith(".bing.com")
            or domain.endswith(".bing.net")
        )
    except Exception:
        return False


# ---------------------------------------------------------------------------
# HTTP session factory (connection pooling + retry)
# ---------------------------------------------------------------------------


def _create_session() -> requests.Session:
    """Create a requests.Session with connection pooling and auto-retry.

    Retries up to 3 times with exponential backoff (1s, 2s, 4s) on
    transient server errors (500, 502, 503, 504).
    """
    from urllib3.util import Retry
    from requests.adapters import HTTPAdapter

    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


# ---------------------------------------------------------------------------
# README fetcher & parser
# ---------------------------------------------------------------------------


def fetch_wallpaper_data(
    dates: list[str],
    session: requests.Session | None = None,
) -> dict[str, str]:
    """Fetch wallpaper 4K URLs from GitHub monthly README pages.

    Args:
        dates: List of date strings in yyyy-MM-dd format.
        session: Optional requests.Session for connection reuse.
            Creates a new session with retry if not provided.

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
    close_session = session is None
    if session is None:
        session = _create_session()

    for year_month in sorted(year_months):
        readme_url = README_URL_TEMPLATE.format(year_month=year_month)
        log.info("Fetching wallpaper index for %s...", year_month)

        try:
            resp = session.get(readme_url, timeout=README_FETCH_TIMEOUT)
            resp.raise_for_status()
            readme_text = resp.text
        except requests.RequestException as exc:
            log.warning("Failed to fetch README for %s: %s", year_month, exc)
            continue

        # Parse date + 4K URL pairs from markdown table
        matches = URL_PATTERN.findall(readme_text)
        for parsed_date, url in matches:
            # Security: only accept URLs from trusted Bing domains
            if not is_safe_url(url):
                log.warning("Skipping unsafe URL for %s: %s", parsed_date, url)
                continue
            # Keep only the first occurrence in case of duplicates
            if parsed_date not in date_url_map:
                date_url_map[parsed_date] = url

        log.info("  Found %d wallpaper entries for %s.", len(matches), year_month)

    if close_session:
        session.close()
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
    download_tasks: list[dict[str, str]],
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

    with _create_session() as session:
        for task in download_tasks:
            date_str = task["date_str"]
            download_url = task["download_url"]
            output_file = output_dir / f"{date_str}.jpg"

            # Skip if file already exists
            if output_file.exists():
                log.info("Skipping %s: file already exists.", date_str)
                skipped += 1
                continue

            # Defense-in-depth: verify URL is from a trusted Bing domain
            if not is_safe_url(download_url):
                log.error("Blocked unsafe download URL for %s: %s", date_str, download_url)
                failed += 1
                continue

            log.info("Downloading %s: %s", date_str, download_url)
            log.info("Saving to: %s", output_file)

            # Download to a temporary file, then replace atomically
            try:
                _download_to_file(download_url, output_file, session=session)
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


def _download_to_file(
    url: str,
    dest: Path,
    session: requests.Session | None = None,
) -> None:
    """Download URL content to dest via a temp file (atomic replace)."""
    if session is None:
        session = _create_session()
    # Write to a temp file in the same directory so replacement is atomic
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=dest.parent, prefix=f".{dest.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "wb") as tmp_file:
            with session.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT) as resp:
                resp.raise_for_status()
                for chunk in resp.iter_content(chunk_size=8192):
                    tmp_file.write(chunk)
        # Atomic replace to final destination (cross-platform compatible)
        os.replace(tmp_path, dest)
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
        "--no-auto-install",
        dest="auto_install",
        action="store_false",
        help="Do not auto-install a missing optional dependency (PySocks); fail fast instead.",
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

    # 1. Optional dependencies (a SOCKS proxy needs PySocks)
    try:
        ensure_socks_support(auto_install=args.auto_install)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1

    # 2. Network check
    try:
        check_network_connectivity()
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1

    # 3. Build date list
    date_strings = build_date_list(args.date, args.num_days)

    # 4. Fetch wallpaper index from GitHub
    log.info("Fetching wallpaper index for %d date(s)...", len(date_strings))
    date_url_map = fetch_wallpaper_data(date_strings)

    if not date_url_map:
        log.error("No wallpaper data found for the requested date(s).")
        return 1

    # 5. Build download tasks
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

    # 6. Ensure output directory exists
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.error("Failed to create output directory '%s': %s", output_dir, exc)
        return 1

    # 7. Retention cleanup
    cleanup_expired(output_dir, args.retention_days)

    # 8. Download wallpapers
    downloaded, skipped, failed = download_wallpapers(download_tasks, output_dir)

    # 9. Summary
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
