"""Unit tests for the shared multi-part chunked reader (no network, tiny fake ZIPs)."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import MagicMock

import pandas as pd
import pytest

from filings_rfb._internal.config.contracts import CNPJ_COMPANIES, ContractError
from filings_rfb.ingestion.cnpj import _multipart
from filings_rfb.ingestion.cnpj._multipart import iter_part_chunks
from tests.unit.conftest import LIST_PART0_LINES, LIST_PART1_LINES, STR_MONTH


DICT_DTYPES = {str_col: "str" for str_col in CNPJ_COMPANIES.tuple_required}
Publish = Callable[[dict[int, list[str]]], MagicMock]


def _read(int_chunk_rows: int, tuple_parts: tuple[int, ...] = (0, 1)) -> list[pd.DataFrame]:
    """Drain the iterator over the given parts.

    Parameters
    ----------
    int_chunk_rows : int
        Rows per chunk.
    tuple_parts : tuple of int, optional
        The parts to read.

    Returns
    -------
    list of pd.DataFrame
        Every chunk.
    """
    return list(
        iter_part_chunks(
            STR_MONTH,
            "Empresas",
            CNPJ_COMPANIES,
            DICT_DTYPES,
            int_chunk_rows=int_chunk_rows,
            tuple_parts=tuple_parts,
        )
    )


def test_chunks_split_at_the_requested_row_count(fake_share: Publish) -> None:
    """Part 0 has three rows: chunks of two give 2 + 1, then part 1 gives 1."""
    fake_share({0: LIST_PART0_LINES, 1: LIST_PART1_LINES})
    assert [len(df_chunk) for df_chunk in _read(2)] == [2, 1, 1]


def test_part_index_and_etag_are_stamped_per_part(fake_share: Publish) -> None:
    """Every row carries the part it came from and that archive's ETag."""
    fake_share({0: LIST_PART0_LINES, 1: LIST_PART1_LINES})
    df_all = pd.concat(_read(2), ignore_index=True)
    assert df_all[["part_index", "source_etag"]].drop_duplicates().to_numpy().tolist() == [
        [0, '"etag-Empresas0.zip"'],
        [1, '"etag-Empresas1.zip"'],
    ]


def test_all_chunks_of_one_read_share_one_run_id(fake_share: Publish) -> None:
    """The ingestion run id is minted once per read, not per chunk."""
    fake_share({0: LIST_PART0_LINES, 1: LIST_PART1_LINES})
    assert len(set(pd.concat(_read(2))["ingestion_run_id"])) == 1


def test_latin1_accents_round_trip(fake_share: Publish) -> None:
    """A latin-1 accented name is decoded, not mangled."""
    fake_share({0: LIST_PART0_LINES, 1: LIST_PART1_LINES})
    assert "CONSTRUÇÕES JOÃO LTDA" in pd.concat(_read(2))["razao_social"].tolist()


def test_missing_part_raises_instead_of_skipping(fake_share: Publish) -> None:
    """Asking for part 1 when only part 0 is published is an error."""
    fake_share({0: LIST_PART0_LINES})
    with pytest.raises(FileNotFoundError, match="Empresas1.zip"):
        _read(2)


def test_missing_part_downloads_nothing(fake_share: Publish) -> None:
    """The completeness check runs before any download starts."""
    mock_download = fake_share({0: LIST_PART0_LINES})
    with pytest.raises(FileNotFoundError):
        _read(2)
    assert mock_download.call_count == 0


def test_non_positive_chunk_size_is_rejected(fake_share: Publish) -> None:
    """A zero chunk size fails fast instead of reading everything at once."""
    fake_share({0: LIST_PART0_LINES, 1: LIST_PART1_LINES})
    with pytest.raises(ValueError, match="int_chunk_rows"):
        _read(0)


def test_wrong_column_count_raises_contract_error(fake_share: Publish) -> None:
    """A part with an extra field is rejected, never silently re-indexed."""
    fake_share({0: ['"1";"A";"2";"3";"4,00";"5";"";"EXTRA"']})
    with pytest.raises(ContractError, match="expected 7"):
        _read(2, (0,))


def test_temporary_workdir_is_cleaned_after_the_read(fake_share: Publish) -> None:
    """Without a workdir the downloaded archive does not outlive the read."""
    mock_download = fake_share({0: LIST_PART0_LINES, 1: LIST_PART1_LINES})
    _read(2)
    assert not mock_download.call_args.args[1].exists()


def test_module_exposes_ten_default_parts() -> None:
    """The default part set is 0 through 9."""
    assert tuple(range(10)) == _multipart.DEFAULT_PARTS
