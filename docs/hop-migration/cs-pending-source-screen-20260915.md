# Source screen for remaining unextracted ALIO notices

Read-only Goldship audit, 2026-09-15 14:44 UTC. The latest ready JOB-ALIO run is
`4eae07ed-1b70-4146-8e4f-75291c6b6b13`. After the four-notice pilot,
`enrichment.linking_status` reported **62 `PENDING_EXTRACTION` postings**.
This opening inventory is the pre-document source-screen. The bounded A/C
review results and native workflow receipt are recorded below; neither is a
final link-publication decision.
The results follow the latest-state view and must be refreshed after later
ingestion, bundle preparation or review.

All 62 current ALIO detail records were inspected for title, employer,
headcount, NCS source categories, eligibility/preference/selection/narrative
text and attachment metadata. They contain **122 A/C notice-or-JD file rows**,
and every posting has at least one A/C file. These are new posting identities
without earlier production enrichment items; the [baseline audit](cs-baseline-20260915.md)
explains that lineage. Source titles, posting-wide NCS codes and certificate
lists are leads, not proof that a particular advertised position performs
technical IT/AI/data work.

| Source-screen state | Postings | Meaning |
|---|---:|---|
| Roster/JD review needed | **16** | Generic/mixed notice, computational research possibility, or certificate/category discrepancy; no accepted technical role yet |
| Parsed-JD non-CS exclusion | **2** | `304913` and `304942` have duties that describe business/process work, not software/data/AI engineering |
| Current source indicates non-CS work | **44** | Explicit clinical, social, office/finance, field/facility or livestock roles; provisional until a broader JD false-negative audit |
| **Total** | **62** | |

## Concrete next roster and JD checks

| Priority | Posting | Source evidence and uncertainty | Exact A/C IDs |
|---|---|---|---|
| High, separate parser work | `304933` 국토안전관리원 일반·전문직, 18 hires | Mixed fields and posting-wide `정보통신` NCS; no technical vacancy identified in inline text. The notice is parsed, but the JD ZIP currently has `NO_TEXT`; do not infer a role from the category. | A `3074827`, C `3074757` |
| High, bounded generic pass | `304922` 한국저작권위원회, 7 hires | Mixed open/limited recruitment; the inline record delegates field details to the notice. Check the vacancy roster and the relevant ZIP member before considering a CS role. | A `3074694`, C `3074695` |
| High, bounded generic pass | `304945` 한국연구재단 연구직/사무지원, 25 hires | Several named fields are in the notice; inline eligibility says choose one detailed field. Separate any technical research position from grant/project administration. | A `3074828`, C `3074830`, both ZIP |
| Bounded generic pass | `304909` 한국출판문화산업진흥원, 3 hires | Generic public/limited title but its named C file is `일반행정`; check the A roster before excluding. | A `3074614`, C `3074616` |
| Bounded generic pass | `304959` 한국연구재단 intern/commissioned, 13 hires | The text delegates field-specific duties to documents and only mentions office-software use inline. Check each advertised position rather than the employer's research name. | A `3074911`, C `3074913` |
| Bounded generic pass | `304960` 중소기업기술정보진흥원 공무직, 10 hires | Generic employer/title, but C is named `직무설명서(사무원)`; verify the vacancy roster and whether any separate technical job is actually advertised. | A `3074935`, C `3074936` |

The five bounded generic notices above have **exactly ten A/C metadata rows**.
The original native selector also planned three named `Z` notice ZIPs, so a
ten-file plan failed with `ATTACHMENT_CAP_EXCEEDED` before downloads and rolled
back. The follow-up used six A/C files under cap six, then a separately tested
A/C-only native selector for `304922`. `304933` was handled in its own JD-ZIP
parser repair; this pass did not touch its frozen attachment batch. The already parsed
`304913`/`304942` evidence below requires no new download.

The remaining **ten lower-priority JD uncertainties** are explicit about their
limits. They are useful spot checks before anyone claims a complete
false-negative screen:

| Posting(s) | Source-only question | Exact A/C IDs |
|---|---|---|
| `304823`, `304824` | Discrete-mathematics and trapped-ion/quantum research may use computation, but their inline fields state no substantive IT/AI/data engineering duty. Do not map pure mathematics or physics to CS by title. | `304823` A `3074155`/C `3074156`; `304824` A `3074161`/C `3074162` |
| `304930` | Doctoral education researcher fields include mathematics education; inspect the JD only if technical assessment/data research falls within the chosen CS policy. | A `3074740` (JPG), C `3074742` (PDF) |
| `304938` | A two-person intern notice requires an office-category certificate list including information processing; the certificate does not establish IT work. The single A file contains notice/support material. | A `3074776`; no C metadata |
| `304948` | Museum staff/intern notice has culture/office NCS categories; digital collections work is possible but absent from inline evidence. | A `3074843`, C `3074845` |
| `304951` | Trade-security institute assessment mentions electronics/information-communications theory; inspect a JD for software/IT or substantive data duties before broadening CS to hardware research. | A `3074861` (PNG), C `3074863` (PDF) |
| `304953` | Twenty-person postal-facility integrated field notice says technical/security/cleaning; determine whether `technical` means building facilities or IT systems. | A `3074876`, C `3074877`, both HWP |
| `304966`, `304968`, `304969` | Livestock agency's shared preference list includes information-management and ADP certificates, but these disability-intern/operations/periodic notices state no data-analysis duty. Compare their own JDs with the distinct `통계` notices `304963`/`304964` before promoting them. | `304966` A `3074962`/C `3074964`; `304968` A `3074970`/C `3074972`; `304969` A `3074974`/C `3074976` |

## Two exclusions backed by already parsed JDs

`304913` 한국환경공단 has a title containing `수탁폐수전자인계인수관리시스템
운영`. Its parsed A `3074633` roster advertises one **environmental** support
vacancy. Parsed C `3074635` describes operating the electronic handoff
*business scheme*: education/publicity, vehicle-verification equipment field
checks and complaint guidance. It does not state software maintenance,
data engineering or system development. A computer certificate is only an
advantage. This is an `OUT_OF_CS` source-screen result; the title's `시스템`
does not establish IT-system work.

`304942` 의료기관평가인증원 has an inline selection multiplier for
`전산관련 직무`, but its parsed C `3074801` advertises healthcare-training
institution designation/evaluation: criteria, committee and education
coordination, survey/assessment and project management. A `3074795` and C
`3074801` are parsed. The multiplier is not evidence of an IT vacancy in this
two-person notice. It is an `OUT_OF_CS` source-screen result.

At this audit, six A/C files were already HTTP-200 archived among three
pending notices: two each for `304913`, `304933` and `304942`. Processor
states were `PARSED` for both `304913` files, `PARSED` for both `304942`
files, `PARSED` for `304933` A `3074827`, and `NO_TEXT` for its C ZIP
`3074757`. The remaining 59 notices had no attachment-document rows before
the five-notice generic pass below.

## Forty-four current source non-CS candidates

The following are **provisional source screens**, not approved exclusions from
a full JD corpus audit. Their current title and inline recruitment text give
the advertised non-CS job family; a future notice/JD check can overturn any
one row if it identifies a separate technical position.

| Job family indicated by source | Count | Posting IDs and basis |
|---|---:|---|
| Clinical, social care or food service | 16 | `304894`, `304905`–`304908`, `304911`, `304915`–`304918`, `304920`, `304923`, `304946`, `304947`, `304949`, `304955`: disability support, cook, hospital office/support, physician, physiotherapist, nursing or dental work |
| Office, finance or legal service | 10 | `304778`, `304891`, `304895`, `304914`, `304924`, `304925`, `304929`, `304943`, `304952`, `304965`: office assistant/intern, fund/finance, HR, trade office or labor lawyer. Computer/OA credentials do not establish engineering. |
| Field facilities, transport, environmental service or short labor | 16 | `304903`, `304904`, `304919`, `304921`, `304926`, `304928`, `304931`, `304935`–`304937`, `304939`–`304941`, `304944`, `304954`, `304957`: water/physical-telecom installation, power work, guard/cleaning, driver, building operations, park/revenue work. `정보통신` for `304904`/`304954` refers to field communication equipment and simple repairs. |
| Livestock-quality evaluation | 2 | `304961`, `304962`: livestock-degree/quality evaluator tracks, distinct from the separate advertised statistical posts; generic ADP/IT certificates are preferences. |

The title-only CS keyword screen would falsely promote roles such as physical
telecom installation and ordinary computer-qualified office work. Conversely,
the generic mixed notices above can hide a position absent from the ALIO
inline fields. This audit has **not** inspected all 122 A/C documents and
does not certify that the 44 provisional rows contain no hidden technical
position.

## Bounded A/C source review and native receipt

The exact five-notice native preflight had `BATCH_ID=cs-generic-docs-20260915-a`,
`MAX_FILES=10`, `EXECUTE_DOWNLOADS=N` and posting IDs
`304909|304922|304945|304959|304960`. It exited with
`ATTACHMENT_CAP_EXCEEDED`, and no batch row persisted. The v3 policy had
selected **13** files: ten A/C plus `Z3074696` for `304922` and
`Z3074831`/`Z3074832` for `304945`. These named notice ZIPs remained
outside the bounded A/C pass. The legacy A/C-only downloader cannot parse
the C ZIP for `304922` or the A/C ZIPs for `304945`.

Native batch `cs-generic-docs-20260915-core-a` then froze and archived the
exact six A/C files for `304909`, `304959` and `304960` under `MAX_FILES=6`.
Its `N` plan and `Y` rerun both exited 0; all six archives returned HTTP 200.
Native parser batch `cs-generic-parse-20260915-core-a`, pinned to hop3 revision
`7541e87c0b45d8d209cd3c110f7bf09c72666779-hop3`, finished **six
`PARSED`**, with zero paid model calls. The advertised rosters, not employer
names or general skill lists, give these source-backed `OUT_OF_CS` screens:

| Posting | A notice roster | C JD |
|---|---|---|
| `304909` | A `3074614` lines 17–19: two general-admin permanent and one general-admin replacement hires; project/admin/culture-content planning | C `3074616` lines 5 and 12: general administration, project management and office work |
| `304959` | A `3074911` lines 11–27: intern and grant/research business replacement roles; one `ICT·융합연구단` hire at line 14 evaluates and manages basic-research grants | C `3074913` lines 45–51: research/project administration. The employer-wide digital-innovation map at A lines 793–798/C lines 145–150 is **not** an advertised role roster. Generative AI and data tools are supporting skills. |
| `304960` | A `3074935` lines 13–15: two veterans' and eight disability office-assistant hires, government-project and executive support | C `3074936` line 9: executive scheduling, reception and office assistance |

`304909` A reported `IMAGE_CONTENT_REQUIRES_REVIEW`, but its visible roster
accounts for all three advertised hires and the C JD agrees. This screen does
not claim a full hidden-image or future-JD false-negative guarantee.

For the two remaining high-priority notices, a **local read-only** fetch
reviewed only their four official A/C URLs and produced no Goldship attachment
rows. `304922` A `3074694` returned HTTP 200 (SHA-256
`b3b3bd054c8928431ee1ef555478c3ddb438e45cc19615c6f32da637502442da`).
Its first-page PDF roster was rendered and visually checked: position **②
정규직 정보기술, two hires**, manages copyright information-technology projects;
the other five hires are administration/museum roles. C `3074695` ZIP returned
HTTP 200 (SHA-256
`aa48ed9525bad2e03b8270e5396b0b4ed2a7b86a6c27913dd295e55d2dd22365`).
Its member `02 직무기술서(정규직_정보기술).hwp` parsed through the existing
`../document-processor`: NCS `20 정보통신 / 01 정보기술`, IT strategy, system
technical support/maintenance and IT project management. This is a confirmed
**CS vacancy**, scoped to the two hires in position ②.

`304945` A `3074828` and C `3074830` official ZIPs returned HTTP 200 with
SHA-256 `b8356edf0640b4657b766f734e0b849160dd649f0237bfc8d636ac9501d44940`
and `cba12dce7d2966065ab791439998a2081a8bb128ff2f327aaf189449d1fe9c06`.
The A ZIP contains a 20-hire research roster (including three `이공계
ICT·융합`) and a five-hire office-support roster. The C research JD applies
to all research fields and classifies them under `01 사업관리 / 프로젝트관리 /
산학협력관리`; its duties are grant/research project planning, selection,
agreements, management and dissemination. The office JD is office support.
The ICT track is an applicant subject/major, with no advertised software,
IT-system or data-engineering duty. This is a source-backed `OUT_OF_CS` screen
with the limitation that the shared JD gives no more specific assignment for
the ICT track. No `304945` live download/parse or scope write followed.

An additive native selector now accepts `FILE_SELECTION=DEFAULT` (the unchanged
named-notice behavior) or `A_C_ONLY`. The latter freezes a separate immutable
`job-alio-documents-v3-ac-only` policy and keeps non-A/C rows as
`ROLE_REVIEW`. A live PostgreSQL **ROLLBACK** trial planned exactly two A/C
plus one review-only Z for `304922` under cap two; the default mode planned
all three under cap three; changed/invalid selectors failed. XML parsed, the
previous deployed hashes matched repository HEAD, and the native SQL installer
exited 0. Persistent deployment receipt:
`~/.local/state/jobtology-hop/ac-selector-deploy-20260915T1450KST/`.
Deployed hashes are `9f17ca860556a36578088f22f9f2a7aaefc34cd93bc7136bab8541426b0e8f41`
for `prepare_downloads.hpl`, `63d7fc9a4c211c68d81e4b1ae90e0927f59ef1e9e7dfef4aa688f4781b4820e2`
for `download_snapshot.hwf`, `b8edf237109a1fce944e796fdc1c251d2a7d18a0e6dcb1a5558d9a378765d56e`
for SQL `010_ac_only_selector.sql`, and `3aa7eb7fdb69dac2a0d4c538826121ad9befe9495856ea45cd851d1075957102`
for `install_ac_only.hwf`.

Native `cs-copyright-docs-20260915-a` then used the same exact JOB run,
`POSTING_IDS=304922`, `MAX_FILES=2`, `FILE_SELECTION=A_C_ONLY`: the `N`
plan and `Y` rerun exited 0. It archived A `3074694` and C `3074695` with
HTTP 200 and the same raw hashes above; Z `3074696` remained `ROLE_REVIEW`
and was not requested. Parser batch `cs-copyright-parse-20260915-hop4-a`,
revision `7541e87c0b45d8d209cd3c110f7bf09c72666779-hop4`, finished both
`PARSED`, warnings `[]`. Its A Markdown line 13 names the two-hire IT role;
its C ZIP Markdown lines 35, 41 and 42 name that role, technical IT duties
and NCS ability units. `prepare_processor_inputs.hwf` exited 0 and froze:

```text
bundle_id   e6426e0b0bd774ceace539c975d5836e4552d8da6c75fe3edefc22add85e8660
source_hash 9c9c8c538f427d9ffb09a5b6b5e4722a500f12bc3e112164efb8dcca50dd032c
```

The production bundle contract is `document-processor-input-v2`, source data
129,304 characters. This source-screen stage itself did not accept a CS scope
decision or NCS link. The subsequent one-request extraction, accepted IT role,
two reviewed NCS links and qualification result are recorded with `304933`'s
information-security vacancy in the
[new-posting triage record](cs-new-postings-triage-20260915.md).
Taken together, the 62 initial screens now contain two confirmed CS notices,
six source-backed non-CS screens, ten still needing roster/JD review, and 44
provisional inline-source non-CS screens; these are source-screen counts, not
current `enrichment.linking_status` outcomes.

## Reproducible status and file counts

The read-only export joined `enrichment.linking_status` to the exact latest
`ingestion.job_posting` row and its `:detail` `ingestion.ready_record`; the
file count kept only `atchFileType IN ('A','C')`. Its source data contains no
model result, scope decision or graph write. A later export should check the
latest snapshot run ID before comparing counts.

```sql
BEGIN READ ONLY;
SELECT outcome, count(*) FROM enrichment.linking_status
WHERE outcome='PENDING_EXTRACTION' GROUP BY outcome;
WITH pending AS MATERIALIZED (
  SELECT posting_id, job_run_id FROM enrichment.linking_status
  WHERE outcome='PENDING_EXTRACTION'
)
SELECT count(*) AS postings,
       sum((SELECT count(*) FROM jsonb_array_elements(
         coalesce(d.source_payload->'files','[]'::jsonb)) f
         WHERE f->>'atchFileType' IN ('A','C'))) AS ac_file_rows
FROM pending p JOIN ingestion.ready_record d
  ON d.run_id=p.job_run_id AND d.source_record_id=p.posting_id||':detail';
COMMIT;
```
