"""Unit tests for the Simples reader (single-file mode of the shared iterator)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from functools import partial
from pathlib import Path
from unittest.mock import MagicMock
import zipfile

import pandas as pd
import pytest

from filings_rfb._internal.utils.webdav_client import WebdavEntry
from filings_rfb.ingestion.cnpj import _multipart
from filings_rfb.ingestion.cnpj.simples import read_simples


STR_MONTH = "2026-10"
LIST_LINES = [
    '"00000006";"N";"20180101";"20191231";"N";"00000000";"00000000"',
    '"00000007";"S";"20200301";"00000000";"S";"20210101";"00000000"',
    '"00000008";"N";"00000000";"00000000";"N";"00000000";"00000000"',
]


def _copy_zip(path_src: Path, str_url: str, path_dest: Path) -> tuple[Path, str]:
    """Fake downloader: copy the prepared archive and return a fixed ETag.

    Parameters
    ----------
    path_src : pathlib.Path
        The prepared archive.
    str_url : str
        The requested URL (unused).
    path_dest : pathlib.Path
        Where the reader wants the download.

    Returns
    -------
    tuple of (pathlib.Path, str)
        The destination and the ETag.
    """
    path_dest.write_bytes(path_src.read_bytes())
    return path_dest, '"e"'


def _publish(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, list_lines: list[str]) -> MagicMock:
    """Publish ``Simples.zip`` (one member of ``list_lines``) on a fake share.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        pytest fixture.
    tmp_path : pathlib.Path
        Where the fake archive lives.
    list_lines : list of str
        The CSV rows.

    Returns
    -------
    unittest.mock.MagicMock
        The patched downloader.
    """
    path_src = tmp_path / "src.zip"
    with zipfile.ZipFile(path_src, "w") as cls_zip:
        cls_zip.writestr("F.K03200$W.SIMPLES.CSV.D61010", "\n".join(list_lines).encode("latin-1"))
    list_entries = [WebdavEntry("Simples.zip", False, 1, '"e"', datetime.now(timezone.utc))]
    monkeypatch.setattr(_multipart, "list_files", lambda _str_month: list_entries)

    mock_download = MagicMock(side_effect=partial(_copy_zip, path_src))
    monkeypatch.setattr(_multipart, "download_file_streaming", mock_download)
    return mock_download


@pytest.fixture
def df_simples(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pd.DataFrame:
    """Read the three-row fixture in chunks of two.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        pytest fixture.
    tmp_path : pathlib.Path
        pytest fixture.

    Returns
    -------
    pd.DataFrame
        All chunks concatenated.
    """
    _publish(monkeypatch, tmp_path, LIST_LINES)
    return pd.concat(read_simples(STR_MONTH, 2), ignore_index=True)


def test_options_are_booleans(df_simples: pd.DataFrame) -> None:
    """S/N become True/False."""
    assert df_simples["opcao_pelo_simples"].tolist() == [False, True, False]


def test_mei_option_is_boolean(df_simples: pd.DataFrame) -> None:
    """The MEI option is typed the same way."""
    assert df_simples["opcao_pelo_mei"].tolist() == [False, True, False]


def test_dates_are_dates(df_simples: pd.DataFrame) -> None:
    """YYYYMMDD becomes a ``datetime.date``."""
    assert df_simples["data_opcao_simples"].iloc[0] == date(2018, 1, 1)


def test_sentinel_date_is_null(df_simples: pd.DataFrame) -> None:
    """00000000 is null, not a stringified date."""
    assert pd.isna(df_simples["data_opcao_simples"].iloc[2])


def test_open_ended_option_has_null_end(df_simples: pd.DataFrame) -> None:
    """An option still in force keeps its start and has no end date."""
    row = df_simples.iloc[1]
    assert (row["data_opcao_simples"], pd.isna(row["data_exclusao_simples"])) == (
        date(2020, 3, 1),
        True,
    )


def test_cnpj_basico_stays_text_with_leading_zeros(df_simples: pd.DataFrame) -> None:
    """The 8-digit root keeps its zeros."""
    assert df_simples["cnpj_basico"].iloc[0] == "00000006"


def test_single_archive_is_stamped_part_zero(df_simples: pd.DataFrame) -> None:
    """One un-numbered archive gives part_index 0 on every row."""
    assert df_simples["part_index"].tolist() == [0, 0, 0]


def test_downloads_the_unnumbered_archive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The single download seam is asked for ``Simples.zip``."""
    mock_download = _publish(monkeypatch, tmp_path, LIST_LINES)
    list(read_simples(STR_MONTH))
    assert mock_download.call_args.args[0].endswith("/Simples.zip")


def test_unpublished_archive_is_an_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A month without Simples.zip fails instead of yielding nothing."""
    _publish(monkeypatch, tmp_path, LIST_LINES)
    monkeypatch.setattr(_multipart, "list_files", lambda _str_month: [])
    with pytest.raises(FileNotFoundError, match=r"Simples\.zip"):
        next(read_simples(STR_MONTH))


def test_unknown_option_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A flag other than S/N is an error, never a silent null."""
    _publish(monkeypatch, tmp_path, ['"00000006";"X";"20180101";"00000000";"N";"0";"0"'])
    with pytest.raises(ValueError, match="expected 'S' or 'N'"):
        next(read_simples(STR_MONTH))
