"""Zip extraction seam — idempotent, optional, password-aware.

A reusable place for "unzip this file (maybe password-protected), but only when needed".
``zipfile`` is stdlib, so no coupling seam is strictly required — this module exists for the
*behaviour*: opt-in extraction, idempotent (skip when the target is already present), and a
caller-supplied password (from ``.env``), never hard-coded.

The ``*_to_memory`` functions are the on-disk trio's counterparts for when the extracted
bytes are consumed immediately (parsed, streamed, hashed) and never need to hit the disk —
returning all members, a subset, or a single member.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import zipfile


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


@type_checker
def _require_zip(path_zip: Path) -> None:
    """Raise when the archive is absent, so every entry point fails the same way.

    The guard was written five times, which is five chances for the message or the exception
    type to drift while each caller keeps passing its own test.

    Parameters
    ----------
    path_zip : pathlib.Path
        The archive that must exist.

    Returns
    -------
    None

    Raises
    ------
    FileNotFoundError
        When ``path_zip`` does not exist.
    """
    if not path_zip.exists():
        raise FileNotFoundError(f"Zip not found: {path_zip}")


@type_checker
def unzip_if_needed(
    path_zip: Path,
    path_target: Path,
    bool_enabled: bool,
    str_password: str | None = None,
) -> bool:
    """Extract ``path_zip`` into the target's directory, when enabled and absent.

    Extraction happens only when **all** hold: ``bool_enabled`` is true, the target file is
    not already present, and the zip exists. Otherwise nothing is done (the caller decides
    what an absent target means — e.g. notify + fallback).

    Parameters
    ----------
    path_zip : pathlib.Path
        The (password-protected) zip to extract.
    path_target : pathlib.Path
        The file expected after extraction; if it already exists, extraction is skipped
        (idempotent). Its parent directory is the extraction destination.
    bool_enabled : bool
        Config switch: only extract when true.
    str_password : str, optional
        ZipCrypto password (from ``.env``); ``None`` for an unencrypted zip.

    Returns
    -------
    bool
        ``True`` when extraction was performed, ``False`` when skipped (target already
        present, extraction disabled, or the zip is absent).
    """
    bool_should_extract = bool_enabled and not path_target.exists() and path_zip.exists()
    if not bool_should_extract:
        return False
    extract_all(path_zip, path_target.parent, str_password)
    return True


@type_checker
def extract_members(path_zip: Path, path_dest_dir: Path, list_members: list[str]) -> list[Path]:
    """Extract only the named members of ``path_zip`` into ``path_dest_dir``.

    Members absent from the archive are silently skipped (the caller decides what a missing
    member means). Used for large multi-file archives where only a few files are needed.

    Parameters
    ----------
    path_zip : pathlib.Path
        The zip to read.
    path_dest_dir : pathlib.Path
        Destination directory (created if absent).
    list_members : list of str
        The archive member names to extract.

    Returns
    -------
    list of pathlib.Path
        The extracted file paths (only those members that were present).

    Raises
    ------
    FileNotFoundError
        If ``path_zip`` does not exist.
    """
    _require_zip(path_zip)
    path_dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path_zip) as cls_zip:
        set_names = set(cls_zip.namelist())
        return [
            Path(cls_zip.extract(str_member, path_dest_dir))
            for str_member in list_members
            if str_member in set_names
        ]


@type_checker
def extract_all(
    path_zip: Path, path_dest_dir: Path, str_password: str | None = None
) -> list[Path]:
    """Extract every member of ``path_zip`` into ``path_dest_dir``.

    Parameters
    ----------
    path_zip : pathlib.Path
        The zip to extract.
    path_dest_dir : pathlib.Path
        Destination directory (created if absent).
    str_password : str, optional
        ZipCrypto password; ``None`` for an unencrypted zip.

    Returns
    -------
    list of pathlib.Path
        The extracted file paths, in archive order.

    Raises
    ------
    FileNotFoundError
        If ``path_zip`` does not exist.
    """
    _require_zip(path_zip)
    path_dest_dir.mkdir(parents=True, exist_ok=True)
    bytes_pwd = str_password.encode() if str_password else None
    with zipfile.ZipFile(path_zip) as cls_zip:
        cls_zip.extractall(path_dest_dir, pwd=bytes_pwd)
        return [path_dest_dir / str_name for str_name in cls_zip.namelist()]


@type_checker
def find_member(list_members: list[Path], str_name: str) -> Path:
    """Select one extracted member by its **exact** file name.

    Regulatory archives routinely ship members whose names *prefix one another* — e.g.
    ``lamina_fi_202601.csv`` alongside ``lamina_fi_carteira_202601.csv`` and
    ``lamina_fi_rentab_ano_202601.csv``. A ``startswith("lamina_fi_")`` scan therefore
    returns whichever member the archive happened to list first, and the caller parses a
    wholly different layout. The failure is **not loud**: the wrong member may still satisfy
    a lax contract. Even a longer prefix is correct only by accident of the literal chosen —
    the next member the publisher adds can re-break it. Matching the exact name removes the
    class of bug rather than the instance, and the caller almost always knows the reference
    month, so it can name the member exactly.

    Parameters
    ----------
    list_members : list of pathlib.Path
        Extracted paths, as returned by :func:`extract_all` or :func:`extract_members`.
    str_name : str
        The member's exact file name, no directory component (e.g. ``"lamina_fi_202601.csv"``).

    Returns
    -------
    pathlib.Path
        The member whose file name equals ``str_name``.

    Raises
    ------
    ValueError
        If no member matches, naming the wanted member and listing what was available.
    """
    path_found = next(
        (path_member for path_member in list_members if path_member.name == str_name), None
    )
    if path_found is None:
        list_available = sorted(path_member.name for path_member in list_members)
        raise ValueError(f"Archive member not found: {str_name!r}. Available: {list_available}")
    return path_found


@type_checker
def extract_all_to_memory(path_zip: Path, str_password: str | None = None) -> dict[str, bytes]:
    """Read every file member of ``path_zip`` into memory, never touching disk.

    The in-memory counterpart of :func:`extract_all` — for when the extracted bytes are
    consumed immediately (parsed, streamed, hashed) and persisting them would be wasteful or
    unwanted. Directory entries are skipped; only file members are returned.

    Parameters
    ----------
    path_zip : pathlib.Path
        The zip to read.
    str_password : str, optional
        ZipCrypto password; ``None`` for an unencrypted zip.

    Returns
    -------
    dict of {str: bytes}
        Member name → its decompressed bytes, for every file member.

    Raises
    ------
    FileNotFoundError
        If ``path_zip`` does not exist.
    """
    _require_zip(path_zip)
    bytes_pwd = str_password.encode() if str_password else None
    with zipfile.ZipFile(path_zip) as cls_zip:
        return {
            str_name: cls_zip.read(str_name, pwd=bytes_pwd)
            for str_name in cls_zip.namelist()
            if not str_name.endswith("/")
        }


@type_checker
def extract_members_to_memory(
    path_zip: Path, list_members: list[str], str_password: str | None = None
) -> dict[str, bytes]:
    """Read only the named members of ``path_zip`` into memory (absent members skipped).

    The in-memory counterpart of :func:`extract_members` — for large multi-file archives
    where only a few members are needed and the bytes are consumed in place. Members absent
    from the archive are silently skipped (the caller decides what a missing member means).

    Parameters
    ----------
    path_zip : pathlib.Path
        The zip to read.
    list_members : list of str
        The archive member names to read.
    str_password : str, optional
        ZipCrypto password; ``None`` for an unencrypted zip.

    Returns
    -------
    dict of {str: bytes}
        Member name → its decompressed bytes, for each requested member that was present.

    Raises
    ------
    FileNotFoundError
        If ``path_zip`` does not exist.
    """
    _require_zip(path_zip)
    bytes_pwd = str_password.encode() if str_password else None
    with zipfile.ZipFile(path_zip) as cls_zip:
        set_names = set(cls_zip.namelist())
        return {
            str_member: cls_zip.read(str_member, pwd=bytes_pwd)
            for str_member in list_members
            if str_member in set_names
        }


@type_checker
def extract_member_to_memory(
    path_zip: Path, str_member: str, str_password: str | None = None
) -> bytes:
    """Read a single named member of ``path_zip`` into memory.

    The single-member in-memory read — for pulling one known file out of an archive without
    writing anything to disk.

    Parameters
    ----------
    path_zip : pathlib.Path
        The zip to read.
    str_member : str
        The archive member name to read.
    str_password : str, optional
        ZipCrypto password; ``None`` for an unencrypted zip.

    Returns
    -------
    bytes
        The decompressed bytes of ``str_member``.

    Raises
    ------
    FileNotFoundError
        If ``path_zip`` does not exist.
    KeyError
        If ``str_member`` is not present in the archive.
    """
    _require_zip(path_zip)
    bytes_pwd = str_password.encode() if str_password else None
    with zipfile.ZipFile(path_zip) as cls_zip:
        if str_member not in set(cls_zip.namelist()):
            raise KeyError(f"Member {str_member!r} not in {path_zip}")
        return cls_zip.read(str_member, pwd=bytes_pwd)
