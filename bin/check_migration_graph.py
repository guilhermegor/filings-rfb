"""Structural gate: the Alembic migration graph must have exactly one head (blueprintx#308).

Two PRs that each add a migration off the same base branch clean-merge Git-side — two new
files, no textual overlap, no conflict — while the *migration* graph silently branches: both
files carry the same ``down_revision``, and ``alembic upgrade head`` then fails with
"Multiple head revisions are present", discovered only when someone tries to migrate a real
database. Nothing in this repo's existing gates reads that graph; ``check_migration_slugs.py``
(#375) checks only the filename's SLUG, a different, purely textual concern.

This gate answers the one question that is decidable from the files alone, with no DB and no
``alembic`` import — read every ``revision``/``down_revision`` header via ``ast`` (never
``import`` the migration modules; they import ``alembic.op``, which is not installed on every
box that runs this gate) and check the graph it describes:

    1. **Every ``revision`` id is unique.** A collision means two files claim the same node.
    2. **Every ``down_revision`` reference resolves** to a ``revision`` that exists in the
       same ``versions/`` directory — a dangling parent is a torn-out or renamed migration.
    3. **Exactly one head.** A head is a revision nobody's ``down_revision`` points at. Two
       heads is the branched-history failure this gate exists to catch; the fix is
       ``alembic merge heads``, whose merge revision's ``down_revision`` is a TUPLE of both
       parents — this gate accepts a tuple the same way Alembic does.

SELF-SKIPS when ``migrations/versions/`` is absent or holds no revision files — only the ORM
tier ships migrations today (#373), and this script ships to every Python tier via
``python-common/bin/``. A file that exists but cannot be parsed (syntax error, no ``revision``
assignment) is NOT a skip — it is a finding: a graph gate that silently ignores what it cannot
read is exactly the "success for having checked nothing" failure this repo writes gates to
prevent.

Out of scope, deliberately (#308's own scope note): the round-trip ``upgrade``/``downgrade``
witness and the autogenerate-empty-diff check both need a live database and an installed
``alembic`` — heavier machinery than a structural graph read, and a separate follow-up.
"""

import ast
import pathlib
import sys


_PATH_MIGRATIONS = pathlib.Path("migrations/versions")
_HEADER_NAMES = frozenset({"revision", "down_revision"})

_MISSING = object()
_UNSUPPORTED = object()


def _literal(node: ast.expr | None) -> object:
    """Return the literal Python value of a simple AST expression.

    Parameters
    ----------
    node : ast.expr or None
        The right-hand side of a ``revision``/``down_revision`` assignment.

    Returns
    -------
    object
        A ``str``, a ``tuple`` of ``str`` (a merge revision's multiple parents), or ``None``
        when the node is not one of the literal shapes Alembic itself generates.
    """
    if node is None:
        return _UNSUPPORTED
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Tuple | ast.List):
        return tuple(_literal(cls_elt) for cls_elt in node.elts)
    return _UNSUPPORTED


def _revision_header(path_file: pathlib.Path) -> dict[str, object]:
    """Extract the ``revision``/``down_revision`` literals from a migration file.

    Reads the module via ``ast`` rather than ``import`` — a migration imports
    ``alembic.op``, which is not installed on every box this gate runs on.

    Parameters
    ----------
    path_file : pathlib.Path
        A migration version file.

    Returns
    -------
    dict of str to object
        ``{"revision": ..., "down_revision": ...}`` for whichever of the two module-level
        assignments are present (plain ``Assign`` or annotated ``AnnAssign`` — Alembic's own
        ``script.py.mako`` uses the annotated form).

    Raises
    ------
    SyntaxError
        When the file is not valid Python.
    """
    cls_tree = ast.parse(path_file.read_text(encoding="utf-8"))
    dict_header: dict[str, object] = {}
    for cls_node in cls_tree.body:
        if isinstance(cls_node, ast.Assign) and len(cls_node.targets) == 1:
            cls_target = cls_node.targets[0]
        elif isinstance(cls_node, ast.AnnAssign):
            cls_target = cls_node.target
        else:
            continue
        if isinstance(cls_target, ast.Name) and cls_target.id in _HEADER_NAMES:
            dict_header[cls_target.id] = _literal(cls_node.value)
    return dict_header


def _parent_revisions(value: object) -> tuple[str, ...]:
    """Normalise a ``down_revision`` literal to a tuple of parent revision ids.

    Parameters
    ----------
    value : object
        The parsed ``down_revision`` value — ``None``, a ``str``, or a ``tuple``.

    Returns
    -------
    tuple
        ``(parents, reason)`` — ``parents`` is empty for a root revision (``None``), one
        entry for a normal migration, more than one for a merge revision. ``reason`` is
        ``None`` when the value was valid, otherwise a description of why it could not be
        trusted; the caller must report it rather than treating the file as a root.
    """
    if value is None:
        return (), None
    if isinstance(value, str):
        return (value,), None
    if isinstance(value, tuple):
        if all(isinstance(str_item, str) for str_item in value):
            return tuple(value), None
        return (), "a tuple whose elements are not all strings"
    if value is _UNSUPPORTED:
        return (), "not a literal this reader can evaluate (a name, call, or f-string)"
    return (), f"an unsupported {type(value).__name__} value"


def _version_files() -> list[pathlib.Path]:
    """Collect migration version files to check.

    Returns
    -------
    list of pathlib.Path
        Every ``*.py`` file under ``migrations/versions/``, excluding ``__init__.py``.
    """
    return sorted(p for p in _PATH_MIGRATIONS.glob("*.py") if p.name != "__init__.py")


_TupleGraphEdge = tuple[str, str, pathlib.Path]


def build_graph(
    list_files: list[pathlib.Path],
) -> tuple[dict[str, pathlib.Path], list[_TupleGraphEdge], list[str]]:
    """Parse every migration file and assemble the revision graph.

    Parameters
    ----------
    list_files : list of pathlib.Path
        Migration version files to parse.

    Returns
    -------
    tuple
        ``(revision_to_file, edges, problems)`` — ``revision_to_file`` maps a revision id to
        the file that declares it; ``edges`` is ``(parent_revision, child_revision, file)``
        for every ``down_revision`` reference; ``problems`` lists unparsable files and
        duplicate revision ids found while building the graph.
    """
    dict_rev_to_file: dict[str, pathlib.Path] = {}
    list_edges: list[_TupleGraphEdge] = []
    list_problems: list[str] = []
    for path_file in list_files:
        try:
            dict_header = _revision_header(path_file)
        except SyntaxError as cls_exc:
            list_problems.append(f"{path_file}: not valid Python ({cls_exc}) — cannot verify")
            continue
        str_revision = dict_header.get("revision")
        if not isinstance(str_revision, str):
            list_problems.append(f"{path_file}: no 'revision' string assignment — cannot verify")
            continue
        if str_revision in dict_rev_to_file:
            list_problems.append(
                f"{path_file}: duplicate revision id '{str_revision}', already used by "
                f"{dict_rev_to_file[str_revision]}"
            )
            continue
        dict_rev_to_file[str_revision] = path_file
        obj_down = dict_header.get("down_revision", _MISSING)
        if obj_down is _MISSING:
            list_problems.append(
                f"{path_file}: no 'down_revision' assignment — cannot verify (a root "
                f"revision must say so explicitly with 'down_revision = None')"
            )
            continue
        tuple_parents, str_reason = _parent_revisions(obj_down)
        if str_reason is not None:
            list_problems.append(f"{path_file}: down_revision is {str_reason} — cannot verify")
            continue
        for str_parent in tuple_parents:
            list_edges.append((str_parent, str_revision, path_file))
    return dict_rev_to_file, list_edges, list_problems


def cycle_problems(
    dict_rev_to_file: dict[str, pathlib.Path], list_edges: list[_TupleGraphEdge]
) -> list[str]:
    """Return one problem per revision that sits on a cycle, in any component.

    Head-counting alone cannot find a cycle that shares the graph with a valid chain: the
    chain still supplies a head, the count reads 1, and the cycle is invisible. Kahn's
    algorithm peels every revision reachable from a root; whatever will not peel is on a
    cycle or downstream of one (blueprintx#308).

    Parameters
    ----------
    dict_rev_to_file : dict of str to pathlib.Path
        Every revision id found, mapped to its file.
    list_edges : list of tuple
        ``(parent_revision, child_revision, file)`` for every ``down_revision`` reference.

    Returns
    -------
    list of str
        A single message naming the revisions that never resolve to a root, or empty.
    """
    dict_indegree = {str_rev: 0 for str_rev in dict_rev_to_file}
    dict_children: dict[str, list[str]] = {str_rev: [] for str_rev in dict_rev_to_file}
    for str_parent, str_child, _ in list_edges:
        if str_parent in dict_rev_to_file and str_child in dict_rev_to_file:
            dict_indegree[str_child] += 1
            dict_children[str_parent].append(str_child)
    list_queue = [str_rev for str_rev, int_deg in dict_indegree.items() if int_deg == 0]
    int_peeled = 0
    while list_queue:
        str_rev = list_queue.pop()
        int_peeled += 1
        for str_child in dict_children[str_rev]:
            dict_indegree[str_child] -= 1
            if dict_indegree[str_child] == 0:
                list_queue.append(str_child)
    if int_peeled == len(dict_rev_to_file):
        return []
    list_stuck = sorted(str_rev for str_rev, int_deg in dict_indegree.items() if int_deg > 0)
    return [
        f"cycle in the revision graph: {', '.join(list_stuck)} never resolve to a root — "
        f"a down_revision chain loops back on itself"
    ]


def graph_problems(
    dict_rev_to_file: dict[str, pathlib.Path], list_edges: list[_TupleGraphEdge]
) -> list[str]:
    """Return dangling-parent, self-reference, and head-count problems for a parsed graph.

    Parameters
    ----------
    dict_rev_to_file : dict of str to pathlib.Path
        Every revision id found, mapped to its file.
    list_edges : list of tuple
        ``(parent_revision, child_revision, file)`` for every ``down_revision`` reference.

    Returns
    -------
    list of str
        One message per dangling or self reference, plus a final message when the head
        count is not exactly one.
    """
    list_problems = []
    for str_parent, str_child, path_file in list_edges:
        if str_parent == str_child:
            list_problems.append(f"{path_file}: down_revision '{str_parent}' references itself")
        elif str_parent not in dict_rev_to_file:
            list_problems.append(
                f"{path_file}: down_revision '{str_parent}' has no matching revision file — "
                f"dangling reference (renamed, deleted, or never merged)"
            )
    set_referenced = {str_parent for str_parent, _, _ in list_edges}
    set_heads = set(dict_rev_to_file) - set_referenced
    if len(set_heads) > 1:
        list_problems.append(
            f"{len(set_heads)} head revisions present: {', '.join(sorted(set_heads))} — two "
            f"branches were merged without an 'alembic merge heads' revision joining them"
        )
    elif not set_heads and dict_rev_to_file:
        list_problems.append(
            "no head revision found — every revision is referenced as a parent (a cycle)"
        )
    list_problems.extend(cycle_problems(dict_rev_to_file, list_edges))
    return list_problems


def vacuous_discovery_reason(list_files: list[pathlib.Path]) -> str | None:
    """Return why discovery is a legitimate skip, or ``None`` when there is real work to check.

    Parameters
    ----------
    list_files : list of pathlib.Path
        The migration version files discovered, if any.

    Returns
    -------
    str or None
        A human-readable skip reason, or ``None`` when ``list_files`` holds real revisions.
    """
    if not _PATH_MIGRATIONS.is_dir():
        return "no migrations/versions/ in this tier — skipping"
    if not list_files:
        return "0 migration files found — nothing to check"
    return None


def main() -> int:
    """Run the gate against ``migrations/versions/`` relative to the current directory.

    Returns
    -------
    int
        ``0`` when the tier ships no migrations yet, or the graph has exactly one head with
        no dangling/duplicate/self-referencing revisions; ``1`` otherwise.
    """
    list_files = _version_files() if _PATH_MIGRATIONS.is_dir() else []
    str_reason = vacuous_discovery_reason(list_files)
    if str_reason is not None:
        print(f"✅ migration graph gate: {str_reason}")
        return 0

    dict_rev_to_file, list_edges, list_problems = build_graph(list_files)
    list_problems += graph_problems(dict_rev_to_file, list_edges)
    for str_problem in list_problems:
        print(f"❌ {str_problem}", file=sys.stderr)
    if list_problems:
        print(
            f"\n{len(list_problems)} problem(s). Run 'alembic heads' to see every head, and "
            f"'alembic merge heads' to join a branched history into one.",
            file=sys.stderr,
        )
        return 1

    print(
        f"✅ migration graph gate: {len(dict_rev_to_file)} revision(s) checked, single head, "
        f"0 findings"
    )
    return 0


if __name__ == "__main__":
    for cls_stream in (sys.stdout, sys.stderr):
        if hasattr(cls_stream, "reconfigure"):
            cls_stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
