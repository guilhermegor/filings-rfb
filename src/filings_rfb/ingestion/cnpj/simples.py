"""Read the RFB CNPJ ``Simples`` dataset (Simples Nacional and MEI options), chunk by chunk.

``Simples.zip`` is one un-numbered archive whose member inflates to ~3.2 GB, so
:func:`read_simples` yields typed DataFrames through the shared multi-part iterator in its
single-file mode. The ``S``/``N`` options become booleans and the ``YYYYMMDD`` dates become
``datetime.date``; the RFB's ``00000000`` (and blank) sentinel date means "no date" and is
read as null, never as a stringified date.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pandas as pd

from filings_rfb._internal.config.contracts import CNPJ_SIMPLES
from filings_rfb._internal.utils.dtypes import apply_dtypes
from filings_rfb._internal.utils.typing import type_checker
from filings_rfb.ingestion.cnpj._multipart import DEFAULT_CHUNK_ROWS, iter_part_chunks


__all__ = ["read_simples"]

_PREFIX: str = "Simples"
_BOOL_COLS: tuple[str, ...] = ("opcao_pelo_simples", "opcao_pelo_mei")
_DATE_COLS: tuple[str, ...] = (
    "data_opcao_simples",
    "data_exclusao_simples",
    "data_opcao_mei",
    "data_exclusao_mei",
)
_DTYPES: dict[str, str] = {"cnpj_basico": "str"}
_SENTINELS: tuple[str, ...] = ("00000000", "")
_DICT_FLAGS: dict[str, bool] = {"S": True, "N": False}


@type_checker
def read_simples(
    str_month: str,
    int_chunk_rows: int = DEFAULT_CHUNK_ROWS,
    path_workdir: Path | None = None,
) -> Iterator[pd.DataFrame]:
    """Yield the ``Simples`` rows of a reference month, one typed DataFrame per chunk.

    Parameters
    ----------
    str_month : str
        The reference month, ``YYYY-MM``.
    int_chunk_rows : int, optional
        Rows per chunk, by default 500,000.
    path_workdir : pathlib.Path, optional
        Directory to keep the downloaded ZIP in; ``None`` uses a temporary one.

    Returns
    -------
    Iterator[pd.DataFrame]
        ``cnpj_basico`` as text, the two options as nullable booleans, the four dates as
        ``datetime.date`` (null for the ``00000000`` sentinel), plus the provenance columns,
        ``source_etag`` and ``part_index`` (always 0: there is one archive).

    Raises
    ------
    FileNotFoundError
        If ``Simples.zip`` is not published for the month (raised on first iteration).
    ValueError
        If an option is neither ``S`` nor ``N``, or a date is not ``YYYYMMDD``.
    """
    return iter_part_chunks(
        str_month,
        _PREFIX,
        CNPJ_SIMPLES,
        _DTYPES,
        int_chunk_rows=int_chunk_rows,
        path_workdir=path_workdir,
        fn_prepare=_type_options_and_dates,
        bool_single_file=True,
    )


@type_checker
def _type_options_and_dates(df_chunk: pd.DataFrame) -> pd.DataFrame:
    """Turn the ``S``/``N`` options into booleans and the ``YYYYMMDD`` dates into dates.

    Parameters
    ----------
    df_chunk : pd.DataFrame
        A named raw (all-text) chunk.

    Returns
    -------
    pd.DataFrame
        A copy with the option columns as nullable ``boolean`` and the date columns typed
        through ``apply_dtypes``.
    """
    df_flags = df_chunk.assign(
        **{str_col: _flags_to_boolean(df_chunk[str_col]) for str_col in _BOOL_COLS},
        **{
            str_col: df_chunk[str_col].mask(df_chunk[str_col].isin(_SENTINELS))
            for str_col in _DATE_COLS
        },
    )
    return apply_dtypes(df_flags, list_date_cols=_DATE_COLS)


@type_checker
def _flags_to_boolean(series_flag: pd.Series) -> pd.Series:
    """Map ``S``/``N`` text to a nullable boolean series, rejecting anything else.

    Parameters
    ----------
    series_flag : pd.Series
        The raw option column.

    Returns
    -------
    pd.Series
        ``True`` for ``S``, ``False`` for ``N``.

    Raises
    ------
    ValueError
        If a value is neither ``S`` nor ``N``.
    """
    series_bool = series_flag.map(_DICT_FLAGS)
    if series_bool.isna().any():
        list_bad = sorted(series_flag[series_bool.isna()].unique().tolist())
        raise ValueError(f"{series_flag.name}: expected 'S' or 'N', got {list_bad}")
    return series_bool.astype("boolean")
