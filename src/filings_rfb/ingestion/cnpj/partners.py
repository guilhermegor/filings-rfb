"""Read the RFB CNPJ ``Socios`` (partners) dataset, chunk by chunk.

Decisions on the sensitive fields, each pinned by a test:

* ``documento_socio`` is **verbatim**. RFB masks an individual's CPF at the source
  (``***240659**``: only the six middle digits are published) and publishes a legal entity's
  CNPJ in full. The reader never unmasks, pads, reformats or guesses a document, and never
  logs one. The project's identifier-masking gate only flags formatted literals
  (``123.456.789-01``) compared against a column, so the RFB mask is not its concern.
* ``documento_representante`` equal to ``***000000**`` means "no legal representative" and
  becomes null; a real masked representative CPF stays verbatim. The sentinel rule never
  applies to ``documento_socio``.
* ``qualificacao_socio`` / ``qualificacao_representante`` stay two-character text codes
  (``"00"`` is kept, it is the published "not informed" code), ready to join to the
  ``Qualificacoes`` lookup read by :func:`filings_rfb.read_lookup`. No label join is done
  here: it would be a second source of truth and would drop unknown codes.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pandas as pd

from filings_rfb._internal.config.contracts import CNPJ_PARTNERS
from filings_rfb._internal.utils.compact_dates import parse_compact_dates
from filings_rfb._internal.utils.typing import type_checker
from filings_rfb.ingestion.cnpj._multipart import DEFAULT_CHUNK_ROWS, iter_part_chunks


__all__ = ["read_partners"]

_PREFIX: str = "Socios"
_COL_REPRESENTATIVE_DOC: str = "documento_representante"
_NO_REPRESENTATIVE: str = "***000000**"
_COL_ENTRY_DATE: str = "data_entrada"
_DTYPES: dict[str, str] = {
    str_col: "str" for str_col in CNPJ_PARTNERS.tuple_required if str_col != _COL_ENTRY_DATE
}


@type_checker
def read_partners(
    str_month: str,
    int_chunk_rows: int = DEFAULT_CHUNK_ROWS,
    path_workdir: Path | None = None,
) -> Iterator[pd.DataFrame]:
    """Yield the ``Socios`` rows of a reference month, one typed DataFrame per chunk.

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
        The eleven published columns as text (documents verbatim, see the module docstring),
        except ``data_entrada``, which is ``datetime.date`` (``00000000`` and blank are null),
        plus the provenance columns, ``source_etag`` and ``part_index``.

    Raises
    ------
    FileNotFoundError
        If any of the ten parts is not published for the month (raised on first iteration).
    ValueError
        If ``data_entrada`` is neither ``YYYYMMDD`` nor a null marker.
    """
    return iter_part_chunks(
        str_month,
        _PREFIX,
        CNPJ_PARTNERS,
        _DTYPES,
        int_chunk_rows=int_chunk_rows,
        path_workdir=path_workdir,
        fn_prepare=_prepare_partners,
    )


@type_checker
def _prepare_partners(df_chunk: pd.DataFrame) -> pd.DataFrame:
    """Null the "no representative" sentinel and parse ``data_entrada``.

    Parameters
    ----------
    df_chunk : pd.DataFrame
        A named raw chunk.

    Returns
    -------
    pd.DataFrame
        A copy whose representative document is null where RFB published ``***000000**`` and
        whose entry date is ``datetime.date`` or null.
    """
    ser_doc = df_chunk[_COL_REPRESENTATIVE_DOC]
    ser_clean = ser_doc.mask(ser_doc == _NO_REPRESENTATIVE)
    return df_chunk.assign(
        **{
            _COL_REPRESENTATIVE_DOC: ser_clean,
            _COL_ENTRY_DATE: parse_compact_dates(df_chunk[_COL_ENTRY_DATE]),
        }
    )
