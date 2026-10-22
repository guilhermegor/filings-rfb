"""Unit tests for the migration-slug verb gate (blueprintx#375; offline, no git/network).

The negative control is the point, same rule as ``test_rmw_race_gate.py``: a should-fail
witness on a real bad slug proves the gate actually fires, not just that it imports.
"""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest


_BIN = Path(__file__).resolve().parents[2] / "bin"


def _load(str_name: str) -> ModuleType:
    """Load a ``bin/`` script by path (``bin/`` is not a package).

    Parameters
    ----------
    str_name : str
        Module stem under ``bin/``.

    Returns
    -------
    ModuleType
        The imported module.
    """
    cls_spec = importlib.util.spec_from_file_location(str_name, _BIN / f"{str_name}.py")
    cls_module = importlib.util.module_from_spec(cls_spec)
    sys.modules[str_name] = cls_module
    cls_spec.loader.exec_module(cls_module)
    return cls_module


gate = _load("check_migration_slugs")


def _migration_file(path_dir: Path, str_name: str, str_body: str = "") -> Path:
    """Write a migration version file and return its path.

    Parameters
    ----------
    path_dir : pathlib.Path
        Directory to write into.
    str_name : str
        Filename, including extension.
    str_body : str
        File contents (default empty — only the filename matters to most tests).

    Returns
    -------
    pathlib.Path
        The written file.
    """
    path_file = path_dir / str_name
    path_file.write_text(str_body, encoding="utf-8")
    return path_file


def test_non_verb_slug_is_reported(tmp_path: Path) -> None:
    """A slug that does not lead with a known verb must fail the gate."""
    path_file = _migration_file(tmp_path, "20260913_a1b2c3d4e5f6_users_table.py")

    assert gate.check_file(path_file) == 1


@pytest.mark.parametrize("str_which", ["file", "slug"])
def test_non_verb_slug_names_file_and_slug(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], str_which: str
) -> None:
    """The message must name the offending file and slug, not just 'invalid'.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest throwaway directory holding the migration.
    capsys : pytest.CaptureFixture
        Captures the gate's output.
    str_which : str
        Which half of the identification is under test.
    """
    path_file = _migration_file(tmp_path, "20260913_a1b2c3d4e5f6_users_table.py")
    gate.check_file(path_file)
    dict_expected = {"file": str(path_file), "slug": "users_table"}

    assert dict_expected[str_which] in capsys.readouterr().out


def test_unparsable_filename_shape_is_reported(tmp_path: Path) -> None:
    """A filename that does not match <date>_<rev>_<slug>.py cannot be verified — a finding."""
    path_file = _migration_file(tmp_path, "add_users_table.py")

    assert gate.check_file(path_file) == 1


@pytest.mark.parametrize(
    "str_slug",
    [
        "create_users",
        "drop_users",
        "add_email_to_users",
        "remove_legacy_flag_from_orders",
        "rename_old_to_new",
        "change_column_on_table",
        "backfill_users_email",
        "seed_roles",
    ],
)
def test_known_verb_slug_passes(tmp_path: Path, str_slug: str) -> None:
    """Every verb from the adopted Rails-style enum must pass untouched."""
    path_file = _migration_file(tmp_path, f"20260913_a1b2c3d4e5f6_{str_slug}.py")

    assert gate.check_file(path_file) == 0


def test_escape_hatch_with_a_reason_silences_the_finding(tmp_path: Path) -> None:
    """`alembic merge` produces a slug outside the enum — the documented escape hatch."""
    path_file = _migration_file(
        tmp_path,
        "20260913_a1b2c3d4e5f6_merge_heads.py",
        "# migration-slug-ok: alembic merge, no verb applies\n",
    )

    assert gate.check_file(path_file) == 0


def test_a_bare_escape_hatch_with_no_reason_is_rejected(tmp_path: Path) -> None:
    """The reason is required — a bare marker must not satisfy the gate."""
    path_file = _migration_file(
        tmp_path,
        "20260913_a1b2c3d4e5f6_merge_heads.py",
        "# migration-slug-ok:\n",
    )

    assert gate.check_file(path_file) == 1


def test_a_bare_escape_hatch_cannot_borrow_a_reason_from_the_next_line(
    tmp_path: Path,
) -> None:
    """A bare pragma must not scavenge non-whitespace content off a later line as its reason."""
    path_file = _migration_file(
        tmp_path,
        "20260913_a1b2c3d4e5f6_merge_heads.py",
        '# migration-slug-ok:\n"""merge migration heads"""\n',
    )

    assert gate.check_file(path_file) == 1


def test_main_skips_when_migrations_dir_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tier with no migrations/versions/ (most Python tiers today) must pass, not fail."""
    monkeypatch.chdir(tmp_path)

    assert gate.main() == 0


def test_main_fails_on_a_bad_slug_in_the_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole-run entrypoint must fail when any file under versions/ has a bad slug."""
    path_versions = tmp_path / "migrations" / "versions"
    path_versions.mkdir(parents=True)
    _migration_file(path_versions, "20260913_a1b2c3d4e5f6_users_table.py")
    monkeypatch.chdir(tmp_path)

    assert gate.main() == 1
