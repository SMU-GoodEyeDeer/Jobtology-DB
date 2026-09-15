# Cohort preparation

**Native PostgreSQL/Hop tests passed locally; not deployed to Goldship.**
This module implements the reversible duplicate groups required by
[the cohort plan](../../docs/implementation-plan.md#111-posting-cohort).
Every source posting remains stored under its original identity. A group records
a reviewed interpretation that several postings describe the same recruitment;
it does not merge organizations, delete postings or choose an occupation.

The separate [country, experience and position-scope guide](profiles.md) covers
profile proposals bound to reviewed positions and typed requirements. Both use
the same installer; the duplicate-group workflow is described below.

The [persisted cohort guide](cohorts.md) combines these inputs with frozen
occupations and observations. Its separate builder installer and native tests
cover the exact date/language filters, representative ranking and normalized
track/claim support. Demand statistics and graph integration remain pending.

The runtime consists of native Hop workflows and PostgreSQL functions, using the
existing `jobtology-postgres` connection and `ontology-local` run configuration.
Python only builds artifacts and runs disposable tests. There are no downloads,
attachment operations or model calls in these workflows. Attachment work remains
[on hold](../../docs/hop-migration/attachment-status.md).

## Create and review a group

Install `cohorts/install.hwf` after `ontology/install.hwf`. It adds the contracts
and append-only duplicate/profile ledgers. It does not install an automatic matching
algorithm or add a scheduled job. The ordinary source refresh remains independent.

Prepare a source release before using this module. If the intended release
includes historical postings, run `ontology/bind_observations.hwf` before
freezing duplicate membership. Adding source revisions afterward requires a new
draft; frozen membership cannot silently grow.

Paths below are relative to `${PROJECT_HOME}/cohorts/`. Each reader has a matching
`.hpl`; preview **Preview JSON here** to inspect `result_json`.

| Workflow | Parameters | Action |
|---|---|---|
| `read_duplicate_input.hwf` | `RELEASE_ID`, `CLUSTER_ID`, `MEMBER_IDS`, `PREVIEW` | Read exact source revisions/support and an editable proposal template. |
| `import_duplicate.hwf` | `PROPOSAL_FILE` | Import one UTF-8 JSON proposal; does not accept it. |
| `review_duplicate.hwf` | `REVIEW_ID`, `PROPOSAL_ID`, `DECISION`, `REVIEWER`, `REVIEWER_KIND`, `NOTES` | Append an independent ACCEPT or REJECT. |
| `freeze_duplicates.hwf` | `RELEASE_ID` | Freeze selected decisions and one group assignment per posting. |
| `read_duplicates.hwf` | `RELEASE_ID`, `PREVIEW` | Inspect frozen membership, all relevant outcomes and original proposal/review evidence. |

1. Choose a stable UUID for the duplicate group. `SELECT gen_random_uuid();`
   generates a new one without storing a group. Keep that UUID for corrections
   to this group; a different UUID creates a different comparison family.
2. Run `read_duplicate_input.hwf` with an exact assembled release,
   `PREVIEW=Y`, that UUID and two or more posting identities separated by `|`.
   For example:
   `urn:jobtology:jobPosting:job_alio:123|urn:jobtology:jobPosting:job_alio:456`.
   All members must be job postings selected by that release.
3. Inspect every `source_binding` entry. It includes the exact revision/payload,
   organization and posting fields, plus original list/detail support references,
   source IDs, run IDs, raw hashes and field lineage. Compare the recruitment
   identity, dates, positions and complete notice context. Matching Korean titles
   or organization names alone do not establish duplication.
4. Save `proposal_template` to a UTF-8 JSON file in the Hop project mount. Fill
   `actor`, `resolver_version` and an evidence-based `reason`. Keep the returned
   sorted `member_ids`, `cluster_id`, `parent_id` and `source_binding_hash`.
   Changing members requires reading a fresh template for that member set.
   Import the file with `PROPOSAL_FILE` set to its full container path.
5. A different reviewer records the decision using the returned proposal ID.
   Use the actual reviewer identity and kind (`human` or `assistant`), and a new
   `REVIEW_ID` UUID. Reuse that review UUID only when retrying the identical
   decision, reviewer and notes. `DECISION` defaults to `REJECT`; an acceptance
   must be explicit.
6. Run `freeze_duplicates.hwf` once the intended decisions are ready, then inspect
   `read_duplicates.hwf`. Freezing keeps exact proposal/review cutoffs and hashes;
   replay verifies them rather than selecting later decisions.

For a manual proposal, use `method=MANUAL`, `actor_kind=human`, and null model/
prompt IDs. A proposal actually produced by a model uses `MODEL_INFERRED`, the
assistant actor kind and recorded model/prompt IDs. Those fields record
provenance; they do not initiate inference. Neither path accepts a supplied
confidence score. Selected reviews remain `HUMAN_ACCEPTED` or
`ASSISTANT_REVIEWED`, with `confidence=null`, `confidence_state=UNASSESSED`.

Files must be JSON objects with unique keys and at most 1 MiB. The schema requires
2–1,000 distinct, sorted posting identities. Unknown fields, invalid UUIDs,
missing source support, a changed source hash, self-review, stale parents and
inconsistent actor/model provenance fail explicitly.

## Frozen outcomes and reversibility

The reader reports `NOT_FROZEN` before selection, with `current_candidates` for
review planning. After selection it reports `FROZEN`, its immutable membership
and one `members` row for every source posting in the release.

| Selected outcome | Grouping behavior |
|---|---|
| `ACCEPTED` | All members use `group_id=duplicate/<cluster UUID>`. |
| `PENDING` | Latest proposal has no accepted decision; no fallback to an earlier acceptance. |
| `REJECTED` | Latest selected decision rejects the group. |
| `SOURCE_CHANGED` | At least one selected content revision differs from the reviewed input; the old grouping is not reused. |
| `MEMBER_OUTSIDE_RELEASE` | At least one reviewed member is absent from the selected source scope; the remaining subset is not silently treated as the accepted group. |

A posting outside every accepted group uses `group_id=posting/<entity ID>` and
null cluster/proposal/decision IDs. This is a grouping default, not proof that
the posting has no duplicate. Pending and rejected comparisons remain visible in
`selections`. Families whose latest proposal has no members in this release are
outside its comparison scope.

Two accepted groups cannot overlap. The whole freeze fails with
`OVERLAPPING_ACCEPTED_DUPLICATE_CLUSTERS` and leaves no partial membership.
Correct or reject the conflicting comparison before retrying. The workflow does
not invent a transitive union that nobody reviewed.

To replace a group, obtain a new template using the same `CLUSTER_ID` and new
member set. Its parent must be the latest proposal. Import and independently
review it, then select it in a new release. Members removed from the group remain
stored and can become singletons in that release. To stop using a group, append
a REJECT to its current proposal and freeze a new release. An earlier release
keeps its original membership and review. No history is deleted.

An unchanged posting fetched again can reuse its content revision and accepted
duplicate decision. The proposal still retains the original review-time source
support. A new retrieval timestamp or source run alone does not force a new
duplicate proposal. A changed content revision does require renewed comparison.
Re-importing the same proposal and identical bound evidence through another
release also reuses its proposal ID and preserves the original capture context.

The input reader's `current_proposal` and `current_decision` are explicitly editing
context, even when inspecting an older release. Use `read_duplicates.hwf` for
that release's frozen selection. Ordinary read gates apply: an explicit draft
requires `PREVIEW=Y`; blank release uses only the active published release;
failed and revoked releases cannot be read in either mode.

## What remains before cohort statistics

This is a prerequisite, not a completed cohort builder. The group count is not
an occupation-demand denominator. The remaining cohort work must:

- Complete real country/experience assessments through the
  [profile workflows](profiles.md), including mixed-position claim scope.
  Existing source `regions` and `recruitment_type` text do not turn every
  JOB-ALIO posting into a domestic, entry-level vacancy by default.
- Apply the exact product occupation, JOB-ALIO source scope, KR filter,
  180 inclusive KST dates and Korean-language rule.
- Use only qualifying, reviewed track claims for mixed new-graduate/experienced
  postings when constructing the cohort.
- Choose one deterministic representative per accepted duplicate group using
  the plan's effective-modified-time, source-priority and posting-ID order, and
  retain every inclusion/exclusion reason.
- Persist cohort and aggregate support, distinguish historical members from
  active/fresh counts, and suppress proportions below 30 unique postings.
- Project duplicate/cohort membership to the versioned graph/interchange and
  finish the publication lifecycle and audits.

The current source contract provides `date_posted` as a date, plus
`recruitment_type`, `employment_type` and `regions` as text. It has no structured
country, locale or minimum/maximum experience policy. Narrative input is split
across eligibility, disqualification, preference and selection fields. The
profile layer preserves those source locations and reviewed position scope;
representative ranking must also retain source date precision.
The source API being Korean is not proof that every job location is in KR.

Until that graph adapter exists, the module rejects sealing a release with a
duplicate freeze if its graph manifest omits `duplicate_membership`. Existing
releases without a duplicate freeze retain their previous behavior. Do not edit
the manifest by hand to bypass this guard. Installation itself neither creates a
freeze nor blocks a previously valid source-only release.

## Developer validation

```sh
python hop/cohorts/tools/build.py
python hop/cohorts/tests/duplicates.py
python hop/cohorts/tests/profiles.py
```

The test owns fresh PostgreSQL/Hop containers and an internal network. It uses
synthetic Korean source records, manual/model proposal provenance and independent
fixture decisions; none represents a real production review or provider call.
The retained fixture directory contains native logs and `duplicate-report.json`.

The final test preserved all five source postings, selected four groups, and
verified changed/missing source members, overlapping comparisons, pending/rejected
corrections, replacement membership and cross-release import idempotence. Empty
releases and legacy graph sealing passed, as did native read/install replay with
an unchanged database fingerprint. Exact evidence paths and remaining deployment
work are in the [completion ledger](../../docs/hop-migration/ontology-completion.md#reviewed-duplicate-groups-for-cohorts--2026-09-13-kst).
