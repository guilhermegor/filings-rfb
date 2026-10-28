#!/usr/bin/env python3
"""Fail when a dynamically versioned project hand-bumps its ``pyproject.toml`` version.

With ``[tool.poetry-dynamic-versioning] enable = true`` the build backend takes the version
from the git tag and never reads ``[tool.poetry] version``. A real-looking number there invites
a hand-bump that then goes stale (filings-rfb#30, #51), so the field must stay the ``0.0.0``
stub and the git tag stays the single source of truth.

Usage::

    python bin/check_dynamic_version_stub.py             # this project
    python bin/check_dynamic_version_stub.py --root DIR  # one project root

A project without dynamic versioning passes: its ``version`` field is the real one.
"""

import pathlib
import sys


try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


STR_STUB = "0.0.0"
STR_ROOT_FLAG = "--root"


def stub_problems(path_root: pathlib.Path) -> list:
    """Return the findings for one project root.

    Parameters
    ----------
    path_root : pathlib.Path
        A project root holding ``pyproject.toml``.

    Returns
    -------
    list of str
        One message when dynamic versioning is on and the version is not the stub.
    """
    path_toml = path_root / "pyproject.toml"
    if not path_toml.is_file():
        return []
    dict_tool = tomllib.loads(path_toml.read_text(encoding="utf-8")).get("tool", {})
    if not dict_tool.get("poetry-dynamic-versioning", {}).get("enable", False):
        return []
    str_version = dict_tool.get("poetry", {}).get("version", "")
    if str_version == STR_STUB:
        return []
    return [
        f"{path_toml}: [tool.poetry] version is {str_version!r}, expected {STR_STUB!r} — "
        "poetry-dynamic-versioning sets the version from the git tag; release by tagging, "
        "never by editing this field"
    ]


def project_root(list_argv: list) -> pathlib.Path:
    """Resolve the command line to the project root to check.

    Parameters
    ----------
    list_argv : list of str
        Arguments after the program name.

    Returns
    -------
    pathlib.Path
        ``--root DIR`` yields ``DIR``; no flag yields the project this script lives in.
    """
    if STR_ROOT_FLAG in list_argv:
        return pathlib.Path(list_argv[list_argv.index(STR_ROOT_FLAG) + 1])
    return pathlib.Path(__file__).resolve().parent.parent


def main(list_argv: list) -> int:
    """Check the resolved project root and print the findings.

    Parameters
    ----------
    list_argv : list of str
        Arguments after the program name.

    Returns
    -------
    int
        0 when the stub holds or dynamic versioning is off, 1 otherwise.
    """
    list_problems = stub_problems(project_root(list_argv))
    for str_problem in list_problems:
        print(str_problem)
    if list_problems:
        return 1
    print("dynamic version stub OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
