# 나라일터 public-service postings

This native Hop workflow loads the `PblJobService` API from data.go.kr into a
source-qualified `nara_job` snapshot. It archives each response before parsing,
keeps every list row in the chosen registration-date window, and fetches the
detail, position, and file-metadata resources for every posting open on the
snapshot date.

## First installation

Run `${PROJECT_HOME}/ingestions/nara_job/install.hwf` once. It adds the source to
the existing `ingestion` ledger, installs the normalization function and read
views, and gives this provider a 10,000-request rolling allowance. Existing
snapshots and tables are preserved.

The workflow uses `jobtology-postgres` and the same protected data.go.kr CSV as
the other public APIs. The CSV must contain exactly one decoded key under the
`service_key` header.

## Fetch a snapshot

Open `${PROJECT_HOME}/ingestions/nara_job/full.hwf`, select **nara-job-local**,
use **Basic** logging, and run `MODE=FULL`.

| Parameter | Default | Meaning |
|---|---:|---|
| `BEGIN_DATE` | blank | Registration-window start. Blank means 120 days before the KST run date. |
| `END_DATE` | blank | Window end and snapshot date. Blank means the KST run date. |
| `MAX_PAGES` | `20` | Refuse a larger list result before scheduling companion resources. |
| `MAX_REQUESTS` | `5000` | Total request cap; maximum 10,000. |
| `RAW_ROOT` | `${PROJECT_HOME}/data/nara-job-raw` | Persistent response archive. |
| `API_KEY_FILE` | `${HOP_CONFIG_FOLDER}/secrets/data-go-kr.csv` | Protected runtime credential. |

At the successful 2026-09-16 production baseline, a 120-day index contained
10,844 rows and 761 postings still open on the snapshot date. That used 11 list
requests and 2,283 companion requests, for 2,294 HTTP documents total. Counts
vary, so the workflow calculates the actual active count and refuses a resource
plan above `MAX_REQUESTS`.

The provider catalog labels `type01` and `type02` in the opposite order from the
live values. The adapter records the observed contract: `type01` is the posting
type (`e…`) and `type02` is the institution type (`g…`). Invalid dates or missing
identity/title/employer values are retained in `ingestion.rejected_row`; a FULL
run with a rejected row cannot become READY.

```sql
SELECT posting_id, normalized->>'title' AS title,
       normalized->>'organization_name' AS employer,
       normalized->>'closing_date' AS closing_date,
       jsonb_array_length(normalized->'positions') AS positions,
       jsonb_array_length(normalized->'attachment_refs') AS files
FROM ingestion.nara_job_posting
WHERE run_id=(SELECT run_id FROM ingestion.latest_ready_run WHERE source_id='nara_job')
ORDER BY posting_id;
```

## CS filtering and LLM extraction

After reinstalling `cs/install.hwf` and `llm/install.hwf`, the postings appear in
`cs.common_posting` and `cs.scope_screen`. Screen the IT/AI/data subset first; do
not pay to process the unrelated public-service corpus.

Run `llm/enrich.hwf` with:

- `JOB_SOURCE_ID=nara_job`
- `JOB_RUN_ID=<exact READY nara_job run ID>`
- `NCS_RUN_ID=<exact READY NCS run ID>`
- `POSTING_IDS=<internal IDs separated by |>` from `cs.current_scope.posting_id`
- `PROMPT_VERSION=ko-link-v1`, `ACCEPTANCE_POLICY=REVIEW`
- `EXECUTE_REQUESTS=N` first, then `Y` after checking the plan and budget

The internal ID is `ext-nara_job-<sha256(source posting ID)>`. The original
나라일터 `idx` and public URL remain in the normalized record. Exact matching
content can use the normal model cache; similar JOB-ALIO titles do not share a
cache entry unless the complete source input and model settings match.

The API exposes file metadata and download URLs. This adapter retains those
references and uses inline `contents` and position names for ordinary extraction.
Downloading and parsing selected HWP/PDF/DOC attachments through the existing
document processor remains a separate source-policy step.

### First live screening and enrichment

The 2026-09-16 snapshot had 13 initial candidate postings. Their first review
excluded four clear false positives; after the model split the remaining notices
into advertised positions, the current position-level decision set contains ten
CS/IT/AI/data roles, two generic ETRI roles pending attachment detail, and 28
explicitly out-of-scope roles. The nine initially selected notices were enriched
with `ko-link-v1` through OpenRouter's `openai/gpt-5.6-luna` route. All nine
extraction responses passed the structural and source-evidence checks in 11
requests at $0.0170414.

Only the medical big-data researcher had sufficiently explicit inline duties.
Its three independently reviewed NCS links were published to Neo4j in
publication `nara-job-20260916`. Three notices require their attachments for
duties, four have no explicit duties in the API text, and one explicit
infrastructure role had no supported NCS match. These outcomes are retained in
`enrichment.linking_status`; attachment extraction is intentionally deferred.
