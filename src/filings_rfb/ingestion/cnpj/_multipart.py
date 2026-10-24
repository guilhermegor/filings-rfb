"""Shared multi-part, chunked reader for the RFB CNPJ archives (``<Name>0.zip`` .. ``<Name>9.zip``).

``Empresas``, ``Estabelecimentos``, ``Socios`` and ``Simples`` all ship as numbered ZIP parts
each holding one headerless ``;``-delimited latin-1 CSV that inflates to hundreds of MB or
GB, so they cannot be returned as one DataFrame. This module is the one place that knows how
to walk them: for each part it checks the part is published, streams the ZIP to disk with the
resumable downloader, reads its single member **as a stream** (never extracted), and yields
typed, contract-validated, provenance-stamped chunks. A dataset reader only supplies its
contract, column names and dtypes.

⚠️ A part the share does not list is an error (:class:`FileNotFoundError`), never a silent
skip: a quietly dropped part is a quietly incomplete dataset.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack
from pathlib import Path
import tempfile
from zipfile import ZipFile

import pandas as pd

from filings_rfb._internal.utils.provenance import (
    hash_artifact,
    new_run_id,
    resolve_package_version,
    stamp_provenance,
    stamp_source_etag,
)
from filings_rfb._internal.utils.stream_downloader import download_file_streaming
from filings_rfb._internal.utils.tabular_reader import FileContract, read_table_chunks
from filings_rfb._internal.utils.typing import type_checker
from filings_rfb.ingestion.cnpj._share import file_url, list_files


__all__ = ["DEFAULT_CHUNK_ROWS", "DEFAULT_PARTS", "iter_part_chunks"]

DEFAULT_PARTS: tuple[int, ...] = tuple(range(10))
DEFAULT_CHUNK_ROWS: int = 500_000
_PACKAGE_NAME: str = "filings-rfb"


@type_checker
def iter_part_chunks(  # noqa: PLR0913 — the shared reader API; each argument is a real option
    str_month: str,
    str_prefix: str,
    cls_contract: FileContract,
    dict_dtypes: dict[str, str],
    int_chunk_rows: int = DEFAULT_CHUNK_ROWS,
    path_workdir: Path | None = None,
    tuple_parts: tuple[int, ...] = DEFAULT_PARTS,
    list_decimal_cols: Sequence[str] | None = None,
    fn_prepare: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
) -> Iterator[pd.DataFrame]:
    """Yield every chunk of every part of one dataset for a reference month.

    Parts are read in order, one at a time; each ZIP is deleted once consumed when the
    workdir is a temporary one, so disk use stays at one archive. Rows carry the contract's
    six provenance columns plus ``source_etag`` and ``part_index``; all chunks of one call
    share one ``ingestion_run_id``.

    Parameters
    ----------
    str_month : str
        The reference month, ``YYYY-MM``.
    str_prefix : str
        The file-name stem before the part number, e.g. ``"Empresas"``.
    cls_contract : FileContract
        The contract whose ``tuple_required`` names the positional columns.
    dict_dtypes : dict of {str: str}
        Column→dtype mapping for :func:`apply_dtypes`.
    int_chunk_rows : int, optional
        Rows per chunk, by default :data:`DEFAULT_CHUNK_ROWS`.
    path_workdir : pathlib.Path, optional
        Where to keep the downloaded ZIPs (kept after the read, so a rerun can reuse the
        directory). ``None`` uses a temporary directory removed when the iterator finishes.
    tuple_parts : tuple of int, optional
        The part numbers to read, by default ``0..9``.
    list_decimal_cols : sequence of str, optional
        Columns coerced to exact ``Decimal``.
    fn_prepare : callable, optional
        Text-level reshaping of each named chunk before typing.

    Yields
    ------
    pd.DataFrame
        One typed, stamped chunk at a time.

    Raises
    ------
    ValueError
        If the month is malformed or not published (from the catalogue).
    FileNotFoundError
        If a requested part is not published for the month.
    """
    dict_published = {cls_entry.str_name: cls_entry for cls_entry in list_files(str_month)}
    list_missing = [
        f"{str_prefix}{int_part}.zip"
        for int_part in tuple_parts
        if f"{str_prefix}{int_part}.zip" not in dict_published
    ]
    if list_missing:
        raise FileNotFoundError(f"{str_month}: part(s) not published: {', '.join(list_missing)}")
    str_run_id = new_run_id()
    str_version = resolve_package_version(_PACKAGE_NAME)
    with ExitStack() as cls_stack:
        path_dir = path_workdir or Path(cls_stack.enter_context(tempfile.TemporaryDirectory()))
        for int_part in tuple_parts:
            yield from _iter_one_part(
                (str_month, f"{str_prefix}{int_part}.zip", int_part),
                path_dir / f"{str_month}_{str_prefix}{int_part}.zip",
                (cls_contract, dict_dtypes, int_chunk_rows, list_decimal_cols, fn_prepare),
                (str_run_id, str_version),
            )
            if path_workdir is None:
                (path_dir / f"{str_month}_{str_prefix}{int_part}.zip").unlink(missing_ok=True)


@type_checker
def _iter_one_part(
    tuple_part: tuple[str, str, int],
    path_zip: Path,
    tuple_read: tuple[
        FileContract,
        dict[str, str],
        int,
        Sequence[str] | None,
        Callable[[pd.DataFrame], pd.DataFrame] | None,
    ],
    tuple_run: tuple[str, str],
) -> Iterator[pd.DataFrame]:
    """Download one part and yield its stamped chunks.

    Parameters
    ----------
    tuple_part : tuple of (str, str, int)
        The month, the file name and the part number.
    path_zip : pathlib.Path
        Where to put the downloaded ZIP.
    tuple_read : tuple
        ``(contract, dtypes, chunk rows, decimal columns, prepare function)``.
    tuple_run : tuple of (str, str)
        The shared ``ingestion_run_id`` and the package version.

    Yields
    ------
    pd.DataFrame
        One typed, stamped chunk at a time.
    """
    str_month, str_name, int_part = tuple_part
    cls_contract, dict_dtypes, int_chunk_rows, list_decimal_cols, fn_prepare = tuple_read
    str_url = file_url(str_month, str_name)
    _, str_etag = download_file_streaming(str_url, path_zip)
    str_hash = hash_artifact(path_zip)
    with ZipFile(path_zip) as cls_zip:
        with cls_zip.open(_single_member(cls_zip, str_name)) as cls_member:
            for df_chunk in read_table_chunks(
                cls_member,
                dict_dtypes,
                cls_contract,
                cls_contract.tuple_required,
                int_chunk_rows,
                list_decimal_cols,
                fn_prepare,
            ):
                df_stamped = stamp_provenance(
                    df_chunk, str_url, cls_contract, str_hash, tuple_run[1], tuple_run[0]
                )
                yield stamp_source_etag(df_stamped, str_etag, int_part)


@type_checker
def _single_member(cls_zip: ZipFile, str_name: str) -> str:
    """Return the name of the one data member of a part archive.

    Parameters
    ----------
    cls_zip : zipfile.ZipFile
        The open archive.
    str_name : str
        The archive's file name, for the error message.

    Returns
    -------
    str
        The member name.

    Raises
    ------
    ValueError
        If the archive does not hold exactly one member.
    """
    list_members = [cls_info.filename for cls_info in cls_zip.infolist() if not cls_info.is_dir()]
    if len(list_members) != 1:
        raise ValueError(f"{str_name} must hold exactly one member, found {list_members}")
    return list_members[0]
