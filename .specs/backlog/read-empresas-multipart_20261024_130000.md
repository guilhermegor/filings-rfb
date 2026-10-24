# Read Empresas and the shared multi-part chunked iterator (#6)

- [x] Generic `iter_part_chunks` (`ingestion/cnpj/_multipart.py`): parts 0-9, stream to disk, read member as stream
- [x] `read_table_chunks` seam in `tabular_reader` (contract + `apply_dtypes` per chunk)
- [x] Per-part provenance: `stamp_source_etag` and a reusable run id
- [x] `read_companies` with exact `Decimal` capital
- [x] `export_companies_parquet` behind the optional `filings-rfb[parquet]` extra
- [x] A missing part is an error, never skipped
- [x] Unit tests on a two-part fixture, docs and README
- [ ] Merge the PR
