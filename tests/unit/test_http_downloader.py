"""Regression tests for the shared HTTP download seam's redirect guard."""

from __future__ import annotations

from collections.abc import Iterator
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from urllib import error

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


@pytest.fixture
def redirect_url(mocker: MockerFixture) -> Iterator[str]:
    """Serve a 302 from loopback with the SSRF host check relaxed and no retry sleeps.

    Parameters
    ----------
    mocker : pytest_mock.MockerFixture
        The pytest-mock patcher.

    Yields
    ------
    str
        The URL that answers with a redirect.
    """
    mocker.patch("time.sleep")
    mocker.patch("filings_rfb._internal.utils.http_downloader._assert_public_host")
    cls_server = ThreadingHTTPServer(("127.0.0.1", 0), _RedirectHandler)
    cls_thread = threading.Thread(target=cls_server.serve_forever, daemon=True)
    cls_thread.start()
    yield f"http://127.0.0.1:{cls_server.server_port}/f.zip"
    cls_server.shutdown()
    cls_server.server_close()
    cls_thread.join()


def test_download_file_blocked_redirect_closes_the_http_error(
    tmp_path: Path, mocker: MockerFixture, redirect_url: str
) -> None:
    """Every blocked redirect closes its ``HTTPError`` (and so the response it wraps).

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest's per-test temp dir.
    mocker : pytest_mock.MockerFixture
        The pytest-mock patcher.
    redirect_url : str
        The URL that answers with a redirect.
    """
    cls_spy = mocker.spy(error.HTTPError, "close")

    with contextlib.suppress(OSError):
        download_file(redirect_url, tmp_path / "f.zip")

    assert cls_spy.call_count == 3


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
