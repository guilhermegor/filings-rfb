#!/usr/bin/env python3
"""Fail when `main`'s required status checks and the PR jobs drift apart (blueprintx#535).

Default mode needs no token. It compares the committed expected contexts
(.github/required-checks.json, per layer) with the workflow jobs, both directions:

1. a REQUIRED context no unconditional PR job emits -> every PR waits forever;
2. an unconditional PR job that is neither required nor listed in the policy file -> a
   failing gate that cannot block a merge.

Policy data: bin/ci/required_checks_policy.txt, `kind|name|reason` per line, kind being
`optional` (deliberately not required) or `external` (required, emitted by an app or a
dynamic workflow that has no file here). A line without a reason is rejected.

`--live` compares the JSON with the live protection and ruleset API instead (read-only token;
runs only on main). Unreadable API: fail with REQUIRED_CHECKS_SYNC_REQUIRED=1,
skip loudly otherwise. Explanation: docs/required-status-checks.md.
"""

import argparse
import itertools
import json
import os
import pathlib
import re
import subprocess
import sys


try:
    import yaml
except ImportError:
    yaml = None

REPO = "guilhermegor/blueprintx"
PR_TYPES = {"opened", "reopened", "synchronize"}
POLICY_FIELDS = 3
PR_EVENTS = ("pull_request", "pull_request_target")
FILTERS = ("branches", "branches-ignore", "paths", "paths-ignore")
RE_EVENT_CLAUSE = re.compile(r"^github\.event_name\s*(==|!=)\s*'([a-z_]+)'$")


def event_clause_true(str_clause: str) -> bool:
    """Whether a bare `github.event_name ==/!= 'x'` clause holds for a pull_request event."""
    match = RE_EVENT_CLAUSE.match(str_clause.strip())
    if not match:
        return False
    return (match.group(2) == "pull_request") == (match.group(1) == "==")


def if_always_true(str_if: object) -> bool:
    """Return whether a job `if:` holds on a pull_request (a true `||` alternative)."""
    if str_if is None:
        return True
    str_expr = re.sub(r"^\$\{\{\s*(.*?)\s*\}\}$", r"\1", str(str_if).strip(), flags=re.S)
    return any(event_clause_true(c) for c in str_expr.split("||"))


class UnsupportedError(Exception):
    """A workflow shape this gate cannot expand; reported per workflow, never fatal."""


def pr_event_keys(dict_on: object) -> list:
    """Return the pull_request / pull_request_target keys a workflow's `on:` carries."""
    if isinstance(dict_on, str):
        dict_on = {dict_on: None}
    elif isinstance(dict_on, list):
        dict_on = dict.fromkeys(dict_on)
    if not isinstance(dict_on, dict):
        return []
    return [k for k in PR_EVENTS if k in dict_on]


def pr_trigger_unfiltered(dict_on: object) -> bool:
    """Return whether `pull_request` has no filter and `types:` covering new pushes.

    A workflow that only `pull_request_target` triggers is judged but conditional: its checks
    may not attach to the PR head, so it is never classed as running on every PR.
    """
    if isinstance(dict_on, str):
        dict_on = {dict_on: None}
    elif isinstance(dict_on, list):
        dict_on = dict.fromkeys(dict_on)
    return "pull_request" in dict_on and event_unfiltered(dict_on["pull_request"])


def event_unfiltered(dict_event: dict | None) -> bool:
    """One event's config: no filter, and `types:` (a scalar counts as a list) complete."""
    dict_event = dict_event or {}
    if any(k in dict_event for k in FILTERS):
        return False
    list_types = dict_event.get("types")
    if list_types is None:
        return True
    list_types = [list_types] if isinstance(list_types, str) else list_types
    return set(list_types) >= PR_TYPES


def matrix_text(value: object) -> str:
    """Render a matrix value as GitHub renders it (booleans lowercase)."""
    return str(value).lower() if isinstance(value, bool) else str(value)


def expand_name(str_name: str, dict_job: dict) -> list:
    """Job check names; interpolates `${{ matrix.k }}` or appends GitHub's `(v1, v2)`."""
    dict_strategy = dict_job.get("strategy") or {}
    dict_matrix = dict_strategy.get("matrix") if isinstance(dict_strategy, dict) else None
    if dict_matrix is None:
        return [str_name]
    if not isinstance(dict_matrix, dict):
        raise UnsupportedError(f"job '{str_name}': dynamic matrix (fromJSON) is not expandable")
    if "include" in dict_matrix or "exclude" in dict_matrix:
        raise UnsupportedError(f"job '{str_name}': matrix include/exclude is not expandable")
    list_keys = list(dict_matrix)
    if not all(isinstance(dict_matrix[k], list) for k in list_keys):
        raise UnsupportedError(f"job '{str_name}': a non-list matrix dimension is not expandable")
    if "matrix." not in str_name:
        return [
            f"{str_name} ({', '.join(matrix_text(v) for v in t)})"
            for t in itertools.product(*(dict_matrix[k] for k in list_keys))
        ]
    list_names = []
    for tuple_vals in itertools.product(*(dict_matrix[k] for k in list_keys)):
        str_out = str_name
        for str_key, str_val in zip(list_keys, tuple_vals, strict=True):
            str_out = re.sub(
                r"\$\{\{\s*matrix\.%s\s*\}\}".replace("%s", re.escape(str_key)),
                matrix_text(str_val),
                str_out,
            )
        list_names.append(str_out)
    return list_names


def job_flags(str_file: str, dict_job_map: dict, flag_wf: bool) -> dict:
    """{job id: unconditional}; a job that `needs` a conditional job is conditional too."""
    dict_flag = {}
    for str_id, dict_job in dict_job_map.items():
        if "uses" in dict_job:
            raise UnsupportedError(
                f"reusable-workflow job '{str_id}' is unsupported; "
                "add its emitted check names to the policy file by hand"
            )
        dict_flag[str_id] = flag_wf and if_always_true(dict_job.get("if"))
    flag_changed = True
    while flag_changed:
        flag_changed = False
        for str_id, dict_job in dict_job_map.items():
            list_needs = dict_job.get("needs") or []
            list_needs = [list_needs] if isinstance(list_needs, str) else list_needs
            if dict_flag[str_id] and not all(dict_flag.get(n, False) for n in list_needs):
                dict_flag[str_id] = False
                flag_changed = True
    return dict_flag


def load_workflow(path_file: pathlib.Path) -> dict:
    """Parse one workflow file into a dict (empty for an empty file)."""
    return yaml.safe_load(path_file.read_text(encoding="utf-8")) or {}


def job_names(dict_job_map: dict, str_id: str) -> list:
    """Check names one job emits."""
    dict_job = dict_job_map[str_id]
    return expand_name(str(dict_job.get("name", str_id)), dict_job)


def pr_jobs(path_dir: pathlib.Path) -> tuple:
    """Return ({emitted name: unconditional on every PR}, [per-workflow problems])."""
    dict_jobs, list_problems = {}, []
    for path_file in sorted(path_dir.glob("*.y*ml")):
        dict_wf = load_workflow(path_file)
        dict_on = dict_wf.get("on", dict_wf.get(True))
        if not pr_event_keys(dict_on):
            continue
        dict_job_map = dict_wf.get("jobs") or {}
        try:
            dict_flag = job_flags(path_file.name, dict_job_map, pr_trigger_unfiltered(dict_on))
            for str_id in dict_job_map:
                for str_name in job_names(dict_job_map, str_id):
                    dict_jobs[str_name] = dict_jobs.get(str_name, False) or dict_flag[str_id]
        except UnsupportedError as exc:
            list_problems.append(f"{path_file.name}: {exc}")
    return dict_jobs, list_problems


def emitting_files(path_dir: pathlib.Path) -> tuple:
    """Return ({emitted name: {file}}, [per-workflow problems]) over every workflow."""
    dict_files, list_problems = {}, []
    for path_file in sorted(path_dir.glob("*.y*ml")):
        dict_job_map = load_workflow(path_file).get("jobs") or {}
        try:
            for str_id, dict_job in dict_job_map.items():
                if "uses" in dict_job:
                    continue
                for str_name in job_names(dict_job_map, str_id):
                    dict_files.setdefault(str_name, set()).add(path_file.name)
        except UnsupportedError as exc:
            list_problems.append(f"{path_file.name}: {exc}")
    return dict_files, list_problems


def inactive_emitters(set_req: set, dict_files: dict, dict_states: dict) -> list:
    """List required contexts whose emitting workflow file is not `active` in the Actions UI."""
    list_err = []
    for str_name in sorted(set_req & set(dict_files)):
        for str_file in sorted(dict_files[str_name]):
            str_state = dict_states.get(str_file, "missing")
            if str_state != "active":
                list_err.append(
                    f"required '{str_name}' is emitted by {str_file}, state {str_state}"
                )
    return list_err


def read_policy(path_file: pathlib.Path) -> dict:
    """{kind: {name: reason}}; a malformed or reason-less line aborts."""
    dict_policy = {"optional": {}, "external": {}}
    for int_no, str_line in enumerate(path_file.read_text(encoding="utf-8").splitlines(), 1):
        if not str_line.strip() or str_line.lstrip().startswith("#"):
            continue
        list_parts = [p.strip() for p in str_line.split("|", 2)]
        if (
            len(list_parts) != POLICY_FIELDS
            or list_parts[0] not in dict_policy
            or not list_parts[2]
        ):
            sys.exit(
                f"::error file={path_file},line={int_no}::need `optional|external|name|reason`"
            )
        if any(list_parts[1] in dict_policy[k] for k in dict_policy):
            sys.exit(
                f"::error file={path_file},line={int_no}::duplicate or conflicting "
                f"policy line for '{list_parts[1]}'"
            )
        dict_policy[list_parts[0]][list_parts[1]] = list_parts[2]
    return dict_policy


def gh_json(str_path: str) -> object:
    """Return the parsed JSON of one `gh api` call."""
    str_out = subprocess.run(  # noqa: S603 - fixed argv, no shell; str_path is a repo-controlled endpoint
        ["gh", "api", str_path],  # noqa: S607 - gh is resolved from PATH on purpose
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(str_out)


def classic_required() -> set:
    """Read classic contexts from the public branch view; an unreadable one raises."""
    dict_prot = gh_json(f"repos/{REPO}/branches/main")["protection"]
    if not dict_prot["enabled"]:
        return set()
    return set(dict_prot["required_status_checks"]["contexts"])


def live_required() -> dict:
    """{"classic": set, "ruleset": set} read from the API (the rules in effect on main)."""
    dict_live = {"classic": classic_required(), "ruleset": set()}
    for dict_rule in gh_json(f"repos/{REPO}/rules/branches/main"):
        if dict_rule["type"] == "required_status_checks":
            list_chk = dict_rule["parameters"]["required_status_checks"]
            dict_live["ruleset"] |= {c["context"] for c in list_chk}
    return dict_live


def live_workflow_states() -> dict:
    """{workflow file name: state} as the Actions API reports it, every page."""
    dict_states = {}
    int_page = 1
    while list_wf := gh_json(f"repos/{REPO}/actions/workflows?per_page=100&page={int_page}")[
        "workflows"
    ]:
        for dict_wf in list_wf:
            dict_states[pathlib.PurePosixPath(dict_wf["path"]).name] = dict_wf["state"]
        int_page += 1
    return dict_states


def read_expected(path_file: pathlib.Path) -> dict:
    """Read the committed {"classic": set, "ruleset": set}; any other shape aborts."""
    dict_raw = json.loads(path_file.read_text(encoding="utf-8"))
    if set(dict_raw) != {"classic", "ruleset"}:
        sys.exit(f"::error file={path_file}::need exactly the keys classic and ruleset")
    return {k: set(v) for k, v in dict_raw.items()}


def compare_live(dict_exp: dict, dict_live: dict) -> list:
    """Per layer, the contexts the JSON and the live settings disagree on."""
    list_err = []
    for str_layer in ("classic", "ruleset"):
        for str_name in sorted(dict_exp[str_layer] - dict_live[str_layer]):
            list_err.append(f"{str_layer}: in required-checks.json, not live: {str_name}")
        for str_name in sorted(dict_live[str_layer] - dict_exp[str_layer]):
            list_err.append(f"{str_layer}: live, not in required-checks.json: {str_name}")
    return list_err


def compare(set_req: set, dict_jobs: dict, dict_policy: dict) -> list:
    """Every finding, as a message; empty means in sync."""
    list_err = []
    set_always = {n for n, f in dict_jobs.items() if f}
    for str_name in sorted(set_req - set_always - set(dict_policy["external"])):
        list_err.append(f"required but no unconditional PR job emits it: {str_name}")
    for str_name in sorted(set_always - set_req - set(dict_policy["optional"])):
        list_err.append(f"runs on every PR, not required, not in the policy file: {str_name}")
    for str_name in sorted(set(dict_policy["optional"]) - set_always):
        list_err.append(f"policy `optional` entry names no unconditional PR job: {str_name}")
    for str_name in sorted(set(dict_policy["external"]) - set_req):
        list_err.append(f"policy `external` entry is not required: {str_name}")
    return list_err


def live_read() -> dict:
    """Live layers plus the workflow states, under one key each."""
    dict_live = live_required()
    dict_live["states"] = live_workflow_states()
    return dict_live


def read_or_skip(args: argparse.Namespace) -> tuple:
    """Return (expected, live-or-None, exit code or None); the API is read only under --live."""
    try:
        if yaml is None:
            raise ValueError("PyYAML is not installed")
        dict_exp = read_expected(pathlib.Path(args.expected))
        return dict_exp, (live_read() if args.live else None), None
    except (OSError, subprocess.CalledProcessError, KeyError, ValueError) as exc:
        if os.environ.get("REQUIRED_CHECKS_SYNC_REQUIRED") == "1":
            print(f"::error::cannot read ({exc}); failing closed", file=sys.stderr)
            return None, None, 1
        print(f"SKIPPED (loudly): cannot read ({exc}). Nothing was checked.")
        return None, None, 0


def check_required_list(args: argparse.Namespace) -> int:
    """Generated-project mode: every name in a plain list must be emitted unconditionally."""
    if yaml is None:
        print("::error::PyYAML is not installed", file=sys.stderr)
        return 1
    list_lines = pathlib.Path(args.required_list).read_text(encoding="utf-8").splitlines()
    set_req = {s.strip() for s in list_lines if s.strip() and not s.lstrip().startswith("#")}
    dict_jobs, list_problems = pr_jobs(pathlib.Path(args.workflows))
    list_err = list_problems + compare(
        set_req,
        dict_jobs,
        {"optional": {n: "" for n, f in dict_jobs.items() if f}, "external": {}},
    )
    for str_msg in list_err:
        print(f"::error::{str_msg}", file=sys.stderr)
    print(f"findings={len(list_err)}")
    return 1 if list_err else 0


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflows", default=".github/workflows")
    parser.add_argument("--policy", default="bin/ci/required_checks_policy.txt")
    parser.add_argument("--expected", default=".github/required-checks.json")
    parser.add_argument("--live", action="store_true", help="compare the JSON with the API")
    parser.add_argument(
        "--required-list",
        help="generated-project mode: bin/required-checks.txt; only direction 1 is checked",
    )
    args = parser.parse_args()
    if args.required_list:
        return check_required_list(args)
    dict_exp, dict_live, int_rc = read_or_skip(args)
    if int_rc is not None:
        return int_rc
    if args.live:
        dict_files, list_problems = emitting_files(pathlib.Path(args.workflows))
        list_err = (
            compare_live(dict_exp, dict_live)
            + inactive_emitters(
                dict_exp["classic"] | dict_exp["ruleset"],
                dict_files,
                dict_live["states"],
            )
            + list_problems
        )
    else:
        dict_jobs, list_problems = pr_jobs(pathlib.Path(args.workflows))
        list_err = list_problems + compare(
            dict_exp["classic"] | dict_exp["ruleset"],
            dict_jobs,
            read_policy(pathlib.Path(args.policy)),
        )
    for str_msg in list_err:
        print(f"::error::{str_msg}", file=sys.stderr)
    print(f"findings={len(list_err)}")
    return 1 if list_err else 0


if __name__ == "__main__":
    sys.exit(main())
