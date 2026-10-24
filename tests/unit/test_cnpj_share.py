"""Unit tests for the RFB CNPJ share catalogue (recorded PROPFIND fixtures, no network)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from filings_rfb.ingestion.cnpj import _share
from filings_rfb.ingestion.cnpj._share import (
    SHARE_ROOT_URL,
    SHARE_TOKEN,
    file_url,
    latest_reference_month,
    list_files,
    list_reference_months,
)


PATH_FIXTURES = Path(__file__).parents[1] / "fixtures" / "cnpj"


@pytest.fixture
def mock_propfind(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Serve the recorded root and 2026-10 listings in place of the network.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        pytest fixture.

    Returns
    -------
    unittest.mock.MagicMock
        The patched ``propfind`` seam, so a test can inspect the URLs requested.
    """
    dict_bodies = {
        SHARE_ROOT_URL: (PATH_FIXTURES / "propfind_root.xml").read_bytes(),
        f"{SHARE_ROOT_URL}2026-10/": (PATH_FIXTURES / "propfind_month_2026-10.xml").read_bytes(),
    }
    mock = MagicMock(side_effect=lambda str_url, int_depth=1: dict_bodies[str_url])
    monkeypatch.setattr(_share, "propfind", mock)
    return mock


def test_share_root_url_embeds_the_token() -> None:
    """The root URL is the WebDAV endpoint of the token, ending in a slash."""
    str_expected = f"https://arquivos.receitafederal.gov.br/public.php/dav/files/{SHARE_TOKEN}/"
    assert str_expected == SHARE_ROOT_URL


def test_list_reference_months_returns_all_42_months_sorted(mock_propfind: MagicMock) -> None:
    """Every month folder is returned, ascending, without the tarball or the root itself.

    Parameters
    ----------
    mock_propfind : unittest.mock.MagicMock
        The patched ``propfind`` seam.
    """
    list_months = list_reference_months()
    assert (len(list_months), list_months == sorted(list_months)) == (42, True)


def test_list_reference_months_first_and_last_match_the_published_range(
    mock_propfind: MagicMock,
) -> None:
    """The recorded share spans 2023-05 through 2026-10.

    Parameters
    ----------
    mock_propfind : unittest.mock.MagicMock
        The patched ``propfind`` seam.
    """
    list_months = list_reference_months()
    assert (list_months[0], list_months[-1]) == ("2023-05", "2026-10")


def test_latest_reference_month_is_the_newest_published(mock_propfind: MagicMock) -> None:
    """``latest_reference_month`` returns the last sorted month.

    Parameters
    ----------
    mock_propfind : unittest.mock.MagicMock
        The patched ``propfind`` seam.
    """
    assert latest_reference_month() == "2026-10"


def test_latest_reference_month_empty_share_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A share listing no month raises instead of returning ``None`` or an index error.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        pytest fixture.
    """
    mock = MagicMock(return_value=b'<d:multistatus xmlns:d="DAV:"/>')
    monkeypatch.setattr(_share, "propfind", mock)
    with pytest.raises(ValueError, match="no reference month"):
        latest_reference_month()


def test_list_files_returns_the_37_files_of_the_month(mock_propfind: MagicMock) -> None:
    """The month folder itself is excluded; its 37 files remain.

    Parameters
    ----------
    mock_propfind : unittest.mock.MagicMock
        The patched ``propfind`` seam.
    """
    assert len(list_files("2026-10")) == 37


def test_list_files_keeps_name_size_etag_and_last_modified(mock_propfind: MagicMock) -> None:
    """Each file carries the three change-detection properties the share publishes.

    Parameters
    ----------
    mock_propfind : unittest.mock.MagicMock
        The patched ``propfind`` seam.
    """
    list_listed = list_files("2026-10")
    cls_empresas = next(cls_f for cls_f in list_listed if cls_f.str_name == "Empresas0.zip")
    assert (
        cls_empresas.int_size,
        cls_empresas.str_etag,
        cls_empresas.dt_last_modified.isoformat(),
    ) == (570972127, '"51ffd6930af710720929322b11eb1027"', "2026-10-13T22:00:54+00:00")


def test_list_files_unpublished_month_raises_and_names_the_month(
    mock_propfind: MagicMock,
) -> None:
    """A month the share does not hold is an error, never a fallback to another month.

    Parameters
    ----------
    mock_propfind : unittest.mock.MagicMock
        The patched ``propfind`` seam.
    """
    with pytest.raises(ValueError, match="2020-01 is not published"):
        list_files("2020-01")


def test_list_files_unpublished_month_does_not_request_it(mock_propfind: MagicMock) -> None:
    """Only the root is listed: the missing month is never fetched.

    Parameters
    ----------
    mock_propfind : unittest.mock.MagicMock
        The patched ``propfind`` seam.
    """
    with pytest.raises(ValueError, match="not published"):  # one-assert-ok: raises + call count
        list_files("2020-01")
    assert mock_propfind.call_count == 1


@pytest.mark.parametrize(
    "str_month", ["2026-1", "202610", "2026-13", "2026-00", "latest", "", "../x"]
)
def test_list_files_malformed_month_raises_before_any_request(
    str_month: str, mock_propfind: MagicMock
) -> None:
    """A value that is not ``YYYY-MM`` is rejected without touching the network.

    Parameters
    ----------
    str_month : str
        A malformed reference month.
    mock_propfind : unittest.mock.MagicMock
        The patched ``propfind`` seam.
    """
    with pytest.raises(ValueError, match="YYYY-MM"):
        list_files(str_month)


def test_file_url_joins_root_month_and_name() -> None:
    """The URL is ``<root>/<YYYY-MM>/<file>``, the plain-GET form the share serves."""
    assert file_url("2026-10", "Empresas0.zip") == (
        f"https://arquivos.receitafederal.gov.br/public.php/dav/files/{SHARE_TOKEN}"
        "/2026-10/Empresas0.zip"
    )


@pytest.mark.parametrize("str_name", ["", "../Empresas0.zip", "a/b.zip", "..", "."])
def test_file_url_unsafe_name_raises(str_name: str) -> None:
    """A file name that is blank or could leave the month folder is refused.

    Parameters
    ----------
    str_name : str
        An unsafe file name.
    """
    with pytest.raises(ValueError, match="file name"):
        file_url("2026-10", str_name)


def test_file_url_malformed_month_raises() -> None:
    """The month is validated here too, so a bad URL cannot be built."""
    with pytest.raises(ValueError, match="YYYY-MM"):
        file_url("2026-10/..", "Empresas0.zip")


def test_file_url_percent_encodes_the_name() -> None:
    """A name with a space is percent-encoded so the URL stays one token."""
    assert file_url("2026-10", "a b.zip").endswith("/2026-10/a%20b.zip")
