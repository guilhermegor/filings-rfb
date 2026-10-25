# **Usage**

Examples for installing and using this library.

> **See also:** [API Reference](api/index.md)

---

## Installation

```bash
pip install filings-rfb
pip install 'filings-rfb[parquet]'   # optional: Parquet export
```

Or with Poetry:

```bash
poetry add filings-rfb
```

Until the first PyPI release is published, install from source:
`pip install git+https://github.com/guilhermegor/filings-rfb.git`.

---

## Basic usage

Every dataset reader (`read_companies`, `read_establishments`, `read_partners`,
`read_simples`) takes a reference month (`YYYY-MM`) and yields typed chunks. `read_lookup` is the
exception: it takes `str_table, path_zip, str_url, str_etag` and returns a single DataFrame.

```python
from filings_rfb import read_partners

for df_chunk in read_partners("2026-10"):
    ...
```

`read_establishments` (up to 2.3 GB per compressed part) and `read_simples` (~3.2 GB inflated)
are the heaviest; keep `path_workdir=` to resume instead of re-downloading.

---

## Cataloguing the RFB CNPJ share

The Receita Federal publishes the CNPJ open data as one folder per reference month
(`YYYY-MM`) on a public WebDAV share. `filings_rfb.ingestion.cnpj._share` lists what is
there, without authentication, so a reader never builds a URL by hand:

```python
from filings_rfb.ingestion.cnpj._share import (
    file_url,
    latest_reference_month,
    list_files,
    list_reference_months,
)

list_reference_months()          # ['2023-05', ..., '2026-10']
str_month = latest_reference_month()

for cls_file in list_files(str_month):
    print(cls_file.str_name, cls_file.int_size, cls_file.str_etag, cls_file.dt_last_modified)

file_url(str_month, "Empresas0.zip")   # plain-GET download URL, no redirect
```

- `list_files` returns one `WebdavEntry` per file: `str_name`, `int_size` (bytes),
  `str_etag` (as the server sends it, quotes included) and `dt_last_modified` (UTC).
- Requesting a month the share does not publish raises `ValueError`; there is no silent
  fallback to another month.
- Every listing is a live request, so it reflects what RFB publishes now. If RFB rotates the
  share, change `SHARE_TOKEN` in `_share.py` and nothing else.

---

## Reading Empresas

`read_companies(str_month)` yields one typed `pandas.DataFrame` per chunk of each of the ten
`Empresas0.zip` .. `Empresas9.zip` parts, so a month that inflates to ~3 GB is never held in
memory at once. Each ZIP is streamed to disk with the resumable downloader and its single member
is read as a stream, never extracted.

```python
from filings_rfb import read_companies

for df_chunk in read_companies("2026-10", int_chunk_rows=500_000):
    print(df_chunk[["cnpj_basico", "razao_social", "capital_social"]].head(1))
```

- `capital_social` is parsed from decimal-comma text (`120000000000,00`) to an exact `Decimal`,
  never through a float, with no rounding.
- Every row carries the provenance columns plus `source_etag` (the part's `ETag`) and
  `part_index` (0-9); all chunks of one call share one `ingestion_run_id`.
- A part the share does not list raises `FileNotFoundError` before any download starts; it is
  never skipped.
- Pass `path_workdir=` to keep the downloaded ZIPs (a rerun resumes from them); by default each
  ZIP is deleted once consumed.

### Exporting to Parquet

`export_companies_parquet(str_month, path_dest)` drains the same iterator into one Parquet file
(`capital_social` stored as `decimal128(38, 2)`). It needs the optional extra, which pulls in
pyarrow:

```bash
pip install 'filings-rfb[parquet]'
```

Without it the call raises an `ImportError` that names the extra. Querying the Parquet lazily
(DuckDB, Polars `scan_parquet`) is up to you; see [Examples](examples.md).

⚠️ Do not read these files with Polars directly: it silently misparses the `.zip` and corrupts
latin-1 text.

## Running from the Makefile

```bash
poe run            # runs src/filings_rfb/main.py
```

---

## Running tests

```bash
poe unit_tests         # unit tests only
poe integration_tests  # integration tests only
poe test_cov           # unit tests + coverage report + badge
```

---

## Linting and formatting

```bash
poe lint          # ruff check + ruff format + codespell + pydocstyle
```

---

## Downloading multi-GB archives

The RFB CNPJ archives reach 2.3 GB each (`Estabelecimentos0.zip`), so they must never be held
in memory. `download_file_streaming` writes the body to disk in fixed-size chunks and can
resume an interrupted transfer:

```python
from pathlib import Path

from filings_rfb._internal.utils.stream_downloader import download_file_streaming

path_zip, str_etag = download_file_streaming(
    "https://example.org/Estabelecimentos0.zip",
    Path("data/raw/Estabelecimentos0.zip"),
)
```

- The body is streamed into `<dest>.part`; only after the byte count matches `Content-Length`
  is it renamed onto the destination, so the final path never holds a partial file.
- The server `ETag` is stored next to the partial file (`<dest>.part.etag`). A retry, or a
  later call after a crash, continues with `Range: bytes=<n>-` and `If-Range: <etag>`. If the
  `ETag` changed, or the leftover has no recorded `ETag`, the download restarts from zero.
- After the rename the `ETag` is recorded in `<dest>.etag`. Calling again for a destination that
  has that sidecar sends `If-None-Match`: a `304` returns the existing file untouched with the
  stored `ETag`; a `200` downloads and replaces it. With no sidecar the file is downloaded
  afresh. This is how a rerun over a kept `path_workdir` avoids re-downloading every part.
- The returned `str_etag` (empty when the server sends none) is for provenance.
- A body shorter than `Content-Length` raises `OSError` after the bounded retries, keeping the
  partial file for the next attempt; a response without `Content-Length` raises `ValueError`.
- It shares the guards of `http_downloader` (http/https only, public hosts only, redirects
  refused, bounded retries). `download_file` there still buffers the whole body: use it only
  for small files.

---

## Publishing to PyPI

Two GitHub Actions workflows handle releases (present when the repo has a GitHub remote):

- **`release-test-pypi.yaml`** — publish to [Test PyPI](https://test.pypi.org) first.
- **`release-pypi.yaml`** — publish to [PyPI](https://pypi.org) and cut a GitHub release.

Trigger either from the **Actions** tab (`workflow_dispatch`) with the version to release.
Both gate on the new version being greater than the latest already published, build with
`python -m build`, and publish through OIDC trusted publishing. No token secrets are needed.

Register a **pending trusted publisher** once on each index:

- pypi.org: workflow `release-pypi.yaml`, environment `release-pypi`.
- test.pypi.org: workflow `release-test-pypi.yaml`, environment `release-test-pypi`.

GitHub creates the environments on the first run.

The docs site (<https://guilhermegor.github.io/filings-rfb/>) returns 404 until the first
`release-pypi.yaml` run's `deploy_docs` job (mike) creates the `gh-pages` branch. After that,
run `poe enable_pages` once.
