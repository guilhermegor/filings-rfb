"""Unit tests for the quality-rules registry gate (blueprintx#432).

**Silence is the failure mode under test.** This gate's own restricted parser used to
drop any line it did not recognise, so a valid-looking ``- id: rule # comment`` parsed to
nothing, ``main`` then checked zero rules, and the run reported success — a registry
that describes nothing passes exactly like a registry that describes everything
(blueprintx#503). Every test below pins one way that silence can come back:

- the parser must REJECT what it cannot consume rather than skip it;
- an empty parse must be a finding, never a clean run;
- each declared config assertion must be checked, not just the first one;
- an explicit ``status:``/``overridden_by:`` exception must still count as coverage,
  since rejecting it would push authors back to the omission this registry forbids.
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


gate = _load("check_quality_rules")


_STR_MINIMAL = """- id: sample
  intent: "Something is prohibited."
  docs: docs/quality-rules.md#sample
  python:
    tool: ruff
    rule: C901
"""


def _write(path_dir: Path, str_body: str) -> Path:
    """Write a registry file and return its path.

    Parameters
    ----------
    path_dir : pathlib.Path
        Directory to write into.
    str_body : str
        Registry contents.

    Returns
    -------
    pathlib.Path
        The written file.
    """
    path_yaml = path_dir / "quality-rules.yaml"
    path_yaml.write_text(str_body, encoding="utf-8")
    return path_yaml


def test_an_inline_comment_on_an_id_is_rejected_not_dropped(tmp_path: Path) -> None:
    """``- id: rule # comment`` is valid YAML this parser does not support.

    It must say so. Dropping the line silently produced an empty parse that read as a
    clean run — the defect this gate exists to prevent, inside the gate itself.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.
    """
    path_yaml = _write(tmp_path, _STR_MINIMAL.replace("- id: sample", "- id: sample # note"))
    with pytest.raises(gate.RegistryError):
        gate.parse_registry(path_yaml)


def test_malformed_nonempty_content_is_rejected(tmp_path: Path) -> None:
    """Content that matches no key pattern is a finding, not a no-op.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.
    """
    path_yaml = _write(tmp_path, _STR_MINIMAL + "        deeply: indented\n")
    with pytest.raises(gate.RegistryError):
        gate.parse_registry(path_yaml)


def test_content_before_the_first_entry_is_rejected(tmp_path: Path) -> None:
    """A stray key above the first ``- id:`` has no rule to belong to.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.
    """
    path_yaml = _write(tmp_path, '  intent: "orphan"\n' + _STR_MINIMAL)
    with pytest.raises(gate.RegistryError):
        gate.parse_registry(path_yaml)


def test_an_empty_registry_is_rejected(tmp_path: Path) -> None:
    """A file of only comments parses to nothing, which must not read as success.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.
    """
    path_yaml = _write(tmp_path, "# only a comment\n")
    with pytest.raises(gate.RegistryError):
        gate.parse_registry(path_yaml)


def test_a_wellformed_registry_still_parses(tmp_path: Path) -> None:
    """The negative control: strictness must not reject the real schema.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.
    """
    list_rules = gate.parse_registry(_write(tmp_path, _STR_MINIMAL))
    assert [dict_rule["id"] for dict_rule in list_rules] == ["sample"]


def test_every_declared_pattern_is_checked_not_only_the_first(tmp_path: Path) -> None:
    """A second declared value drifting is a finding.

    One ``pattern:`` per entry meant the registry asserted one number while vouching for
    several — the later ceilings could drift with nothing reporting it.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.
    """
    (tmp_path / "conf.txt").write_text("first_value=1\n", encoding="utf-8")
    dict_entry = {"file": "conf.txt", "patterns": ["first_value=1", "second_value=2"]}
    list_problems = gate.config_pattern_problems([{"id": "r", "python": dict_entry}], tmp_path)
    assert len(list_problems) == 1


def test_the_drifted_second_pattern_is_named(tmp_path: Path) -> None:
    """The finding names the second pattern, the one that drifted.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.
    """
    (tmp_path / "conf.txt").write_text("first_value=1\n", encoding="utf-8")
    dict_entry = {"file": "conf.txt", "patterns": ["first_value=1", "second_value=2"]}
    list_problems = gate.config_pattern_problems([{"id": "r", "python": dict_entry}], tmp_path)
    assert "second_value=2" in list_problems[0]


def test_a_single_pattern_entry_still_works(tmp_path: Path) -> None:
    """The older one-assertion form keeps working alongside ``patterns:``.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.
    """
    (tmp_path / "conf.txt").write_text("only_value=7\n", encoding="utf-8")
    dict_entry = {"file": "conf.txt", "pattern": "only_value=7"}
    assert gate.config_pattern_problems([{"id": "r", "python": dict_entry}], tmp_path) == []


def test_an_exception_only_entry_counts_as_coverage() -> None:
    """``status:``/``overridden_by:`` without tool/rule is a documented, valid entry.

    Rejecting it would force an author to invent a tool name or leave the language out
    entirely — the omission this registry exists to forbid.
    """
    dict_rule = {
        "id": "r",
        "python": {"tool": "ruff", "rule": "C901"},
        "typescript": {"status": "not-implemented", "note": "tracked in an issue"},
    }
    assert gate.language_coverage_problems([dict_rule], {"python", "typescript"}) == []


@pytest.mark.parametrize("str_bogus", ["planned", "not_implemented", "todo", "wip"])
def test_an_unrecognised_status_value_does_not_buy_coverage(str_bogus: str) -> None:
    """Only a declared status waives tool+rule; any other string is still an omission.

    The check read ``bool(entry.get("status"))``, so a typo (``not_implemented``) or an
    invented value (``planned``) satisfied coverage without a tool or a rule — the gate
    failing open on the one field whose whole job is to grant an exemption.

    Parameters
    ----------
    str_bogus : str
        A status value the gate must not accept as coverage.
    """
    dict_rule = {
        "id": "r",
        "python": {"tool": "ruff", "rule": "C901"},
        "typescript": {"status": str_bogus, "note": "tracked in an issue"},
    }
    list_problems = gate.language_coverage_problems([dict_rule], {"python", "typescript"})
    assert len(list_problems) == 1, f"{str_bogus!r} was accepted as coverage"


@pytest.mark.parametrize("str_bogus", ["planned", "not_implemented", "todo", "wip"])
def test_an_unrecognised_status_finding_names_the_language(str_bogus: str) -> None:
    """The finding for a bogus status names the language left without coverage.

    Parameters
    ----------
    str_bogus : str
        A status value the gate must not accept as coverage.
    """
    dict_rule = {
        "id": "r",
        "python": {"tool": "ruff", "rule": "C901"},
        "typescript": {"status": str_bogus, "note": "tracked in an issue"},
    }
    list_problems = gate.language_coverage_problems([dict_rule], {"python", "typescript"})
    assert "typescript" in list_problems[0]


def test_an_entry_with_neither_implementation_nor_exception_is_flagged() -> None:
    """The negative control for the test above: a bare note is still an omission."""
    dict_rule = {
        "id": "r",
        "python": {"tool": "ruff", "rule": "C901"},
        "typescript": {"note": "no tool, no rule, no stated exception"},
    }
    list_problems = gate.language_coverage_problems([dict_rule], {"python", "typescript"})
    assert len(list_problems) == 1


def test_an_entry_with_neither_implementation_nor_exception_names_the_language() -> None:
    """The bare-note finding names the language left uncovered."""
    dict_rule = {
        "id": "r",
        "python": {"tool": "ruff", "rule": "C901"},
        "typescript": {"note": "no tool, no rule, no stated exception"},
    }
    list_problems = gate.language_coverage_problems([dict_rule], {"python", "typescript"})
    assert "typescript" in list_problems[0]


def test_a_comment_only_note_does_not_satisfy_the_reason_requirement() -> None:
    """`note: # reason` is a comment, not a note — the exception still owes an explanation.

    `_parse_scalar` returned the raw `# reason` text, which is non-empty, so a
    `status:`/`overridden_by:` entry could take the waiver with the reason left unwritten.
    In YAML the value is empty; the restricted parser disagreed, permissively.
    """
    assert gate._parse_scalar("# reason") == ""


def test_a_bare_hash_is_an_empty_value() -> None:
    """A lone ``#`` with leading whitespace is an empty value too."""
    assert gate._parse_scalar("  #") == ""


def test_a_trailing_comment_is_stripped_from_a_bare_value() -> None:
    """Same bug one step along: the comment is not part of the value."""
    assert gate._parse_scalar("not-implemented  # tracked in #430") == "not-implemented"


def test_a_quoted_hash_is_a_real_string_not_a_comment() -> None:
    """The negative control: quoting is how you mean a literal '#'."""
    assert gate._parse_scalar('"# literal hash"') == "# literal hash"


def test_a_quoted_hash_inside_prose_stays_in_the_string() -> None:
    """A quoted value containing ``#430`` keeps the whole text."""
    assert gate._parse_scalar('"see #430 for why"') == "see #430 for why"


def test_a_comment_only_note_is_reported_as_a_missing_reason() -> None:
    """End to end: the parser fix must actually reach reason_required_problems."""
    dict_rule = {
        "id": "r",
        "python": {"tool": "ruff", "rule": "C901"},
        "typescript": {"status": "not-implemented", "note": gate._parse_scalar("# reason")},
    }
    list_problems = gate.reason_required_problems([dict_rule])
    assert len(list_problems) == 1


def test_a_comment_only_note_missing_reason_names_the_language() -> None:
    """The missing-reason finding names the language whose note was only a comment."""
    dict_rule = {
        "id": "r",
        "python": {"tool": "ruff", "rule": "C901"},
        "typescript": {"status": "not-implemented", "note": gate._parse_scalar("# reason")},
    }
    assert "typescript" in gate.reason_required_problems([dict_rule])[0]
