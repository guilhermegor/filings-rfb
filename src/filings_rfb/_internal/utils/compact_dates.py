"""Parse the RFB's compact ``YYYYMMDD`` date text, where ``00000000`` and empty mean null."""

from __future__ import annotations

import pandas as pd

from filings_rfb._internal.utils.typing import type_checker


__all__ = ["parse_compact_dates"]

_NULL_DATE: str = "00000000"


@type_checker
def parse_compact_dates(series_text: pd.Series) -> pd.Series:
    """Parse strict ``YYYYMMDD`` text to ``datetime.date``.

    The sentinels ``00000000`` and the empty string (after stripping) become null. Every other
    value must be exactly eight digits and a real calendar date: ``pandas`` alone would
    silently accept ``2020101`` or ``202011`` as a shorter format, so the shape is checked first.

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
        If a value is neither eight digits forming a real date nor a null marker; the message
        names (up to five of) the offending values.
    """
    series_clean = series_text.str.strip().replace({_NULL_DATE: ""})
    series_bad = series_clean[(series_clean != "") & ~series_clean.str.fullmatch(r"\d{8}")]
    if not series_bad.empty:
        raise ValueError(f"not YYYYMMDD: {sorted(set(series_bad))[:5]}")
    series_parsed = pd.to_datetime(series_clean.replace("", pd.NA), format="%Y%m%d")
    return pd.Series(
        [None if pd.isna(dt_value) else dt_value.date() for dt_value in series_parsed],
        index=series_text.index,
        dtype=object,
    )
