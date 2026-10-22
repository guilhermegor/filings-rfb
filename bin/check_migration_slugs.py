"""Structural gate: a migration filename must lead with a known verb (blueprintx#375).

Alembic imposes no naming convention — ``-m`` is free text. This adopts Rails'
``<verb>_<object>[_<qualifier>]`` shape: the verb is the first token, so
``ls migrations/versions/`` sorts by date and reads as a changelog on its own.
``templates/ddd-service-orm-db/alembic.ini``'s ``file_template`` (#373) already fixes the
filename to ``<date>_<rev>_<slug>.py``; this gate checks only the SLUG, decidable from the
filename alone — no interactive picker, no ``db.sh`` change (#375 leaves those undecided).

    create   drop     add      remove   rename
    change   backfill seed

``backfill``/``seed`` are their own verbs because they are NOT schema changes and cannot be
safely re-run — a reader scanning "what could have moved data" needs them to stand out.

SELF-SKIPS when ``migrations/versions/`` is absent. Only the ORM tier ships migrations today
(#373), and this script ships to every Python tier via ``python-common/bin/``.

Escape hatch, reason required, same shape as ``rmw-ok:``/``complexity-ok:`` elsewhere in this
file family — ``alembic merge`` produces a ``merge_<rev>`` slug outside the enum::

    # migration-slug-ok: <reason>

anywhere in the migration file's first few lines.
"""

import pathlib
import re
import sys


_ALLOWED_VERBS = frozenset(
    {"create", "drop", "add", "remove", "rename", "change", "backfill", "seed"}
)

_RE_FILENAME = re.compile(r"^\d{8}_[0-9a-f]+_(?P<slug>.+)\.py$")
_RE_ESCAPE = re.compile(r"migration-slug-ok:[ \t]*(\S[^\r\n]*)")
_INT_ESCAPE_SCAN_LINES = 5

_PATH_MIGRATIONS = pathlib.Path("migrations/versions")


def _slug_verb(str_slug: str) -> str:
    """Return the leading verb token of a migration slug.

    Parameters
    ----------
    str_slug : str
        The migration slug (filename minus date/rev/extension).

    Returns
    -------
    str
        Everything before the first underscore.
    """
    return str_slug.split("_", 1)[0]


def _has_escape_hatch(path_file: pathlib.Path) -> bool:
    """Return whether the file carries a reasoned ``migration-slug-ok:`` pragma.

    Parameters
    ----------
    path_file : pathlib.Path
        The migration file to scan.

    Returns
    -------
    bool
        True when a pragma with a reason appears in the file's first few lines.
    """
    list_lines = path_file.read_text(encoding="utf-8").splitlines()[:_INT_ESCAPE_SCAN_LINES]
    return bool(_RE_ESCAPE.search("\n".join(list_lines)))


def check_file(path_file: pathlib.Path) -> int:
    """Report a migration filename's slug-verb violation, if any.

    Parameters
    ----------
    path_file : pathlib.Path
        A migration version file.

    Returns
    -------
    int
        1 when the filename fails the shape or verb check and carries no escape hatch,
        0 otherwise.
    """
    cls_match = _RE_FILENAME.match(path_file.name)
    if cls_match is None:
        print(
            f"❌ {path_file}: filename does not match <date>_<rev>_<slug>.py "
            f"(ddd-service-orm-db/alembic.ini's file_template) — cannot verify the slug"
        )
        return 1
    str_slug = cls_match.group("slug")
    if _slug_verb(str_slug) in _ALLOWED_VERBS or _has_escape_hatch(path_file):
        return 0
    print(
        f"❌ {path_file}: slug '{str_slug}' does not start with a known verb "
        f"({', '.join(sorted(_ALLOWED_VERBS))}). Rename the migration message, or add "
        f"'# migration-slug-ok: <reason>' near the top of the file."
    )
    return 1


def _version_files() -> list:
    """Collect migration version files to check.

    Returns
    -------
    list of pathlib.Path
        Every ``*.py`` file under ``migrations/versions/``, excluding ``__init__.py``.
    """
    return sorted(p for p in _PATH_MIGRATIONS.glob("*.py") if p.name != "__init__.py")


def main() -> int:
    """Run the gate against ``migrations/versions/`` relative to the current directory.

    Returns
    -------
    int
        Process exit code: 0 when the tier ships no migrations, has none yet, or every
        slug passes; 1 when any slug fails.
    """
    if not _PATH_MIGRATIONS.exists():
        print("✅ migration slug gate: no migrations/versions/ in this tier — skipping")
        return 0

    list_files = _version_files()
    if not list_files:
        print("✅ migration slug gate: 0 migration files found — nothing to check")
        return 0

    int_total = sum(check_file(path_file) for path_file in list_files)
    if int_total == 0:
        print(f"✅ migration slug gate: {len(list_files)} file(s) checked, 0 findings")
    return 1 if int_total > 0 else 0


if __name__ == "__main__":
    for cls_stream in (sys.stdout, sys.stderr):
        if hasattr(cls_stream, "reconfigure"):
            cls_stream.reconfigure(encoding="utf-8", errors="replace")

    sys.exit(main())
