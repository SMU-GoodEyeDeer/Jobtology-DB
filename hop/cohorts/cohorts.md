# Persist a posting cohort in Hop

**Native PostgreSQL/Hop tests passed locally; not deployed to Goldship.**
This stage selects a reproducible set of postings for one product
occupation. It preserves every input identity and exclusion decision, with
normalized support rows for the qualifying positions and claims. Attachment
processing remains [on hold](../../docs/hop-migration/attachment-status.md).

## Prepare the release and run the workflow

Use the existing `jobtology-postgres` connection and `ontology-local` run
configuration. Paths below are relative to the project mount.

1. Install `ontology/install.hwf`, `editorial/install.hwf` and
   `cohorts/install.hwf` in that order. Then run
   **`cohorts/install_builder.hwf`**. The builder has a separate installer because
   it requires both the editorial occupation and cohort preparation modules.
   It fails explicitly when these prerequisites are absent.
2. Prepare the intended source release. Bind historical posting observations
   with `ontology/bind_observations.hwf` before freezing extraction reviews.
   Pin the reviewed editorial catalogue and assemble the independently reviewed
   extraction claims.
3. Finish the intended occupation, typed-requirement, profile and duplicate
   reviews. Run `editorial/freeze_occupations.hwf`,
   `ontology/freeze_requirements.hwf`,
   `cohorts/freeze_cohort_profiles.hwf` and `cohorts/freeze_duplicates.hwf`.
   Requirement freezing must precede [profile input/review](profiles.md).
   An unresolved posting can remain explicitly unresolved; it is not silently
   accepted to make the builder run.
4. Run **`cohorts/build_cohort.hwf`** with the exact `RELEASE_ID`,
   `OCCUPATION_ID` and `AS_OF`. The release must still be unsealed. `AS_OF` is a
   KST date in `YYYY-MM-DD` form and cannot be later than that release's creation
   date in KST. It controls the posting-date window; the selected release still
   identifies the source and review versions used.
5. Copy the returned `cohort_id`. Run `cohorts/read_posting_cohort.hwf` with
   `RELEASE_ID`, `COHORT_ID`, `PREVIEW=Y` for a draft, and optional `AS_AT` with an
   explicit time zone. Blank `AS_AT` means now. Preview **Preview JSON here** in
   the matching `.hpl` to inspect `result_json`.
6. Inspect each decision through `cohorts/read_cohort_members.hwf` with the same
   release/cohort and `PREVIEW=Y`. `PAGE_SIZE` is 1–100; leave `CURSOR` blank for
   the first page, then copy the returned `next_cursor` until it is null. The
   opaque cursor is bound to the cohort's immutable manifest and is safe to
   pass through Hop's startup parameter syntax.

The four allowed occupation IDs are:

```text
urn:jobtology:occupation:product:AI_ENGINEER
urn:jobtology:occupation:product:BACKEND_DEVELOPER
urn:jobtology:occupation:product:FRONTEND_DEVELOPER
urn:jobtology:occupation:product:DATA_ANALYST
```

They must be selected from the release's pinned catalogue. Each cohort contains
exactly one occupation. Run the builder once per desired occupation/date. Replay
with identical frozen inputs returns the same cohort and verifies its contents;
it does not duplicate members or select later reviews.

## Fixed selection rules

The `posting-cohort-job-alio-v1` filter is persisted in full with its hash. It
requires JOB-ALIO, the chosen reviewed product occupation, a qualifying reviewed
KR/experience/position scope, Korean content, and an inclusive interval from
`AS_OF - 179 days` through `AS_OF`. This is exactly 180 KST calendar dates.
Saramin requires a new source/methodology version; it is not enabled here.

Country and experience decisions come from the frozen profiles. The builder
does not infer KR from a Korean API or guess an unknown experience range.
Only the selected claims of qualifying tracks can enter cohort claim support.
In particular, a mixed posting's senior claims do not accompany its eligible
junior track.

For language checking, the description is the source API body assembled from
`description_text`, `duties_text`, `eligibility_text`, `preference_text`,
`disqualification_text` and `selection_text`, in that order, joined by newlines
with the title. Empty or absent fields are skipped. The reader records the exact
field hashes and character counts. This does not read attachments or generated
summaries. The current JOB-ALIO normalizer supplies no locale; no Korean locale
is assumed. An explicitly supplied normalized source `locale` such as `ko-KR`
can satisfy the locale branch; otherwise at least 100 Hangul syllables and 30%
Hangul among all letter characters are required. Counting uses NFC/LF text and
PostgreSQL's versioned `pg_c_utf8` Unicode collation. Emoji, digits and punctuation
do not increase the letter denominator.

For each accepted duplicate group, choose one representative **among members
that pass the other filters**. An ineligible newer record does not suppress an
eligible historical member. The order is newest source-modified timestamp,
otherwise source-published timestamp/date, otherwise retrieval timestamp; ties
use JOB-ALIO before Saramin and then lexical source posting ID. Only JOB-ALIO is
eligible in this methodology.

The current source supplies `date_posted` with day precision and no modified or
published instant. The temporal record keeps that date, its field and precision,
with `effective_timestamp_at=null`. A KST day-start value is used solely as the
deterministic ordering key, explicitly marked `KST_DAY_START_ORDER_KEY_ONLY`.
It is not asserted as the actual publication time. Explicit normalized source
timestamp fields, when present, must contain a valid ISO timestamp with a zone;
malformed values are excluded rather than silently ignored.

## Inspect counts, excluded rows and evidence

Every source posting has exactly one membership outcome:

- `INCLUDED`: the eligible representative that contributes to the cohort count.
- `DUPLICATE`: eligible, with another representative from its reviewed group.
- `EXCLUDED`: fails one or more named filters; the reader retains all reasons.

Membership keeps the source revision, group/representative, language metrics,
temporal fields and exact occupation/profile/duplicate/observation selections.
Tracks retain their own eligibility and scope. `posting_cohort_claim` stores
individual selected claim references, normalization decisions, requirement keys,
necessity and polarity; it does not put a large support-ID array on a graph node.
All original and non-representative source records remain stored.

The manifest's `included` count is the fixed historical cohort size. Closed,
expired or subsequently stale postings are still historical members when they
meet the cohort filters. `active_fresh_count` is separate: it evaluates the
release-bound observations at `AS_AT`, checks elapsed deadlines and requires both
the selected source watermark and posting's last observation to remain within
the JOB-ALIO 30-hour freshness window. A later source run does not silently swap
the release's evidence. Activate a properly prepared new release for refreshed
source content and review selections.

`AS_AT` must be at or after the release's creation timestamp. Changing it can
change the active/fresh count; it does not mutate historical membership. Failed,
revoked and unpublished release read gates still apply. Blank `RELEASE_ID`
means only an active published release, not the latest draft.

## What remains before publication

This stage persists cohort membership and qualifying claim support. Demand
aggregates, the minimum-30 denominator rule for ratios, calibrated publication
and graph/interchange integration remain separate work. The reader reports
`publication_ready=false`; a stored cohort is not proof of complete extraction
or a published demand statistic.

A graph manifest must eventually carry the exact duplicate, profile and cohort
memberships. Until the versioned adapter is implemented, sealing such a release
fails instead of omitting them. Do not hand-edit a manifest to bypass these
guards. No scheduler, paid call, extraction review, graph activation or source
refresh is initiated by building or reading a cohort.

Developer verification uses synthetic Korean fixtures and fresh disposable
containers:

```sh
python hop/cohorts/tools/build.py
python hop/cohorts/tests/cohorts.py
```

The driver retains native logs and `cohort-report.json` in its printed fixture
directory. Production use additionally requires deployment, real source and
catalogue reviews, and the remaining publication work.
