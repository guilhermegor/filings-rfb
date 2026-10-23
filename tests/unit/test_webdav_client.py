"""Unit tests for the WebDAV PROPFIND seam (no network: fixtures + a mocked opener)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
from urllib import error

import pytest

from filings_rfb._internal.utils import webdav_client
from filings_rfb._internal.utils.retry import backoff
from filings_rfb._internal.utils.webdav_client import (
    WebdavEntry,
    parse_multistatus,
    propfind,
)


PATH_FIXTURES = Path(__file__).parents[1] / "fixtures" / "cnpj"
HTTP_MULTISTATUS = 207


@pytest.fixture
def list_root_entries() -> list[WebdavEntry]:
    """Parse the recorded root PROPFIND once for the module.

    Returns
    -------
    list of WebdavEntry
        Every entry of the recorded root listing.
    """
    return parse_multistatus((PATH_FIXTURES / "propfind_root.xml").read_bytes())


@pytest.fixture
def list_month_entries() -> list[WebdavEntry]:
    """Parse the recorded 2026-10 PROPFIND once for the module.

    Returns
    -------
    list of WebdavEntry
        Every entry of the recorded month listing.
    """
    return parse_multistatus((PATH_FIXTURES / "propfind_month_2026-10.xml").read_bytes())


def test_parse_multistatus_root_lists_self_months_and_tarball(
    list_root_entries: list[WebdavEntry],
) -> None:
    """Root listing holds the folder itself, 42 month folders and ``cnpj.tar.gz``.

    Parameters
    ----------
    list_root_entries : list of WebdavEntry
        Parsed root fixture.
    """
    assert len(list_root_entries) == 44


def test_parse_multistatus_month_lists_self_and_37_files(
    list_month_entries: list[WebdavEntry],
) -> None:
    """A month listing holds the folder itself plus its 37 files.

    Parameters
    ----------
    list_month_entries : list of WebdavEntry
        Parsed month fixture.
    """
    assert len(list_month_entries) == 38


def test_parse_multistatus_file_entry_carries_every_property(
    list_month_entries: list[WebdavEntry],
) -> None:
    """The first file of the month keeps name, size, ETag and Last-Modified verbatim.

    Parameters
    ----------
    list_month_entries : list of WebdavEntry
        Parsed month fixture.
    """
    cls_cnaes = next(cls_e for cls_e in list_month_entries if cls_e.str_name == "Cnaes.zip")
    assert cls_cnaes == WebdavEntry(
        str_name="Cnaes.zip",
        is_collection=False,
        int_size=22078,
        str_etag='"17e2f9b2f51164f0e35a0e6011551c63"',
        dt_last_modified=datetime(2026, 10, 13, 22, 0, 16, tzinfo=timezone.utc),
    )


def test_parse_multistatus_collection_has_no_size(
    list_month_entries: list[WebdavEntry],
) -> None:
    """A collection reports no ``getcontentlength``, so its size is ``None``.

    Parameters
    ----------
    list_month_entries : list of WebdavEntry
        Parsed month fixture.
    """
    cls_self = next(cls_e for cls_e in list_month_entries if cls_e.is_collection)
    assert cls_self.int_size is None


def test_parse_multistatus_tarball_size_matches_source_bytes(
    list_root_entries: list[WebdavEntry],
) -> None:
    """``cnpj.tar.gz`` size equals the figure recorded in the epic discovery (63.9 GB).

    Parameters
    ----------
    list_root_entries : list of WebdavEntry
        Parsed root fixture.
    """
    cls_tar = next(cls_e for cls_e in list_root_entries if cls_e.str_name == "cnpj.tar.gz")
    assert cls_tar.int_size == 63954782749


def test_parse_multistatus_href_is_percent_decoded() -> None:
    """A percent-encoded href yields the decoded file name."""
    bytes_xml = (
        b'<d:multistatus xmlns:d="DAV:"><d:response><d:href>/dav/a%20b.zip</d:href>'
        b"<d:propstat><d:prop><d:resourcetype/></d:prop></d:propstat></d:response>"
        b"</d:multistatus>"
    )
    assert parse_multistatus(bytes_xml)[0].str_name == "a b.zip"


def test_parse_multistatus_entity_declaration_is_rejected() -> None:
    """Defusedxml refuses a document declaring entities (billion-laughs guard)."""
    bytes_xml = b'<!DOCTYPE d [<!ENTITY x "y">]><d:multistatus xmlns:d="DAV:"/>'
    with pytest.raises(ValueError, match="[Ee]ntit"):
        parse_multistatus(bytes_xml)


def test_parse_multistatus_malformed_xml_raises_value_error() -> None:
    """A body that is not XML raises ``ValueError`` naming the parse failure."""
    with pytest.raises(ValueError, match="not valid multistatus XML"):
        parse_multistatus(b"<html>login</html")


@pytest.fixture
def mock_opener(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch the shared no-redirect opener, skip the DNS check and the retry sleep.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        pytest fixture.

    Returns
    -------
    unittest.mock.MagicMock
        The patched ``_OPENER.open`` mock.
    """
    monkeypatch.setattr(webdav_client, "_assert_url_allowed", MagicMock())
    monkeypatch.setattr(backoff.time, "sleep", MagicMock())
    cls_response = MagicMock()
    cls_response.status = HTTP_MULTISTATUS
    cls_response.read.return_value = b"<xml/>"
    cls_response.__enter__.return_value = cls_response
    mock = MagicMock(return_value=cls_response)
    monkeypatch.setattr(webdav_client._OPENER, "open", mock)
    return mock


def test_propfind_sends_propfind_method_with_depth_header(mock_opener: MagicMock) -> None:
    """The request uses the ``PROPFIND`` verb and the requested ``Depth``.

    Parameters
    ----------
    mock_opener : unittest.mock.MagicMock
        The patched opener.
    """
    propfind("https://example.com/dav/", int_depth=1)
    cls_request = mock_opener.call_args.args[0]
    assert (cls_request.get_method(), cls_request.get_header("Depth")) == ("PROPFIND", "1")


def test_propfind_returns_response_body(mock_opener: MagicMock) -> None:
    """The raw multistatus body is returned unparsed.

    Parameters
    ----------
    mock_opener : unittest.mock.MagicMock
        The patched opener.
    """
    assert propfind("https://example.com/dav/") == b"<xml/>"


def test_propfind_non_multistatus_status_raises_os_error(mock_opener: MagicMock) -> None:
    """A 200 where a 207 is expected is an error, not a silent empty listing.

    Parameters
    ----------
    mock_opener : unittest.mock.MagicMock
        The patched opener.
    """
    mock_opener.return_value.status = 200
    with pytest.raises(OSError, match="status 200"):
        propfind("https://example.com/dav/")


def test_propfind_url_error_maps_to_os_error(mock_opener: MagicMock) -> None:
    """A transport failure surfaces as ``OSError`` naming the URL.

    Parameters
    ----------
    mock_opener : unittest.mock.MagicMock
        The patched opener.
    """
    mock_opener.side_effect = error.URLError("boom")
    with pytest.raises(OSError, match="example.com"):
        propfind("https://example.com/dav/")


def test_propfind_invalid_depth_raises_value_error() -> None:
    """Only Depth 0 and 1 are supported (``infinity`` is refused by most servers)."""
    with pytest.raises(ValueError, match="int_depth"):
        propfind("https://example.com/dav/", int_depth=2)
