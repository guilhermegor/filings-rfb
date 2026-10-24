"""Unit tests for the Socios reader: masked documents, qualification codes, null sentinel."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
import zipfile

import pandas as pd
import pytest

from filings_rfb._internal.config.contracts import COLUMNS_PARTNERS
from filings_rfb._internal.utils.webdav_client import WebdavEntry
from filings_rfb.ingestion.cnpj import _multipart
from filings_rfb.ingestion.cnpj.partners import read_partners
from tests.unit.conftest import STR_MONTH


LIST_PART0_LINES = [
    '"11222333";"1";"HOLDING SA";"11222333000181";"22";"20100305";"";"***000000**";"";"00";"0"',
    '"07396865";"2";"GERSON HOFFMANN";"***240659**";"49";"20050518";"";"***000000**";"";"00";"6"',
    '"07396865";"3";"JOHN DOE";"00000000000";"37";"20180101";"249";"***123456**";"MARIA";"05";"3"',
]
LIST_PART1_LINES = [
    '"00000009";"2";"ANA";"***111222**";"49";"20200202";"";"***000000**";"";"00";"2"',
]


@pytest.fixture
def fake_share(  # complexity-ok: fixture factory with a nested fake
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Callable[[dict[int, list[str]]], MagicMock]:
    """Patch the catalogue and downloader so ``Socios`` parts come from tiny local ZIPs.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        pytest fixture.
    tmp_path : pathlib.Path
        pytest fixture; the fake archives live here.

    Returns
    -------
    collections.abc.Callable
        ``publish({part: CSV lines})`` registers the published parts.
    """

    def publish(  # complexity-ok: builds the fake share
        dict_parts: dict[int, list[str]],
    ) -> MagicMock:
        dict_paths = {}
        for int_part, list_lines in dict_parts.items():
            path_zip = tmp_path / f"src_{int_part}.zip"
            with zipfile.ZipFile(path_zip, "w") as cls_zip:
                cls_zip.writestr("K3241.K03200Y0.D61010.SOCIOCSV", "\n".join(list_lines))
            dict_paths[f"Socios{int_part}.zip"] = path_zip
        list_entries = [
            WebdavEntry(str_name, False, 1, f'"etag-{str_name}"', datetime.now(timezone.utc))
            for str_name in dict_paths
        ]
        monkeypatch.setattr(_multipart, "list_files", lambda _str_month: list_entries)

        def fake_download(str_url: str, path_dest: Path) -> tuple[Path, str]:
            str_name = str_url.rsplit("/", 1)[-1]
            path_dest.write_bytes(dict_paths[str_name].read_bytes())
            return path_dest, f'"etag-{str_name}"'

        mock_download = MagicMock(side_effect=fake_download)
        monkeypatch.setattr(_multipart, "download_file_streaming", mock_download)
        return mock_download

    return publish


@pytest.fixture
def df_partners(fake_share: Callable[[dict[int, list[str]]], MagicMock]) -> pd.DataFrame:
    """Read all ten fake parts (part 0 has the three partner types) into one frame.

    Parameters
    ----------
    fake_share : collections.abc.Callable
        The share fixture.

    Returns
    -------
    pd.DataFrame
        The concatenated chunks.
    """
    fake_share({0: LIST_PART0_LINES, **{int_part: LIST_PART1_LINES for int_part in range(1, 10)}})
    return pd.concat(read_partners(STR_MONTH, 2), ignore_index=True)


def test_columns_are_renamed_to_qualification_not_education(df_partners: pd.DataFrame) -> None:
    """The published columns carry qualification names; no ``education`` column survives."""
    assert list(df_partners.columns[:11]) == list(COLUMNS_PARTNERS)


def test_masked_individual_cpf_is_kept_verbatim(df_partners: pd.DataFrame) -> None:
    """``***240659**`` is never unmasked, reformatted or guessed."""
    assert df_partners["documento_socio"].iloc[1] == "***240659**"


def test_legal_entity_cnpj_is_kept_in_full(df_partners: pd.DataFrame) -> None:
    """A type-1 partner's CNPJ arrives unmasked and stays as published (no punctuation)."""
    assert df_partners["documento_socio"].iloc[0] == "11222333000181"


def test_no_representative_sentinel_becomes_null(df_partners: pd.DataFrame) -> None:
    """``***000000**`` in the representative CPF means "none" and is null."""
    assert df_partners["documento_representante"].iloc[:2].isna().tolist() == [True, True]


def test_real_masked_representative_cpf_is_kept(df_partners: pd.DataFrame) -> None:
    """Only the all-zero sentinel is nulled; a real masked representative CPF is verbatim."""
    assert df_partners["documento_representante"].iloc[2] == "***123456**"


def test_partner_document_with_zero_mask_is_not_nulled(fake_share: Callable) -> None:
    """The sentinel rule applies to the representative only, never to the partner's own CPF."""
    str_line = '"1";"2";"X";"***000000**";"49";"20200101";"";"***000000**";"";"00";"1"'
    fake_share({int_part: [str_line] for int_part in range(10)})
    df_chunk = next(read_partners(STR_MONTH, 2))
    assert df_chunk["documento_socio"].iloc[0] == "***000000**"


def test_qualification_codes_stay_text_with_leading_zeros(df_partners: pd.DataFrame) -> None:
    """Codes are join keys to ``Qualificacoes`` (text), so ``00``/``05`` keep their zero."""
    assert df_partners["qualificacao_representante"].iloc[[0, 2]].tolist() == ["00", "05"]


def test_partner_qualification_matches_lookup_code_format(df_partners: pd.DataFrame) -> None:
    """Partner qualification is the two-character code, ready to join to ``Qualificacoes``."""
    assert df_partners["qualificacao_socio"].iloc[:3].tolist() == ["22", "49", "37"]


def test_partner_types_one_two_three_are_read(df_partners: pd.DataFrame) -> None:
    """Legal entity, individual and foreign partners all come through."""
    assert df_partners["tipo_socio"].iloc[:3].tolist() == ["1", "2", "3"]


def test_provenance_columns_are_stamped(df_partners: pd.DataFrame) -> None:
    """Rows carry the part index, ranging over all ten parts."""
    assert sorted(df_partners["part_index"].unique().tolist()) == list(range(10))


def test_missing_part_is_an_error(fake_share: Callable) -> None:
    """Nine published parts out of ten fail the read."""
    fake_share({int_part: LIST_PART1_LINES for int_part in range(9)})
    with pytest.raises(FileNotFoundError, match="Socios9.zip"):
        next(read_partners(STR_MONTH, 2))
