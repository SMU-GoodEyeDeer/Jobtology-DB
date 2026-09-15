# Live baseline for the IT, AI and data posting completion work

Read-only audit on Goldship, 2026-09-15 13:02 UTC. This records the state before
the new source-independent CS selection and review work. It is **not** a measured
CS cohort: the counts below cover every posting in the latest ALIO snapshot.
`enrichment.linking_status` follows the latest ready snapshots, so rerun the
queries before using the counts to schedule work.

## Pinned source and reference runs

| Source | Latest ready run at audit |
|---|---|
| ALIO job postings | `4eae07ed-1b70-4146-8e4f-75291c6b6b13` (530 postings) |
| ALIO organizations | `cb6db580-6cdb-4015-8fd6-2d7f682e460a` |
| NCS competency units | `a32170ed-7485-4e31-82d3-ed48b3398946` |
| NCS qualifications | `2b485d2e-715c-4310-b5fc-4ffbd663de7a` |
| NCS career paths | `51a6a5d2-5ccf-4459-8218-d61668c34d96` |
| QNet exam sessions | `6b5c8995-beb4-4256-9c69-9608a29a31f2` |

The prior ALIO run was `4c4fcc8b-1292-4d66-ace5-e36d005f194a` (517
postings). `enrichment.input_bundle` contains 517 bundles for its 517 IDs.
The older run `7c34eb6b-0e8f-4deb-a93b-9d336762f8be` has 1,029
historical bundles covering 513 distinct posting IDs. No bundle row is labelled
with the latest 530-posting run; exact content hashes, rather than run labels,
establish which earlier bundles can still be used.

## Current posting status and saved work

| Current outcome | Postings | Exact current-hash bundles/items | Validated extraction attempts | Validated categorization attempts | Saved matched categorization |
|---|---:|---:|---:|---:|---:|
| `ACCEPTED_LINKS` | 72 | 72 | 72 | 72 | 72 |
| `NO_ACCEPTED_LINKS` | 9 | 9 | 9 | 9 | 9 |
| `NO_SUPPORTED_MATCH` | 28 | 28 | 27 | 28 | 0 |
| `LINK_REVIEW` | 3 | 3 | 0 | 3 | 3 |
| `EXTRACTION_REVIEW` | 347 | 347 | 345 | 337 | **207** |
| `EXTRACTION_FAILED` | 5 | 5 | 0 | 0 | 0 |
| `PENDING_EXTRACTION` | **66** | **0** | 0 | 0 | 0 |
| **Total** | **530** | **464** | 453 | 449 | 291 |

These are distinct postings with at least one attempt at the exact source hash
used by the current status view. They are not raw attempt-row counts. A corrected
accepted revision can explain an accepted posting without a validated original
extraction attempt (for example, the three `LINK_REVIEW` rows). A validated
attempt is a schema/model result; it does not establish semantic acceptance.

Among the 347 `EXTRACTION_REVIEW` postings, **207** have at least one validated
categorization with `outcome='matched'` and saved match objects, **130** have a
validated `no_supported_match`, and **10** have neither outcome. The 207 are the
largest zero-call candidate review pool after applying the role-level CS scope.
Saved matches remain model proposals until the extraction and individual NCS
links are reviewed. The 130 no-match results also deserve source/catalogue
review; they do not prove that the posting has no applicable NCS unit.

All 66 `PENDING_EXTRACTION` IDs are absent from the prior 517-posting run. They
also have no historical input bundle or production `ENRICH` item under **any**
hash. Thus they are new posting identities, not old results invalidated only by
a source change. Screen their advertised roles before preparing documents or
making new model requests. Existing `attachment.processor_document` rows are
1,923 `PARSED`, 40 `NO_TEXT` and 49 `PARSE_ERROR` across historical processing;
these are document rows and must not be read as 1,923 current postings.

The published reviewed graph currently contains 112 accepted posting
extractions and 299 accepted NCS links. Only 72 of those postings have at least
one accepted link. Publication, model processing and source loading are separate
milestones.

## Cheap title triage and its limits

A broad title-only signal
`(전산|정보|데이터|빅데이터|인공지능|AI|SW|소프트웨어|개발|시스템|IT|보안|클라우드|네트워크|디지털|통계)`
matched 35 of 530 titles: 7 `ACCEPTED_LINKS`, 26 `EXTRACTION_REVIEW`, one
`NO_SUPPORTED_MATCH` and one new `PENDING_EXTRACTION`. All 26 review cases have
saved validated extractions; 18 have saved matched categorization, seven have
saved no-match results, and one has neither.

This signal is only a triage hint. It catches `88관광개발` (`304626`), routine
`근로자정보입력원` (`304747`) and physical-security notices, while it misses technical
roles inside generic multi-position notices such as `304697` and `304833`.
Accepted NCS `보안` units for `304507`, `304548` and `304734` describe patrol or
access control, not cybersecurity. Define scope from the **advertised position
and duty evidence**, with an explicit undecided state for mixed or unclear cases.

Useful saved-result review starters, pending source/duty checks:

| Posting | Current state | Saved categorization |
|---|---|---|
| `304451` software policy institute research notice | `EXTRACTION_REVIEW` | `matched`, 6 match objects |
| `304470` healthcare information-system operations | `EXTRACTION_REVIEW` | `matched`, 2 match objects |
| `304490` mixed general administration / IT development-operations / facilities | `EXTRACTION_REVIEW` | `matched`, 3 match objects; select the IT position only |
| `304822` radiation/AI research notice | `EXTRACTION_REVIEW` | `no_supported_match`; inspect duties and catalogue locally |
| `304913` electronic handoff-system operations notice | `PENDING_EXTRACTION` | no saved bundle or production attempt |

Already published IT-like links occur under both specific and generic titles:
`304055` network operations, `304425` technical security operations, `304482`
information-system security, `304686` programming, `304697` privacy and system
design, `304714` network maintenance, `304763` system design, `304792` database
management, and `304833` data preprocessing and AI platform requirements.
Recheck the linked duty for each position before counting it in the CS cohort.

## Cost route and balance observation

No inference request was made during this audit. An authenticated, read-only
`GET /api/v1/credits` using the protected key on Goldship returned HTTP 200:
OpenRouter **funded** credits $8.00, reported usage $2.58042104, remaining
**$5.41957896**. The key was not printed or copied into the repository.

The user's new $10 recharge is not reflected in that funded-credit total. The
active model route has previously used OpenRouter **BYOK** through OpenAI; its
upstream spend and available OpenAI balance are separate from this OpenRouter
funded-credit endpoint. Do not treat $5.41957896 as confirmation or denial of
the upstream recharge. Production attempt `cost_usd` stores reported upstream
inference cost for BYOK; OpenRouter's `usage.cost=0` alone is not a zero-charge
signal. Confirm the actual provider route and budget before bounded new calls.

The first CS scope and saved-output review should incur zero new provider calls.
New calls can be limited to selected new IDs or selected positions whose source
evidence and existing extraction/categorization cannot be resolved by review or
local NCS retrieval.

## Reproducible read-only SQL

Run against the live PostgreSQL database in a read-only transaction. These
queries return live latest-state counts; the pinned run IDs above are the audit
reference, not a filter in `enrichment.linking_status`.

```sql
BEGIN READ ONLY;
SELECT source_id, run_id, created_at
FROM ingestion.latest_ready_run ORDER BY source_id;
SELECT outcome, count(*)
FROM enrichment.linking_status GROUP BY outcome ORDER BY outcome;
SELECT job_run_id, count(*) AS bundle_rows,
       count(DISTINCT posting_id) AS distinct_postings
FROM enrichment.input_bundle GROUP BY job_run_id;
COMMIT;
```

The lineage table above used this exact-hash join. A `matched` result is counted
only if its categorization attempt is validated.

```sql
BEGIN READ ONLY;
WITH s AS MATERIALIZED (
  SELECT posting_id, source_hash, outcome FROM enrichment.linking_status
), a AS MATERIALIZED (
  SELECT i.posting_id, i.source_hash,
         bool_or(x.state='VALIDATED') AS extracted,
         bool_or(c.state='VALIDATED') AS categorized,
         bool_or(c.state='VALIDATED'
                 AND c.parsed_output->>'outcome'='matched') AS matched,
         bool_or(c.state='VALIDATED'
                 AND c.parsed_output->>'outcome'='no_supported_match') AS no_match,
         count(*) AS item_count
  FROM enrichment.item i JOIN enrichment.batch b USING(batch_id)
  LEFT JOIN enrichment.attempt x ON x.attempt_id=i.extraction_id
  LEFT JOIN enrichment.attempt c ON c.attempt_id=i.categorization_id
  WHERE b.mode='ENRICH' GROUP BY i.posting_id, i.source_hash
), u AS MATERIALIZED (
  SELECT posting_id, source_hash, count(*) AS bundle_count
  FROM enrichment.input_bundle GROUP BY posting_id, source_hash
)
SELECT s.outcome, count(*) AS postings,
       count(*) FILTER (WHERE u.bundle_count IS NOT NULL) AS has_bundle,
       count(*) FILTER (WHERE a.item_count IS NOT NULL) AS has_item,
       count(*) FILTER (WHERE a.extracted) AS extracted,
       count(*) FILTER (WHERE a.categorized) AS categorized,
       count(*) FILTER (WHERE a.matched) AS matched,
       count(*) FILTER (WHERE a.no_match) AS no_match
FROM s LEFT JOIN a USING(posting_id, source_hash)
LEFT JOIN u USING(posting_id, source_hash)
GROUP BY s.outcome ORDER BY s.outcome;
COMMIT;
```

The 66 new-ID check compared `PENDING_EXTRACTION` IDs with the prior run and
all historical bundles and production items, regardless of hash:

```sql
BEGIN READ ONLY;
WITH pending AS MATERIALIZED (
  SELECT posting_id FROM enrichment.linking_status
  WHERE outcome='PENDING_EXTRACTION'
), prior AS MATERIALIZED (
  SELECT DISTINCT posting_id FROM ingestion.job_posting
  WHERE run_id='4c4fcc8b-1292-4d66-ace5-e36d005f194a'
), bundles AS MATERIALIZED (
  SELECT DISTINCT posting_id FROM enrichment.input_bundle
), items AS MATERIALIZED (
  SELECT DISTINCT i.posting_id FROM enrichment.item i
  JOIN enrichment.batch b USING(batch_id) WHERE b.mode='ENRICH'
)
SELECT count(*) AS pending,
       count(*) FILTER (WHERE prior.posting_id IS NOT NULL) AS in_prior,
       count(*) FILTER (WHERE bundles.posting_id IS NOT NULL) AS prior_bundle,
       count(*) FILTER (WHERE items.posting_id IS NOT NULL) AS prior_item
FROM pending LEFT JOIN prior USING(posting_id)
LEFT JOIN bundles USING(posting_id) LEFT JOIN items USING(posting_id);
COMMIT;
```
