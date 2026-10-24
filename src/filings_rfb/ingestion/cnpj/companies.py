"""Read the RFB CNPJ ``Empresas`` dataset, chunk by chunk, and export it to Parquet.

``Empresas0.zip`` .. ``Empresas9.zip`` inflate to ~330 MB each, so :func:`read_companies`
yields typed DataFrames (one per part chunk) instead of one frame. ``capital_social`` is parsed
from the source's decimal-comma text (``"120000000000,00"``) to an exact ``Decimal`` with no
rounding. :func:`export_companies_parquet` drains the same iterator into one Parquet file for
lazy querying (DuckDB, Polars ``scan_parquet``) on the consumer's side; it needs the optional
``filings-rfb[parquet]`` extra.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pandas as pd

from filings_rfb._internal.config.contracts import CNPJ_COMPANIES
from filings_rfb._internal.utils.parquet_writer import ParquetChunkWriter
from filings_rfb._internal.utils.typing import type_checker
from filings_rfb.ingestion.cnpj._multipart import DEFAULT_CHUNK_ROWS, iter_part_chunks


__all__ = ["export_companies_parquet", "read_companies"]

_PREFIX: str = "Empresas"
_COL_CAPITAL: str = "capital_social"
_DECIMAL_COLS: tuple[str, ...] = (_COL_CAPITAL,)
_DTYPES: dict[str, str] = {
    str_col: "str" for str_col in CNPJ_COMPANIES.tuple_required if str_col != _COL_CAPITAL
}
_CAPITAL_SCALE: int = 2


@type_checker
def read_companies(
    str_month: str,
    int_chunk_rows: int = DEFAULT_CHUNK_ROWS,
    path_workdir: Path | None = None,
) -> Iterator[pd.DataFrame]:
    """Yield the ``Empresas`` rows of a reference month, one typed DataFrame per chunk.

    Parameters
    ----------
    str_month : str
        The reference month, ``YYYY-MM``.
    int_chunk_rows : int, optional
        Rows per chunk, by default 500,000.
    path_workdir : pathlib.Path, optional
        Directory to keep the downloaded ZIPs in; ``None`` uses a temporary one.

    Returns
    -------
    Iterator[pd.DataFrame]
        Columns are the seven published ones (text, with ``capital_social`` as ``Decimal``)
        plus the provenance columns, ``source_etag`` and ``part_index``.

    Raises
    ------
    FileNotFoundError
        If any of the ten parts is not published for the month (raised on first iteration).
    """
    return iter_part_chunks(
        str_month,
        _PREFIX,
        CNPJ_COMPANIES,
        _DTYPES,
        int_chunk_rows=int_chunk_rows,
        path_workdir=path_workdir,
        list_decimal_cols=_DECIMAL_COLS,
        fn_prepare=_decimal_point_capital,
    )


@type_checker
def export_companies_parquet(
    str_month: str,
    path_dest: Path,
    int_chunk_rows: int = DEFAULT_CHUNK_ROWS,
    path_workdir: Path | None = None,
) -> Path:
    """Write the ``Empresas`` of a reference month to one Parquet file, chunk by chunk.

    ``capital_social`` is stored as ``decimal128(38, 2)``; a value with more fractional digits
    raises instead of being rounded. The file is only created once the first chunk is read.

    Parameters
    ----------
    str_month : str
        The reference month, ``YYYY-MM``.
    path_dest : pathlib.Path
        The Parquet file to write; its parent is created.
    int_chunk_rows : int, optional
        Rows per chunk, by default 500,000.
    path_workdir : pathlib.Path, optional
        Directory to keep the downloaded ZIPs in; ``None`` uses a temporary one.

    Returns
    -------
    pathlib.Path
        ``path_dest``.

    Raises
    ------
    ImportError
        If ``pyarrow`` is missing; install the ``filings-rfb[parquet]`` extra.
    """
    with ParquetChunkWriter(path_dest, {_COL_CAPITAL: _CAPITAL_SCALE}) as cls_writer:
        for df_chunk in read_companies(str_month, int_chunk_rows, path_workdir):
            cls_writer.write(df_chunk)
    return path_dest


@type_checker
def _decimal_point_capital(df_chunk: pd.DataFrame) -> pd.DataFrame:
    """Turn the decimal-comma capital text into decimal-point text (still a string).

    Parameters
    ----------
    df_chunk : pd.DataFrame
        A named raw chunk.

    Returns
    -------
    pd.DataFrame
        A copy whose ``capital_social`` uses ``.``; the exact ``Decimal`` is built from this
        text by ``apply_dtypes``, never through a float.
    """
    return df_chunk.assign(**{_COL_CAPITAL: df_chunk[_COL_CAPITAL].str.replace(",", ".")})
