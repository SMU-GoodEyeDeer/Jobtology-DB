# Plan: IT, AI and data postings with NCS links

Status: bounded first ALIO rollout and evidence tail complete at graph checkpoint
`cs-reviewed-20260916-tail-reviewed-c`, 2026-09-16 KST. The live work and its
measured limits are recorded in [the execution report](cs-execution-20260915.md):
67 selected positions, 54 with position-bound NCS links and 13 explicit gaps.
The remaining source-evidence and review cases are explicit; this plan does not
authorize an unbounded model run.

The deliverable is a source-independent selection of CS-related advertised
positions, with supported NCS competency links and related qualifications where
the reference data provides them. Reuse saved source documents, LLM responses,
extraction revisions and review decisions before making additional model calls.

## Starting point

The pre-rollout status check on 2026-09-15 covered JOB-ALIO snapshot
`4eae07ed-1b70-4146-8e4f-75291c6b6b13`, containing 530 loaded postings:

| Current outcome | Postings |
|---|---:|
| Accepted extraction with accepted NCS links | 72 |
| Accepted extraction, all proposed links rejected | 9 |
| Accepted extraction, no supported match in the supplied shortlist | 28 |
| Accepted extraction, link review pending | 3 |
| Extraction review or correction pending | 347 |
| No current extraction result | 66 |
| Extraction failed | 5 |

At that check, 112 accepted extractions and 299 accepted links were published.
The 530 count
is an ingestion count; it is not a completed LLM/review count. The earlier
517-posting snapshot had document input bundles prepared for every posting.
Inventory historical attempts before treating a current missing result as work
that was never attempted: source or attachment changes can invalidate reuse.

Existing code has three relevant limitations:

- Enrichment source selection, input lookup and posting publication identities
  contain ALIO-specific assumptions. A generic filter alone will not make the
  complete path source independent.
- Qualification fetching uses a fixed list of 11 IT/data/AI occupations, including
  a literal count check. That list is neither a posting filter nor the full
  intended IT scope.
- The existing editorial catalogue has four product occupations. Its descriptions
  are useful references, but it is narrower than this ingestion scope.

See [current execution and review procedures](linked-ingestion.md) and
[server access and deployment](server-runbook.md).

## 1. Define and record the relevant positions

Create a versioned scope policy, initially `cs-it-ai-data-v1`, with these defaults:

| Family | Included work examples |
|---|---|
| Software | Backend, frontend, application/system software, software testing and automation |
| IT systems | System administration, networks, cloud, infrastructure, DevOps and technical information-system operations |
| Security | Technical cybersecurity, security engineering and operations |
| Data | Databases, data engineering, substantive analysis, analytics and data science |
| AI | Model development/evaluation, ML engineering, AI service implementation and technical AI data work |

Classify the recruited work. An employer mentioning AI, office work using Excel,
routine data entry, or a preference for an IT certificate does not alone establish
technical job relevance. Ambiguous digital planning, data-labelling, research and
mixed administrative/technical roles need evidence review. Experience, degree and
student eligibility remain separate attributes; this first filter does not silently
exclude experienced jobs.

Use three decisions: `IN_SCOPE`, `OUT_OF_SCOPE`, `NEEDS_REVIEW`. Save the policy
version, source/evidence references, reason, reviewer or rule identity, and input
hash. A missing description or a generic recruitment title stays unresolved until
the available notice/JD or existing extraction has been checked.

Make the decision per advertised position where a posting recruits several roles.
Include a posting if at least one role is in scope, and retain the exact selected
role/duty identifiers. For example, a combined developer/accountant notice must
not pass accounting duties into the CS link view. Existing extraction revisions
need not be rewritten merely to select their relevant roles.

Screen cheaply using source job categories, titles, Korean/English aliases, parsed
JD text and saved extracted duties. Inspect mixed and uncertain cases against the
source. Titles can establish likely relevance; competency links require actual
work evidence. Check exclusions for missed technical roles, especially generic
ALIO titles and notices with several jobs. Do not require an existing NCS or
qualification link to enter the scope: that would hide matching failures.

## 2. Add a common source interface and preserve existing identities

Define a normalized posting interface with `source_id`, `source_posting_id`,
source snapshot, canonical posting identity, employer/title, job categories,
available narrative fields, attachment references and evidence/content hashes.
ALIO becomes the first adapter. Later sources map into this interface and reuse
the same scope, review and linking workflows.

Use source-qualified identities so two providers' posting ID `123` cannot collide.
Keep a compatibility mapping to current ALIO identities, attempts, revisions and
graph nodes. Do not rehash every existing input simply to introduce the interface;
prove that the ALIO adapter preserves the source content and existing evidence
bindings. Cross-provider duplicates retain their provenance; deduplication does
not transfer a reviewed link between different source texts without verification.

Update source selection, prepared-input lookup, status reporting and publication
to resolve the common identity. A second-source fixture with colliding native IDs
must pass before claiming source independence. Implementing additional live
connectors is separate from providing this interface.

## 3. Audit and reuse the work already paid for

Produce a frozen report for every selected position, resolving historical/current
source hashes, bundles, production attempts, extraction revisions, proposed links
and decisions. Record the exact next action and its reason.

| Available result | Next action | Additional provider calls |
|---|---|---|
| Current accepted extraction and supported accepted links | Reuse and expose in the CS view | None |
| Validated extraction and saved NCS proposals awaiting review | Review saved source evidence and proposals; publish supported links | None |
| Correct extraction, categorization never completed | Reuse extraction; complete only missing categorization if source review cannot resolve it | Categorization only, if needed |
| Incorrect role assignment or small evidence-bound correction | Create and review a corrected revision; reassess affected links | None if source review resolves it |
| Correct extraction but weak/missing NCS shortlist | Search the catalogue again and review candidates | None for retrieval/review; categorization only if needed |
| New/changed source with no reusable correct extraction | Prepare/reuse documents and extract the selected job evidence | Extraction, then categorization if needed |
| Unreadable or absent duty evidence | Record an evidence gap and recover the source when possible | Do not repeatedly ask a model to infer missing text |

The first audit, filtering, saved-output review, database joins and publication
require **zero new OpenRouter calls**. Review still requires work; it is not an
automatic consequence of schema validation.

`REUSE_CACHE=Y` requires an exact eligible cache match. The cache includes request
content, model/options, prompt/validator version, source hash and categorization
catalogue/retrieval context. Some paths also include the extraction revision ID.
Changing defaults or migrating identities can cause misses. Reusing an existing
accepted revision directly is preferable to rerunning a workflow in the hope of
a cache hit. Preserve the actual producing model and prompt metadata.

Inspect saved rejected outputs before deciding to retry. Correctable outputs can
become reviewed child revisions; raw invalid responses must not be relabelled as
successful. Evaluation outputs remain evaluation evidence and are not promoted
into production by this plan.

## 4. Finish NCS links for the selected jobs

For each in-scope position, review its duty evidence and all usable saved proposals.
Use current accepted NCS definitions and occupational context. Prefer relevant
software/IT/data/AI candidates during retrieval, while retaining a controlled
wider search for work that crosses occupational boundaries. The qualification
scope must not restrict NCS retrieval.

When the original shortlist missed the right unit, search Korean names, aliases,
definitions and the NCS hierarchy locally. A reviewed source-backed match can be
recorded without a new provider request. Explicit source NCS codes are leads to
verify, especially if they identify an occupation or omit a competency version;
they are not automatically duty-level matches.

When additional model help is necessary, use `llm/categorize_reviewed.hwf` on exact
accepted revision IDs. Use `llm/enrich.hwf` with exact inputs only for missing or
unusable extractions. Do not use `enrich_changed.hwf` alone to finish categorization:
it skips successful extractions even when their categorization is incomplete.
Specify verified prompt/model options explicitly; workflow defaults are not a
guarantee that the previous request settings will be reused.

Treat NCS coverage as the primary completion requirement: aim for at least one
supported competency for every in-scope position with sufficient duty evidence,
and inspect material duties that remain uncovered. One generic link must not
disguise a missed specialized role. For any remaining gap, record whether it is
missing evidence, a retrieval problem, unresolved review, or an investigated
catalogue gap. Never manufacture a match to reach a coverage target.

Import decisions through the existing review workflows and publish through
`llm/publish_links.hwf`. Record assistant review as assistant review.

## 5. Join related qualifications and exams

Traverse accepted NCS competency links to the existing authoritative qualification
mappings, then to QNet exam data using their recorded identifiers and versions.
These are database/reference joins and do not need an LLM.

For accepted units outside the existing 11-occupation fetch scope, expand the
reference policy deliberately to cover the selected IT work. Update the partition
planner, fixed-count validation and dependency checks together; fetch missing
reference mappings and relevant exam data. Report separately an unfetched scope,
a fetched empty mapping, an unresolved identifier and a qualification with no
loaded exam schedule. Do not call each of these simply “no qualification.”

Expose the path as “related qualification through NCS.” It does not mean the
employer requires that credential. The current duty-only extraction deliberately
does not model complete eligibility requirements. Any future “required/preferred
certificate” edge needs explicit posting evidence and a separate decision.

Missing qualifications do not block an otherwise supported job-to-NCS link.

## 6. Make cost and completion visible in Hop

Add manual orchestration and reports around the existing workflows. Proposed
entry points (not yet implemented):

- `cs/assess.hwf`: pin source snapshots, classify positions, inventory reusable
  results, export unresolved cases and a proposed request/cost report. No paid calls.
- `cs/complete.hwf`: accept that frozen selection, process only the listed missing
  stages, and prepare review packets. Model calls remain controlled by
  `EXECUTE_REQUESTS`, exact IDs, request limits and budget limits.
- `cs/report.hwf`: report selection, extraction, review, NCS publication and
  qualification coverage separately for the pinned run.

The assessment must show cache hits, no-call review work, extraction-only work,
categorization-only work and work requiring both stages. Estimate the remaining
request cost using actual selected inputs and applicable model prices at execution
time. The 66 pending and five failed postings in the whole corpus are not a paid
request estimate: some may be outside scope or have reusable historical work.
Pilot the remaining paid path on a few representative cases before expanding it.

On refresh, rerun scope selection only where source content or the scope policy
changed. A filter-policy change alone does not require re-extraction. Reuse valid
unchanged outputs; assess affected NCS links when the catalogue changes and refresh
qualification/exam joins without re-extracting jobs. Preserve previous snapshots
and review provenance. The first rollout uses manual triggers.

## Delivery order and acceptance checks

1. **Baseline and scope report:** pin the current corpus; enumerate included,
   excluded and unresolved positions; audit all saved outputs for included jobs.
   Deliver the actual CS denominator and a zero-call/paid-work split.
2. **Shared source interface and scope workflows:** preserve existing ALIO lineage;
   test another source's shape and native-ID collisions. Check mixed-role notices,
   misleading keywords and technical jobs under generic titles.
3. **Reuse and publish:** review usable saved outputs for selected positions and
   publish supported links. Report the resulting coverage before new calls.
4. **Targeted gap completion:** resolve remaining source/retrieval issues, then
   execute only justified missing LLM stages within a reported budget.
5. **Qualification coverage and verification:** fetch missing in-scope reference
   partitions, join qualifications/exams and verify PostgreSQL/Neo4j agreement.

The completion report must count both postings and positions: in scope,
unresolved scope, with usable duties, with accepted/published NCS links, with
related qualifications, and each outstanding reason. Give NCS coverage over all
in-scope positions and over those with sufficient duty evidence; neither denominator
may be defined by whether matching succeeded. Track material duty gaps as well.

Verify that selected-position links do not leak from other roles, replay produces
no duplicates, stale/revoked links disappear from current views, source identities
do not collide, and unchanged selections produce no new provider calls. Read back
the actual Neo4j paths and counts. Publish unresolved exceptions with their reason
rather than describing source loading alone as completion.
