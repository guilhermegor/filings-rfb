"""Structural gate: an arithmetic read-modify-write race on an ORM-loaded row (blueprintx#385).

THE SHAPE THIS GATE CATCHES — row 1 of #385's decidability table, and *only* row 1::

    record = session.get(Product, product_id)     # or query(Product).filter(...).first()/.one()
    record.stock = record.stock - quantity         # or record.stock -= quantity
    session.flush()

Under ``READ COMMITTED`` (the default in both PostgreSQL and MySQL) two concurrent callers can
both read ``stock == 1``, both decide there is stock, and both write. Nothing crashes, nothing
logs, both transactions commit — the number is silently wrong. The fix is a property of the
CODE SHAPE (push the arithmetic into the ``UPDATE``, or lock/version the read), not of the
transaction, which is exactly why a reviewer scanning for ``BEGIN``/``COMMIT`` never sees it.

WHY ONLY ROW 1. #385 is explicit that row 2 — "read an entity, assign an attribute, flush, with
no lock" — is NOT gated: every ORM ``update()`` in existence reads then writes, so firing on
that shape is 100% noise. This gate fires only when the assigned value is an ARITHMETIC
expression over the SAME attribute read moments earlier — the one form a reviewer cannot catch
by eye, because ``x.qty = x.qty - n`` reads as obviously correct.

WHAT IS FLAGGED, and what silences it, within the SAME function:

1. a variable bound to a single-row ORM read — ``session.get(Model, id)`` or a
   ``<query>.first()``/``<query>.one()`` chain that also calls ``.query(Model)`` (the ``.query``
   call is what pins a model onto the chain and rules out an unrelated ``.first()`` on a plain
   list — the false-positive risk #385 calls out explicitly for the wider "any read then write"
   shape);
2. that variable's attribute reassigned (``=`` or an augmented op) FROM AN EXPRESSION THAT
   REFERENCES ITS OWN PRIOR VALUE — ``x.attr = x.attr - n`` or ``x.attr -= n``;
3. with no ``with_for_update()`` on the read (a chained call, or the ``with_for_update=`` kwarg
   on ``session.get``) and no ``version_id_col`` on the model's ``__mapper_args__`` — checked
   against a same-file class definition; a model defined elsewhere cannot be resolved by this
   structural gate and relies on the lock check or the escape hatch below.

⚠️ MEASURED ZERO INSTANCES IN templates/ TODAY (#385) — and that does not disqualify the gate.
``templates/`` ships example code a generated project copies and extends; the subject is what a
downstream project WILL write against a stock schema, not what is present here now, the same
anticipatory-allowlist reasoning ``codespell:ignore`` already relies on with zero occurrences.

ESCAPE HATCH, required reason, same shape as ``dtype-ok:``/``complexity-ok:`` elsewhere in this
file family — a single-writer migration script legitimately does read-modify-write::

    record.stock = record.stock - n  # rmw-ok: single-writer offline migration, no contention

A bare marker with no reason does not satisfy the gate.

NOT GATED HERE, by design (#385): a missing ``CHECK (… >= 0)`` (deciding which columns are
quantities is a naming heuristic — ``check_comment_language.py``'s first draft was 19 findings,
18 false, from exactly this kind of guess) and whether a given read-modify-write is actually
contended (a batch job and a checkout endpoint look identical in the AST). Both are docs, not a
gate — see the DB-layer ``CLAUDE.md`` this issue's docs half (PR #387) added.

WIRING (blueprintx#385): pre-commit only, in this file's own ``.pre-commit-config.yaml`` — NOT
CI. The CI workflow (``.github/workflows/scaffold_checks.yml``) is held by an unrelated open PR
(#286) at the time this gate shipped; adding a job there is left for that PR's owner rather than
widening this change's surface. Not run over BlueprintX's own tree either: this repo has no
``src/`` (it is a Make + bash scaffolding tool, not a Python application), so a root invocation
would discover zero files and, by this gate's own zero-discovery guard, fail every commit for a
reason no one could fix by editing code here — the same reasoning ``lint_deps.sh`` documents for
staying scoped to a generated project.
"""

import ast
import pathlib
import re
import sys


_READ_TERMINALS = {"first", "one"}

_LOCK_METHOD = "with_for_update"
_LOCK_KWARG = "with_for_update"

_RE_ALLOW_MARKER = re.compile(r"rmw-ok:\s*(\S.*)")

_ARITH_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)


def _walk_own_statements(node: ast.AST) -> list:
    """Collect every descendant of ``node`` WITHOUT crossing into a nested function.

    A nested function is its own scope for this gate's "same function" rule, and it gets its
    own top-level visit from :func:`check_file`'s outer walk — descending into it here would
    double-report every finding inside it.

    Parameters
    ----------
    node : ast.AST
        A function (or async function) node.

    Returns
    -------
    list of ast.AST
        Every node in ``node``'s own body, one function-scope deep.
    """
    list_out: list = []
    list_stack = list(ast.iter_child_nodes(node))
    while list_stack:
        cls_child = list_stack.pop()
        list_out.append(cls_child)
        if isinstance(cls_child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            continue
        list_stack.extend(ast.iter_child_nodes(cls_child))
    return list_out


def _session_get_read(call: ast.Call) -> tuple | None:
    """Classify a ``session.get(Model, id, ...)`` call as a single-row ORM read.

    Parameters
    ----------
    call : ast.Call
        A call expression.

    Returns
    -------
    tuple of (str, bool) or None
        ``(model_name, has_lock)`` when this is a ``*.get(Model, ...)`` call reached through
        something named ``session``; ``None`` otherwise.
    """
    if not isinstance(call.func, ast.Attribute) or call.func.attr != "get":
        return None
    if "session" not in ast.unparse(call.func.value) or not call.args:
        return None
    str_model = ast.unparse(call.args[0])
    bool_lock = _keyword_locks(call.keywords)
    return str_model, bool_lock


def _keyword_locks(list_keywords: list) -> bool:
    """Return whether a lock keyword is present AND asks for a lock.

    Parameters
    ----------
    list_keywords : list of ast.keyword
        The call's keyword arguments.

    Returns
    -------
    bool
        ``True`` only when the lock keyword is given a truthy literal.

    Notes
    -----
    ⚠️ Presence is not protection. ``with_for_update=False`` and ``with_for_update=None`` read
    as "a lock keyword is here" to a presence check while meaning **no lock** — and a gate that
    suppresses on them reports a protected read where none exists, which is the direction that
    hides the very race this file exists to find.

    A non-literal value (a variable, a call) is treated as UNLOCKED: whether it is truthy is a
    runtime question, and a static check that guesses "probably locked" trades a false positive
    for a false negative. The escape hatch is for the cases where the author knows better.
    """
    for cls_kw in list_keywords:
        if cls_kw.arg != _LOCK_KWARG:
            continue
        if isinstance(cls_kw.value, ast.Constant):
            return bool(cls_kw.value.value)
        return False
    return False


def _query_chain_read(call: ast.Call) -> tuple | None:
    """Classify a ``session.query(Model)....first()``/``.one()`` chain as an ORM read.

    Parameters
    ----------
    call : ast.Call
        The outermost call — ``<chain>.first()`` or ``<chain>.one()``.

    Returns
    -------
    tuple of (str, bool) or None
        ``(model_name, has_lock)`` when the chain includes a ``.query(Model)`` call (the one
        signal that pins a model onto an otherwise generic ``.first()``/``.one()``);
        ``None`` when it does not.
    """
    if not isinstance(call.func, ast.Attribute) or call.func.attr not in _READ_TERMINALS:
        return None
    str_model, bool_lock, cls_node = None, False, call.func.value
    while isinstance(cls_node, ast.Call) and isinstance(cls_node.func, ast.Attribute):
        if cls_node.func.attr == "query" and cls_node.args:
            str_model = ast.unparse(cls_node.args[0])
        elif cls_node.func.attr == _LOCK_METHOD:
            bool_lock = True
        cls_node = cls_node.func.value
    return (str_model, bool_lock) if str_model else None


def _collect_read_entities(func: ast.AST) -> dict:
    """Map each simple variable bound to a single-row ORM read to ``(model, has_lock)``.

    Parameters
    ----------
    func : ast.AST
        A function (or async function) node.

    Returns
    -------
    dict of str to tuple
        Variable name -> ``(model_name, has_lock)``, scoped to this function only.
    """
    dict_entities: dict = {}
    for cls_node in _walk_own_statements(func):
        if not isinstance(cls_node, ast.Assign) or len(cls_node.targets) != 1:
            continue
        if not isinstance(cls_node.targets[0], ast.Name):
            continue
        if not isinstance(cls_node.value, ast.Call):
            continue
        cls_read = _session_get_read(cls_node.value) or _query_chain_read(cls_node.value)
        if not cls_read:
            continue
        str_name = cls_node.targets[0].id
        cls_prev = dict_entities.get(str_name)
        if cls_prev is None or (cls_prev[1] and not cls_read[1]):
            dict_entities[str_name] = cls_read
    return dict_entities


def _references_attr(expr: ast.AST, str_var: str, str_attr: str) -> bool:
    """Return whether ``expr`` reads ``var.attr`` anywhere within it.

    Parameters
    ----------
    expr : ast.AST
        The expression to search.
    str_var : str
        The entity variable name.
    str_attr : str
        The attribute name.

    Returns
    -------
    bool
        ``True`` when ``expr`` contains ``var.attr``.
    """
    return any(
        isinstance(cls_node, ast.Attribute)
        and cls_node.attr == str_attr
        and isinstance(cls_node.value, ast.Name)
        and cls_node.value.id == str_var
        for cls_node in ast.walk(expr)
    )


def _assign_target_and_check(node: ast.AST) -> tuple:
    """Normalise an ``Assign``/``AugAssign`` node to ``(target, self-reference-expr)``.

    Parameters
    ----------
    node : ast.AST
        A statement node.

    Returns
    -------
    tuple of (ast.AST or None, ast.AST or None)
        The attribute target and the expression to test for a self-reference, or
        ``(None, None)`` when ``node`` is not an arithmetic reassignment.
    """
    if isinstance(node, ast.AugAssign) and isinstance(node.op, _ARITH_OPS):
        return node.target, node.target
    bool_is_arith_assign = (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.value, ast.BinOp)
        and isinstance(node.value.op, _ARITH_OPS)
    )
    if bool_is_arith_assign:
        return node.targets[0], node.value
    return None, None


def _model_has_version_id_col(tree: ast.Module, str_source: str, str_model: str) -> bool:
    """Return whether a same-file class named ``str_model`` declares ``version_id_col``.

    Parameters
    ----------
    tree : ast.Module
        The parsed module.
    str_source : str
        Unused; kept so the call site stays stable. See Notes.
    str_model : str
        The model name to look up.

    Returns
    -------
    bool
        ``True`` when the class assigns ``__mapper_args__`` with a ``version_id_col`` key.
        A model defined in another file cannot be resolved by this structural gate and reads
        as unprotected — use ``with_for_update()`` or the escape hatch for that case.

    Notes
    -----
    ⚠️ Parsed, never text-matched. A substring test over the class body's SOURCE is satisfied
    by a docstring, a comment or a string literal that merely mentions the option — measured:
    ``str_note = "todo: consider version_id_col here"`` suppressed the finding entirely. That
    is the same defeat shape as counting ``pytest.raises`` by regex (blueprintx#334): a gate
    turned off by writing its own keyword in prose.
    """
    del str_source
    for cls_node in ast.walk(tree):
        if isinstance(cls_node, ast.ClassDef) and cls_node.name == str_model:
            return _class_declares_version_id_col(cls_node)
    return False


def _class_declares_version_id_col(cls_class: ast.ClassDef) -> bool:
    """Return whether a class body assigns ``__mapper_args__`` carrying ``version_id_col``.

    Parameters
    ----------
    cls_class : ast.ClassDef
        The model class to inspect.

    Returns
    -------
    bool
        ``True`` when a ``__mapper_args__`` dict declares the key.
    """
    for cls_stmt in cls_class.body:
        if not isinstance(cls_stmt, ast.Assign) or not isinstance(cls_stmt.value, ast.Dict):
            continue
        if not any(
            isinstance(cls_target, ast.Name) and cls_target.id == "__mapper_args__"
            for cls_target in cls_stmt.targets
        ):
            continue
        if any(
            isinstance(cls_key, ast.Constant) and cls_key.value == "version_id_col"
            for cls_key in cls_stmt.value.keys
        ):
            return True
    return False


def _message(str_var: str, str_attr: str, str_model: str) -> str:
    """Build the finding message: names the race and its one-line SQL fix.

    Parameters
    ----------
    str_var : str
        The entity variable name.
    str_attr : str
        The attribute name.
    str_model : str
        The model name.

    Returns
    -------
    str
        The finding message.
    """
    return (
        f"read-modify-write race: `{str_var}.{str_attr}` is reassigned from its own value, "  # noqa: S608
        f"read earlier in this function, with no with_for_update() and no version_id_col on "
        f"{str_model}. Two concurrent writers can read the same value and silently lose an "
        f"update. Fix in SQL: `UPDATE <table> SET {str_attr} = {str_attr} - <n> WHERE id = ? "
        f"AND {str_attr} >= <n>`, or add with_for_update()/version_id_col. Escape hatch: "
        f"# rmw-ok: <reason>"
    )


def _race_violations(func: ast.AST, tree: ast.Module, str_source: str) -> list:
    """Find arithmetic read-modify-write races inside one function's own body.

    Parameters
    ----------
    func : ast.AST
        A function (or async function) node.
    tree : ast.Module
        The parsed module (for cross-statement model lookup).
    str_source : str
        The module's source text.

    Returns
    -------
    list of tuple
        ``(line_number, message)`` for every unprotected race found.
    """
    dict_entities = _collect_read_entities(func)
    list_findings: list = []
    for cls_node in _walk_own_statements(func):
        cls_target, cls_check = _assign_target_and_check(cls_node)
        if cls_target is None or not isinstance(cls_target, ast.Attribute):
            continue
        if not isinstance(cls_target.value, ast.Name) or cls_target.value.id not in dict_entities:
            continue
        str_var, str_attr = cls_target.value.id, cls_target.attr
        if not _references_attr(cls_check, str_var, str_attr):
            continue
        str_model, bool_lock = dict_entities[str_var]
        if bool_lock or _model_has_version_id_col(tree, str_source, str_model):
            continue
        list_findings.append((cls_node.lineno, _message(str_var, str_attr, str_model)))
    return list_findings


def check_file(str_path: str) -> int:
    """Report every read-modify-write race in one file.

    Parameters
    ----------
    str_path : str
        Path to the Python source file to scan.

    Returns
    -------
    int
        The number of violations found (0 when clean). An unparsable file is one violation,
        never a silent pass — "cannot be checked" and "is clean" must not read the same.
    """
    str_source = pathlib.Path(str_path).read_text(encoding="utf-8")
    try:
        tree = ast.parse(str_source, filename=str_path)
    except SyntaxError as cls_exc:
        print(f"❌ {str_path}: could not parse ({cls_exc}) — treated as a finding, not a pass")
        return 1

    list_lines = str_source.splitlines()
    int_errors = 0
    for cls_func in ast.walk(tree):
        if not isinstance(cls_func, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for int_line, str_msg in _race_violations(cls_func, tree, str_source):
            str_src_line = list_lines[int_line - 1] if int_line - 1 < len(list_lines) else ""
            if _RE_ALLOW_MARKER.search(str_src_line):
                continue
            print(f"❌ {str_path}:{int_line}: {str_src_line.strip()}\n   {str_msg}")
            int_errors += 1
    return int_errors


def _source_files() -> list:
    """Collect every Python file under ``src/``.

    Returns
    -------
    list of pathlib.Path
        Python source files to check.
    """
    return sorted(pathlib.Path("src").rglob("*.py"))


if __name__ == "__main__":
    for cls_stream in (sys.stdout, sys.stderr):
        if hasattr(cls_stream, "reconfigure"):
            cls_stream.reconfigure(encoding="utf-8", errors="replace")

    list_files = _source_files()
    if not list_files:
        print(
            "❌ read-modify-write race gate: 0 files discovered under src/ — a gate that "
            "checked nothing is not a passing gate; check the discovery glob"
        )
        sys.exit(1)

    int_total = sum(check_file(str(cls_path)) for cls_path in list_files)
    if int_total == 0:
        print(f"✅ read-modify-write race gate: {len(list_files)} file(s) checked, 0 findings")
    sys.exit(1 if int_total > 0 else 0)
