"""Unit tests for the Empresas reader and its optional Parquet export."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
import sys
from unittest.mock import MagicMock

import pandas as pd
import pytest

from filings_rfb.ingestion.cnpj.companies import export_companies_parquet, read_companies
from tests.unit.conftest import LIST_PART0_LINES, LIST_PART1_LINES, STR_MONTH


Publish = Callable[[dict[int, list[str]]], MagicMock]
DICT_TEN_PARTS = {0: LIST_PART0_LINES, **{int_part: LIST_PART1_LINES for int_part in range(1, 10)}}


def test_capital_is_an_exact_decimal(fake_share: Publish) -> None:
    """Decimal-comma text becomes the exact Decimal, trailing zeros kept, no float."""
    fake_share(DICT_TEN_PARTS)
    df_all = pd.concat(read_companies(STR_MONTH, 2), ignore_index=True)
    assert df_all["capital_social"].iloc[0] == Decimal("120000000000.00")


def test_capital_keeps_cents_without_rounding(fake_share: Publish) -> None:
    """``1234,50`` is exactly 1234.50."""
    fake_share(DICT_TEN_PARTS)
    df_all = pd.concat(read_companies(STR_MONTH, 2), ignore_index=True)
    assert str(df_all["capital_social"].iloc[1]) == "1234.50"


def test_capital_cells_are_decimal_instances(fake_share: Publish) -> None:
    """No cell is a float."""
    fake_share(DICT_TEN_PARTS)
    df_chunk = next(read_companies(STR_MONTH, 2))
    assert all(isinstance(value, Decimal) for value in df_chunk["capital_social"])


def test_all_ten_parts_are_read(fake_share: Publish) -> None:
    """Part indices 0 through 9 all appear."""
    fake_share(DICT_TEN_PARTS)
    df_all = pd.concat(read_companies(STR_MONTH, 2), ignore_index=True)
    assert sorted(df_all["part_index"].unique().tolist()) == list(range(10))


def test_missing_part_is_an_error(fake_share: Publish) -> None:
    """Nine published parts out of ten fail the read."""
    fake_share({int_part: LIST_PART1_LINES for int_part in range(9)})
    with pytest.raises(FileNotFoundError, match="Empresas9.zip"):
        next(read_companies(STR_MONTH, 2))


def test_export_without_pyarrow_names_the_extra(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A missing pyarrow raises an ImportError that names ``filings-rfb[parquet]``."""
    monkeypatch.setitem(sys.modules, "pyarrow", None)
    with pytest.raises(ImportError, match=r"filings-rfb\[parquet\]"):
        export_companies_parquet(STR_MONTH, tmp_path / "out.parquet")


def test_export_parquet_round_trips_rows_text_and_decimals(
    fake_share: Publish, tmp_path: Path
) -> None:
    """The exported file holds every row, the accented name and the exact capital."""
    pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    fake_share(DICT_TEN_PARTS)
    path_out = export_companies_parquet(STR_MONTH, tmp_path / "sub" / "empresas.parquet", 2)
    cls_table = pq.read_table(path_out)
    assert (
        cls_table.num_rows,
        "CONSTRUÇÕES JOÃO LTDA" in cls_table["razao_social"].to_pylist(),
        Decimal("1234.50") in cls_table["capital_social"].to_pylist(),
    ) == (12, True, True)
