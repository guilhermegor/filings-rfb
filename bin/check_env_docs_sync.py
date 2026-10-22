#!/usr/bin/env python3
"""Fail when ``.env.example`` and ``docs/configuration.md`` list different variables.

``.env.example`` carries keys and example values only (blueprintx#304): every annotation
lives in the configuration table. A table whose header has an ``In .env.example`` column
lists one variable per row; the rows marked ``yes`` must equal the file's keys, in both
directions, so a renamed or added variable turns red where a stale comment never did.

Usage::

    python bin/check_env_docs_sync.py                  # this project
    python bin/check_env_docs_sync.py --root DIR       # one project root
    python bin/check_env_docs_sync.py --each-under DIR # every child of DIR with a .env.example

A root with neither file passes: nothing to document.
"""

import pathlib
import re
import sys


STR_ENV_NAME = ".env.example"
STR_DOC_NAME = "docs/configuration.md"
STR_COLUMN = "in .env.example"
STR_ROOT_FLAG = "--root"
STR_EACH_FLAG = "--each-under"

RE_ENV_KEY = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=")
RE_ROW_NAME = re.compile(r"^`([A-Za-z_][A-Za-z0-9_]*)`$")


def env_keys(str_text: str) -> set:
    """Return the variable names assigned in a dotenv file.

    Parameters
    ----------
    str_text : str
        The ``.env.example`` content.

    Returns
    -------
    set of str
        Every key on a ``KEY=value`` line.
    """
    set_keys = set()
    for str_line in str_text.splitlines():
        cls_match = RE_ENV_KEY.match(str_line.strip())
        if cls_match:
            set_keys.add(cls_match.group(1))
    return set_keys


def split_cells(str_line: str) -> list:
    """Split one Markdown table row into stripped cells.

    Parameters
    ----------
    str_line : str
        A line starting with ``|``.

    Returns
    -------
    list of str
        The cell texts without the outer pipes.
    """
    return [str_cell.strip() for str_cell in str_line.strip().strip("|").split("|")]


def seeded_name(list_cells: list, int_column: int) -> str:
    """Return the variable a table row marks as seeded, or an empty string.

    Parameters
    ----------
    list_cells : list of str
        The row's cells.
    int_column : int
        Index of the ``In .env.example`` column, -1 outside such a table.

    Returns
    -------
    str
        The backticked name in the first cell when the flag cell reads ``yes``.
    """
    cls_match = RE_ROW_NAME.match(list_cells[0])
    if int_column < 0 or not cls_match or len(list_cells) <= int_column:
        return ""
    return cls_match.group(1) if list_cells[int_column].lower() == "yes" else ""


def seeded_rows(str_text: str) -> set:
    """Return the variables the configuration tables mark as seeded in ``.env.example``.

    Parameters
    ----------
    str_text : str
        The ``docs/configuration.md`` content.

    Returns
    -------
    set of str
        Names in the first cell of rows whose ``In .env.example`` cell reads ``yes``.
    """
    set_names = set()
    int_column = -1
    for str_line in str_text.splitlines():
        if not str_line.lstrip().startswith("|"):
            int_column = -1
            continue
        list_cells = split_cells(str_line)
        list_lower = [str_cell.lower() for str_cell in list_cells]
        if STR_COLUMN in list_lower:
            int_column = list_lower.index(STR_COLUMN)
        else:
            set_names.add(seeded_name(list_cells, int_column))
    set_names.discard("")
    return set_names


def project_problems(path_root: pathlib.Path) -> list:
    """Return the findings for one project root.

    Parameters
    ----------
    path_root : pathlib.Path
        A project root that may hold ``.env.example`` and ``docs/configuration.md``.

    Returns
    -------
    list of str
        One message per variable on only one side, or per missing file.
    """
    path_env = path_root / STR_ENV_NAME
    path_doc = path_root / STR_DOC_NAME
    if not path_env.is_file() and not path_doc.is_file():
        return []
    if not path_doc.is_file():
        return [f"{path_root}: {STR_ENV_NAME} exists but {STR_DOC_NAME} does not"]
    set_env = env_keys(path_env.read_text(encoding="utf-8")) if path_env.is_file() else set()
    set_doc = seeded_rows(path_doc.read_text(encoding="utf-8"))
    list_problems = [
        f"{path_root}: {str_key} is in {STR_ENV_NAME} but has no 'yes' row in {STR_DOC_NAME}"
        for str_key in sorted(set_env - set_doc)
    ]
    list_problems += [
        f"{path_root}: {str_key} is marked 'yes' in {STR_DOC_NAME} but is not in {STR_ENV_NAME}"
        for str_key in sorted(set_doc - set_env)
    ]
    return list_problems


def project_roots(list_argv: list) -> list:
    """Resolve the command line to the project roots to check.

    Parameters
    ----------
    list_argv : list of str
        Arguments after the program name.

    Returns
    -------
    list of pathlib.Path
        ``--each-under DIR`` yields every child of ``DIR`` holding a ``.env.example``;
        ``--root DIR`` yields ``DIR``; no flag yields the project this script lives in.
    """
    if STR_EACH_FLAG in list_argv:
        path_parent = pathlib.Path(list_argv[list_argv.index(STR_EACH_FLAG) + 1])
        return sorted(path_dir for path_dir in path_parent.iterdir() if path_dir.is_dir())
    if STR_ROOT_FLAG in list_argv:
        return [pathlib.Path(list_argv[list_argv.index(STR_ROOT_FLAG) + 1])]
    return [pathlib.Path(__file__).resolve().parent.parent]


def main(list_argv: list) -> int:
    """Check every resolved project root and print the findings.

    Parameters
    ----------
    list_argv : list of str
        Arguments after the program name.

    Returns
    -------
    int
        0 when every root is in sync, 1 otherwise.
    """
    list_problems = []
    list_roots = project_roots(list_argv)
    for path_root in list_roots:
        list_problems += project_problems(path_root)
    for str_problem in list_problems:
        print(str_problem)
    if list_problems:
        print(f"{len(list_problems)} finding(s): keep {STR_ENV_NAME} and {STR_DOC_NAME} in step.")
        return 1
    print(f"env docs OK ({len(list_roots)} project root(s) checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
