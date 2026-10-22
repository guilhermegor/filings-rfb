"""Provenance stamping for ingested DataFrames (downloaded files or webscrapes).

Every DataFrame produced by ingestion carries a fixed set of **provenance** columns,
appended after its source columns, so a datalake's bronze layer is self-describing and
drift-detectable: given a stored row you can answer *where it came from*, *how stale it is*,
*which dataset and package version produced it*, and *whether the source artifact changed*.

The seam is deliberately split so it composes with the raw-artifact-persistence pattern:

- :func:`hash_artifact` — the **I/O half**: streams a file's bytes into a ``sha256`` digest.
  The reader (which holds the downloaded file) calls this *inside* its temp-workspace block,
  before the workspace is torn down.
- :func:`stamp_provenance` — the **pure half**: a frame transform with no I/O. It takes the
  already-computed content hash (and the package version) as arguments, so a reader that
  finishes building its frame *after* the workspace closes (e.g. a post-extraction merge) can
  still stamp it. The one non-determinism — a per-call ``ingestion_run_id`` UUID shared by
  every row of one read — is generated here.

The column *names* live on :class:`utils.tabular_reader.FileContract`
(``PROVENANCE_COLUMNS``) so the contract describes the full output shape
(``output_columns``); they are not in ``tuple_required`` (that validates the source artifact,
which lacks them), so stamping happens **after** contract validation. Text provenance columns
use the nullable ``string`` dtype, consistent with the dtypes lesson; ``updated_at`` is
**tz-aware UTC** (lossless, unambiguous) — a sink that cannot store tz-aware timestamps
normalises at the warehouse load boundary, never here and never via a per-reader flag.

Enforcement: ``bin/check_provenance.py`` (wired into both ``.pre-commit-config.yaml`` and
``.github/workflows/tests.yaml``) asserts that every ``src/`` module referencing ``read_table``
also references ``stamp_provenance`` — so a contract-checked read cannot ship without a stamp.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING
import uuid

import pandas as pd

from filings_rfb._internal.utils.tabular_reader import FileContract  # noqa: TID251


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


_HASH_CHUNK_BYTES = 1 << 20


@type_checker
def hash_artifact(path_file: Path) -> str:
    """Return the ``sha256`` hex digest of a file's bytes, read in streamed chunks.

    Parameters
    ----------
    path_file : pathlib.Path
        The downloaded source artifact to hash. Hash the *raw bytes on disk* (not the parsed
        frame) so the digest is stable across parser/pandas versions and lets the lake detect a
        changed source without re-parsing.

    Returns
    -------
    str
        The lowercase hex ``sha256`` digest.

    Raises
    ------
    FileNotFoundError
        If ``path_file`` does not exist (fail fast at the read boundary).
    """
    cls_digest = hashlib.sha256()
    with path_file.open("rb") as fh:
        for bytes_chunk in iter(lambda: fh.read(_HASH_CHUNK_BYTES), b""):
            cls_digest.update(bytes_chunk)
    return cls_digest.hexdigest()


@type_checker
def resolve_package_version(str_distribution: str) -> str:
    """Resolve an installed distribution's version, tolerating an uninstalled tree.

    Kept out of :func:`stamp_provenance` (which must stay a pure frame transform): the reader
    resolves the version once and passes it in, exactly as it passes the content hash.

    Parameters
    ----------
    str_distribution : str
        The installed distribution name (e.g. the project's package name).

    Returns
    -------
    str
        The resolved version, or ``"0.0.0"`` when the distribution is not installed (a source
        checkout run without ``pip install`` still stamps, just with the stub version).
    """
    try:
        return metadata.version(str_distribution)
    except metadata.PackageNotFoundError:
        return "0.0.0"


@type_checker
def stamp_provenance(
    df_input: pd.DataFrame,
    str_url: str,
    cls_contract: FileContract,
    str_content_hash: str,
    str_package_version: str,
) -> pd.DataFrame:
    """Append the provenance columns to an ingested frame (pure transform, no I/O).

    Returns a **new** frame (the input is not mutated) with
    :attr:`~utils.tabular_reader.FileContract.PROVENANCE_COLUMNS` appended after the source
    columns. Call it **after** the contract check and dtype coercion, once per read: a single
    ``ingestion_run_id`` UUID is generated here and shared by every row of the read.

    Parameters
    ----------
    df_input : pd.DataFrame
        The typed, contract-validated frame to stamp.
    str_url : str
        The exact source URL the rows came from.
    cls_contract : FileContract
        The contract the frame satisfied; its ``str_source_key`` disambiguates rows when
        several readers share one URL (e.g. N members of one ZIP) or many datasets share a
        bronze table.
    str_content_hash : str
        The ``sha256`` of the downloaded artifact bytes (from :func:`hash_artifact`), shared by
        every row so the lake can detect a changed source without re-parsing.
    str_package_version : str
        The producing package's version (from :func:`resolve_package_version`), so rows made by
        a buggy version are identifiable and re-ingestible after a fix.

    Returns
    -------
    pd.DataFrame
        A copy of ``df_input`` with the six provenance columns appended (text columns as the
        nullable ``string`` dtype; ``updated_at`` as tz-aware UTC).
    """
    dt_fetched = datetime.now(UTC)
    str_run_id = _new_run_id()
    dict_text_provenance = {
        "url": str_url,
        "source_key": cls_contract.str_source_key,
        "package_version": str_package_version,
        "ingestion_run_id": str_run_id,
        "content_hash": str_content_hash,
    }
    df_stamped = df_input.copy()
    for str_col, str_value in dict_text_provenance.items():
        df_stamped[str_col] = pd.array([str_value] * len(df_stamped), dtype="string")
    df_stamped["updated_at"] = pd.Series(
        [dt_fetched] * len(df_stamped), index=df_stamped.index, dtype="datetime64[ns, UTC]"
    )
    return df_stamped[[*df_input.columns, *cls_contract.PROVENANCE_COLUMNS]]


@type_checker
def _new_run_id() -> str:
    """Return a fresh UUID4 string identifying one ingestion read.

    Isolated so a test can monkeypatch it to a deterministic value.

    Returns
    -------
    str
        A new random UUID as a string.
    """
    return str(uuid.uuid4())
