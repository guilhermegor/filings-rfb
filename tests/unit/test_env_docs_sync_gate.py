"""Unit tests for the ``.env.example`` / ``docs/configuration.md`` sync gate (blueprintx#304)."""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest


_BIN = Path(__file__).resolve().parents[2] / "bin"
STR_HEADER = "| Variable | In .env.example | Default |\n|---|---|---|\n"


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


gate = _load("check_env_docs_sync")


def _env(path_root: Path, str_env: str) -> Path:
    """Write ``.env.example`` under ``path_root``.

    Parameters
    ----------
    path_root : pathlib.Path
        Project root, created if absent.
    str_env : str
        ``.env.example`` content.

    Returns
    -------
    pathlib.Path
        ``path_root``.
    """
    path_root.mkdir(parents=True, exist_ok=True)
    (path_root / ".env.example").write_text(str_env, encoding="utf-8")
    return path_root


def _project(path_root: Path, str_env: str, str_doc: str) -> Path:
    """Write ``.env.example`` and ``docs/configuration.md`` under ``path_root``.

    Parameters
    ----------
    path_root : pathlib.Path
        Project root, created if absent.
    str_env : str
        ``.env.example`` content.
    str_doc : str
        ``docs/configuration.md`` content.

    Returns
    -------
    pathlib.Path
        ``path_root``.
    """
    _env(path_root, str_env)
    (path_root / "docs").mkdir(exist_ok=True)
    (path_root / "docs" / "configuration.md").write_text(str_doc, encoding="utf-8")
    return path_root


def test_matching_keys_and_rows_pass(tmp_path: Path) -> None:
    """Every key has a ``yes`` row and every ``yes`` row has a key.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.
    """
    path_root = _project(
        tmp_path, "A=1\nB=2\n", f"{STR_HEADER}| `A` | yes | 1 |\n| `B` | yes | 2 |\n"
    )
    assert gate.project_problems(path_root) == []


def test_a_key_without_a_row_fails(tmp_path: Path) -> None:
    """Should-fail witness: a variable added to the file but not to the table.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.
    """
    path_root = _project(tmp_path, "A=1\nB=2\n", f"{STR_HEADER}| `A` | yes | 1 |\n")
    assert "B is in .env.example" in gate.project_problems(path_root)[0]


def test_a_yes_row_without_a_key_fails(tmp_path: Path) -> None:
    """Should-fail witness: a variable renamed in the file leaves a stale row behind.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.
    """
    path_root = _project(
        tmp_path, "A=1\n", f"{STR_HEADER}| `A` | yes | 1 |\n| `OLD` | yes | 2 |\n"
    )
    assert "OLD is marked 'yes'" in gate.project_problems(path_root)[0]


def test_a_no_row_may_name_a_variable_the_file_omits(tmp_path: Path) -> None:
    """An optional variable left unset on purpose is documented with ``no``.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.
    """
    path_root = _project(
        tmp_path, "A=1\n", f"{STR_HEADER}| `A` | yes | 1 |\n| `PORT` | no | - |\n"
    )
    assert gate.project_problems(path_root) == []


def test_a_row_in_a_table_without_the_column_is_ignored(tmp_path: Path) -> None:
    """Only tables carrying the ``In .env.example`` header are read.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.
    """
    str_doc = f"| Name | Note |\n|---|---|\n| `X` | yes |\n\n{STR_HEADER}| `A` | yes | 1 |\n"
    assert gate.project_problems(_project(tmp_path, "A=1\n", str_doc)) == []


def test_comment_lines_in_the_env_file_are_not_keys(tmp_path: Path) -> None:
    """A commented-out assignment is not a seeded key.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.
    """
    path_root = _project(tmp_path, "# PORT=1\nA=1\n", f"{STR_HEADER}| `A` | yes | 1 |\n")
    assert gate.project_problems(path_root) == []


def test_an_env_file_without_a_doc_fails(tmp_path: Path) -> None:
    """Should-fail witness: the file exists but the table was never written.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.
    """
    assert "does not" in gate.project_problems(_env(tmp_path, "A=1\n"))[0]


def test_a_project_with_neither_file_passes(tmp_path: Path) -> None:
    """A library tier with no ``.env.example`` has nothing to document.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.
    """
    assert gate.project_problems(tmp_path) == []


def test_each_under_checks_every_child_and_fails_on_one_bad_tier(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Should-fail witness: one drifted tier among good ones fails the whole run.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.
    capsys : pytest.CaptureFixture
        Captures the gate's report.
    """
    _project(tmp_path / "good", "A=1\n", f"{STR_HEADER}| `A` | yes | 1 |\n")
    _project(tmp_path / "bad", "A=1\n", f"{STR_HEADER}| `Z` | yes | 1 |\n")
    int_code = gate.main(["--each-under", str(tmp_path)])
    assert (int_code, "2 finding(s)" in capsys.readouterr().out) == (1, True)
