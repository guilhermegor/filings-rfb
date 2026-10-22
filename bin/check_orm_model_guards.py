"""Structural gate: ORM model-DEFINITION guards for the SILENT WRONG ANSWER (blueprintx#361).

#355 (``check_sql_guards.py``) guards SQL as it reaches the database. This gate guards SQL as
it is DECLARED in the ORM: a wrong model declaration produces a valid schema and a valid query
that returns the wrong rows — no exception, no crash, no red test.

**Scope of this gate — 3 of the 5 candidates in #361, chosen because they need no extra
infrastructure to decide.** The other two are deferred, not silently dropped:

- ⚠️ **Dialect-specific regex in a CheckConstraint (#361 candidate 2)** needs a declared
  target dialect to compare against, and these ORM tiers support SIX backends at RUNTIME via
  ``DB_BACKEND`` — there is no single dialect to check against today. Flagged as a follow-up
  once a tier can declare one (see #381, the Alembic migration scaffold).
- ⚠️ **Classic ``Column`` vs modern ``mapped_column`` (#361 candidate 5)** is the issue's own
  lowest-priority item, explicitly "drop if noisy" — left for a follow-up measurement.

**Python/SQLAlchemy-only, and deliberately so** — #361 states each TS-side equivalent
explicitly: bitwise-precedence has no TS analogue (Prisma/Drizzle filters are object literals,
and TS ``&``/``|`` on those is a type error, not a silent coercion); Prisma owns schema
generation, so there is no user-authored ``Base``/``create_all`` to get wrong; and a Prisma
schema has no MRO to concatenate a duplicate constraint name across. Each is a real "not
applicable", stated once here rather than a runtime skip on every scaffolded TS tier (this
gate only ever runs against ``src/**/*.py``, so it never executes on a TS tier at all).

Three guards ship:

1. **Bitwise ``&``/``|``/``~`` inside ``.where()``/``.filter()``.** Python binds ``&``/``|``
   TIGHTER than ``==``, so ``User.age == 18 & User.is_active == True`` reparses as a chained
   comparison over ``(18 & User.is_active)`` — a valid query, returning wrong rows, no error
   anywhere. Flagged unconditionally inside these two calls (even when correctly parenthesised
   today): the house form is ``and_()``/``or_()``/``not_()``, which cannot be mis-parenthesised
   by a future edit.
2. **Two ``Base``/early ``create_all``.** A second ``declarative_base()``/``DeclarativeBase``
   subclass in the tree, or a ``metadata.create_all(...)`` reachable without entering a
   function, leaves ``Base.metadata`` empty or partial at the moment it runs — and
   ``create_all`` then SUCCEEDS having created nothing (or only part) of the schema, with no
   exception raised.
3. **Duplicate constraint ``name=`` in the EFFECTIVE ``__table_args__``, and a
   ``__table_args__`` shadowed by one.** SQLAlchemy does **not**
   concatenate ``__table_args__`` across bases. It is an ordinary class attribute, so
   attribute lookup takes the first declaration in the MRO and every later one is
   discarded whole — mixins do not compose. This check therefore does two things: it
   looks for duplicate ``name=`` values *within the one declaration that is live*, and it
   reports a base whose ``__table_args__`` is shadowed, because those constraints are
   silently absent from the table. Resolved only across bases defined in the SAME file — a
   mixin imported from elsewhere is out of scope for this pass (see the module's own
   ``_base_class_names``).

**Escape hatch**, same shape as ``sql-guard-ok:`` in ``check_sql_guards.py``::

    class Base(DeclarativeBase): ...  # orm-guard-ok: separate bind, reviewed in PR #123

An empty or whitespace-only reason after the marker is rejected — the marker's presence is
not a decision, the written reason is.
"""

from __future__ import annotations

import ast
import pathlib
import sys


_ALLOW_MARKER = "orm-guard-ok:"
_SRC_ROOT = "src"

_FILTER_CALL_NAMES = frozenset({"where", "filter"})
_BASE_CALL_NAMES = frozenset({"declarative_base", "generate_base"})
_BASE_CLASS_NAMES = frozenset({"DeclarativeBase", "DeclarativeBaseNoMeta"})


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
        empty/whitespace-only.
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


def _imports_sqlalchemy(cls_tree: ast.Module) -> bool:
    """Return whether the module imports ``sqlalchemy`` at all.

    Parameters
    ----------
    cls_tree : ast.Module
        The parsed module.

    Returns
    -------
    bool
        ``True`` when any ``sqlalchemy``/``sqlalchemy.*`` import is present.
    """
    for cls_node in ast.walk(cls_tree):
        if isinstance(cls_node, ast.Import) and any(
            a.name == "sqlalchemy" or a.name.startswith("sqlalchemy.") for a in cls_node.names
        ):
            return True
        if (
            isinstance(cls_node, ast.ImportFrom)
            and cls_node.module
            and (cls_node.module == "sqlalchemy" or cls_node.module.startswith("sqlalchemy."))
        ):
            return True
    return False


def _receiver_root_name(cls_expr: ast.expr) -> str:
    """Return the base identifier of a call chain's receiver (``df_x.loc[m].where`` -> ``df_x``).

    Parameters
    ----------
    cls_expr : ast.expr
        The ``.value`` of the ``.where``/``.filter`` attribute.

    Returns
    -------
    str
        The leftmost ``Name``, or ``""`` when the chain does not start at one.
    """
    while isinstance(cls_expr, ast.Attribute | ast.Subscript | ast.Call):
        cls_expr = cls_expr.func if isinstance(cls_expr, ast.Call) else cls_expr.value
    return cls_expr.id if isinstance(cls_expr, ast.Name) else ""


def _is_pandas_receiver(cls_attr: ast.Attribute) -> bool:
    """Return whether a ``.where``/``.filter`` call is on a DataFrame/Series by naming convention.

    pandas boolean masks use ``&``/``|`` by design, so flagging them is a false positive. The
    house type-prefix convention (``df_``/``series_``) is the only receiver evidence this gate
    has without type inference, so it is what separates the two APIs.

    Parameters
    ----------
    cls_attr : ast.Attribute
        The ``.where``/``.filter`` attribute access of the call.

    Returns
    -------
    bool
        True when the receiver chain starts at a ``df``/``df_*``/``series_*`` name.
    """
    str_root = _receiver_root_name(cls_attr.value)
    return str_root == "df" or str_root.startswith(("df_", "series_"))


def _find_bitwise_nodes(cls_node: ast.AST) -> list[ast.AST]:
    """Find the outermost bitwise-precedence-hazard node(s) inside an expression tree.

    Stops descending once a hazard is found, so ``(a & b) & c`` reports ONE finding (the
    outer ``BinOp``), not two nested ones for the same landmine.

    Parameters
    ----------
    cls_node : ast.AST
        The expression subtree to search.

    Returns
    -------
    list of ast.AST
        Zero or more ``BinOp``/``UnaryOp`` nodes using ``&``/``|``/``~``.
    """
    if isinstance(cls_node, ast.BinOp) and isinstance(cls_node.op, ast.BitAnd | ast.BitOr):
        return [cls_node]
    if isinstance(cls_node, ast.UnaryOp) and isinstance(cls_node.op, ast.Invert):
        return [cls_node]
    list_found: list[ast.AST] = []
    for cls_child in ast.iter_child_nodes(cls_node):
        list_found += _find_bitwise_nodes(cls_child)
    return list_found


def _bitwise_filter_message(path_file: pathlib.Path, int_line: int) -> str:
    """Return the bitwise-precedence finding, naming the failure mode and the fix.

    Parameters
    ----------
    path_file : pathlib.Path
        The offending file.
    int_line : int
        The line of the bitwise operator.

    Returns
    -------
    str
        A human-readable finding.
    """
    return (
        f"{path_file}:{int_line}: bitwise operator (&/|/~) inside .where()/.filter() — Python "
        f"binds &/|/~ TIGHTER than ==/</>, so `a == 1 & b == True` silently reparses as a "
        f"chained comparison over `(1 & b)` — a valid query returning wrong rows, no error "
        f"raised. Use and_()/or_()/not_() instead: they cannot be mis-parenthesised by a later "
        f"edit. If this is a deliberately parenthesised column expression, annotate the line: "
        f"# {_ALLOW_MARKER} <reason>"
    )


def _bitwise_filter_problems(
    cls_tree: ast.Module, path_file: pathlib.Path, list_lines: list[str]
) -> list[str]:
    """Report every &/|/~ found inside a ``.where()``/``.filter()`` call's arguments.

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
    if not _imports_sqlalchemy(cls_tree):
        return []
    list_problems: list[str] = []
    for cls_node in ast.walk(cls_tree):
        if not (
            isinstance(cls_node, ast.Call)
            and isinstance(cls_node.func, ast.Attribute)
            and cls_node.func.attr in _FILTER_CALL_NAMES
        ):
            continue
        if _is_pandas_receiver(cls_node.func):
            continue
        for cls_arg in cls_node.args:
            for cls_hazard in _find_bitwise_nodes(cls_arg):
                if not _line_allowed(list_lines, cls_hazard.lineno):
                    list_problems.append(_bitwise_filter_message(path_file, cls_hazard.lineno))
    return list_problems


def _base_declarations_in_file(
    cls_tree: ast.Module, path_file: pathlib.Path, list_lines: list[str]
) -> list[tuple[pathlib.Path, int, str]]:
    """Collect every Base declaration (``declarative_base()``, ``generate_base()``, subclasses).

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
    list of (pathlib.Path, int, str)
        One entry per un-hatched declaration: file, line, human-readable kind.
    """
    list_found: list[tuple[pathlib.Path, int, str]] = []
    for cls_node in ast.walk(cls_tree):
        str_kind: str | None = None
        int_line = 0
        if isinstance(cls_node, ast.Call):
            str_call_name = (
                cls_node.func.id
                if isinstance(cls_node.func, ast.Name)
                else cls_node.func.attr
                if isinstance(cls_node.func, ast.Attribute)
                else None
            )
            if str_call_name in _BASE_CALL_NAMES:
                str_kind, int_line = f"{str_call_name}() call", cls_node.lineno
        elif isinstance(cls_node, ast.ClassDef) and any(
            (isinstance(b, ast.Name) and b.id in _BASE_CLASS_NAMES)
            or (isinstance(b, ast.Attribute) and b.attr in _BASE_CLASS_NAMES)
            for b in cls_node.bases
        ):
            str_kind, int_line = f"class {cls_node.name}(DeclarativeBase)", cls_node.lineno
        if str_kind is not None and not _line_allowed(list_lines, int_line):
            list_found.append((path_file, int_line, str_kind))
    return list_found


def _duplicate_base_message(
    cls_entry: tuple[pathlib.Path, int, str], list_others: list[tuple[pathlib.Path, int, str]]
) -> str:
    """Return the "more than one Base" finding for one declaration site.

    Parameters
    ----------
    cls_entry : tuple of (pathlib.Path, int, str)
        This declaration's (file, line, kind).
    list_others : list of (pathlib.Path, int, str)
        Every OTHER declaration found across the tree.

    Returns
    -------
    str
        A human-readable finding naming every sibling declaration.
    """
    path_file, int_line, str_kind = cls_entry
    str_others = "; ".join(f"{p}:{ln} ({k})" for p, ln, k in list_others)
    return (
        f"{path_file}:{int_line}: {str_kind} — {len(list_others)} other Base declaration(s) "
        f"also exist in this tree ({str_others}). create_all() only creates tables registered "
        f"on the ONE Base instance it is called against; a model built on a different Base is "
        f"silently never created — no exception, no table, no signal. Import a single shared "
        f"Base everywhere, or if genuinely intentional (e.g. a separate bind), annotate the "
        f"line: # {_ALLOW_MARKER} <reason>"
    )


def _is_create_all_call(cls_call: ast.Call) -> bool:
    """Return whether this call matches the ``X.metadata.create_all(...)`` shape.

    Parameters
    ----------
    cls_call : ast.Call
        The call to classify.

    Returns
    -------
    bool
        ``True`` only for a two-level ``<obj>.metadata.create_all(...)`` chain.
    """
    if not (isinstance(cls_call.func, ast.Attribute) and cls_call.func.attr == "create_all"):
        return False
    cls_receiver = cls_call.func.value
    return isinstance(cls_receiver, ast.Attribute) and cls_receiver.attr == "metadata"


def _create_all_message(path_file: pathlib.Path, int_line: int) -> str:
    """Return the module-scope ``create_all`` finding, naming the failure mode and the fix.

    Parameters
    ----------
    path_file : pathlib.Path
        The offending file.
    int_line : int
        The line of the call.

    Returns
    -------
    str
        A human-readable finding.
    """
    return (
        f"{path_file}:{int_line}: metadata.create_all(...) at MODULE scope runs the instant "
        f"this module is imported — possibly before every model that should register on "
        f"Base.metadata has itself been imported. It then creates whatever IS registered at "
        f"that point and reports success, silently omitting the rest. Move the call inside a "
        f"function invoked after all models are imported, or if deliberate: "
        f"# {_ALLOW_MARKER} <reason>"
    )


def _is_main_guard(cls_node: ast.AST) -> bool:
    """Return whether a node is ``if __name__ == "__main__":`` — code that never runs on import.

    Parameters
    ----------
    cls_node : ast.AST
        The node to classify.

    Returns
    -------
    bool
        ``True`` only for an ``If`` comparing ``__name__`` to the string ``"__main__"``.
    """
    if not (isinstance(cls_node, ast.If) and isinstance(cls_node.test, ast.Compare)):
        return False
    cls_test = cls_node.test
    return (
        isinstance(cls_test.left, ast.Name)
        and cls_test.left.id == "__name__"
        and any(
            isinstance(c, ast.Constant) and c.value == "__main__" for c in cls_test.comparators
        )
    )


def _module_scope_create_all_problems(
    cls_tree: ast.Module, path_file: pathlib.Path, list_lines: list[str]
) -> list[str]:
    """Report every ``create_all(...)`` call reachable without entering a function scope.

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
    list_problems: list[str] = []

    def _walk(cls_node: ast.AST, bool_in_function: bool) -> None:
        for cls_child in ast.iter_child_nodes(cls_node):
            if (
                isinstance(cls_child, ast.Call)
                and not bool_in_function
                and _is_create_all_call(cls_child)
                and not _line_allowed(list_lines, cls_child.lineno)
            ):
                list_problems.append(_create_all_message(path_file, cls_child.lineno))
            bool_child_in_function = (
                bool_in_function
                or isinstance(cls_child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda)
                or _is_main_guard(cls_child)
            )
            _walk(cls_child, bool_child_in_function)

    _walk(cls_tree, False)
    return list_problems


def _declared_attr_table_args(cls_node: ast.ClassDef) -> ast.FunctionDef | None:
    """Return a ``@declared_attr def __table_args__`` method, SQLAlchemy's documented mixin form.

    Parameters
    ----------
    cls_node : ast.ClassDef
        The class to inspect.

    Returns
    -------
    ast.FunctionDef or None
        The method, or ``None`` when the class defines no such method.
    """
    for cls_stmt in cls_node.body:
        if isinstance(cls_stmt, ast.FunctionDef) and cls_stmt.name == "__table_args__":
            return cls_stmt
    return None


def _table_args_value(cls_node: ast.ClassDef) -> ast.AST | None:
    """Return this class's own ``__table_args__`` declaration node, or ``None``.

    Parameters
    ----------
    cls_node : ast.ClassDef
        The class to inspect.

    Returns
    -------
    ast.AST or None
        The assigned expression, or the ``@declared_attr`` method; ``None`` when absent.
    """
    return _declared_attr_table_args(cls_node) or _assigned_table_args_value(cls_node)


def _assigned_table_args_value(cls_node: ast.ClassDef) -> ast.expr | None:
    """Return this class's own ``__table_args__`` RHS expression, or ``None``.

    Parameters
    ----------
    cls_node : ast.ClassDef
        The class to inspect.

    Returns
    -------
    ast.expr or None
        The assigned expression, or ``None`` when the class declares no ``__table_args__``.
    """
    for cls_stmt in cls_node.body:
        cls_target: ast.expr | None = None
        if isinstance(cls_stmt, ast.Assign) and len(cls_stmt.targets) == 1:
            cls_target = cls_stmt.targets[0]
        elif isinstance(cls_stmt, ast.AnnAssign):
            cls_target = cls_stmt.target
        if isinstance(cls_target, ast.Name) and cls_target.id == "__table_args__":
            return getattr(cls_stmt, "value", None)
    return None


def _is_name_kw(cls_kw: ast.keyword) -> bool:
    """Return whether a keyword argument is ``name=<string literal>``.

    Parameters
    ----------
    cls_kw : ast.keyword
        The keyword argument to inspect.

    Returns
    -------
    bool
        ``True`` only for ``name=`` bound to a literal string.
    """
    return (
        cls_kw.arg == "name"
        and isinstance(cls_kw.value, ast.Constant)
        and isinstance(cls_kw.value.value, str)
    )


def _call_constraint_names(cls_call: ast.Call) -> list[str]:
    """Return the constraint/index names one call declares: ``name=`` and ``Index``'s first arg.

    Parameters
    ----------
    cls_call : ast.Call
        A call found inside a ``__table_args__`` expression.

    Returns
    -------
    list of str
        Zero or more literal names.
    """
    list_names = [
        str(cls_kw.value.value)
        for cls_kw in cls_call.keywords
        if _is_name_kw(cls_kw) and isinstance(cls_kw.value, ast.Constant)
    ]
    str_func = cls_call.func.id if isinstance(cls_call.func, ast.Name) else ""
    if str_func == "Index" and cls_call.args and isinstance(cls_call.args[0], ast.Constant):
        list_names.append(str(cls_call.args[0].value))
    return list_names


def _constraint_names_in_expr(cls_value: ast.AST | None) -> list[tuple[str, int]]:
    """Return every ``name="..."`` constraint literal inside a ``__table_args__`` expression.

    Parameters
    ----------
    cls_value : ast.AST or None
        The ``__table_args__`` declaration node, or ``None`` (no such declaration).

    Returns
    -------
    list of (str, int)
        ``(constraint_name, lineno)`` pairs; empty when ``cls_value`` is ``None`` or holds none.
    """
    if cls_value is None:
        return []
    list_names: list[tuple[str, int]] = []
    for cls_inner in ast.walk(cls_value):
        if not isinstance(cls_inner, ast.Call):
            continue
        list_names += [(str_n, cls_inner.lineno) for str_n in _call_constraint_names(cls_inner)]
    return list_names


def _table_args_names(cls_node: ast.ClassDef) -> list[tuple[str, int]]:
    """Return every ``name="..."`` constraint literal in this class's OWN ``__table_args__``.

    Parameters
    ----------
    cls_node : ast.ClassDef
        The class to inspect.

    Returns
    -------
    list of (str, int)
        ``(constraint_name, lineno)`` pairs; empty when the class has no ``__table_args__``.
    """
    return _constraint_names_in_expr(_table_args_value(cls_node))


def _declares_tablename(cls_node: ast.ClassDef) -> bool:
    """Return whether this class assigns ``__tablename__`` — i.e. it maps its own table.

    Parameters
    ----------
    cls_node : ast.ClassDef
        The class to inspect.

    Returns
    -------
    bool
        True when the class body assigns ``__tablename__``.
    """
    return any(
        isinstance(cls_stmt, ast.Assign | ast.AnnAssign)
        and any(
            isinstance(cls_t, ast.Name) and cls_t.id == "__tablename__"
            for cls_t in (
                cls_stmt.targets if isinstance(cls_stmt, ast.Assign) else [cls_stmt.target]
            )
        )
        for cls_stmt in cls_node.body
    )


def _declares_table_args(cls_node: ast.ClassDef) -> bool:
    """Return whether this class assigns ``__table_args__`` at all.

    Separate from :func:`_table_args_names` on purpose: a class declaring
    ``__table_args__ = (UniqueConstraint(...),)`` with no ``name=`` yields an empty name list,
    which is NOT the same as declaring nothing — it still shadows every base's declaration.

    Parameters
    ----------
    cls_node : ast.ClassDef
        The class to inspect.

    Returns
    -------
    bool
        True when the class body assigns ``__table_args__``.
    """
    return _table_args_value(cls_node) is not None


def _base_class_names(cls_node: ast.ClassDef) -> list[str]:
    """Return this class's base names that are simple identifiers (in-file resolvable).

    Parameters
    ----------
    cls_node : ast.ClassDef
        The class to inspect.

    Returns
    -------
    list of str
        Base class names reachable by a plain ``ast.Name`` (e.g. ``class C(MixinA, MixinB)``);
        a dotted base (``sqlalchemy.orm.DeclarativeBase``) is not resolvable in-file and is
        skipped — it carries no ``__table_args__`` this gate can read anyway.
    """
    return [cls_base.id for cls_base in cls_node.bases if isinstance(cls_base, ast.Name)]


def _linearised_bases(
    str_name: str, dict_classes: dict[str, ast.ClassDef], set_visited: set[str]
) -> list[str]:
    """Return ``str_name`` and its in-file ancestors, depth-first and left to right.

    Only the fallback of :func:`_in_file_mro`, for a hierarchy Python itself cannot linearise.

    Parameters
    ----------
    str_name : str
        The class to start from.
    dict_classes : dict of str to ast.ClassDef
        Every class defined in this file, by name.
    set_visited : set of str
        Class names already walked, to guard against a base-name cycle.

    Returns
    -------
    list of str
        Class names in attribute-lookup order, starting with ``str_name`` itself.
    """
    if str_name in set_visited or str_name not in dict_classes:
        return []
    set_visited.add(str_name)
    list_order = [str_name]
    for str_base in _base_class_names(dict_classes[str_name]):
        list_order += _linearised_bases(str_base, dict_classes, set_visited)
    return list_order


def _in_file_mro(str_name: str, dict_classes: dict[str, ast.ClassDef]) -> list[str]:
    """Return ``str_name`` and its in-file ancestors in Python's own C3 attribute-lookup order.

    Builds a throwaway ``type`` per in-file class, bases first, and reads ``__mro__`` — so the
    order is the interpreter's, diamonds included, instead of a hand-written approximation.
    Bases defined elsewhere carry no ``__table_args__`` this gate can read and are skipped.

    Parameters
    ----------
    str_name : str
        The class to start from.
    dict_classes : dict of str to ast.ClassDef
        Every class defined in this file, by name.

    Returns
    -------
    list of str
        Class names in lookup order, starting with ``str_name``; the depth-first walk when
        Python rejects the hierarchy (a cycle or an inconsistent order).
    """
    dict_built: dict[str, type] = {}

    def _build(str_cls: str) -> type:
        if str_cls not in dict_built:
            tuple_bases = tuple(
                _build(str_base)
                for str_base in _base_class_names(dict_classes[str_cls])
                if str_base in dict_classes
            )
            dict_built[str_cls] = type(str_cls, tuple_bases, {})
        return dict_built[str_cls]

    try:
        list_mro = _build(str_name).__mro__
    except (TypeError, RecursionError):
        return _linearised_bases(str_name, dict_classes, set())
    dict_name_of = {id(cls_type): str_cls for str_cls, cls_type in dict_built.items()}
    return [dict_name_of[id(cls_type)] for cls_type in list_mro if id(cls_type) in dict_name_of]


def _consumed_bases(cls_declaration: ast.AST | None) -> set[str]:
    """Return the bases a declaration composes explicitly, via ``<Base>.__table_args__``.

    Parameters
    ----------
    cls_declaration : ast.AST or None
        A class's own ``__table_args__`` declaration node.

    Returns
    -------
    set of str
        Names ``X`` for every ``X.__table_args__`` the declaration reads — those bases are
        combined into the live declaration, not discarded by it.
    """
    if cls_declaration is None:
        return set()
    return {
        cls_node.value.id
        for cls_node in ast.walk(cls_declaration)
        if isinstance(cls_node, ast.Attribute)
        and cls_node.attr == "__table_args__"
        and isinstance(cls_node.value, ast.Name)
    }


def _effective_table_args(
    str_name: str,
    dict_classes: dict[str, ast.ClassDef],
    dict_own_names: dict[str, list[tuple[str, int]]],
) -> tuple[list[tuple[str, int, str]], list[str]]:
    """Return the ONE ``__table_args__`` Python will actually use, plus the shadowed ones.

    🔴 ``__table_args__`` is an ordinary class attribute: attribute lookup stops at the first
    class in the MRO that defines it, and SQLAlchemy neither concatenates nor merges the
    rest. Unioning every base's constraint names — which this function replaced — invented
    collisions between a live declaration and a dead one, and renaming the dead one
    "resolved" a finding by editing code that never runs. The exception is a declaration that
    reads ``<Base>.__table_args__`` itself: that base is part of the live declaration.

    Parameters
    ----------
    str_name : str
        The class to resolve.
    dict_classes : dict of str to ast.ClassDef
        Every class defined in this file, by name.
    dict_own_names : dict of str to list of (str, int)
        Each class's OWN ``__table_args__`` constraint names (see :func:`_table_args_names`).

    Returns
    -------
    tuple
        ``(effective, shadowed)`` — ``effective`` is ``(constraint_name, lineno, owner)`` from
        the live declaration (and any base it composes); ``shadowed`` names the later
        declaring classes whose ``__table_args__`` is silently discarded at runtime.
    """
    list_declarers = [
        str_cls
        for str_cls in _in_file_mro(str_name, dict_classes)
        if _declares_table_args(dict_classes[str_cls])
    ]
    if not list_declarers:
        return [], []
    str_owner = list_declarers[0]
    set_consumed = _consumed_bases(_table_args_value(dict_classes[str_owner]))
    list_effective = [
        (str_n, int_ln, str_cls)
        for str_cls in [str_owner, *(c for c in list_declarers[1:] if c in set_consumed)]
        for str_n, int_ln in dict_own_names.get(str_cls, [])
    ]
    list_shadowed = [
        str_cls
        for str_cls in list_declarers[1:]
        if str_cls not in set_consumed and not _declares_tablename(dict_classes[str_cls])
    ]
    return list_effective, list_shadowed


def _duplicate_constraint_message(
    path_file: pathlib.Path,
    str_name: str,
    int_line: int,
    str_class: str,
    int_other_line: int,
    str_other_class: str,
) -> str:
    """Return the duplicate-constraint-name finding, naming both declaration sites.

    Parameters
    ----------
    path_file : pathlib.Path
        The offending file.
    str_name : str
        The duplicated constraint or index name.
    int_line : int
        The line of the second declaration.
    str_class : str
        The class owning the second declaration.
    int_other_line : int
        The line of the first declaration.
    str_other_class : str
        The class owning the first declaration.

    Returns
    -------
    str
        A human-readable finding.
    """
    return (
        f"{path_file}:{int_line}: name '{str_name}' is declared twice in one effective "
        f"__table_args__ (on {str_class} here, on {str_other_class} at line {int_other_line}). "
        f"Some backends fail at DDL time and others resolve it arbitrarily, so the model may "
        f"enforce less than it reads. Rename one of the two, or if deliberate: "
        f"# {_ALLOW_MARKER} <reason>"
    )


def _shadowed_table_args_problems(
    path_file: pathlib.Path,
    dict_inheritors: dict[str, list[str]],
    dict_classes: dict[str, ast.ClassDef],
    list_lines: list[str],
) -> list[str]:
    """Report each class whose ``__table_args__`` is discarded, once, naming who inherits it.

    Two mixins each declaring ``__table_args__`` do not compose: the first in the MRO wins
    and the rest vanish, silently, with every constraint they declared. A declaration that
    reads ``<Base>.__table_args__`` itself is exempt (see :func:`_consumed_bases`).

    Parameters
    ----------
    path_file : pathlib.Path
        The module's path, for the message.
    dict_inheritors : dict of str to list of str
        Each shadowed class, mapped to the models whose lookup discards it.
    dict_classes : dict of str to ast.ClassDef
        Every class defined in this file, by name.
    list_lines : list of str
        The source, split into lines, for the escape-hatch check.

    Returns
    -------
    list of str
        One finding per shadowed declaration not covered by an escape hatch.
    """
    list_problems = []
    for str_shadowed, list_models in dict_inheritors.items():
        int_line = dict_classes[str_shadowed].lineno
        if _line_allowed(list_lines, int_line):
            continue
        list_problems.append(
            f"{path_file}:{int_line}: '{str_shadowed}' declares '__table_args__', but "
            f"{', '.join(list_models)} also inherit(s) another declaration, and Python's "
            f"attribute lookup discards this one entirely. SQLAlchemy does not merge them; "
            f"every constraint declared here is silently absent from the table. Combine them "
            f"in one explicit '__table_args__' on the model "
            f"('A.__table_args__ + B.__table_args__'), or if deliberate: "
            f"# {_ALLOW_MARKER} <reason>"
        )
    return list_problems


def _duplicate_names_in(
    path_file: pathlib.Path,
    list_effective: list[tuple[str, int, str]],
    list_lines: list[str],
) -> list[str]:
    """Report each name declared twice inside one effective ``__table_args__``.

    Parameters
    ----------
    path_file : pathlib.Path
        The module's path, for the message.
    list_effective : list of (str, int, str)
        ``(constraint_name, lineno, owner)`` from :func:`_effective_table_args`.
    list_lines : list of str
        The source, split into lines, for the escape-hatch check.

    Returns
    -------
    list of str
        Human-readable findings; empty when every name is unique.
    """
    list_problems: list[str] = []
    dict_seen: dict[str, tuple[int, str]] = {}
    for str_constraint, int_line, str_class in list_effective:
        if str_constraint not in dict_seen:
            dict_seen[str_constraint] = (int_line, str_class)
        elif not _line_allowed(list_lines, int_line):
            int_other_line, str_other_class = dict_seen[str_constraint]
            list_problems.append(
                _duplicate_constraint_message(
                    path_file, str_constraint, int_line, str_class, int_other_line, str_other_class
                )
            )
    return list_problems


def _duplicate_constraint_name_problems(
    cls_tree: ast.Module, path_file: pathlib.Path, list_lines: list[str]
) -> list[str]:
    """Report duplicated constraint names and discarded ``__table_args__`` across in-file MROs.

    Only module-level classes are resolved: a nested class of the same name (an inner
    ``Meta``/``Config``) would otherwise overwrite the model it shares a name with.

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
        Human-readable findings, each reported once; empty when the file complies.
    """
    dict_classes = {n.name: n for n in cls_tree.body if isinstance(n, ast.ClassDef)}
    dict_own_names = {str_name: _table_args_names(n) for str_name, n in dict_classes.items()}
    dict_inheritors: dict[str, list[str]] = {}
    list_problems: list[str] = []
    for str_name, cls_model in dict_classes.items():
        list_effective, list_shadowed = _effective_table_args(
            str_name, dict_classes, dict_own_names
        )
        if not _line_allowed(list_lines, cls_model.lineno):
            for str_shadowed in list_shadowed:
                dict_inheritors.setdefault(str_shadowed, []).append(str_name)
        list_problems += _duplicate_names_in(path_file, list_effective, list_lines)
    list_problems += _shadowed_table_args_problems(
        path_file, dict_inheritors, dict_classes, list_lines
    )
    return list(dict.fromkeys(list_problems))


def check_python_file(
    path_file: pathlib.Path,
) -> tuple[list[str], list[tuple[pathlib.Path, int, str]]]:
    """Run every per-file guard against one Python source file.

    Parameters
    ----------
    path_file : pathlib.Path
        The module to check.

    Returns
    -------
    tuple of (list of str, list of (pathlib.Path, int, str))
        Per-file findings, and this file's Base declarations (for the tree-wide dedup that
        :func:`main` performs once every file has been visited).
    """
    str_source = path_file.read_text(encoding="utf-8")
    try:
        cls_tree = ast.parse(str_source)
    except SyntaxError as cls_exc:
        return [f"{path_file}: could not parse ({cls_exc})"], []

    list_lines = str_source.splitlines()
    list_problems = _bitwise_filter_problems(cls_tree, path_file, list_lines)
    list_problems += _module_scope_create_all_problems(cls_tree, path_file, list_lines)
    list_problems += _duplicate_constraint_name_problems(cls_tree, path_file, list_lines)
    list_bases = _base_declarations_in_file(cls_tree, path_file, list_lines)
    return list_problems, list_bases


def main() -> int:
    """Check every Python file under ``src/`` against every ORM model-definition guard.

    Returns
    -------
    int
        ``0`` when the tree complies (or ``src/`` does not exist), ``1`` otherwise.
    """
    path_src = pathlib.Path(_SRC_ROOT)
    if not path_src.is_dir():
        print(f"No {_SRC_ROOT}/ directory — skipping the ORM model guards check.")
        return 0

    list_py = sorted(p for p in path_src.rglob("*.py") if "__pycache__" not in p.parts)
    if not list_py:
        print(
            f"❌ 0 Python files discovered under {_SRC_ROOT}/ — the ORM model guards checked "
            f"NOTHING. A wrong working directory or a broken glob reporting success for having "
            f"checked nothing is the exact failure this gate exists to prevent."
        )
        return 1

    list_problems: list[str] = []
    list_all_bases: list[tuple[pathlib.Path, int, str]] = []
    for path_file in list_py:
        list_file_problems, list_bases = check_python_file(path_file)
        list_problems += list_file_problems
        list_all_bases += list_bases

    if len(list_all_bases) > 1:
        for cls_entry in list_all_bases:
            list_others = [e for e in list_all_bases if e != cls_entry]
            list_problems.append(_duplicate_base_message(cls_entry, list_others))

    for str_problem in list_problems:
        print(f"❌ {str_problem}")
    if list_problems:
        print(f"\n{len(list_problems)} ORM model guard violation(s).")
        return 1

    print(f"✅ ORM model guards OK ({len(list_py)} Python file(s) checked).")
    return 0


if __name__ == "__main__":
    for cls_stream in (sys.stdout, sys.stderr):
        if hasattr(cls_stream, "reconfigure"):
            cls_stream.reconfigure(encoding="utf-8", errors="replace")

    sys.exit(main())
