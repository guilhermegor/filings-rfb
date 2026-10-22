"""Robust tabular reading (Excel, CSV, JSON, or SQL) with dtype treatment and data contracts.

One reusable seam for turning a worksheet, a CSV, a JSON document, OR a SQL query into a
typed, validated DataFrame. File format is chosen by extension (``.csv`` → CSV with a
configurable delimiter; ``.json`` → a JSON array of records; otherwise Excel). Capabilities:

- :func:`read_table` — reads a **file**, **always** enforces its contract (raising
  :class:`ContractError` on violation), and applies explicit column types via
  :func:`utils.dtypes.apply_dtypes` (never trusting pandas' inference).
- :func:`read_query` — the **SQL** sibling: runs a parameterized query against an
  already-open DB-API connection and shares the same mandatory contract + dtype tail. The
  seam never opens connections (that stays a controller/boundary concern).
- :func:`find_file_problems` — validates a file against a contract and returns a
  :class:`ProblemReport` **without raising** (the boundary reads ``list_fatal`` to decide
  whether to abort, and ``list_warnings`` to log and continue). See blueprintx#162.
- :func:`decode_positional_payload` — decodes an API payload whose rows are positional
  arrays beside a separate ``columns`` header, handling a row wider than its own header
  asymmetrically (drop a surplus position only when it is empty everywhere; raise when it
  holds a value). The ``.json`` reader uses it automatically for a
  ``{"columns": …, "rows": …}`` document.
- :class:`FileContract` — declares the columns a file must have and the columns that must
  hold valid CNPJs (a coercible-type check).

Column NAMES are as untrusted as column values: they are stripped at the read boundary,
because a publisher shipping ``"Symb "`` yields a column that prints as ``Symb`` while only
``df["Symb "]`` reaches it.

Bare ``pd.read_*`` is banned project-wide (ruff ``TID251``); this seam (and tests) is the one
exempt place, so every read funnels through a contract + dtype check. Projects keep their
concrete contract instances next to their models (or in ``config/contracts/``); the machinery
here stays domain-agnostic.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import csv
from dataclasses import dataclass
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd

from filings_rfb._internal.utils.br_identifiers import is_valid_cnpj, unmask_cnpj
from filings_rfb._internal.utils.dtypes import apply_dtypes
from filings_rfb._internal.utils.text import safe_str


if TYPE_CHECKING:
    from typing import TypeVar

    _F = TypeVar("_F", bound=Callable[..., object])

    def type_checker(fn: _F) -> _F:
        """Type-only stub — see src/utils/CLAUDE.md."""

    class TypeChecker(type):
        """Type-only stub — see src/utils/CLAUDE.md."""
else:
    try:
        from filings_rfb._internal.utils.typing import TypeChecker, type_checker
    except ModuleNotFoundError:
        from filings_rfb._internal.utils.typing import TypeChecker, type_checker


@dataclass(frozen=True)
class FileContract(metaclass=TypeChecker):
    """The required shape of one input file.

    Parameters
    ----------
    str_name : str
        Human-readable file label (used in logs and notifications).
    str_source_key : str
        Source key used to route notifications (e.g. ``"cadastro"``).
    tuple_required : tuple of str
        Columns that must be present.
    tuple_cnpj_cols : tuple of str
        Columns that must hold at least one valid CNPJ (coercible-type check).
    bool_full_column : bool, optional
        Whether ``tuple_required`` lists the source's **complete** published header (default
        ``False``). ``tuple_required`` means "the file must contain **at least** these", so a
        contract is either a deliberate **subset** (require the keys, let the rest flow through
        as typed text) or **full-column** (generated from the whole header, the pinned-oracle
        kind). The distinction is load-bearing for the drift job: "a required column vanished
        from the source" is *always* drift, but "the source has a column we don't require" is
        drift **only** when the contract claims completeness — flagging it on a subset contract
        reports every non-required column as a finding. Keep the default ``False`` unless the
        contract was pinned to the full header; the choice should be conscious per source, not
        accidental.

    Attributes
    ----------
    PROVENANCE_COLUMNS : tuple of str
        The fixed provenance columns appended to every ingested frame by
        :func:`utils.provenance.stamp_provenance`. They describe the full output shape
        (:attr:`output_columns`) but are **not** in ``tuple_required`` — that validates the
        *source* artifact, which never carries them, so the stamp is applied *after* the
        contract check.
    """

    str_name: str
    str_source_key: str
    tuple_required: tuple[str, ...]
    tuple_cnpj_cols: tuple[str, ...]
    bool_full_column: bool = False

    PROVENANCE_COLUMNS: ClassVar[tuple[str, ...]] = (
        "url",
        "updated_at",
        "source_key",
        "package_version",
        "ingestion_run_id",
        "content_hash",
    )

    @property
    def output_columns(self) -> tuple[str, ...]:
        """Return the full output shape: source-required columns then provenance columns.

        Returns
        -------
        tuple of str
            ``tuple_required + PROVENANCE_COLUMNS`` — what a stamped, ingested frame holds.
        """
        return self.tuple_required + self.PROVENANCE_COLUMNS


class ContractError(Exception, metaclass=TypeChecker):
    """Raised when a strictly-read file/query violates its data contract.

    Parameters
    ----------
    list_problems : list of str
        The problem messages describing the violations.
    """

    def __init__(self, list_problems: list[str]) -> None:
        self.list_problems = list_problems
        super().__init__("; ".join(list_problems))


@dataclass(frozen=True)
class ProblemReport(metaclass=TypeChecker):
    """Severity-split findings from a ``find_*_problems`` validator (blueprintx#162).

    A single flat list of problem strings carries no severity, so a caller reading it has to
    guess — from the wording alone — whether a given entry means "abort" or "log and
    continue", and a loader author and a caller author routinely guess differently. Splitting
    the findings into two lists instead of tagging each string with a severity field makes the
    mistake **unrepresentable**: a caller that reads only ``list_warnings`` (its "proceed with
    a note" branch) physically cannot see a fatal problem, because a fatal one is never placed
    there — there is no field to forget to check.

    Attributes
    ----------
    list_fatal : list of str
        Problems that make the data unusable; the caller should abort.
    list_warnings : list of str
        Problems worth logging that do not, on their own, block use of the data.
    """

    list_fatal: list[str]
    list_warnings: list[str]


@type_checker
def read_table(  # noqa: PLR0913 — the public reader API; each argument is a real read option
    path_file: Path,
    str_sheet: str,
    dict_dtypes: dict[str, str],
    cls_contract: FileContract,
    list_date_cols: Sequence[str] | None = None,
    list_decimal_cols: Sequence[str] | None = None,
    str_csv_sep: str = ";",
    list_columns: Sequence[str] | None = None,
    str_encoding: str = "utf-8-sig",
    int_header_row: int = 0,
    int_csv_quoting: int = csv.QUOTE_MINIMAL,
) -> pd.DataFrame:
    """Read a file (Excel/CSV/JSON) into a typed, contract-validated DataFrame.

    The file is **read as raw text** (``dtype="str"``) and :func:`utils.dtypes.apply_dtypes`
    does all coercion — never pandas' inference, which would truncate a money decimal or drop a
    code's leading zeros irrecoverably before typing.

    The data contract is **mandatory**: the file is always validated first and
    :class:`ContractError` is raised on any violation, before types are applied. A read that
    legitimately constrains nothing still declares intent by passing an empty contract
    (``FileContract(name, key, (), ())``).

    Parameters
    ----------
    path_file : pathlib.Path
        Path to the workbook, CSV, or JSON. The extension selects the reader.
    str_sheet : str
        Worksheet name (used for Excel; ignored for CSV/JSON). ``""`` reads the first sheet.
    dict_dtypes : dict of {str: str}
        Column→dtype mapping enforced via :func:`utils.dtypes.apply_dtypes`.
    cls_contract : FileContract
        The contract the file must satisfy (required).
    list_date_cols : sequence of str, optional
        Columns coerced to ``datetime.date``.
    list_decimal_cols : sequence of str, optional
        Columns coerced to exact :class:`decimal.Decimal`. Use this for money and any other
        value whose fractional part carries meaning: a binary float dtype would destroy the
        source's exact value irreversibly and silently.
    str_csv_sep : str, optional
        CSV delimiter (default ``";"``); ignored otherwise.
    list_columns : sequence of str, optional
        CSV only: read **headerless** and assign these names in order. Ignored otherwise.
    str_encoding : str, optional
        CSV only: text encoding (default ``"utf-8-sig"`` so a leading BOM never corrupts the
        first cell). Pass ``"ISO-8859-1"`` for Latin-1 exports. Ignored otherwise.
    int_header_row : int, optional
        Excel only: zero-based header-row index (default ``0``). Ignored otherwise.
    int_csv_quoting : int, optional
        CSV only: the :mod:`csv` quoting constant passed to the reader (default
        ``csv.QUOTE_MINIMAL``, pandas' own default). Pass ``csv.QUOTE_NONE`` for external
        ``;``-delimited regulatory dumps (e.g. CVM open data), where an upstream submitter's
        stray ``"`` is literal text, not a field wrapper — the default engine would swallow the
        delimiter and shift subsequent columns, corrupting the parse. Ignored otherwise.

    Returns
    -------
    pd.DataFrame
        The rows with the declared types applied.

    Raises
    ------
    ContractError
        When the file violates ``cls_contract``.

    Notes
    -----
    The file is always read as text, never with pandas' type inference: a zero-padded code
    loses its leading zeros and a money decimal its trailing zeros *before* typing, and
    ``apply_dtypes`` cannot recover them afterwards. Reading as text is lossless — the
    declared dtype then coerces the exact source text.
    """
    df_raw = _read_raw(
        path_file,
        str_sheet,
        "str",
        str_csv_sep,
        list_columns,
        str_encoding,
        int_header_row,
        int_csv_quoting,
    )
    return _finalize(df_raw, dict_dtypes, list_date_cols, cls_contract, list_decimal_cols)


@type_checker
def read_query(
    cls_connection: Any,  # noqa: ANN401 — opaque DB-API connection; any driver's object is valid
    str_sql: str,
    dict_dtypes: dict[str, str],
    cls_contract: FileContract,
    list_params: Sequence[Any] | None = None,
    list_date_cols: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Run a parameterized SQL query into a typed, contract-validated DataFrame.

    The SQL sibling of :func:`read_table`: it shares the same mandatory contract check +
    :func:`utils.dtypes.apply_dtypes` tail so file and DB reads cannot diverge. The connection
    is **passed in already open** (the seam never opens connections — that is a
    controller/boundary concern); queries are parameterized, never string-interpolated.

    Parameters
    ----------
    cls_connection : Any
        An open DB-API 2.0 connection (e.g. from ``config.connection_db.build_connection``).
        Opaque by design — any driver's connection object is accepted.
    str_sql : str
        The SQL query, with ``?``/``%s`` placeholders for any parameters.
    dict_dtypes : dict of {str: str}
        Column→dtype mapping enforced via :func:`utils.dtypes.apply_dtypes`.
    cls_contract : FileContract
        The contract the result must satisfy (required).
    list_params : sequence, optional
        Bound query parameters passed to :func:`pandas.read_sql_query`.
    list_date_cols : sequence of str, optional
        Columns coerced to ``datetime.date``.

    Returns
    -------
    pd.DataFrame
        The query rows with the declared types applied.

    Raises
    ------
    ContractError
        When the result violates ``cls_contract``.
    """
    df_raw = pd.read_sql_query(str_sql, cls_connection, params=list_params)
    return _finalize(df_raw, dict_dtypes, list_date_cols, cls_contract)


@type_checker
def find_file_problems(
    cls_contract: FileContract, path_file: Path, str_sheet: str, str_csv_sep: str = ";"
) -> ProblemReport:
    """Validate a file against its contract; return a severity-split report (never raises).

    Parameters
    ----------
    cls_contract : FileContract
        The contract to validate against.
    path_file : pathlib.Path
        The file to read (Excel or CSV).
    str_sheet : str
        Worksheet name (used for Excel; ignored for CSV).
    str_csv_sep : str, optional
        CSV delimiter (default ``";"``); ignored for Excel.

    Returns
    -------
    ProblemReport
        ``list_fatal`` and ``list_warnings``, both empty when the file is sound. A missing
        file is a **finding, not an exception** — see the note below.
    """
    if not path_file.exists():
        return ProblemReport(list_fatal=[f"File not found: {path_file}"], list_warnings=[])
    df_raw = _read_raw(path_file, str_sheet, "str", str_csv_sep)
    return find_contract_problems(df_raw, cls_contract)


@type_checker
def find_contract_problems(df_input: pd.DataFrame, cls_contract: FileContract) -> ProblemReport:
    """Return the contract problems of an already-read frame, split by severity (never raises).

    A required column that is simply absent is **fatal** — there is no way to proceed, every
    downstream lookup would raise ``KeyError``. A CNPJ column that is present but holds no
    valid value is a **warning** — the shape of the frame is sound, only its content is
    questionable, so a tolerant caller may log it and continue. :func:`_finalize` (the strict
    twin behind ``read_table``/``read_query``) still aborts on either kind, unchanged from
    before this split — only a caller reading this report directly gets to tell them apart.

    Parameters
    ----------
    df_input : pd.DataFrame
        The frame to validate (raw, as read).
    cls_contract : FileContract
        The contract to validate against.

    Returns
    -------
    ProblemReport
        ``list_fatal`` holds missing required columns; ``list_warnings`` holds CNPJ columns
        that hold no valid CNPJ.
    """
    list_missing = [
        f"Required column missing in '{cls_contract.str_name}': '{str_col}'"
        for str_col in cls_contract.tuple_required
        if str_col not in df_input.columns
    ]
    list_cnpj = [
        str_problem
        for str_col in cls_contract.tuple_cnpj_cols
        if str_col in df_input.columns
        for str_problem in [
            _cnpj_column_problem(df_input[str_col], str_col, cls_contract.str_name)
        ]
        if str_problem is not None
    ]
    return ProblemReport(list_fatal=list_missing, list_warnings=list_cnpj)


@type_checker
def _cnpj_column_problem(  # complexity-ok: two acceptance rules, empty-column one load-bearing
    series_col: pd.Series, str_col: str, str_contract: str
) -> str | None:
    """Return the problem with a CNPJ column, or ``None`` when it is acceptable.

    ⚠️ An EMPTY column is not a broken column. Over an empty series the any-reducer answers
    False — the exact answer a column of garbage gives — so without this guard a source
    reporting "nothing today" by shipping its header alone is reproved as holding no valid
    CNPJ, and the run dies on a perfectly well-formed file. A column that HAS values and none
    valid must still be reported (as a warning — see :class:`ProblemReport`), so the guard is
    emptiness only.

    Parameters
    ----------
    series_col : pd.Series
        The column to validate.
    str_col : str
        Its name, for the message.
    str_contract : str
        The contract's name, for the message.

    Returns
    -------
    str or None
        The problem description, or ``None``.
    """
    if series_col.empty:
        return None
    series_valid = series_col.map(lambda obj_cell: is_valid_cnpj(unmask_cnpj(safe_str(obj_cell))))
    if bool(series_valid.any()):
        return None
    return f"Column '{str_col}' in '{str_contract}' holds no valid CNPJ (unexpected data type)"


@type_checker
def decode_positional_payload(  # complexity-ok: two rejection rules, never invent or drop data
    list_columns: Sequence[str], list_rows: Sequence[Sequence[Any]]
) -> pd.DataFrame:
    """Decode an API payload whose rows are positional arrays beside a separate header.

    An endpoint returning ``{"columns": [...], "rows": [[...], ...]}`` can send rows **wider
    than its own header** — and it is per table, not per format, so a sibling endpoint that
    matches exactly is no evidence about this one. The width mismatch is handled
    **asymmetrically**: a surplus position is dropped only when it is empty on *every* row,
    and raises when it ever holds a value. The payload is positional, so a surplus value
    cannot be named — and trimming it blindly is exactly how a source column stops arriving
    with nothing going red, since a contract validates column PRESENCE, not payload WIDTH.

    Never ``zip()`` (it truncates in silence) and never pad: a short row is a defect too, it
    simply happens to be the direction that blows up on its own.

    Parameters
    ----------
    list_columns : sequence of str
        The header the payload declares, in order.
    list_rows : sequence of sequence
        The rows as positional arrays.

    Returns
    -------
    pd.DataFrame
        A frame with exactly ``list_columns`` as its columns.

    Raises
    ------
    ContractError
        If a row is narrower than the header, or if a surplus position holds a value.
    """
    int_declared = len(list_columns)
    list_narrow = [int_i for int_i, seq_row in enumerate(list_rows) if len(seq_row) < int_declared]
    if list_narrow:
        raise ContractError(
            [
                f"Positional payload has {len(list_narrow)} row(s) narrower than the declared "
                f"{int_declared} columns (first at index {list_narrow[0]}); "
                f"padding would invent data"
            ]
        )

    int_widest = max((len(seq_row) for seq_row in list_rows), default=int_declared)
    list_populated_surplus = [
        int_pos
        for int_pos in range(int_declared, int_widest)
        if any(
            seq_row[int_pos] not in (None, "") for seq_row in list_rows if len(seq_row) > int_pos
        )
    ]
    if list_populated_surplus:
        raise ContractError(
            [
                f"Positional payload row is wider than its header and surplus position "
                f"{list_populated_surplus[0]} holds a value — it cannot be named, so it "
                f"must not be dropped"
            ]
        )

    return pd.DataFrame(
        [list(seq_row)[:int_declared] for seq_row in list_rows], columns=list(list_columns)
    )


@type_checker
def resolve_sheet_name(  # complexity-ok: three documented resolution outcomes, one branch each
    path_file: Path, tuple_known_names: tuple[str, ...]
) -> str:
    """Resolve which worksheet to read from a workbook whose sheet name varies by source.

    A **single-sheet** workbook uses that one sheet (whatever its name); a **multi-sheet**
    workbook uses the first sheet whose name matches one of ``tuple_known_names``
    (case-insensitive). A multi-sheet workbook with **no** known name raises
    :class:`ContractError`, so the caller treats the file as invalid rather than silently
    reading the wrong sheet. Non-Excel files have no sheet concept and return ``""``.

    Parameters
    ----------
    path_file : pathlib.Path
        The workbook to inspect.
    tuple_known_names : tuple of str
        Accepted sheet names, in priority order (matched case-insensitively).

    Returns
    -------
    str
        The sheet name to read (``""`` for non-Excel files).

    Raises
    ------
    ContractError
        When the workbook has multiple sheets and none matches ``tuple_known_names``.
    """
    if path_file.suffix.lower() not in {".xlsx", ".xls", ".xlsm"}:
        return ""
    with pd.ExcelFile(path_file) as cls_excel:
        list_sheets = [str(s) for s in cls_excel.sheet_names]
    if len(list_sheets) == 1:
        return list_sheets[0]
    dict_by_lower = {s.casefold(): s for s in list_sheets}
    str_match = next(
        (
            dict_by_lower[str_known.casefold()]
            for str_known in tuple_known_names
            if str_known.casefold() in dict_by_lower
        ),
        None,
    )
    if str_match is not None:
        return str_match
    raise ContractError(
        [
            f"{path_file.name}: multiple sheets {list_sheets} and none with a known name "
            f"{list(tuple_known_names)}"
        ]
    )


@type_checker
def _finalize(
    df_raw: pd.DataFrame,
    dict_dtypes: dict[str, str],
    list_date_cols: Sequence[str] | None,
    cls_contract: FileContract,
    list_decimal_cols: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Enforce the contract then apply declared types (shared, mandatory read tail).

    Parameters
    ----------
    df_raw : pd.DataFrame
        The frame as read (file or query), before validation or typing.
    dict_dtypes : dict of {str: str}
        Column→dtype mapping enforced via :func:`utils.dtypes.apply_dtypes`.
    list_date_cols : sequence of str | None
        Columns coerced to ``datetime.date``.
    cls_contract : FileContract
        The contract validated before typing.
    list_decimal_cols : sequence of str | None
        Columns coerced to exact ``Decimal`` — money and any other value whose fractional
        part carries meaning, which must never round-trip through a binary float.

    Returns
    -------
    pd.DataFrame
        The rows with the declared types applied.

    Raises
    ------
    ContractError
        When the frame violates ``cls_contract`` — fatal or warning, since this is the
        STRICT twin: unlike a caller reading :class:`ProblemReport` directly, it aborts on
        either kind rather than choosing per severity.
    """
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
def _read_raw(
    path_file: Path,
    str_sheet: str,
    str_dtype: str | None,
    str_csv_sep: str,
    list_columns: Sequence[str] | None = None,
    str_encoding: str = "utf-8-sig",
    int_header_row: int = 0,
    int_csv_quoting: int = csv.QUOTE_MINIMAL,
) -> pd.DataFrame:
    """Read a file into a raw DataFrame and normalise its column NAMES.

    Ingestion validates a source's values and tends to trust its column names; both are
    untrusted, and the name defect is the nastier of the two because it is invisible. A
    publisher that ships ``"Symb "`` with a trailing space produces a column that PRINTS as
    ``Symb`` while only ``df["Symb "]`` reaches it — so the contract reports a required column
    *missing* and every lookup raises ``KeyError`` on a name plainly visible in
    ``df.columns``. Stripping at the read boundary is the one place that fixes it for every
    caller, and it is per-dataset, never per-format: a sibling table from the same endpoint
    is usually clean, which is exactly why nobody expects it.

    See :func:`_read_raw_dispatch` for the per-format reading itself.
    """
    df_raw = _read_raw_dispatch(
        path_file,
        str_sheet,
        str_dtype,
        str_csv_sep,
        list_columns,
        str_encoding,
        int_header_row,
        int_csv_quoting,
    )
    list_normalised = [str(col).strip() for col in df_raw.columns]
    list_duplicates = sorted({c for c in list_normalised if list_normalised.count(c) > 1})
    if list_duplicates:
        raise ContractError(
            [
                f"Column names collide after trimming whitespace: {', '.join(list_duplicates)}. "
                f"The source published the same name with and without surrounding spaces; "
                f"disambiguate it before reading."
            ]
        )
    df_raw.columns = list_normalised
    return df_raw


@type_checker
def _read_raw_dispatch(
    path_file: Path,
    str_sheet: str,
    str_dtype: str | None,
    str_csv_sep: str,
    list_columns: Sequence[str] | None = None,
    str_encoding: str = "utf-8-sig",
    int_header_row: int = 0,
    int_csv_quoting: int = csv.QUOTE_MINIMAL,
) -> pd.DataFrame:
    """Read a file into a raw DataFrame, dispatching by extension (CSV, JSON, or Excel).

    Parameters
    ----------
    path_file : pathlib.Path
        The file to read.
    str_sheet : str
        Worksheet name (Excel only; ignored for CSV and JSON).
    str_dtype : str | None
        Optional dtype applied to every column on read (e.g. ``"str"`` for validation);
        ``None`` lets the reader infer (types are applied afterwards).
    str_csv_sep : str
        CSV delimiter (ignored for Excel and JSON).
    list_columns : sequence of str, optional
        CSV only: when given, read headerless and assign these column names.
    str_encoding : str, optional
        CSV text encoding (default ``"utf-8-sig"`` so a leading BOM never corrupts the first
        cell); pass ``"ISO-8859-1"`` for Latin-1 exports.
    int_header_row : int, optional
        Excel header-row index (default ``0``). Ignored for CSV/JSON.
    int_csv_quoting : int, optional
        CSV :mod:`csv` quoting constant (default ``csv.QUOTE_MINIMAL``). ``csv.QUOTE_NONE``
        treats a stray ``"`` as literal text — correct for ``;``-delimited regulatory dumps.

    Returns
    -------
    pd.DataFrame
        The raw rows as read.

    Raises
    ------
    FileNotFoundError
        If ``path_file`` does not exist (fail fast at the read boundary).
    """
    if not path_file.exists():
        raise FileNotFoundError(f"File not found: {path_file}")
    fn_reader = _DICT_RAW_READERS.get(path_file.suffix.lower(), _read_excel_raw)
    return fn_reader(
        path_file,
        str_sheet=str_sheet,
        str_dtype=str_dtype,
        str_csv_sep=str_csv_sep,
        list_columns=list_columns,
        str_encoding=str_encoding,
        int_header_row=int_header_row,
        int_csv_quoting=int_csv_quoting,
    )


@type_checker
def _read_csv_raw(
    path_file: Path,
    str_dtype: str | None = None,
    str_csv_sep: str = ",",
    list_columns: Sequence[str] | None = None,
    str_encoding: str = "utf-8-sig",
    int_csv_quoting: int = csv.QUOTE_MINIMAL,
    **_kwargs: object,
) -> pd.DataFrame:
    """Read a CSV, naming the columns positionally when the file carries no header.

    Parameters
    ----------
    path_file : pathlib.Path
        The file to read.
    str_dtype : str or None, optional
        Dtype passed through to pandas.
    str_csv_sep : str, optional
        Field separator.
    list_columns : sequence of str or None, optional
        When given, the file is treated as headerless and these names are applied.
    str_encoding : str, optional
        Text encoding.
    int_csv_quoting : int, optional
        ``csv`` quoting constant.
    **_kwargs : object
        Ignored; present so every reader shares one dispatch signature.

    Returns
    -------
    pd.DataFrame
        The raw frame.
    """
    dict_header = {"header": None, "names": list(list_columns)} if list_columns is not None else {}
    return pd.read_csv(
        path_file,
        dtype=str_dtype,
        sep=str_csv_sep,
        encoding=str_encoding,
        quoting=int_csv_quoting,
        **dict_header,
    )


@type_checker
def _read_json_raw(
    path_file: Path,
    str_dtype: str | None = None,
    str_encoding: str = "utf-8-sig",
    **_kwargs: object,
) -> pd.DataFrame:
    """Read a JSON document as TEXT, decoding a header-plus-positional-rows payload.

    ⚠️ Never use pandas' own JSON reader here. It infers types before anything can ask it not
    to, and the later astype cannot undo that. It coerces even values the document QUOTES as
    strings — measured, ``"1000.50"`` comes back as ``1000.5`` and ``"007"`` as ``7`` — so the
    "always read as text" guarantee ``read_table`` documents was false on this branch alone
    while the CSV branch honoured it. Parsing floats and ints as ``str`` keeps the exact source
    token, which is what a Decimal column is later built from.

    Parameters
    ----------
    path_file : pathlib.Path
        The file to read.
    str_dtype : str or None, optional
        Dtype applied after decoding.
    str_encoding : str, optional
        Text encoding.
    **_kwargs : object
        Ignored; present so every reader shares one dispatch signature.

    Returns
    -------
    pd.DataFrame
        The raw frame.
    """
    obj_json = json.loads(
        path_file.read_text(encoding=str_encoding), parse_float=str, parse_int=str
    )
    bool_positional = isinstance(obj_json, dict) and {"columns", "rows"} <= set(obj_json)
    df_json = (
        decode_positional_payload(obj_json["columns"], obj_json["rows"])
        if bool_positional
        else pd.DataFrame(obj_json)
    )
    return df_json.astype(str_dtype) if str_dtype is not None else df_json


@type_checker
def _read_excel_raw(
    path_file: Path,
    str_sheet: str = "",
    str_dtype: str | None = None,
    int_header_row: int = 0,
    **_kwargs: object,
) -> pd.DataFrame:
    """Read a worksheet, defaulting to the first sheet whatever it is named.

    An empty sheet name means "the first worksheet, whatever it is named" — external files
    arrive with locale-dependent default sheet names such as ``Planilha1`` or ``Sheet1``, so
    the first sheet is read by POSITION rather than by guessing its name.

    Parameters
    ----------
    path_file : pathlib.Path
        The workbook to read.
    str_sheet : str, optional
        Worksheet name; empty means the first sheet by position.
    str_dtype : str or None, optional
        Dtype passed through to pandas.
    int_header_row : int, optional
        Zero-based header row index.
    **_kwargs : object
        Ignored; present so every reader shares one dispatch signature.

    Returns
    -------
    pd.DataFrame
        The raw frame.
    """
    sheet_excel: str | int = 0 if str_sheet == "" else str_sheet
    return pd.read_excel(path_file, sheet_name=sheet_excel, dtype=str_dtype, header=int_header_row)


_DICT_RAW_READERS: dict[str, Callable[..., pd.DataFrame]] = {
    ".csv": _read_csv_raw,
    ".json": _read_json_raw,
}
