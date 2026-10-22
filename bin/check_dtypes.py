"""Structural gate: an ingested source column is never typed as a binary float.

``float64`` cannot represent most decimal fractions. A traded volume of ``1984223115.42``
is stored as ``1984223115.4200000762939453125`` — close enough to print correctly, wrong
enough that summing a session and reconciling against the exchange's published total misses by
a hair, with nothing to point at. The loss happens at ingestion, is **irreversible**, and is
**silent**: no contract check, no test of a single value, and no eyeball on a printed frame
will show it.

So this gate bans a float dtype declaration in ``src/``. The replacement is
``list_decimal_cols`` (exact :class:`decimal.Decimal`, scale preserved from the source) or
plain text; both are lossless, and a consumer can always downcast to float, whereas the
reverse is impossible.

**Escape hatch.** A genuinely dimensionless quantity with no exact decimal scale — a
statistical measure, a ratio derived by the source — may legitimately be a float. Annotate the
line and the gate accepts it::

    "SOME_RATIO": "float64",  # dtype-ok: dimensionless statistic, no exact scale

Requiring the reason in writing is the point: it turns an invisible default into a decision
someone made on purpose.
"""

import pathlib
import re
import sys


_RE_FLOAT_DTYPE = re.compile(r"""["'](?:float(?:16|32|64|128)?|Float(?:32|64))["']""")

_ALLOW_MARKER = "dtype-ok:"

_EXCLUDED_PARTS = {"typing", "chassis"}


def check_file(str_path: str) -> int:
    """Report every banned float dtype declaration in one file.

    Parameters
    ----------
    str_path : str
        Path to the Python source file to scan.

    Returns
    -------
    int
        The number of violations found (0 when clean).
    """
    int_errors = 0
    for int_no, str_line in enumerate(
        pathlib.Path(str_path).read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not _RE_FLOAT_DTYPE.search(str_line):
            continue
        if _ALLOW_MARKER in str_line:
            continue
        print(
            f"❌ {str_path}:{int_no}: {str_line.strip()}\n"
            f"   A binary float loses the source value irreversibly and silently. Use "
            f"list_decimal_cols (exact Decimal) or text. If the value is genuinely "
            f"dimensionless, annotate the line:  # {_ALLOW_MARKER} <reason>"
        )
        int_errors += 1
    return int_errors


def _source_files() -> list[pathlib.Path]:
    """Collect every Python file under ``src/`` outside the exempt trees.

    Returns
    -------
    list[pathlib.Path]
        Python source files to check.
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
