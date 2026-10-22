"""HTTP file-download seam (stdlib, SSRF-hardened).

One reusable place for "download a file from a URL". The transport uses the standard
library (``urllib.request``) so the skeleton stays dependency-free for peripheral I/O —
the same choice as ``webhook`` adapters. This is the **only** place network downloads
should happen (the "library coupling" seam rule in CLAUDE.md): callers depend on
``download_file``, not on a vendor API, so a transport change is confined here and tests
mock at this boundary.

**SSRF hardening.** When a URL can originate from untrusted input, a tampered value could
point the server at an internal host. Before fetching, the host is resolved and rejected
if it maps to a private / loopback / link-local / reserved address, and HTTP redirects are
NOT followed (a redirect could hop to an internal target that bypasses the up-front check).
"""

from __future__ import annotations

from http.client import HTTPMessage
import ipaddress
from pathlib import Path
import socket
from typing import IO, TYPE_CHECKING
from urllib import error, request
from urllib.parse import urlsplit

from filings_rfb._internal.utils.retry import retry_with_backoff


if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import TypeVar

    _F = TypeVar("_F", bound=Callable[..., object])

    def type_checker(fn: _F) -> _F:
        """Type-only stub — see src/utils/CLAUDE.md."""

    class TypeChecker(type):
        """Type-only stub — see src/utils/CLAUDE.md."""
else:
    try:
        from filings_rfb._internal.utils.typing import TypeChecker, type_checker
    except ModuleNotFoundError:
        from filings_rfb._internal.utils.typing import TypeChecker, type_checker


_TIMEOUT_SECONDS: int = 30
_HTTP_OK_MIN: int = 200
_HTTP_OK_MAX: int = 299
_ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})
_DOWNLOAD_MAX_ATTEMPTS: int = 3
_DOWNLOAD_BASE_WAIT_S: float = 2.0


class _NoRedirectHandler(request.HTTPRedirectHandler, metaclass=TypeChecker):
    """Redirect handler that refuses to follow any redirect (SSRF guard).

    ``urllib`` follows 3xx automatically through the default opener and fetches the
    redirect target **without** re-validating its host — a classic SSRF bypass. Raising
    here turns any redirect into an error the caller treats as a failed (broken) download.
    """

    def redirect_request(
        self,
        req: request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> None:
        """Reject the redirect instead of following it.

        Parameters
        ----------
        req : urllib.request.Request
            The original request.
        fp : IO[bytes]
            The response file object.
        code : int
            The 3xx status code.
        msg : str
            The status message.
        headers : HTTPMessage
            The response headers.
        newurl : str
            The redirect target.

        Raises
        ------
        urllib.error.HTTPError
            Always — redirects are not followed.
        """
        raise error.HTTPError(req.full_url, code, f"redirect blocked to {newurl!r}", headers, fp)


_OPENER: request.OpenerDirector = request.build_opener(_NoRedirectHandler)


@retry_with_backoff(
    int_max_attempts=_DOWNLOAD_MAX_ATTEMPTS,
    float_base_wait_s=_DOWNLOAD_BASE_WAIT_S,
    tuple_exceptions=(OSError,),
)
@type_checker
def download_file(str_url: str, path_dest: Path, int_timeout_s: int = _TIMEOUT_SECONDS) -> Path:
    """Download ``str_url`` to ``path_dest`` and return the written path.

    Validates the URL (scheme + non-internal host), fetches it **without following
    redirects**, and writes the body to disk (the destination directory is created when
    absent). Any failure — bad URL, internal host, non-2xx status, redirect, network
    error, timeout — raises, so the caller can treat a failed download as a broken input.

    Parameters
    ----------
    str_url : str
        The (http/https) URL to download.
    path_dest : pathlib.Path
        Destination file path; its parent is created if missing.
    int_timeout_s : int, optional
        Socket timeout in seconds, by default :data:`_TIMEOUT_SECONDS`.

    Returns
    -------
    pathlib.Path
        The path the content was written to (``path_dest``).

    Raises
    ------
    ValueError
        If the URL is empty, its scheme is not http/https, or its host resolves to a
        non-public (private / loopback / link-local / reserved) address.
    OSError
        If the download fails (network error, non-2xx status, redirect, timeout, write).
    """
    _assert_url_allowed(str_url)
    path_dest.parent.mkdir(parents=True, exist_ok=True)
    path_dest.write_bytes(_fetch_bytes(str_url, int_timeout_s))
    return path_dest


@type_checker
def _assert_url_allowed(
    str_url: str,
) -> None:  # complexity-ok: input validation, one branch per rejection rule
    """Reject a blank URL or a non-http/https scheme, then validate the host.

    Parameters
    ----------
    str_url : str
        The URL to validate.

    Returns
    -------
    None

    Raises
    ------
    ValueError
        If the URL is blank, its scheme is not allowed, or its host is not public.
    OSError
        If the host cannot be resolved.
    """
    if not str_url.strip():
        raise ValueError("empty download URL")
    str_scheme = str_url.split("://", 1)[0].lower() if "://" in str_url else ""
    if str_scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"unsupported URL scheme (expected http/https): {str_url!r}")
    _assert_public_host(str_url)


@type_checker
def _fetch_bytes(
    str_url: str, int_timeout_s: int
) -> bytes:  # complexity-ok: transport error handling
    """Fetch a validated URL and return its body, mapping transport failures to ``OSError``.

    ⚠️ Call only AFTER :func:`_assert_url_allowed`. The S310 suppressions below are sound
    precisely because the scheme is already validated and the opener blocks redirects; reached
    without that validation they would be a bare arbitrary-scheme open.

    Parameters
    ----------
    str_url : str
        An already-validated URL.
    int_timeout_s : int
        Socket timeout in seconds.

    Returns
    -------
    bytes
        The response body.

    Raises
    ------
    OSError
        On a non-2xx status or any transport failure.
    """
    cls_request = request.Request(str_url, method="GET")  # noqa: S310
    try:
        with _OPENER.open(cls_request, timeout=int_timeout_s) as cls_response:  # noqa: S310
            int_status = cls_response.status
            if not _HTTP_OK_MIN <= int_status <= _HTTP_OK_MAX:
                raise OSError(f"Download returned status {int_status} for {str_url!r}")
            return cls_response.read()
    except error.URLError as cls_err:
        raise OSError(f"Failed to download {str_url!r}: {cls_err}") from cls_err


@type_checker
def _assert_public_host(
    str_url: str,
) -> None:  # complexity-ok: SSRF guard, one branch per rejection rule
    """Reject a URL whose host resolves to a non-public address (SSRF guard).

    Resolves every address the host maps to and rejects the request if any is private,
    loopback, link-local, reserved, unspecified or multicast — the ranges an SSRF probe
    would target (e.g. ``127.0.0.1``, ``169.254.169.254``, ``10.x``, ``::1``, ``fc00::/7``).

    Parameters
    ----------
    str_url : str
        The URL whose host is validated.

    Raises
    ------
    ValueError
        If the host is empty or resolves to a non-public address.
    OSError
        If the host cannot be resolved.
    """
    str_host = (urlsplit(str_url).hostname or "").rstrip(".").lower()
    if not str_host:
        raise ValueError(f"URL without host: {str_url!r}")
    try:
        list_info = socket.getaddrinfo(str_host, None)
    except socket.gaierror as cls_err:
        raise OSError(f"Host not resolved ({str_host!r}): {cls_err}") from cls_err
    for tuple_info in list_info:
        cls_ip = ipaddress.ip_address(tuple_info[4][0])
        if (
            cls_ip.is_private
            or cls_ip.is_loopback
            or cls_ip.is_link_local
            or cls_ip.is_reserved
            or cls_ip.is_unspecified
            or cls_ip.is_multicast
        ):
            raise ValueError(f"Host {str_host!r} resolves to a non-public address ({cls_ip})")
