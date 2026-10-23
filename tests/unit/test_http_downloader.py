"""Regression tests for the shared HTTP download seam's redirect guard."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

import pytest
from pytest_mock import MockerFixture

from filings_rfb._internal.utils.http_downloader import download_file


pytestmark = pytest.mark.allow_network


class _RedirectHandler(BaseHTTPRequestHandler):
    """Answer every GET with a 302 to another host."""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Silence the default stderr access log.

        Parameters
        ----------
        format : str
            Ignored.
        *args : object
            Ignored.
        """

    def do_GET(self) -> None:  # noqa: N802
        """Redirect to an unrelated URL."""
        self.send_response(302)
        self.send_header("Location", "http://127.0.0.1:1/elsewhere")
        self.end_headers()


def test_download_file_redirect_raises_oserror_not_followed(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """A 3xx surfaces as ``OSError`` (retryable download failure), never a ``TypeError``.

    The redirect handler's ``fp`` annotation once rejected ``urllib``'s ``HTTPResponse`` at
    runtime, so the guard fired as a ``TypeError`` instead of the documented ``OSError``.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest's per-test temp dir.
    mocker : pytest_mock.MockerFixture
        The pytest-mock patcher.
    """
    mocker.patch("time.sleep")
    mocker.patch("filings_rfb._internal.utils.http_downloader._assert_public_host")
    cls_server = ThreadingHTTPServer(("127.0.0.1", 0), _RedirectHandler)
    cls_thread = threading.Thread(target=cls_server.serve_forever, daemon=True)
    cls_thread.start()
    try:
        with pytest.raises(OSError, match="redirect blocked"):
            download_file(f"http://127.0.0.1:{cls_server.server_port}/f.zip", tmp_path / "f.zip")
    finally:
        cls_server.shutdown()
        cls_server.server_close()
        cls_thread.join()
