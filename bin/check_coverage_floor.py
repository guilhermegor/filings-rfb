"""Enforce that ``.coveragerc``'s ``omit`` list never swallows a capability's real logic.

``fail_under`` in ``.coveragerc`` is the coverage floor this repo already ships. That floor is
only honest if the ``omit`` list beside it is accurate — and ``omit`` is exactly the shape of
hand-declared list this repo distrusts: nobody can contradict it. Widen one glob (turn
``src/capabilities/*/infrastructure/*`` into ``src/capabilities/*``) and a whole new
capability's domain/application logic drops out of the denominator. ``fail_under`` still
reads 80, the suite is still green, and the layer CLAUDE.md calls "pure Python, no I/O" is
no longer measured at all — green, silent, wrong.

The floor here is CODE-derived, not a second hand list: for every capability under
``src/capabilities/`` that ``.coveragerc`` does not name outright (the single literal,
non-wildcard exclusion — today ``example_feature``, the shipped example — read straight out
of the same ``omit`` list, never hardcoded), walk its ``domain/`` and ``application/`` layers
via ``ast`` and collect every module that defines at least one function. That set is what
"real logic" means structurally: an enum-only file (``domain/enums.py``, the other declared
exception) defines classes but no functions, and is correctly excluded without a second rule
about it. Any file in that set matched by an ``omit`` pattern is the floor's finding.

⚠️ **Coarse is the decision, not a lapse.** This floor works at the capability root: it
catches a NEW capability's logic being wildcard-omitted wholesale. It cannot catch a single
mis-omitted file inside a capability that already has narrower, legitimate exclusions —
closing that gap would mean deriving coverage expectations file-by-file, which is exactly
the fragile, hand-maintained map this gate exists to avoid needing.

A fresh scaffold ships exactly one capability (``example_feature``), which the omit list
already names outright, so the derived "must stay covered" set is empty and this gate has
nothing to check yet. That is the expected result, not a broken detector — the synthetic
probe in the test suite is what proves discovery works before a second capability exists.
"""

import ast
import configparser
import fnmatch
import os
import pathlib
import re
import sys


_COVERAGERC = pathlib.Path(".coveragerc")
_CAPABILITIES = pathlib.Path("src/capabilities")
_SRC = pathlib.Path("src")
_LAYERS = ("domain", "application")

_RE_WHOLE_CAPABILITY = re.compile(r"^src/capabilities/([A-Za-z0-9_]+)/\*$")


def omit_patterns(path_coveragerc: pathlib.Path) -> list[str]:
    """Return the ``[run] omit`` glob patterns declared in ``.coveragerc``.

    Parameters
    ----------
    path_coveragerc : pathlib.Path
        The coverage config to read.

    Returns
    -------
    list of str
        One pattern per non-blank line, in declaration order.
    """
    cls_parser = configparser.ConfigParser()
    cls_parser.read(path_coveragerc, encoding="utf-8")
    str_raw = cls_parser.get("run", "omit", fallback="")
    return [
        os.path.expandvars(str_line.strip())
        for str_line in str_raw.splitlines()
        if str_line.strip()
    ]


def whole_capability_exclusions(list_patterns: list[str]) -> set[str]:
    """Return capability names the omit list excludes wholesale, by literal (non-glob) name.

    Parameters
    ----------
    list_patterns : list of str
        The declared ``omit`` patterns.

    Returns
    -------
    set of str
        Capability directory names named outright, e.g. ``{"example_feature"}``.
    """
    return {
        cls_match.group(1)
        for str_pattern in list_patterns
        if (cls_match := _RE_WHOLE_CAPABILITY.match(str_pattern)) is not None
    }


def defines_a_function(path_module: pathlib.Path) -> bool:
    """Return whether a module defines a function or method anywhere in its AST.

    A class with only attribute assignments (an enum) has none; a class with a method does.
    This is the structural fact that stands in for "carries real behavior" — read from the
    AST, never from the source text.

    Parameters
    ----------
    path_module : pathlib.Path
        The module to inspect.

    Returns
    -------
    bool
        ``True`` when the module defines at least one function or method.
    """
    cls_tree = ast.parse(path_module.read_text(encoding="utf-8"))
    return any(
        isinstance(cls_node, ast.FunctionDef | ast.AsyncFunctionDef)
        for cls_node in ast.walk(cls_tree)
    )


def logic_bearing_modules(path_capability: pathlib.Path) -> list[pathlib.Path]:
    """Return the domain/application modules of one capability that define real behavior.

    Parameters
    ----------
    path_capability : pathlib.Path
        A directory under ``src/capabilities/``.

    Returns
    -------
    list of pathlib.Path
        Modules under ``domain/`` or ``application/`` that define a function, sorted.
    """
    list_modules = []
    for str_layer in _LAYERS:
        path_layer = path_capability / str_layer
        if not path_layer.is_dir():
            continue
        list_modules.extend(
            path_module
            for path_module in sorted(path_layer.rglob("*.py"))
            if defines_a_function(path_module)
        )
    return list_modules


def must_stay_covered(
    path_capabilities: pathlib.Path, set_excluded: set[str]
) -> list[pathlib.Path]:
    """Return every logic-bearing module the omit list has no standing excuse to swallow.

    Parameters
    ----------
    path_capabilities : pathlib.Path
        ``src/capabilities/``.
    set_excluded : set of str
        Capability names the omit list already names outright.

    Returns
    -------
    list of pathlib.Path
        Domain/application modules, across every non-excluded capability, that define a
        function — the code-derived floor.
    """
    list_capabilities = sorted(
        path_capability
        for path_capability in path_capabilities.iterdir()
        if path_capability.is_dir() and path_capability.name not in set_excluded
    )
    return [
        path_module
        for path_capability in list_capabilities
        for path_module in logic_bearing_modules(path_capability)
    ]


def swallowed_by_omit(
    list_must_stay_covered: list[pathlib.Path], list_patterns: list[str]
) -> list[str]:
    """Return one message per module the omit list excludes despite defining real behavior.

    Parameters
    ----------
    list_must_stay_covered : list of pathlib.Path
        The code-derived floor: modules that must stay in the coverage denominator.
    list_patterns : list of str
        The declared ``omit`` patterns.

    Returns
    -------
    list of str
        Human-readable problems; empty when none are swallowed.
    """
    list_problems = []
    for path_module in list_must_stay_covered:
        str_posix = path_module.as_posix()
        str_absolute = path_module.resolve().as_posix()
        list_matched = [
            str_pattern
            for str_pattern in list_patterns
            if fnmatch.fnmatch(str_posix, str_pattern)
            or fnmatch.fnmatch(str_absolute, str_pattern)
        ]
        if list_matched:
            list_problems.append(
                f"{str_posix}: defines a function but is matched by omit pattern "
                f"'{list_matched[0]}' — dropped out of the coverage floor's denominator"
            )
    return list_problems


def vacuous_discovery_reason() -> str | None:
    """Return why discovery would be vacuous, or ``None`` when the inputs are usable.

    Split out of ``main`` so the three "nothing to scan" guards share one return path — a
    gate reporting success after scanning nothing is the exact failure this repo distrusts.

    Returns
    -------
    str or None
        A human-readable reason, or ``None`` when ``.coveragerc`` and ``src/`` are both real.
    """
    if not _COVERAGERC.is_file():
        return f"{_COVERAGERC} not found"
    if not omit_patterns(_COVERAGERC):
        return (
            f"{_COVERAGERC} declares an empty omit list — refusing to report success. "
            f"Either the section moved or discovery is broken."
        )
    if not any(_SRC.rglob("*.py")):
        return f"found ZERO .py files under {_SRC}"
    return None


def main() -> int:
    """Run the gate against the current working directory's ``.coveragerc`` and ``src/``.

    Returns
    -------
    int
        ``0`` when no logic-bearing module is silently omitted, ``1`` otherwise.
    """
    str_reason = vacuous_discovery_reason()
    if str_reason is not None:
        print(f"check_coverage_floor: {str_reason}", file=sys.stderr)
        return 1

    list_patterns = omit_patterns(_COVERAGERC)

    if not _CAPABILITIES.is_dir():
        print(
            "check_coverage_floor: no src/capabilities/ in this tier — nothing for the floor "
            "to check (e.g. the MVC layout has no domain/application split)."
        )
        return 0

    set_excluded = whole_capability_exclusions(list_patterns)
    list_must_stay_covered = must_stay_covered(_CAPABILITIES, set_excluded)
    if not list_must_stay_covered:
        print(
            "check_coverage_floor: 0 non-excluded capabilities carry domain/application "
            "logic yet — expected on a fresh scaffold (only the shipped, already-excluded "
            "example capability exists). This is not a broken detector; see the test suite's "
            "synthetic probe for proof discovery works."
        )
        return 0

    list_problems = swallowed_by_omit(list_must_stay_covered, list_patterns)
    for str_problem in list_problems:
        print(f"❌ {str_problem}", file=sys.stderr)
    if list_problems:
        print(
            f"\n{len(list_problems)} problem(s). Scope the omit pattern to the layer that "
            f"needs it (e.g. .../infrastructure/*), or name the capability outright if the "
            f"whole thing is deliberately excluded.",
            file=sys.stderr,
        )
        return 1

    print(
        f"coverage floor OK: {len(list_must_stay_covered)} domain/application module(s) "
        f"across {len(set(p.parts[2] for p in list_must_stay_covered))} capability(ies) "
        f"stay in the coverage denominator."
    )
    return 0


if __name__ == "__main__":
    for cls_stream in (sys.stdout, sys.stderr):
        if hasattr(cls_stream, "reconfigure"):
            cls_stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
