# Ledger — stream multi-GB RFB archives (issue #3)

Branch `feat/3-stream-multi-gb-rfb-archives`. Sibling module `stream_downloader.py` rather than
editing `http_downloader.py` in place, so the template seam stays close to byte-identical for
the BlueprintX backport.

## Done

- [x] Failing tests first: chunked write, resume after a cut, ETag change restart, size mismatch.
- [x] `stream_downloader.download_file_streaming` (chunked, `.part` + ETag sidecar, `Range` /
  `If-Range`, size check, atomic rename), importing the `http_downloader` guards.
- [x] Fix `_NoRedirectHandler.redirect_request` annotation (a 3xx raised `TypeError`).
- [x] `docs/usage.md` section.

## Open

- [ ] Backport the `redirect_request` annotation fix and the sibling module to BlueprintX.
- [ ] Wire `download_file_streaming` into the Empresas / Estabelecimentos / Socios readers (#6-#8).
