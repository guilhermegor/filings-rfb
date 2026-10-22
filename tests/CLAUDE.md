# CLAUDE.md — tests/

Conventions for writing tests in this project. Read this before creating or editing any
test file. The goal: an AI (or human) can add a new test module that passes lint and CI on
the first try.

## Layout

```
tests/
  unit/          # fast, isolated tests — mock at I/O boundaries (DB, network, filesystem)
    conftest.py  # shared fixtures (e.g. df_sample)
    test_*.py    # one module per unit under test
  integration/   # tests that touch a real DB/API/filesystem
  performance/   # benchmarks, load, memory
  fixtures/      # pinned oracles — real artifacts, never hand-authored (see below)
```

Run them with `poe unit_tests` or `pytest tests/unit/`.

## Imports

`pytest.ini` sets `pythonpath = . src` — **both** the project root and `src/` are on the
path. For most tests, import the code under test through the `src` package:

```python
from src.view.report_renderer import RenderToExcel
from src.model.example_entity import ExampleEntity
```

### The dual-import-root trap (TypeChecker-guarded classes)

Because both roots are on the path, a module is importable **two** ways — `src.utils.x`
(via the root) and `utils.x` (via `src/`) — and Python treats them as **distinct module
and class objects**. This bites when a `TypeChecker`-guarded class is constructed in a test
and handed *another* src-class instance: if the two are imported via different roots,
`isinstance` fails with the baffling `X must be of type Foo, got Foo` (same name, different
object).

Rule: when a test wires together two src classes and at least one is `TypeChecker`-guarded,
import **both** via the **bare runtime root** — the way the app actually runs:

```python
from utils.paths import resolve_path            # NOT src.utils.paths
from view.report_renderer import RenderToExcel  # NOT src.view.report_renderer
```

The plain `from src.X import …` convention is fine for classes whose constructor takes only
stdlib types / paths (no cross-src instances to `isinstance`-check).

**Measured (blueprintx#290): the `.` on `pythonpath` is removable, and the fix is purely
mechanical.** Dropping `pythonpath = . src` to `pythonpath = src` and stripping the `src.`
prefix from every import in this directory (29 lines across 27 files, including **both**
branches of the `test_typing.py` layout shim — the flush-left sed that fixed the rest misses
its indented `try`/`except` lines) took a scaffolded `ddd-service-native-db` project from 23
collection errors back to a fully green suite — no cross-import defect to untangle, just the
prefix. `mypy.ini` and `.coveragerc` are unaffected: mypy runs from `src/` via a separate
`../mypy.ini` invocation that never reads `pytest.ini`, and coverage attributes lines by file
path, not import alias (confirmed: `TOTAL` read `0/0 100%` before and after — though that
figure can't detect a regression either way, since a fresh scaffold's only non-omitted files
are two empty `__init__.py`s). **Not shipped**: `mvc-service-{native,orm}-db`'s own
`tests/unit/{test_pipeline.py,test_report_renderer.py}` need the identical one-line strip (4
lines, 2 tiers) and were frozen by an unrelated collision at measurement time — land those
together with the `pytest.ini` edit in one pass; a partial rewrite breaks two of five tiers.
Separately: `ddd-service-{native,orm}-db`'s `src/{main.py,app/bootstrap.py}` import `from
src.config.startup import …` as real (non-test) application code, resolved by `bin/run.sh`'s
own `PYTHONPATH=".:src"` — unrelated to this file, but it means the app is not uniformly
`src.`-free at runtime the way the prose above assumes; worth aligning with the bare `from
app.bootstrap import …` line beside it in a later pass.

Order imports as `ruff.toml` enforces (`force-sort-within-sections = true`) — within each
group, `import X` and `from X import Y` are sorted together by module name, stdlib then
third-party then first-party, two blank lines after the import block:

```python
from pathlib import Path

import pandas as pd
import pytest
from pytest_mock import MockerFixture

from src.view.report_renderer import RenderToExcel
```

### Loading a `bin/` script as a module

The gates in `bin/` are scripts, not an importable package, and several have no `.py`-clean
module path. Load one **by path** via `importlib`, never by mutating `sys.path`:

```python
import importlib.util
from pathlib import Path


def load_gate(str_name: str) -> object:
    """Load a bin/ gate by file path so tests import the shipped file itself."""
    path_gate = Path(__file__).parents[2] / "bin" / f"{str_name}.py"
    cls_spec = importlib.util.spec_from_file_location(str_name, path_gate)
    # Both can be None — a missing file, or a loader-less spec. Without this guard the
    # failure is `AttributeError: 'NoneType' has no attribute 'exec_module'`, which names
    # neither the gate nor the path and reads like a bug in the test rather than a renamed
    # or deleted file.
    if cls_spec is None or cls_spec.loader is None:
        raise ImportError(f"cannot load gate from {path_gate}")
    cls_module = importlib.util.module_from_spec(cls_spec)
    cls_spec.loader.exec_module(cls_module)
    return cls_module
```

Importing the file the project actually ships is the point: a copy pasted into `tests/`
passes forever while the shipped gate rots.

## Formatting (must pass `poe lint`)

- **4-space indent** — `ruff.toml` sets `indent-style = "space"`. Let `ruff format` handle
  it; a hand-indented test file is the most common source of drift from this rule.
- **Double quotes** everywhere (`quote-style = "double"`).
- **Type annotations on every function**, including `-> None` on tests and fixtures
  (flake8-annotations is strict).
- **NumPy docstrings** on every test and fixture. **Never** append `, optional` to a
  parameter's type field — write the type exactly as annotated (`tmp_path : pathlib.Path`,
  not `tmp_path : pathlib.Path, optional`); the docstring type checker runs on tests too.

## Structure of a test module

Order a test module as plain helpers (no fixtures), then fixtures (or put shared ones in
`conftest.py`), then the tests. Do not mark the sections with comment banners: a module carries
no comments apart from QA suppressions.

## Test rules

- **Name**: `test_<unit>_<scenario>_<expected_outcome>` — e.g.
  `test_render_missing_parent_dir_creates_it`.
- **A UNIT test has exactly ONE assertion site. An INTEGRATION test has one BEHAVIOUR, and may
  need several.** The split is the rule; it is enforced, not advisory, and
  `bin/check_one_assert.py` is what enforces it (blueprintx#544).

  **Why one assert in `tests/unit/`.** A test with two asserts that goes red does not say which
  behaviour broke — the failure names a line, and the reader has to reconstruct which of two
  claims the code stopped honouring. Worse, the *green* never says which one ran: an assert
  placed after an early `return`, a `raise`, or a `pytest.raises` block is never reached, and
  a passing suite reports that unexecuted claim as proven. One assert per unit test makes the
  red name the behaviour and the green mean exactly one thing.

  **Why `tests/integration/` stays on one behaviour.** An integration test legitimately asserts
  a *sequence* of observable effects: one HTTP call, several consequences (a row written, a
  status returned, a webhook fired). Splitting those re-runs the whole expensive *arrange* to
  prove no new fact. That is the argument the old rule was built on, and it is still correct —
  for that suite. It is not correct for a unit test, where the arrange is cheap and a fixture
  or `parametrize` carries it for free.

  **The measurement is why the split is enforceable rather than aspirational.** Re-measured
  2026-09-20 (AST assertion-site count over `templates/**`, counting `assert`, `assert_*()`
  calls, and `raises`/`warns` context managers — the same counter the gate uses):

  | suite | tests | 0 sites | exactly 1 | **more than 1** |
  |---|---|---|---|---|
  | `tests/unit/` | 828 | 1 | 626 | **201 (24%)** |
  | `tests/integration/` | 68 | 0 | 16 | **52 (76%)** |

  At 24% the unit rule is a real but finishable remediation. At 76% the same rule on
  integration tests would be a wall — and a gate at a threshold nobody pays is a gate nobody
  keeps. (This supersedes blueprintx#429's "554 / 31%" and #431's "188 / 33%"; both are stale,
  do not re-cite them.)

  **Splitting is where this goes wrong.** A mechanical split that copies the *arrange* into N
  near-identical tests is worse than the multi-assert original. Two patterns carry it instead,
  in this order:

  1. **`@pytest.mark.parametrize`** when the asserts are the *same* assertion over different
     inputs or different attributes of one result. One test function, N cases, each named in
     the failure output.
  2. **A scoped fixture** when the asserts are *different* assertions over one expensive
     artifact — see "Expensive shared setup" below. That section is not repealed by this rule;
     it is what makes this rule affordable.

  **The escape hatch, for the unit test that genuinely needs two.** `# one-assert-ok: <reason>`
  anywhere inside the function exempts it; the reason is **required** (a bare marker is
  rejected), same shape as `# complexity-ok:` / `orm-guard-ok:` / `sql-guard-ok:`. Expect it to
  be rare — 76% of unit tests already comply without it.

  **The complexity cap still applies, and a split must not evade it.** `bin/check_complexity.sh`
  caps `tests/` at cyclomatic complexity **1** — the same argument one level up: a test with a
  *branch* tests two paths and the green never says which ran. Reaching one assert by
  introducing a branch (a loop over cases, an `if` selecting the expected value) trades one
  violation for another; `parametrize` is the form that adds cases without adding paths.

  One narrow slice is **not** this gate's job: `assert a and b`, where a failure cannot say
  which half broke, is ruff's `PT018` (0 violations in this tree). Do not re-implement it.
- **Mock at the boundary, not inside business logic.** Patch the filesystem, DB cursor/session,
  HTTP client, or webhook — never the function under test. Use `pytest-mock`'s `mocker`
  (`mocker.patch`, `mocker.patch.object`); use `tmp_path` for real-but-disposable files.
  Stubbing the unit under test tests the caller, not the unit.
- **Mocks must be `spec=`-ed.** The runtime type checker rejects a bare `Mock()` where a typed
  collaborator is expected — `Mock(spec=DatabaseHandler)` is the form that passes, and it is
  also the one that fails when the real class loses the method you are calling.
- **Deterministic.** No real network, no real clock dependence, no unseeded randomness.

### The network guard is not advisory

`tests/conftest.py` ships an **autouse** guard that swaps the `socket` primitives so a real
network call raises `NetworkAccessError`, naming the target and the fix. It is the
deterministic enforcement of "mock at the I/O boundary" — prose is probabilistic, the guard
is not. A test that genuinely must reach the wire opts out with `@pytest.mark.allow_network`
(registered in `pytest.ini`). Reaching for that marker is a design question, not a formality.

## Fixtures are the pinned ORACLE

A fixture under `tests/fixtures/` is not sample data — it is the **oracle** the test is
measured against. Three rules follow, and they are the difference between a suite that can
catch a reader defect and one that cannot.

**1. Generate, never transcribe.** A fixture's expected value must come out of the source
bytes, not out of a person reading the source and typing what they saw. A transcribed
expectation encodes the author's *understanding* of the file, so a reader that shares the
misunderstanding passes. `bin/pin_contract_oracle.py` exists for exactly this: point it at a
downloaded artifact and it emits the `tuple_required` and a header-only fixture.

**2. At least one anti-tautology test.** A test whose expected value the test author wrote
proves the author and the code agree. Pin one assertion against a value **nobody authored** —
a checksum of the real file, a row count from the source, a header extracted by the tool
above. That test is the one that fails when the reader silently changes shape.

**3. Header-only under PII.** When the real artifact carries personal or confidential data,
commit only its **header**. It preserves the encoding, the separator, the column names and
their order — the entire surface a reader parses — and carries no records. There is no
tension between "use the real file" and "commit nothing sensitive"; the header is both.

Two mechanical details that bite:

- **Preserve the encoding and line endings.** A fixture re-saved as UTF-8/LF when the source
  ships ISO-8859-1/CRLF quietly tests a file the producer never sends. `tests/fixtures/` is
  excluded from the whitespace-fixing pre-commit hooks (`^tests/fixtures/`) precisely so the
  bytes survive being committed.
- **Never let a formatter near them.** Same reason.

## Expensive shared setup: render once, share via a scoped fixture

When several tests assert on **different facets of one expensive-to-build artifact** (a
rendered workbook, a built report, a large parsed frame), build it **once** with a
module- or session-scoped fixture instead of rebuilding it per test:

```python
@pytest.fixture(scope="module")
def path_rendered(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Render the report once for the whole module (expensive build shared)."""
    path_out = tmp_path_factory.mktemp("render") / "report.xlsx"
    RenderToExcel().write(df_sample(), path_out)
    return path_out
```

The smell this fixes is "redundant expensive setup masquerading as independent coverage" —
N tests each re-running the same costly build. **Share only when the tests inspect one
artifact**; if a test needs a *different* input/state, give it its own (function-scoped)
fixture. Never share a **mutable** object across tests at module scope (one test's mutation
leaks into the next) — share the immutable result (a path, a frozen frame copy).

## Proving a claim

A green suite is not evidence, and a red one is not either until you check **how** it went
red. Every rule below was paid for by a measurement that contradicted the obvious reading.

### Every gate needs a should-fail test

A gate is a claim that something cannot pass. The only proof is an input that **does** fail
it, asserted in the suite. Without it, a gate that has silently stopped firing — a rotted
glob, a discovery that matches zero files, an exception swallowed — is indistinguishable
from a gate with nothing to find. Assert on the exit code **and** on the message naming the
offending file; "it exited non-zero" also describes a crash.

### A negative control needs a VERIFIED restore

Mutating the tree to prove a test catches the mutation is the standard technique, and both
halves of it fail silently.

- **The restore.** `git checkout -- <tracked> <untracked>` treats the unknown pathspec as
  fatal and **aborts entirely, restoring nothing** — and files added on a feature branch are
  untracked, which is exactly the state these experiments run in. Restore from a
  **pre-mutation snapshot copy** instead, and **re-measure the baseline between mutations**,
  or mutation N+1 runs on a doubly-mutated tree. Measured: an experiment reported 4/11/12
  failures where the true isolated figures were **4/7/1**. Nothing looked wrong, because
  every mutant went red — which IS the outcome being tested for. The `1` was the most
  valuable number in the set: it named a **singular** defence.
- **The mutation itself.** A swap asserted `count(name) == 1`, the name appeared twice, the
  assert raised, **nothing was written**, and the run read `27 passed` — a false "the suite
  does not catch this". A mutation must **print what it changed** ("applied to N
  occurrences"), and a green mutant is believable only after that line has been seen.

### A mutation too coarse cannot isolate the test it targets

When a negative control goes red, check **how**. A mutation that breaks *imports* produces a
**collection error** — a different signal from the assertion you meant to prove fires, and it
masks a test that asserts nothing at all.

- **A test asserting an object's own identity is a tautology.** `assert Cls.__name__ == "Cls"`
  only runs once the import succeeded, so the *import* is the defence and the assertion is
  decoration. Assert over a **collection the code publishes** — `__all__`, a registry, a
  roster — so the test has something to be wrong about.
- **Shrink the mutation until only the target test can fail.** Mutate *one entry of `__all__`*
  rather than renaming a class across four modules. Measured: the rename gave **31 collection
  errors in ~2 s and zero failing assertions**; the shrunk mutation gave **exactly one
  failure, the right one**.
- ⚠️ **Speed is the tell.** A suite that "fails" in 2 s when the baseline takes 30 s did not
  run the tests. Compare **duration and failure TYPE**, never colour.

### A mutant that SURVIVES is a finding — run the whole set, not until the first red

The section above is about mutations that go red for the wrong reason. The opposite outcome is
the one people stop on: a mutant that changes nothing red reads as reassuring and is a **gap
report**. Do not stop at the first mutant that behaves; run one per claim and treat every
survivor as a defect in the suite.

Two survivors, two distinct causes, both measured in one sitting (blueprintx#264):

- **The claim is asserted in one place and implemented in two.** A remedy sentence was printed by
  *two* error branches and only one had a test, so downgrading the other changed nothing. If a
  string, constant or rule appears in N branches, N tests — or hoist it to one constant and test
  that.
- 🔴 **The needle appears twice in one haystack, for unrelated reasons.**
  `assert "full review" in str_problem` passed while the actual command had been downgraded to
  `review`, because the same message ends "…and a full review does not". The assertion was
  satisfied by **explanatory prose** sitting beside the thing under test. This is the tautology
  trap in a form the rule above does not name: not an assertion about the code's own identity,
  but one whose substring is over-available in the text it searches.

  **Assert the most specific form that can still be typed by a user** — the command
  (`@coderabbitai full review`), the flag, the exact key — never a bare noun phrase that ordinary
  surrounding prose could satisfy. When in doubt, mutate and watch it fail before believing it.

### Prove a cosmetic change with a STABLE hash — never `hash()`

For a change meant to alter only presentation (translating comments, reformatting,
re-wrapping), prove the semantic content is identical: parse before and after and compare

```python
import hashlib, json

import yaml


str_digest = hashlib.sha256(
    json.dumps(yaml.safe_load(str_text), sort_keys=True, default=str).encode()
).hexdigest()
```

AST-dump (`ast.dump(ast.parse(...))`) is the equivalent for Python reformats.

🔴 **Never Python's built-in `hash()`.** It is randomised per process (PYTHONHASHSEED, since
3.3), so two `python3 -c` runs disagree on identical input. A before/after recipe built on it
reports a spurious mismatch on **every** run — proving nothing and training you to ignore the
check. Spell the stable form out explicitly in any brief you hand to someone else, because
the shorter word is the one they will reach for.

### Prove a rewrite changed nothing — by digest, over real consumers

A rewrite that must produce identical output is not proven by a green suite. Run every real
consumer against a real artifact under **both** implementations and compare a SHA-256 of the
full serialised result **plus dtypes and row count**, then report it as a count (`18/18
identical`). Shape checks alone are not enough: a dropped repeated element or an unresolved
join leaves row and column counts identical while changing values.

Swap implementations by **file copy with a `trap` restore**, never `git stash`. One process
per run also yields a free peak-RSS figure, so the memory claim is measured rather than
estimated — a rewrite once claimed "constant memory" where measurement showed a ~1.13 GB
floor remained.

## Examples in this folder

- `unit/test_report_renderer.py` — the canonical sample: real-file tests via `tmp_path`,
  a round-trip assertion, and one boundary-mocked test via `mocker`.
- `unit/conftest.py` — the `df_sample` fixture shared across the unit suite.
- `unit/test_family_convention_example.py` — the **introspective-convention** pattern: a rule
  every member of a family must follow gets a test that *discovers* the family from `__all__`
  and asserts the convention on each member, instead of a doc paragraph and a hand-listed set.
  Copy it; delete it if this project has no such family.

## Testing the layers

The layer names differ by skeleton; the rule does not — test the layer that owns the
decision, and mock the one below it at its boundary.

| Skeleton | Layers | Where to put the test |
|---|---|---|
| `mvc-service-*` | `model/`, `view/`, `controller/` | Model against an in-memory engine; view against `tmp_path`; the controller is script-style (side effects on import) — prefer testing model and view directly. |
| `ddd-service-*` | `capabilities/<f>/{domain,application,infrastructure}`, `chassis/` | Domain is pure — unit-test it directly, no mocks needed. Application against a `Mock(spec=…)` of the port. Infrastructure against a real in-memory backend, in `tests/integration/`. |
| `lib-minimal` | `_internal/{utils,config}` | Unit-test the private modules directly; the public surface gets one test that imports a **deep** submodule (a top-level `__init__` compiles even when the package name is malformed). |

For a DB-backed layer: native variants take an in-memory `sqlite3.connect(":memory:")`
connection; ORM variants build `sqlalchemy.create_engine("sqlite://")`. Both are
integration-flavoured — put them in `tests/integration/` if they spin up a real engine.

## Testing shell scripts

A bash script in `bin/` has no conventional unit test, so map the tests-with-every-change rule:

- **Unit gate** = `shellcheck --severity=warning --exclude=SC1091` + `bash -n` (already run by
  `bin/lint_shell.sh` and the `lint-shell` pre-commit hook). When a shell change ships without a
  Python unit test, say so explicitly — it is a documented choice, not an omission.
- **Integration** = invoke the script via `subprocess` and assert observable behaviour (exit
  code, a created file/dir, a status line). Resolve bash with `shutil.which("bash") or "bash"`,
  build a constant trusted argv, scope-ignore bandit `S603` with a one-line reason, and self-skip
  when a dependency is unavailable offline.

⚠️ **Construct the child's environment; never inherit it.** A `subprocess` test that passes
`os.environ` straight through is not testing the script — it is testing the script *plus*
whatever the operator exported. Strip the variables that change a child tool's **output format**
(`FORCE_COLOR`, `CLICOLOR_FORCE`, `NO_COLOR`, `LC_ALL`, `COLUMNS`, `TZ`) and give the runner an
explicit override parameter, so each test states the environment it is testing:

```python
_MAPPING_NO_EXTRA_ENV: Mapping[str, str] = MappingProxyType({})


def _run_gate(path_root: Path, dict_extra: Mapping[str, str] = _MAPPING_NO_EXTRA_ENV) -> ...:
    dict_env = dict(os.environ)
    dict_env.pop("FORCE_COLOR", None)      # unrolled: a loop costs complexity, and tests/ is capped at 1
    dict_env.pop("CLICOLOR_FORCE", None)
    dict_env.pop("NO_COLOR", None)
    dict_env.update(dict_extra)
    return subprocess.run(..., env=dict_env, check=False)
```

Measured (blueprintx#254): nine green subprocess tests for `check_complexity.sh` went **red on a
correct gate** the moment the developer's shell exported `FORCE_COLOR`, because the gate parses
ruff's rendered output and the ANSI escapes reached an arithmetic expansion. The suite's verdict
was a function of the shell, so it could neither catch the defect nor be believed after it was
found. ⚠️ And when a child must not colour its output, **unset the forcing variable** — do not
set the suppressing one: `NO_COLOR=1` does *not* beat `FORCE_COLOR=3` in ruff 0.11.13, so the
obvious fix leaves the defect live behind a green test.

`tests/integration/test_bin_scripts.py` is the shipped reference example (covers the shared
`bin/poetry_exec.sh` and `bin/precommit.sh` seams). See also `bin/CLAUDE.md`.
