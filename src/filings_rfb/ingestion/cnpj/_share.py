"""Catalogue of the RFB CNPJ open-data share: which months exist, which files each holds.

The share is a public NextCloud folder. Its WebDAV endpoint answers ``PROPFIND`` and plain
``GET`` without authentication, laid out as ``<root>/<YYYY-MM>/<file>`` plus a root-level
``cnpj.tar.gz``. This module is the one place that knows that layout: every CNPJ reader asks
it for a month, a file listing, or a download URL instead of building URLs itself.

⚠️ Do not use the legacy ``index.php/s/<token>/download?...`` URL stpstone relies on — it now
303-redirects to a path-less zip that drops the month. If RFB rotates the share, change
:data:`SHARE_TOKEN` and nothing else.

Listings are fetched on every call (no cache): the catalogue answers "what does RFB publish
*now*", and a stale answer is exactly what an incremental ingestion must not act on.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from filings_rfb._internal.utils.typing import type_checker
from filings_rfb._internal.utils.webdav_client import WebdavEntry, parse_multistatus, propfind


__all__ = [
    "SHARE_ROOT_URL",
    "SHARE_TOKEN",
    "file_url",
    "latest_reference_month",
    "list_files",
    "list_reference_months",
]

SHARE_TOKEN: str = "YggdBLfdninEJX9"  # noqa: S105 — public share id, not a secret
SHARE_ROOT_URL: str = f"https://arquivos.receitafederal.gov.br/public.php/dav/files/{SHARE_TOKEN}/"

_RE_MONTH: re.Pattern[str] = re.compile(r"(?:19|20)\d{2}-(?:0[1-9]|1[0-2])")
_UNSAFE_NAMES: frozenset[str] = frozenset({"", ".", ".."})


@type_checker
def list_reference_months() -> list[str]:
    """List every reference month the share publishes.

    Returns
    -------
    list of str
        ``YYYY-MM`` folder names, ascending (the share's non-month entries, such as
        ``cnpj.tar.gz``, are ignored).
    """
    list_entries = parse_multistatus(propfind(SHARE_ROOT_URL, int_depth=1))
    return sorted(
        cls_entry.str_name
        for cls_entry in list_entries
        if cls_entry.is_collection and _RE_MONTH.fullmatch(cls_entry.str_name)
    )


@type_checker
def latest_reference_month() -> str:
    """Return the newest reference month the share publishes.

    Returns
    -------
    str
        The greatest ``YYYY-MM``.

    Raises
    ------
    ValueError
        If the share lists no reference month at all.
    """
    list_months = list_reference_months()
    if not list_months:
        raise ValueError(f"the share lists no reference month: {SHARE_ROOT_URL}")
    return list_months[-1]


@type_checker
def list_files(str_month: str) -> list[WebdavEntry]:
    """List the files of one reference month with their size, ``ETag`` and Last-Modified.

    Parameters
    ----------
    str_month : str
        The reference month, ``YYYY-MM``.

    Returns
    -------
    list of WebdavEntry
        The month's files in the order the share returns them (sub-folders excluded).

    Raises
    ------
    ValueError
        If ``str_month`` is not ``YYYY-MM`` or the share does not publish it. There is no
        fallback to another month: the caller asked for this one.
    """
    _assert_month_format(str_month)
    list_months = list_reference_months()
    if str_month not in list_months:
        raise ValueError(
            f"reference month {str_month} is not published "
            f"(latest: {', '.join(list_months[-3:]) or 'none'})"
        )
    list_entries = parse_multistatus(propfind(f"{SHARE_ROOT_URL}{str_month}/", int_depth=1))
    return [cls_entry for cls_entry in list_entries if not cls_entry.is_collection]


@type_checker
def file_url(str_month: str, str_name: str) -> str:
    """Build the plain-``GET`` download URL of one file of a month.

    Pure string work: it does not check that the file exists (see :func:`list_files`).

    Parameters
    ----------
    str_month : str
        The reference month, ``YYYY-MM``.
    str_name : str
        The file name, e.g. ``Empresas0.zip``.

    Returns
    -------
    str
        ``<root>/<YYYY-MM>/<file>``, with the name percent-encoded.

    Raises
    ------
    ValueError
        If the month is not ``YYYY-MM``, or the name is blank, ``.``/``..`` or holds a path
        separator (it could otherwise leave the month folder).
    """
    _assert_month_format(str_month)
    if str_name in _UNSAFE_NAMES or "/" in str_name or "\\" in str_name:
        raise ValueError(f"invalid file name: {str_name!r}")
    return f"{SHARE_ROOT_URL}{str_month}/{quote(str_name)}"


@type_checker
def _assert_month_format(str_month: str) -> None:
    """Reject anything that is not a ``YYYY-MM`` month.

    Parameters
    ----------
    str_month : str
        The value to validate.

    Raises
    ------
    ValueError
        If ``str_month`` is not ``YYYY-MM``.
    """
    if not _RE_MONTH.fullmatch(str_month):
        raise ValueError(f"reference month must be YYYY-MM, got {str_month!r}")
