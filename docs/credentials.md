# Fetch credentials and source activation

There are three external-provider secret values. The existing ignored `.env` has empty slots for
each:

```dotenv
DATA_GO_KR_SERVICE_KEY=
SARAMIN_ACCESS_KEY=
WORK24_AUTH_KEY=
```

Do not send keys in chat, commit them, bake them into an image, or put them in Coolify build-time
arguments. Add them as runtime secrets on the ingestion worker. The query parameter names are
source-defined and case-sensitive; the connector redacts all of them before logging or persistence.

Production also needs a secret `JOBTOLOGY_PIPELINE_DATABASE_URL`. Use the private Coolify service
name and port 5432 (not a public or Tailscale address) from the ingestion worker, with a dedicated
pipeline role. The loopback DSN in `.env.example` is only for the included local development
container.

## 1. Public Data Portal (`DATA_GO_KR_SERVICE_KEY`)

Create or select one data.go.kr project/personal service key and submit a separate utilization
application for each service below. Reuse the same selected key for all five applications:

| ID | Connector use | Approval shown by provider |
|---|---|---|
| `15063879` | NCS classification and competency information | development/production automatic |
| `15074404` | NCS classification to qualification mapping | development automatic; production reviewed |
| `15074408` | Q-Net qualification examination schedule | development automatic; production reviewed |
| `15125273` | official JOB-ALIO recruitment list/detail | development automatic; production reviewed |
| `15125287` | official ALIO public-institution list | development automatic; production reviewed |

Put the **decoded/raw** portal key in `.env`. If the portal displays both encoded and decoded forms,
use the decoded one; the HTTP client encodes it exactly once. Development quotas differ: the NCS
information API lists 10,000 calls, while the other four list 1,000. Request production access before
scheduling a load that could exceed a development quota.

JOB-ALIO fetching is fixed to the official API, not page scraping. By default it enumerates the
complete active-posting snapshot (`ongoingYn=Y`) and retrieves `/detail` for every
`recrutPblntSn`. ALIO organization fetching uses the official `/public_inst/list` API and `instCd`.

## 2. Saramin (`SARAMIN_ACCESS_KEY`)

Register with Saramin Open API, complete the application form, wait for approval, create an app, and
copy its access key. The form asks for verified contact details, school/company and department,
service URL, and a substantive usage purpose. The published limit is 500 returned postings per day,
with at most 110 postings in one response.

Before enabling stored raw data or derived ontology use, obtain written confirmation from Saramin for
this project's retention, normalization, LLM processing, and future commercial use. Their published
terms require attribution and restrict resale/paid API-powered services. Until that review is recorded,
the checked-in rights registry blocks this connector even if a key is present. After permission is
received, record its reference and exact granted permissions in `config/source_rights.yaml`, increment
the registry revision, and review that change in Git. Activation also requires written quota terms
that can support a complete, reproducible collection; the current 500-posting daily limit is not
assumed sufficient. There is no environment-variable bypass.

## 3. Work24 (`WORK24_AUTH_KEY`)

Work24 issues Open API keys to enterprise members after an application and staff review. Apply for the
training-course API and record the approved purpose/retention terms. The connector calls the training
list endpoint; `C0104` and `C0105` select K-Digital Training and basic digital competency, and `C0061`
adds the general 국민내일배움카드 catalog for regular/low-cost alternatives. (`C0054`, which is not in
the default MVP partitions, is the separate 국가기간전략산업직종 code.)

The public documentation does not state a clear blanket retention/derivative-data license or call
quota. Confirm raw retention, normalization, excerpts, model processing, and any commercial use during
approval. Treat the key as non-transferable.
The checked-in rights registry blocks this connector even if a key is present. After permission is
received, record its reference and exact granted permissions in `config/source_rights.yaml`, increment
the registry revision, and review that change in Git. There is no environment-variable bypass.

## Non-secret configuration

| Variable | Purpose |
|---|---|
| `JOBTOLOGY_PIPELINE_DATABASE_URL` | PostgreSQL fetch-ledger DSN; required for every real run |
| `JOBTOLOGY_RAW_ROOT` | durable content-addressed raw store; use `/home/maxjo/jobtology-data` on Goldship |
| `JOBTOLOGY_CONTACT_EMAIL` / `JOBTOLOGY_HTTP_USER_AGENT` | accountable source contact identity |
| `JOBTOLOGY_SOURCE_RIGHTS_FILE` | versioned, fail-closed source permission registry |
| `SARAMIN_KEYWORDS` | deterministic Korean job-query partitions |
| `WORK24_START_DATE`, `WORK24_END_DATE` | `YYYYMMDD` training window |
| `WORK24_NCS1` | top-level NCS filter; `20` is information/communications |
| `WORK24_COURSE_TYPES` | checked course-type partitions |
| `QNET_YEARS` | comma-separated examination-year partitions |
| `QNET_ITEM_CODES_FILE` | relevant four-character Q-Net `jmCd` values, one per line |
| `NCS_QUALIFICATION_CODES_FILE` | one full versioned NCS competency-unit code per line |
| `NCS_CAREER_PATH_DOWNLOAD_URL` | pinned current direct file URL, not the HTML catalog page |
| `JOB_ALIO_ONGOING_ONLY` | fixed true for the complete active MVP snapshot |

The NCS career-path artifact is officially a one-time dataset last published in 2023, so it needs no
secret for its file download. The environment template pins the current portal-provided direct URL;
fetch it once, then perform a monthly metadata/integrity check rather than pretending it is a monthly
feed. Update the pinned URL only when the official catalog publishes a replacement artifact.

## Activation order

1. Start PostgreSQL and run `uv run alembic upgrade head`.
2. Add the data.go.kr key and activate all five API applications.
3. Run one-page `backfill` smoke tests for `ncs_competency`, `alio_organization`, and `job_alio`.
4. Derive the MVP-relevant full versioned competency-unit code list from the NCS taxonomy, place it in
   `config/ncs_qualification_codes.txt`, then smoke-test `ncs_qualification`.
5. Derive the accepted qualification item codes from that mapping, place them in
   `config/qnet_item_codes.txt`, then smoke-test `qnet_schedule`. Partitioning by item code preserves
   the qualification context even when a schedule response omits the item code itself.
6. Fetch the pinned NCS career-path artifact once.
7. Add Saramin and Work24 only after their approvals and rights notes are recorded.
8. Run uncapped `scheduled-full` fetches. Continue into parsing/grounding only after that later pipeline
   exists; raw fetching alone intentionally does not mark a run successful.

Neo4j, an LLM provider, and object-storage credentials are not needed for this raw-fetch slice. They
become relevant in later processing/publication work. PostgreSQL metadata and raw filesystem storage
are sufficient now.
