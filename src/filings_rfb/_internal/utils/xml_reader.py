"""Robust XML reading into a typed, contract-validated DataFrame (blueprintx#117).

The XML sibling of :mod:`utils.tabular_reader`, sharing its contract + dtype tail
(:class:`~utils.tabular_reader.FileContract`, :class:`~utils.tabular_reader.ContractError`,
:func:`~utils.dtypes.apply_dtypes`) so an XML source and a workbook/CSV source cannot diverge
on validation or typing.

- One repeating **row anchor** element yields one row each; every other declared column is
  resolved **relative to that row** by an ordered tuple of alternative paths — first match
  wins, so a column present under different sub-blocks in the same document still lands in one
  place.
- A path segment matches by **local name**, ignoring any XML namespace, so a namespace-version
  bump in the source does not break the reader.
- A single-level ``*`` wildcard segment matches *any* child at that level — covers every
  type-specific sub-block a schema declares (and any the publisher adds later) without listing
  them.
- A path may end in ``@name`` to read an **attribute** instead of element text. This is not a
  cosmetic option: in ISO-20022-shaped documents a money value's currency lives in an attribute
  of the amount element, so a text-only reader silently drops the unit of every monetary
  column. Measured in the proving ground: 142,164 prices shipped with no currency, and the
  column still looked fully populated.
- A path starting with ``/`` is resolved once against the **document root** instead of the row,
  and that single value is **broadcast** to every extracted row — for a document-level field
  (a report id, a as-of date) that has no reason to repeat per row in the source.
- ``str_row_filter`` keeps only row-anchor elements where a given relative path resolves
  (checked by presence, not value), applied **before** contract validation — so one
  heterogeneous file (several record types sharing one row tag) yields a per-type frame
  without re-anchoring.

Bare :mod:`xml.etree.ElementTree` parsing is a trust boundary risk (entity expansion, external
entity resolution); this seam parses through :mod:`defusedxml` instead, exactly as
``tabular_reader`` bans bare ``pd.read_*`` project-wide.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree.ElementTree import Element  # noqa: S405 — annotation only; parsing uses defusedxml

import defusedxml.ElementTree as defused_et
import pandas as pd

from filings_rfb._internal.utils.dtypes import apply_dtypes
from filings_rfb._internal.utils.tabular_reader import (
    ContractError,
    FileContract,  # noqa: TID251
    ProblemReport,
    find_contract_problems,
)


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


__all__ = [
    "ContractError",
    "FileContract",
    "ProblemReport",
    "find_xml_row_problems",
    "is_attribute_path",
    "read_xml",
    "text_path_columns",
]


@type_checker
def read_xml(  # noqa: PLR0913 — the public reader API; each argument is a real read option
    path_file: Path,
    str_row_anchor: str,
    dict_column_paths: dict[str, tuple[str, ...]],
    dict_dtypes: dict[str, str],
    cls_contract: FileContract,  # complexity-ok: parse/filter-rows/extract/validate — 4 real steps
    str_row_filter: str | None = None,
    list_date_cols: Sequence[str] | None = None,
    list_decimal_cols: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Read an XML file into a typed, contract-validated DataFrame.

    Parameters
    ----------
    path_file : pathlib.Path
        Path to the XML document.
    str_row_anchor : str
        Local name of the repeating element that anchors one output row (matched anywhere in
        the document, namespace-agnostic).
    dict_column_paths : dict of {str: tuple of str}
        Column name to an ORDERED tuple of alternative paths, each relative to the row anchor
        (or absolute — leading ``/`` — for a document-level value broadcast to every row).
        Segments are ``/``-separated local names, ``*`` (single-level wildcard), or a trailing
        ``@name`` to read an attribute. The first alternative that resolves wins.
    dict_dtypes : dict of {str: str}
        Column→dtype mapping enforced via :func:`utils.dtypes.apply_dtypes`.
    cls_contract : FileContract
        The contract the extracted rows must satisfy (required, mirroring
        :func:`utils.tabular_reader.read_table`).
    str_row_filter : str | None, optional
        A path (same grammar, relative to the row anchor) that must resolve for a row-anchor
        element to be kept — checked by presence, not value. ``None`` keeps every row-anchor
        match.
    list_date_cols : sequence of str, optional
        Columns coerced to ``datetime.date``.
    list_decimal_cols : sequence of str, optional
        Columns coerced to exact :class:`decimal.Decimal`.

    Returns
    -------
    pd.DataFrame
        One row per matching (and filtered-in) row-anchor element, with declared types applied.

    Raises
    ------
    FileNotFoundError
        If ``path_file`` does not exist.
    ContractError
        When the extracted rows violate ``cls_contract``.
    """
    if not path_file.exists():
        raise FileNotFoundError(f"File not found: {path_file}")
    cls_root = defused_et.parse(str(path_file)).getroot()
    list_rows = [
        cls_row
        for cls_row in _find_rows(cls_root, str_row_anchor)
        if str_row_filter is None or _path_exists(cls_row, str_row_filter)
    ]
    list_records = [
        {
            str_col: _resolve_column(cls_row, cls_root, tuple_paths)
            for str_col, tuple_paths in dict_column_paths.items()
        }
        for cls_row in list_rows
    ]
    df_raw = pd.DataFrame(list_records, columns=list(dict_column_paths))
    cls_report = find_contract_problems(df_raw, cls_contract)
    if cls_report.list_fatal or cls_report.list_warnings:
        raise ContractError(cls_report.list_fatal + cls_report.list_warnings)
    return apply_dtypes(
        df_raw,
        dict_dtypes=dict_dtypes,
        list_date_cols=list_date_cols,
        list_decimal_cols=list_decimal_cols,
    )


@type_checker
def find_xml_row_problems(  # complexity-ok: two independent guards, missing file vs no rows
    path_file: Path, str_row_anchor: str, cls_contract: FileContract
) -> ProblemReport:
    """Return whether ``path_file`` has at least one ``str_row_anchor`` element (never raises).

    A lightweight pre-check for a caller that wants to skip/notify on a document carrying none
    of the expected rows before attempting the full :func:`read_xml` (which would otherwise
    raise a required-column :class:`ContractError` on an empty extraction, naming a symptom
    rather than the cause). A document with no row-anchor at all is a structural problem —
    there is nothing to extract — so it is always **fatal**, never a warning.

    Parameters
    ----------
    path_file : pathlib.Path
        The XML document to inspect.
    str_row_anchor : str
        Local name of the repeating row element.
    cls_contract : FileContract
        Named in the message only, so the problem reads the same as a tabular one.

    Returns
    -------
    ProblemReport
        ``list_fatal`` and ``list_warnings`` both empty when at least one ``str_row_anchor``
        element is found; otherwise ``list_fatal`` names the missing file or the missing
        anchor. A missing file is a **finding, not an exception** — see the note below.
    """
    if not path_file.exists():
        return ProblemReport(list_fatal=[f"File not found: {path_file}"], list_warnings=[])
    cls_root = defused_et.parse(str(path_file)).getroot()
    if _find_rows(cls_root, str_row_anchor):
        return ProblemReport(list_fatal=[], list_warnings=[])
    return ProblemReport(
        list_fatal=[f"No '{str_row_anchor}' element found for contract '{cls_contract.str_name}'"],
        list_warnings=[],
    )


@type_checker
def is_attribute_path(str_path: str) -> bool:
    """Return whether a column path reads an XML attribute rather than element text.

    Parameters
    ----------
    str_path : str
        A single declared path (one alternative from ``dict_column_paths``).

    Returns
    -------
    bool
        ``True`` when the path's last segment is ``@name``.
    """
    list_segments = [str_segment for str_segment in str_path.split("/") if str_segment]
    return bool(list_segments) and list_segments[-1].startswith("@")


@type_checker
def text_path_columns(dict_column_paths: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    """Return the columns whose FIRST declared path reads element text, not an attribute.

    Scopes a layout/drift check to the document's **element structure**: an attribute holds
    per-value metadata (a currency, a unit), not layout, so a check comparing the source's
    element structure against a full-column contract must not flag an attribute column as an
    unexpected (or missing) piece of layout.

    Parameters
    ----------
    dict_column_paths : dict of {str: tuple of str}
        The same mapping passed to :func:`read_xml`.

    Returns
    -------
    tuple of str
        Column names excluding those whose first alternative is an attribute path.
    """
    return tuple(
        str_col
        for str_col, tuple_paths in dict_column_paths.items()
        if tuple_paths and not is_attribute_path(tuple_paths[0])
    )


@type_checker
def _local_name(str_tag: str) -> str:
    """Strip an XML namespace (``{uri}tag``) down to the bare local name.

    Parameters
    ----------
    str_tag : str
        An element's ``.tag`` value.

    Returns
    -------
    str
        The tag without its namespace prefix.
    """
    return str_tag.rsplit("}", 1)[-1]


@type_checker
def _find_rows(cls_root: Element, str_row_anchor: str) -> list[Element]:
    """Find every element anywhere in the tree whose local name is ``str_row_anchor``.

    Parameters
    ----------
    cls_root : xml.etree.ElementTree.Element
        The document root.
    str_row_anchor : str
        Local name of the repeating row element.

    Returns
    -------
    list of xml.etree.ElementTree.Element
        Every matching element, in document order.
    """
    return [cls_el for cls_el in cls_root.iter() if _local_name(cls_el.tag) == str_row_anchor]


@type_checker
def _find_child(  # complexity-ok: wildcard vs exact-name match is the whole child lookup
    cls_element: Element, str_segment: str
) -> Element | None:
    """Return the first direct child matching a path segment (single level, not recursive).

    Used only for the FINAL (leaf) segment of a path, where there is nothing further to fail
    on — the first match is as good as any other. An intermediate segment instead goes through
    :func:`_matching_children`, which a caller must be able to backtrack across.

    Parameters
    ----------
    cls_element : xml.etree.ElementTree.Element
        The element to search under.
    str_segment : str
        Either ``"*"`` (matches any child) or a local name to match exactly.

    Returns
    -------
    xml.etree.ElementTree.Element | None
        The first matching child, or ``None``.
    """
    for cls_child in cls_element:
        if str_segment == "*" or _local_name(cls_child.tag) == str_segment:
            return cls_child
    return None


@type_checker
def _matching_children(cls_element: Element, str_segment: str) -> list[Element]:
    """Return every direct child matching a path segment, in document order.

    Unlike :func:`_find_child`, this returns ALL candidates — required for an INTERMEDIATE
    path segment, where the first matching child is not necessarily the one whose subtree
    completes the rest of the path (a ``*`` wildcard is the common case: the row's first child
    might be an unrelated ``Meta`` block that has no ``FinInstrm`` under it, while a later
    sibling does).

    Parameters
    ----------
    cls_element : xml.etree.ElementTree.Element
        The element to search under.
    str_segment : str
        Either ``"*"`` (matches any child) or a local name to match exactly.

    Returns
    -------
    list of xml.etree.ElementTree.Element
        Every matching child, in document order.
    """
    if str_segment == "*":
        return list(cls_element)
    return [cls_child for cls_child in cls_element if _local_name(cls_child.tag) == str_segment]


@type_checker
def _get_attribute(  # complexity-ok: linear scan is the whole point of local-name matching
    cls_element: Element, str_name: str
) -> str | None:
    """Return an attribute's value, matched by LOCAL NAME (namespace-agnostic).

    ``Element.get(key)`` requires the EXACT stored key, which is Clark notation
    (``{uri}name``) for a namespace-prefixed attribute — so a plain ``.get("Ccy")`` silently
    misses a source that writes it as, say, ``xsi:Ccy``. Matching by local name here is what
    makes attribute paths honour the same namespace-agnostic promise element paths already
    make (see :func:`_local_name`).

    Parameters
    ----------
    cls_element : xml.etree.ElementTree.Element
        The element carrying the attribute.
    str_name : str
        The attribute's local name (without any ``@`` prefix or namespace).

    Returns
    -------
    str | None
        The attribute's value, or ``None`` when no attribute has that local name.
    """
    for str_key, str_value in cls_element.attrib.items():
        if _local_name(str_key) == str_name:
            return str_value
    return None


@type_checker
def _resolve_path(cls_element: Element, str_path: str) -> str | None:
    """Resolve one path to its element text or attribute value.

    Parameters
    ----------
    cls_element : xml.etree.ElementTree.Element
        The element the path is relative to.
    str_path : str
        A ``/``-separated path; the last segment may be ``@name`` for an attribute.

    Returns
    -------
    str | None
        The stripped text/attribute value, or ``None`` when unresolved or blank.
    """
    list_segments = [str_segment for str_segment in str_path.split("/") if str_segment]
    return _resolve_segments(cls_element, list_segments) if list_segments else None


@type_checker
def _resolve_segments(  # complexity-ok: leaf (attr vs text) vs intermediate (backtracking loop)
    cls_element: Element, list_segments: list[str]
) -> str | None:
    """Resolve a path's remaining segments, backtracking across an intermediate ``*``/name.

    Parameters
    ----------
    cls_element : xml.etree.ElementTree.Element
        The element the remaining segments are relative to.
    list_segments : list of str
        The not-yet-consumed path segments (at least one).

    Returns
    -------
    str | None
        The resolved value, or ``None`` when no candidate at any level completes the path.
    """
    str_segment = list_segments[0]
    if len(list_segments) == 1:
        if str_segment.startswith("@"):
            return _get_attribute(cls_element, str_segment[1:])
        cls_target = _find_child(cls_element, str_segment)
        if cls_target is None:
            return None
        return (cls_target.text or "").strip() or None
    for cls_child in _matching_children(cls_element, str_segment):
        str_value = _resolve_segments(cls_child, list_segments[1:])
        if str_value is not None:
            return str_value
    return None


@type_checker
def _path_exists(cls_element: Element, str_path: str) -> bool:
    """Return whether a path resolves to an element or attribute (presence, not value).

    Parameters
    ----------
    cls_element : xml.etree.ElementTree.Element
        The element the path is relative to.
    str_path : str
        A ``/``-separated path; the last segment may be ``@name`` for an attribute.

    Returns
    -------
    bool
        ``True`` when the path's target exists, regardless of whether it is blank.
    """
    list_segments = [str_segment for str_segment in str_path.split("/") if str_segment]
    return bool(list_segments) and _segments_exist(cls_element, list_segments)


@type_checker
def _segments_exist(  # complexity-ok: mirrors _resolve_segments' two branches, presence only
    cls_element: Element, list_segments: list[str]
) -> bool:
    """Return whether a path's remaining segments exist, with the same backtracking.

    The presence-only twin of :func:`_resolve_segments`.

    Parameters
    ----------
    cls_element : xml.etree.ElementTree.Element
        The element the remaining segments are relative to.
    list_segments : list of str
        The not-yet-consumed path segments (at least one).

    Returns
    -------
    bool
        ``True`` when some candidate at every level has the rest of the path.
    """
    str_segment = list_segments[0]
    if len(list_segments) == 1:
        if str_segment.startswith("@"):
            return _get_attribute(cls_element, str_segment[1:]) is not None
        return _find_child(cls_element, str_segment) is not None
    return any(
        _segments_exist(cls_child, list_segments[1:])
        for cls_child in _matching_children(cls_element, str_segment)
    )


@type_checker
def _resolve_column(  # complexity-ok: the loop over ordered alternatives IS "first match wins"
    cls_row: Element, cls_root: Element, tuple_paths: tuple[str, ...]
) -> str | None:
    """Resolve one column's ordered alternative paths; the first that resolves wins.

    A path starting with ``/`` is resolved against the document ROOT (broadcasting one
    document-level value to every row); any other path is resolved relative to ``cls_row``.

    Parameters
    ----------
    cls_row : xml.etree.ElementTree.Element
        The current row-anchor element.
    cls_root : xml.etree.ElementTree.Element
        The document root, used for a broadcast (``/``-prefixed) path.
    tuple_paths : tuple of str
        The column's ordered alternative paths.

    Returns
    -------
    str | None
        The first resolved value, or ``None`` when no alternative resolves.
    """
    for str_path in tuple_paths:
        str_value = (
            _resolve_path(cls_root, str_path.lstrip("/"))
            if str_path.startswith("/")
            else _resolve_path(cls_row, str_path)
        )
        if str_value is not None:
            return str_value
    return None
