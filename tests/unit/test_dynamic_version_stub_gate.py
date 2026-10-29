"""Unit tests for the dynamic-version stub gate (filings-rfb#51)."""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType


_BIN = Path(__file__).resolve().parents[2] / "bin"
STR_DYNAMIC = "\n[tool.poetry-dynamic-versioning]\nenable = true\n"


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


gate = _load("check_dynamic_version_stub")


def _project(path_root: Path, str_toml: str) -> Path:
    """Write ``pyproject.toml`` under ``path_root``.

    Parameters
    ----------
    path_root : pathlib.Path
        Project root.
    str_toml : str
        ``pyproject.toml`` content.

    Returns
    -------
    pathlib.Path
        ``path_root``.
    """
    (path_root / "pyproject.toml").write_text(str_toml, encoding="utf-8")
    return path_root


def test_the_stub_passes(tmp_path: Path) -> None:
    """Dynamic versioning on and the version left at ``0.0.0``.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.
    """
    path_root = _project(tmp_path, f'[tool.poetry]\nversion = "0.0.0"\n{STR_DYNAMIC}')
    assert gate.stub_problems(path_root) == []


def test_a_hand_bumped_version_fails(tmp_path: Path) -> None:
    """Should-fail witness: the #30 hand-bump that went stale.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.
    """
    path_root = _project(tmp_path, f'[tool.poetry]\nversion = "1.0.0"\n{STR_DYNAMIC}')
    assert "'1.0.0'" in gate.stub_problems(path_root)[0]


def test_a_project_without_dynamic_versioning_is_ignored(tmp_path: Path) -> None:
    """Without the plugin the ``version`` field is the real one.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.
    """
    path_root = _project(tmp_path, '[tool.poetry]\nversion = "1.0.0"\n')
    assert gate.stub_problems(path_root) == []


def test_this_repo_holds_the_stub() -> None:
    """The project's own ``pyproject.toml`` passes the gate."""
    assert gate.main([]) == 0
