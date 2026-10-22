"""Explicit column typing for DataFrames loaded from a source.

A single place to enforce the project rule *every DataFrame or SQL-to-memory load
must declare its column types* — instead of trusting pandas' inference, which silently
turns a zero-padded code into an int or a mixed column into ``object``. Pass an
``astype`` dict for the plain types plus optional lists for ``date`` / ``datetime``
columns, which need ``to_datetime`` rather than ``astype``.
"""

from __future__ import annotations

import collections
from collections.abc import Sequence
from decimal import Decimal
import functools
from typing import TYPE_CHECKING

import pandas as pd


if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import TypeVar

    _F = TypeVar("_F", bound=Callable[..., object])

    def type_checker(fn: _F) -> _F:
        """Type-only stub — see src/utils/CLAUDE.md."""
else:
    try:
        from filings_rfb._internal.utils.typing import type_checker
    except ModuleNotFoundError:
        from filings_rfb._internal.utils.typing import type_checker


_DTYPE_TEXT = "string"

_FROZENSET_MISSING_TEXT = frozenset({"nan", "none", "<na>"})


@type_checker
def _resolve_text_dtypes(dict_dtypes: dict[str, str]) -> dict[str, str]:
    """Swap ``"str"`` declarations for the NA-safe nullable ``"string"`` dtype.

    Callers keep writing the obvious ``"str"``; this is the single place that knows the
    pandas-major caveat.

    Parameters
    ----------
    dict_dtypes : dict of {str: str}
        The caller's column→dtype mapping.

    Returns
    -------
    dict of {str: str}
        The same mapping with every ``"str"`` replaced by ``"string"``.
    """
    return {
        str_col: (_DTYPE_TEXT if str_dtype == "str" else str_dtype)
        for str_col, str_dtype in dict_dtypes.items()
    }


@type_checker
def _to_decimal(value: object) -> object:
    """Convert one source value to an exact :class:`~decimal.Decimal`.

    Accepts the two forms a lossless pipeline can deliver — text (``"1984223115.42"``, the
    usual shape from CSV or from JSON parsed with ``parse_float=Decimal``) and ``int`` — plus
    ``Decimal`` itself, which passes through untouched. Missing values stay missing.

    A binary ``float`` is **rejected rather than converted**. By the time a float exists the
    source's exact value is already gone, so converting it would launder a lossy value into a
    type that advertises exactness — the silent failure this seam exists to prevent. The fix
    belongs upstream at the parse boundary (``json.loads(..., parse_float=Decimal)``, or
    reading the column as text), never here.

    Parameters
    ----------
    value : object
        One cell from a decimal-typed column.

    Returns
    -------
    object
        A :class:`decimal.Decimal`, or :data:`pandas.NA` for a missing value.

    Raises
    ------
    ValueError
        If ``value`` is a binary ``float`` — precision was already lost upstream.
    """
    if value is pd.NA:
        return pd.NA
    return _decimal_by_type(value)


@functools.singledispatch
@type_checker
def _decimal_by_type(value: object) -> object:
    """Convert anything not handled by a registered type: as text, or NA when it reads empty.

    Parameters
    ----------
    value : object
        One cell from a decimal-typed column.

    Returns
    -------
    object
        A :class:`decimal.Decimal`, or :data:`pandas.NA`.
    """
    str_value = str(value).strip()
    if not str_value or str_value.lower() in _FROZENSET_MISSING_TEXT:
        return pd.NA
    return Decimal(str_value)


@_decimal_by_type.register
@type_checker
def _decimal_from_none(value: None) -> object:
    """Map a missing value to :data:`pandas.NA`.

    Parameters
    ----------
    value : None
        The missing value.

    Returns
    -------
    object
        :data:`pandas.NA`.
    """
    return pd.NA


@_decimal_by_type.register
@type_checker
def _decimal_from_decimal(value: Decimal) -> object:
    """Pass an already-exact Decimal through untouched.

    Parameters
    ----------
    value : Decimal
        The value.

    Returns
    -------
    object
        ``value``.
    """
    return value


@_decimal_by_type.register
@type_checker
def _decimal_from_int(value: int) -> object:
    """Convert an int, which carries no lost precision.

    Parameters
    ----------
    value : int
        The value.

    Returns
    -------
    object
        The converted value.
    """
    return Decimal(value)


@_decimal_by_type.register
@type_checker
def _decimal_from_float(value: float) -> object:
    """Reject a binary float — the source's exact value is already gone.

    ⚠️ NaN is a float, but it means "missing", not "a value we lost precision on": pandas
    uses it as the missing marker in any numeric column, so it must map to NA rather than
    raise, or every blank cell in such a column would fail the load.

    Parameters
    ----------
    value : float
        The rejected value.

    Returns
    -------
    object
        :data:`pandas.NA` for NaN; never returns otherwise.

    Raises
    ------
    ValueError
        For any non-NaN float — precision was already lost upstream.
    """
    if value != value:  # noqa: PLR0124 — NaN is the only value not equal to itself
        return pd.NA
    raise ValueError(
        f"Refusing to convert float {value!r} to Decimal: the source's exact value is "
        "already lost. Parse the source losslessly instead — "
        "json.loads(..., parse_float=Decimal), or read the column as text."
    )


@type_checker
def apply_dtypes(
    df_input: pd.DataFrame,
    dict_dtypes: dict[str, str] | None = None,
    list_date_cols: Sequence[str] | None = None,
    list_datetime_cols: Sequence[str] | None = None,
    list_decimal_cols: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Coerce a DataFrame's columns to declared types, returning a new frame.

    Validation runs first (fail fast): every referenced column must exist, and the
    four column sets must be disjoint. Then, on a copy: the ``astype`` dict is applied,
    ``list_datetime_cols`` are parsed to full timestamps, ``list_date_cols`` to pure
    ``date`` objects, and ``list_decimal_cols`` to exact :class:`decimal.Decimal` values.

    Parameters
    ----------
    df_input : pd.DataFrame
        The source frame (left unmodified — work happens on a copy).
    dict_dtypes : dict of {str: str}, optional
        Column→dtype mapping passed to :meth:`pandas.DataFrame.astype` (e.g. ``"str"``,
        ``"int64"``). A ``"str"`` declaration is normalised to the nullable ``"string"``
        dtype so a missing value stays NA instead of becoming the literal ``"nan"`` on
        pandas 2 — see :data:`_DTYPE_TEXT`. **Do not declare a binary float dtype for an
        ingested source column** — use ``list_decimal_cols`` (see below).
    list_date_cols : sequence of str, optional
        Columns coerced to ``datetime.date`` (date only, no time component).
    list_datetime_cols : sequence of str, optional
        Columns coerced to ``datetime64`` timestamps.
    list_decimal_cols : sequence of str, optional
        Columns coerced to exact :class:`decimal.Decimal` values (``object`` dtype), for any
        number whose fractional part carries meaning — money, volumes, rates, quantities.
        ``float64`` cannot represent most decimal fractions: ``1984223115.42`` is stored as
        ``1984223115.4200000762939453125``, and that loss is **irreversible and silent**,
        surfacing later as a reconciliation that misses by a hair. The source's own scale is
        preserved exactly; no precision is *chosen* here, because choosing one is a
        downstream (warehouse) decision this layer cannot make.

    Returns
    -------
    pd.DataFrame
        A new frame with the requested types applied.

    Raises
    ------
    KeyError
        If any referenced column is absent from ``df_input``.
    ValueError
        If a column appears in more than one of the four sets, a date/datetime column
        cannot be parsed (``to_datetime`` uses ``errors="raise"``), or a decimal column
        already holds a binary ``float`` (see :func:`_to_decimal`).
    """
    dict_dtypes = dict_dtypes or {}
    list_date_cols = list(list_date_cols or [])
    list_datetime_cols = list(list_datetime_cols or [])
    list_decimal_cols = list(list_decimal_cols or [])

    list_referenced = (
        list(dict_dtypes.keys()) + list_date_cols + list_datetime_cols + list_decimal_cols
    )
    _validate_referenced_columns(df_input, list_referenced)

    df_typed = df_input.copy()
    if dict_dtypes:
        df_typed = df_typed.astype(_resolve_text_dtypes(dict_dtypes))

    dict_derived = {
        **{
            str_col: pd.to_datetime(df_typed[str_col], errors="raise")
            for str_col in list_datetime_cols
        },
        **{
            str_col: pd.to_datetime(df_typed[str_col], errors="raise").dt.date
            for str_col in list_date_cols
        },
        **{str_col: df_typed[str_col].map(_to_decimal) for str_col in list_decimal_cols},
    }
    return df_typed.assign(**dict_derived)


@type_checker
def _validate_referenced_columns(  # complexity-ok: two distinct validation faults
    df_input: pd.DataFrame, list_referenced: list[str]
) -> None:
    """Fail fast when a referenced column is absent or claimed by more than one target type.

    Validation is separated from the coercion it guards so each reads as one job.

    Parameters
    ----------
    df_input : pd.DataFrame
        The source frame.
    list_referenced : list of str
        Every column named across the four target-type sets, in declaration order.

    Returns
    -------
    None

    Raises
    ------
    KeyError
        If any referenced column is absent from ``df_input``.
    ValueError
        If a column appears in more than one of the four sets.
    """
    set_missing = {str_col for str_col in list_referenced if str_col not in df_input.columns}
    if set_missing:
        raise KeyError(f"Columns not found in DataFrame: {sorted(set_missing)}")

    cls_counts = collections.Counter(list_referenced)
    set_overlap = {str_col for str_col, int_n in cls_counts.items() if int_n > 1}
    if set_overlap:
        raise ValueError(f"Columns assigned more than one target type: {sorted(set_overlap)}")
