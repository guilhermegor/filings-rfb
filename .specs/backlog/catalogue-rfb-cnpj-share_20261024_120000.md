# Catalogue the RFB CNPJ share (#4)

- [x] PROPFIND seam (`_internal/utils/webdav_client.py`) with defusedxml parsing
- [x] Share catalogue (`ingestion/cnpj/_share.py`): months, files, `file_url`
- [x] Recorded PROPFIND fixtures and unit tests (no network)
- [x] `docs/usage.md` section
- [x] Collections never report a size
- [x] Vendor XML errors re-raised in the seam's own ValueError wording
- [ ] Merge PR #18
