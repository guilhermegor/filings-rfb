"""Read the six RFB CNPJ lookup tables into typed, provenance-stamped DataFrames.

Cnaes, Motivos, Municipios, Naturezas, Paises and Qualificacoes are each published as a ZIP
holding **one** headerless, ``;``-separated, fully quoted ``latin-1`` CSV of two columns,
``code;description``. Its member name never ends in ``.csv`` (``F.K03200$Z.D61010.MOTICSV``),
so the member is picked by being the only file in the archive, never by extension — filtering
on ``.csv`` is the defect that made every legacy reader return an empty frame.

This module reads an archive that is already on disk; fetching it (and learning its URL and
``ETag`` from the share catalogue) is the caller's job and the values are passed in so they can
be stamped as provenance.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING

import pandas as pd

from filings_rfb._internal.config.contracts import (
    CNPJ_LOOKUP_CONTRACTS,
    CNPJ_LOOKUP_NAMES,
    ContractError,
    FileContract,
)
from filings_rfb._internal.utils.provenance import (
    hash_artifact,
    resolve_package_version,
    stamp_provenance,
)
from filings_rfb._internal.utils.tabular_reader import read_table
from filings_rfb._internal.utils.zip_extractor import extract_all_to_memory


if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import TypeVar

    _F = TypeVar("_F", bound=Callable[..., object])

    def type_checker(fn: _F) -> _F:
        """Type-only stub — see src/utils/CLAUDE.md."""
else:
    from filings_rfb._internal.utils.typing import type_checker


__all__ = ["CNPJ_LOOKUP_NAMES", "read_lookup"]

_TUPLE_COLUMNS = ("code", "description")
_DICT_DTYPES = {"code": "str", "description": "str"}
_STR_ENCODING = "latin-1"
_STR_DISTRIBUTION = "filings-rfb"


@type_checker
def read_lookup(str_table: str, path_zip: Path, str_url: str, str_etag: str) -> pd.DataFrame:
    """Read one lookup ZIP into a typed frame stamped with its provenance.

    Parameters
    ----------
    str_table : str
        One of :data:`CNPJ_LOOKUP_NAMES` (``"Cnaes"``, ``"Motivos"``, ``"Municipios"``,
        ``"Naturezas"``, ``"Paises"``, ``"Qualificacoes"``).
    path_zip : pathlib.Path
        The downloaded archive.
    str_url : str
        The exact URL the archive was fetched from.
    str_etag : str
        The ``ETag`` the share reported for it, stamped as ``source_etag``.

    Returns
    -------
    pd.DataFrame
        ``code`` and ``description`` as text (leading zeros kept), then the provenance columns
        and ``source_etag``.

    Raises
    ------
    ValueError
        When ``str_table`` is unknown, or the archive does not hold exactly one file member.
    ContractError
        When a row is not the two-column ``code;description`` shape.
    """
    cls_contract = _resolve_contract(str_table)
    bytes_member = _read_single_member(path_zip)
    _assert_two_columns(bytes_member, str_table)
    df_typed = _read_typed(bytes_member, cls_contract)
    df_stamped = stamp_provenance(
        df_typed,
        str_url,
        cls_contract,
        hash_artifact(path_zip),
        resolve_package_version(_STR_DISTRIBUTION),
    )
    df_stamped["source_etag"] = pd.array([str_etag] * len(df_stamped), dtype="string")
    return df_stamped


@type_checker
def _resolve_contract(str_table: str) -> FileContract:
    """Return the contract of a known lookup table.

    Parameters
    ----------
    str_table : str
        The table name.

    Returns
    -------
    FileContract
        Its declared contract.

    Raises
    ------
    ValueError
        When the name is not one of the six published tables.
    """
    if str_table not in CNPJ_LOOKUP_CONTRACTS:
        raise ValueError(f"Unknown lookup table {str_table!r}. Known: {list(CNPJ_LOOKUP_NAMES)}")
    return CNPJ_LOOKUP_CONTRACTS[str_table]


@type_checker
def _read_single_member(path_zip: Path) -> bytes:
    """Return the bytes of the archive's only file member, whatever its name.

    Parameters
    ----------
    path_zip : pathlib.Path
        The archive. Lookup archives are tens of KB, so reading the member into memory is safe.

    Returns
    -------
    bytes
        The member's content.

    Raises
    ------
    ValueError
        When the archive holds zero or several file members — guessing would hide a layout
        change.
    """
    dict_members = extract_all_to_memory(path_zip)
    if len(dict_members) != 1:
        raise ValueError(
            f"{path_zip.name}: expected exactly one file member, found "
            f"{len(dict_members)}: {sorted(dict_members)}"
        )
    return next(iter(dict_members.values()))


@type_checker
def _assert_two_columns(bytes_member: bytes, str_table: str) -> None:
    """Reject any row that is not ``code;description``.

    A wider row would otherwise be accepted by pandas, which silently promotes the surplus
    leading fields to the index and shifts the data under the wrong names.

    Parameters
    ----------
    bytes_member : bytes
        The raw CSV.
    str_table : str
        The table name, for the message.

    Raises
    ------
    ContractError
        When any non-blank row does not have exactly two fields.
    """
    str_text = bytes_member.decode(_STR_ENCODING)
    list_bad = [
        int_line
        for int_line, list_row in enumerate(csv.reader(io.StringIO(str_text), delimiter=";"), 1)
        if list_row and len(list_row) != len(_TUPLE_COLUMNS)
    ]
    if list_bad:
        raise ContractError(
            [f"{str_table}: rows {list_bad[:5]} are not the two columns code;description"]
        )


@type_checker
def _read_typed(bytes_member: bytes, cls_contract: FileContract) -> pd.DataFrame:
    """Parse the CSV bytes through the contract-checked, explicitly typed reader.

    Parameters
    ----------
    bytes_member : bytes
        The raw CSV.
    cls_contract : FileContract
        The table's contract.

    Returns
    -------
    pd.DataFrame
        The typed frame (not yet stamped).
    """
    with tempfile.TemporaryDirectory() as str_dir:
        path_csv = Path(str_dir) / "lookup.csv"
        path_csv.write_bytes(bytes_member)
        return read_table(
            path_csv,
            "",
            _DICT_DTYPES,
            cls_contract,
            str_csv_sep=";",
            list_columns=_TUPLE_COLUMNS,
            str_encoding=_STR_ENCODING,
        )
