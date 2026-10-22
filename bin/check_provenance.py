"""Enforce that every file/scrape read is paired with a provenance stamp.

Ingestion honesty has two halves that must never drift apart: the ``read_table`` contract
check (already enforced — bare ``pd.read_*`` is banned by ruff ``TID251`` so every read funnels
through a contract) and the ``stamp_provenance`` call that makes the resulting bronze row
traceable. This hook is the second guardrail: for every ``.py`` under ``src/``, **if the module
calls ``read_table(`` it must also reference ``stamp_provenance``** — so a file/scrape read
cannot ship without a stamp.

The token is the **call form** ``read_table(``, deliberately, for two reasons:

- It excludes ``read_query`` (the SQL sibling) — a DataFrame read back from your own database is
  **not** internet-ingested and is out of provenance scope (see the dtypes/provenance lesson).
- It excludes prose mentions of the bare name (e.g. a ``FileContract`` module docstring that
  says "passed to ``read_table``") — those are declarations, not reads.

Inheritance is handled naturally: a base reader that calls both satisfies the check; thin
subclasses that inherit ``read()`` call neither and are fine. The seam module
``utils/tabular_reader.py`` — which *defines* ``def read_table(`` — is exempt (pairing it would
be circular).

Every finding is a hard error (exit 1).
"""

import pathlib
import sys


_READ_MARKER = "read_table("
_STAMP_MARKER = "stamp_provenance"

_EXCLUDED_PARTS = {"typing", "chassis", "example_feature"}

_SEAM_FILENAMES = {"tabular_reader.py", "provenance.py"}


def check_file(filepath: str) -> int:
    """Return 1 when a module references a contract read without a provenance stamp.

    Parameters
    ----------
    filepath : str
        Path to a Python source file under ``src/``.

    Returns
    -------
    int
        1 when ``read_table`` appears without ``stamp_provenance``, else 0.
    """
    str_source = pathlib.Path(filepath).read_text(encoding="utf-8")
    if _READ_MARKER not in str_source:
        return 0
    if _STAMP_MARKER in str_source:
        return 0
    print(
        f"❌ {filepath}: calls '{_READ_MARKER}' but never references '{_STAMP_MARKER}' — a "
        f"file/scrape read must stamp provenance (utils.provenance.stamp_provenance) so its "
        f"bronze rows stay traceable."
    )
    return 1


def _source_files() -> list[pathlib.Path]:
    """Collect every Python file under ``src/`` except the documented exempt trees and seams.

    Returns
    -------
    list[pathlib.Path]
        Python source files to check (``typing``/``chassis``/``example_feature`` trees and the
        ``tabular_reader.py``/``provenance.py`` seam definitions are exempt).
    """
    return sorted(
        p
        for p in pathlib.Path("src").rglob("*.py")
        if _EXCLUDED_PARTS.isdisjoint(p.parts) and p.name not in _SEAM_FILENAMES
    )


if __name__ == "__main__":
    for cls_stream in (sys.stdout, sys.stderr):
        if hasattr(cls_stream, "reconfigure"):
            cls_stream.reconfigure(encoding="utf-8", errors="replace")

    list_targets = _source_files()
    if not list_targets:
        print("❌ no Python files found under src/ — refusing to report success.")
        sys.exit(1)

    total_errors = sum(check_file(str(p)) for p in list_targets)
    if total_errors == 0:
        print(f"✅ provenance stamp OK ({len(list_targets)} file(s) checked)")
    sys.exit(1 if total_errors > 0 else 0)
