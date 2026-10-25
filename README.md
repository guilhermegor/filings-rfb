<!-- readme-archetype: library -->
# filings-rfb

<p align="center"><img src="assets/logo.png" width="200" alt="Receita Federal emblem"></p>
<p align="center"><sub>Unofficial, community library. Not affiliated with or endorsed by the Receita Federal do Brasil; the emblem is theirs.</sub></p>

[![Project Status: Active](https://www.repostatus.org/badges/latest/active.svg)](https://www.repostatus.org/#active)
![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![PyPI Version](https://img.shields.io/pypi/v/filings-rfb)
[![Snyk Vulnerabilities](https://snyk.io/test/github/guilhermegor/filings-rfb/badge.svg)](https://snyk.io/test/github/guilhermegor/filings-rfb)
[![Snyk License](https://snyk.io/advisor/python/filings-rfb/badge.svg)](https://snyk.io/advisor/python/filings-rfb)
![PyPI Downloads](https://static.pepy.tech/badge/filings-rfb)
[![Linting](https://img.shields.io/badge/linting-ruff_|_codespell-blue)](https://github.com/astral-sh/ruff+https://github.com/codespell-project/codespell)
![Formatting: isort](https://img.shields.io/badge/formatting-isort-%231674b1)
![Test Coverage](./coverage.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Open Issues](https://img.shields.io/github/issues/guilhermegor/filings-rfb)
![Contributions Welcome](https://img.shields.io/badge/contributions-welcome-darkgreen.svg)

<!-- slug: overview -->
## Overview

`filings-rfb` reads the Receita Federal do Brasil (RFB) **CNPJ open data** (the company registry)
into typed pandas DataFrames. It covers every dataset the RFB publishes:

| Dataset | Reader | Content |
|---------|--------|---------|
| Empresas | `read_companies` | Legal entities (basic CNPJ, name, legal nature, share capital) |
| Estabelecimentos | `read_establishments` | Establishments, with the full 14-character CNPJ and its validity |
| Socios | `read_partners` | Partners and representatives (CPFs stay masked) |
| Simples | `read_simples` | Simples Nacional and MEI options |
| Cnaes, Motivos, Municipios, Naturezas, Paises, Qualificacoes | `read_lookup` | Code lookup tables |

**Data source and cadence.** The data comes from the RFB's public share
(`arquivos.receitafederal.gov.br`), which publishes one folder per reference month (`YYYY-MM`),
refreshed monthly. A reader takes the month as its argument; a month the share does not publish
raises an error rather than falling back to another one.

⚠️ **Size.** The archives are large and are never held in memory: each reader streams every ZIP
to disk and yields typed chunks. `Estabelecimentos` is the heaviest (ten parts, up to 2.3 GB
each compressed) and `Simples.zip` inflates to ~3.2 GB. Plan for disk space and a long first
run; pass `path_workdir=` to keep the ZIPs so a rerun resumes instead of downloading again.

<!-- slug: getting-started -->
## Getting Started

Python 3.10+ is the only prerequisite.

<!-- slug: install -->
### Install

```bash
pip install filings-rfb
pip install 'filings-rfb[parquet]'   # optional: Parquet export (pulls in pyarrow)
```

Until the first PyPI release is published, install from source:
`pip install git+https://github.com/guilhermegor/filings-rfb.git`. To work on the library
itself, see [CONTRIBUTING.md](CONTRIBUTING.md).

<!-- slug: usage -->
### Usage

Every dataset reader (`read_companies`, `read_establishments`, `read_partners`,
`read_simples`) takes a reference month (`YYYY-MM`) and yields chunks of `int_chunk_rows` rows
(default 500,000), so memory stays flat. `read_lookup` is the exception: it takes
`str_table, path_zip, str_url, str_etag` and returns a single DataFrame, since each lookup table
is small. Every row carries provenance columns (`url`,
`updated_at`, `source_key`, `package_version`, `ingestion_run_id`, `content_hash`,
`source_etag`).

**Empresas.** `capital_social` is an exact `Decimal`, never a float.

```python
from filings_rfb import read_companies

for df_chunk in read_companies("2026-10"):
    ...
```

**Estabelecimentos.** Adds the full `cnpj_completo` and its validity flag `cnpj_valido`
(alphanumeric-aware).

```python
from filings_rfb import read_establishments

for df_chunk in read_establishments("2026-10"):
    ...
```

**Socios.** Masked CPFs (`***240659**`) are kept verbatim, never unmasked; `***000000**` as
representative document becomes null.

```python
from filings_rfb import read_partners

for df_chunk in read_partners("2026-10"):
    ...
```

**Simples.** Booleans and real dates, with the RFB's `00000000` read as null.

```python
from filings_rfb import read_simples

for df_chunk in read_simples("2026-10"):
    ...
```

**Lookups.** `read_lookup` reads one downloaded lookup ZIP (one of `CNPJ_LOOKUP_NAMES`).

```python
from pathlib import Path

from filings_rfb import read_lookup
from filings_rfb._internal.utils.stream_downloader import download_file_streaming
from filings_rfb.ingestion.cnpj._share import file_url, latest_reference_month

str_url = file_url(latest_reference_month(), "Cnaes.zip")
path_zip, str_etag = download_file_streaming(str_url, Path("data/raw/Cnaes.zip"))
df_cnaes = read_lookup("Cnaes", path_zip, str_url, str_etag)
```

**Parquet.** `export_companies_parquet("2026-10", path)` writes `Empresas` to one Parquet file
for lazy querying (DuckDB, Polars `scan_parquet`); it needs the `parquet` extra.

⚠️ Do not read these files with Polars directly: it silently misparses the `.zip` and corrupts
latin-1 text.

More recipes are in the [documentation](https://guilhermegor.github.io/filings-rfb/).

<!-- slug: project-structure -->
## Project Structure

```text
filings-rfb/
├── .github/        workflows, CODEOWNERS, PR template
├── .specs/         feature specs and backlog trackers
├── bin/            gate scripts and helpers
├── docs/           published documentation
├── src/            application code
├── tests/
│   ├── unit/
│   └── integration/
├── pyproject.toml
└── poe_tasks.toml  task runner entry points
```

<!-- slug: development -->
## Development

```bash
poetry run pytest tests/unit/ -v
poetry run pytest tests/integration/ -v
```

<!-- slug: public-api -->
## Public API

The public surface is whatever the package `__init__.py` lists in `__all__`; everything
under `_internal/` is private.

- `read_companies(str_month, int_chunk_rows=500_000, path_workdir=None)`: `Empresas` chunks.
- `read_establishments(...)`: `Estabelecimentos` chunks, same signature.
- `read_partners(...)`: `Socios` chunks, same signature.
- `read_simples(...)`: `Simples` chunks, same signature.
- `export_companies_parquet(str_month, path_dest, int_chunk_rows=500_000, path_workdir=None)`:
  `Empresas` to one Parquet file (needs the `parquet` extra).
- `read_lookup(str_table, path_zip, str_url, str_etag)`: one of the six lookup tables
  (`CNPJ_LOOKUP_NAMES`) as a typed DataFrame.
- `CNPJ_LOOKUP_NAMES`, `main`, `__version__`.

<!-- slug: publishing -->
## Publishing

Releases go out from the release workflows under `.github/workflows/`; the git tag is the
version.

<!-- slug: contributing -->
## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch, commit and review rules.

<!-- slug: license -->
## License

This project is licensed under MIT; see [LICENSE](LICENSE).

<!-- slug: authors -->
## Authors

- guilhermegor — [GitHub](https://github.com/guilhermegor) | [LinkedIn](https://www.linkedin.com/in/guilhermegor)

<!-- slug: useful-links -->
## Useful Links

- [GitHub Repository](https://github.com/guilhermegor/filings-rfb)
- [Issue Tracker](https://github.com/guilhermegor/filings-rfb/issues)
