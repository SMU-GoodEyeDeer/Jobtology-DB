# LLM workflow deployment verification — 2026-09-11

The native artifacts are installed in Goldship's persistent default Hop project at
`/usr/local/tomcat/webapps/ROOT/config/projects/default/llm`.
The `llm-local` pipeline and workflow run configurations disable row sampling and
execution-data capture. All 41 deployed public runtime files matched their local
SHA-256 hashes after installation. Private connection metadata and credentials were
not copied to the repository.

## Live state

| Item | Verified result |
|---|---|
| OpenRouter key | `GET /api/v1/key` returned HTTP 200; authenticated. No inference endpoint was used. |
| Key file | Existing `config/secrets/openrouter.csv`, mode `0600`, owned by Hop UID/GID 501. |
| Installer | Native `llm/install.hwf` completed; repeat installation preserved data. |
| Evaluation dataset | `korean-jd-v1`, 20 real Korean JOB-ALIO postings. |
| Sampling | Four each: alternatives, multiple positions, attachment references, unrestricted eligibility, general. |
| JOB-ALIO snapshot | `77ccb77b-3afc-4965-8ce5-efd687304954` |
| NCS snapshot | `a32170ed-7485-4e31-82d3-ed48b3398946`, 15,520 cached competency definitions. |
| Dry-run batch | `c1a567ac-083e-4e72-8647-c1fa82e890a8`, state `PLANNED`. |
| Prepared requests | 20 extraction requests, all `PLANNED`; categorization awaits extraction. |
| Paid/model requests | **0** reservations, **0** responses, **0** accepted enrichments. |
| Gold labels / model-quality scores | None yet; quality has not been measured on real postings. |
| Review document | `${PROJECT_HOME}/data/llm/korean-jd-v1-review.json`, exported by native Hop. |
| Automatic LLM schedule | None; source refresh does not invoke paid LLM work. |

The current accepted source counts remained 355 organizations, 1,012 posting
representations / 506 jobs, 15,520 competencies, 87 qualification mappings,
56 exam sessions and 12,864 career records. No live inferred Neo4j relationships
were created because there are no model outputs to accept.

## Isolated implementation checks

The tests ran native Hop 2.19.0 against disposable PostgreSQL 17 and Neo4j 5.26,
with an HTTPS OpenRouter-shaped fixture server on an internal Docker network.
The server used a test certificate explicitly trusted by the test runner. TLS
verification remained enabled. Credentials were synthetic.

Passed checks include:

- Native SQL installer, repeat installation, frozen sample preparation and no-key dry run.
- Two extraction calls and one categorization call for two synthetic Korean postings;
  the attachment-only posting abstained without a categorization call.
- JSON Schema, evidence quotes, preference/requirement separation, out-of-shortlist codes,
  invalid duty indices, malformed/duplicate-key JSON, truncation and refusals.
- Actual request/response JSON handling, trace metadata, usage/cost storage and no gold-label leakage.
- Repeat-cache reuse with no additional mock requests, and changed-content cache invalidation.
- Request caps, durable reservations, duplicate-reservation denial, unknown-charge accounting,
  and a duplicate-key CSV rejected before any reservation or HTTP request.
- Gold-file import, pinned gold labels, requirement/NCS metrics and correct abstention counts.
- EVAL isolation from publication, manual acceptance, automatic `VALIDATED` acceptance policy,
  and continued EVAL isolation even when that policy is selected.
- Neo4j property/evidence/count verification, repeated publication without extra nodes or
  relationships, and revocation in both the current PostgreSQL view and synchronized graph.
- Native UTF-8 review-file export and parsing, XML/schema/Python syntax, and whitespace checks.

These checks establish implementation behavior, not Korean model accuracy. Fund the
OpenRouter account, label the pilot cases, and run comparable evaluations before selecting
production model settings. See the [operating guide](../../hop/llm/README.md).
