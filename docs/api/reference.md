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

## Module: `filings_rfb.ingestion.cnpj.establishments`

### `read_establishments(str_month, int_chunk_rows=500_000, path_workdir=None) -> Iterator[pd.DataFrame]`

Yields the `Estabelecimentos` rows of a reference month (`YYYY-MM`), one typed DataFrame per chunk
of each part 0-9. Adds `cnpj_completo` (basic + order + check digits) and `cnpj_valido`
(check-digit validation, alphanumeric-aware). The three date columns are `datetime.date`, with
`00000000` and empty as null; `cnae_fiscal_secundaria` stays comma-separated text. Raises
`FileNotFoundError` when a part is not published.

---

## Module: `filings_rfb.ingestion.cnpj.partners`

### `read_partners(str_month, int_chunk_rows=500_000, path_workdir=None) -> Iterator[pd.DataFrame]`

Yields the `Socios` rows of a reference month, one typed DataFrame per chunk of each part 0-9.
`documento_socio` is verbatim (RFB pre-masks an individual's CPF as `***dddddd**`; it is never
unmasked). `documento_representante` is null where RFB published `***000000**` (no
representative). `qualificacao_socio` and `qualificacao_representante` are two-character text
codes that join to the `Qualificacoes` lookup. Raises `FileNotFoundError` when a part is not
published.

---

## Module: `ingestion.cnpj.lookups`

Reads the six RFB CNPJ lookup tables: `Cnaes`, `Motivos`, `Municipios`, `Naturezas`, `Paises`
and `Qualificacoes` (the partner/representative qualification, i.e. role).

### `CNPJ_LOOKUP_NAMES: tuple[str, ...]`

The six table names `read_lookup` accepts.

### `read_lookup(str_table, path_zip, str_url, str_etag) -> pd.DataFrame`

Reads one downloaded lookup ZIP. The archive must hold exactly one file member, whatever its
name; the member is a headerless, `;`-separated, quoted `latin-1` CSV of `code;description`.

| Parameter | Meaning |
|-----------|---------|
| `str_table` | One of `CNPJ_LOOKUP_NAMES` |
| `path_zip` | The archive on disk |
| `str_url` | The URL it was fetched from (stamped as `url`) |
| `str_etag` | The share's `ETag` for it (stamped as `source_etag`) |

Returns `code` and `description` as text (leading zeros are kept), followed by the provenance
columns (`url`, `updated_at`, `source_key`, `package_version`, `ingestion_run_id`,
`content_hash`) and `source_etag`.

Raises `ValueError` for an unknown table or an archive with zero or several file members, and
`ContractError` for a row that is not exactly two fields.

---

## Module: `filings_rfb.ingestion.cnpj.simples`

### `read_simples(str_month, int_chunk_rows=500_000, path_workdir=None) -> Iterator[pd.DataFrame]`

Yields the `Simples` rows (Simples Nacional and MEI options) of a reference month (`YYYY-MM`),
one typed DataFrame per chunk. `Simples.zip` is one un-numbered archive, read through the same
shared iterator as the numbered datasets (`part_index` is always 0). `opcao_pelo_simples` and
`opcao_pelo_mei` are booleans (`S`/`N`; anything else raises `ValueError`); the four date
columns are `datetime.date`, with the RFB's `00000000` sentinel read as null. Raises
`FileNotFoundError` when `Simples.zip` is not published.

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
