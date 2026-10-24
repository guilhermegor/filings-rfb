# Root cnpj.tar.gz assessment

Status: draft
Owner: Guilherme Rodrigues
Created: 2026-10-22

## Objective
Decide whether `filings-rfb` should support the `cnpj.tar.gz` archive that sits at the root
of the RFB share, next to the `YYYY-MM` folders (epic #2, sub-issue #10).

**Recommendation: ignore it.** It is a redundant gzip snapshot of nine monthly
folders that the library already reaches one file at a time. It cannot back-fill anything
older than `2025-05`, and it is a worse transport than the per-file zips. No follow-up
implementation issue is warranted.

## Method
Only `HEAD`, `PROPFIND` and `Range` requests were used; no multi-GB body was read. The
largest single transfer was an 8 MiB range from offset 0. `<tok>` is the public share token
from epic #2 (`YggdBLfdninEJX9`); `BASE=https://arquivos.receitafederal.gov.br/public.php/dav/files/<tok>`.
Observed 2026-10-22/23.

## Findings

### F-1 Size and validators
```bash
curl -sS -I "$BASE/cnpj.tar.gz"
curl -sS -X PROPFIND -H 'Depth: 1' "$BASE/"      # filtered to the cnpj.tar.gz entry
```
```text
HTTP/1.1 200 OK
Last-Modified: Wed, 28 Jan 2026 15:22:29 GMT
ETag: "9f049a6e219b65bba80d08b98238269c"
Content-Length: 63954782749
Content-Type: application/gzip
```
`PROPFIND` agrees (`getcontentlength` 63954782749, same `getetag` and `getlastmodified`).
63,954,782,749 bytes is 59.6 GiB. The root holds exactly one file, `cnpj.tar.gz`, plus the
42 month folders `2023-05` to `2026-10`. The file has not changed since 2026-01-28 while
nine newer monthly folders have appeared, so it is a one-off snapshot, not a rolling
artefact.

### F-2 Range support and container format
```bash
curl -sS -D - -o head16.bin -r 0-15 "$BASE/cnpj.tar.gz"
```
```text
HTTP/1.1 206 Partial Content
Content-Range: bytes 0-15/63954782749
1f8b 0800 0000 0000 0003 ecfc 43b0 3040
```
`Range` works (206). The first bytes are a gzip header: flags `00` (no embedded name),
mtime 0, OS `03` (Unix), deflate payload from byte 10.

### F-3 Leading tar members
```bash
curl -sS -r 0-8388607 -o head8m.bin "$BASE/cnpj.tar.gz"     # 8 MiB, status=206
python3 -I walk.py head8m.bin     # zlib.decompressobj(16+MAX_WBITS) + tarfile.TarInfo.frombuf
```
```text
@         0 type=5 size=           0 mtime=2025-05-12 04:22:43 2025-05
@       512 type=0 size=       22078 mtime=2025-05-12 04:14:53 2025-05/Cnaes.zip
@     23552 type=0 size=   428195500 mtime=2025-05-12 04:15:21 2025-05/Empresas0.zip
```
GNU tar (`ustar  ` magic), owner `ctmagent:controlm` (a Control-M job account). The archive
**opens at `2025-05`**, not `2023-05`. Members are the share's own zips under their
`YYYY-MM/` prefix, in directory order. The member mtimes (2025-05-12) precede the share's
`Last-Modified` for the same files (2025-05-20), so the tar was built from the upstream
copy, not from the published folder.

The 8 MiB window cannot reach the next header: `Empresas0.zip` alone is 428 MB, and a
gzip stream cannot be seeked, so deeper listing needs sequential decompression of the
bytes before it. That is what F-5 sidesteps.

### F-4 The members are byte-identical to the per-month zips
`2025-05/Cnaes.zip` (22,078 B) and the first 8,365,043 bytes of `2025-05/Empresas0.zip`
were fetched from the share (`curl -r 0-8365042 "$BASE/2025-05/Empresas0.zip"`) and compared
with the tar members decompressed in F-3: both SHA-256 prefixes match
(`68306667f8e21dbf`, `963520657ac394d3`) and the inputs compare equal. The sizes
`PROPFIND` reports for `2025-05/Cnaes.zip` and `2025-05/Empresas0.zip` equal the tar
header sizes.

### F-5 Inferred extent: nine months, `2025-05` to `2026-01`
The last 8 bytes of a gzip stream are CRC32 and ISIZE (uncompressed length mod 2^32):
```bash
curl -sS -r 63954782741-63954782748 -o tail8.bin "$BASE/cnpj.tar.gz"   # 206
# 6a59 615a 00c0 17e7  ->  CRC32=5a61596a  ISIZE=3877093376
```
The expected tar length for each candidate month range was computed from the `PROPFIND`
sizes: per month one 512 B directory header, plus a 512 B header and 512-padded body for
each of the 37 files, plus a 1024 B end marker, rounded up to GNU tar's 10240 B record.

| Range | Expected tar bytes | mod 2^32 | Equals ISIZE (3877093376)? |
|-------|--------------------|----------|----------------------------|
| 2025-05..2025-12 | 56,713,021,440 | 878,446,592 | no |
| 2025-05..2026-01 | 64,006,635,520 | 3,877,093,376 | **yes** |
| 2025-05..2026-02 | 71,375,370,240 | 2,655,893,504 | no |

(The 2025-08..2025-11 ranges also miss; the match is exact to the byte.) The match is
conditional on one assumption: the file is a single gzip member spanning the whole tar.
The trailer's ISIZE covers only the last member, so a multi-member file would give a
different residue; the match is consistent with one member, the simplest explanation, but
does not rule out several (that needs a full 64 GB scan for further `1f8b08` headers).
Compression gains nothing, since the payload is already zip: 64.0 GB
becomes 63.95 GB (0.9992). The tar is therefore **consistent with** the 9 folders
`2025-05` to `2026-01` (333 files). ISIZE is the length mod 2^32 and the range check is
exact to the byte, but a 32-bit residue does not prove membership, and only two members
were byte-compared. This is an inference, not a verified listing.

## Does it help the library?

| Question | Answer |
|----------|--------|
| Back-fill months before `2023-05`? | No. Earliest month inside is `2025-05`. |
| Fill gaps between `2023-05` and `2026-10`? | No. All nine months it holds are still served individually. |
| Any data absent from the per-month folders? | None seen: the files sampled are byte-identical, and the tar length is consistent with the folders. |
| Cheaper to fetch? | No. Compression is 0.08%; one month is ~7 GB but a month inside the tar costs sequential reads of everything before it. |
| Resumable / selective? | Poorly. `Range` works, but a gzip stream (probably one member, see F-5) offers no known seek points, so one lost connection past a few GB restarts the decode, and one table costs the whole prefix. |
| Maintained? | No. Frozen at 2026-01-28 while releases continue monthly. |
| Fits the architecture? | No. The reader contracts (#6-#9) and the catalogue (#4) are keyed on `YYYY-MM/<file>.zip`; a tar reader would be a second, parallel input path for zero new data. |

## Options considered
- **Support (new `cnpj.tar.gz` reader):** rejected. It costs a streaming gzip+tar path
  and a second catalogue, and the data it carries is already in the library's supported
  path.
- **Back-fill only:** rejected, because it cannot back-fill; it starts at `2025-05`.
- **Ignore:** chosen. The catalogue (#4) lists only `YYYY-MM/` folders, so a root file is
  never offered for download. Document it in the FAQ so users do not spend 64 GB on it.

## Acceptance Criteria
- AC-001: Given the share root, when the catalogue is built (#4), then `cnpj.tar.gz` is not
  treated as a month and is not offered as a download.
- AC-002: Given a user wondering what the root archive is, when they read `docs/faq.md`,
  then the FAQ states what it contains and that the library does not use it.

## Assumptions
- ASM-001: The share's per-month files for `2025-05` to `2026-01` are unchanged since the
  tar was cut (sizes equal to the byte; content verified only for the two files in F-4).
- ASM-002: The archive remains static. If RFB starts refreshing it, revisit F-1 (`ETag`).

## Open Questions
- Q-001: Why RFB publishes it (likely a bulk-mirror convenience) is not documented; no
  upstream statement was found, so the purpose is inferred.

## Out of Scope
- Downloading or fully decompressing the archive (64 GB, adds nothing to the verdict).
- Any implementation: no follow-up issue is filed because the recommendation is to ignore.

## Notes
- Epic #2; sub-issue #10; catalogue #4 and streaming download #3 are unaffected.
- Reproduce with the commands above; `walk.py` is ~8 lines of `zlib` + `tarfile`.
