"""Raw-artifact workspace seam (bronze-layer retention).

Every ingestion reader downloads a raw artifact from its source and parses it. Two callers
want two different things from those bytes:

- an **interactive** consumer wants a DataFrame and nothing else — the bytes are scratch and
  should leave no residue on disk;
- a **datalake** ingestion routine wants the artifact *kept*, byte-for-byte, as the bronze
  layer's authoritative record of what the source actually served.

Both are the same read with a different disposal policy, so they collapse into **one branch
in one place**. Without this seam each reader re-decides it, and the ones written under
deadline pick "scratch" — which is unrecoverable, because the source has already moved on.

Pass ``None`` and the artifact lands in a :class:`tempfile.TemporaryDirectory` destroyed on
exit; pass a path and the directory is created (parents included) and left in place, holding
the downloaded artifact and everything extracted from it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING


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


@contextmanager
@type_checker
def raw_workspace(path_raw: Path | None = None) -> Iterator[Path]:
    """Yield the directory this read's raw artifacts belong in.

    Parameters
    ----------
    path_raw : pathlib.Path or None, optional
        Bronze-layer destination. ``None`` (the default) means the bytes are scratch: a
        temporary directory is used and destroyed on exit. A path means the artifact is
        kept — the directory is created if missing, parents included, and left in place.

    Yields
    ------
    pathlib.Path
        An existing directory to write the downloaded artifact (and anything extracted
        from it) into.

    Examples
    --------
    >>> with raw_workspace() as path_dir:  # scratch — gone afterwards
    ...     path_dir.is_dir()
    True
    """
    if path_raw is None:
        with tempfile.TemporaryDirectory() as str_tmp:
            yield Path(str_tmp)
        return
    path_raw.mkdir(parents=True, exist_ok=True)
    yield path_raw
