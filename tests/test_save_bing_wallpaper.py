"""pytest tests for save_bing_wallpaper.py.

Run: python -m pytest tests/ -v
"""

import re
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import save_bing_wallpaper as sbw


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def build_mock_readme(year: int, month: int, day_count: int) -> str:
    """Generate a mock GitHub README with wallpaper entries.

    Matches the format produced by the PowerShell New-MockReadme function:
    a markdown table with 3 columns per row, each cell containing a thumbnail,
    a date, and a [download 4k](url) link.
    """
    lines = [
        f"## Bing Wallpaper ({year}-{month:02d})",
        "",
    ]

    cells = []
    for d in range(1, day_count + 1):
        date_str = f"{year}-{month:02d}-{d:02d}"
        url = (
            f"https://cn.bing.com/th?id=OHR.Test_{date_str}_UHD.jpg"
            f"&rf=LaDigue_UHD.jpg&pid=hp&w=3840&h=2160&rs=1&c=4"
        )
        cells.append(
            f"![](https://example.com/thumb.jpg){date_str} [download 4k]({url})"
        )

    # Pad to fill rows of 3
    while len(cells) % 3 != 0:
        cells.append("||")

    lines.append("|      |      |      |")
    lines.append("| :----: | :----: | :----: |")
    for i in range(0, len(cells), 3):
        c1 = cells[i]
        c2 = cells[i + 1] if i + 1 < len(cells) else ""
        c3 = cells[i + 2] if i + 2 < len(cells) else ""
        lines.append(f"|{c1}|{c2}|{c3}|")

    return "\n".join(lines)


def mock_requests_get_for_readme(
    mock_readmes: dict[str, str],
    captured_calls: list,
):
    """Return a side_effect function for requests.get that serves mock READMEs.

    Args:
        mock_readmes: dict mapping year_month -> mock README text.
        captured_calls: list to append call info to.
    """

    def _side_effect(url, timeout=None, **kwargs):
        match = re.search(r"/picture/(\d{4}-\d{2})/README\.md$", url)
        if match:
            year_month = match.group(1)
            captured_calls.append({"year_month": year_month})
            text = mock_readmes.get(year_month, "")
            mock_resp = MagicMock()
            mock_resp.text = text
            mock_resp.raise_for_status = MagicMock()
            mock_resp.status_code = 200
            return mock_resp
        # For actual image downloads, return empty content
        mock_resp = MagicMock()
        mock_resp.iter_content = MagicMock(return_value=iter([b""]))
        mock_resp.raise_for_status = MagicMock()
        mock_resp.status_code = 200
        return mock_resp

    return _side_effect


# ---------------------------------------------------------------------------
# Network check tests
# ---------------------------------------------------------------------------


class TestNetworkCheck:
    def test_active_interfaces_found(self):
        """On Linux, when /sys/class/net has an up interface, it should be detected."""
        # Create a mock Path that simulates /sys/class/net with eth0 up
        mock_eth0 = MagicMock()
        mock_eth0.is_dir.return_value = True
        mock_eth0.name = "eth0"
        mock_eth0.__truediv__.return_value = MagicMock(
            **{"read_text.return_value": "up\n"}
        )

        mock_net_dir = MagicMock()
        mock_net_dir.is_dir.return_value = True
        mock_net_dir.iterdir.return_value = [mock_eth0]

        with patch("sys.platform", "linux"):
            with patch.object(sbw, "Path", return_value=mock_net_dir):
                active = sbw._get_active_interfaces()

        assert "eth0" in active

    def test_no_active_interfaces_raises(self):
        """On Linux, when no interfaces are up, check_network_connectivity should raise."""
        with patch.object(sbw, "_get_active_interfaces", return_value=[]):
            with patch("sys.platform", "linux"):
                with pytest.raises(RuntimeError, match="No active network connection"):
                    sbw.check_network_connectivity()

    def test_non_linux_skips_interface_check(self):
        """On non-Linux, empty active interfaces should not raise — socket probe is the fallback."""
        mock_sock = MagicMock()
        with patch.object(sbw, "_get_active_interfaces", return_value=[]):
            with patch("sys.platform", "win32"):
                with patch("socket.create_connection", return_value=mock_sock):
                    # Should not raise
                    sbw.check_network_connectivity()

    def test_interfaces_up_but_socket_fails(self):
        """When interfaces are up but socket connect fails, should raise."""
        with patch.object(sbw, "_get_active_interfaces", return_value=["eth0"]):
            with patch(
                "socket.create_connection",
                side_effect=OSError("Connection refused"),
            ):
                with pytest.raises(RuntimeError, match="Cannot reach"):
                    sbw.check_network_connectivity()

    def test_connectivity_ok(self):
        """When interfaces are up and socket connects, no error."""
        with patch.object(sbw, "_get_active_interfaces", return_value=["eth0"]):
            mock_sock = MagicMock()
            with patch("socket.create_connection", return_value=mock_sock):
                # Should not raise
                sbw.check_network_connectivity()


# ---------------------------------------------------------------------------
# README parsing tests
# ---------------------------------------------------------------------------


class TestFetchWallpaperData:
    def test_single_month_fetch(self):
        """NumDays=7 fetches the current month README."""
        today = date.today()
        this_month = today.strftime("%Y-%m")
        this_year = today.year
        this_month_num = today.month

        mock_readme = build_mock_readme(this_year, this_month_num, 31)
        mock_readmes = {this_month: mock_readme}
        captured = []

        dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]

        with patch("requests.Session.get", side_effect=mock_requests_get_for_readme(mock_readmes, captured)):
            url_map = sbw.fetch_wallpaper_data(dates)

        assert len(captured) > 0
        assert any(c["year_month"] == this_month for c in captured)
        # All 7 dates should be found
        for d in dates:
            assert d in url_map, f"Date {d} should be in the URL map"

    def test_cross_month_fetch(self):
        """NumDays large enough to span two months fetches both READMEs."""
        today = date.today()
        this_month = today.strftime("%Y-%m")
        prev_date = today - timedelta(days=31)
        prev_month = prev_date.strftime("%Y-%m")

        this_year = today.year
        this_month_num = today.month
        prev_year = prev_date.year
        prev_month_num = prev_date.month

        mock_this = build_mock_readme(this_year, this_month_num, 31)
        # For previous month, use actual day count
        import calendar
        prev_day_count = calendar.monthrange(prev_year, prev_month_num)[1]
        mock_prev = build_mock_readme(prev_year, prev_month_num, prev_day_count)

        mock_readmes = {
            this_month: mock_this,
            prev_month: mock_prev,
        }
        captured = []

        # Request enough days to go into previous month
        num_days_to_cross = today.day + 3
        dates = [
            (today - timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(num_days_to_cross)
        ]

        with patch("requests.Session.get", side_effect=mock_requests_get_for_readme(mock_readmes, captured)):
            url_map = sbw.fetch_wallpaper_data(dates)

        assert len(captured) > 1
        captured_months = {c["year_month"] for c in captured}
        assert this_month in captured_months
        assert prev_month in captured_months

    def test_single_date_mode(self):
        """--date fetches only the relevant monthly README."""
        mock_readme = build_mock_readme(2026, 5, 31)
        mock_readmes = {"2026-05": mock_readme}
        captured = []

        with patch("requests.Session.get", side_effect=mock_requests_get_for_readme(mock_readmes, captured)):
            url_map = sbw.fetch_wallpaper_data(["2026-05-15"])

        assert len(captured) == 1
        assert captured[0]["year_month"] == "2026-05"
        assert "2026-05-15" in url_map

    def test_readme_fetch_failure(self):
        """When README fetch fails, no URLs are returned."""
        import requests as req_lib

        def _failing_get(url, timeout=None, **kwargs):
            if "/picture/" in url and "/README.md" in url:
                raise req_lib.RequestException("404 Not Found")
            mock_resp = MagicMock()
            mock_resp.iter_content = MagicMock(return_value=iter([b""]))
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        with patch("requests.Session.get", side_effect=_failing_get):
            url_map = sbw.fetch_wallpaper_data(["2025-01-15"])

        assert url_map == {}


# ---------------------------------------------------------------------------
# Date list builder tests
# ---------------------------------------------------------------------------


class TestBuildDateList:
    def test_single_date(self):
        dates = sbw.build_date_list("2026-05-15", 7)
        assert dates == ["2026-05-15"]

    def test_num_days(self):
        today = date.today()
        dates = sbw.build_date_list(None, 3)
        assert len(dates) == 3
        assert dates[0] == today.strftime("%Y-%m-%d")
        assert dates[1] == (today - timedelta(days=1)).strftime("%Y-%m-%d")
        assert dates[2] == (today - timedelta(days=2)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Date validation tests
# ---------------------------------------------------------------------------


class TestDateValidation:
    def test_valid_date(self):
        today = date.today()
        assert sbw.validate_date(today.strftime("%Y-%m-%d")) == today.strftime("%Y-%m-%d")

    def test_future_date(self):
        future = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
        import argparse
        with pytest.raises(argparse.ArgumentTypeError, match="future"):
            sbw.validate_date(future)

    def test_invalid_format(self):
        import argparse
        with pytest.raises(argparse.ArgumentTypeError, match="yyyy-MM-dd"):
            sbw.validate_date("2026/05/15")


# ---------------------------------------------------------------------------
# Cleanup tests
# ---------------------------------------------------------------------------


class TestCleanupExpired:
    def test_deletes_old_files(self, tmp_path):
        """Files with date older than retention should be deleted."""
        # Create a file dated 30 days ago
        old_date = date.today() - timedelta(days=30)
        old_file = tmp_path / f"{old_date.strftime('%Y-%m-%d')}.jpg"
        old_file.write_text("fake image data")

        # Create a file dated yesterday (should be kept)
        recent_date = date.today() - timedelta(days=1)
        recent_file = tmp_path / f"{recent_date.strftime('%Y-%m-%d')}.jpg"
        recent_file.write_text("fake image data")

        deleted = sbw.cleanup_expired(tmp_path, retention_days=7)

        assert deleted == 1
        assert not old_file.exists()
        assert recent_file.exists()

    def test_retention_zero_skips(self, tmp_path):
        """retention_days=0 should skip cleanup."""
        old_date = date.today() - timedelta(days=30)
        old_file = tmp_path / f"{old_date.strftime('%Y-%m-%d')}.jpg"
        old_file.write_text("fake image data")

        deleted = sbw.cleanup_expired(tmp_path, retention_days=0)

        assert deleted == 0
        assert old_file.exists()

    def test_non_matching_files_ignored(self, tmp_path):
        """Files that don't match yyyy-MM-dd.jpg pattern should be ignored."""
        other_file = tmp_path / "other_file.jpg"
        other_file.write_text("content")

        deleted = sbw.cleanup_expired(tmp_path, retention_days=7)

        assert deleted == 0
        assert other_file.exists()


# ---------------------------------------------------------------------------
# Download tests
# ---------------------------------------------------------------------------


class TestDownloadWallpapers:
    def test_skips_existing_file(self, tmp_path, caplog):
        """Files that already exist should be skipped."""
        date_str = "2026-05-15"
        existing_file = tmp_path / f"{date_str}.jpg"
        existing_file.write_text("existing content")

        tasks = [
            {
                "date_str": date_str,
                "download_url": "https://example.com/wp.jpg",
            }
        ]

        with patch("requests.get"):
            downloaded, skipped, failed = sbw.download_wallpapers(tasks, tmp_path)

        assert skipped == 1
        assert downloaded == 0
        assert failed == 0

    def test_downloads_new_file(self, tmp_path):
        """New files should be downloaded."""
        date_str = "2026-05-15"

        tasks = [
            {
                "date_str": date_str,
                "download_url": "https://cn.bing.com/th?id=OHR.Test_UHD.jpg",
            }
        ]

        # Mock the download
        def _mock_download(url, dest: Path, session=None):
            dest.write_text("downloaded content")

        with patch.object(sbw, "_download_to_file", side_effect=_mock_download):
            downloaded, skipped, failed = sbw.download_wallpapers(tasks, tmp_path)

        assert downloaded == 1
        assert skipped == 0
        assert failed == 0
        assert (tmp_path / f"{date_str}.jpg").exists()


# ---------------------------------------------------------------------------
# URL safety validator tests
# ---------------------------------------------------------------------------


class TestIsSafeUrl:
    def test_allows_bing_com_url(self):
        """Bing.com URLs should be accepted."""
        assert sbw.is_safe_url("https://cn.bing.com/th?id=OHR.Test_UHD.jpg")

    def test_allows_bing_net_url(self):
        """Bing.net URLs should be accepted."""
        assert sbw.is_safe_url("https://images.bing.net/wallpaper.jpg")

    def test_rejects_non_bing_url(self):
        """Non-Bing URLs should be rejected."""
        assert not sbw.is_safe_url("https://example.com/malware.jpg")

    def test_rejects_non_http_scheme(self):
        """Non-HTTP/HTTPS URLs should be rejected."""
        assert not sbw.is_safe_url("ftp://bing.com/file.jpg")

    def test_rejects_malformed_url(self):
        """Malformed URLs should be safely rejected."""
        assert not sbw.is_safe_url("not a url at all")


# ---------------------------------------------------------------------------
# Main flow integration tests
# ---------------------------------------------------------------------------


class TestMainFlow:
    def test_main_no_network(self, capsys):
        """main() should return 1 when network check fails."""
        with patch.object(sbw, "check_network_connectivity", side_effect=RuntimeError("No network")):
            exit_code = sbw.main(["--num-days", "1", "--retention-days", "0"])
        assert exit_code == 1

    def test_main_no_wallpaper_data(self, tmp_path, capsys):
        """main() should return 1 when no wallpaper data found."""
        with patch.object(sbw, "check_network_connectivity", return_value=None):
            with patch.object(
                sbw, "fetch_wallpaper_data", return_value={}
            ):
                exit_code = sbw.main([
                    "--date", "2025-01-15",
                    "--retention-days", "0",
                    "--output-path", str(tmp_path),
                ])
        assert exit_code == 1

    def test_main_success_flow(self, tmp_path, capsys):
        """Full successful flow: network OK, data found, files downloaded."""
        mock_url_map = {
            "2026-05-15": "https://cn.bing.com/th?id=OHR.Test_UHD.jpg",
        }

        def _mock_download(url, dest: Path, session=None):
            dest.write_text("content")

        with patch.object(sbw, "check_network_connectivity", return_value=None):
            with patch.object(sbw, "fetch_wallpaper_data", return_value=mock_url_map):
                with patch.object(sbw, "cleanup_expired", return_value=0):
                    with patch.object(sbw, "_download_to_file", side_effect=_mock_download):
                        exit_code = sbw.main([
                            "--date", "2026-05-15",
                            "--retention-days", "0",
                            "--output-path", str(tmp_path),
                        ])

        assert exit_code == 0
        assert (tmp_path / "2026-05-15.jpg").exists()
