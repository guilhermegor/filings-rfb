"""Report files this project's template tier ships that this project never received.

Scaffolding is a one-shot copy (blueprintx#109): adding a file to ``templates/<tier>/`` (or
the shared ``templates/python-common/``) protects only projects generated AFTER that commit.
No existing project is ever compared against the template it came from, so a fix landing in
the template silently never reaches a project scaffolded before it — forever, unless someone
remembers to backfill it by hand. Two independent real cases motivated this: a network-block
``conftest.py`` guard and a ``.codespellrc`` skip pattern, both missing from a downstream
project scaffolded before either was added to ``templates/python-common/``.

Shape: PRESENCE-ONLY, deliberately, not a content diff. A project's own legitimate local
changes are not drift — only a file/tool the template ships that the project simply does not
have. This is the cheap, high-signal, low-false-positive half of the drift question; the two
real cases above are both absence. A content-diff check on files a project should never
customise (the shared ``bin/check_*.py`` gates, ``.pre-commit-config.yaml`` hook ids) is a
real follow-on but needs a notion of "not meant to be edited locally" this module does not
attempt — a check that fires on legitimate local edits gets disabled the first week it is
noisy, the same "a number nobody pays is a gate nobody keeps" reasoning that set the ``bin/``
complexity ceiling.

Reporter, not a gate — like ``check_contract_drift.py`` in this same directory (read its
header first; the reasoning is identical). Drift in a downstream project is not that
project's fault on the day it is detected: a template gaining a fix after a project was
scaffolded and a source dropping a column are the same shape, something changed on a
DIFFERENT clock than the one CI is checking. So this always exits 0.

What it needs to run: a BLUEPRINTX CHECKOUT (``--blueprintx-root``, or
``BLUEPRINTX_TEMPLATE_ROOT`` in the environment) — nothing here vendors a second copy of the
template tree. Absent one, it self-skips LOUDLY (prints why, never a silent pass) — the same
contract ``check_actions.sh`` documents for its own missing tool. Absent a provenance stamp
(``.blueprintx-provenance.yaml``, written at scaffold time by
``bin/lib/scaffold_provenance.sh::scaffold_stamp_provenance``) it also self-skips
loudly: that is the path BlueprintX's OWN tree always takes (not a scaffolded project, no
tier — ``--root .`` here never falls through to a comparison), and the path any project
scaffolded before this feature shipped takes too.

What the stamp is used for: ``tier`` and ``review_bot_roster`` are READ and select what to
compare. ``blueprintx_version`` and ``blueprintx_commit`` are NOT read; they are provenance
for a human. The comparison is always against the checkout's CURRENT template, never the
stamped commit: comparing against the stamped commit would need that commit's history and
would answer "what did this project start with", while this check asks what the template
has gained since.

The required-path set is DERIVED, not a hand-maintained second list: the checkout's
``bin/lib/scaffold_python_templates.sh --list-copies`` dry-runs the one shared step every
service tier's scaffold calls and prints the copies it would make, so this check reads the
scaffold's own output instead of parsing its source, and cannot drift from what it copies.
Deliberately scoped to ``templates/python-common/`` and ``templates/common/`` sources, not
the tier-specific ``templates/<tier>/src/`` (each ``bin/scaffold/python_*.sh`` copies that
with its own logic) — a narrower, honest MVP over a wider check that would risk false
positives on conditional tier files it cannot see.
"""

import argparse
import os
import pathlib
import posixpath
import shutil
import subprocess
import sys


_PROVENANCE_FILENAME = ".blueprintx-provenance.yaml"
_SCAFFOLD_LIB_RELPATH = pathlib.Path("bin/lib/scaffold_python_templates.sh")
_COMMON_TEMPLATE_RELPATH = pathlib.Path("templates/python-common")
_TIERS_OUTSIDE_SHARED_LIB = frozenset({"lib-minimal"})
_INT_COPY_FIELDS = 4
_INT_RM_FIELDS = 2


def read_tier(path_root: pathlib.Path) -> str | None:
    """Return the ``tier:`` value stamped in the project's provenance file, or ``None``.

    Parameters
    ----------
    path_root : pathlib.Path
        The project root to inspect.

    Returns
    -------
    str or None
            The stamped tier name, or ``None`` when there is no provenance stamp at all.
    """
    path_stamp = path_root / _PROVENANCE_FILENAME
    if not path_stamp.exists():
        return None
    for str_line in path_stamp.read_text(encoding="utf-8").splitlines():
        str_stripped = str_line.strip()
        if str_stripped.startswith("tier:"):
            return str_stripped.split(":", 1)[1].strip()
    return None


def review_bot_roster_enabled(path_root: pathlib.Path) -> bool | None:
    """Return the ``review_bot_roster:`` choice stamped at scaffold time, or ``None``.

    Provenance recorded only tier/version/commit/timestamp, so the drift checker could not
    recover an opt-out and had to guess. It now records the choice; ``None`` means the
    project predates the stamp, and the caller must not assume either answer.

    Parameters
    ----------
    path_root : pathlib.Path
        The project root to inspect.

    Returns
    -------
    bool or None
            The stamped choice, or ``None`` when the stamp is absent or silent on it.
    """
    path_stamp = path_root / _PROVENANCE_FILENAME
    if not path_stamp.exists():
        return None
    for str_line in path_stamp.read_text(encoding="utf-8").splitlines():
        str_stripped = str_line.strip()
        if str_stripped.startswith("review_bot_roster:"):
            return str_stripped.split(":", 1)[1].strip().lower() in {"true", "yes", "y", "1"}
    return None


def _template_roots(path_blueprintx_root: pathlib.Path) -> list[pathlib.Path]:
    """Return the template directories whose copies the drift check polices.

    Parameters
    ----------
    path_blueprintx_root : pathlib.Path
        Root of a BlueprintX checkout.

    Returns
    -------
    list of pathlib.Path
            ``templates/python-common`` and the language-agnostic ``templates/common``.
    """
    return [
        path_blueprintx_root / _COMMON_TEMPLATE_RELPATH,
        path_blueprintx_root / "templates/common",
    ]


def _dry_run_lines(
    path_blueprintx_root: pathlib.Path, str_tier: str, bool_roster: bool
) -> list[str] | None:
    """Run the checkout's scaffold lib in ``--list-copies`` mode and return its stdout lines.

    This sources and executes shell from ``path_blueprintx_root``, so that checkout has the
    same trust level as running the scaffolder itself.

    Parameters
    ----------
    path_blueprintx_root : pathlib.Path
        Root of a BlueprintX checkout.
    str_tier : str
        The tier whose copy list to print.
    bool_roster : bool
        Whether the review-bot roster was opted into (it gates one copy).

    Returns
    -------
    list of str or None
            The output lines, or ``None`` when the lib is missing, bash is missing, or the
            dry run failed — the caller treats that as SKIPPED, never as "nothing required".
    """
    path_lib = path_blueprintx_root / _SCAFFOLD_LIB_RELPATH
    str_bash = shutil.which("bash")
    if not path_lib.exists() or str_bash is None:
        return None
    dict_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    list_argv = [str_bash, str(path_lib), "--list-copies", "--tier", str_tier]
    list_argv += ["--roster", "true" if bool_roster else "false"]
    cls_run = subprocess.run(  # noqa: S603
        list_argv,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=dict_env,
    )
    return cls_run.stdout.splitlines() if cls_run.returncode == 0 else None


def _parse_dry_run(list_lines: list[str]) -> tuple[list[tuple[str, str, str]], set[str]]:
    """Split ``--list-copies`` output into copies and removals.

    Parameters
    ----------
    list_lines : list of str
        Output lines: ``COPY<TAB>file|dir<TAB>src<TAB>dst`` and ``RM<TAB>dst``.

    Returns
    -------
    tuple of (list of tuple of str, set of str)
            ``(kind, source relative to the checkout, project-relative destination)`` per
            copy, and the project-relative paths the scaffold deletes after copying.
    """
    list_copies: list[tuple[str, str, str]] = []
    set_removed: set[str] = set()
    for str_line in list_lines:
        list_fields = str_line.split("\t")
        if list_fields[0] == "COPY" and len(list_fields) == _INT_COPY_FIELDS:
            list_copies.append((list_fields[1], list_fields[2], list_fields[3]))
        elif list_fields[0] == "RM" and len(list_fields) == _INT_RM_FIELDS:
            set_removed.add(list_fields[1])
    return list_copies, set_removed


def _copy_destinations(
    path_blueprintx_root: pathlib.Path,
    tuple_copy: tuple[str, str, str],
    dict_tracked: dict[pathlib.Path, set[str]],
) -> set[str]:
    """Return the project-relative paths one dry-run copy delivers, or none if out of scope.

    A directory source delivers every tracked file under it. A file source is dropped only
    when it exists but git does not track it (a draft matched by a shell glob is not a
    template file); with no git answer every existing file counts as tracked.

    Parameters
    ----------
    path_blueprintx_root : pathlib.Path
        Root of a BlueprintX checkout.
    tuple_copy : tuple of str
        ``(kind, source, destination)`` from the dry run.
    dict_tracked : dict of pathlib.Path to set of str
        Tracked files per policed template root, relative to that root.

    Returns
    -------
    set of str
            Project-relative destinations; empty when the source is outside the policed roots.
    """
    str_kind, str_src, str_dst = tuple_copy
    path_src = path_blueprintx_root / str_src
    for path_root, set_tracked in dict_tracked.items():
        if not path_src.is_relative_to(path_root):
            continue
        if str_kind == "dir":
            return {
                posixpath.join(str_dst, str_rel)
                for str_rel in _template_files(path_blueprintx_root, path_src)
            }
        bool_draft = (
            path_src.exists() and path_src.relative_to(path_root).as_posix() not in set_tracked
        )
        return set() if bool_draft else {str_dst}
    return set()


def required_relpaths(
    path_blueprintx_root: pathlib.Path, str_tier: str, bool_roster: bool = False
) -> set[str]:
    """Derive every python-common-sourced path a scaffold of ``str_tier`` copies.

    Read from the lib's ``--list-copies`` dry run rather than hand-listed or parsed out of
    shell source, so a copy written in any shell form is seen. Copies guarded by the
    review-bot roster flag are present exactly when ``bool_roster`` is true, because the dry
    run evaluates the guard with that value.

    Parameters
    ----------
    path_blueprintx_root : pathlib.Path
        Root of a BlueprintX checkout.
    str_tier : str
        The project's stamped tier.
    bool_roster : bool
        Whether the project opted into the review-bot roster.

    Returns
    -------
    set of str
            Project-relative paths (POSIX separators) the shared scaffold step copies.
            Empty when the dry run could not be made — the caller treats that as SKIPPED,
            never as "nothing is required".
    """
    list_lines = _dry_run_lines(path_blueprintx_root, str_tier, bool_roster)
    if list_lines is None:
        return set()
    list_copies, set_removed = _parse_dry_run(list_lines)
    dict_tracked = {
        path_root: set(_template_files(path_blueprintx_root, path_root))
        for path_root in _template_roots(path_blueprintx_root)
        if path_root.is_dir()
    }
    set_required: set[str] = set()
    for tuple_copy in list_copies:
        set_required |= _copy_destinations(path_blueprintx_root, tuple_copy, dict_tracked)
    return {str_rel for str_rel in set_required if not _is_removed(str_rel, set_removed)}


def _is_removed(str_rel: str, set_removed: set[str]) -> bool:
    """Return whether the scaffold ``rm``s this destination, or a directory above it.

    Parameters
    ----------
    str_rel : str
        A project-relative destination.
    set_removed : set of str
        Project-relative paths the scaffold deletes after copying.

    Returns
    -------
    bool
            ``True`` when ``str_rel`` never survives a scaffold.
    """
    str_rel = posixpath.normpath(str_rel)
    return any(
        str_rel == str_rm or str_rel.startswith(f"{str_rm}/")
        for str_rm in map(posixpath.normpath, set_removed)
    )


def _template_files(path_blueprintx_root: pathlib.Path, path_dir: pathlib.Path) -> list[str]:
    """List the template files under ``path_dir``, relative to it.

    Tracked files only when the checkout is a git repo: an untracked artifact (a log, an
    editor swap file) is not a template file and would be a permanent false "missing".
    Falls back to a walk that skips ``__pycache__`` when git cannot answer.

    Parameters
    ----------
    path_blueprintx_root : pathlib.Path
        Root of the BlueprintX checkout.
    path_dir : pathlib.Path
        The template directory to list.

    Returns
    -------
    list of str
            POSIX paths relative to ``path_dir``.
    """
    dict_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        cls_git = subprocess.run(  # noqa: S603
            ["git", "-C", str(path_blueprintx_root), "ls-files", "-z", "--", str(path_dir)],  # noqa: S607, E501
            capture_output=True,
            check=False,
            env=dict_env,
        )
    except FileNotFoundError:
        cls_git = None
    str_out = cls_git.stdout.decode() if cls_git else ""
    list_tracked = [str_f for str_f in str_out.split("\0") if str_f]
    if cls_git and cls_git.returncode == 0 and list_tracked:
        path_rel_dir = path_dir.relative_to(path_blueprintx_root)
        return [pathlib.Path(str_f).relative_to(path_rel_dir).as_posix() for str_f in list_tracked]
    return [
        path_f.relative_to(path_dir).as_posix()
        for path_f in sorted(path_dir.rglob("*"))
        if path_f.is_file() and "__pycache__" not in path_f.parts
    ]


def missing_relpaths(path_root: pathlib.Path, set_required: set[str]) -> list[str]:
    """Return the required paths that do not exist under the project root, sorted.

    Parameters
    ----------
    path_root : pathlib.Path
        The project root to check.
    set_required : set of str
        Project-relative paths the template ships.

    Returns
    -------
    list of str
            Sorted relative paths present in the template but absent from the project.
    """
    return sorted(str_rel for str_rel in set_required if not (path_root / str_rel).exists())


def _parse_args(list_argv: list) -> tuple[pathlib.Path, pathlib.Path | None]:
    """Parse ``--root`` and ``--blueprintx-root`` out of argv, with env-var fallbacks.

    Parameters
    ----------
    list_argv : list of str
        Raw CLI arguments (``sys.argv[1:]``).

    Returns
    -------
    tuple of (pathlib.Path, pathlib.Path or None)
            The project root (defaults to cwd) and the BlueprintX checkout root (defaults to
            ``BLUEPRINTX_TEMPLATE_ROOT`` in the environment, or ``None`` when unset).
    """
    cls_parser = argparse.ArgumentParser(description="Report template drift.")
    cls_parser.add_argument("--root", default=None)
    cls_parser.add_argument(
        "--blueprintx-root", default=os.environ.get("BLUEPRINTX_TEMPLATE_ROOT")
    )
    cls_args = cls_parser.parse_args(list_argv)
    path_root = pathlib.Path(cls_args.root).resolve() if cls_args.root else pathlib.Path.cwd()
    path_blueprintx = (
        pathlib.Path(cls_args.blueprintx_root).resolve() if cls_args.blueprintx_root else None
    )
    return path_root, path_blueprintx


def _report_missing(str_tier: str, list_missing: list, int_total: int) -> None:
    """Print the drift report body for a non-empty ``list_missing``.

    Parameters
    ----------
    str_tier : str
        The project's stamped tier name.
    list_missing : list of str
        Sorted relative paths the template ships that the project lacks.
    int_total : int
        How many paths were required in total (for the trailing summary line).

    Returns
    -------
    None
    """
    print(
        f"Template drift detected for tier '{str_tier}' — the template ships these paths and "
        f"this project does not have them:\n"
    )
    for str_rel in list_missing:
        print(f"➖ {str_rel}")
    print(
        f"\n{len(list_missing)} of {int_total} required path(s) missing. This is a REPORT, not "
        f"a gate — a project may have removed one of these on purpose; a human decides whether "
        f"to backfill it."
    )


def main(list_argv: list) -> int:
    """Report template drift for the project at ``--root``. Always returns 0 (a reporter).

    Parameters
    ----------
    list_argv : list of str
        CLI arguments (``sys.argv[1:]``).

    Returns
    -------
    int
            Always 0 — see the module docstring for why this never gates.
    """
    path_root, path_blueprintx = _parse_args(list_argv)

    str_tier = read_tier(path_root)
    if str_tier is None:
        print(
            f"SKIPPED: no {_PROVENANCE_FILENAME} at {path_root} — nothing to check. Either this "
            f"tree was not scaffolded by BlueprintX (this repo, run over itself, always takes "
            f"this path), or it predates provenance stamping (blueprintx#109). This run proves "
            f"nothing about drift."
        )
        return 0

    if path_blueprintx is None or not path_blueprintx.exists():
        print(
            f"SKIPPED: tier is '{str_tier}' but no BlueprintX checkout is available to compare "
            f"against — pass --blueprintx-root or set BLUEPRINTX_TEMPLATE_ROOT. This run proves "
            f"nothing about drift."
        )
        return 0

    if str_tier in _TIERS_OUTSIDE_SHARED_LIB:
        print(
            f"SKIPPED: tier '{str_tier}' copies files through its own scaffold script, not "
            f"{_SCAFFOLD_LIB_RELPATH}, so there is no required list to compare against. This "
            f"run proves nothing about drift."
        )
        return 0

    set_required = required_relpaths(
        path_blueprintx, str_tier, bool(review_bot_roster_enabled(path_root))
    )
    if not set_required:
        print(
            f"SKIPPED: found no required paths under {path_blueprintx} — "
            f"{_SCAFFOLD_LIB_RELPATH} is missing there, or its --list-copies dry run failed or "
            f"printed nothing (bash is also required). This run proves nothing about drift, "
            f"and is NOT the same as a clean comparison."
        )
        return 0

    list_missing = missing_relpaths(path_root, set_required)
    if not list_missing:
        print(f"No template drift detected — {len(set_required)} required path(s) present.")
        return 0

    _report_missing(str_tier, list_missing, len(set_required))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
