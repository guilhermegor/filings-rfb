"""Streaming, resumable HTTP download seam for multi-GB archives (stdlib).

Sibling of :mod:`filings_rfb._internal.utils.http_downloader`, whose ``download_file`` buffers
the whole body in memory — infeasible for the RFB CNPJ archives (``Estabelecimentos0.zip`` is
2.28 GB). Kept as a separate module so ``http_downloader.py`` stays byte-identical to the
BlueprintX template seam; the SSRF guards (scheme allow-list, public-host check, no redirects)
and the retry policy are **imported from it, not copied**, so a hardening there reaches here.

The body is streamed in fixed-size chunks into ``<dest>.part``. The server ``ETag`` is stored in
``<dest>.part.etag``; after an interruption (or a retry of the same call) the download resumes
with ``Range: bytes=<n>-`` plus ``If-Range: <etag>``, and restarts from zero whenever the
server's ``ETag`` no longer matches the stored one or the leftover has no recorded ``ETag``.
The finished file is verified against ``Content-Length`` and renamed atomically, so the final
path never holds a partial file.
"""

from __future__ import annotations

from http.client import HTTPException, HTTPResponse
from io import BufferedIOBase
from pathlib import Path
import re
from urllib import error, request

from filings_rfb._internal.utils.http_downloader import (
    _DOWNLOAD_BASE_WAIT_S,
    _DOWNLOAD_MAX_ATTEMPTS,
    _OPENER,
    _TIMEOUT_SECONDS,
    _assert_url_allowed,
    close_http_error,
)
from filings_rfb._internal.utils.retry import retry_with_backoff
from filings_rfb._internal.utils.typing import type_checker


_CHUNK_BYTES: int = 1 << 20
_HTTP_PARTIAL_CONTENT: int = 206
_HTTP_RANGE_NOT_SATISFIABLE: int = 416
_BODY_STATUSES: frozenset[int] = frozenset({200, _HTTP_PARTIAL_CONTENT})
_CONTENT_RANGE: re.Pattern[str] = re.compile(r"bytes (\d+)-(\d+)/(\d+)")


class _StaleResume(Exception):  # noqa: N818
    """The leftover partial file cannot be continued; restart from zero."""


@retry_with_backoff(
    int_max_attempts=_DOWNLOAD_MAX_ATTEMPTS,
    float_base_wait_s=_DOWNLOAD_BASE_WAIT_S,
    tuple_exceptions=(OSError,),
)
@type_checker
def download_file_streaming(
    str_url: str,
    path_dest: Path,
    int_timeout_s: int = _TIMEOUT_SECONDS,
    int_chunk_bytes: int = _CHUNK_BYTES,
) -> tuple[Path, str]:
    """Stream ``str_url`` to ``path_dest`` in chunks, resuming an interrupted transfer.

    Validates the URL like ``download_file`` (scheme + public host, redirects refused), writes
    to ``<path_dest>.part`` and renames it onto ``path_dest`` only once the byte count matches
    ``Content-Length``. Transient failures are retried; a retry resumes from the bytes already
    on disk.

    Parameters
    ----------
    str_url : str
        The (http/https) URL to download.
    path_dest : pathlib.Path
        Final destination path; its parent is created if missing.
    int_timeout_s : int
        Socket timeout in seconds.
    int_chunk_bytes : int
        Size of each read from the socket, in bytes.

    Returns
    -------
    tuple[pathlib.Path, str]
        ``path_dest`` and the server ``ETag`` (empty string when the server sent none), for
        provenance.

    Raises
    ------
    ValueError
        If ``int_chunk_bytes`` is not positive, the URL is rejected by the SSRF guards, or the
        response lacks ``Content-Length``.
    OSError
        On a status other than 200/206, a redirect, a transport failure, or a body shorter than
        ``Content-Length`` (after the retries are exhausted).
    """
    _assert_chunk_size(int_chunk_bytes)
    _assert_url_allowed(str_url)
    path_dest.parent.mkdir(parents=True, exist_ok=True)
    path_part = path_dest.with_name(path_dest.name + ".part")
    str_etag = _stream_to_part(str_url, path_part, int_timeout_s, int_chunk_bytes)
    path_part.replace(path_dest)
    _etag_path(path_part).unlink(missing_ok=True)
    return path_dest, str_etag


@type_checker
def _assert_chunk_size(int_chunk_bytes: int) -> None:
    """Reject a non-positive chunk size before any connection is opened.

    ``read(-1)`` would buffer the whole remaining body, defeating the bounded-memory
    guarantee, and ``read(0)`` ends the copy loop at once.

    Parameters
    ----------
    int_chunk_bytes : int
        The requested chunk size.

    Raises
    ------
    ValueError
        If the size is not positive.
    """
    if int_chunk_bytes <= 0:
        raise ValueError(f"int_chunk_bytes must be positive, got {int_chunk_bytes}")


@type_checker
def _stream_to_part(
    str_url: str, path_part: Path, int_timeout_s: int, int_chunk_bytes: int
) -> str:
    """Resume from the leftover partial file if valid, else (re)start from zero.

    Parameters
    ----------
    str_url : str
        An already-validated URL.
    path_part : pathlib.Path
        The partial-file path.
    int_timeout_s : int
        Socket timeout in seconds.
    int_chunk_bytes : int
        Size of each read from the socket, in bytes.

    Returns
    -------
    str
        The server ``ETag`` of the completed body.
    """
    int_offset, str_stored_etag = _read_resume_state(path_part)
    try:
        return _stream_once(
            str_url, path_part, int_timeout_s, int_chunk_bytes, int_offset, str_stored_etag
        )
    except _StaleResume:
        return _stream_once(str_url, path_part, int_timeout_s, int_chunk_bytes, 0, "")


@type_checker
def _etag_path(path_part: Path) -> Path:
    """Return the sidecar path that records the partial file's ``ETag``.

    Parameters
    ----------
    path_part : pathlib.Path
        The partial-file path.

    Returns
    -------
    pathlib.Path
        The sidecar path.
    """
    return path_part.with_name(path_part.name + ".etag")


@type_checker
def _read_resume_state(path_part: Path) -> tuple[int, str]:
    """Return ``(bytes already on disk, their ETag)``, or ``(0, "")`` when not resumable.

    Parameters
    ----------
    path_part : pathlib.Path
        The partial-file path.

    Returns
    -------
    tuple[int, str]
        The resume offset and the ETag recorded with those bytes.
    """
    path_etag = _etag_path(path_part)
    if not (path_part.is_file() and path_etag.is_file() and path_etag.stat().st_size):
        return 0, ""
    return path_part.stat().st_size, path_etag.read_text()


@type_checker
def _stream_once(
    str_url: str,
    path_part: Path,
    int_timeout_s: int,
    int_chunk_bytes: int,
    int_offset: int,
    str_stored_etag: str,
) -> str:
    """Perform one request and append/write its body to the partial file.

    Parameters
    ----------
    str_url : str
        An already-validated URL.
    path_part : pathlib.Path
        The partial-file path.
    int_timeout_s : int
        Socket timeout in seconds.
    int_chunk_bytes : int
        Size of each read from the socket, in bytes.
    int_offset : int
        Bytes already on disk to resume from (0 for a fresh download).
    str_stored_etag : str
        The ETag recorded with those bytes.

    Returns
    -------
    str
        The response ``ETag`` (empty when absent).

    Raises
    ------
    ValueError
        If the response lacks ``Content-Length``.
    OSError
        If the body is shorter than ``Content-Length``.
    """
    with _open_response(str_url, int_timeout_s, int_offset, str_stored_etag) as cls_response:
        str_etag = cls_response.headers.get("ETag", "")
        int_start = _resolve_start(cls_response, int_offset, str_etag, str_stored_etag)
        int_expected = _read_content_length(cls_response)
        _record_etag(path_part, str_etag, int_start)
        int_received = _write_chunks(cls_response, path_part, int_start, int_chunk_bytes)
    _assert_complete(str_url, int_received, int_expected)
    return str_etag


@type_checker
def _assert_complete(str_url: str, int_received: int, int_expected: int) -> None:
    """Raise if the body ended before ``Content-Length`` bytes arrived.

    The partial file is kept, so the retry resumes instead of starting over.

    Parameters
    ----------
    str_url : str
        The URL being downloaded.
    int_received : int
        Body bytes received by this request.
    int_expected : int
        Body bytes promised by ``Content-Length``.

    Raises
    ------
    OSError
        If the counts differ.
    """
    if int_received != int_expected:
        raise OSError(
            f"Download truncated for {str_url!r}: got {int_received} of {int_expected} bytes"
        )


@type_checker
def _open_response(
    str_url: str, int_timeout_s: int, int_offset: int, str_etag: str
) -> HTTPResponse:
    """Open the GET request (with ``Range`` / ``If-Range`` when resuming) without redirects.

    ⚠️ Call only AFTER ``_assert_url_allowed``: the S310 suppressions are sound precisely
    because the scheme is validated and the shared opener blocks redirects.

    Parameters
    ----------
    str_url : str
        An already-validated URL.
    int_timeout_s : int
        Socket timeout in seconds.
    int_offset : int
        Bytes already on disk; when positive a ``Range`` request is sent.
    str_etag : str
        The ETag recorded with those bytes, sent as ``If-Range``.

    Returns
    -------
    http.client.HTTPResponse
        The open response.

    Raises
    ------
    _StaleResume
        If the server answers 416 to a ranged request.
    OSError
        On a non-2xx status, a blocked redirect or any transport failure.
    """
    dict_headers = {"Range": f"bytes={int_offset}-", "If-Range": str_etag} if int_offset else {}
    cls_request = request.Request(str_url, headers=dict_headers, method="GET")  # noqa: S310
    try:
        return _OPENER.open(cls_request, timeout=int_timeout_s)  # noqa: S310
    except error.URLError as cls_err:
        raise _map_open_error(cls_err, str_url, int_offset) from cls_err


@type_checker
def _map_open_error(
    cls_err: error.URLError, str_url: str, int_offset: int
) -> _StaleResume | OSError:
    """Translate a failed open into the exception the caller handles.

    A 416 to a ranged request means the leftover cannot be continued (resume is stale);
    anything else is a failed download (``OSError``, retried).

    Parameters
    ----------
    cls_err : urllib.error.URLError
        The error raised by the opener (an ``HTTPError`` for any non-2xx or blocked redirect).
    str_url : str
        The URL being downloaded.
    int_offset : int
        Bytes already on disk; 416 only signals a stale resume when positive.

    Returns
    -------
    _StaleResume | OSError
        The exception to raise.
    """
    close_http_error(cls_err)
    if (
        isinstance(cls_err, error.HTTPError)
        and int_offset > 0
        and cls_err.code == _HTTP_RANGE_NOT_SATISFIABLE
    ):
        return _StaleResume()
    return OSError(f"Failed to download {str_url!r}: {cls_err}")


@type_checker
def _resolve_start(
    cls_response: HTTPResponse, int_offset: int, str_etag: str, str_stored_etag: str
) -> int:
    """Return the byte offset the response body continues from.

    A 200 to a ranged request means the server restarted the body (``If-Range`` failed), so
    the file is rewritten from zero. A 206 is accepted only if the ETag still matches and the
    ``Content-Range`` starts exactly at the offset; otherwise the resume is stale.

    Parameters
    ----------
    cls_response : http.client.HTTPResponse
        The open response.
    int_offset : int
        Bytes already on disk (0 for a fresh download).
    str_etag : str
        The ETag the server just sent.
    str_stored_etag : str
        The ETag recorded with the bytes on disk.

    Returns
    -------
    int
        ``int_offset`` when continuing, else 0.

    Raises
    ------
    _StaleResume
        If a 206 does not continue the stored partial file.
    """
    _assert_body_status(cls_response.status)
    if cls_response.status != _HTTP_PARTIAL_CONTENT:
        return 0
    _assert_continues(cls_response, int_offset, int_offset == 0 or str_etag == str_stored_etag)
    return int_offset


@type_checker
def _assert_body_status(int_status: int) -> None:
    """Raise unless the response carries a file body (200) or a range of it (206).

    Any other 2xx (204, 205, ...) has no content; renaming its empty ``.part`` into place
    would publish an empty file as a finished download.

    Parameters
    ----------
    int_status : int
        The response status code.

    Raises
    ------
    OSError
        If the status is neither 200 nor 206.
    """
    if int_status not in _BODY_STATUSES:
        raise OSError(f"Download returned status {int_status}; expected 200 or 206")


@type_checker
def _assert_continues(cls_response: HTTPResponse, int_offset: int, bool_same_etag: bool) -> None:
    """Raise unless a 206 covers the object from ``int_offset`` through its last byte.

    A 206 to an initial request (``int_offset`` 0) is only acceptable when it spans the whole
    object; otherwise the truncated body would be renamed into place as complete.

    Parameters
    ----------
    cls_response : http.client.HTTPResponse
        The open 206 response.
    int_offset : int
        Bytes already on disk.
    bool_same_etag : bool
        Whether the server ETag equals the one recorded with those bytes.

    Raises
    ------
    _StaleResume
        If a resume's ETag changed or its ``Content-Range`` does not continue the file.
    ValueError
        If a response to an initial request is a partial one.
    """
    tuple_range = _parse_content_range(cls_response.headers.get("Content-Range", ""))
    bool_ok = bool_same_etag and tuple_range[0] == int_offset and tuple_range[1] == tuple_range[2]
    if bool_ok:
        return
    raise (
        _StaleResume
        if int_offset
        else ValueError(
            "206 response to an initial request does not cover the whole file (Content-Range)"
        )
    )


@type_checker
def _parse_content_range(str_range: str) -> tuple[int, int, int]:
    """Parse ``bytes <start>-<end>/<total>`` into ``(start, end + 1, total)``.

    Parameters
    ----------
    str_range : str
        The ``Content-Range`` header value.

    Returns
    -------
    tuple[int, int, int]
        ``(start, end + 1, total)``; ``(-1, -1, -2)`` when absent or unparsable, which never
        satisfies the "covers the rest of the file" comparison.
    """
    cls_match = _CONTENT_RANGE.fullmatch(str_range.strip())
    if cls_match is None:
        return -1, -1, -2
    int_start, int_end, int_total = (int(str_group) for str_group in cls_match.groups())
    return int_start, int_end + 1, int_total


@type_checker
def _read_content_length(cls_response: HTTPResponse) -> int:
    """Return the number of body bytes this response promises.

    Parameters
    ----------
    cls_response : http.client.HTTPResponse
        The open response.

    Returns
    -------
    int
        The ``Content-Length`` value.

    Raises
    ------
    ValueError
        If the header is absent (the final size could not be verified).
    """
    str_length = cls_response.headers.get("Content-Length")
    if str_length is None:
        raise ValueError("response lacks Content-Length; cannot verify the download size")
    return int(str_length)


@type_checker
def _record_etag(path_part: Path, str_etag: str, int_start: int) -> None:
    """Record the ETag of a fresh download beside its partial file.

    A continued download keeps the sidecar it resumed from. An empty ETag is recorded as an
    empty sidecar, which :func:`_read_resume_state` treats as not resumable.

    Parameters
    ----------
    path_part : pathlib.Path
        The partial-file path.
    str_etag : str
        The ETag the server sent (empty when absent).
    int_start : int
        Offset the body continues from; positive means the sidecar is already correct.
    """
    if int_start:
        return
    _etag_path(path_part).write_text(str_etag)


@type_checker
def _write_chunks(
    cls_response: HTTPResponse, path_part: Path, int_start: int, int_chunk_bytes: int
) -> int:
    """Copy the body to the partial file chunk by chunk and return the bytes written.

    Parameters
    ----------
    cls_response : http.client.HTTPResponse
        The open response.
    path_part : pathlib.Path
        The partial-file path.
    int_start : int
        Offset the body continues from; positive appends, zero truncates and rewrites.
    int_chunk_bytes : int
        Size of each read from the socket, in bytes.

    Returns
    -------
    int
        Number of body bytes written by this call.

    Raises
    ------
    OSError
        If the connection drops mid-body.
    """
    with path_part.open("ab" if int_start else "wb") as cls_file:
        try:
            return _copy_chunks(cls_response, cls_file, int_chunk_bytes)
        except HTTPException as cls_err:
            raise OSError(f"Connection dropped mid-body: {cls_err}") from cls_err


@type_checker
def _copy_chunks(
    cls_response: HTTPResponse, cls_file: BufferedIOBase, int_chunk_bytes: int
) -> int:
    """Read the body ``int_chunk_bytes`` at a time into ``cls_file``.

    Parameters
    ----------
    cls_response : http.client.HTTPResponse
        The open response.
    cls_file : io.BufferedIOBase
        The open partial file.
    int_chunk_bytes : int
        Size of each read from the socket, in bytes.

    Returns
    -------
    int
        Number of body bytes copied.
    """
    int_received = 0
    while bytes_chunk := cls_response.read(int_chunk_bytes):
        cls_file.write(bytes_chunk)
        int_received += len(bytes_chunk)
    return int_received
