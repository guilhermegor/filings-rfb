"""Parse the RFB's compact ``YYYYMMDD`` date text, where ``00000000`` and empty mean null."""

from __future__ import annotations

import pandas as pd

from filings_rfb._internal.utils.typing import type_checker


__all__ = ["parse_compact_dates"]

_NULL_DATE: str = "00000000"


@type_checker
def parse_compact_dates(series_text: pd.Series) -> pd.Series:
    """Parse ``YYYYMMDD`` text to ``datetime.date``, with ``00000000`` and empty as null.

    Parameters
    ----------
    series_text : pd.Series
        The raw text column.

    Returns
    -------
    pd.Series
        An ``object`` column of ``datetime.date`` and ``None``.

    Raises
    ------
    ValueError
        If a value is neither ``YYYYMMDD`` nor a null marker.
    """
    series_clean = series_text.str.strip().replace({_NULL_DATE: ""})
    series_parsed = pd.to_datetime(series_clean.replace("", pd.NA), format="%Y%m%d")
    return pd.Series(
        [None if pd.isna(dt_value) else dt_value.date() for dt_value in series_parsed],
        index=series_text.index,
        dtype=object,
    )
