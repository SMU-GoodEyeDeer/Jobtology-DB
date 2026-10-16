# Repository context

Read [the current handoff](docs/hop-migration/current-handoff.md) before working on
deployment or ingestion. It records the latest verified state, user decisions and
pending work; dated September reports remain historical evidence.

## Prefetched job board datasets

- Use only supplied, locally available exports and archived content. Do not make
  requests to job board listing, posting, description, image, iframe or signed
  storage URLs, including HEAD checks, browser visits, link refreshes or fallback
  recovery. The user set this restriction on 2026-10-07 to avoid rate limits and
  bot bans; it applies until the user changes it.
- Treat scraper output as raw source input. Generate ingestion metadata,
  provenance, normalization, quality flags, embeddings and other enrichment in
  this repository; do not require the scraper to produce those derived fields.
  Follow [the input and processing responsibilities](docs/hop-migration/prefetched-postings.md).
- Record import and processing timestamps here. Record an actual scrape time
  only when supported by the collection event or supplied evidence; otherwise
  leave it unknown. Import time and file modification time are not scrape time.
- On 2026-10-11 the user supplied the actual collection time for the entire
  8,434-posting JobKorea snapshot: `2026-10-08 02:48:14 Asia/Seoul` (KST), or
  `2026-10-07T17:48:14Z`. Record this as separate `USER_REPORTED` scrape evidence.
  The original import receipt and frozen inputs recorded unknown/NULL scrape
  time; preserve their bytes and hashes rather than rewriting them. Effective
  ingestion-date metadata may use this later evidence while retaining its basis.
- Record missing source content explicitly. Process supplied local content when
  available, without requiring a richer export before accepting listing metadata.
- Application start dates are optional and low priority. For prefetched JobKorea
  postings, the user's 2026-10-07 policy treats missing or NULL application end
  dates as `상시채용`: normalize to `deadline_kind=ROLLING` with a NULL end date
  and `deadline_basis=USER_POLICY`. Preserve raw input and distinguish this
  assumption from source-stated deadlines. Explicit deadlines or closed status
  take precedence; malformed supplied dates remain validation issues.
- Keep original exports, signed URLs and credentials out of Git. Preserve raw
  evidence separately from normalized fields.
- Full production exports will use NDJSON: one JSON object per physical line,
  as requested by the user on 2026-10-07. The JobKorea adapter now supports
  streaming NDJSON with bounded batches, exact file/physical-line/UTF-8 byte
  provenance, immutable checkpoints and archive-only resume. Require a terminal
  LF on every complete object line (CRLF is accepted); reject blank, malformed
  or truncated lines. Keep staged rows invisible until the entire supplied file
  passes READY validation. The bounded JSON-array path remains supported.
  Production installation and the supplied 8,434-posting, 21,951,764-byte composed
  NDJSON import were verified on 2026-10-08, including the source graph and all
  frozen listing inputs; see the current handoff and protected receipts. This
  proves the supplied snapshot. Larger advertised maxima remain validation
  bounds, and operation at larger sizes/cardinalities is unverified.
- On 2026-10-08 the user confirmed OpenRouter account readiness, instructed
  linking to proceed, and explicitly selected `ALLOW INFERRED METADATA MATCHES`.
  This lifts the earlier LLM/linking hold for this task. Process only the frozen
  local listing evidence; use a separate, clearly labeled metadata-to-NCS
  occupation inference path with provenance, abstentions and actual review status.
  Keep confidence NULL/UNASSESSED. Validated bulk inferences may remain
  STAGING/UNREVIEWED; only individually reviewed results gain review status.
  Inferred occupation matches do not establish source-stated duties, extracted
  narrative, or competency evidence. Preserve the strict explicit-duty
  `ko-link-v1` contract. Start with a small paid pilot and scale toward the
  supplied 8,434 listings only when quality and measured cost permit, under the
  coordinator's explicit total accounting budget including upstream BYOK costs
  and router fees. The measured five-row pilot supports the coordinator's
  explicit $5 combined task cap, including the separate health probe; native
  inference accounting is capped at $4.9999922. Defaults remain unchanged.
  The user corrected the earlier $100 statement to $50 available OpenAI credit
  and requested continued use of the lighter model; this balance is
  user-reported, not API-verified. Preserve existing
  credentials/accounts/provider routing. Do not
  infer upstream BYOK account credit from OpenRouter credit balances.
- On 2026-10-14, after the O*NET 31.0 reference catalogue was loaded and
  independently verified, the user reported `$45.90` available credit and said
  `ok proceed` to posting linking. The coordinator set a **separate $40 combined
  O*NET task cap**, including upstream BYOK charges and router fees, covering the
  pilot, full processing and every resume across source/catalogue pins. This
  supersedes the catalogue-only hold for this task; the historical NCS $5 scope
  remains unchanged. Use the existing lighter `openai/gpt-5.6-luna` model,
  OpenRouter/OpenAI routing and credentials. The reported balance is not
  API-verified and does not reset either accounting scope.
  Freeze the locally archived source-only cohort of **22,635 postings**:
  8,434 JobKorea, 12,736 Nara and 1,465 JOB-ALIO. Exclude the 1,014 duplicate
  ontology `jobPosting` entities. Use a separate, explicitly inferred metadata
  to O*NET path with pinned catalogue, original source evidence, immutable
  shortlists/requests, abstentions and actual review status. Preserve existing
  source/NCS facts, edges, strict duty contracts and catalogue namespaces.
  Start with the deterministic 36-posting pilot (12 per source); scale only
  after measured cost and quality review. Unknown charges stop further calls;
  resumes may process only never-sent inputs and must not repeat paid requests
  or graph links. Keep confidence NULL/UNASSESSED and bulk links
  STAGING/UNREVIEWED unless an actual individual review establishes otherwise.
  No job-board HTTP or source content recovery is authorized.

## Working preferences

- Delegate coding and text-writing tasks to GPT-6.1-sol subagents
  (`gpt-6.1-sol`) with high or xhigh reasoning when delegation is available.
  The root agent coordinates, reviews, and verifies their work.
- The user reports that the network is private except for selected domains.
  Distinguish local reachability from public exposure in assessments.
