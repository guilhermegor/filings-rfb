# Work ledger: read the six CNPJ lookup tables (issue #5)

## Done
- [x] One `FileContract` per lookup table in `_internal/config/contracts/cnpj_lookups.py`.
- [x] `read_lookup` picks the single ZIP member regardless of name; zero or several raise.
- [x] Codes stay text (leading zeros kept); `latin-1`, `;`, headerless verified on the live share.
- [x] Provenance stamped, including the source `ETag` via `stamp_source_etag`.
- [x] Unit tests on trimmed real fixtures (accented `latin-1` rows included).
- [x] Docs: API reference, example recipe, README line.

## Open
- [ ] Wire the streamed downloader (#3) and share catalogue (#4) to `read_lookup` once both land.
- [ ] Decide whether `source_etag` belongs in `FileContract.PROVENANCE_COLUMNS`.
