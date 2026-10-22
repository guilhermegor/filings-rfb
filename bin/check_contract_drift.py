"""Weekly, non-gating drift check: whether each contract still matches its live source.

The second half of the oracle discipline (`config/CLAUDE.md` → "Pin every contract to a
source-published oracle"). A pinned fixture proves the contract matched **the day it was written**;
only re-fetching the live source can catch the source changing it *afterwards*. This driver does
exactly that — and **never fails**. It compares each contract's columns against the current header
and reports drift; the surrounding workflow turns a report into an *issue*, never a red check.

Why never fail: a network test contradicts the socket-blocking `conftest` guard, "the source is
down" and "our contract is wrong" are indistinguishable as a failed check, and an external host on
a gating path has silently skipped a release before. So this always exits 0 — it is a *reporter*,
not a gate. It **self-skips to success** when `config/contract_oracles.yaml` lists no sources.

Run online only (it is wired into the scheduled `contract_drift.yaml` workflow, never into PR/push
CI). Reads the registry, re-fetches each source's header through the one `http_downloader` seam,
writes a Markdown report to ``contract_drift_report.md`` (empty when there is no drift), and prints
a summary.
"""

import pathlib
import sys
import tempfile


sys.path.insert(0, "src")

import yaml  # noqa: E402 — after the sys.path bootstrap above

from config import contracts as contracts_module  # noqa: E402
from utils.http_downloader import download_file  # noqa: E402
from utils.tabular_reader import FileContract  # noqa: E402, TID251


_REGISTRY_PATH = pathlib.Path("src/config/contract_oracles.yaml")
_REPORT_PATH = pathlib.Path("contract_drift_report.md")
_DEFAULT_TIMEOUT_SECONDS = 60


def load_registry() -> dict:
    """Return the ``oracles`` mapping from the registry file (empty when unset/absent).

    Returns
    -------
    dict
        ``{source_key: {"url", "sep", "encoding"}}`` — empty when no sources are configured.
    """
    if not _REGISTRY_PATH.exists():
        return {}
    dict_doc = yaml.safe_load(_REGISTRY_PATH.read_text(encoding="utf-8")) or {}
    return dict_doc.get("oracles") or {}


def contracts_by_source_key() -> dict:
    """Index every ``FileContract`` declared in ``config.contracts`` by its ``str_source_key``.

    Returns
    -------
    dict
        ``{str_source_key: FileContract}`` for each contract instance re-exported
        by the package.
    """
    dict_index = {}
    for str_name in dir(contracts_module):
        obj = getattr(contracts_module, str_name)
        if isinstance(obj, FileContract):
            dict_index[obj.str_source_key] = obj
    return dict_index


def live_header(dict_entry: dict) -> tuple[str, ...]:
    """Download the source artifact and return its current header columns.

    Parameters
    ----------
    dict_entry : dict
        A registry entry with ``url`` and optional ``sep`` / ``encoding``.

    Returns
    -------
    tuple of str
        The live header's columns, stripped.
    """
    str_sep = dict_entry.get("sep", ";")
    str_encoding = dict_entry.get("encoding", "utf-8-sig")
    int_timeout_s = int(dict_entry.get("timeout_s", _DEFAULT_TIMEOUT_SECONDS))
    with tempfile.TemporaryDirectory() as str_tmp:
        path_art = download_file(
            dict_entry["url"], pathlib.Path(str_tmp) / "artifact", int_timeout_s
        )
        with path_art.open(encoding=str_encoding) as fh:
            for str_line in fh:
                if str_line.strip():
                    return tuple(cell.strip() for cell in str_line.rstrip("\n").split(str_sep))
    return ()


def drift_for_source(
    cls_contract: FileContract, dict_entry: dict
) -> tuple[list[str] | None, list[str]]:
    """Return ``(drift_lines, note_lines)`` for one source — notes are logged, never reported.

    ⚠️ ``drift_lines`` is ``None`` when the source could **not be checked**, and ``[]`` when it
    was checked and matched. Returning ``[]`` for both is the defect this signature exists to
    prevent: the caller then prints its all-clear line for a comparison that never happened —
    a reporting job announcing its own blindness as a clean bill of health, which is precisely
    the failure this job exists to catch in someone else's data. Measured elsewhere: a source
    outage printed ``no layout drift detected``.

    The two directions are **not** symmetric:

    - **A required column vanished from the source is ALWAYS drift** — the read would raise.
    - **"the source has a column the contract doesn't list" is drift ONLY when the contract
      claims completeness** (``bool_full_column``). ``tuple_required`` means "must contain at
      least these", so a deliberate *subset* contract (require the keys, let the rest flow
      through) legitimately omits most columns; flagging them reports every non-required column
      as a finding. A job that cries wolf on its first run is worse than no job.

    A fetch failure is **not** drift either (the source may be down, or the artifact for the
    current period may not be published yet), so it becomes a *note* — logged for the operator,
    kept out of the report that opens an issue.

    Parameters
    ----------
    cls_contract : FileContract
        The shipped contract to check.
    dict_entry : dict
        The source's registry entry.

    Returns
    -------
    tuple of (list of str or None, list of str)
        ``(drift_lines, note_lines)`` — ``None`` drift lines mean the source was unreachable
        and nothing was compared; ``[]`` means checked and clean. Drift lines open/update the
        issue; note lines only log.
    """
    try:
        tuple_live = live_header(dict_entry)
    except Exception as cls_err:  # noqa: BLE001 — see below
        return None, [
            f"could not fetch {dict_entry.get('url')}: "
            f"{type(cls_err).__name__}: {cls_err} (NOT checked — not drift either)"
        ]
    set_live = set(tuple_live)
    set_contract = set(cls_contract.tuple_required)
    list_lines: list[str] = []
    for str_removed in sorted(set_contract - set_live):
        list_lines.append(f"➖ contract requires column the source dropped: `{str_removed}`")
    if cls_contract.bool_full_column:
        for str_added in sorted(set_live - set_contract):
            list_lines.append(
                f"➕ source added column not in the full-column contract: `{str_added}`"
            )
    return list_lines, []


def build_report(dict_registry: dict, dict_contracts: dict) -> tuple[str, list[str], list[str]]:
    """Assemble the drift report and the log-only notes across all configured sources.

    Parameters
    ----------
    dict_registry : dict
        The ``oracles`` mapping.
    dict_contracts : dict
        ``{source_key: FileContract}``.

    Returns
    -------
    tuple of (str, list of str, list of str)
        The Markdown report body (``""`` when every checked contract still matches its source),
        the note lines (logged, never opening an issue), and the keys of the sources that were
        **not checked at all**. The third element is the one that keeps an empty report from
        being read as an all-clear.
    """
    list_sections: list[str] = []
    list_notes: list[str] = []
    list_skipped: list[str] = []
    for str_key, dict_entry in dict_registry.items():
        cls_contract = dict_contracts.get(str_key)
        if cls_contract is None:
            list_sections.append(
                f"### `{str_key}`\n\n⚠️ no FileContract with this source_key in config/contracts/."
            )
            continue
        list_lines, list_entry_notes = drift_for_source(cls_contract, dict_entry)
        list_notes.extend(f"{str_key}: {note}" for note in list_entry_notes)
        if list_lines is None:
            list_skipped.append(str_key)
            continue
        if list_lines:
            list_sections.append(
                f"### `{str_key}`\n\n" + "\n".join(f"- {ln}" for ln in list_lines)
            )
    return "\n\n".join(list_sections), list_notes, list_skipped


def main() -> int:
    """Run the drift check and write the report. Always returns 0 (reporter, never a gate).

    Returns
    -------
    int
        Always 0 — drift is reported via the written file, never via a non-zero exit.
    """
    dict_registry = load_registry()
    if not dict_registry:
        print("No oracles configured in config/contract_oracles.yaml — skipping drift check.")
        _REPORT_PATH.write_text("", encoding="utf-8")
        return 0
    str_report, list_notes, list_skipped = build_report(dict_registry, contracts_by_source_key())
    _REPORT_PATH.write_text(str_report, encoding="utf-8")
    for str_note in list_notes:
        print(f"note: {str_note}")
    if str_report:
        print("Contract drift detected:\n")
        print(str_report)
    if list_skipped:
        print(
            f"SKIPPED: {len(list_skipped)} of {len(dict_registry)} source(s) could not be "
            f"checked — {', '.join(sorted(list_skipped))}. This run proves nothing about them."
        )
    elif not str_report:
        print("No contract drift — every contract still matches its source.")
    return 0


if __name__ == "__main__":
    for cls_stream in (sys.stdout, sys.stderr):
        if hasattr(cls_stream, "reconfigure"):
            cls_stream.reconfigure(encoding="utf-8", errors="replace")

    sys.exit(main())
