# Canonical schemas and storage ownership

Implemented 2026-09-06: schema/storage foundation and offline canonical assembly, **not a serving
corpus**. Canonical loading is explicitly enabled for local PostgreSQL. Production, LLM calls and
automatic publication remain unchanged; see [the local load report](canonical-load-status.md).

## Where the data lives

| Data | Authority | Neo4j representation |
|---|---|---|
| Original response bytes | Immutable raw files; PostgreSQL snapshot/observation ledger | References only |
| Parsed text, excerpts, locators and extraction output | PostgreSQL `grounding` | Selected evidence references/excerpts in a future serving projection |
| Canonical entities and immutable revisions | PostgreSQL `canonical` | Identities, selected revision properties and relationships |
| Resolved requirements and review decisions | PostgreSQL `grounding` | Accepted claims/relationships selected by a future corpus release |
| Names, email, school, resumes, chat, plans and progress | Backend-owned `jobtology_app` PostgreSQL database | Not copied |
| User's target and resolved capabilities | Backend application state | Private `Person` projection keyed by an opaque UUID |

PostgreSQL and Neo4j are not independent writable authorities for the same corpus fact. The intended
direction is PostgreSQL → validated release → Neo4j. The graph is rebuildable; user projections are
rebuilt separately by the backend. Raw files support reparsing. Database credentials stay out of the
browser and model context.

The migration adds B-tree indexes for source identity, revision identity/name and claim subject/review
status; JSONB GIN indexes for structured filters; and a `simple`-configuration full-text GIN index on
normalized text blocks. This is token search, **not Korean morphological, substring, fuzzy or semantic
search**. No additional search service or database extension is required at this stage. Search APIs
belong in the backend.

## Executable schemas

Pydantic is the contract authority. `schema show` emits JSON Schema from those same classes.

| Area | Models | Important rules |
|---|---|---|
| NCS/taxonomy | `ConceptScheme`, `Occupation`, `NCSClass`, `NCSCompetencyUnit`, `Skill`, `Credential` | Full unit version retained; classification version required; NCS units distinct from market skills |
| Examinations | `ExamSession`, `ExamDates` | Qualification/year/category/round identity; fixed written/practical dates at DAY precision |
| JD | `JobPosting` | Provider-neutral; missing metadata stays null; list/detail belongs in provenance |
| Organization | `Organization`, `ExternalIdentifier` | Source-scoped identifiers; equal names never automatically merge entities |
| Identity/history | `EntityIdentity`, `EntityRevision`, `FieldSupport` | Stable identities separate from content-addressed revisions |
| Grounding | `SourceDocument`, `TextBlock`, `EvidenceSpan` | NFC/LF text, SHA-256 hashes and verified half-open Unicode code-point spans |
| Extraction | `ExtractionOutput`, `RequirementCandidate`, `RequirementGroup`, `ExtractionRecord` | Untrusted mentions/spans, nested AND/OR groups; no extractor-controlled acceptance or canonical IDs |
| Requirements | `RequirementClaim`, typed conditions, `ReviewDecision` | Required/preferred/optional/unspecified, negation/no-constraint, conditional applicability, unresolved mappings |
| Private user | `PersonProjection`, `PersonCapability` | UUID, monotonic projection version, zero/one target, distinct Skill/Credential capabilities; extra profile fields forbidden |

These selected internal contracts align with [JobPosting](https://schema.org/JobPosting),
[Occupation](https://schema.org/Occupation), [Organization](https://schema.org/Organization) and
[Person](https://schema.org/Person), rather than copying every Schema.org property. Posting title,
dates, employer and occupation correspond to `title`, `datePosted`, `validThrough`,
`hiringOrganization` and `relevantOccupation`. Evidence/review/revision concepts are local extensions.
The Hop release layer now has a [versioned JSON-LD export and SHACL package](../ontology/README.md).
It preserves sealed release inventories and distinguishes structural validation
from publication requirements. Hop now binds canonical posting observations and
historical source revisions, with Neo4j and JSON-LD v2 readback; see the
[observation contract](../hop/ontology/observations.md). The
[typed requirement ledger](../hop/ontology/requirements.md) now provides native
PostgreSQL normalization proposals, JCS requirement keys, target-revision checks,
separate reviews and frozen atom outcomes. The [typed projection](../hop/ontology/requirement-graph.md)
preserves them in Neo4j and JSON-LD v3. Calibrated confidence, production
normalization, guarded-rule binding and aggregate records remain pending.

An `NCSClass.taxonomy_version` must come from a source/editorial registry version, never a fabricated
competency-unit version. An unversioned career-path CSV unit cannot construct a versioned competency
unit. NCS occupations and the four product roles use distinct scheme IDs, with reviewed mappings.

## Processing boundary

Existing `contracts/processing.py` models remain unchanged and enforce provider-specific rules,
including JOB-ALIO required dates and list/detail completeness. `processing/canonical.py` provides
pure bridges for parsed documents, postings, organizations, occupations and versioned competencies.
The bridges do not write databases or infer role mappings. Canonical organization IDs are supplied
by a resolver; name equality is not an identity rule.

A new JD provider implements its own fetch/parser adapter and emits these same canonical drafts.
Text-only JDs need neither ALIO codes nor invented dates. Missing metadata remains incomplete and
ineligible for publication. New HTML/PDF parsers and provider connectors are not included here.

Extractors return only `ExtractionOutput`. Orchestration supplies document identity and extractor
metadata. LLM provenance requires requested/returned model IDs, prompt hash, response ID and token
usage. **No LLM runner, prompt, provider dependency or paid call has been added.**

Resolution creates a separate claim with vocabulary/resolver versions. It must preserve candidate
kind, necessity, polarity, applicability and evidence. AND/OR groups remain in the linked extraction;
a future graph loader/planner must retain that structure. `Python OR Java` must not become two
mandatory requirements. Corrections to extracted meaning require a new extraction record.

`CanonicalBundle` validates cross-record references, exact excerpts, target types, field evidence,
extraction membership and claim subject/evidence consistency. Unresolved or unspecified-necessity
claims cannot be accepted. Human acceptance requires reviewer/time; automatic acceptance requires
policy version, pipeline confidence and time. The model cannot assign acceptance/confidence fields
through its extraction output.

These are necessary structural checks, **not semantic proof or authorization**. Actual approved
vocabulary resolution, evaluated acceptance policies and review authorization are still required.
The store is a trusted ingestion component, not a model-facing tool. Draft field support may be
incomplete; `missing_publication_fields()` is a completeness helper, not the final publication gate.

Internal content IDs use the existing sorted compact JSON SHA-256 encoding, tagged by schema version
where applicable. They do not claim RFC 8785/JCS equivalence or constitute final release manifests.
Arrays retain order. System times come from PostgreSQL creation timestamps and fetch observations;
posting source dates retain DAY versus timezone-aware INSTANT precision. Full taxonomy validity
intervals, requirement aggregation keys and the release lifecycle remain publication work.

## Database and graph contracts

Migration `0005_canonical_contracts` creates `canonical` and `grounding`, preserving all existing
staging/raw data. PUBLIC has no privileges on the new schemas; deployment must provision runtime
roles. `CanonicalStore.save(bundle, observations)` revalidates input, binds each document to a
successful source/snapshot observation, and writes transactionally. Identical replays are idempotent;
conflicting identity/content rolls back the entire transaction. Claims reference exact revisions,
extractions and evidence rows. No current-version pointer or serving release is created.

Migration `0006_canonical_assembly` adds exam-session identities and canonical assembly manifests.
`load canonical` rechecks source rights, raw byte hashes, completeness, staging-record hashes and
posting pairs before writing. Each item and its input/revision memberships commit atomically;
replays verify the same bundle hash and resume completed items. Changed assembly logic requires a
new assembler version. A completed run is READY with serving scope DRAFT, not a published release.

JOB-ALIO list/detail records become one posting revision referencing both source documents. Detail
fields take precedence, with list values filling nulls (including the null detail ongoing status).
The official ALIO institution code resolves the employer identity. The four product-role mappings
remain unknown. Source-occurrence-specific NCS/credential revisions retain differing names and
evidence without arbitrarily selecting a current value. Scheme/credential/employer identity shells
can exist without a descriptive revision when a source supplies only their stable identifier.

NCS career-path ranks and unversioned unit relationships, and NCS qualification-mapping qualifiers,
remain in typed staging records reached through `canonical.assembly_input`. Assembly does not invent
version mappings, skill equivalence or credential attestation claims. String-backed projected fields
receive exact evidence spans; numeric and request-context fields retain their existing staging
field-lineage paths and fetch-observation bindings. This is not completed requirement extraction.

This API is append-only; privileged SQL writers are not restricted by immutability triggers.
Raw-to-parsed correctness belongs to trusted parsers: this writer does not reparse arbitrary raw
formats. Rights/release checks must be applied by orchestration before production publication.

`schema neo4j-ddl` prints idempotent canonical uniqueness constraints; `--include-person` adds Person.
It only prints DDL, never connects/applies it. Future canonical entities require both `CorpusEntity`
and their specific type label for cross-type ID uniqueness. Community-compatible uniqueness does
not enforce relationship cardinality or every property type; contracts and the future publisher do.
Existing `Ingest*` graph staging is unchanged.

Person is excluded from the public corpus entity union and PostgreSQL table. Its graph contract
belongs here, but the backend owns private state and projection writes. The backend must authorize
ownership, resolve target IDs, reject stale projection versions, transactionally replace
`TARGETS_OCCUPATION`/`HAS_CAPABILITY` edges and handle deletion/revocation. Its outbox writer is not
implemented in this ingestion repository.

## Inspect and deploy

```bash
uv run jobtology schema list
uv run jobtology schema show job-posting
uv run jobtology schema show person
uv run jobtology schema show extraction-output
uv run jobtology schema show bundle
uv run jobtology schema neo4j-ddl --include-person

# Explicit PostgreSQL-only loads, no upstream calls or Neo4j writes.
uv run jobtology load canonical <processing-run-id>
uv run jobtology load canonical-latest
```

Use the existing `uv run alembic upgrade head` step against an explicitly selected deployment DB.
The local corpus database now has migrations through `0006_canonical_assembly`. PostgreSQL 18
integration tests use a separate disposable database. No Coolify/server migration was performed.

The updater **still writes validated staging only**; canonical assembly has an explicit offline CLI.
Automatic canonical invocation, extraction/resolution, reviewed release selection and the serving
Neo4j projection remain integration work.
No cron, daemon, scheduled model requests or production load was enabled.

## Initial schema verification (before the subsequent canonical load)

- 184 tests pass, including opt-in disposable PostgreSQL 18 / Neo4j 5.26 tests; the prior full-corpus
  replay is deselected. Ruff, Pyright and `git diff --check` also pass. Checks include
  schema export, incomplete JDs, NCS version identity, evidence offsets, AND/OR structure, forbidden
  Person profile fields, replay, transaction rollback, source-observation binding and repeatable DDL.
- All 29,759 existing relevant staging records passed read-only canonical bridge validation:
  12,864 career-path rows, 15,520 competencies, 355 organizations and 1,020 posting representations
  (the list/detail records for 510 jobs). No canonical records were persisted by this check.
- The earlier full six-source fetch/processing replay was not rerun for this schema-only change;
  see the separate processing test report for that previous test.
- No upstream request or model call was made. Production and the original local corpus DB remain
  unchanged during that initial schema-only test. The later authorized local migration and load are
  recorded separately in [the load report](canonical-load-status.md).
