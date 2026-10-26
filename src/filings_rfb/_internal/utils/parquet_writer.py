"""Chunked Parquet writing seam (``pyarrow``, an optional dependency).

The seam knows the vendor, the callers do not: a dataset exporter feeds DataFrame chunks to
:class:`ParquetChunkWriter` and never imports ``pyarrow``. ``pyarrow`` ships only in the
``filings-rfb[parquet]`` extra, so it is imported **lazily**, at construction, and its absence
raises an :class:`ImportError` that names the extra.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType, TracebackType
from typing import Any

import pandas as pd

from filings_rfb._internal.utils.typing import TypeChecker, type_checker


__all__ = ["ParquetChunkWriter"]

_MSG_NEEDS_PYARROW: str = (
    "writing Parquet needs pyarrow; install the optional extra: "
    "pip install 'filings-rfb[parquet]' or poetry add 'filings-rfb[parquet]'"
)
_DECIMAL_PRECISION: int = 38


@type_checker
def _load_pyarrow() -> tuple[ModuleType, ModuleType]:
    """Import ``pyarrow`` and ``pyarrow.parquet``, or explain how to install them.

    Returns
    -------
    tuple[ModuleType, ModuleType]
        ``pyarrow`` and ``pyarrow.parquet``.

    Raises
    ------
    ImportError
        If ``pyarrow`` is not installed; the message names the ``filings-rfb[parquet]`` extra.
    """
    try:
        import pyarrow as pa  # noqa: PLC0415 — optional extra, imported only when writing
        import pyarrow.parquet as pq  # noqa: PLC0415
    except ImportError as cls_err:
        raise ImportError(_MSG_NEEDS_PYARROW) from cls_err
    return pa, pq


class ParquetChunkWriter(metaclass=TypeChecker):
    """Write DataFrame chunks into one Parquet file, with a schema fixed by the first chunk.

    Parameters
    ----------
    path_dest : pathlib.Path
        The Parquet file to write; its parent is created.
    dict_decimal_scales : dict of {str: int}
        Columns holding ``Decimal`` objects mapped to the fractional digits to store them with
        (``decimal128(38, scale)``). Pinned up front because a type inferred per chunk would
        differ between chunks and the writer would reject the second one; a value with more
        fractional digits raises instead of being rounded.

    Raises
    ------
    ImportError
        If ``pyarrow`` is missing (see :func:`_load_pyarrow`).
    """

    def __init__(self, path_dest: Path, dict_decimal_scales: dict[str, int]) -> None:
        self._pa, self._pq = _load_pyarrow()
        self._path_dest = path_dest
        self._dict_decimal_scales = dict_decimal_scales
        self._cls_schema: Any = None
        self._cls_writer: Any = None

    def write(self, df_chunk: pd.DataFrame) -> None:
        """Append one chunk, opening the file (and fixing the schema) on the first call.

        Parameters
        ----------
        df_chunk : pd.DataFrame
            The rows to append.
        """
        if self._cls_writer is None:
            self._open(df_chunk)
        self._cls_writer.write_table(
            self._pa.Table.from_pandas(df_chunk, schema=self._cls_schema, preserve_index=False)
        )

    def close(self) -> None:
        """Finish the file; a no-op when nothing was written."""
        if self._cls_writer is not None:
            self._cls_writer.close()
            self._cls_writer = None

    def __enter__(self) -> ParquetChunkWriter:
        """Return the writer for use in a ``with`` block.

        Returns
        -------
        ParquetChunkWriter
            This writer.
        """
        return self

    def __exit__(
        self,
        cls_type: type[BaseException] | None,
        cls_value: BaseException | None,
        cls_traceback: TracebackType | None,
    ) -> None:
        """Close the file when the ``with`` block ends, even on an error.

        Parameters
        ----------
        cls_type : type or None
            The exception type, if any.
        cls_value : BaseException or None
            The exception, if any.
        cls_traceback : types.TracebackType or None
            The traceback, if any.
        """
        self.close()

    def _open(self, df_first: pd.DataFrame) -> None:
        """Infer the schema from the first chunk, pin the decimal columns, open the file.

        Parameters
        ----------
        df_first : pd.DataFrame
            The first chunk.
        """
        cls_schema = self._pa.Schema.from_pandas(df_first, preserve_index=False)
        for str_col, int_scale in self._dict_decimal_scales.items():
            cls_field = self._pa.field(str_col, self._pa.decimal128(_DECIMAL_PRECISION, int_scale))
            cls_schema = cls_schema.set(cls_schema.get_field_index(str_col), cls_field)
        self._path_dest.parent.mkdir(parents=True, exist_ok=True)
        self._cls_schema = cls_schema
        self._cls_writer = self._pq.ParquetWriter(self._path_dest, cls_schema)
