"""Unit tests for the in-memory zip extraction seam."""

from collections import deque
from pathlib import Path
import zipfile

import pytest

from filings_rfb._internal.utils.zip_extractor import extract_all_to_memory


def _write_zip_with_names(path_zip: Path, list_names: list[str]) -> Path:
    """Write an archive with one member per name, repeats included.

    Parameters
    ----------
    path_zip : pathlib.Path
        Where to write the archive.
    list_names : list of str
        Member names in order; a repeated name makes a duplicate member.

    Returns
    -------
    pathlib.Path
        ``path_zip``.
    """
    with zipfile.ZipFile(path_zip, "w") as cls_zip:
        deque(map(cls_zip.writestr, list_names, map(str.encode, list_names)), maxlen=0)
    return path_zip


def test_extract_all_to_memory_distinct_members_returns_name_to_bytes(tmp_path: Path) -> None:
    """Distinct member names map to their own bytes."""
    path_zip = _write_zip_with_names(tmp_path / "ok.zip", ["a", "b"])
    assert extract_all_to_memory(path_zip) == {"a": b"a", "b": b"b"}


@pytest.mark.filterwarnings("ignore:Duplicate name")
def test_extract_all_to_memory_duplicate_names_raises(tmp_path: Path) -> None:
    """Two members with one name raise instead of silently dropping a copy."""
    path_zip = _write_zip_with_names(tmp_path / "dup.zip", ["a", "a"])
    with pytest.raises(ValueError, match="duplicate member names"):
        extract_all_to_memory(path_zip)
