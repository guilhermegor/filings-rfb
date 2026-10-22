"""Daily on-disk cache for a vendor artifact that does not change intraday.

Some sources publish once a day and then serve the same bytes until tomorrow — a regulator's
daily register, a reference table, an official CSV dump. Re-fetching one of those on every run
(or worse, once per entity) reads as scraping abuse and gets the source IP **blocked**. For a
routine whose whole purpose is to reconcile against that regulator, a block means **no runs at
all**, and it outlives the session, so nobody can simply retry.

The asymmetry is what decides it: the worst case of caching here is a one-day-stale file the
source did not change anyway; the worst case of not caching is losing access.

⚠️ **Only for a source whose data is stable for the whole reference day.** State the change
granularity in the calling reader's docstring. A source that revises intraday must not use
this — a cache cannot represent a value that moved after it was written.

⚠️ The cache is keyed by the **data's reference date**, never by wall-clock time. A run at
23:59 and one at 00:01 asking for the same reference day must hit the same file; keying on
"today" silently re-downloads at midnight and, worse, splits one logical day across two files.

**Cache policy belongs to the caller's intent, not to the client.** A scheduled drift job wants
the opposite of this module (see ``bin/check_contract_drift.py``): a cached read cannot detect
drift, and a partially-populated cache gets reported *as* drift. That is why the switch is an
explicit argument rather than an ambient default — pass ``bool_use_cache=False`` (or call
``utils.http_downloader.download_file`` directly) from any caller whose question is "did the
source change?".
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
import os
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from filings_rfb._internal.utils.http_downloader import download_file
from filings_rfb._internal.utils.retry import LogEmitter


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


@type_checker
def _is_usable_cache_entry(path_cached: Path) -> bool:
    """Return whether a cached artifact may be served as a hit.

    ⚠️ A zero-byte file counts as a MISS, not a hit. ``write_bytes`` is not atomic, so an
    interrupted run can leave an empty file behind — and serving it would hand the caller a
    valid-looking path to nothing, which fails much later and far away.

    Parameters
    ----------
    path_cached : pathlib.Path
        The candidate cache entry.

    Returns
    -------
    bool
        ``True`` only for an existing, non-empty file.
    """
    return path_cached.is_file() and path_cached.stat().st_size > 0


@type_checker
def daily_cache_path(
    path_cache_dir: Path, str_key: str, dt_reference: date, str_suffix: str
) -> Path:
    """Build the cache path for one source on one reference day.

    Parameters
    ----------
    path_cache_dir : pathlib.Path
        Directory the cached artifacts live in.
    str_key : str
        Kebab-case source name, e.g. ``"cvm-daily-register"``.
    dt_reference : datetime.date
        The **data's** reference date — not the moment of the run.
    str_suffix : str
        File extension including the dot, e.g. ``".csv"``; may be empty.

    Returns
    -------
    pathlib.Path
        ``<dir>/<key>_<YYYYMMDD><suffix>`` — the house naming convention, minus the time
        component, because the whole point is that one reference day is one file.
    """
    return path_cache_dir / f"{str_key}_{dt_reference:%Y%m%d}{str_suffix}"


@type_checker
def download_daily(
    str_url: str,
    path_cache_dir: Path,
    str_key: str,
    dt_reference: date,
    str_suffix: str = "",
    bool_use_cache: bool = True,
    cls_logger: LogEmitter | None = None,
    fn_download: Callable[[str, Path], Path] = download_file,
) -> Path:
    """Return the artifact for ``dt_reference``, from disk when already fetched today.

    Always logs **which branch ran** — a cache that is silent about hit-vs-network cannot be
    told from one that never engaged, and "why is this data stale?" is then unanswerable from
    the log alone.

    Parameters
    ----------
    str_url : str
        The source URL to fetch on a miss.
    path_cache_dir : pathlib.Path
        Directory the cached artifacts live in; created (parents included) on a miss rather
        than assumed to exist — the archiver may not have run yet on a fresh dated folder.
    str_key : str
        Kebab-case source name used in the cached filename.
    dt_reference : datetime.date
        The **data's** reference date, never the wall clock.
    str_suffix : str, optional
        File extension including the dot, by default ``""``.
    bool_use_cache : bool, optional
        ``True`` (default) reads an existing file for this reference day. ``False`` skips the
        READ and fetches from the network — it still WRITES, refreshing the cached copy.
    cls_logger : LogEmitter, optional
        Emitter for the branch line; defaults to :class:`utils.retry.LogEmitter`.
    fn_download : Callable[[str, pathlib.Path], pathlib.Path], optional
        The download seam, by default :func:`utils.http_downloader.download_file`. Injected so
        tests never touch the network.

    Returns
    -------
    pathlib.Path
        Path to the artifact for ``dt_reference``.

    Notes
    -----
    A miss downloads into a unique staging name inside the cache directory and then renames it
    over the final path, so the file becomes visible under its cache name only once complete.
    The zero-byte guard alone is not enough: a truncated but non-empty file — disk full, a
    killed process, or another process reading while this one writes — would be served as a hit
    and reach the parser. The rename is atomic on POSIX, and on Windows for a same-filesystem
    move, which staging inside the cache directory guarantees. The staging name carries the PID
    so two concurrent downloads cannot corrupt each other; whichever finishes last wins, and
    both wrote the same day's bytes.

    A ``datetime`` is rejected explicitly even though it satisfies the ``date`` annotation: it
    is a **subclass**, so the runtime checker accepts a wall-clock value, and it formats into a
    perfectly plausible filename — the exact failure this module exists to prevent, with nothing
    downstream to complain. One reference day is one file, so the shape that silently means
    "now" cannot be allowed in.
    """
    _require_reference_date(dt_reference)

    cls_emitter: LogEmitter = cls_logger if cls_logger is not None else LogEmitter()
    path_cached = daily_cache_path(path_cache_dir, str_key, dt_reference, str_suffix)
    str_day = f"{dt_reference:%Y-%m-%d}"

    if bool_use_cache and _is_usable_cache_entry(path_cached):
        cls_emitter.log_message(
            f"daily cache HIT for {str_key} ({str_day}): {path_cached}", "info"
        )
        return path_cached

    str_reason = "bypassed by caller" if not bool_use_cache else "miss"
    cls_emitter.log_message(
        f"daily cache {str_reason} for {str_key} ({str_day}) — downloading {str_url}", "info"
    )
    path_cache_dir.mkdir(parents=True, exist_ok=True)
    _download_and_publish(str_url, path_cached, fn_download)
    return path_cached


@type_checker
def _require_reference_date(dt_reference: date) -> None:
    """Reject a datetime where a reference DATE is required.

    The annotation cannot enforce this — ``datetime`` is a subclass of ``date`` — and the
    distinction is load-bearing: a wall-clock value keys the cache on when the run happened
    rather than on what the data is, so every run gets its own entry and the cache never hits.

    Parameters
    ----------
    dt_reference : datetime.date
        The value to check.

    Returns
    -------
    None

    Raises
    ------
    TypeError
        If ``dt_reference`` is a ``datetime``.
    """
    if isinstance(dt_reference, datetime):
        raise TypeError(
            "dt_reference must be a date (the DATA's reference day), not a datetime: a "
            "wall-clock value keys the cache on when the run happened, not on what the data is"
        )


@type_checker
def _download_and_publish(
    str_url: str, path_cached: Path, fn_download: Callable[[str, Path], Path]
) -> None:
    """Download to a staging file and publish it atomically under the cache name.

    The rename is what makes the entry appear only once it is COMPLETE: ``write_bytes`` is
    not atomic, so a download interrupted mid-write would otherwise leave a truncated file
    sitting under the final name, where the next run serves it as a hit.

    Parameters
    ----------
    str_url : str
        The source URL.
    path_cached : pathlib.Path
        Final cache path; created by rename once the download completed.
    fn_download : Callable[[str, pathlib.Path], pathlib.Path]
        The download transport.

    Returns
    -------
    None

    Raises
    ------
    OSError
        If the download produced a missing or empty artifact.
    """
    path_staging = path_cached.with_name(f"{path_cached.name}.{uuid4().hex}.part")
    try:
        path_written = fn_download(str_url, path_staging)
        if not path_written.is_file() or path_written.stat().st_size == 0:
            raise OSError(f"daily cache download produced an empty artifact for {str_url!r}")
        os.replace(path_written, path_cached)
    finally:
        path_staging.unlink(missing_ok=True)
