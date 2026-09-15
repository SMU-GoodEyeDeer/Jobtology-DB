# Reviewed country, experience and position scope

This stage prepares the source-bound country/experience inputs needed by
[the cohort specification](../../docs/implementation-plan.md#111-posting-cohort).
It records assessments separately from the source posting. A Korean API, an
organization address or a posting title alone does not establish a domestic,
entry-level vacancy.

**Native PostgreSQL/Hop tests passed locally; not deployed to Goldship.**
Attachment processing remains [on hold](../../docs/hop-migration/attachment-status.md).
The workflows below use existing database records and perform no downloads or
model calls. Do not use them to accept new attachment-derived assessments during
the hold. Production source reviews and profile assessments are still required.

## Run order in Hop

Use `jobtology-postgres` and the `ontology-local` run configuration. Paths below
are relative to the Hop project folder. Install `cohorts/install.hwf` after the
ontology installer. This adds both the [duplicate ledger](README.md) and profile
ledger; it does not create a schedule or change a source payload.

1. Prepare the exact source release, including any intended historical source
   observations. Freeze extraction reviews and assemble the reviewed claims.
2. Resolve and independently review typed requirements with the ontology
   requirement workflows. Run `ontology/freeze_requirements.hwf` with the exact
   `RELEASE_ID`. This must precede reading/importing a profile: profile evidence
   includes the selected requirement interpretations and their reviews.
3. Run `cohorts/read_cohort_profile_input.hwf` with `RELEASE_ID`, `ENTITY_ID`
   (for example, `urn:jobtology:jobPosting:job_alio:123`) and `PREVIEW=Y` for a
   draft. Preview **Preview JSON here** in the corresponding `.hpl`; inspect
   `result_json` and save its `proposal_template` as a UTF-8 JSON file.
4. Fill the template using the displayed normalized `source_binding.fields`,
   selected positions, requirement atoms and typed conditions. Keep the returned
   source hash, posting identity and parent ID. Fill the actual author,
   resolver version and reason. The template deliberately starts with unknown
   values and unresolved scope; it is not an automatic assessment.
5. Run `cohorts/import_cohort_profile.hwf` with `PROPOSAL_FILE` set to the full
   container path, such as `${PROJECT_HOME}/cohort-profile.json`. The file must
   be a JSON object with unique keys, no unknown properties and at most 1 MiB.
   Import returns a proposal ID without accepting it.
6. A different reviewer runs `cohorts/review_cohort_profile.hwf` with that
   `PROPOSAL_ID`, a new `REVIEW_ID` UUID, explicit `DECISION=ACCEPT` or `REJECT`,
   and actual `REVIEWER`, `REVIEWER_KIND`, `NOTES`. Reuse the UUID only for an
   identical retry. Inspect role applicability, country and experience meaning,
   including alternatives and conditions; valid JSON and matching quotations
   do not prove those interpretations correct.
7. Run `cohorts/freeze_cohort_profiles.hwf` with `RELEASE_ID`. Read the result
   through `cohorts/read_cohort_profiles.hwf` with `PREVIEW=Y`. Every selected
   source posting gets an explicit selection outcome, including unprocessed or
   unresolved postings. Replay verifies the frozen membership and does not
   adopt newer decisions.

Blank `RELEASE_ID` in a reader selects only an active published release. It is
not a shortcut to the latest draft. Failed and revoked releases are unavailable;
explicit draft reads require `PREVIEW=Y`.

## Fill the profile without inventing missing information

The root `posting_experience_label` is `ENTRY`, `INTERNSHIP`, `UNRESTRICTED`,
`MIXED`, `EXPERIENCED` or `UNKNOWN`. A known label requires
`posting_label_evidence`. A resolved proposal must contain exactly one track for
every reviewed position, including positions that will be excluded.

| Track field | Required interpretation |
|---|---|
| `position_id` | Exact selected position ID from the template; retain every position. |
| `country_scope`, `country_evidence` | `KR`, `NON_KR`, `MIXED` or `UNKNOWN`; known values need exact source evidence for the job's work location. |
| `experience_policy`, `policy_basis` | Same policy vocabulary as the root; basis is `EXPLICIT_LABEL`, `PARSED_RANGE` or `UNKNOWN`. Known policies need `experience_evidence`. |
| `minimum_months`, `maximum_months` | Keep absent bounds null. Every supplied bound, including zero, must occur in a referenced, reviewed total-experience condition. |
| `experience_requirement_ids` | Sorted unique IDs of selected `REQUIRED`, `POSITIVE`, `EXPERIENCE` claims with null `context_id`, applicable to this position. Preferred or skill-specific experience cannot supply the total-experience cutoff. |
| `considered_atom_ids` | Keep the exact sorted set returned for this position, including unresolved atoms. These are `source_claim_id/node_index` references, not typed claim IDs. |
| `included_requirement_ids` | Sorted unique selected typed claim IDs applicable to this position and chosen scope. Another position's claims cannot be included. |
| `cohort_scope`, `scope_notes` | `POSITION` includes all relevant, reviewed requirements with known applicability; `REVIEWED_SUBSET` explicitly selects a smaller evidenced scope; `UNRESOLVED` includes no requirements. Explain the scope. |
| `scope_evidence`, `entry_track_scoped`, `domestic_track_scoped` | A reviewed subset requires evidence. Set a scoped flag only when that entry or domestic subtrack is explicitly separable. The domestic flag alone never makes senior experience eligible. |

Each citation has `field`, `start_offset`, `end_offset` and `excerpt`. Offsets are
zero-based, half-open **Unicode code points in the displayed NFC/LF normalized
field**, not UTF-8 bytes or JavaScript UTF-16 units. Copy the quotation exactly.
For example, in `😀 서울\n대한민국`, `서울` occupies offsets `[2, 4)`. The importer
checks the field, bounds and exact substring and preserves field/excerpt hashes.

`ENTRY`, `INTERNSHIP` and `UNRESTRICTED` track policies require explicit label
evidence. Do not turn an absent experience field into zero months or
`UNRESTRICTED`. A maximum of 24 months must be an actual reviewed maximum; a
minimum of 24 months does not establish it. Preserve source AND/OR and conditional
context when deciding whether separate bounds belong together. Referenced
experience claims must be included in a reviewed subset that uses those bounds.

For a posting with separately named 신입 and 경력 positions, assess both. The
qualifying new-graduate track uses `REVIEWED_SUBSET`, appropriate scope evidence
and its own claims. The experienced position stays in the profile with its
exclusion reasons; its requirements are not inherited by the junior position.
If the source does not establish the separation, leave scope unresolved.

When extraction is not accepted or contains no reviewed positions, the template
is `UNRESOLVED`, with a reason and no tracks. It cannot be accepted as a profile.
An otherwise accepted extraction may also remain unresolved for ambiguous scope
or insufficient evidence.

Manual proposals use `method=MANUAL`, `actor_kind=human`, and null model/prompt
IDs. Model-produced proposals use `MODEL_INFERRED`, `actor_kind=assistant`, and
actual model/prompt IDs. These fields record provenance and do not call a model.
Review status is `HUMAN_ACCEPTED` or `ASSISTANT_REVIEWED`; confidence remains null
and `UNASSESSED`. This stage does not fabricate calibration or production review.

## Read outcomes and make corrections

Frozen selection outcomes are `EXTRACTION_NOT_ACCEPTED`, `NOT_PROPOSED`,
`SOURCE_CHANGED`, `PENDING`, `REJECTED`, `UNRESOLVED` and `REVIEWED`. Only the last
produces reviewed tracks. A newer pending or rejected proposal does not fall
back to an older acceptance. Each track carries its selected review, profile and
country/experience/scope exclusion reasons.

`country_experience_scope_eligible=true` means only those three filters pass.
Unknown country is excluded. Unknown experience is excluded unless the posting
has an explicit entry/internship label. An explicit qualifying track policy or
reviewed maximum of at most 24 months can pass the experience filter. Mixed
postings additionally require an explicitly reviewed claim subset. Mixed-country
tracks require a reviewed domestic subset. None of these booleans publishes a
cohort, demand statistic or graph claim.

For a correction, obtain a new template and retain its latest `parent_id`.
Import and independently review it, then freeze a new release. Existing releases
retain their original selection and evidence. Identical source and review
bindings can reuse a proposal across releases; re-reviewing an extraction or
typed requirement changes the binding and requires a fresh assessment even when
the source wording is unchanged. Original source support, proposals, decisions
and input/review hashes remain available in the read result.

The input reader's `current_proposal` and `current_decision` are editing context
and can be newer than the requested release. Use `read_cohort_profiles.hwf` for
that release's actual frozen selection.

## Remaining integration and validation

The locally tested [cohort builder](cohorts.md) combines these profiles with the
selected product occupation, source scope, exact 180-day KST window, Korean
language rule and duplicate representatives. It persists inclusion/exclusion and
claim support. Demand aggregates, deployment and publication checks remain
unfinished. Date precision and raw source fields remain unchanged here.

A release with frozen profiles cannot be sealed by a graph manifest that omits
their membership. The error is `COHORT_PROFILE_GRAPH_INTEGRATION_REQUIRED` until
the versioned graph/interchange adapter is implemented. Do not write a manifest
by hand to bypass it. Releases without a profile freeze retain their existing
sealing behavior.

Developer checks use fresh owned PostgreSQL/Hop containers and synthetic Korean
records; they never make provider calls or operate on Goldship:

```sh
python hop/cohorts/tools/build.py
python hop/cohorts/tests/profiles.py
python hop/cohorts/tests/duplicates.py
```

The profile driver retains native workflow logs and `profile-report.json` in its
printed fixture directory. The final run covered nine synthetic postings, seven
reviewed profiles and three tracks passing the country/experience/scope filter;
the duplicate regression also passed with the expanded installer. See the
[completion evidence](../../docs/hop-migration/ontology-completion.md#reviewed-countryexperience-and-position-scope--2026-09-13-kst).
Deployment, real source assessments and the remaining cohort/publication work
are still required for production use.
