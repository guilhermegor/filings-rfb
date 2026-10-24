"""Read the RFB CNPJ ``Estabelecimentos`` dataset, chunk by chunk.

``Estabelecimentos0.zip`` .. ``Estabelecimentos9.zip`` are the largest CNPJ files (2+ GB each
zipped), so :func:`read_establishments` yields typed DataFrames, one per part chunk. Each row
gains ``cnpj_completo`` (the 14 characters ``cnpj_basico + cnpj_ordem + cnpj_dv``) and
``cnpj_valido`` (its check digits, alphanumeric-aware, via ``br_identifiers``). The three date
columns become ``datetime.date`` with the source's ``00000000`` and empty values as null.
``cnae_fiscal_secundaria`` stays the comma-separated text (bronze: no explode).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pandas as pd

from filings_rfb._internal.config.contracts import CNPJ_ESTABLISHMENTS
from filings_rfb._internal.utils.br_identifiers import is_valid_cnpj
from filings_rfb._internal.utils.compact_dates import parse_compact_dates
from filings_rfb._internal.utils.typing import type_checker
from filings_rfb.ingestion.cnpj._multipart import DEFAULT_CHUNK_ROWS, iter_part_chunks


__all__ = ["read_establishments"]

_PREFIX: str = "Estabelecimentos"
_LEN_BASICO: int = 8
_LEN_ORDEM: int = 4
_LEN_DV: int = 2
_DATE_COLS: tuple[str, ...] = (
    "data_situacao_cadastral",
    "data_inicio_atividade",
    "data_situacao_especial",
)
_DTYPES: dict[str, str] = {
    str_col: "str" for str_col in CNPJ_ESTABLISHMENTS.tuple_required if str_col not in _DATE_COLS
}


@type_checker
def read_establishments(
    str_month: str,
    int_chunk_rows: int = DEFAULT_CHUNK_ROWS,
    path_workdir: Path | None = None,
) -> Iterator[pd.DataFrame]:
    """Yield the ``Estabelecimentos`` rows of a reference month, one typed DataFrame per chunk.

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
        The 30 published columns (text, the three date columns as ``datetime.date`` or null),
        ``cnpj_completo``, ``cnpj_valido`` and the provenance columns, ``source_etag`` and
        ``part_index``.

    Raises
    ------
    FileNotFoundError
        If any of the ten parts is not published for the month (raised on first iteration).
    ValueError
        If a date is neither ``YYYYMMDD`` nor a null marker.
    """
    return iter_part_chunks(
        str_month,
        _PREFIX,
        CNPJ_ESTABLISHMENTS,
        _DTYPES,
        int_chunk_rows=int_chunk_rows,
        path_workdir=path_workdir,
        fn_prepare=_assemble_cnpj_and_dates,
    )


@type_checker
def _assemble_cnpj_and_dates(df_chunk: pd.DataFrame) -> pd.DataFrame:
    """Derive the full CNPJ and its validity, and parse the three date columns.

    Parameters
    ----------
    df_chunk : pd.DataFrame
        A named raw (all-text) chunk.

    Returns
    -------
    pd.DataFrame
        A copy with ``cnpj_completo``, ``cnpj_valido`` and the date columns as ``date``/null.
    """
    series_cnpj = df_chunk["cnpj_basico"] + df_chunk["cnpj_ordem"] + df_chunk["cnpj_dv"]
    df_out = df_chunk.assign(
        cnpj_completo=series_cnpj,
        cnpj_valido=_parts_aligned(df_chunk) & series_cnpj.map(is_valid_cnpj),
    )
    for str_col in _DATE_COLS:
        df_out[str_col] = parse_compact_dates(df_out[str_col])
    return df_out


@type_checker
def _parts_aligned(df_chunk: pd.DataFrame) -> pd.Series:
    """Flag rows whose CNPJ parts are exactly 8, 4 and 2 characters wide.

    Parameters
    ----------
    df_chunk : pd.DataFrame
        A named raw (all-text) chunk.

    Returns
    -------
    pd.Series
        ``True`` where a misaligned split cannot pass for a valid 14-character CNPJ.
    """
    return (
        (df_chunk["cnpj_basico"].str.len() == _LEN_BASICO)
        & (df_chunk["cnpj_ordem"].str.len() == _LEN_ORDEM)
        & (df_chunk["cnpj_dv"].str.len() == _LEN_DV)
    )
