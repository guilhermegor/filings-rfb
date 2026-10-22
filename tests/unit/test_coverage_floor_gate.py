"""Unit tests for the coverage-floor omit gate (``bin/check_coverage_floor.py``).

The should-PASS cases matter as much as the should-fail ones: a gate exercised only on what
it rejects has been shown to reject, not to discriminate. The one that carries the whole
point of issue #149 is ``test_widened_omit_swallows_new_capability_logic_is_flagged`` — the
synthetic probe that proves the floor actually notices when ``omit`` widens past its
legitimate scope, since the real template ships only the already-excluded example capability
and therefore finds nothing to flag on its own.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def _load_gate() -> ModuleType:
    """Import ``bin/check_coverage_floor.py`` as a module.

    Returns
    -------
    ModuleType
        The loaded gate module.
    """
    path_gate = Path(__file__).resolve().parents[2] / "bin" / "check_coverage_floor.py"
    cls_spec = importlib.util.spec_from_file_location("_check_coverage_floor", path_gate)
    assert cls_spec is not None
    assert cls_spec.loader is not None
    cls_module = importlib.util.module_from_spec(cls_spec)
    cls_spec.loader.exec_module(cls_module)
    return cls_module


def _project(tmp_path: Path, str_omit: str) -> Path:
    """Write a minimal project root with a ``.coveragerc`` and empty ``src/``.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Directory to build in.
    str_omit : str
        The ``omit =`` body (indented lines), or ``""`` for an empty list.

    Returns
    -------
    pathlib.Path
        The project root.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    str_body = f"omit =\n{str_omit}" if str_omit else "omit ="
    (tmp_path / ".coveragerc").write_text(f"[run]\nsource = src/\n{str_body}\n", encoding="utf-8")
    return tmp_path


def _capability(path_root: Path, str_name: str, str_layer: str, str_source: str) -> None:
    """Write one module under ``src/capabilities/<name>/<layer>/service.py``.

    Parameters
    ----------
    path_root : pathlib.Path
        The project root built by ``_project``.
    str_name : str
        Capability directory name.
    str_layer : str
        ``"domain"`` or ``"application"``.
    str_source : str
        The module's Python source.
    """
    path_layer = path_root / "src" / "capabilities" / str_name / str_layer
    path_layer.mkdir(parents=True, exist_ok=True)
    (path_layer / "service.py").write_text(str_source, encoding="utf-8")


def test_missing_coveragerc_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No ``.coveragerc`` at all must exit non-zero, never green."""
    (tmp_path / "src").mkdir()
    monkeypatch.chdir(tmp_path)
    assert _load_gate().main() == 1


def test_empty_omit_list_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty declared list is broken discovery, not a clean slate."""
    _project(tmp_path, "")
    monkeypatch.chdir(tmp_path)
    assert _load_gate().main() == 1


def test_no_python_files_under_src_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Scanning nothing must exit non-zero, never report success."""
    path_root = _project(tmp_path, "    src/chassis/*\n")
    (path_root / "src" / "__init__.py").unlink()
    monkeypatch.chdir(path_root)
    assert _load_gate().main() == 1


def test_no_capabilities_dir_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A layout with no capabilities/ split (e.g. MVC) has nothing for this floor to check."""
    path_root = _project(tmp_path, "    src/utils/*\n")
    monkeypatch.chdir(path_root)
    assert _load_gate().main() == 0


def test_fresh_scaffold_with_only_excluded_example_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh scaffold ships only the example capability, already named outright.

    Zero findings here is the EXPECTED result, not a broken detector — the probe test below
    is what proves discovery works.
    """
    path_root = _project(tmp_path, "    src/capabilities/example_feature/*\n")
    _capability(path_root, "example_feature", "domain", "def compute():\n    return 1\n")
    monkeypatch.chdir(path_root)
    assert _load_gate().main() == 0


def test_narrowly_scoped_omit_does_not_flag_new_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An omit pattern scoped to infrastructure/ leaves a new capability's domain logic in."""
    path_root = _project(
        tmp_path,
        "    src/capabilities/example_feature/*\n    src/capabilities/*/infrastructure/*\n",
    )
    _capability(path_root, "example_feature", "domain", "def compute():\n    return 1\n")
    _capability(path_root, "orders", "domain", "def place_order():\n    return True\n")
    monkeypatch.chdir(path_root)
    assert _load_gate().main() == 0


def test_widened_omit_swallows_new_capability_logic_is_flagged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """The synthetic probe: widening omit past infrastructure/ must fail, naming the file.

    This is the exact hole a hand-declared list cannot see on its own: nothing in
    ``.coveragerc`` contradicts a glob quietly growing from "infrastructure only" to "the
    whole capability" — the suite stays green precisely because nothing is looking anymore.
    """
    path_root = _project(
        tmp_path,
        "    src/capabilities/example_feature/*\n    src/capabilities/*\n",
    )
    _capability(path_root, "orders", "domain", "def place_order():\n    return True\n")
    monkeypatch.chdir(path_root)
    _load_gate().main()
    str_err = capsys.readouterr().err
    assert "orders/domain/service.py" in str_err


def test_widened_omit_swallowing_new_capability_logic_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same widened-omit probe exits 1, not 0.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway project root.
    monkeypatch : pytest.MonkeyPatch
        Used to run the gate from the project root.
    """
    path_root = _project(
        tmp_path,
        "    src/capabilities/example_feature/*\n    src/capabilities/*\n",
    )
    _capability(path_root, "orders", "domain", "def place_order():\n    return True\n")
    monkeypatch.chdir(path_root)
    assert _load_gate().main() == 1


def test_single_misomitted_file_in_a_narrowly_excluded_capability_is_flagged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Detection is per MODULE even when the capability carries narrower exclusions.

    Pins the distinction the design record gets asked about: the capability-root
    coarseness is the EXEMPTION granularity (only a literal whole-capability pattern
    exempts), not the detection granularity. ``orders`` below keeps a legitimate
    ``infrastructure/*`` exclusion and is therefore NOT exempt, so its one mis-omitted
    domain module must still be named. Documented as uncaught until 2026-09-18; it was
    caught all along, and a doc that understates a gate invites a redundant second one.
    """
    path_root = _project(
        tmp_path,
        "    src/capabilities/example_feature/*\n"
        "    src/capabilities/*/infrastructure/*\n"
        "    src/capabilities/orders/domain/service.py\n",
    )
    _capability(path_root, "orders", "domain", "def place_order():\n    return True\n")
    monkeypatch.chdir(path_root)
    _load_gate().main()
    assert "orders/domain/service.py" in capsys.readouterr().err


def test_single_misomitted_file_in_a_narrowly_excluded_capability_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same single mis-omitted module makes the gate exit 1.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway project root.
    monkeypatch : pytest.MonkeyPatch
        Used to run the gate from the project root.
    """
    path_root = _project(
        tmp_path,
        "    src/capabilities/example_feature/*\n"
        "    src/capabilities/*/infrastructure/*\n"
        "    src/capabilities/orders/domain/service.py\n",
    )
    _capability(path_root, "orders", "domain", "def place_order():\n    return True\n")
    monkeypatch.chdir(path_root)
    assert _load_gate().main() == 1


def test_enum_only_module_is_never_in_the_must_cover_set(tmp_path: Path) -> None:
    """A module with only class/attribute definitions (an enum) defines no function.

    Matched by omit or not, it never enters the derived floor — this is the AST fact that
    replaces the hardcoded ``domain/enums.py`` exception with a structural one.
    """
    cls_gate = _load_gate()
    path_root = _project(tmp_path, "")
    _capability(path_root, "orders", "domain", "class Status:\n    OPEN = 1\n    CLOSED = 2\n")
    path_module = path_root / "src" / "capabilities" / "orders" / "domain" / "service.py"
    assert cls_gate.defines_a_function(path_module) is False


def test_whole_capability_exclusions_reads_only_literal_names() -> None:
    """A wildcarded capability segment is a scoping rule, not a named exception."""
    cls_gate = _load_gate()
    set_excluded = cls_gate.whole_capability_exclusions(
        ["src/capabilities/example_feature/*", "src/capabilities/*/infrastructure/*"]
    )
    assert set_excluded == {"example_feature"}


def test_omit_patterns_expands_environment_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Coverage.py expands ``${VAR}`` before applying omit; the raw text would never match."""
    cls_gate = _load_gate()
    monkeypatch.setenv("COV_ROOT", "/srv/app")
    path_cfg = tmp_path / ".coveragerc"
    path_cfg.write_text(
        "[run]\nomit =\n    ${COV_ROOT}/src/capabilities/*/domain/*\n", encoding="utf-8"
    )

    assert cls_gate.omit_patterns(path_cfg) == ["/srv/app/src/capabilities/*/domain/*"]


def test_absolute_omit_pattern_still_swallows_a_relative_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An expanded, absolute pattern must match the RELATIVE module path it really omits."""
    cls_gate = _load_gate()
    path_root = _project(tmp_path, "")
    _capability(path_root, "orders", "domain", "def place() -> None:\n    return None\n")
    monkeypatch.chdir(path_root)
    path_module = Path("src/capabilities/orders/domain/service.py")
    str_absolute_pattern = f"{path_root.resolve().as_posix()}/src/capabilities/*/domain/*"

    list_problems = cls_gate.swallowed_by_omit([path_module], [str_absolute_pattern])

    assert len(list_problems) == 1


def test_relative_omit_pattern_keeps_working(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Widening to absolute must not break the plain relative form the template ships."""
    cls_gate = _load_gate()
    path_root = _project(tmp_path, "")
    _capability(path_root, "orders", "domain", "def place() -> None:\n    return None\n")
    monkeypatch.chdir(path_root)
    path_module = Path("src/capabilities/orders/domain/service.py")

    list_problems = cls_gate.swallowed_by_omit([path_module], ["src/capabilities/*/domain/*"])

    assert len(list_problems) == 1
