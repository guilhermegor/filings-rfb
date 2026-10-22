"""Import a source's sidecar schema/metadata descriptor when it publishes one.

Many open-data portals ship a **sidecar descriptor** next to the data — a data dictionary that
declares the field names, descriptions, types, and sizes. CVM, for example, ships
``META/meta_<dataset>.txt`` beside each dataset. When a source provides one it is the
*authoritative* schema (better than sniffing the artifact header), and it does two jobs:

1. **Dev-time** — define the `FileContract` from it (column names, and later types/scales).
2. **Runtime** — fetch it alongside the data and persist it to the bronze layer, so a datalake
   can diff it across runs and detect (and attribute) an upstream schema change.

This module is a **generic seam**, not a CVM parser: the *locator* (data URL → descriptor URL)
and the *download transport* are injectable, and :func:`cvm_meta_url` ships as the documented
**reference** locator. A source that publishes no sidecar is a first-class case — the fetch
returns ``None`` (never raises), so a reader falls back to inferring the contract from the real
artifact without special-casing.

The transport defaults to :func:`utils.http_downloader.download_file` (the one network-download
seam), so tests mock at that boundary and the autouse network guard stays satisfied.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from filings_rfb._internal.utils.http_downloader import download_file


if TYPE_CHECKING:
    from typing import TypeVar

    _F = TypeVar("_F", bound=Callable[..., object])

    def type_checker(fn: _F) -> _F:
        """Type-only stub — see src/utils/CLAUDE.md."""
else:
    try:
        from filings_rfb._internal.utils.typing import type_checker
    except ModuleNotFoundError:
        from filings_rfb._internal.utils.typing import type_checker


_INT_MIN_DESCRIPTOR_LINES = 2


@type_checker
def cvm_meta_url(str_base_url: str, str_dataset_key: str) -> str:
    """Build a CVM sidecar-descriptor URL from a dataset's base URL (the reference locator).

    CVM publishes ``<base>/META/meta_<dataset>.txt`` beside each dataset. This is the documented
    reference implementation of a *locator* — a `str -> str` (here `(base, key) -> url`) mapping a
    dataset to its descriptor. Other sources publish sidecars under different conventions (a
    ``.dtd``/``.xsd``, an OpenAPI doc, a data-dictionary page); write a sibling locator for those
    and pass its result to :func:`fetch_sidecar_text`.

    Parameters
    ----------
    str_base_url : str
        The dataset's base/directory URL (the portion before the data file) — for CVM, the
        host ``https://dados.cvm.gov.br`` followed by the path ``/dados/FI/DOC/CAD``.
        ⚠️ Written as host + path rather than one URL on purpose: the ``check-urls`` hook
        fetches every fetchable docstring URL and that directory answers 404 to a scripted
        probe, while the host answers 200. It skips host-only URLs, which is why this form
        passes and the joined one does not. See ``bin/CLAUDE.md`` → "Docstring URL convention".
    str_dataset_key : str
        The dataset key naming the descriptor (``cad_fi`` -> ``meta_cad_fi.txt``).

    Returns
    -------
    str
        The descriptor URL ``<base>/META/meta_<key>.txt``.
    """
    return f"{str_base_url.rstrip('/')}/META/meta_{str_dataset_key}.txt"


@type_checker
def fetch_sidecar_text(
    str_descriptor_url: str,
    path_dest: Path,
    fn_download: Callable[[str, Path], Path] = download_file,
    str_encoding: str = "utf-8",
) -> str | None:
    """Fetch a sidecar descriptor to the bronze layer and return its text, or ``None`` if absent.

    Persists the descriptor bytes to ``path_dest`` (the ``path_raw`` bronze location) as a tracked
    artifact — the *runtime* half of the metadata loop — and returns the decoded text for
    *dev-time* contract definition. **Tolerates absence:** not every source ships a sidecar, so a
    failed fetch (a 404 / any :class:`OSError` from the transport) returns ``None`` rather than
    raising; the reader then falls back to inferring the contract from the real artifact.

    Parameters
    ----------
    str_descriptor_url : str
        The descriptor URL (e.g. from :func:`cvm_meta_url`).
    path_dest : pathlib.Path
        Bronze-layer path to persist the descriptor to (the ``path_raw`` seam). Its parent is
        created by the transport when missing.
    fn_download : Callable[[str, pathlib.Path], pathlib.Path], optional
        The download transport, by default
        :func:`utils.http_downloader.download_file`. Injected so
        tests mock at the one network boundary.
    str_encoding : str, optional
        Text encoding for decoding the persisted descriptor (default ``"utf-8"``; pass
        ``"ISO-8859-1"`` for Latin-1 dumps such as CVM's).

    Returns
    -------
    str or None
        The descriptor text, or ``None`` when the source publishes no sidecar.
    """
    try:
        path_written = fn_download(str_descriptor_url, path_dest)
    except OSError:
        return None
    return path_written.read_text(encoding=str_encoding)


@type_checker
def parse_sidecar_metadata(str_text: str, str_sep: str = ";") -> dict[str, dict[str, str]]:
    """Parse a delimited sidecar descriptor into ``{field: {column: value}}``.

    Header-driven and format-agnostic: the first non-empty line names the columns; every later
    non-empty line is a field, keyed by its **first** column, mapping the *remaining* columns by
    their header name. For a CVM ``meta_<x>.txt`` (``;``-separated, columns like
    ``Campo;Descrição;Tipo;Tamanho``) this yields ``{campo: {"Descrição": ..., "Tipo": ...,
    "Tamanho": ...}}`` — the descriptor is the authoritative source of field names, and later of
    types/scales.

    Parameters
    ----------
    str_text : str
        The raw descriptor text (from :func:`fetch_sidecar_text`).
    str_sep : str, optional
        Column delimiter (default ``";"``, the CVM open-data convention).

    Returns
    -------
    dict of {str: dict of {str: str}}
        Field key -> {remaining header -> cell value}. Empty when the text has no data rows.
    """
    list_lines = [line for line in str_text.splitlines() if line.strip()]
    if len(list_lines) < _INT_MIN_DESCRIPTOR_LINES:
        return {}
    list_headers = [cell.strip() for cell in list_lines[0].split(str_sep)]
    list_rows = [[cell.strip() for cell in str_line.split(str_sep)] for str_line in list_lines[1:]]
    return {
        list_cells[0]: {
            str_header: (list_cells[int_idx] if int_idx < len(list_cells) else "")
            for int_idx, str_header in enumerate(list_headers[1:], start=1)
        }
        for list_cells in list_rows
    }
