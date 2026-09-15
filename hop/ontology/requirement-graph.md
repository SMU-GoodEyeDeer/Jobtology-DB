# Typed requirements in Neo4j and JSON-LD

**Status, 2026-09-13 KST:** the tested seven-file graph/export package is deployed
on Goldship. The native installer and draft read passed; protected data, earlier
export contracts and the attachment hold were unchanged. The v3 exporter is now
available. Production typed proposals/reviews are still zero; see the
[deployment receipt](../../docs/hop-migration/ontology-completion.md#typed-graphexport-v3-live-deployment--2026-09-13-kst).

Use this after [typed normalization and review](requirements.md). It projects
frozen PostgreSQL records with native Hop SQL and Neo4j transforms. It does not
fetch attachments, run a model, create reviews or activate a release.

## Run

1. Finish the intended review cut and run `freeze_requirements.hwf` with the
   unsealed `RELEASE_ID`. Inspect `read_requirements.hwf` with `PREVIEW=Y`.
   Unprocessed and unresolved atoms remain explicit outcomes.
2. Run `load_release.hwf` with the same `RELEASE_ID`, the `ontology-local` run
   configuration and the existing private `jobtology-neo4j` connection. The
   loader verifies the frozen source/review/requirement memberships before sealing
   and loading the graph. Replaying the sealed release verifies the same inventory.
3. For interchange, run `export_jsonld_v3.hwf` with `RELEASE_ID` and `PREVIEW=Y`.
   A successfully sealed inventory is required. The workflow writes a fresh UUID
   file under `${PROJECT_HOME}/data/ontology-exports/`. Wait for workflow success.
4. Validate the copied artifact using the repository's matching v3 package:

   ```bash
   uv run --no-project --with-requirements ontology/requirements-validation.txt \
     python ontology/tools/validate.py path/to/export.jsonld
   ```

These are draft inspection steps. Reviewed conditions still have
`confidence_state=UNASSESSED` and no numeric confidence. Pending extraction,
normalization, scope, guarded-rule interpretation, calibration, editorial,
occupation and cohort work continues to block publication. A structural export
pass does not remove those blockers. `PREVIEW=N` never selects a draft.

## What the nodes mean

| Neo4j label | Meaning | JSON-LD v3 class |
| --- | --- | --- |
| `requirementClaim` | Original reviewed Korean source group and expression | `SourceRequirementGroup` |
| `requirementNormalization` | A proposed interpretation of one exact source atom | `RequirementNormalization` |
| `requirementReviewSelection` | The decision/outcome frozen for that atom in one release | `RequirementReviewSelection` |
| `normalizedRequirementClaim` | A typed interpretation with a selected `ACCEPT` decision | `RequirementClaim` |
| `typedCondition` | Canonical condition fields, including explicit null/empty values | `TypedCondition` |
| `unresolvedCondition` | Explicit unresolved mention and reason | `UnresolvedCondition` |
| `requirementTargetBinding` | Exact target identity, revision, payload hash and role | `RequirementTargetBinding` |
| `requirementContract` | The immutable normalization schema version/hash | `RequirementContract` |

The original source nodes are preserved. V3 gives them the precise
`SourceRequirementGroup` RDF class, and uses `RequirementClaim` for the new typed
interpretations. The v1/v2 packages remain immutable. Their exporters refuse the
new node labels instead of dropping typed data. Consumers must pin the release
and interchange version; do not combine graphs from different contracts as if
they used identical class meanings.

In Neo4j, `jobPostingRevision -HAS_TYPED_REQUIREMENT-> normalizedRequirementClaim`
is the direct typed requirement path. The original `HAS_REQUIREMENT` edges still
lead to source groups. In JSON-LD v3 these map to `jt:hasRequirement` and
`jt:hasSourceRequirement`, respectively, so the canonical RDF requirement path
does not mix source groups with typed claims.

`name` on a normalization and typed claim is the source text; use that property
for readable Korean captions in the graph viewer. Condition names identify the kind; their fields
carry the actual threshold, code, date or target. Posting and organization names
continue to come from their selected revisions.

## Evidence, logic and targets

`FOR_SOURCE_ATOM` identifies the exact original expression leaf, or the original
source group for a requirement with no expression tree. `FOR_SOURCE_GROUP`
retains the complete containing requirement. Follow `HAS_EXPRESSION` and
`HAS_CHILD` for AND/OR, conditional and exception structure. Position links are
copied through `APPLIES_TO`, without widening a scoped atom to the whole posting.

For example, normalizing both alternatives in
`(내과 전문의 OR 응급의학과 전문의) AND 경력 2년 이상` does not mean both specialist
credentials are mandatory. `necessity=REQUIRED` is interpreted within that source
expression and position scope. Consumers and future aggregates must preserve
that context. Canonical guarded-rule binding is still unfinished.

Every typed claim has `EVIDENCED_BY` edges to the original atom's exact spans,
including their part indices. It has `HAS_SUBJECT` to its posting revision,
`DERIVED_FROM` to its proposal and `REVIEWED_BY` to the release-specific selection.

- `SKILL`, `LANGUAGE` and `CREDENTIAL` use `TARGETS` to the canonical identity.
  NCS targets retain the full versioned unit identity. A language requirement
  must bind a language skill definition.
- Other kinds use `NORMALIZED_CONDITION` to one typed condition and have no
  `TARGETS` edge. Place, context, capability and vocabulary references remain
  available through `USES_TARGET_BINDING` and their explicit roles.
- A proposal's condition is always visible through `HAS_PROPOSED_CONDITION`,
  including proficiency parameters on a targeted capability.
- A target binding uses `SELECTS_REVISION` only when that exact revision belongs
  to the release. A target-mismatch proposal retains its reference metadata and
  mismatch outcome; it does not import an unselected revision or become a typed
  claim.

All proposal outcomes are retained in the graph. Only the selected `REVIEWED`
outcome produces a typed claim. Its immutable identity includes the normalization
ID and selected decision ID, so a later review does not overwrite an older
release's claim or relabel it as accepted/rejected in place. Human and assistant
reviews remain distinguishable.

Query the selected release's edges, because immutable nodes can be shared with
older releases. For example, with the intended `$release_id` parameter:

```cypher
MATCH (posting:jobPostingRevision)-[membership:HAS_TYPED_REQUIREMENT]->(claim:normalizedRequirementClaim)
WHERE membership.release_id = $release_id
RETURN posting.name, claim.name, claim.requirement_kind,
       claim.requirement_scope, claim.necessity, claim.review_status
```

Keep the source-expression and position context when interpreting the result;
this query lists claims and does not decide applicant eligibility or calculate
occupation demand.

## Integrity and limits

The graph manifest includes both the PostgreSQL requirement membership and a
compact hash of every selected atom/outcome/typed-claim identity. No atom can be
silently omitted from the frozen projection. Proposal-only or unresolved records
are not counted as reviewed requirements.

Condition nodes retain explicit `condition_fields` and `null_fields`. This allows
an independent reader to reconstruct nulls after Neo4j's native property model
omits null values. Empty primitive arrays remain arrays. The availability date is
a Neo4j date and a typed RDF date; proposal/review times have typed RDF aliases
while their exact native strings remain available for hash verification.

The offline validator checks native node/edge hashes, condition identities and
JCS requirement keys, frozen atom membership, selected review identity/kind,
target bindings, source-atom/position/evidence links and typed date aliases.
SHACL distinguishes structural validity from publication readiness. It does not
perform a new semantic review of Korean language or assign confidence.

The PostgreSQL authority remains the normalization ledger. This projection is
rebuildable. Source groups, earlier sealed releases and private `Person` nodes
are preserved. Attachment processing remains [on hold](../../docs/hop-migration/attachment-status.md).
