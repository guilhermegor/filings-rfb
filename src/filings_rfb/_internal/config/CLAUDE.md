# CLAUDE.md — `_internal/config/`

`config/` is the home of **every private structural declaration** — the shapes and
interfaces the library conforms to. It holds three sub-packages, all under `_internal/`
(they ship inside the wheel but are **not part of the public API** — consumers import the
library's core, never `_internal`):

| Sub-package | Declares | Ships |
|-------------|----------|-------|
| `contracts/` | `FileContract` — the columns an input file must carry | always (drop if the library never reads tabular inputs) |
| `ports/` | private behavioural ABCs (the hexagonal *ports*) | **opt-in** — only when two macro-sections share an operation |
| `schemas/` | direction-neutral Pydantic models, one per external standard | **opt-in** — same condition as `ports/` |

The organising split is **declaration vs machinery**: `config/` answers "*what shape /
interface must this conform to?*"; `_internal/utils/` answers "*how is it done?*" (the engines:
`tabular_reader`, `dtypes`, `typing/`). A `ports/` ABC is a behavioural contract rather than a
pure data declaration, but it still declares a *contract to conform to*, so it lives here beside
`contracts/`, **not** in `utils/`.

⚠️ `ports/` and `schemas/` are an **opt-in tier** — a single-purpose library should carry
**neither** (an interface with one implementation is over-abstraction). This starter ships a
reference `ports/` seam to copy; delete it (and never add `schemas/`) unless the library really
grows two macro-sections over a shared domain.

## The `contracts/` sub-package

A `FileContract` declares the shape an input file (or SQL result) must have: which columns
must be present (`tuple_required`) and which must hold at least one valid CNPJ
(`tuple_cnpj_cols`). It is a **declaration**, not a validator — the validation engine lives
in `_internal/utils/tabular_reader.py` (`read_table` / `read_query` raise `ContractError`
on a violation before types are applied).

- **One contract per file** (`cadastro.py`, `orders.py`, …): a module docstring plus a
  single `FileContract` constant. New input → new file.
- `contracts/__init__.py` re-exports every contract **and** the machinery
  (`FileContract`, `find_file_problems` from `_internal.utils.tabular_reader`), so callers
  use one import: `from <pkg>._internal.config.contracts import EXAMPLE_SOURCE`.
- A contract that constrains nothing is still explicit: `FileContract(name, key, (), ())`.
- **`contracts/` is the ONLY place a `FileContract` is constructed** — statically enforced
  by ruff (`TID251`). Loaders import the instances; they never build one inline.

`EXAMPLE_SOURCE` is a reference instance — copy `example_source.py` per real source and
delete the example once your own contracts exist. Drop this whole sub-package if your
library never reads tabular inputs.

## The `ports/` sub-package (opt-in)

Private behavioural interfaces — the **ports** of hexagonal *ports-and-adapters*. Everything
here is an **abstract contract**, not an implementation; consumers import the concrete adapters,
never `_internal.config.ports`.

A **port** is the abstract operation a family of concrete classes (the **adapters**) all
implement, so callers treat any adapter polymorphically and every new variant conforms to the
same shape. When two macro-sections share one operation (e.g. an `export`, a `read`), name that
operation as a port here; the concrete classes are the adapters.

- **One port per file** (`example_port.py`, `submission_writer.py`, …): a module docstring plus
  a single ABC. New shared operation → new file.
- **`metaclass=ABCTypeCheckerMeta`** on the port gives both abstract-method enforcement (a
  partial adapter fails at instantiation) and runtime type checking of every call.
- **Adapters inherit the port and its metaclass** — never redeclare `metaclass` on a subclass;
  Python inherits it (the `check_typing` hook already skips a class with bases for that reason).
- **Generic over its value** (`Generic[T]`): an adapter narrows the type through the type
  parameter (`class CsvHandler(ExamplePort[pd.DataFrame])`) rather than by re-annotating the
  override, keeping the concrete signature Liskov-compatible.
- `ports/__init__.py` re-exports every port so callers use one import:
  `from <pkg>._internal.config.ports import ExamplePort`.
- Ports stay **private** — never add one to the library's public `__all__`.

`ExamplePort` is a reference — copy `example_port.py` per real shared operation and delete the
example once your own ports exist. Drop this whole sub-package if the library has no
macro-sections sharing a behavioural contract.

## `schemas/` vs `contracts/` — the boundary people get wrong

If you add `schemas/` (opt-in), keep the distinction sharp: a **schema** is a Pydantic model
that mirrors an external **standard** (e.g. the submission XML your library emits) — **schema ↔
structured document**. A **`FileContract`** describes a flat **tabular dump** an ingestion
reader consumes (an open-data CSV of the *same* standard) — **`FileContract` ↔ flat table**. So a
reader that consumes a *different artifact* of a standard your schema already models declares its
**own `FileContract`**; it does **not** reuse the schema. Same domain, two artifacts, two
declarations — both living here under `config/`.
