"""Unit tests for ``bin/check_docs_code_refs.py`` — the docs-versus-code reference gate.

⚠️ Both directions matter more here than in most gates. A gate that reports a defect where
none exists is worse than an absent one: the first false positive on correct prose teaches
everyone to reach for the escape hatch, and from then on it guards nothing. So every case
below that asserts "no finding" is a real test, not filler.
"""

import importlib.util
import pathlib
import sys
import types

import pytest


def _load_gate() -> types.ModuleType:
    """Import ``check_docs_code_refs.py`` by path — ``bin/`` is not an importable package.

    Returns
    -------
    types.ModuleType
        The loaded gate module.
    """
    path_gate = pathlib.Path(__file__).resolve().parents[2] / "bin" / "check_docs_code_refs.py"
    cls_spec = importlib.util.spec_from_file_location("check_docs_code_refs", path_gate)
    cls_module = importlib.util.module_from_spec(cls_spec)
    sys.modules["check_docs_code_refs"] = cls_module
    cls_spec.loader.exec_module(cls_module)
    return cls_module


cls_gate = _load_gate()


@pytest.fixture
def path_src(tmp_path: pathlib.Path) -> pathlib.Path:
    """Build a miniature ``src/`` tree: a package with one symbol and one submodule.

    Parameters
    ----------
    tmp_path : pathlib.Path
        pytest's per-test temporary directory.

    Returns
    -------
    pathlib.Path
        The ``src/`` directory of the fabricated project.
    """
    path_root = tmp_path / "src"
    path_pkg = path_root / "chassis"
    path_pkg.mkdir(parents=True)
    str_body = "def build() -> None:\n\treturn None\n"
    (path_pkg / "__init__.py").write_text(str_body, encoding="utf-8")
    (path_pkg / "widgets.py").write_text(
        "def build_widget() -> None:\n\treturn None\n", encoding="utf-8"
    )
    return path_root


@pytest.mark.parametrize(
    ("str_names", "list_expected"),
    [
        ("build_widget  # example", ["build_widget"]),
        ("widgets  # noqa: F401", ["widgets"]),
        ("Foo, Bar  # two of them", ["Foo", "Bar"]),
        ("(Foo, Bar,)  # grouped", ["Foo", "Bar"]),
    ],
)
def test_parse_names_drops_an_inline_comment(str_names: str, list_expected: list[str]) -> None:
    """A trailing ``# comment`` is not part of the imported name.

    Docs annotate example imports as a matter of course. Keeping the comment produced a name
    no module could ever define, so the gate failed correct documentation.
    """
    assert cls_gate.parse_names(str_names) == list_expected


@pytest.mark.parametrize(
    ("str_names", "list_expected"),
    [
        ("Foo, Bar as Baz", ["Foo", "Bar"]),
        ("(Foo, Bar,)", ["Foo", "Bar"]),
        ("*", []),
    ],
)
def test_parse_names_still_handles_the_uncommented_forms(
    str_names: str, list_expected: list[str]
) -> None:
    """The comment fix must not disturb aliases, grouped imports or the star form."""
    assert cls_gate.parse_names(str_names) == list_expected


def test_submodule_import_from_a_package_is_accepted(path_src: pathlib.Path) -> None:
    """``from chassis import widgets`` is valid even when ``__init__.py`` does not re-export it.

    Python resolves the name to ``chassis/widgets.py``. Checking only the names defined in
    ``__init__.py`` flagged a perfectly ordinary import.
    """
    assert cls_gate.candidate_problem(path_src, "chassis", ["widgets"]) is None


def test_symbol_defined_in_the_package_is_accepted(path_src: pathlib.Path) -> None:
    """The ordinary case still passes: a name defined in ``__init__.py`` is fine."""
    assert cls_gate.candidate_problem(path_src, "chassis", ["build"]) is None


def test_a_genuinely_absent_name_is_still_reported(path_src: pathlib.Path) -> None:
    """⚠️ The other direction: neither fix may turn the gate into one that passes everything.

    ``nonexistent`` is not defined in the package and is not a submodule, so it must still be
    a finding — otherwise the two fixes above would have silently disabled the check.
    """
    str_problem = cls_gate.candidate_problem(path_src, "chassis", ["nonexistent"])
    assert "nonexistent" in str_problem


def test_an_absent_module_is_still_reported(path_src: pathlib.Path) -> None:
    """A module that does not resolve at all remains a finding."""
    str_problem = cls_gate.candidate_problem(path_src, "no_such_package", ["anything"])
    assert "module not found" in str_problem


_CASES_MULTILINE_IMPORT = pytest.mark.parametrize(
    ("list_body", "list_expected"),
    [
        (
            [
                "from chassis.widgets import (",
                "\tbuild_widget,  # )",
                "\tmissing_name,",
                ")",
            ],
            ["build_widget", "missing_name"],
        ),
        (
            [
                "from chassis.widgets import (",
                "\tbuild_widget,  # an annotated example",
                "\tmissing_name,",
                ")",
            ],
            ["build_widget", "missing_name"],
        ),
        (
            [
                "from chassis.widgets import (",
                "\tbuild_widget,",
                "\tmissing_name,",
                ")",
            ],
            ["build_widget", "missing_name"],
        ),
    ],
)


@_CASES_MULTILINE_IMPORT
def test_a_comment_never_shortens_a_multiline_import(
    list_body: list[str], list_expected: list[str]
) -> None:
    """Every name in a parenthesised import is seen, whatever comments sit between them.

    ⚠️ These are silent MISSES, the opposite of the false positives above and worse to live
    with: the gate reported success having examined fewer names than the import declares.

    Two distinct causes, one fix. A ``)`` inside a comment ended the closing-paren scan early,
    so names on later lines were never gathered. And once the fragments were joined, cutting
    the string at its first ``#`` swallowed every name that followed the comment — which the
    ordinary annotated import in the second case triggers with no exotic syntax at all.
    """
    list_statements = cls_gate.import_statements(list_body, 1)
    assert cls_gate.parse_names(list_statements[0][2]) == list_expected


@_CASES_MULTILINE_IMPORT
def test_a_multiline_import_is_one_statement_whatever_comments_sit_in_it(
    list_body: list[str], list_expected: list[str]
) -> None:
    """A parenthesised import with interleaved comments is still ONE statement.

    Parameters
    ----------
    list_body : list[str]
        The import's source lines.
    list_expected : list[str]
        Unused here; shared with the sibling test's cases.
    """
    assert len(cls_gate.import_statements(list_body, 1)) == 1


def test_strip_inline_comment_leaves_an_uncommented_line_alone() -> None:
    """The other direction: the helper must not chew on a line that has no comment."""
    assert cls_gate.strip_inline_comment("build_widget, missing_name") == (
        "build_widget, missing_name"
    )
