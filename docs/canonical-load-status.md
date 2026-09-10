# Local canonical load — 2026-09-06

Target: existing **local PostgreSQL 17.11**, `127.0.0.1:55432`, database `jobtology_pipeline`.
This is not the Coolify production PostgreSQL 18 service.

## Scope

The user authorized applying the canonical migration locally and assembling the saved staging data.
Migrations `0005_canonical_contracts` and `0006_canonical_assembly` were applied successfully. The
database doctor confirms the new head. Existing raw files and 29,902 staging records are preserved.

The repeatable command is:

```bash
uv run jobtology load canonical-latest
```

For one selected processing run:

```bash
uv run jobtology load canonical <processing-run-id>
```

This is an offline load: no provider fetch, LLM request, Neo4j write or production change. Source
rights, raw hashes, completeness and staging hashes are rechecked before each source is assembled.
Completed item checkpoints and canonical memberships commit together. Failed or interrupted work
can resume without duplicating completed items.

## Representation

- NCS rows produce canonical occupations and full-version competency-unit records. The NCS scheme
  identity is retained without inventing a global publisher revision. Career-path ranks and
  unversioned-unit relationships remain preserved in staging and document provenance.
- NCS qualification mappings supply credential identities/names. Detailed mapping conditions and
  training-hour fields remain in typed staging; no new accepted attestation claim is manufactured.
- Q-Net supplies exam-session revisions with qualification/year/category/round identity and fixed
  written/practical date fields. Missing dates remain null; no clock times or fees are inferred.
- ALIO supplies organization records. JOB-ALIO joins employers by official institution code, not
  company-name similarity.
- Each JOB-ALIO list/detail pair produces one posting revision with both source documents. Detail
  values win where supplied; list fields fill null detail values. Product-role mappings remain null.

`canonical.entity` contains stable identities. `canonical.revision` contains source-occurrence-based
revisions, so its row count is larger than the number of unique occupations or credentials. There
is no arbitrary global "latest revision" selection: future release selection will reconcile source
variants. All assembly runs are **DRAFT**, not a published recommendation corpus.

Grounding is stored in `grounding.document`, `text_block`, `evidence_span` and
`document_observation`; projected string fields link through `canonical.field_evidence`.
`canonical.assembly_input` links every input document to the original typed staging record, including
numeric/request-context field lineage. `canonical.assembly_revision` identifies each run's outputs.
The operational status/manifests are in `control.canonical_run`.

## Verification

The test suite reports **190 passed, 2 skipped, 1 deselected** against disposable PostgreSQL 18.
The skipped cases require Neo4j, which is outside this PostgreSQL-only load. The deselected case is
the previously tested complete upstream-response replay. New checks cover posting-pair assembly,
NCS version preservation, exam dates/identity, raw-integrity rechecks, replay and interrupted-item
transaction rollback/recovery. Ruff, Pyright and `git diff --check` pass.

All six source assembly runs completed READY with serving scope DRAFT. Every original staging
record is represented in the canonical input manifest.

| Canonical identity | Unique identities | Source-backed revisions |
|---|---:|---:|
| Occupation | 1,111 | 28,384 |
| NCS competency unit | 15,520 | 15,520 |
| Organization | 355 | 355 |
| JobPosting | 510 | 510 |
| Credential | 31 | 87 |
| ExamSession | 56 | 56 |
| NCS concept-scheme shell | 1 | 0 |
| **Total** | **17,584** | **44,912** |

The 1,111 occupations are the union of supplied occupation codes, not the four product roles and
not an assertion that every occupation is relevant to CS/AI students. Repeated occupation/credential
revisions preserve evidence from different source-record occurrences; they are not duplicate
identity nodes. The 510 postings correspond to the 1,020 original list/detail staging records.

| Storage | Rows |
|---|---:|
| Original `staging.record_revision` | 29,902, unchanged |
| `grounding.document` | 29,902 |
| `grounding.text_block` | 285,787 |
| `grounding.evidence_span` | 151,036 |
| `canonical.field_evidence` | 213,116 |
| `canonical.assembly_input` | 29,902 |
| `grounding.extraction` / `grounding.requirement_claim` | 0 / 0 |

The complete local command was then rerun: **all 29,392 assembly items reused their checkpoints,
with zero new rows** in canonical identities/revisions, documents, text blocks, evidence, field
links or input memberships. The item count is 510 lower than the input-record count because each
posting item combines two source representations.

Post-load SQL checks verify every stored excerpt against its actual text offsets, all 510 posting
employer references, both source documents on every posting, and matching processing/assembly input
hashes. Product-role mappings remain null. Local Korean token search was checked against the saved
text. The temporary PostgreSQL 18 test container/volume was removed; the persistent local corpus
database and its newly loaded data are retained.

## Remaining boundaries

The daily updater still automatically stops at staging; canonical loading is an explicit command.
Requirement extraction/resolution, reviewed mappings, serving-release selection and the final Neo4j
projection remain subsequent work. No Person records or private user data were loaded.
