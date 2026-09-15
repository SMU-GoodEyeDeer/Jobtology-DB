# Typed requirement normalization

This stage gives reviewed Korean requirements comparable types and stable keys.
It does not fetch attachments, call a model, approve the source extraction, or
publish a release. Attachment processing remains [on hold](../../docs/hop-migration/attachment-status.md).

The existing `ontology.claim` records are source groups. A group can mean
`(내과 전문의 OR 응급의학과 전문의) AND 경력 2년 이상`. Keep that expression and its
position scope. Normalizing the experience atom to `minimum_months: 24` does not
make each specialty credential independently mandatory.

## Operator sequence in Hop

1. Prepare a release and bind observation history as described in
   [the ontology guide](README.md). Run `assemble_reviewed.hwf` to select existing
   extraction/link decisions and assemble their exact source evidence. This
   stage only processes accepted source extractions; structural validation alone
   does not create claims.
2. Open `inspect_requirements.hpl`, set `RELEASE_ID`, and preview **Preview source
   and typed conditions**. Each row gives a `source_claim_id`, `node_index`, the
   source text, its expression and evidence, latest proposal, latest review, and
   any already-frozen selection. This is a live review queue, not publication.
3. Save a UTF-8 JSON object matching
   [the input schema](schemas/requirement-normalization-v1.schema.json) in the
   mounted project, for example `${PROJECT_HOME}/data/ontology/requirement.json`.
   Use a real source atom's IDs. Do not use an expression's `all_of`, `any_of`,
   `if_then` or `except` node as an atom. `node_index: -1` is only for a source
   requirement with no expression tree.
4. Run `import_requirement.hwf` with `NORMALIZATION_FILE` pointing to that file.
   The log returns `normalization_id`. A proposal begins without a review.
5. Inspect the typed meaning, original words, target definitions, polarity,
   necessity, position scope and complete expression. Run `review_requirement.hwf`
   with that ID, `DECISION=ACCEPT` or `REJECT`, actual reviewer identity/kind and
   evidence-based `NOTES`. An assistant must use `REVIEWER_KIND=assistant`.
   The reviewer identity must differ from the proposal author; proposal import
   itself never supplies the independent review decision.
6. Once the review cut is intentional, run `freeze_requirements.hwf` with
   `RELEASE_ID`. It freezes an outcome for **every** source atom, including those
   with no proposal. Repeating the workflow verifies and reuses that exact cut.
   Repeat this step while the draft is unsealed. After graph sealing, replay the
   graph loader to verify the sealed inventory; draft-editing workflows reject it.
7. Run `read_requirements.hwf` with `RELEASE_ID` and `PREVIEW=Y` to inspect frozen
   outcomes, evidence and remaining issues. `PREVIEW=N` requires a published
   release; a blank ID never silently selects the latest draft.

Example file for an atom that explicitly says `경력 2년 이상`:

```json
{
  "schema_version": "hop-requirement-normalization-v1",
  "release_id": "YOUR_UNSEALED_RELEASE",
  "source_claim_id": "COPY_THE_SOURCE_CLAIM_HASH",
  "node_index": 4,
  "parent_id": null,
  "actor": "actual-proposal-author",
  "reason": "The cited atom explicitly requires at least two years of experience.",
  "resolver_version": "manual-normalization-v1",
  "necessity": "REQUIRED",
  "polarity": "POSITIVE",
  "condition": {
    "kind": "EXPERIENCE",
    "context_id": null,
    "minimum_months": 24,
    "maximum_months": null
  }
}
```

The `4` above is illustrative. Copy the actual leaf index from inspection.
Evidence IDs, source text, posting revision and the entire expression are bound
by the database from that atom. They are not supplied or overwritten by this file.

To correct a proposal, retain its source atom IDs and set `parent_id` to the latest
`normalization_id`. Earlier proposals and reviews remain immutable. A newer
pending proposal supersedes an older approval for future releases: there is no
fallback to the older accepted interpretation. Re-importing the same normalized
document is idempotent. A frozen release does not pick up later proposals/reviews;
prepare another release to select them.

## Conditions and reference checks

| Kind | Condition fields | Scope |
| --- | --- | --- |
| `SKILL` | `target_id`, `target_kind`, nullable `proficiency_scheme_id` and `minimum_proficiency` pair | `CAPABILITY` |
| `LANGUAGE` | Same fields; must target a language skill | `CAPABILITY` |
| `CREDENTIAL` | `target_id` for a canonical qualification | `CAPABILITY` |
| `EDUCATION` | `minimum_degree`, sorted `accepted_major_groups`, nullable `accepts_expected_graduate` | `CAPABILITY` |
| `EXPERIENCE` | Nullable occupation/skill `context_id`, minimum/maximum months | `CAPABILITY` |
| `PROJECT` | `minimum_count`, `portfolio_required`, sorted `capability_ids` | `CAPABILITY` |
| `LOCATION` | Sorted `administrative_codes`, `work_mode` | `POSTING_FILTER` |
| `ELIGIBILITY` | Reviewed `vocabulary_id`, `code`, exact atom `source_text` | `POSTING_FILTER` |
| `AVAILABILITY` | Nullable ISO `earliest_start` date and `schedule_text` | `POSTING_FILTER` |

Every canonical reference must be selected in that release. Targets retain their
exact revision and payload hash; a later release cannot reuse an approval against
a different or absent target revision. NCS targets use full versioned
`ncsCompetency` identities, never an unversioned family or a generic skill.
`LANGUAGE` requires a `skill` revision whose payload has `kind: LANGUAGE`.

The planned editorial catalogue must supply references absent from the six
external feeds. Nothing in this stage invents or installs those concepts:

- A proficiency reference is a `conceptScheme` revision with `kind: PROFICIENCY`
  and an `ordered_values` array containing the selected integer level.
- An eligibility vocabulary is a `conceptScheme` revision with `kind: ELIGIBILITY`,
  `review_state: HUMAN_ACCEPTED`, and a `codes` object containing the approved
  code/definition. Editorial provenance and release pinning remain required work;
  adding that payload is not a substitute for their publication checks.
- Each administrative code must identify exactly one selected `place` revision
  with the corresponding `administrative_code`.
- Education field groups use the explicit enums from the implementation plan.
  Duplicate set members are removed and sets are sorted before key creation.

Unknown or compound-unsplit meaning stays explicit:

```json
{"kind":"UNRESOLVED","mention":"EXACT_ATOM_TEXT","reason":"NO_MATCH"}
```

Other reasons are `AMBIGUOUS` and `UNSUPPORTED_CONDITION`. Unresolved conditions
have no requirement key and cannot be accepted. Necessity `UNSPECIFIED` also
cannot be accepted. `NEGATED` and `NO_CONSTRAINT` remain distinct from `POSITIVE`;
for example, do not turn `경력무관` into a positive experience demand. The validator
checks shape/references/bounds, while semantic review must check what the source
actually means. It does not infer correctness from plausible field values.

## Keys, reviews and completion limits

`requirement_key` is SHA-256 over JCS canonical JSON of the normalized condition
specified in implementation-plan §9.5. Capability keys omit the redundant
`target_kind`; all keys exclude posting identity, necessity, polarity, author,
review and source expression. The posting-filter condition retains its prescribed
fields, including the eligibility source text. Set fields are sorted/deduplicated.

The native SQL serializer deliberately supports the exact schema's JCS subset:
ASCII object keys, Unicode string values, booleans/null, arrays and 32-bit integer
values. It rejects unsupported numeric/key forms. This key is distinct from the
existing `hop-ontology-jsonb-v1` hash used for immutable proposal/membership IDs.

Review decisions and confidence are separate. A human `ACCEPT` is recorded as
`HUMAN_ACCEPTED`; an assistant `ACCEPT` is `ASSISTANT_REVIEWED`, never an invented
human or automatic approval. The input schema rejects a `confidence` field.
Confidence remains null/`UNASSESSED` until the planned calibrated assessment
layer exists. No reviewed normalization currently passes that publication gate.

Frozen outcomes are `NOT_PROPOSED`, `PENDING`, `UNRESOLVED`, `REJECTED`,
`TARGET_REVISION_MISMATCH` or `REVIEWED`. Additional issues preserve unresolved
position scope and pending guarded-rule normalization. A reviewed atom does not
resolve its parent group or posting by implication. Ordinary AND/OR relationships
remain in the bound source tree; `if_then`/`except` still need their guarded
semantics connected to canonical conditions.

The ledger and native import/review/freeze/read workflows feed the
[typed Neo4j projection and JSON-LD v3 export](requirement-graph.md). That guide
explains the difference between source groups, proposals and reviewed typed
claims. **Calibrated confidence, guarded-rule binding, editorial concepts,
production normalization, occupation assignments, cohorts and final activation
remain unfinished.** A successful draft projection does not complete those stages.

Runtime storage is `ontology.requirement_normalization`, `requirement_decision`,
`requirement_freeze`, `requirement_selection` and `requirement_membership`.
`ontology.typed_requirement_issue` reports the remaining stage-specific issues.
No scheduled trigger or model spending is added.

Development verification uses fresh disposable containers:

```bash
python hop/ontology/tools/build.py
python hop/ontology/tests/requirements.py
```
