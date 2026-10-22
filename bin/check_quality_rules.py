"""Validate ``quality-rules.yaml`` against the templates it claims to describe (blueprintx#432).

THE DEFECT THIS GATE EXISTS FOR. Cross-language quality parity today lives only in the head
of whoever remembers it — the measured cost is blueprintx#430: TypeScript carried **zero** of
the six quality gates Python already had, discovered only by a human noticing. A registry file
fixes the "nobody remembers" half. It does nothing for the OTHER half — a registry that ages
out of sync with the tools it describes is worse than no registry, because it reads as
authoritative. This gate is what keeps it honest, the same relationship
``check_codespell_sync.sh`` has to the two copies of ``.codespellrc``.

WHAT THIS GATE CAN AND CANNOT DECIDE (the split is the whole design — see
``docs/quality-rules.md``'s own table):

- **Decidable:** every language ``templates/*/skeleton.meta`` declares has an entry for every
  rule (a missing language is an error, never a silent omission); a ``status:
  not-implemented``/``overridden_by:`` entry carries a non-empty ``note``; a declared
  ``file``/``pattern`` pair actually appears in the real config file.
- **Not decidable, and this gate does not pretend to be:** whether two differently-worded rules
  in two languages prohibit the *same construct*, or whether a rule missing from one language
  *should* exist there. Both stay review questions — a hand-rolled semantic comparator here
  would be exactly the "gate promises more than it can check" defect the issue opens by naming.

``pattern`` IS A PLAIN SUBSTRING, NOT A REGEX. The registry's own entries would need heavy
double-escaping to embed a regex inside a YAML double-quoted scalar parsed by a hand-rolled
reader (this file avoids a PyYAML dependency the same way ``check_gate_integrity.py`` avoids
one for workflow YAML) — a substring match is exactly as decidable for "does the file still
say what the table claims" and costs no escaping.

WHY A HAND-ROLLED PARSER. ``quality-rules.yaml`` uses a small, fixed, self-authored subset (a
top-level list of ``- id: <x>`` items, each with flat scalar keys plus at most one level of
nested language blocks) — not general YAML. Reading it with a restricted line-based parser
keeps this gate dependency-free, matching every sibling in this file (``check_function_length``,
``check_gate_integrity``, ``check_docs_code_refs``) — none of them carries a PyYAML dependency
either, and CI's job for each installs nothing beyond ``python3`` itself.

ZERO IS A LEGITIMATE STATE HERE. ``quality-rules.yaml`` lives only at BlueprintX's own root —
it describes cross-language parity across *templates*, which a single-language generated
project has no concept of. This file still ships into every scaffolded project's ``bin/``
(``templates/python-common/`` is copied verbatim), so it self-skips there rather than treating
absence as a discovery-glob bug — the same asymmetry ``check_docs_code_refs.py``'s own header
documents for a project that ships no docs.
"""

import pathlib
import re
import sys


PATH_ROOT = pathlib.Path(__file__).resolve().parent.parent

SET_VALID_STATUSES = frozenset({"not-implemented"})

_RE_TOP_ID = re.compile(r"^- id:\s*(\S+)\s*$")
_RE_KEY2 = re.compile(r"^ {2}(\w+):\s*(.*)$")
_RE_KEY4 = re.compile(r"^ {4}(\w+):\s*(.*)$")
_RE_ITEM6 = re.compile(r"^ {6}- (.+)$")
_RE_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$")
_RE_SLUG_STRIP = re.compile(r"[^a-z0-9\s-]")
_RE_SLUG_SPACE = re.compile(r"[\s]+")


class RegistryError(Exception):
    """Raised when the registry holds content this restricted parser cannot consume.

    Silently skipping an unrecognised line is what made a valid-looking
    ``- id: rule # comment`` parse to nothing, leaving ``main`` to check zero rules
    and report success (blueprintx#503).
    """


def slugify(str_text: str) -> str:
    """Return a heading's markdown-anchor slug (mkdocs-material / python-markdown's algorithm).

    Parameters
    ----------
    str_text : str
        Heading text, e.g. ``"Function length"``.

    Returns
    -------
    str
        Lowercase, non-``[a-z0-9 -]`` characters stripped, whitespace collapsed to single
        hyphens — e.g. ``"function-length"``.
    """
    str_lower = str_text.lower()
    str_stripped = _RE_SLUG_STRIP.sub("", str_lower)
    return _RE_SLUG_SPACE.sub("-", str_stripped.strip())


def heading_slugs(path_md: pathlib.Path) -> set:
    """Return every markdown heading's anchor slug in a doc file.

    Parameters
    ----------
    path_md : pathlib.Path
        The markdown file to scan.

    Returns
    -------
    set of str
        Empty when the file does not exist.
    """
    if not path_md.is_file():
        return set()
    set_slugs = set()
    for str_line in path_md.read_text(encoding="utf-8").splitlines():
        cls_match = _RE_HEADING.match(str_line)
        if cls_match:
            set_slugs.add(slugify(cls_match.group(1)))
    return set_slugs


_INT_MIN_QUOTED_LEN = 2

_RE_TRAILING_COMMENT = re.compile(r"(?:^|\s)#.*$")


def _parse_scalar(str_raw: str) -> str:
    r"""Return a registry value's decoded text — a bare token or a double-quoted string.

    Parameters
    ----------
    str_raw : str
        Raw text following ``key:``.

    Returns
    -------
    str
        The decoded scalar. A double-quoted value has ``\"``/``\\`` unescaped; a bare
        token is returned stripped, unchanged.
    """
    str_raw = str_raw.strip()
    if str_raw[:1] == '"' and str_raw[-1:] == '"' and len(str_raw) >= _INT_MIN_QUOTED_LEN:
        return str_raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    str_uncommented = _RE_TRAILING_COMMENT.sub("", str_raw)
    return str_uncommented.strip()


def _meaningful_lines(path_yaml: pathlib.Path) -> list:
    """Return a registry file's lines with blanks and full-line comments removed.

    Parameters
    ----------
    path_yaml : pathlib.Path
        The registry file.

    Returns
    -------
    list of str
        Lines in original order, indentation preserved.
    """
    return [
        str_line
        for str_line in path_yaml.read_text(encoding="utf-8").splitlines()
        if str_line.strip() and not str_line.lstrip().startswith("#")
    ]


def _apply_line(dict_rule: dict, tuple_state: tuple, str_line: str) -> tuple:
    """Fold one registry line into the rule dict being built; return the parser state.

    Parameters
    ----------
    dict_rule : dict
        The rule currently being assembled — mutated in place.
    tuple_state : tuple
        ``(str_lang_key, str_list_key)`` carried between lines: the nested language block
        currently open (``""`` at top level), and the list key currently accepting items
        (``""`` when no list is open).
    str_line : str
        One non-blank, non-comment source line.

    Returns
    -------
    tuple
        The ``(str_lang_key, str_list_key)`` still open after this line — unchanged unless
        this line opened or closed a nested ``python:``/``typescript:`` block or a list.
    """
    str_lang_key, str_list_key = tuple_state

    cls_item = _RE_ITEM6.match(str_line)
    if cls_item and str_lang_key and str_list_key:
        dict_rule[str_lang_key][str_list_key].append(_parse_scalar(cls_item.group(1)))
        return (str_lang_key, str_list_key)

    cls_k4 = _RE_KEY4.match(str_line)
    if cls_k4 and str_lang_key:
        str_key, str_val = cls_k4.group(1), cls_k4.group(2)
        if str_val:
            dict_rule[str_lang_key][str_key] = _parse_scalar(str_val)
            return (str_lang_key, "")
        dict_rule[str_lang_key][str_key] = []
        return (str_lang_key, str_key)

    cls_k2 = _RE_KEY2.match(str_line)
    if not cls_k2:
        raise RegistryError(f"unparsable line: {str_line!r}")
    str_key, str_val = cls_k2.group(1), cls_k2.group(2)
    if str_val:
        dict_rule[str_key] = _parse_scalar(str_val)
        return ("", "")
    dict_rule[str_key] = {}
    return (str_key, "")


def parse_registry(path_yaml: pathlib.Path) -> list:
    """Parse ``quality-rules.yaml``'s restricted subset into one dict per rule.

    Parameters
    ----------
    path_yaml : pathlib.Path
        The registry file.

    Returns
    -------
    list of dict
        Each dict carries ``id`` plus whatever top-level and nested-language keys the
        file declared. Empty when the file has no ``- id:`` entries.
    """
    list_rules = []
    dict_rule = None
    tuple_state = ("", "")
    for str_line in _meaningful_lines(path_yaml):
        cls_top = _RE_TOP_ID.match(str_line)
        if cls_top:
            dict_rule = {"id": cls_top.group(1)}
            list_rules.append(dict_rule)
            tuple_state = ("", "")
            continue
        if dict_rule is None:
            raise RegistryError(f"content before the first '- id:' entry: {str_line!r}")
        tuple_state = _apply_line(dict_rule, tuple_state, str_line)
    if not list_rules:
        raise RegistryError("no rules parsed — the registry is empty or unreadable")
    return list_rules


def discovered_languages(path_root: pathlib.Path) -> set:
    """Return every ``language=`` value declared across ``templates/*/skeleton.meta``.

    Mirrors ``bin/blueprintx.sh``'s own discovery (``prompt_language``) — the set of
    languages a rule must cover.

    Parameters
    ----------
    path_root : pathlib.Path
        The BlueprintX repo root.

    Returns
    -------
    set of str
        Empty when no skeleton is discoverable at this root — a generated project, for
        instance, which is not a defect (see the module docstring).
    """
    set_languages = set()
    for path_meta in sorted(path_root.glob("templates/*/skeleton.meta")):
        for str_line in path_meta.read_text(encoding="utf-8").splitlines():
            if str_line.startswith("language="):
                set_languages.add(str_line.split("=", 1)[1].strip())
    return set_languages


def language_coverage_problems(list_rules: list, set_languages: set) -> list:
    """Return findings for a rule missing a declared, non-empty ``tool``/``rule`` entry.

    Parameters
    ----------
    list_rules : list of dict
        Parsed registry entries.
    set_languages : set of str
        Every language a rule must cover (:func:`discovered_languages`).

    Returns
    -------
    list of str
        One message per rule/language combination with no usable entry.
    """
    list_problems = []
    for dict_rule in list_rules:
        str_id = dict_rule.get("id", "?")
        for str_lang in sorted(set_languages):
            dict_entry = dict_rule.get(str_lang)
            bool_covered = isinstance(dict_entry, dict) and (
                bool(dict_entry.get("tool") and dict_entry.get("rule"))
                or dict_entry.get("status") in SET_VALID_STATUSES
                or bool(dict_entry.get("overridden_by"))
            )
            if not bool_covered:
                list_problems.append(
                    f"{str_id}: no {str_lang!r} entry (needs tool+rule, "
                    f"status: {'/'.join(sorted(SET_VALID_STATUSES))}, or overridden_by) — "
                    f"a rule missing a language is an error, not an omission "
                    f"(blueprintx#430)"
                )
    return list_problems


def reason_required_problems(list_rules: list) -> list:
    """Return findings for a ``status``/``overridden_by`` entry with no ``note``.

    Parameters
    ----------
    list_rules : list of dict
        Parsed registry entries.

    Returns
    -------
    list of str
        One message per language entry declaring an escape hatch with no reason —
        matching this repo's ``# complexity-ok: <reason>`` convention: the reason is
        required, never a bare marker.
    """
    list_problems = []
    for dict_rule in list_rules:
        str_id = dict_rule.get("id", "?")
        for str_lang, dict_entry in dict_rule.items():
            if not isinstance(dict_entry, dict):
                continue
            bool_hatch = bool(dict_entry.get("status") or dict_entry.get("overridden_by"))
            if bool_hatch and not dict_entry.get("note"):
                list_problems.append(f"{str_id}: {str_lang!r} status/overridden_by with no note")
    return list_problems


def _declared_patterns(dict_entry: dict) -> list:
    """Return every config assertion an entry declares, single or multiple.

    One `pattern:` checked only one value per entry, so the other documented ceilings in
    the same file (tests/bin, the .tsx length, detectObjects) could drift with nothing
    reporting it — the registry asserted one number and vouched for four (blueprintx#503).

    Parameters
    ----------
    dict_entry : dict
        One language block.

    Returns
    -------
    list of str
        ``patterns:`` items plus any single ``pattern:``; empty when the entry declares
        a file but no assertion, which checks only that the file exists.
    """
    list_patterns = [str_p for str_p in dict_entry.get("patterns", []) if str_p]
    str_single = dict_entry.get("pattern", "")
    if str_single:
        list_patterns.append(str_single)
    return list_patterns


def config_pattern_problems(list_rules: list, path_root: pathlib.Path) -> list:
    """Return findings where a declared ``file``/``pattern`` no longer matches reality.

    Parameters
    ----------
    list_rules : list of dict
        Parsed registry entries.
    path_root : pathlib.Path
        The BlueprintX repo root — ``file`` is resolved relative to it.

    Returns
    -------
    list of str
        One message per missing file or absent pattern — the check that stops this
        table from lying about a config it claims to describe.
    """
    list_problems = []
    for dict_rule in list_rules:
        str_id = dict_rule.get("id", "?")
        for str_lang, dict_entry in dict_rule.items():
            if not isinstance(dict_entry, dict) or not dict_entry.get("file"):
                continue
            path_file = path_root / dict_entry["file"]
            if not path_file.is_file():
                list_problems.append(
                    f"{str_id}: {str_lang!r} file not found: {dict_entry['file']}"
                )
                continue
            str_text = path_file.read_text(encoding="utf-8")
            for str_pattern in _declared_patterns(dict_entry):
                if str_pattern not in str_text:
                    list_problems.append(
                        f"{str_id}: {str_lang!r} pattern {str_pattern!r} not found in "
                        f"{dict_entry['file']} — the registry and the real config have drifted"
                    )
    return list_problems


def docs_anchor_problems(list_rules: list, path_root: pathlib.Path) -> list:
    """Return findings for a ``docs:`` reference whose anchor does not resolve.

    Parameters
    ----------
    list_rules : list of dict
        Parsed registry entries.
    path_root : pathlib.Path
        The BlueprintX repo root.

    Returns
    -------
    list of str
        One message per rule with a missing/malformed ``docs:`` field or an anchor
        absent from the target file's headings.
    """
    list_problems = []
    dict_cache = {}
    for dict_rule in list_rules:
        str_id = dict_rule.get("id", "?")
        str_docs = dict_rule.get("docs", "")
        if "#" not in str_docs:
            list_problems.append(f"{str_id}: docs field missing or malformed: {str_docs!r}")
            continue
        str_path, str_anchor = str_docs.split("#", 1)
        if str_path not in dict_cache:
            dict_cache[str_path] = heading_slugs(path_root / str_path)
        if str_anchor not in dict_cache[str_path]:
            list_problems.append(f"{str_id}: docs anchor {str_anchor!r} not found in {str_path}")
    return list_problems


def structure_problems(list_rules: list) -> list:
    """Return findings for a rule missing a required top-level field.

    Parameters
    ----------
    list_rules : list of dict
        Parsed registry entries.

    Returns
    -------
    list of str
        One message per rule with an empty ``intent`` — the field the issue names as
        "what makes the file worth it": the prohibited construct, not a number to copy.
    """
    return [
        f"{dict_rule.get('id', '?')}: empty or missing 'intent'"
        for dict_rule in list_rules
        if not dict_rule.get("intent")
    ]


def apply_root_flag(list_argv: list) -> bool:
    """Parse a leading ``--root <dir>`` flag, updating ``PATH_ROOT`` in place.

    Parameters
    ----------
    list_argv : list of str
        The raw argv tail.

    Returns
    -------
    bool
        ``False`` on bad usage (already reported to stdout).
    """
    global PATH_ROOT  # noqa: PLW0603 — same documented seam as check_docs_code_refs.py
    if list_argv[:1] != ["--root"]:
        return True
    if len(list_argv) < 2:  # noqa: PLR2004
        print("❌ --root needs a directory")
        return False
    PATH_ROOT = pathlib.Path(list_argv[1]).resolve()
    return True


def main(list_argv: list) -> int:
    """Validate ``quality-rules.yaml`` against the templates and docs it describes.

    Parameters
    ----------
    list_argv : list of str
        ``["--root", <dir>]`` to check a tree other than this file's own project, else empty.

    Returns
    -------
    int
        0 when clean, or when this ``--root`` ships no ``quality-rules.yaml`` at all (a
        generated project — a legitimate state, see the module docstring); 1 on any finding.
    """
    if not apply_root_flag(list_argv):
        return 1

    path_yaml = PATH_ROOT / "quality-rules.yaml"
    if not path_yaml.is_file():
        print("No quality-rules.yaml at this root — skipping quality-rules check.")
        return 0

    try:
        list_rules = parse_registry(path_yaml)
    except RegistryError as cls_error:
        print(f"quality-rules.yaml: {cls_error}")
        print("\n1 finding(s) in quality-rules.yaml.")
        return 1
    set_languages = discovered_languages(PATH_ROOT)
    list_problems = [
        *structure_problems(list_rules),
        *language_coverage_problems(list_rules, set_languages),
        *reason_required_problems(list_rules),
        *config_pattern_problems(list_rules, PATH_ROOT),
        *docs_anchor_problems(list_rules, PATH_ROOT),
    ]

    for str_problem in list_problems:
        print(str_problem)
    if list_problems:
        print(f"\n{len(list_problems)} finding(s) in quality-rules.yaml.")
        return 1

    print(
        f"✅ quality-rules OK ({len(list_rules)} rule(s), "
        f"{len(set_languages)} language(s): {', '.join(sorted(set_languages)) or '—'})"
    )
    return 0


if __name__ == "__main__":
    for cls_stream in (sys.stdout, sys.stderr):
        if hasattr(cls_stream, "reconfigure"):
            cls_stream.reconfigure(encoding="utf-8", errors="replace")

    sys.exit(main(sys.argv[1:]))
