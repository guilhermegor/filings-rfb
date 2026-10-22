"""Unit tests for the SQL guards gate (blueprintx#355; offline, no git, no network).

Each guard needs BOTH directions proven: the dangerous form must FAIL naming the file, the
line, the fix and the escape hatch; the safe form must PASS. A gate that cannot fail is
reporting its own blindness as OK — the exact failure mode this repo's gates exist to
prevent. The false-positive tests (a plain ``dict.update()``, a single-instance
``session.delete(record)``) are just as load-bearing: the issue's own review history is full
of matchers that fired on every ORM mutation and became 100% noise on first use.
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


gate = _load("check_sql_guards")


def _python_file(path_dir: Path, str_source: str) -> Path:
    """Write a Python source file and return its path.

    Parameters
    ----------
    path_dir : pathlib.Path
        Directory to write into.
    str_source : str
        File contents.

    Returns
    -------
    pathlib.Path
        The written file.
    """
    path_file = path_dir / "sample.py"
    path_file.write_text(str_source, encoding="utf-8")
    return path_file


@pytest.fixture
def list_whereless_delete_problems(tmp_path: Path) -> list[str]:
    """Return the findings for a bare Core ``delete(...)`` with no ``.where()``.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.

    Returns
    -------
    list[str]
        The gate's findings.
    """
    path_file = _python_file(
        tmp_path,
        "from sqlalchemy import delete\n\nstmt = delete(comments)\n",
    )
    return gate.check_python_file(path_file)


def test_whereless_core_delete_is_reported(list_whereless_delete_problems: list[str]) -> None:
    """A bare Core ``delete(...)`` with no ``.where()`` is a violation.

    Parameters
    ----------
    list_whereless_delete_problems : list[str]
        The gate's findings.
    """
    assert len(list_whereless_delete_problems) == 1


def test_whereless_core_delete_finding_names_the_hazard(
    list_whereless_delete_problems: list[str],
) -> None:
    """The finding says the ``delete(...)`` has no ``.where()``.

    Parameters
    ----------
    list_whereless_delete_problems : list[str]
        The gate's findings.
    """
    assert "delete(...) has no .where()" in list_whereless_delete_problems[0]


def test_whereless_core_delete_finding_names_the_file(
    tmp_path: Path,
    list_whereless_delete_problems: list[str],
) -> None:
    """The finding names the file it was found in.

    Parameters
    ----------
    tmp_path : pathlib.Path
        The same per-test directory the fixture wrote ``sample.py`` into.
    list_whereless_delete_problems : list[str]
        The gate's findings.
    """
    assert str(tmp_path / "sample.py") in list_whereless_delete_problems[0]


def test_whereless_core_delete_finding_names_the_escape_hatch(
    list_whereless_delete_problems: list[str],
) -> None:
    """The finding tells the reader how to waive it (``sql-guard-ok:``).

    Parameters
    ----------
    list_whereless_delete_problems : list[str]
        The gate's findings.
    """
    assert "sql-guard-ok:" in list_whereless_delete_problems[0]


def test_whereless_module_qualified_delete_is_reported(tmp_path: Path) -> None:
    """``sa.delete(t)`` is a Core builder, not the ambiguous ``.delete()`` attribute form."""
    path_file = _python_file(
        tmp_path,
        "import sqlalchemy as sa\n\nstmt = sa.delete(comments)\n",
    )

    assert len(gate.check_python_file(path_file)) == 1


def test_whereless_module_qualified_update_is_reported(tmp_path: Path) -> None:
    """The unaliased spelling reaches the same branch — the module name IS the alias."""
    path_file = _python_file(
        tmp_path,
        'import sqlalchemy\n\nstmt = sqlalchemy.update(comments).values(status="x")\n',
    )

    assert len(gate.check_python_file(path_file)) == 1


def test_module_qualified_delete_with_where_passes(tmp_path: Path) -> None:
    """Widening to the module alias must not fire on a properly scoped mutation."""
    path_file = _python_file(
        tmp_path,
        "import sqlalchemy as sa\n\nstmt = sa.delete(comments).where(comments.c.id == 1)\n",
    )

    assert gate.check_python_file(path_file) == []


def test_whereless_core_delete_with_where_passes(tmp_path: Path) -> None:
    """The same call with a ``.where()`` chained on is clean."""
    path_file = _python_file(
        tmp_path,
        "from sqlalchemy import delete\n\nstmt = delete(comments).where(comments.c.id == 1)\n",
    )

    assert gate.check_python_file(path_file) == []


@pytest.fixture
def list_whereless_update_problems(tmp_path: Path) -> list[str]:
    """Return the findings for ``update(...).values(...)`` with no ``.where()``.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.

    Returns
    -------
    list[str]
        The gate's findings.
    """
    path_file = _python_file(
        tmp_path,
        'from sqlalchemy import update\n\nstmt = update(comments).values(status="x")\n',
    )
    return gate.check_python_file(path_file)


def test_whereless_core_update_values_only_is_reported(
    list_whereless_update_problems: list[str],
) -> None:
    """``update(...).values(...)`` with no ``.where()`` mutates every row.

    Parameters
    ----------
    list_whereless_update_problems : list[str]
        The gate's findings.
    """
    assert len(list_whereless_update_problems) == 1


def test_whereless_core_update_finding_names_the_hazard(
    list_whereless_update_problems: list[str],
) -> None:
    """The finding says the ``update(...)`` has no ``.where()``.

    Parameters
    ----------
    list_whereless_update_problems : list[str]
        The gate's findings.
    """
    assert "update(...) has no .where()" in list_whereless_update_problems[0]


@pytest.fixture
def list_query_delete_problems(tmp_path: Path) -> list[str]:
    """Return the findings for ``session.query(Model).delete()`` with no ``.filter()``.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.

    Returns
    -------
    list[str]
        The gate's findings.
    """
    path_file = _python_file(
        tmp_path,
        "from sqlalchemy.orm import Session\n\nsession.query(Model).delete()\n",
    )
    return gate.check_python_file(path_file)


def test_whereless_query_style_delete_is_reported(list_query_delete_problems: list[str]) -> None:
    """``session.query(Model).delete()`` with no ``.filter()`` is a violation.

    Parameters
    ----------
    list_query_delete_problems : list[str]
        The gate's findings.
    """
    assert len(list_query_delete_problems) == 1


def test_whereless_query_style_delete_finding_names_the_hazard(
    list_query_delete_problems: list[str],
) -> None:
    """The finding says the ``delete(...)`` has no ``.where()``.

    Parameters
    ----------
    list_query_delete_problems : list[str]
        The gate's findings.
    """
    assert "delete(...) has no .where()" in list_query_delete_problems[0]


def test_query_style_update_with_filter_passes(tmp_path: Path) -> None:
    """``session.query(Model).filter(...).update(...)`` is a safe, scoped mutation."""
    path_file = _python_file(
        tmp_path,
        "from sqlalchemy.orm import Session\n\n"
        'session.query(Model).filter_by(id=1).update({"x": 1})\n',
    )

    assert gate.check_python_file(path_file) == []


def test_single_instance_session_delete_is_not_flagged(tmp_path: Path) -> None:
    """``session.delete(record)`` (primary-key-scoped) must never be flagged.

    This is the ONLY delete pattern this repo's own ORM templates ship today — a matcher
    that fires here would break on first use, exactly the failure mode the issue warns
    against.
    """
    path_file = _python_file(
        tmp_path,
        "from sqlalchemy.orm import Session\n\nsession.delete(record)\n",
    )

    assert gate.check_python_file(path_file) == []


def test_plain_dict_update_in_a_sqlalchemy_file_is_not_flagged(tmp_path: Path) -> None:
    """A ``dict.update()`` call must not be confused for a SQLAlchemy mutation."""
    path_file = _python_file(
        tmp_path,
        "from sqlalchemy.orm import Session\n\ndict_config.update(other_dict)\n",
    )

    assert gate.check_python_file(path_file) == []


def test_no_sqlalchemy_import_skips_the_whereless_check(tmp_path: Path) -> None:
    """A file with no ``sqlalchemy`` import is out of scope entirely."""
    path_file = _python_file(tmp_path, "stmt = delete(comments)\n")

    assert gate.check_python_file(path_file) == []


@pytest.fixture
def list_nolock_literal_problems(tmp_path: Path) -> list[str]:
    """Return the findings for a ``WITH (NOLOCK)`` hint inside a Python string literal.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.

    Returns
    -------
    list[str]
        The gate's findings.
    """
    path_file = _python_file(
        tmp_path,
        'str_query = "SELECT * FROM comments WITH (NOLOCK)"\n',
    )
    return gate.check_python_file(path_file)


def test_nolock_in_python_string_literal_is_reported(
    list_nolock_literal_problems: list[str],
) -> None:
    """A ``WITH (NOLOCK)`` hint inside a Python string literal is a violation.

    Parameters
    ----------
    list_nolock_literal_problems : list[str]
        The gate's findings.
    """
    assert len(list_nolock_literal_problems) == 1


def test_nolock_finding_names_the_hint(list_nolock_literal_problems: list[str]) -> None:
    """The finding quotes the offending hint.

    Parameters
    ----------
    list_nolock_literal_problems : list[str]
        The gate's findings.
    """
    assert "WITH (NOLOCK)" in list_nolock_literal_problems[0]


def test_nolock_finding_names_the_dirty_read_risk(
    list_nolock_literal_problems: list[str],
) -> None:
    """The finding explains the dirty-read risk.

    Parameters
    ----------
    list_nolock_literal_problems : list[str]
        The gate's findings.
    """
    assert "dirty read" in list_nolock_literal_problems[0].lower()


def test_nolock_finding_names_the_escape_hatch(
    list_nolock_literal_problems: list[str],
) -> None:
    """The finding names the hatch that justifies a deliberate hint.

    Parameters
    ----------
    list_nolock_literal_problems : list[str]
        The gate's findings.
    """
    assert "sql-guard-ok:" in list_nolock_literal_problems[0]


@pytest.fixture
def list_nolock_sql_file_problems(tmp_path: Path) -> list[str]:
    """Return the findings for a ``WITH (NOLOCK)`` hint in a raw ``.sql`` file.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.

    Returns
    -------
    list[str]
        The gate's findings.
    """
    path_file = tmp_path / "query.sql"
    path_file.write_text("SELECT * FROM comments WITH (NOLOCK);\n", encoding="utf-8")
    return gate._nolock_problems_in_sql(path_file)


def test_nolock_in_sql_file_is_reported(list_nolock_sql_file_problems: list[str]) -> None:
    """A ``WITH (NOLOCK)`` hint in a raw ``.sql`` file is a violation.

    Parameters
    ----------
    list_nolock_sql_file_problems : list[str]
        The gate's findings.
    """
    assert len(list_nolock_sql_file_problems) == 1


def test_nolock_in_sql_file_finding_names_the_hint(
    list_nolock_sql_file_problems: list[str],
) -> None:
    """The ``.sql`` finding quotes the offending hint.

    Parameters
    ----------
    list_nolock_sql_file_problems : list[str]
        The gate's findings.
    """
    assert "WITH (NOLOCK)" in list_nolock_sql_file_problems[0]


@pytest.fixture
def list_second_nolock_problems(tmp_path: Path) -> list[str]:
    """Return the findings for a literal whose first hint carries a hatch and second does not.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.

    Returns
    -------
    list[str]
        The gate's findings.
    """
    path_file = _python_file(
        tmp_path,
        "STR_Q = (\n"
        '\t"SELECT a FROM t1 WITH (NOLOCK) "  # sql-guard-ok: reporting replica\n'
        '\t"UNION ALL SELECT b FROM t2 WITH (NOLOCK)"\n'
        ")\n",
    )
    return gate.check_python_file(path_file)


def test_second_nolock_in_one_literal_is_still_reported(
    list_second_nolock_problems: list[str],
) -> None:
    """A hatch on the first hint must not cover a second, unannotated one in the same literal.

    Parameters
    ----------
    list_second_nolock_problems : list[str]
        The gate's findings.
    """
    assert len(list_second_nolock_problems) == 1


def test_second_nolock_finding_points_at_the_unannotated_line(
    list_second_nolock_problems: list[str],
) -> None:
    """The one finding points at line 3, the unannotated hint.

    Parameters
    ----------
    list_second_nolock_problems : list[str]
        The gate's findings.
    """
    assert ":3:" in list_second_nolock_problems[0]


@pytest.fixture
def list_split_nolock_problems(tmp_path: Path) -> list[str]:
    """Return the findings for a hint broken after ``WITH`` across two lines.

    Parameters
    ----------
    tmp_path : pathlib.Path
        A throwaway directory pytest provides per test.

    Returns
    -------
    list[str]
        The gate's findings.
    """
    path_file = tmp_path / "query.sql"
    path_file.write_text(
        "SELECT *\nFROM comments WITH\n(NOLOCK)\nWHERE id = 1;\n", encoding="utf-8"
    )
    return gate._nolock_problems_in_sql(path_file)


def test_nolock_split_across_lines_is_reported(list_split_nolock_problems: list[str]) -> None:
    """A hint broken after ``WITH`` is one hint; a per-line search never spans the break.

    Parameters
    ----------
    list_split_nolock_problems : list[str]
        The gate's findings.
    """
    assert len(list_split_nolock_problems) == 1


def test_nolock_split_across_lines_points_at_the_line_it_starts_on(
    list_split_nolock_problems: list[str],
) -> None:
    """The finding points at line 2, where the hint starts.

    Parameters
    ----------
    list_split_nolock_problems : list[str]
        The gate's findings.
    """
    assert ":2:" in list_split_nolock_problems[0]


def test_nolock_split_across_lines_honours_the_hatch(tmp_path: Path) -> None:
    """The hatch is read on the line the match STARTS on, not on the line it ends."""
    path_file = tmp_path / "query.sql"
    path_file.write_text(
        "SELECT *\nFROM comments WITH  -- sql-guard-ok: reporting replica\n(NOLOCK);\n",
        encoding="utf-8",
    )

    assert gate._nolock_problems_in_sql(path_file) == []


def test_query_without_nolock_passes(tmp_path: Path) -> None:
    """A plain read with no ``NOLOCK`` hint is clean."""
    path_file = tmp_path / "query.sql"
    path_file.write_text("SELECT * FROM comments;\n", encoding="utf-8")

    assert gate._nolock_problems_in_sql(path_file) == []


def test_escape_hatch_with_reason_suppresses_the_finding(tmp_path: Path) -> None:
    """A written reason after the marker is accepted."""
    path_file = _python_file(
        tmp_path,
        "from sqlalchemy import delete\n\n"
        "stmt = delete(comments)  # sql-guard-ok: full purge, reviewed in PR #123\n",
    )

    assert gate.check_python_file(path_file) == []


def test_escape_hatch_with_empty_reason_still_fails(tmp_path: Path) -> None:
    """A bare marker with no reason (or whitespace only) is rejected, not accepted."""
    path_file = _python_file(
        tmp_path,
        "from sqlalchemy import delete\n\nstmt = delete(comments)  # sql-guard-ok:   \n",
    )

    list_problems = gate.check_python_file(path_file)

    assert len(list_problems) == 1


def test_main_skips_when_src_is_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No ``src/`` directory at all is a legitimate skip."""
    monkeypatch.chdir(tmp_path)

    assert gate.main() == 0


def test_main_fails_on_zero_discovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``src/`` exists but holds no Python files — that must FAIL, not pass silently."""
    (tmp_path / "src").mkdir()
    monkeypatch.chdir(tmp_path)

    assert gate.main() == 1


def test_main_passes_on_a_clean_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real file with no violations reports success."""
    path_src = tmp_path / "src"
    path_src.mkdir()
    (path_src / "mod.py").write_text("int_x = 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert gate.main() == 0
