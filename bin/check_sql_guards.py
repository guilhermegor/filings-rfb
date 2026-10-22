"""Structural gate: SQL guards for the SILENT WRONG ANSWER (blueprintx#355).

A gate's value is decidability times severity, and for AI-written code severity has a
specific shape: a model produces plausible-looking code by construction, so the failures it
is most likely to ship are the ones where the code READS correctly and BEHAVES wrongly. A
crash reports itself; a wrong number does not.

Two guards ship here, both scoped to what an AST or a keyword search can decide without
guessing:

1. **WHERE-less DELETE/UPDATE.** ``delete(comments)`` with no ``.where(...)`` mutates or
   erases every row in the table, silently — no exception, no warning. Detected for the
   SQLAlchemy Core builder (``delete(...)``/``update(...)`` imported from ``sqlalchemy``) and
   for the legacy ``session.query(Model)...delete()/update()`` chain. ⚠️ The query-style check
   fires ONLY when ``.query(`` appears in the same call chain — without that anchor, a bare
   ``.update()``/``.delete()`` attribute match is 100% noise (a dict's own ``.update()``, a
   single-instance ``session.delete(record)`` which is already primary-key-scoped and safe).
   That anchor is also why ``session.delete(record)`` — the only delete pattern this repo's
   own ORM templates ship today — is correctly never flagged.

2. **``WITH (NOLOCK)``.** This FLAGS the hint, it does not require it (the original proposal
   was inverted on review — see blueprintx#355). ``NOLOCK`` is ``READ UNCOMMITTED``: dirty
   reads from transactions that later roll back, and missed/duplicated rows during a page
   split, with no error raised. It is MSSQL-only syntax. The real fix for non-blocking reads
   on MSSQL is ``READ_COMMITTED_SNAPSHOT`` (RCSI) at the database level, not a query hint.
   Scanned in Python string/f-string literals (AST) and in raw ``.sql`` files (text) — one
   keyword, two surfaces, since SQL reaches this codebase both ways.

**Escape hatch**, same shape as ``dtype-ok:``/``complexity-ok:`` elsewhere in this tree::

    stmt = delete(comments)  # sql-guard-ok: full-table purge, reviewed in PR #123

An empty or whitespace-only reason after the marker is rejected — the marker's presence is
not a decision, the written reason is.

**Explicitly out of scope for this gate** (see blueprintx#355 for the full analysis):
``SELECT *``, DDL in application code, ``float`` for money, and CPF/CNPJ/CNH normalisation —
each is decidable but is its own rule with its own false-positive shape, and shipping six
rules in one diff gives no way to tell which one caused a regression. Raw ``.sql`` WHERE-less
DELETE/UPDATE is also out: that needs a SQL-grammar parser (a custom sqlfluff rule, or a
dedicated tokenizer), a different mechanism from the Python AST check above it, not a
regex extension of it.

⚠️ **Zero findings on a real project tree is the expected result, not a broken gate** — the
templates' own ORM code has no WHERE-less mutation and no NOLOCK hint today. The synthetic
probes in this gate's own test suite are what prove discovery actually works.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys


_ALLOW_MARKER = "sql-guard-ok:"
_SRC_ROOT = "src"

_RE_NOLOCK = re.compile(r"with\s*\(\s*nolock\s*\)", re.IGNORECASE)

_MUTATION_NAMES = frozenset({"delete", "update"})
_WHERE_NAMES = frozenset({"where", "filter", "filter_by"})


def _hatch_reason(str_line: str) -> str | None:
    """Return the escape-hatch reason on a line, or ``None`` when there isn't one.

    Parameters
    ----------
    str_line : str
        The source line to inspect.

    Returns
    -------
    str or None
        The written reason, or ``None`` when the marker is absent OR the reason after it is
        empty/whitespace-only — a bare marker is not a decision anyone made on purpose.
    """
    if _ALLOW_MARKER not in str_line:
        return None
    return str_line.split(_ALLOW_MARKER, 1)[1].strip() or None


def _line_allowed(list_lines: list[str], int_line: int) -> bool:
    """Return whether a 1-indexed line carries a valid escape-hatch reason.

    Parameters
    ----------
    list_lines : list of str
        The source file, split into lines.
    int_line : int
        The 1-indexed line number to check.

    Returns
    -------
    bool
        ``True`` only when the line exists and carries a non-empty reason.
    """
    if not (1 <= int_line <= len(list_lines)):
        return False
    return _hatch_reason(list_lines[int_line - 1]) is not None


def _sqlalchemy_usage(cls_tree: ast.Module) -> tuple[bool, set[str], set[str]]:
    """Return whether the module imports ``sqlalchemy``, and its bare mutation aliases.

    Parameters
    ----------
    cls_tree : ast.Module
        The parsed module.

    Returns
    -------
    tuple of (bool, set of str, set of str)
        Whether any ``sqlalchemy`` import is present; the local names bound to
        ``sqlalchemy``'s ``delete``/``update`` Core builder functions (honouring ``as``
        aliases), e.g. ``{"delete", "update"}`` for a plain ``from sqlalchemy import
        delete, update``; and the local names bound to the ``sqlalchemy`` MODULE itself,
        e.g. ``{"sa"}`` for ``import sqlalchemy as sa``.
    """
    bool_uses_sqlalchemy = False
    set_core_aliases: set[str] = set()
    set_module_aliases: set[str] = set()
    for cls_node in ast.walk(cls_tree):
        if isinstance(cls_node, ast.Import):
            for cls_alias in cls_node.names:
                if cls_alias.name == "sqlalchemy" or cls_alias.name.startswith("sqlalchemy."):
                    bool_uses_sqlalchemy = True
                    set_module_aliases.add(cls_alias.asname or cls_alias.name.split(".")[0])
        elif (
            isinstance(cls_node, ast.ImportFrom)
            and cls_node.module
            and (cls_node.module == "sqlalchemy" or cls_node.module.startswith("sqlalchemy."))
        ):
            bool_uses_sqlalchemy = True
            for cls_alias in cls_node.names:
                if cls_alias.name in _MUTATION_NAMES:
                    set_core_aliases.add(cls_alias.asname or cls_alias.name)
    return bool_uses_sqlalchemy, set_core_aliases, set_module_aliases


def _parent_map(cls_tree: ast.AST) -> dict[int, ast.AST]:
    """Map ``id(child)`` to its parent, so a call chain can be climbed upward.

    Parameters
    ----------
    cls_tree : ast.AST
        The parsed module.

    Returns
    -------
    dict of int to ast.AST
        Parent lookup keyed by the child node's ``id()``.
    """
    dict_parents: dict[int, ast.AST] = {}
    for cls_node in ast.walk(cls_tree):
        for cls_child in ast.iter_child_nodes(cls_node):
            dict_parents[id(cls_child)] = cls_node
    return dict_parents


def _downward_chain_names(cls_call: ast.Call) -> list[str]:
    """Collect the function/method names walking DOWN a call chain, outer to inner.

    ``session.query(Model).filter(x).delete()`` yields ``["delete", "filter", "query"]`` when
    called with the outermost (``.delete()``) node.

    Parameters
    ----------
    cls_call : ast.Call
        The call to start from.

    Returns
    -------
    list of str
        Names encountered, outer to inner.
    """
    list_names: list[str] = []
    cls_node: ast.expr = cls_call
    while isinstance(cls_node, ast.Call):
        if isinstance(cls_node.func, ast.Name):
            list_names.append(cls_node.func.id)
            break
        if isinstance(cls_node.func, ast.Attribute):
            list_names.append(cls_node.func.attr)
            cls_node = cls_node.func.value
            continue
        break
    return list_names


def _upward_chain_names(cls_call: ast.Call, dict_parents: dict[int, ast.AST]) -> list[str]:
    """Collect method names chained AFTER this call, e.g. ``.where(...)`` appended on top.

    ``delete(comments).where(...)`` yields ``["where"]`` when called with the inner
    ``delete(comments)`` node.

    Parameters
    ----------
    cls_call : ast.Call
        The call to start from.
    dict_parents : dict of int to ast.AST
        Parent lookup from :func:`_parent_map`.

    Returns
    -------
    list of str
        Method names chained on top of ``cls_call``, innermost first.
    """
    list_names: list[str] = []
    cls_current: ast.AST = cls_call
    while True:
        cls_parent = dict_parents.get(id(cls_current))
        if not (isinstance(cls_parent, ast.Attribute) and cls_parent.value is cls_current):
            break
        cls_grandparent = dict_parents.get(id(cls_parent))
        if not (isinstance(cls_grandparent, ast.Call) and cls_grandparent.func is cls_parent):
            break
        list_names.append(cls_parent.attr)
        cls_current = cls_grandparent
    return list_names


def _whereless_message(path_file: pathlib.Path, int_line: int, str_verb: str) -> str:
    """Return the WHERE-less mutation finding, naming the failure mode and the fix.

    Parameters
    ----------
    path_file : pathlib.Path
        The offending file.
    int_line : int
        The line of the mutation call.
    str_verb : str
        ``"delete"`` or ``"update"``.

    Returns
    -------
    str
        A human-readable finding.
    """
    return (
        f"{path_file}:{int_line}: {str_verb}(...) has no .where()/.filter() — a WHERE-less "
        f"{str_verb.upper()} mutates or erases every row in the table, with no error and no "
        f"warning raised. Add .where(<condition>) (or .filter()/.filter_by() on a Query), or "
        f"if a full-table purge/reset is genuinely intended, annotate the line: "
        f"# {_ALLOW_MARKER} <reason>"
    )


def _mutation_verb(
    cls_call: ast.Call, set_core_aliases: set[str], set_module_aliases: set[str]
) -> tuple[str | None, bool]:
    """Return the mutation verb a call invokes, and whether it needs the ``query`` anchor.

    Parameters
    ----------
    cls_call : ast.Call
        The call to classify.
    set_core_aliases : set of str
        Local names bound to ``sqlalchemy``'s bare ``delete``/``update`` builders.
    set_module_aliases : set of str
        Local names bound to the ``sqlalchemy`` module itself, e.g. ``{"sa"}``.

    Returns
    -------
    tuple of (str or None, bool)
        ``(None, False)`` when this call is not a mutation at all. Otherwise the verb
        (``"delete"``/``"update"``), and whether it is the attribute (``.delete()``/
        ``.update()``) form — which needs a ``.query(`` anchor elsewhere in its chain to be
        treated as SQLAlchemy at all, rather than a dict's own ``.update()``.
    """
    if isinstance(cls_call.func, ast.Name) and cls_call.func.id in set_core_aliases:
        return cls_call.func.id, False
    if isinstance(cls_call.func, ast.Attribute) and cls_call.func.attr in _MUTATION_NAMES:
        if (
            isinstance(cls_call.func.value, ast.Name)
            and cls_call.func.value.id in set_module_aliases
        ):
            return cls_call.func.attr, False
        return cls_call.func.attr, True
    return None, False


def _whereless_mutation_problems(
    cls_tree: ast.Module, path_file: pathlib.Path, list_lines: list[str]
) -> list[str]:
    """Report every WHERE-less ``delete``/``update`` mutation in one parsed module.

    Parameters
    ----------
    cls_tree : ast.Module
        The parsed module.
    path_file : pathlib.Path
        The module's path, for the message.
    list_lines : list of str
        The source, split into lines, for the escape-hatch check.

    Returns
    -------
    list of str
        Human-readable findings; empty when the file complies.
    """
    bool_uses_sqlalchemy, set_core_aliases, set_module_aliases = _sqlalchemy_usage(cls_tree)
    if not bool_uses_sqlalchemy:
        return []

    dict_parents = _parent_map(cls_tree)
    list_problems: list[str] = []

    for cls_node in ast.walk(cls_tree):
        if not isinstance(cls_node, ast.Call):
            continue
        str_verb, bool_is_query_style = _mutation_verb(
            cls_node, set_core_aliases, set_module_aliases
        )
        if str_verb is None:
            continue

        list_chain = _downward_chain_names(cls_node) + _upward_chain_names(cls_node, dict_parents)

        if bool_is_query_style and "query" not in list_chain:
            continue
        if any(str_name in list_chain for str_name in _WHERE_NAMES):
            continue
        if _line_allowed(list_lines, cls_node.lineno):
            continue

        list_problems.append(_whereless_message(path_file, cls_node.lineno, str_verb))
    return list_problems


def _nolock_message(path_file: pathlib.Path, int_line: int) -> str:
    """Return the ``WITH (NOLOCK)`` finding, naming the failure mode and the fix.

    Parameters
    ----------
    path_file : pathlib.Path
        The offending file.
    int_line : int
        The line carrying the hint.

    Returns
    -------
    str
        A human-readable finding.
    """
    return (
        f"{path_file}:{int_line}: WITH (NOLOCK) reads uncommitted data — dirty reads from "
        f"transactions that later roll back, and missed/duplicated rows during a page split, "
        f"with NO error raised. It is MSSQL-only syntax. The fix for non-blocking reads is "
        f"READ_COMMITTED_SNAPSHOT (RCSI) at the database level, not a query hint. If this is "
        f"a deliberate, reviewed exception, annotate the line: # {_ALLOW_MARKER} <reason>"
    )


def _nolock_problems_in_python(
    cls_tree: ast.Module, path_file: pathlib.Path, list_lines: list[str]
) -> list[str]:
    """Report every ``WITH (NOLOCK)`` hint inside a Python string/f-string literal.

    Parameters
    ----------
    cls_tree : ast.Module
        The parsed module.
    path_file : pathlib.Path
        The module's path, for the message.
    list_lines : list of str
        The source, split into lines, for the escape-hatch check.

    Returns
    -------
    list of str
        Human-readable findings; empty when the file complies.
    """
    str_source = "\n".join(list_lines)
    list_problems: list[str] = []
    for cls_node in ast.walk(cls_tree):
        if not (isinstance(cls_node, ast.Constant) and isinstance(cls_node.value, str)):
            continue
        str_segment = ast.get_source_segment(str_source, cls_node) or ""
        for cls_match in _RE_NOLOCK.finditer(str_segment):
            int_line = cls_node.lineno + str_segment.count("\n", 0, cls_match.start())
            if not _line_allowed(list_lines, int_line):
                list_problems.append(_nolock_message(path_file, int_line))
    return list_problems


def _nolock_problems_in_sql(path_file: pathlib.Path) -> list[str]:
    """Report every ``WITH (NOLOCK)`` hint in a raw ``.sql`` file.

    Parameters
    ----------
    path_file : pathlib.Path
        The ``.sql`` file to scan.

    Returns
    -------
    list of str
        Human-readable findings; empty when the file complies.
    """
    str_text = path_file.read_text(encoding="utf-8")
    list_lines = str_text.splitlines()
    list_problems: list[str] = []
    for cls_match in _RE_NOLOCK.finditer(str_text):
        int_no = str_text.count("\n", 0, cls_match.start()) + 1
        if _hatch_reason(list_lines[int_no - 1]) is None:
            list_problems.append(_nolock_message(path_file, int_no))
    return list_problems


def check_python_file(path_file: pathlib.Path) -> list[str]:
    """Run both guards against one Python source file.

    Parameters
    ----------
    path_file : pathlib.Path
        The module to check.

    Returns
    -------
    list of str
        Human-readable findings; empty when the file complies.
    """
    str_source = path_file.read_text(encoding="utf-8")
    try:
        cls_tree = ast.parse(str_source)
    except SyntaxError as cls_exc:
        return [f"{path_file}: could not parse ({cls_exc})"]

    list_lines = str_source.splitlines()
    list_problems = _whereless_mutation_problems(cls_tree, path_file, list_lines)
    list_problems += _nolock_problems_in_python(cls_tree, path_file, list_lines)
    return list_problems


def _discovered_files() -> tuple[list[pathlib.Path], list[pathlib.Path]]:
    """Return every Python and ``.sql`` file under ``src/``.

    Returns
    -------
    tuple of (list of pathlib.Path, list of pathlib.Path)
        ``(list_py, list_sql)``, both sorted; empty when ``src/`` has no such files.
    """
    path_src = pathlib.Path(_SRC_ROOT)
    list_py = sorted(p for p in path_src.rglob("*.py") if "__pycache__" not in p.parts)
    list_sql = sorted(path_src.rglob("*.sql"))
    return list_py, list_sql


def main() -> int:
    """Check every Python and ``.sql`` file under ``src/`` against both SQL guards.

    Returns
    -------
    int
        ``0`` when the tree complies (or ``src/`` does not exist), ``1`` otherwise.
    """
    path_src = pathlib.Path(_SRC_ROOT)
    if not path_src.is_dir():
        print(f"No {_SRC_ROOT}/ directory — skipping the SQL guards check.")
        return 0

    list_py, list_sql = _discovered_files()
    if not list_py:
        print(
            f"❌ 0 Python files discovered under {_SRC_ROOT}/ — the SQL guards checked "
            f"NOTHING. A wrong working directory or a broken glob reporting success for "
            f"having checked nothing is the exact failure this gate exists to prevent."
        )
        return 1

    list_problems: list[str] = []
    for path_file in list_py:
        list_problems += check_python_file(path_file)
    for path_file in list_sql:
        list_problems += _nolock_problems_in_sql(path_file)

    for str_problem in list_problems:
        print(f"❌ {str_problem}")
    if list_problems:
        print(f"\n{len(list_problems)} SQL guard violation(s).")
        return 1

    print(
        f"✅ SQL guards OK ({len(list_py)} Python file(s), {len(list_sql)} SQL file(s) checked)."
    )
    return 0


if __name__ == "__main__":
    for cls_stream in (sys.stdout, sys.stderr):
        if hasattr(cls_stream, "reconfigure"):
            cls_stream.reconfigure(encoding="utf-8", errors="replace")

    sys.exit(main())
