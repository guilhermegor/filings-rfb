"""Unit tests for the Estabelecimentos reader."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import zipfile

import pandas as pd
import pytest

from filings_rfb._internal.utils.compact_dates import parse_compact_dates
from filings_rfb._internal.utils.webdav_client import WebdavEntry
from filings_rfb.ingestion.cnpj import _multipart
from filings_rfb.ingestion.cnpj.establishments import read_establishments


STR_MONTH = "2026-10"


def _row(str_cnpj: str, str_start: str, str_cnae: str, int_cut: int = 8) -> str:
    """Build one 30-field line: split CNPJ, flags, a status date, start date, CNAEs."""
    list_head = [
        str_cnpj[:int_cut],
        str_cnpj[int_cut:12],
        str_cnpj[12:],
        "1",
        "FANTASIA",
        "02",
        str_start,
    ]
    list_mid = ["", "", "", str_start, "6422100", str_cnae]
    list_fields = [f'"{str_val}"' for str_val in list_head + list_mid]
    list_fields += ['"x"'] * 6 + ['"SP"'] + ['""'] * 9 + ['"00000000"']
    return ";".join(list_fields)


LIST_LINES = [
    _row("00000000000191", "20001231", "6422100"),
    _row("11222333000181", "00000000", "4711301,4711302,4712100"),
    _row("00000001000100", "", "1"),
    _row("11222333000181", "", "1", int_cut=7),
]


@pytest.fixture
def share(  # complexity-ok: fixture factory with a nested fake
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Publish ten tiny Estabelecimentos parts, each holding the same three rows."""
    list_names = [f"Estabelecimentos{int_part}.zip" for int_part in range(10)]
    for str_name in list_names:
        with zipfile.ZipFile(tmp_path / f"src_{str_name}", "w") as cls_zip:
            cls_zip.writestr("K.ESTABELE", "\n".join(LIST_LINES))
    list_entries = [
        WebdavEntry(str_name, False, 1, '"e"', datetime.now(timezone.utc))
        for str_name in list_names
    ]
    monkeypatch.setattr(_multipart, "list_files", lambda _str_month: list_entries)

    def fake_download(str_url: str, path_dest: Path) -> tuple[Path, str]:
        path_dest.write_bytes((tmp_path / f"src_{str_url.rsplit('/', 1)[-1]}").read_bytes())
        return path_dest, '"e"'

    monkeypatch.setattr(_multipart, "download_file_streaming", fake_download)


@pytest.fixture
def df_all(share: None) -> pd.DataFrame:
    """All chunks concatenated."""
    return pd.concat(read_establishments(STR_MONTH, 2), ignore_index=True)


def test_full_cnpj_is_assembled(df_all: pd.DataFrame) -> None:
    """Basic + order + check digits make the 14-character CNPJ."""
    assert df_all["cnpj_completo"].iloc[1] == "11222333000181"


def test_cnpj_validity_rejects_misaligned_parts(df_all: pd.DataFrame) -> None:
    """A 7+5+2 split that concatenates to a valid CNPJ is still not valid."""
    assert not df_all["cnpj_valido"].iloc[3]


def test_cnpj_validity_flags_the_bad_row(df_all: pd.DataFrame) -> None:
    """Valid, valid, invalid in part 0."""
    assert df_all["cnpj_valido"].iloc[:3].tolist() == [True, True, False]


def test_zero_and_empty_dates_are_null(df_all: pd.DataFrame) -> None:
    """``00000000`` and empty become null; a real date is a ``date``."""
    series = df_all["data_inicio_atividade"].iloc[:3]
    assert (series.iloc[0], series.iloc[1:].isna().all()) == (date(2000, 12, 31), True)


def test_secondary_cnaes_stay_text(df_all: pd.DataFrame) -> None:
    """The comma list is kept as one string."""
    assert df_all["cnae_fiscal_secundaria"].iloc[1] == "4711301,4711302,4712100"


def test_all_ten_parts_are_read(df_all: pd.DataFrame) -> None:
    """Part indices 0 through 9 all appear."""
    assert sorted(df_all["part_index"].unique().tolist()) == list(range(10))


@pytest.mark.parametrize("str_bad", ["2026XXYY", "2020101", "202011", "202010011"])
def test_bad_date_is_an_error(str_bad: str) -> None:
    """A value that is not exactly eight digits is raised, never parsed or nulled."""
    with pytest.raises(ValueError, match=str_bad):
        parse_compact_dates(pd.Series([str_bad]))


def test_missing_part_is_an_error(share: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """A part the share does not list fails the read."""
    monkeypatch.setattr(_multipart, "list_files", lambda _str_month: [])
    with pytest.raises(FileNotFoundError, match="Estabelecimentos0.zip"):
        next(read_establishments(STR_MONTH, 2))
