"""Read-only WebDAV listing seam (``PROPFIND``), stdlib transport + ``defusedxml`` parsing.

The sibling of :mod:`filings_rfb._internal.utils.http_downloader`: that module owns ``GET``,
this one owns the single other verb a catalogue needs. It reuses the downloader's SSRF
guard and its no-redirect opener, so a listing is held to the same rules as a download —
callers depend on :func:`propfind` / :func:`parse_multistatus`, never on ``urllib`` or an
XML vendor, so a transport or parser change is confined here and tests mock at this boundary.

A multistatus body is untrusted input; it is parsed through :mod:`defusedxml` (entity
expansion and external entities are refused), never bare :mod:`xml.etree.ElementTree`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib import error, request
from urllib.parse import unquote
from xml.etree.ElementTree import (  # noqa: S405 — types only; parsing is defused
    Element,
    ParseError,
)

from defusedxml.ElementTree import fromstring as defused_fromstring

from filings_rfb._internal.utils.http_downloader import (
    _OPENER,  # noqa: PLC2701 — shares the SSRF-hardened no-redirect opener
    _assert_url_allowed,  # noqa: PLC2701 — shares the scheme + public-host guard
)
from filings_rfb._internal.utils.retry import retry_with_backoff
from filings_rfb._internal.utils.typing import TypeChecker, type_checker


__all__ = ["WebdavEntry", "parse_multistatus", "propfind"]

_TIMEOUT_SECONDS: int = 30
_HTTP_MULTISTATUS: int = 207
_VALID_DEPTHS: frozenset[int] = frozenset({0, 1})
_MAX_ATTEMPTS: int = 3
_BASE_WAIT_S: float = 2.0
_DAV: dict[str, str] = {"d": "DAV:"}


@dataclass(frozen=True)
class WebdavEntry(metaclass=TypeChecker):
    """One resource of a multistatus listing.

    Parameters
    ----------
    str_name : str
        Last path segment of the resource's href, percent-decoded (empty for the share root).
    is_collection : bool
        Whether the resource is a folder.
    int_size : int | None
        ``getcontentlength`` in bytes; ``None`` for a collection.
    str_etag : str
        ``getetag`` exactly as the server sent it, quotes included (``'"abc"'``); empty when
        absent.
    dt_last_modified : datetime | None
        ``getlastmodified`` as a timezone-aware datetime; ``None`` when absent.
    """

    str_name: str
    is_collection: bool
    int_size: int | None
    str_etag: str
    dt_last_modified: datetime | None


@retry_with_backoff(
    int_max_attempts=_MAX_ATTEMPTS,
    float_base_wait_s=_BASE_WAIT_S,
    tuple_exceptions=(OSError,),
)
@type_checker
def propfind(  # complexity-ok: depth guard + status check + transport error mapping
    str_url: str, int_depth: int = 1, int_timeout_s: int = _TIMEOUT_SECONDS
) -> bytes:
    """Return the raw ``207 Multi-Status`` body of a ``PROPFIND`` on ``str_url``.

    Redirects are not followed and the host must be public, exactly as for a download.

    Parameters
    ----------
    str_url : str
        The (http/https) collection URL to list.
    int_depth : int, optional
        ``0`` for the resource itself, ``1`` for it plus its children, by default ``1``.
    int_timeout_s : int, optional
        Socket timeout in seconds, by default :data:`_TIMEOUT_SECONDS`.

    Returns
    -------
    bytes
        The undecoded response body.

    Raises
    ------
    ValueError
        If ``int_depth`` is not 0 or 1, or the URL is blank, non-http(s) or non-public.
    OSError
        On a transport failure, a redirect, or any status other than 207.
    """
    if int_depth not in _VALID_DEPTHS:
        raise ValueError(f"int_depth must be 0 or 1, got {int_depth!r}")
    _assert_url_allowed(str_url)
    cls_request = request.Request(  # noqa: S310
        str_url, method="PROPFIND", headers={"Depth": str(int_depth)}
    )
    try:
        with _OPENER.open(cls_request, timeout=int_timeout_s) as cls_response:  # noqa: S310
            if cls_response.status != _HTTP_MULTISTATUS:
                raise OSError(f"PROPFIND returned status {cls_response.status} for {str_url!r}")
            return cls_response.read()
    except error.URLError as cls_err:
        raise OSError(f"Failed to PROPFIND {str_url!r}: {cls_err}") from cls_err


@type_checker
def parse_multistatus(bytes_xml: bytes) -> list[WebdavEntry]:
    """Parse a multistatus body into one :class:`WebdavEntry` per ``<response>``.

    The listed collection itself is included (WebDAV returns it first); a caller that wants
    only the children filters on ``is_collection`` or the name.

    Parameters
    ----------
    bytes_xml : bytes
        The body returned by :func:`propfind`.

    Returns
    -------
    list of WebdavEntry
        The entries in document order.

    Raises
    ------
    ValueError
        If the body is not well-formed XML, or declares entities (refused by defusedxml).
    """
    try:
        cls_root = defused_fromstring(bytes_xml)
    except ParseError as cls_err:
        raise ValueError(f"not valid multistatus XML: {cls_err}") from cls_err
    return [_to_entry(cls_response) for cls_response in cls_root.findall("d:response", _DAV)]


@type_checker
def _to_entry(cls_response: Element) -> WebdavEntry:
    """Build one entry from a ``<response>`` element.

    Parameters
    ----------
    cls_response : xml.etree.ElementTree.Element
        A ``DAV:response`` element.

    Returns
    -------
    WebdavEntry
        The decoded resource.
    """
    str_href = cls_response.findtext("d:href", default="", namespaces=_DAV)
    cls_prop = _found_prop(cls_response)
    str_size = cls_prop.findtext("d:getcontentlength", default="", namespaces=_DAV)
    str_modified = cls_prop.findtext("d:getlastmodified", default="", namespaces=_DAV)
    is_collection = cls_prop.find("d:resourcetype/d:collection", _DAV) is not None
    return WebdavEntry(
        str_name=unquote(str_href.rstrip("/").rsplit("/", 1)[-1]),
        is_collection=is_collection,
        int_size=int(str_size) if str_size and not is_collection else None,
        str_etag=cls_prop.findtext("d:getetag", default="", namespaces=_DAV),
        dt_last_modified=parsedate_to_datetime(str_modified) if str_modified else None,
    )


@type_checker
def _found_prop(  # complexity-ok: one pass over the propstats, taking the 200 one
    cls_response: Element,
) -> Element:
    """Return the ``<prop>`` of the ``200 OK`` propstat (an empty one when none is OK).

    A server answers properties it lacks in a separate ``404`` propstat; reading the first
    propstat blindly would take that one when it happens to come first.

    Parameters
    ----------
    cls_response : xml.etree.ElementTree.Element
        A ``DAV:response`` element.

    Returns
    -------
    xml.etree.ElementTree.Element
        The matching ``DAV:prop`` element, or an empty ``Element`` when no propstat is 200.
    """
    for cls_propstat in cls_response.findall("d:propstat", _DAV):
        if " 200 " in cls_propstat.findtext("d:status", default="", namespaces=_DAV):
            cls_prop = cls_propstat.find("d:prop", _DAV)
            return cls_prop if cls_prop is not None else Element("prop")
    return Element("prop")
