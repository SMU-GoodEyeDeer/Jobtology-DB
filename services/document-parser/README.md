# Existing document-processor adapter

Uses `../document-processor`, including its HWP converter, rather than implementing
file-format parsing here. Hop remains responsible for fetching, provenance, SQL,
model requests and graph publication. This service only reads archived files and
returns Markdown plus structural/semantic JSON. No model or download credentials.

Build from the workspace parent with this Dockerfile and a revision identifying
the exact source used (include a worktree digest when the parser has local edits):

```sh
docker build -f Jobtology-DB/services/document-parser/Dockerfile \
  --build-arg PARSER_REVISION=<source-revision> -t jobtology-document-parser:local .
```

Run on a private Docker network reachable by Hop, with **no published port**, a
read-only attachment directory mounted at the same absolute path used by Hop,
`DOCUMENT_ROOT` set to that path, a writable `/tmp` tmpfs, and memory/CPU limits.
Do not mount private Hop connection metadata or API keys into the service.
The standard library service processes requests sequentially; each document runs
in a separate process with a timeout (default 180 seconds). Configure Hop's HTTP
read timeout above that timeout. Failed documents return explicit outcomes.

`POST /parse`: JSON `{path, raw_hash, extension}`. Accepted extensions are pdf,
hwp, hwpx, doc and docx; ZIP bundles can contain these formats. Paths must resolve under DOCUMENT_ROOT, bytes must match
the pinned SHA-256, and archive sizes are bounded. `GET /health` reports the
parser revision. The service has no public authentication interface; keep it
private. Input documents and parser dependencies remain separate mounted/image
artifacts, never content committed to this repository.

ZIP members are unpacked only into numbered temporary files; traversal, symlinks,
encryption and oversized archives are rejected. The adapter can read one nested
ZIP layer and hand its PDF/HWP/HWPX/DOC/DOCX leaves to the existing library.
It bounds the whole tree to 100 file members and 256 MiB of nested uncompressed
bytes. Deeper ZIPs and images are reported as unsupported members. Each leaf
retains its outer and inner member names, non-directory ordinals, raw SHA-256
chain and block boundaries; the outer original stays immutable. No OCR is
currently performed.

Outputs use `document-processor-v1`: exact NFC/LF Markdown, SHA-256, block offsets
in Unicode code points, source node locators, semantic blocks, full structural
JSON without binary image assets, and image-review warnings. A PARSED result is
text extraction, not evidence that every image or table was understood correctly.


The adapter normalizes NUL to U+FFFD before storing JSONB, recording affected
JSON paths and counts. For the bundled HWP converter's raw-control-character XML
failure, it can normalize a derived HWPX container and feed it back to the same
library. Changed XML-entry hashes/counts are recorded; original HWP bytes are
untouched. This recovery does not repair arbitrary malformed XML or PDF files.

Changing adapter behavior also changes the pinned `PARSER_REVISION` suffix.
Image `20260914-2` uses suffix `-hop2`; the tested normalization build
`20260914-3` uses `-hop3`. The nested-ZIP adapter was deployed privately on
Goldship as `jobtology-document-parser:20260915-4` with
`PARSER_REVISION=7541e87c0b45d8d209cd3c110f7bf09c72666779-hop4`.
The immutable 304933 outer JD ZIP then parsed through native Hop, with all
16 PDF leaves, 147 pinned sections and no warnings; see the
[source triage receipt](../../docs/hop-migration/cs-new-postings-triage-20260915.md).
Check the live health response and deployment record before assuming which
image is active. The upstream parser repository itself remains unmodified.

Fast adapter checks: `python services/document-parser/test_contract.py`.
Native Hop/PG/parser/Neo4j checks: `python hop/llm/tests/linked_ingestion.py`.
The latter uses disposable containers and the local parser image; it makes no
paid API calls and never copies synthetic review decisions to production.
