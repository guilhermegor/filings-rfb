"""Enforce the canonical docs skeleton — English file slugs + nav registration.

Docs rot **structurally** before they rot factually: a canonical page is deleted, a new page
never reaches ``mkdocs.yml`` ``nav:`` (MkDocs still *builds* it — it just vanishes from
navigation, which is how a page silently goes missing), or a page family drifts apart heading by
heading. This gate catches all three mechanically, and is wired into both
``.pre-commit-config.yaml`` and ``.github/workflows/tests.yaml`` (gate parity).

It enforces the **invariant, never the prose**:

- **Layer 1 — the skeleton (fully language-agnostic).** Every canonical page must exist under
  ``docs/`` **and** be registered in ``nav:``. The canonical set is keyed on **English file slugs**
  (``index.md``, ``usage.md``, ``api/index.md``, …), never on the nav *title* — the title is
  localized (``Início``, ``Referência da API``, …) and this gate must not look at it.
- **Layer 2 — per-page sections (optional, repo-owned).** A page family (e.g. ``api/*.md``) may be
  required to carry the same headings. The gate is generic; the **section labels are repo config**
  — declared in ``docs/.docs-skeleton.yaml`` in the repo's own language — so a non-English project
  overrides the labels once and the mechanism is untouched. Absent that file, Layer 2 is skipped.

Docs prose language follows ``mkdocs.yml`` ``theme.language`` (a single-sourced declaration);
everything contributor/machine-facing (code, commits, CI output, bot PR comments) stays English
regardless. That rule is documented in ``docs/CLAUDE.md``; this gate only enforces structure.

Every finding is a hard error (exit 1).
"""

import fnmatch
import pathlib
import sys

import yaml


_DEFAULT_REQUIRED_PAGES = (
    "index.md",
    "usage.md",
    "examples.md",
    "api/index.md",
    "faq.md",
    "contributing.md",
    "changelog.md",
)

_DOCS_DIR = pathlib.Path("docs")
_MKDOCS_YML = pathlib.Path("mkdocs.yml")
_SKELETON_CONFIG = _DOCS_DIR / ".docs-skeleton.yaml"


class _MkDocsSafeLoader(yaml.SafeLoader):
    """SafeLoader that tolerates MkDocs' custom ``!!python/name:`` tags (returns ``None``).

    ``mkdocs.yml`` embeds ``!!python/name:...`` tags (e.g. pymdownx emoji generators) that a plain
    ``SafeLoader`` rejects. We only need ``nav`` and ``theme.language``, so unknown tags resolve to
    ``None`` rather than failing the parse.
    """


def _ignore_unknown(loader: _MkDocsSafeLoader, tag_suffix: str, node: yaml.Node) -> None:  # noqa: ARG001
    """Resolve any unknown YAML tag to ``None`` (see :class:`_MkDocsSafeLoader`).

    Parameters
    ----------
    loader : _MkDocsSafeLoader
        The active loader.
    tag_suffix : str
        The unresolved tag suffix.
    node : yaml.Node
        The node carrying the unknown tag.

    Returns
    -------
    None
        Always ``None`` — the value is irrelevant to this gate.
    """


_MkDocsSafeLoader.add_multi_constructor("tag:yaml.org,2002:python/name:", _ignore_unknown)
_MkDocsSafeLoader.add_multi_constructor("!", _ignore_unknown)


def _nav_files(nav: object) -> set[str]:
    """Collect every ``.md`` file path registered anywhere in a (possibly nested) ``nav`` tree.

    Parameters
    ----------
    nav : object
        The parsed ``nav`` value (a list of str / dict, arbitrarily nested).

    Returns
    -------
    set of str
        Every doc path referenced in the nav, normalised with forward slashes.
    """
    set_files: set[str] = set()
    if isinstance(nav, str):
        set_files.add(nav)
    elif isinstance(nav, list):
        for item in nav:
            set_files |= _nav_files(item)
    elif isinstance(nav, dict):
        for value in nav.values():
            set_files |= _nav_files(value)
    return set_files


def _load_config() -> dict:
    """Return the repo's docs-skeleton override (``{}`` when the file is absent).

    Returns
    -------
    dict
        The parsed ``docs/.docs-skeleton.yaml`` (``required_pages`` /
        ``section_families``), or an empty dict when the repo ships no override.
    """
    if not _SKELETON_CONFIG.exists():
        return {}
    return yaml.safe_load(_SKELETON_CONFIG.read_text(encoding="utf-8")) or {}


def _check_layer1(set_nav_files: set[str], tuple_required: tuple[str, ...]) -> list[str]:
    """Return errors for canonical pages that are missing on disk or absent from ``nav:``.

    Parameters
    ----------
    set_nav_files : set of str
        Every doc path registered in ``mkdocs.yml`` ``nav:``.
    tuple_required : tuple of str
        The canonical English slugs that must exist and be navigable.

    Returns
    -------
    list of str
        One message per violation.
    """
    list_errors: list[str] = []
    for str_slug in tuple_required:
        if not (_DOCS_DIR / str_slug).is_file():
            list_errors.append(f"❌ canonical page missing on disk: docs/{str_slug}")
        if str_slug not in set_nav_files:
            list_errors.append(
                f"❌ canonical page not registered in mkdocs.yml nav: {str_slug} "
                f"(MkDocs builds it anyway, so it silently vanishes from navigation)"
            )
    return list_errors


def _headings(path_md: pathlib.Path) -> set[str]:
    """Return the set of Markdown heading texts in a page (``#``-prefixed lines, stripped).

    Parameters
    ----------
    path_md : pathlib.Path
        The Markdown file to scan.

    Returns
    -------
    set of str
        Heading texts with the leading ``#`` markers and surrounding ``*`` stripped.
    """
    set_headings: set[str] = set()
    for str_line in path_md.read_text(encoding="utf-8").splitlines():
        if str_line.lstrip().startswith("#"):
            set_headings.add(str_line.lstrip("#").strip().strip("*").strip())
    return set_headings


def _check_layer2(dict_families: dict) -> list[str]:
    """Return errors for pages in a declared family that lack a required section heading.

    Parameters
    ----------
    dict_families : dict
        ``{glob: [heading, ...]}`` from the repo's ``docs/.docs-skeleton.yaml``
        (repo-owned labels).

    Returns
    -------
    list of str
        One message per page missing a required heading.
    """
    list_errors: list[str] = []
    for str_glob, list_required in (dict_families or {}).items():
        for path_md in sorted(_DOCS_DIR.glob("**/*.md")):
            str_rel = path_md.relative_to(_DOCS_DIR).as_posix()
            if not fnmatch.fnmatch(str_rel, str_glob):
                continue
            set_have = _headings(path_md)
            for str_heading in list_required:
                if str_heading not in set_have:
                    list_errors.append(
                        f"❌ docs/{str_rel}: family '{str_glob}' requires "
                        f"a '{str_heading}' section"
                    )
    return list_errors


def main() -> int:
    """Run both layers over the project's docs; return 1 on any violation.

    Returns
    -------
    int
        0 when the docs skeleton is intact, 1 otherwise.
    """
    if not _MKDOCS_YML.exists():
        print("No mkdocs.yml — skipping docs-skeleton check.")
        return 0
    dict_mkdocs = (
        yaml.load(
            _MKDOCS_YML.read_text(encoding="utf-8"),
            Loader=_MkDocsSafeLoader,  # noqa: S506 — SafeLoader-derived, see the comment above
        )
        or {}
    )
    set_nav_files = _nav_files(dict_mkdocs.get("nav"))
    dict_config = _load_config()
    tuple_required = tuple(dict_config.get("required_pages") or _DEFAULT_REQUIRED_PAGES)
    list_errors = _check_layer1(set_nav_files, tuple_required)
    list_errors += _check_layer2(dict_config.get("section_families") or {})
    for str_error in list_errors:
        print(str_error)
    return 1 if list_errors else 0


if __name__ == "__main__":
    for cls_stream in (sys.stdout, sys.stderr):
        if hasattr(cls_stream, "reconfigure"):
            cls_stream.reconfigure(encoding="utf-8", errors="replace")

    sys.exit(main())
