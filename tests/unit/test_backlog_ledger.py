"""Unit tests for the work-ledger gate's pure logic (offline; no git, no network).

Only the path-classification and ledger-validation seams are tested here — the git plumbing
(`merge-base`, `diff --cached`) belongs to an integration test, not a unit one.
"""

import importlib.util
import json
from pathlib import Path
import subprocess
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


gate = _load("pr_gate")
ledger = _load("check_backlog_ledger")
gate_integrity = _load("check_gate_integrity")


def _first_problem(list_problems: list[str]) -> str:
    """Return the first problem reported, asserting the list is not empty.

    "It fired at all" and "it said the right thing" are two claims (blueprintx#544). The
    first is a precondition of the second — indexing ``[0]`` of an empty list raises an
    ``IndexError`` that names neither the gate nor the input — so it is checked here and
    each test keeps the single assertion that names the behaviour.

    Parameters
    ----------
    list_problems : list of str
        Whatever the gate reported.

    Returns
    -------
    str
        The first problem.
    """
    assert list_problems, "the gate reported nothing at all"
    return list_problems[0]


@pytest.mark.parametrize("str_path", ["src/model/loader.py", "bin/venv.sh"])
def test_ledger_required_for_src_and_ci(str_path: str) -> None:
    """A branch touching src/ or ci paths must carry a ledger."""
    assert ledger.needs_ledger([str_path], gate) is True


@pytest.mark.parametrize(
    "str_path",
    ["docs/usage.md", "poetry.lock", "tests/unit/test_x.py", ".specs/features/x/design.md"],
)
def test_ledger_not_required_for_routine_classes(str_path: str) -> None:
    """docs/deps/tests-only branches are routine — a ledger there would be noise."""
    assert ledger.needs_ledger([str_path], gate) is False


_LIST_MIXED_BRANCH = ["bin/venv.sh", "tests/unit/test_x.py"]


def test_the_whole_list_view_collapses_a_mixed_branch_to_tests() -> None:
    """The collapse is real — this is why the whole-list view cannot be the one asked."""
    assert gate.classify_risk(_LIST_MIXED_BRANCH) == "tests"


def test_membership_is_asked_per_path_not_over_the_whole_list() -> None:
    """The regression this guards: a mixed branch must NOT escape the ledger requirement."""
    assert ledger.needs_ledger(_LIST_MIXED_BRANCH, gate) is True


def test_a_valid_ledger_satisfies_the_branch() -> None:
    """A correctly named ledger clears the requirement."""
    list_files = ["src/a.py", ".specs/backlog/my-topic_20260720_101500.md"]
    assert ledger.find_ledger_problems(list_files) == []


def test_missing_ledger_is_reported() -> None:
    """A src-touching branch with no ledger fails, and the message says what to create."""
    assert "Create .specs/backlog/<kebab-topic>_YYYYMMDD_HHMMSS.md" in _first_problem(
        ledger.find_ledger_problems(["src/a.py"])
    )


def test_ledger_name_must_be_kebab_plus_timestamp() -> None:
    """A misnamed ledger is rejected — the timestamped kebab name is the convention."""
    assert ".specs/backlog/<kebab-topic>_YYYYMMDD_HHMMSS.md" in _first_problem(
        ledger.find_ledger_problems(["src/a.py", ".specs/backlog/BadName.md"])
    )


def test_gitkeep_is_not_reported_as_a_misnamed_ledger() -> None:
    """Only ``.md`` paths are ledgers, so the scaffold's ``.gitkeep`` never trips the name rule."""
    list_problems = ledger.find_ledger_problems(["src/a.py", ".specs/backlog/.gitkeep"])
    assert not any("name must match" in str_problem for str_problem in list_problems)


def test_crlf_ledger_with_a_closed_fence_keeps_its_real_checkboxes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A CRLF checkout must not turn every closed fence into an unclosed one."""
    str_rel = ".specs/backlog/crlf_20260101_000000.md"
    path_ledger = tmp_path / str_rel
    path_ledger.parent.mkdir(parents=True)
    path_ledger.write_bytes(b"# t\r\n\r\n```\r\nexample\r\n```\r\n\r\n- [ ] real\r\n")
    monkeypatch.chdir(tmp_path)
    assert ledger.find_ledger_problems([str_rel]) == []


@pytest.mark.parametrize(
    "str_fenced",
    [
        "```\n- [ ] example\n```\n",
        "```\n- [ ] example\n````\n",
        "~~~\n- [ ] example\n~~~~\n",
        "```\n- [ ] example\n",
    ],
)
def test_checkbox_inside_a_code_fence_does_not_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, str_fenced: str
) -> None:
    """The specs gate skips fenced blocks, closers may be longer; an example-only ledger fails."""
    str_rel = ".specs/backlog/fenced_20260101_000000.md"
    path_ledger = tmp_path / str_rel
    path_ledger.parent.mkdir(parents=True)
    path_ledger.write_text(f"# t\n\n{str_fenced}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert "outside a code fence" in _first_problem(ledger.find_ledger_problems([str_rel]))


@pytest.mark.parametrize(
    "str_line", ["- [ ] todo", "- [x] done", "- [~] feat/a doing", "+ [ ] plus"]
)
def test_checkbox_grammar_accepts_the_specs_markers(str_line: str) -> None:
    """The ledger gate accepts the same markers check_specs_structure.sh does."""
    assert ledger.CHECKBOX_RE.search(str_line)


@pytest.mark.parametrize(
    "str_line",
    ["- [X] upper", "- [] empty", "- [?] unknown", "- plain", "- [~]", "- [~] doing", "- [~]\t"],
)
def test_checkbox_grammar_rejects_what_the_specs_gate_rejects(str_line: str) -> None:
    """NEGATIVE CONTROL: a marker the specs gate rejects does not count as a checkbox."""
    assert not ledger.CHECKBOX_RE.search(str_line)


@pytest.mark.parametrize("str_login", ["dependabot[bot]", "github-actions[bot]", "renovate[bot]"])
def test_bot_login_is_exempt(str_login: str) -> None:
    """GitHub's own ``[bot]`` suffix identifies the author, with no allow-list to rot."""
    assert ledger.is_bot_author(str_login) is True


@pytest.mark.parametrize("str_login", ["octocat", "robotics-team", "dependabot"])
def test_human_login_is_not_exempt(str_login: str) -> None:
    """NEGATIVE CONTROL: the gate still fires for humans, including bot-ish names."""
    assert ledger.is_bot_author(str_login) is False


def test_unresolved_author_is_treated_as_human() -> None:
    """An author that cannot be resolved must fail CLOSED, never exempt."""
    assert ledger.is_bot_author("") is False


def _write_event(path_dir: Path, dict_payload: dict) -> str:
    """Write a GitHub event payload to disk and return its path.

    Parameters
    ----------
    path_dir : pathlib.Path
        Directory to write the payload into.
    dict_payload : dict
        The event body, e.g. ``{"pull_request": {"user": {"login": "x"}}}``.

    Returns
    -------
    str
        Path to the written JSON file.
    """
    path_event = path_dir / "event.json"
    path_event.write_text(json.dumps(dict_payload), encoding="utf-8")
    return str(path_event)


def test_pr_author_comes_from_the_payload_never_the_actor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⚠️ The trap: ``GITHUB_ACTOR`` is whoever TRIGGERED the run, not the PR author.

    Keying on the actor makes the exemption die the moment a human touches the bot's PR
    (update-branch, re-run, fixup) — so the very act of unblocking it defeats the fix, and
    each retry reads as "the fix doesn't work". This pins the author as authoritative even
    when a human is the actor.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest throwaway dir holding the event payload.
    monkeypatch : pytest.MonkeyPatch
        Used to set the GitHub Actions environment variables.
    """
    str_event = _write_event(tmp_path, {"pull_request": {"user": {"login": "dependabot[bot]"}}})
    monkeypatch.setenv("GITHUB_EVENT_PATH", str_event)
    monkeypatch.setenv("GITHUB_ACTOR", "a-human-who-clicked-rerun")

    assert ledger.pr_author_login() == "dependabot[bot]"


def test_human_authored_pr_is_not_exempt_even_when_a_bot_is_the_actor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other direction: a bot triggering a human's PR must not exempt it."""
    str_event = _write_event(tmp_path, {"pull_request": {"user": {"login": "octocat"}}})
    monkeypatch.setenv("GITHUB_EVENT_PATH", str_event)
    monkeypatch.setenv("GITHUB_ACTOR", "github-actions[bot]")

    assert ledger.is_bot_author(ledger.pr_author_login()) is False


def test_a_push_run_has_no_pr_author_and_stays_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inside a workflow run the payload is the ONLY authority — never the actor.

    A push payload carries no ``pull_request`` object, so there is no author, and the gate must
    stay enforced rather than fall back to a possibly-bot actor.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest throwaway dir holding the event payload.
    monkeypatch : pytest.MonkeyPatch
        Used to set the GitHub Actions environment variables.
    """
    str_event = _write_event(tmp_path, {"ref": "refs/heads/main"})
    monkeypatch.setenv("GITHUB_EVENT_PATH", str_event)
    monkeypatch.setenv("GITHUB_ACTOR", "dependabot[bot]")

    assert ledger.is_bot_author(ledger.pr_author_login()) is False


def test_a_missing_event_file_exempts_nobody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GITHUB_EVENT_PATH set but the file absent must fail CLOSED, not fall back to the actor.

    This is the narrow hole an earlier revision left: the missing-file branch skipped the
    payload entirely and returned ``GITHUB_ACTOR``, so a bot re-running or auto-merging a
    human's PR would have exempted it — the exact defect keying on the author exists to avoid.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest throwaway dir; the payload path deliberately points at nothing.
    monkeypatch : pytest.MonkeyPatch
        Used to set the GitHub Actions environment variables.
    """
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(tmp_path / "does_not_exist.json"))
    monkeypatch.setenv("GITHUB_ACTOR", "dependabot[bot]")

    assert ledger.is_bot_author(ledger.pr_author_login()) is False


def test_a_missing_event_file_resolves_to_no_author_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The MECHANISM behind the test above: the resolver returns "", never the actor.

    Split from its sibling rather than dropped (blueprintx#544). The two are genuinely
    different claims — "nobody is exempted" is the behaviour, and "the resolver returns the
    empty string" is why. Keeping only the first would let a resolver that returned some
    other non-bot login pass while the real defect (falling back to ``GITHUB_ACTOR``) went
    unnamed.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest throwaway dir; the payload path deliberately points at nothing.
    monkeypatch : pytest.MonkeyPatch
        Used to set the GitHub Actions environment variables.
    """
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(tmp_path / "does_not_exist.json"))
    monkeypatch.setenv("GITHUB_ACTOR", "dependabot[bot]")

    assert ledger.pr_author_login() == ""


def test_unreadable_payload_exempts_nobody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corrupt payload must fail closed rather than exempt the whole run."""
    path_event = tmp_path / "event.json"
    path_event.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(path_event))
    monkeypatch.delenv("GITHUB_ACTOR", raising=False)

    assert ledger.is_bot_author(ledger.pr_author_login()) is False


def test_local_run_has_no_author_and_stays_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    """Off CI (a local pre-commit) nothing is exempt — the gate behaves exactly as before."""
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    monkeypatch.delenv("GITHUB_ACTOR", raising=False)

    assert ledger.is_bot_author(ledger.pr_author_login()) is False


_RUFF_BASE = """
select = [
    "E",
    "F",
    "S",
]
ignore = [
    "D206",
]
exclude = [
    ".venv",
]

[lint.per-file-ignores]
"bin/*.py" = [
    "ERA001",
]
"""


def test_hook_removal_is_detected() -> None:
    """The should-fail witness: a hook present at the base and gone now is reported by name."""
    str_old = "repos:\n  - hooks:\n      - id: check-complexity\n      - id: ruff\n"
    str_new = "repos:\n  - hooks:\n      - id: ruff\n"
    list_problems = gate_integrity.precommit_problems(str_old, str_new, ".pre-commit-config.yaml")
    assert list_problems == [".pre-commit-config.yaml: pre-commit hook 'check-complexity' removed"]


def test_hook_reorder_is_not_a_removal() -> None:
    """NEGATIVE CONTROL: moving a hook must not read as deleting and re-adding it."""
    str_old = "- id: a\n- id: b\n"
    str_new = "- id: b\n- id: a\n"
    assert gate_integrity.precommit_problems(str_old, str_new, "x.yaml") == []


def test_ruff_rule_removed_from_select() -> None:
    """A rule dropped from [lint] select is a weakening."""
    str_new = _RUFF_BASE.replace('    "S",\n', "")
    list_problems = gate_integrity.ruff_toml_problems(_RUFF_BASE, str_new, "ruff.toml")
    assert "ruff.toml: rule 'S' removed from [lint] select" in list_problems


def test_ruff_rule_added_to_ignore() -> None:
    """A rule added to [lint] ignore is a weakening — the rule-level surface PR #306 avoided."""
    str_new = _RUFF_BASE.replace('    "D206",\n', '    "D206",\n    "S608",\n')
    list_problems = gate_integrity.ruff_toml_problems(_RUFF_BASE, str_new, "ruff.toml")
    assert "ruff.toml: rule 'S608' added to [lint] ignore" in list_problems


def test_ruff_exclude_path_added() -> None:
    """Re-excluding a tree that was being checked is a weakening."""
    str_new = _RUFF_BASE.replace('    ".venv",\n', '    ".venv",\n    "src/chassis",\n')
    list_problems = gate_integrity.ruff_toml_problems(_RUFF_BASE, str_new, "ruff.toml")
    assert "ruff.toml: path 'src/chassis' added to exclude" in list_problems


def test_ruff_per_file_ignore_added_is_rule_level_and_flagged() -> None:
    """A per-file-ignore is inherently rule-level for that glob — exactly what #306 avoided."""
    str_old_pfi = '"bin/*.py" = [\n    "ERA001",\n]'
    str_new_pfi = '"bin/*.py" = [\n    "ERA001",\n    "S608",\n]'
    str_new = _RUFF_BASE.replace(str_old_pfi, str_new_pfi)
    list_problems = gate_integrity.ruff_toml_problems(_RUFF_BASE, str_new, "ruff.toml")
    assert "ruff.toml: rule 'S608' added to per-file-ignores['bin/*.py']" in list_problems


def test_ruff_toml_with_no_changes_reports_nothing() -> None:
    """NEGATIVE CONTROL: an untouched (or purely additive-to-select) file passes clean."""
    str_new = _RUFF_BASE.replace('    "S",\n', '    "S",\n    "B",\n')
    assert gate_integrity.ruff_toml_problems(_RUFF_BASE, str_new, "ruff.toml") == []


_MYPY_BASE = "[mypy]\nexclude = (?x)(^utils/typing/|_internal/utils/typing/)\n"


def test_mypy_exclude_path_added() -> None:
    """A new alternative added to [mypy] exclude is a weakening."""
    str_new = _MYPY_BASE.rstrip() + "|^chassis/)\n"
    list_problems = gate_integrity.mypy_ini_problems(_MYPY_BASE, str_new, "mypy.ini")
    assert any("chassis" in str_problem for str_problem in list_problems)


def test_mypy_ignore_errors_section_added() -> None:
    """A new [mypy-X] ignore_errors = True section re-hides a tree, same as blueprintx#190."""
    str_new = _MYPY_BASE + "\n[mypy-chassis.*]\nignore_errors = True\n"
    list_problems = gate_integrity.mypy_ini_problems(_MYPY_BASE, str_new, "mypy.ini")
    assert "mypy.ini: [mypy-chassis.*] ignore_errors = True added" in list_problems


def test_mypy_ignore_errors_flipped_on_existing_section() -> None:
    """The should-fail witness for blueprintx#313.

    Flipping ``ignore_errors`` on a section that was ALREADY there — not just a brand new
    one — must still be caught, by comparing the effective value rather than only scanning
    sections added since the merge-base.
    """
    str_old = _MYPY_BASE + "\n[mypy-legacy_module]\nignore_errors = False\n"
    str_new = _MYPY_BASE + "\n[mypy-legacy_module]\nignore_errors = True\n"
    list_problems = gate_integrity.mypy_ini_problems(str_old, str_new, "mypy.ini")
    assert "mypy.ini: [mypy-legacy_module] ignore_errors = True added" in list_problems


def test_mypy_ignore_errors_left_true_is_not_a_new_weakening() -> None:
    """NEGATIVE CONTROL: a section already True on both sides is pre-existing, not a delta."""
    str_old = _MYPY_BASE + "\n[mypy-legacy_module]\nignore_errors = True\n"
    str_new = _MYPY_BASE + "\n[mypy-legacy_module]\nignore_errors = True\n"
    assert gate_integrity.mypy_ini_problems(str_old, str_new, "mypy.ini") == []


_PYTEST_BASE = (
    "[pytest]\n"
    "filterwarnings =\n"
    "    error:Missing docstring for parameter.*:\n"
    "    ignore::DeprecationWarning:PIL\n"
)


def test_pytest_filterwarnings_escalation_removed() -> None:
    """Dropping an error: escalation quietly downgrades a docstring check to a warning."""
    str_new = "[pytest]\nfilterwarnings =\n    ignore::DeprecationWarning:PIL\n"
    list_problems = gate_integrity.pytest_ini_problems(_PYTEST_BASE, str_new, "pytest.ini")
    assert list_problems == [
        "pytest.ini: filterwarnings escalation 'error:Missing docstring for parameter.*:' removed"
    ]


def test_pytest_ignore_entries_are_not_escalations() -> None:
    """NEGATIVE CONTROL: removing an `ignore:` line is routine noise-tuning, not a weakening."""
    str_new = _PYTEST_BASE.replace("    ignore::DeprecationWarning:PIL\n", "")
    assert gate_integrity.pytest_ini_problems(_PYTEST_BASE, str_new, "pytest.ini") == []


def test_workflow_job_removed() -> None:
    """A job dropped from a workflow's jobs: block is a check silently switched off."""
    str_old = "jobs:\n  lint-shell:\n    runs-on: x\n  complexity:\n    runs-on: x\n"
    str_new = "jobs:\n  complexity:\n    runs-on: x\n"
    list_problems = gate_integrity.workflow_problems(str_old, str_new, "tests.yaml")
    assert list_problems == ["tests.yaml: workflow job 'lint-shell' removed"]


def test_required_status_check_removed() -> None:
    """A context dropped from REQUIRED_CHECKS is a weakening of the branch-protection ruleset."""
    str_old = 'REQUIRED_CHECKS=(\n  "Review threads answered"\n  "lint-shell"\n)\n'
    str_new = 'REQUIRED_CHECKS=(\n  "lint-shell"\n)\n'
    list_problems = gate_integrity.required_checks_problems(
        str_old, str_new, "enable_repo_rules.sh"
    )
    assert list_problems == [
        "enable_repo_rules.sh: required status check 'Review threads answered' removed"
    ]


def test_deletion_flags_a_bin_ci_script() -> None:
    """A quality-check script deleted outright is the bluntest form of weakening."""
    list_changed = [("D", "bin/ci/check_actions.sh"), ("M", "README.md")]
    list_problems = gate_integrity.deletion_problems(list_changed)
    assert list_problems == ["bin/ci/check_actions.sh: quality-check script deleted"]


def test_deletion_flags_a_bin_check_script() -> None:
    """The template-side equivalent: bin/check_*.py / bin/lint_*.sh, not just bin/ci/."""
    list_changed = [("D", "bin/check_typing.py")]
    assert gate_integrity.deletion_problems(list_changed) == [
        "bin/check_typing.py: quality-check script deleted"
    ]


def test_deletion_flags_a_watched_config_file() -> None:
    """The should-fail witness for blueprintx#313.

    Deleting ``ruff.toml`` outright — the most complete weakening possible — must be caught
    even though no line-level rule diff exists to read, because there is no file left to
    read one from.
    """
    list_changed = [("D", "ruff.toml"), ("M", "README.md")]
    assert gate_integrity.deletion_problems(list_changed) == [
        "ruff.toml: watched gate configuration deleted"
    ]


def test_deletion_flags_a_deleted_workflow() -> None:
    """Same weakening, workflow-shaped: deleting the file removes every job at once."""
    list_changed = [("D", ".github/workflows/tests.yaml")]
    assert gate_integrity.deletion_problems(list_changed) == [
        ".github/workflows/tests.yaml: watched gate configuration deleted"
    ]


def test_ordinary_source_file_is_not_dispatched() -> None:
    """⚠️ THE SHOULD-PASS WITNESS.

    This gate reads only the watched config basenames — an ordinary source file (where a
    `# noqa: E501` line-level suppression would live) is structurally invisible to it, by
    construction rather than by exception list.
    """
    assert Path("src/model/foo.py").name not in gate_integrity._DICT_DISPATCH


def test_an_ordinary_source_file_is_not_a_watched_workflow_path() -> None:
    """The second half of the should-pass witness: the path regex is blind to it too.

    Split from its sibling rather than folded in (blueprintx#544): the dispatch table and
    the workflow-path regex are two independent doors, and one assertion covering both
    cannot say which one opened.
    """
    assert gate_integrity.RE_WORKFLOW_PATH.search("src/model/foo.py") is None


def test_justification_reason_reads_the_pr_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `gate-change-ok: <reason>` line in the PR body satisfies the escape hatch."""
    str_event = _write_event(
        tmp_path, {"pull_request": {"body": "Removes a duplicate hook.\n\ngate-change-ok: dup"}}
    )
    monkeypatch.setenv("GITHUB_EVENT_PATH", str_event)
    monkeypatch.setattr(gate_integrity, "_git", lambda _args: "")

    assert gate_integrity.justification_reason("deadbeef") == "dup"


@pytest.mark.parametrize(
    "str_marker",
    ["gate-change-ok:\n", "gate-change-ok:   \n"],
    ids=["empty", "whitespace-only"],
)
def test_bare_marker_with_no_reason_does_not_satisfy(str_marker: str) -> None:
    """The reason is REQUIRED, matching `# complexity-ok: <reason>` elsewhere in this repo."""
    assert gate_integrity.RE_JUSTIFICATION.search(str_marker) is None


def test_module_stem_strips_the_test_prefix() -> None:
    """The repo's own naming convention IS the correlation signal — no directory mapping."""
    assert gate_integrity.test_module_stem("tests/unit/test_decimals.py") == "decimals"


def test_touched_code_stems_ignores_test_files_and_non_python() -> None:
    """Only non-test .py files contribute a stem; a test file must never gate on itself."""
    list_changed = [
        ("M", "src/utils/decimals.py"),
        ("M", "tests/unit/test_decimals.py"),
        ("M", "README.md"),
    ]
    assert gate_integrity.touched_code_stems(list_changed) == frozenset({"decimals"})


_TEST_OLD = '''
def test_to_decimal_strict_truncates_by_default() -> None:
	"""Truncation, not rounding, is the documented contract."""
	assert to_decimal_strict("1.999", 2) == Decimal("1.99")


def test_something_unrelated() -> None:
	"""Untouched sibling test — must never appear in any finding."""
	assert 1 == 1
'''

_TEST_NEW_WEAKENED = _TEST_OLD.replace(
    'assert to_decimal_strict("1.999", 2) == Decimal("1.99")',
    'assert to_decimal_strict("1.999", 2) == Decimal("2.00")',
)


@pytest.mark.parametrize(
    ("str_fragment", "bool_present"),
    [
        ("test_to_decimal_strict_truncates_by_default", True),
        ("expected value changed", True),
        ("test_something_unrelated", False),
    ],
    ids=["names-the-test", "names-the-weakening", "does-not-name-the-innocent-test"],
)
def test_assertion_expected_value_changed_is_detected_and_names_the_test(
    str_fragment: str, bool_present: bool
) -> None:
    """⚠️ THE SHOULD-FAIL WITNESS: the exact #323 shape — same call, new expected value."""
    str_problem = _first_problem(
        gate_integrity.test_assertion_problems(
            _TEST_OLD, _TEST_NEW_WEAKENED, "tests/unit/test_decimals.py"
        )
    )

    assert (str_fragment in str_problem) is bool_present


def test_only_the_weakened_assertion_is_reported_not_a_cascade() -> None:
    """Exactly one finding — the count claim, split out rather than dropped (#544).

    Keeping it is what makes the "does-not-name-the-innocent-test" case above meaningful:
    that case now reads the FIRST problem, so without this test a second problem naming
    ``test_something_unrelated`` could hide behind it.
    """
    assert (
        len(
            gate_integrity.test_assertion_problems(
                _TEST_OLD, _TEST_NEW_WEAKENED, "tests/unit/test_decimals.py"
            )
        )
        == 1
    )


def test_assertion_unrelated_rewrite_is_not_flagged() -> None:
    """NEGATIVE CONTROL: a line whose left-hand expression ALSO changed is not the #323 shape."""
    str_new = _TEST_OLD.replace(
        'assert to_decimal_strict("1.999", 2) == Decimal("1.99")',
        'assert to_decimal_strict("1.999", 3) == Decimal("1.999")',
    )
    assert gate_integrity.test_assertion_problems(_TEST_OLD, str_new, "x") == []


def test_assertion_operator_weakened_to_in_is_detected() -> None:
    """The #289 shape: `==` (pins one value) replaced by `in` (pins a set, can't pin one)."""
    str_old = 'def test_intent() -> None:\n\tassert resolve_intent(x) == "send"\n'
    str_new = 'def test_intent() -> None:\n\tassert resolve_intent(x) in {"send", "reconcile"}\n'
    list_problems = gate_integrity.test_assertion_problems(str_old, str_new, "x")
    assert any("operator weakened from '==' to 'in'" in str_p for str_p in list_problems)


def test_assert_equal_to_assert_true_is_detected() -> None:
    """`assertTrue` cannot fail on the SHAPE `assertEqual` was pinning, only on falsiness."""
    str_old = "def test_x(self) -> None:\n\tself.assertEqual(compute(), 42)\n"
    str_new = "def test_x(self) -> None:\n\tself.assertTrue(compute())\n"
    list_problems = gate_integrity.test_assertion_problems(str_old, str_new, "x")
    assert any("assertEqual() -> assertTrue()" in str_p for str_p in list_problems)


def test_pytest_raises_broadened_is_detected() -> None:
    """A narrow, meaningful exception widened to the exception hierarchy's root catches nothing."""
    str_old = "def test_x() -> None:\n\twith pytest.raises(ValueError):\n\t\tdo_thing()\n"
    str_new = "def test_x() -> None:\n\twith pytest.raises(Exception):\n\t\tdo_thing()\n"
    list_problems = gate_integrity.test_assertion_problems(str_old, str_new, "x")
    assert any("pytest.raises broadened" in str_p for str_p in list_problems)


def test_pytest_raises_removed_is_detected() -> None:
    """Dropping the raises wrapper entirely stops asserting the error ever happens.

    The removal reindents the wrapped body, so this is caught by the whole-file COUNT check
    (``raises_count_decreased``), not the same-length line-replace pairing.
    """
    str_old = "def test_x() -> None:\n\twith pytest.raises(ValueError):\n\t\tdo_thing()\n"
    str_new = "def test_x() -> None:\n\tdo_thing()\n"
    list_problems = gate_integrity.test_assertion_problems(str_old, str_new, "x")
    assert any("pytest.raises(...) count dropped" in str_p for str_p in list_problems)


def test_deleted_test_is_detected() -> None:
    """A test function gone at HEAD is as much a weakening as a gutted one."""
    str_old = (
        "def test_a() -> None:\n\tassert 1 == 1\n\n\ndef test_b() -> None:\n\tassert 2 == 2\n"
    )
    str_new = "def test_a() -> None:\n\tassert 1 == 1\n"
    list_problems = gate_integrity.deleted_or_gutted_tests(str_old, str_new, "x")
    assert list_problems == ["x: test 'test_b' deleted"]


def test_gutted_test_body_is_detected() -> None:
    """A body collapsed to `pass` is functionally the same as deleting the test."""
    str_old = 'def test_a() -> None:\n\t"""Doc."""\n\tassert compute() == 42\n'
    str_new = 'def test_a() -> None:\n\t"""Doc."""\n\tpass\n'
    list_problems = gate_integrity.deleted_or_gutted_tests(str_old, str_new, "x")
    assert list_problems == ["x: test 'test_a' body replaced with a no-op"]


def test_gutted_test_body_assert_true_is_detected() -> None:
    """`assert True` never fails — an equally silent way to gut a test."""
    str_old = "def test_a() -> None:\n\tassert compute() == 42\n"
    str_new = "def test_a() -> None:\n\tassert True\n"
    list_problems = gate_integrity.deleted_or_gutted_tests(str_old, str_new, "x")
    assert list_problems == ["x: test 'test_a' body replaced with a no-op"]


def test_new_test_with_a_trivial_body_is_not_flagged() -> None:
    """NEGATIVE CONTROL: a BRAND NEW test has nothing to have been gutted FROM."""
    str_old = ""
    str_new = "def test_a() -> None:\n\tpass\n"
    assert gate_integrity.deleted_or_gutted_tests(str_old, str_new, "x") == []


def test_newly_skipped_test_is_detected() -> None:
    """A skip mark added since the merge-base stops the test from ever running at all."""
    str_old = "def test_a() -> None:\n\tassert compute() == 42\n"
    str_new = (
        "@pytest.mark.skip(reason='flaky')\ndef test_a() -> None:\n\tassert compute() == 42\n"
    )
    list_problems = gate_integrity.newly_skipped_tests(str_old, str_new, "x")
    assert list_problems == ["x: test 'test_a' newly decorated @pytest.mark.skip"]


def test_preexisting_skip_mark_is_not_a_new_weakening() -> None:
    """NEGATIVE CONTROL: a mark present on BOTH sides is pre-existing, not a delta."""
    str_old = "@pytest.mark.skip\ndef test_a() -> None:\n\tassert compute() == 42\n"
    str_new = "@pytest.mark.skip\ndef test_a() -> None:\n\tassert compute() == 43\n"
    assert gate_integrity.newly_skipped_tests(str_old, str_new, "x") == []


@pytest.mark.parametrize(
    ("str_path", "bool_watched"),
    [
        ("tests/unit/test_decimals.py", True),
        ("templates/python-common/tests/unit/test_x.py", True),
        ("src/utils/decimals.py", False),
    ],
    ids=["bare-tests-tree", "nested-template-tests-tree", "ordinary-source-file"],
)
def test_test_path_regex_matches_unit_and_integration_only(
    str_path: str, bool_watched: bool
) -> None:
    """Only the shipped test tree is watched — an ordinary source file is invisible to this."""
    assert (gate_integrity.RE_TEST_PATH.search(str_path) is not None) is bool_watched


def _stub_show(str_ref: str, _str_path: str) -> str:
    """Module-level stand-in for ``show`` — a nested ``def`` inside a test costs +1 complexity.

    Parameters
    ----------
    str_ref : str
        ``STR_INDEX_REF`` (the new content) or anything else (the merge-base content).
    _str_path : str
        Unused — ``show``'s real signature, kept for ``monkeypatch.setattr`` compatibility.

    Returns
    -------
    str
        ``_TEST_NEW_WEAKENED`` for the index ref, ``_TEST_OLD`` otherwise.
    """
    return {gate_integrity.STR_INDEX_REF: _TEST_NEW_WEAKENED}.get(str_ref, _TEST_OLD)


def test_file_problems_fires_when_code_under_test_is_also_touched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end wiring: a real weakening surfaces only when the correlation signal is met."""
    set_stems = gate_integrity.touched_code_stems(
        [("M", "src/utils/decimals.py"), ("M", "tests/unit/test_decimals.py")]
    )
    monkeypatch.setattr(gate_integrity, "show", _stub_show)
    list_problems = gate_integrity.file_problems(
        "tests/unit/test_decimals.py", "deadbeef", set_stems
    )
    assert any("expected value changed" in str_p for str_p in list_problems)


def test_file_problems_stays_silent_when_code_under_test_is_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """⚠️ THE SHOULD-PASS WITNESS (issue #324, Case 3).

    Correcting a wrong expectation alone — no change to the code it tests — is the legitimate
    case and must never be caught.
    """
    monkeypatch.setattr(gate_integrity, "show", _stub_show)
    list_problems = gate_integrity.file_problems(
        "tests/unit/test_decimals.py", "deadbeef", frozenset()
    )
    assert list_problems == []


def test_deletion_flags_a_test_file_deleted_with_its_code() -> None:
    """Deleting the whole test file is the bluntest form of weakening it.

    Same as #313's config case — but only when the branch also touches the code the deleted
    test covered.
    """
    list_changed = [("D", "tests/unit/test_decimals.py"), ("M", "src/utils/decimals.py")]
    set_stems = gate_integrity.touched_code_stems(list_changed)
    assert gate_integrity.deletion_problems(list_changed, set_stems) == [
        "tests/unit/test_decimals.py: test file deleted while its code under test changed"
    ]


def test_deletion_of_a_test_file_alone_is_not_flagged() -> None:
    """NEGATIVE CONTROL: a test file deleted with NO matching code change is out of scope here.

    E.g. a real cleanup of an obsolete test, not a cover-up.
    """
    list_changed = [("D", "tests/unit/test_decimals.py")]
    set_stems = gate_integrity.touched_code_stems(list_changed)
    assert gate_integrity.deletion_problems(list_changed, set_stems) == []


def test_a_string_literal_cannot_restore_the_raises_count() -> None:
    """A regex over source text counts occurrences; only calls are calls."""
    gate_integrity = _load("check_gate_integrity")
    assert gate_integrity.count_pytest_raises_calls('marker = "pytest.raises(ValueError)"\n') == 0


def test_a_real_raises_call_is_still_counted() -> None:
    """The control: tightening the count must not blind it to the genuine wrapper."""
    gate_integrity = _load("check_gate_integrity")
    assert (
        gate_integrity.count_pytest_raises_calls("with pytest.raises(ValueError):\n\tpass\n") == 1
    )


def test_unparsable_source_falls_back_to_the_regex_count() -> None:
    """One diff side can be a fragment; a rough count beats no count."""
    gate_integrity = _load("check_gate_integrity")
    assert (
        gate_integrity.count_pytest_raises_calls("with pytest.raises(ValueError):\n\tdef f(:") == 1
    )


def test_not_equal_is_weaker_than_equal() -> None:
    """``!=`` accepts every value except one, so it is a weakening of ``==``."""
    gate_integrity = _load("check_gate_integrity")
    assert "!=" in gate_integrity._SET_WEAKER_THAN_EQ


def test_skipif_does_not_register_a_skip_mark() -> None:
    """``@pytest.mark.skipif(platform.skip, …)`` holds `skip` in its ARGUMENTS, not as a mark."""
    import ast

    gate_integrity = _load("check_gate_integrity")
    cls_node = ast.parse(
        '@pytest.mark.skipif(platform.skip, reason="x")\ndef test_a() -> None:\n\tpass\n'
    ).body[0]
    assert gate_integrity.skip_marks(cls_node) == frozenset()


def test_a_bare_skip_mark_is_still_registered() -> None:
    """The control: excluding `skipif` must not exclude `skip` itself."""
    import ast

    gate_integrity = _load("check_gate_integrity")
    cls_node = ast.parse("@pytest.mark.skip\ndef test_b() -> None:\n\tpass\n").body[0]
    assert gate_integrity.skip_marks(cls_node) == frozenset({"skip"})


def _git_in(path_repo: Path, *args: str) -> str:
    """Run ``git`` inside a throwaway repo and return its stripped stdout.

    Parameters
    ----------
    path_repo : pathlib.Path
        The repository to run in.
    *args : str
        Arguments after ``git``.

    Returns
    -------
    str
        Captured stdout, stripped.
    """
    cls_proc = subprocess.run(  # noqa: S603
        ["git", "-C", str(path_repo), *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    return cls_proc.stdout.strip()


@pytest.fixture
def path_mid_merge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return a repo whose ``feature`` has a merge of ``main`` in progress.

    ``main`` moves on after the fork, so a base resolved from the pre-merge HEAD (the fork
    point) differs from main's tip.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest-provided scratch directory.
    monkeypatch : pytest.MonkeyPatch
        Used to run the gate inside the repo.

    Returns
    -------
    pathlib.Path
        The repository, left mid-merge.
    """
    _git_in(tmp_path, "init", "-q", "--initial-branch=main")
    _git_in(tmp_path, "config", "user.email", "t@example.com")
    _git_in(tmp_path, "config", "user.name", "t")
    _git_in(tmp_path, "config", "commit.gpgsign", "false")
    _git_in(tmp_path, "commit", "-q", "--allow-empty", "-m", "seed")
    _git_in(tmp_path, "checkout", "-q", "-b", "feature")
    (tmp_path / "own").write_text("own", encoding="utf-8")
    _git_in(tmp_path, "add", "own")
    _git_in(tmp_path, "commit", "-q", "-m", "own")
    _git_in(tmp_path, "checkout", "-q", "main")
    (tmp_path / "theirs").write_text("theirs", encoding="utf-8")
    _git_in(tmp_path, "add", "theirs")
    _git_in(tmp_path, "commit", "-q", "-m", "theirs")
    _git_in(tmp_path, "checkout", "-q", "feature")
    _git_in(tmp_path, "merge", "-q", "--no-commit", "--no-ff", "main")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_resolve_base_mid_merge_is_the_incoming_tip(path_mid_merge: Path) -> None:
    """Mid-merge the base is main's tip, never the fork point that charges main's delta."""
    assert ledger.resolve_base() == _git_in(path_mid_merge, "rev-parse", "main")
