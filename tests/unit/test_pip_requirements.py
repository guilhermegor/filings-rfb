"""Unit tests for the pip-fallback requirement translator (offline; no pip, no network).

**No shipped tier exercises the case these tests exist for**, and that is exactly why they
are here. Every skeleton declares ``[tool.poetry]``, so the equivalence probe that guarded
the heredoc extraction — five tiers x four group selections — could not see a PEP 621
project at all, let alone one declaring *only* ``[project.optional-dependencies]``. That
shape sent the selector down the Poetry path and emitted nothing, and the caller wrote the
nothing to ``requirements-lock.txt`` where it reads as "this project has no dependencies"
(blueprintx#211).

So the fixtures below are hand-built rather than lifted from a tier: the bug lives in the
layouts the repo does not ship, which is the half no amount of running the real thing can
reach.
"""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest


_LIB = Path(__file__).resolve().parents[2] / "bin" / "lib"


def _load() -> ModuleType:
    """Load ``bin/lib/pip_requirements.py`` by path (``bin/lib/`` is not a package).

    Returns
    -------
    ModuleType
        The imported module.
    """
    cls_spec = importlib.util.spec_from_file_location(
        "pip_requirements", _LIB / "pip_requirements.py"
    )
    cls_module = importlib.util.module_from_spec(cls_spec)
    sys.modules["pip_requirements"] = cls_module
    cls_spec.loader.exec_module(cls_module)
    return cls_module


MODULE = _load()


DICT_PEP621_OPTIONAL_ONLY = {
    "project": {
        "name": "optional-only",
        "optional-dependencies": {
            "dev": ["pytest>=8.0", "ruff>=0.6"],
            "docs": ["mkdocs>=1.6"],
        },
    }
}

DICT_PEP621_WITH_MAIN = {
    "project": {
        "name": "both",
        "dependencies": ["httpx>=0.27"],
        "optional-dependencies": {"dev": ["pytest>=8.0"]},
    }
}

DICT_POETRY_WITH_EMPTY_PROJECT_TABLE = {
    "project": {"name": "poetry-project"},
    "tool": {
        "poetry": {
            "dependencies": {"python": "^3.11", "pandas": "^2.2"},
            "group": {"dev": {"dependencies": {"pytest": "^8.0"}}},
        }
    },
}


def test_optional_only_pep621_resolves_its_group() -> None:
    """An optional-only PEP 621 project must resolve through the PEP 621 path."""
    assert MODULE.select_requirements(DICT_PEP621_OPTIONAL_ONLY, ["dev"]) == [
        "pytest>=8.0",
        "ruff>=0.6",
    ]


def test_optional_only_pep621_with_main_requested_still_resolves_the_group() -> None:
    """Requesting ``main`` on a project without main deps yields the optional group alone."""
    assert MODULE.select_requirements(DICT_PEP621_OPTIONAL_ONLY, ["main", "dev"]) == [
        "pytest>=8.0",
        "ruff>=0.6",
    ]


def test_main_dependencies_are_omitted_when_main_is_not_requested() -> None:
    """``[project.dependencies]`` belongs to the ``main`` group, not to every request."""
    assert MODULE.select_requirements(DICT_PEP621_WITH_MAIN, ["dev"]) == ["pytest>=8.0"]


def test_main_dependencies_are_included_when_main_is_requested() -> None:
    """The same table IS emitted once ``main`` is among the requested groups."""
    assert MODULE.select_requirements(DICT_PEP621_WITH_MAIN, ["main", "dev"]) == [
        "httpx>=0.27",
        "pytest>=8.0",
    ]


def test_empty_project_table_falls_through_to_poetry() -> None:
    """A bare ``[project]`` name beside a populated ``[tool.poetry]`` must resolve via Poetry."""
    assert MODULE.select_requirements(DICT_POETRY_WITH_EMPTY_PROJECT_TABLE, ["main"]) == [
        "pandas>=2.2,<3.0.0"
    ]


def test_poetry_group_still_resolves() -> None:
    """The Poetry group path is unchanged by the selector fix."""
    assert MODULE.select_requirements(DICT_POETRY_WITH_EMPTY_PROJECT_TABLE, ["dev"]) == [
        "pytest>=8.0,<9.0.0"
    ]


def test_empty_result_for_a_requested_group_fails_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zero requirements for a non-empty request must raise, never print nothing and exit 0.

    The negative control for the whole file: an empty ``requirements-lock.txt`` is
    indistinguishable from a dependency-free project, on precisely the constrained hosts
    where the pip fallback runs and nobody is reading the output.
    """
    tmp_path.joinpath("pyproject.toml").write_text('[project]\nname = "empty"\n', encoding="utf-8")
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("BX_GROUPS", "main,dev")

    with pytest.raises(SystemExit, match="No requirements resolved"):
        MODULE.main()
