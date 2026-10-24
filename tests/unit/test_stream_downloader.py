"""Unit tests for the streaming, resumable download seam (local HTTP stub, no real network)."""

from __future__ import annotations

from collections.abc import Iterator
import contextlib
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from urllib import error

import pytest
from pytest_mock import MockerFixture

from filings_rfb._internal.utils.stream_downloader import download_file_streaming


pytestmark = pytest.mark.allow_network

BODY: bytes = bytes(range(256)) * 40
CUT_AT: int = 4096
CHUNK: int = 1024


@dataclass
class _StubState:
    """Mutable behaviour of the stub server, set per test."""

    body: bytes = BODY
    str_etag: str = '"v1"'
    int_cuts_left: int = 0
    int_cut_after: int = CUT_AT
    bool_honour_if_range: bool = True
    bool_send_length: bool = True
    bool_redirect: bool = False
    list_requests: list[dict[str, str]] = field(default_factory=list)


class _StubServer(ThreadingHTTPServer):
    """Threading HTTP server carrying the shared :class:`_StubState`."""

    state: _StubState


class _Handler(BaseHTTPRequestHandler):
    """Serve ``state.body`` with ``Range`` / ``If-Range`` / ``ETag`` semantics."""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Silence the default stderr access log.

        Parameters
        ----------
        format : str
            Ignored.
        *args : object
            Ignored.
        """

    def do_GET(self) -> None:  # noqa: N802  # complexity-ok: stub server protocol branching
        """Answer a GET: redirect, full body, or a (possibly cut) range."""
        cls_state: _StubState = self.server.state  # type: ignore[attr-defined]
        cls_state.list_requests.append(dict(self.headers))
        if cls_state.bool_redirect:
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/elsewhere")
            self.end_headers()
            return
        int_start = self._resolve_start(cls_state)
        self.send_response(206 if int_start else 200)
        self.send_header("ETag", cls_state.str_etag)
        if cls_state.bool_send_length:
            self.send_header("Content-Length", str(len(cls_state.body) - int_start))
        if int_start:
            int_last = len(cls_state.body) - 1
            self.send_header(
                "Content-Range", f"bytes {int_start}-{int_last}/{len(cls_state.body)}"
            )
        self.end_headers()
        self.wfile.write(self._payload(cls_state, int_start))

    def _resolve_start(  # complexity-ok: stub server protocol branch (Range / If-Range)
        self, cls_state: _StubState
    ) -> int:
        """Return the byte offset to serve from (0 when the range is not honoured).

        Parameters
        ----------
        cls_state : _StubState
            The stub behaviour.

        Returns
        -------
        int
            The first byte to send.
        """
        str_range = self.headers.get("Range")
        str_if_range = self.headers.get("If-Range")
        bool_valid = str_if_range in (None, cls_state.str_etag)
        if str_range and (bool_valid or not cls_state.bool_honour_if_range):
            return int(str_range.removeprefix("bytes=").rstrip("-"))
        return 0

    @staticmethod
    def _payload(  # complexity-ok: stub server protocol branch (cut vs full body)
        cls_state: _StubState, int_start: int
    ) -> bytes:
        """Return the bytes to write, cut short while ``int_cuts_left`` remains.

        Parameters
        ----------
        cls_state : _StubState
            The stub behaviour (``int_cuts_left`` is decremented on a cut).
        int_start : int
            The first byte to send.

        Returns
        -------
        bytes
            The response payload.
        """
        bytes_payload = cls_state.body[int_start:]
        if cls_state.int_cuts_left > 0:
            cls_state.int_cuts_left -= 1
            return bytes_payload[: cls_state.int_cut_after]
        return bytes_payload


@dataclass
class _Stub:
    """A running stub server: its URL and mutable state."""

    str_url: str
    cls_state: _StubState


@pytest.fixture(autouse=True)
def no_sleep(mocker: MockerFixture) -> None:
    """Skip retry backoff waits so a failing download test stays fast.

    Parameters
    ----------
    mocker : pytest_mock.MockerFixture
        The pytest-mock patcher.
    """
    mocker.patch("time.sleep")


@pytest.fixture
def stub(mocker: MockerFixture) -> Iterator[_Stub]:
    """Run a loopback HTTP stub and let the SSRF host check accept loopback.

    Parameters
    ----------
    mocker : pytest_mock.MockerFixture
        The pytest-mock patcher.

    Yields
    ------
    _Stub
        The running stub (URL + mutable state).
    """
    mocker.patch("filings_rfb._internal.utils.http_downloader._assert_public_host")
    cls_server = _StubServer(("127.0.0.1", 0), _Handler)
    cls_server.daemon_threads = True
    cls_server.state = _StubState()
    cls_thread = threading.Thread(target=cls_server.serve_forever, daemon=True)
    cls_thread.start()
    yield _Stub(f"http://127.0.0.1:{cls_server.server_port}/file.zip", cls_server.state)
    cls_server.shutdown()
    cls_server.server_close()
    cls_thread.join()


@pytest.fixture
def path_dest(tmp_path: Path) -> Path:
    """Return the final download path inside a temp dir.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest's per-test temp dir.

    Returns
    -------
    pathlib.Path
        The destination path (not yet created).
    """
    return tmp_path / "out" / "file.zip"


@pytest.fixture
def path_part(path_dest: Path) -> Path:
    """Return the temp ``.part`` path the downloader streams into.

    Parameters
    ----------
    path_dest : pathlib.Path
        The final destination path.

    Returns
    -------
    pathlib.Path
        The partial-file path.
    """
    return path_dest.with_name(path_dest.name + ".part")


def _seed_partial(path_part: Path, bytes_old: bytes, str_etag: str) -> None:
    """Pre-create a leftover partial download together with its ETag sidecar.

    Parameters
    ----------
    path_part : pathlib.Path
        The partial-file path.
    bytes_old : bytes
        The leftover bytes.
    str_etag : str
        The ETag recorded with them.
    """
    path_part.parent.mkdir(parents=True, exist_ok=True)
    path_part.write_bytes(bytes_old)
    path_part.with_name(path_part.name + ".etag").write_text(str_etag)


def test_download_streaming_full_body_matches_source(stub: _Stub, path_dest: Path) -> None:
    """The streamed file holds exactly the served bytes.

    Parameters
    ----------
    stub : _Stub
        The running stub server.
    path_dest : pathlib.Path
        The destination path.
    """
    download_file_streaming(stub.str_url, path_dest, int_chunk_bytes=CHUNK)

    assert path_dest.read_bytes() == BODY


def test_download_streaming_reads_in_bounded_chunks(
    stub: _Stub, path_dest: Path, mocker: MockerFixture
) -> None:
    """No single read asks for more than the chunk size (the body is never buffered whole).

    Parameters
    ----------
    stub : _Stub
        The running stub server.
    path_dest : pathlib.Path
        The destination path.
    mocker : pytest_mock.MockerFixture
        The pytest-mock patcher.
    """
    cls_spy = mocker.spy(__import__("http.client").client.HTTPResponse, "read")

    download_file_streaming(stub.str_url, path_dest, int_chunk_bytes=CHUNK)

    assert max(tuple_call.args[1] for tuple_call in cls_spy.call_args_list) == CHUNK


def test_download_streaming_returns_path_and_etag(stub: _Stub, path_dest: Path) -> None:
    """The result carries the final path and the server ETag for provenance.

    Parameters
    ----------
    stub : _Stub
        The running stub server.
    path_dest : pathlib.Path
        The destination path.
    """
    tuple_result = download_file_streaming(stub.str_url, path_dest)

    assert tuple_result == (path_dest, '"v1"')


def test_download_streaming_success_leaves_no_part_file(
    stub: _Stub, path_dest: Path, path_part: Path
) -> None:
    """After a clean run the temp file has been renamed away.

    Parameters
    ----------
    stub : _Stub
        The running stub server.
    path_dest : pathlib.Path
        The destination path.
    path_part : pathlib.Path
        The partial-file path.
    """
    download_file_streaming(stub.str_url, path_dest)

    assert not path_part.exists()


def test_download_streaming_resume_after_cut_completes_file(stub: _Stub, path_dest: Path) -> None:
    """A connection cut mid-body is resumed and the final file is byte-identical.

    Parameters
    ----------
    stub : _Stub
        The running stub server.
    path_dest : pathlib.Path
        The destination path.
    """
    stub.cls_state.int_cuts_left = 1

    download_file_streaming(stub.str_url, path_dest, int_chunk_bytes=CHUNK)

    assert path_dest.read_bytes() == BODY


def test_download_streaming_resume_after_cut_requests_remaining_range(
    stub: _Stub, path_dest: Path
) -> None:
    """The second request asks only for the bytes after the cut, guarded by ``If-Range``.

    Parameters
    ----------
    stub : _Stub
        The running stub server.
    path_dest : pathlib.Path
        The destination path.
    """
    stub.cls_state.int_cuts_left = 1

    download_file_streaming(stub.str_url, path_dest, int_chunk_bytes=CHUNK)

    dict_second = stub.cls_state.list_requests[1]
    assert (dict_second["Range"], dict_second["If-Range"]) == (f"bytes={CUT_AT}-", '"v1"')


@pytest.mark.parametrize("bool_honour_if_range", [True, False])
def test_download_streaming_etag_change_restarts_from_zero(
    stub: _Stub, path_dest: Path, path_part: Path, bool_honour_if_range: bool
) -> None:
    """A changed ETag discards the leftovers whether the server answers 200 or a stale 206.

    Parameters
    ----------
    stub : _Stub
        The running stub server.
    path_dest : pathlib.Path
        The destination path.
    path_part : pathlib.Path
        The partial-file path.
    bool_honour_if_range : bool
        Whether the stub validates ``If-Range`` (200) or ignores it (206 with a new ETag).
    """
    _seed_partial(path_part, b"OLD-CONTENT", '"old"')
    stub.cls_state.bool_honour_if_range = bool_honour_if_range

    download_file_streaming(stub.str_url, path_dest, int_chunk_bytes=CHUNK)

    assert path_dest.read_bytes() == BODY


def test_download_streaming_partial_without_etag_restarts(
    stub: _Stub, path_dest: Path, path_part: Path
) -> None:
    """A leftover with no recorded ETag cannot be trusted, so the download restarts.

    Parameters
    ----------
    stub : _Stub
        The running stub server.
    path_dest : pathlib.Path
        The destination path.
    path_part : pathlib.Path
        The partial-file path.
    """
    path_part.parent.mkdir(parents=True)
    path_part.write_bytes(b"UNKNOWN-ORIGIN")

    download_file_streaming(stub.str_url, path_dest)

    assert path_dest.read_bytes() == BODY


def test_download_streaming_size_mismatch_raises(stub: _Stub, path_dest: Path) -> None:
    """A body that stays shorter than ``Content-Length`` fails after the retries.

    Parameters
    ----------
    stub : _Stub
        The running stub server.
    path_dest : pathlib.Path
        The destination path.
    """
    stub.cls_state.int_cuts_left = 99
    stub.cls_state.int_cut_after = 100

    with pytest.raises(OSError, match="truncated"):
        download_file_streaming(stub.str_url, path_dest)


@pytest.fixture
def failed_download(stub: _Stub, path_dest: Path) -> None:
    """Run a download whose body never completes, swallowing the final error.

    Parameters
    ----------
    stub : _Stub
        The running stub server.
    path_dest : pathlib.Path
        The destination path.
    """
    stub.cls_state.int_cuts_left = 99
    stub.cls_state.int_cut_after = 100
    with contextlib.suppress(OSError):
        download_file_streaming(stub.str_url, path_dest)


@pytest.mark.usefixtures("failed_download")
def test_download_streaming_size_mismatch_leaves_nothing_at_dest(path_dest: Path) -> None:
    """A failed download never leaves a file at the final path.

    Parameters
    ----------
    path_dest : pathlib.Path
        The destination path.
    """
    assert not path_dest.exists()


def test_download_streaming_missing_content_length_raises(stub: _Stub, path_dest: Path) -> None:
    """Without ``Content-Length`` the size cannot be verified, so the download is refused.

    Parameters
    ----------
    stub : _Stub
        The running stub server.
    path_dest : pathlib.Path
        The destination path.
    """
    stub.cls_state.bool_send_length = False

    with pytest.raises(ValueError, match="Content-Length"):
        download_file_streaming(stub.str_url, path_dest)


def test_download_streaming_redirect_is_not_followed(stub: _Stub, path_dest: Path) -> None:
    """The seam's no-redirect guard still applies (a 3xx is a failed download).

    Parameters
    ----------
    stub : _Stub
        The running stub server.
    path_dest : pathlib.Path
        The destination path.
    """
    stub.cls_state.bool_redirect = True

    with pytest.raises(OSError, match="redirect blocked"):
        download_file_streaming(stub.str_url, path_dest)


def test_download_streaming_blocked_redirect_closes_the_http_error(
    stub: _Stub, path_dest: Path, mocker: MockerFixture
) -> None:
    """Every blocked redirect closes its ``HTTPError`` (and so the response it wraps).

    Parameters
    ----------
    stub : _Stub
        The running stub server.
    path_dest : pathlib.Path
        The destination path.
    mocker : pytest_mock.MockerFixture
        The pytest-mock patcher.
    """
    stub.cls_state.bool_redirect = True
    cls_spy = mocker.spy(error.HTTPError, "close")

    with contextlib.suppress(OSError):
        download_file_streaming(stub.str_url, path_dest)

    assert cls_spy.call_count == 3


def test_download_streaming_non_http_scheme_raises(path_dest: Path) -> None:
    """The scheme allow-list is reused: ``file://`` is rejected.

    Parameters
    ----------
    path_dest : pathlib.Path
        The destination path.
    """
    with pytest.raises(ValueError, match="unsupported URL scheme"):
        download_file_streaming("file:///etc/passwd", path_dest)


def test_download_streaming_loopback_host_raises(path_dest: Path) -> None:
    """The public-host guard is reused: a loopback target is rejected before any request.

    Parameters
    ----------
    path_dest : pathlib.Path
        The destination path.
    """
    with pytest.raises(ValueError, match="non-public address"):
        download_file_streaming("http://127.0.0.1:1/file.zip", path_dest)
