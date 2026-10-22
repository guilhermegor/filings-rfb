"""Enforce runtime type-checking application across the whole ``src/`` package.

Runtime type checking (the ``**/typing/`` engine — ``utils/typing`` in MVC, ``chassis/typing``
in DDD, ``<pkg>/_internal/utils/typing`` in lib-minimal) is **mandatory everywhere** — it
complements ruff ``ANN`` + mypy by turning annotated signatures into contracts that
fail loudly on values that cross a runtime boundary (deserialised data, DB rows). This
hook enforces the convention structurally, since neither ruff nor mypy can assert the
*presence* of a metaclass or decorator.

Rules, for every ``.py`` under ``src/`` (excluding the typing engine itself,
``**/typing/``). The doctrine is uniform — private helpers are checked too; the only
name-based skip is **dunders**, mirroring the ``TypeChecker`` metaclass which leaves
``__dunder__`` attributes untouched:

- **Standalone functions** (module-level, non-dunder) must be decorated with
  ``@type_checker``.
- **Classes** (top-level, non-dunder) that are **hierarchy roots** (declare no base
  class) must declare a checker metaclass (``TypeChecker`` / ``ABCTypeCheckerMeta`` /
  ``ProtocolTypeCheckerMeta``). A class *with* bases is left alone — Python inherits the
  metaclass, so a subclass of a checked class is already checked (e.g.
  ``LogsEmitter(LogEmitter)``).
- **Pydantic ``BaseModel`` subclasses** must **not** declare ``metaclass=TypeChecker`` —
  Pydantic owns the metaclass (conflict at import) and already validates at construction.

Every finding is a hard error (exit 1).
"""

import ast
import io
import pathlib
import sys
import tokenize


_CHECKER_METACLASSES = {"TypeChecker", "ABCTypeCheckerMeta", "ProtocolTypeCheckerMeta"}


def _is_dunder(name: str) -> bool:
    """Return whether a name is a Python dunder (``__x__``).

    Dunders are the one enforcement skip: the ``TypeChecker`` metaclass itself leaves
    ``__dunder__`` attributes untouched to avoid interfering with Python internals, so
    the hook mirrors that boundary rather than skipping all ``_``-prefixed names.

    Parameters
    ----------
    name : str
        The class or function name.

    Returns
    -------
    bool
        ``True`` when the name is a dunder.
    """
    return name.startswith("__") and name.endswith("__")


def _base_names(node: ast.ClassDef) -> set[str]:
    """Return the unqualified names of a class's base classes.

    Parameters
    ----------
    node : ast.ClassDef
        The class definition node.

    Returns
    -------
    set[str]
        Unqualified base-class names (``pydantic.BaseModel`` -> ``BaseModel``).
    """
    names: set[str] = set()
    for base in node.bases:
        if isinstance(base, ast.Name):
            names.add(base.id)
        elif isinstance(base, ast.Attribute):
            names.add(base.attr)
    return names


def _metaclass_name(node: ast.ClassDef) -> str | None:
    """Return the name given as ``metaclass=`` in a class header, if any.

    Parameters
    ----------
    node : ast.ClassDef
        The class definition node.

    Returns
    -------
    str or None
        The unqualified metaclass name, or ``None`` when none is declared.
    """
    for keyword in node.keywords:
        if keyword.arg != "metaclass":
            continue
        value = keyword.value
        if isinstance(value, ast.Name):
            return value.id
        if isinstance(value, ast.Attribute):
            return value.attr
    return None


def _decorator_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Return the unqualified names of a function's decorators.

    Parameters
    ----------
    node : ast.FunctionDef or ast.AsyncFunctionDef
        The function definition node.

    Returns
    -------
    set[str]
        Unqualified decorator names (``@type_checker``, ``@a.b`` -> ``b``).
    """
    names: set[str] = set()
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name):
            names.add(dec.id)
        elif isinstance(dec, ast.Attribute):
            names.add(dec.attr)
        elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
            names.add(dec.func.id)
    return names


_MARKER = "type-checker-ok:"


def comment_lines(str_source: str) -> dict[int, str]:
    """Map line number to comment text, for real ``COMMENT`` tokens only.

    ⚠️ **Read tokens, never raw lines.** A substring scan of the source cannot tell a comment
    from a string literal, so ``def f(x: str = "type-checker-ok: reason") -> str:`` would hand
    back a reason and wave an undecorated function through — a gate reporting success for a
    file it never actually exempted. ``check_comment_language.py`` tokenizes for the same
    reason. A file that will not tokenize yields no exemptions, so a syntax error can never
    widen the gate.

    Parameters
    ----------
    str_source : str
        The file's full source text.

    Returns
    -------
    dict of int to str
        Comment text keyed by 1-based line number.
    """
    dict_comments: dict[int, str] = {}
    try:
        for cls_tok in tokenize.generate_tokens(io.StringIO(str_source).readline):
            if cls_tok.type == tokenize.COMMENT:
                dict_comments[cls_tok.start[0]] = cls_tok.string
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return {}
    return dict_comments


def _escape_reason(
    node: ast.FunctionDef | ast.AsyncFunctionDef, dict_comments: dict[int, str]
) -> str | None:
    """Return the written reason for skipping the checker, or ``None`` when there is none.

    Scans the contiguous comment block immediately above the function **and** its signature
    lines, because ``ruff format`` re-wraps a long signature and pushes a trailing comment onto
    the closing-paren line — the same widening ``check_complexity.sh`` needed after a correctly
    written escape was silently voided.

    ⚠️ A bare ``# type-checker-ok`` is NOT accepted. The reason is the whole point: an
    unexplained marker is a rule the next reader widens.

    Parameters
    ----------
    node : ast.FunctionDef or ast.AsyncFunctionDef
        The function that lacks ``@type_checker``.
    dict_comments : dict of int to str
        Comment text by line number, from :func:`comment_lines`.

    Returns
    -------
    str or None
        The reason text, or ``None`` when no reason-carrying marker is present.
    """
    int_first = min([node.lineno, *[d.lineno for d in node.decorator_list]])
    int_last = node.body[0].lineno if node.body else node.lineno
    int_top = int_first
    while int_top - 1 in dict_comments:
        int_top -= 1
    for int_line in range(int_top, int_last):
        str_comment = dict_comments.get(int_line, "")
        if _MARKER in str_comment:
            return str_comment.split(_MARKER, 1)[1].strip() or None
    return None


def _check_class(node: ast.ClassDef, filepath: str) -> int:
    """Check one public class for correct runtime-checker application.

    Parameters
    ----------
    node : ast.ClassDef
        The class definition node.
    filepath : str
        Source file (for messages).

    Returns
    -------
    int
        Number of hard errors for this class (0 or 1).
    """
    is_pydantic = "BaseModel" in _base_names(node)
    metaclass = _metaclass_name(node)
    if is_pydantic:
        if metaclass in _CHECKER_METACLASSES:
            print(
                f"❌ {node.name} at line {node.lineno} ({filepath}): a Pydantic model must not "
                f"set metaclass={metaclass} (metaclass conflict at import)."
            )
            return 1
        return 0
    if node.bases:
        return 0
    if metaclass not in _CHECKER_METACLASSES:
        allowed = ", ".join(sorted(_CHECKER_METACLASSES))
        print(
            f"❌ {node.name} at line {node.lineno} ({filepath}): a root class must declare "
            f"metaclass=<one of: {allowed}> (runtime type checking)."
        )
        return 1
    return 0


def check_file(filepath: str) -> int:
    """Check runtime-checker application for every public class/function in a file.

    Parameters
    ----------
    filepath : str
        Path to a Python source file under ``src/``.

    Returns
    -------
    int
        Number of hard errors found in the file.
    """
    errors = 0
    with open(filepath, encoding="utf-8") as fh:
        str_source = fh.read()
    dict_comments = comment_lines(str_source)
    tree = ast.parse(str_source, filename=filepath)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not _is_dunder(node.name):
            errors += _check_class(node, filepath)
        elif (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and not _is_dunder(node.name)
            and "type_checker" not in _decorator_names(node)
            and _escape_reason(node, dict_comments) is None
        ):
            print(
                f"❌ {node.name}() at line {node.lineno} ({filepath}): a standalone function must "
                f"be decorated with @type_checker (runtime type checking)."
            )
            errors += 1
    return errors


_EXCLUDED_PARTS = {"typing", "chassis", "example_feature"}


def _source_files() -> list[pathlib.Path]:
    """Collect every Python file under ``src/`` except the documented exempt trees.

    Returns
    -------
    list[pathlib.Path]
        Python source files to check (``**/typing/``, ``**/chassis/`` and
        ``**/example_feature/`` are exempt, mirroring ruff.toml / mypy.ini).
    """
    return sorted(
        p for p in pathlib.Path("src").rglob("*.py") if _EXCLUDED_PARTS.isdisjoint(p.parts)
    )


if __name__ == "__main__":
    for cls_stream in (sys.stdout, sys.stderr):
        if hasattr(cls_stream, "reconfigure"):
            cls_stream.reconfigure(encoding="utf-8", errors="replace")

    total_errors = sum(check_file(str(p)) for p in _source_files())
    sys.exit(1 if total_errors > 0 else 0)
