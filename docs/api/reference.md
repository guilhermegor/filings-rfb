# **API Reference**

Public interface for this library.

> **See also:** [Usage](../usage.md)

---

## Module: `main`

Entry point module. Extend this with your library's public functions.

### `main() -> None`

Runs the library entry point. Replace the body with your top-level logic.

```python
from <package_name>.main import main

main()
```

---

## Module: `filings_rfb.ingestion.cnpj.companies`

### `read_companies(str_month, int_chunk_rows=500_000, path_workdir=None) -> Iterator[pd.DataFrame]`

Yields the `Empresas` rows of a reference month (`YYYY-MM`), one typed DataFrame per chunk of
each part 0-9. `capital_social` is an exact `Decimal`. Raises `FileNotFoundError` when a part is
not published.

### `export_companies_parquet(str_month, path_dest, int_chunk_rows=500_000, path_workdir=None) -> Path`

Writes the same rows to one Parquet file. Requires the `filings-rfb[parquet]` extra and raises an
`ImportError` naming it otherwise.

---

## Adding new modules

Place new modules under `src/<package_name>/`. Export public symbols from `src/<package_name>/__init__.py` so callers can do:

```python
from <package_name> import my_function
```

Follow the one-class-per-file convention: utility functions with no shared state belong at module level, not wrapped in a class.

---

## Conventions

| Convention | Rule |
|------------|------|
| Type hints | Required on all public functions, including `-> None` return types |
| Docstrings | NumPy style; explain *why*, not *what* |
| Variable names | Type-prefixed (`str_`, `list_`, `cls_`, `dict_`, …) |
| Testing | `unittest`; one assertion per test; name as `test_<unit>_<scenario>_<expected>` |
