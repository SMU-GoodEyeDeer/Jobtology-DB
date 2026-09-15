# New ALIO postings: source and document triage

Read-only Goldship audit on 2026-09-15, pinned to ready JOB-ALIO run
`4eae07ed-1b70-4146-8e4f-75291c6b6b13`. This is a preparation queue, not
an accepted scope or NCS decision. The latest `enrichment.linking_status` had
66 genuinely new `PENDING_EXTRACTION` posting IDs. Their saved ALIO detail
records provide 253 distinct attachment IDs. At the start of this audit, none
of those IDs appeared in `attachment.document`: no archive or parsed Markdown
could be reused for the initial 66-notice screening. The four-posting document
run below subsequently created eight archive/parse receipts.

| Posting | Source-grounded reason to check | A/C document IDs | Initial source conclusion |
|---|---|---|---|
| `304956` 국가아동권리보장원 | Inline eligibility explicitly names `기관운영(정보화전략) 4급`, a computer/communications degree and four years of IT work; IT/security certificates are separately preferred. | `3074887` notice PDF; `3074889` JD PDF | High-priority technical vacancy check; read JD before choosing a CS scope family. |
| `304958` 한국토지주택공사 | Inline eligibility names `사무직(전문-전산·국가유산)` and requires a field-specific certificate. It recruits 235 across many fields, so only the `전산` vacancy should enter technical analysis. | `3074903` notice ZIP; `3074905` JD ZIP | High-priority position-specific check. |
| `304963`, `304964` 축산물품질평가원 | Both `행정직` notices require **one of** 사회조사분석사 2급, 데이터분석전문가 (ADP) or 빅데이터분석기사; neither title nor broad NCS category says data. The postings recruit two and one respectively. | `304963`: `3074950`/`3074952`; `304964`: `3074954`/`3074956`, all PDF | High-priority data-duty check. The certificate requirement alone does not prove substantive analysis. |
| `304933` 국토안전관리원 | Generic 18-person general/professional notice includes broad NCS `정보통신` category, but the inline recruitment fields do not identify a technical vacancy. | `3074827` notice PDF; `3074757` JD ZIP | Unresolved; inspect vacancy roster in the notice and match the appropriate JD member. |
| `304913` 한국환경공단 | The title says `수탁폐수전자인계인수관리시스템 운영`, but the source assigns the environmental NCS category and inline text gives no system-engineering duties. It could mean operating the environmental business process. | `3074633` notice HWP; `3074635` JD HWP | Unresolved; determine whether it maintains software or merely uses it. |
| `304942` 의료기관평가인증원 | The selection text mentions `전산관련 직무` even though its named JD concerns clinical education-institution designation/evaluation and only two people are recruited. This may be boilerplate. | `3074795` notice PDF; `3074801` JD PDF | Low-priority discrepancy check; do not classify from that phrase alone. |

`304713` is **not** among the 66: it is `EXTRACTION_FAILED`, but its
exact-current-hash input bundle already exists (`2be37c73945eb10c84aa802b72313fabe5ddd12ce26b3fb656c6086e20d043bb`).
Its notice/JD PDFs `3073606` and `3073608` each have saved `PARSED` document-
processor rows. Notice Markdown line 99 advertises a 4급 `AI·디지털` role with
AI/digital service strategy and information-system operation; line 164
advertises 공무직 `정보화기술지원` with AI/IT planning support, system operation
and public web service. JD lines 1–13 and 219–232 describe those roles and
their NCS units. The newest paid extraction attempt was `REJECTED` for
`duties:UNSUPPORTED_FRAGMENT`, after a 159,459-token request billed
`$0.042935`. Review its saved extraction against the exact cited fragments
and make a source-bound correction; a fresh extraction call is unnecessary
for discovering these roles.

A full vacancy-roster check found two **additional non-CS recruitment rows**
missing from that saved model output: a second 공무직
`일반행정(장애인)` at Chuncheon, one hire (notice line 163), and a second
`양묘관리기능원(식물생산)` at Chuncheon, two hires (line 175). The corresponding
same-named roles at Sejong remain separate on lines 162 and 174. The notice
has 20 vacancy rows and 27 hires; the original model output covered only 18
rows and missed these three hires. A proposed append-only child correction
adds two role IDs and six separately cited duties while preserving the first
literal fix and all earlier indices. It passed the pinned schema and source
validators in a rolled-back transaction. The source has mandatory position-
specific eligibility, including p1's IT/security certificate and three years
of experience (line 99), and p14's information-processing function certificate
(line 164). `ko-link-v1` is explicitly `DUTIES_ONLY`, so its empty
`requirements` array is expected; those conditions need a separate
eligibility/scope note and should not be fabricated in this raw schema.

For an economical next pass, run the existing manual
`attachments/download_snapshot.hwf` and `attachments/parse_documents.hwf`
on **only** `304956|304958|304963|304964` first. Their eight A/C documents
carry the vacancy evidence; application forms and unrelated auxiliary files
are not needed. Check parser/ZIP member outcomes and select the technical
vacancy and its cited duty sections before preparing a bounded production
input. The three unresolved notices `304933|304913|304942` form a second,
six-document A/C check queue. Download and parsing are no-cost operations
in the LLM sense; model extraction remains a later, targeted step for
roles that actually pass the document review. The large mixed `304958`
notice/JD should not be sent in full to a paid model merely because its
inline text contains `전산`.

This source-only pass is not a full false-negative guarantee for generic
multi-position notices. Other new postings with generic titles but no inline
technical vacancy, such as `304922` (copyright council) and `304945`
(research foundation), still need deterministic notice/JD roster screening
when broader coverage is required. Physical telecom installation notices
`304904` and `304954` have technical-sounding categories but their inline
eligibility describes electric/telecom field work, cable/equipment checks
and simple repair; they do not establish a software, data or IT system
engineering role. Pure mathematics and quantum research notices `304823`
and `304824` similarly do not establish this policy's IT/AI/data duties
from their source text alone.

## Four-posting native Hop document pass

The existing native Hop workflows completed a bounded production document
pass for `304956|304958|304963|304964`. The plan
`cs-new-docs-20260915-a` selected **exactly eight** A/C notice/JD files
from 20 metadata entries (`MAX_FILES=8`); application forms and unrelated
auxiliary files remained in the metadata ledger. The subsequent manual
`attachments/download_snapshot.hwf` run got eight HTTP 200 archives with
byte hashes and no active retention writer left behind. The parser health
response pinned revision
`7541e87c0b45d8d209cd3c110f7bf09c72666779-hop3`. The dry parser
plan and live `attachments/parse_documents.hwf` batch
`cs-new-parse-20260915-a` finished **8/8 `PARSED`**, with no `NO_TEXT` or
`PARSE_ERROR`. LH's notice ZIP had four parsed PDF members and its JD ZIP
had nineteen parsed PDF members, including the separate `5급 전산` JD.
The LH notice and the four 축산물품질평가원 PDFs report
`IMAGE_CONTENT_REQUIRES_REVIEW`; their relevant vacancy/duty text is
present in extracted Markdown, but images may hold additional content.

`attachments/prepare_processor_inputs.hwf` then froze four production
`document-processor-input-v2` bundles. The IDs, exact content hashes and
source-data sizes are:

| Posting | Bundle ID | Source hash | Serialized source-data characters |
|---|---|---|---:|
| `304956` | `fe239442fc2e6708b505bf4e6ba3e58fac67f8ff5176648eaefdc1695a1acee7` | `9bd8bc6834753faac29ca84473b6788123b4dc68cbaf71a5c0a9dea140b2b6c0` | 145,208 |
| `304958` | `823bd41c61e09d390651b4afd8331ebd3f7f64df93411da6bcc131944056e634` | `f029d2f50da0e02c36c4971ca50ec36bd6d505aa1c02f421a4e1d502e4f22370` | 651,684 |
| `304963` | `00a3af4d2a1851feac81e77c5d3d0670a9bb783426809a50293454825179a75d` | `fa597bff5f0ff32c3c8192faebd11d11dbf2033a050573abdbfa8042dbf61ccf` | 59,566 |
| `304964` | `d710bd1a54bbb2d48b72c26ebfda7f8145bba888e49a21b011f9fee5ea9accd1` | `c9320c445c0165ba48089625d67c5ed56c03ab2ee1b615380c2dec121c70139e` | 60,483 |

These are immutable source inputs, not LLM results or accepted scope records.
No paid calls, extraction items, scope decisions or graph links were created
in this pass.

The parsed vacancy evidence confirms position-specific relevance:

| Posting / recruited role | Notice evidence | JD evidence | Scope review implication |
|---|---|---|---|
| `304956` / `기관운영(정보화전략)`, two hires | `attachment_1_3074887:22`: information-system construction, infrastructure operation and security | `attachment_3_3074889:116-138`: its own NCS JD names system SW, IT system administration/support, information protection, DB/NW/security operations and incident response | Strong `IT_SYSTEMS`/`SECURITY` candidate; isolate this row from the other 23 staff. |
| `304958` / 5급 specialist `전산`, two hires | `attachment_1_3074903:15` in the 5급 notice ZIP roster | `attachment_2_3074905:392-415`: ZIP member `4. 5급 전산.pdf` names IT systems, big-data platform/data-quality operation and IT project work | Strong `IT_SYSTEMS`/`DATA` candidate; do not treat all 235 recruits or all nineteen JDs as CS positions. |
| `304963` / `통계`, two hires | `attachment_1_3074950:12`: public-data operation and data-analysis planning/support | `attachment_3_3074952:5-21`: substantive statistical analysis, big-data analysis/planning, data quality/standards and programming/model skills | Strong `DATA` candidate despite `행정직` title. |
| `304964` / `통계`, one hire | `attachment_1_3074954:12`: same advertised work under a distinct veterans recruitment notice | `attachment_3_3074956:5-21`: the source's separate JD and same technical data duties | Strong `DATA` candidate; preserve its distinct source identity. |

Review the exact technical positions and evidence before any paid extraction.
The prepared `304958` bundle serializes 651,684 source-data characters
because the notice/JD ZIPs cover many unrelated tracks. The current native
bundle verifier always reconstructs **all** parsed attachment fields from the
processor batch; `INPUT_BUNDLE_IDS` selects a whole bundle, not a ZIP member.
The LH notice ZIP contributes 113,510 text characters across four PDF
members, and its JD ZIP contributes 145,782 across nineteen PDF members.
There is no supported selective-member or passage-filter parameter in the
installed `llm/enrich.hwf`. Do not delete unrelated members from the frozen
bundle: that would break `attachment.verify_input_bundle` and source review.

## Bounded LLM extraction pilot

An independent PostgreSQL `BEGIN`/`ROLLBACK` preview called the installed
`enrichment.plan_batch` and `enrichment.plan_stage('extract')` for all four
exact bundles using `ko-link-v1`, `openai/gpt-5.6-luna`, `PROVIDER_ONLY=openai`,
`REUSE_CACHE=Y`, `ACCEPTANCE_POLICY=REVIEW`, and
`MAX_INPUT_CHARS=1000000`. It made no API calls and left no batch/items.
Every proposed extraction was `PLANNED` with no `INPUT_TOO_LARGE` issue:

| Posting | Complete extraction request characters | Source-data characters |
|---|---:|---:|
| `304956` | 150,990 | 145,208 |
| `304958` | 421,439 | 651,684 |
| `304963` | 53,487 | 59,566 |
| `304964` | 54,069 | 60,483 |

The LH request is smaller than serialized source data because the model
packet omits audit-only document structure, but it still sends the whole
notice/JD Markdown. Its `5급 전산.pdf` member is present at
`attachment_2_3074905:392-415`; the notice roster binds it to two hires
at `attachment_1_3074903:15`. The other nineteen JD tracks remain context,
so review must reject any model roles that are not advertised vacancies or
whose evidence bleeds across ZIP members. A selective-member model packet
would require a new versioned planner/prompt change while retaining the full
immutable bundle and audit evidence; it is not a current Hop option.

At this check, the protected key file was mode `0600` and authenticated:
OpenRouter `GET /api/v1/key` returned HTTP 200. `GET /api/v1/credits`
reported $8 funded and $2.58042104 usage, or $5.41957896 remaining in
OpenRouter credits. Those endpoints do not expose the separate OpenAI BYOK
balance; the API key could not access the BYOK management list (HTTP 401).
All four new source hashes have **zero** historical enrichment items, so no
identical-request response can currently be reused. OpenRouter's
[Luna model page](https://openrouter.ai/openai/gpt-5.6-luna-20260709)
lists $0.20 per million input tokens and $1.20 per million output tokens
for standard OpenAI routing. The [BYOK documentation](https://openrouter.ai/docs/guides/overview/auth/byok)
says provider pinning alone does not prove the account key was used; its
prioritized/fallback configuration controls that. Hop's `MAX_COST_USD` is
an accounting cap using reported request costs and reservations, not a
provider-side prepaid limit.

For the first paid run, keep the three compact notices together and LH in a
separate batch. Both runs should use `RUN_MODE=ENRICH`, the pinned ALIO run
`4eae07ed-1b70-4146-8e4f-75291c6b6b13`, pinned NCS run
`a32170ed-7485-4e31-82d3-ed48b3398946`, exact `POSTING_IDS` and bundle
IDs above, `EXTRACT_MODEL=CATEGORIZE_MODEL=openai/gpt-5.6-luna`,
`PROVIDER_ONLY=openai`, `PROMPT_VERSION=ko-link-v1`, `REUSE_CACHE=Y`, and
`ACCEPTANCE_POLICY=REVIEW`. Use `MAX_REQUESTS=6`,
`REQUEST_RESERVE_USD=0.05`, `MAX_COST_USD=0.40`,
`DAILY_BUDGET_USD=12`, `MAX_INPUT_CHARS=300000`, and
`MAX_OUTPUT_TOKENS=8192` for `304956|304963|304964`. The separate
`304958` run can use `MAX_REQUESTS=2`, the same reserve,
`MAX_COST_USD=0.25`, `MAX_INPUT_CHARS=600000`, and
`MAX_OUTPUT_TOKENS=16000`. Combined Hop batch caps are $0.65; at most
eight paid HTTP requests are eligible, with no automatic retries. The
current rolling-day recorded cost was $5.8464, below the proposed $12
shared daily cap. These limits are deliberately above the measured request
sizes and below the prompt's 1,000,000-character maximum.

The following native Hop commands execute the two bounded batches on
Goldship. Each workflow generates its own batch UUID and prints it in its
log; preserve that ID for review and later publication. Run the compact
batch first, inspect its exact output, then run LH separately:

```sh
ssh -o BatchMode=yes maxjo@goldship 'docker exec -w /usr/local/tomcat/webapps/ROOT -e "HOP_OPTIONS=-Xmx1024m -Djavax.xml.transform.TransformerFactory=com.sun.org.apache.xalan.internal.xsltc.trax.TransformerFactoryImpl" b4a19e0a24e8 bash hop-run.sh -j default -r llm-local -f /usr/local/tomcat/webapps/ROOT/config/projects/default/llm/enrich.hwf -p "RUN_MODE=ENRICH,JOB_RUN_ID=4eae07ed-1b70-4146-8e4f-75291c6b6b13,NCS_RUN_ID=a32170ed-7485-4e31-82d3-ed48b3398946,POSTING_IDS=304956|304963|304964,INPUT_BUNDLE_IDS=fe239442fc2e6708b505bf4e6ba3e58fac67f8ff5176648eaefdc1695a1acee7|00a3af4d2a1851feac81e77c5d3d0670a9bb783426809a50293454825179a75d|d710bd1a54bbb2d48b72c26ebfda7f8145bba888e49a21b011f9fee5ea9accd1,POSTING_LIMIT=3,EXTRACT_MODEL=openai/gpt-5.6-luna,CATEGORIZE_MODEL=openai/gpt-5.6-luna,PROVIDER_ONLY=openai,PROMPT_VERSION=ko-link-v1,CANDIDATE_LIMIT=60,MAX_MATCHES=12,MAX_INPUT_CHARS=300000,MAX_OUTPUT_TOKENS=8192,MAX_REQUESTS=6,REQUEST_RESERVE_USD=0.05,MAX_COST_USD=0.40,DAILY_BUDGET_USD=12,EXECUTE_REQUESTS=Y,REUSE_CACHE=Y,ACCEPTANCE_POLICY=REVIEW,REQUEST_DELAY_MS=3000,READ_TIMEOUT_MS=180000" -l Basic'

ssh -o BatchMode=yes maxjo@goldship 'docker exec -w /usr/local/tomcat/webapps/ROOT -e "HOP_OPTIONS=-Xmx1024m -Djavax.xml.transform.TransformerFactory=com.sun.org.apache.xalan.internal.xsltc.trax.TransformerFactoryImpl" b4a19e0a24e8 bash hop-run.sh -j default -r llm-local -f /usr/local/tomcat/webapps/ROOT/config/projects/default/llm/enrich.hwf -p "RUN_MODE=ENRICH,JOB_RUN_ID=4eae07ed-1b70-4146-8e4f-75291c6b6b13,NCS_RUN_ID=a32170ed-7485-4e31-82d3-ed48b3398946,POSTING_IDS=304958,INPUT_BUNDLE_IDS=823bd41c61e09d390651b4afd8331ebd3f7f64df93411da6bcc131944056e634,POSTING_LIMIT=1,EXTRACT_MODEL=openai/gpt-5.6-luna,CATEGORIZE_MODEL=openai/gpt-5.6-luna,PROVIDER_ONLY=openai,PROMPT_VERSION=ko-link-v1,CANDIDATE_LIMIT=60,MAX_MATCHES=12,MAX_INPUT_CHARS=600000,MAX_OUTPUT_TOKENS=16000,MAX_REQUESTS=2,REQUEST_RESERVE_USD=0.05,MAX_COST_USD=0.25,DAILY_BUDGET_USD=12,EXECUTE_REQUESTS=Y,REUSE_CACHE=Y,ACCEPTANCE_POLICY=REVIEW,REQUEST_DELAY_MS=3000,READ_TIMEOUT_MS=180000" -l Basic'
```

`EXECUTE_REQUESTS=N` creates a persistent planned preview; `Y` starts a
**new** generated UUID batch, so do not use the same dry-run batch as a paid
continuation. After each paid batch, inspect `enrichment.batch_report`,
`enrichment.item`, `enrichment.attempt`, and the review/scope queues. In
particular, the extraction output should include only the sourced technical
vacancy rows noted above as CS-scope candidates; the LLM can extract other
advertised roles, but those must remain outside the CS scope decision. Do
not publish NCS links until independent source-bound extraction and link
reviews pass.

## Compact-batch source review

Luna batch `a3ef3c09-7f78-4a41-aa9d-b39e3d7c09a5` validated all three
compact inputs after six requests ($0.0891394 reported). Native
`llm/export_link_review.hwf` exported exactly `304956|304963|304964`,
zero omissions and sixteen proposed links. The independently completed
packet is `/tmp/jobtology-cs-new-link-review-completed-20260915.json`
(SHA-256 `280d2f64e6eb22926069f7e3c345fa4a7d1246782b5ffbecfda0248fcb59174f`).
It recommends extraction `REJECT` for `304956`/`304963`, `ACCEPT`
for `304964`, one link `ACCEPT`, eleven link `REJECT`s and four reasoned
abstentions. `enrichment.apply_link_review` first validated the packet
inside `BEGIN`/`ROLLBACK`, then the main workstream imported that exact
packet **before** the child corrections. Its immutable receipt
`ce7ea549f3f5fa4437f854a7b22b767852f5d2c4de54b6bad531bd25c0b6b86a`
records 3 extraction and 12 link decisions. Those decisions are valid
historical provenance for the original revisions, not decisions on the
later corrected children. The native review import itself made no graph
write.

`304956` notice `attachment_1_3074887:18-32` has eleven vacancy rows and
25 hires. The model had ten roles representing 23 hires because p4 merged
the separately recruited 4급 records role (one hire, line 21) and 5급
records role (two hires, line 23); its quote also crossed the IT vacancy
at line 22. It correctly extracted IT p5 duties 21–24 from JD
`attachment_3_3074889:116-129`, but proposed no NCS links for them.
The no-cost child correction staged at
`/tmp/jobtology-extraction-correction-304956-roster-20260915.json`
(SHA-256 `8c8cc54be6d9ed6da09ceace91b5e71cde2fd29e9b81604b0724ba88e97c17b0`)
isolates p4 to line 21, appends p11 for line 23 and duplicates their
four shared records-JD duties as p11-bound indices 45–48. It preserves
p1–p10, duties 0–44 and the IT role. Pinned schema/source validators
returned `[]`; rolled-back capture proposed revision
`0430c2ffde481ec0cd637668808b17d44c58fe50de3da548884bd55c34d5df94`.

`304963` notice `attachment_1_3074950:12` recruits two `통계` specialists
under the youth-intern administrative route, confirmed by its JD
`attachment_3_3074952:5,17`. Model p1 used only the generic internship
name. The no-cost child correction
`/tmp/jobtology-extraction-correction-304963-statistics-20260915.json`
(SHA-256 `6aad7d77a6e6ae090fc2d31ed4757df6c291b405ff6d14d84fc958d680fb7374`)
renames p1 to source-literal `통계`, preserving its ID and all eight duty
texts, indices and citations. This source remains separate from `304964`,
the veterans notice for one `통계` hire. Schema/source validators returned
`[]`; rolled-back capture proposed revision
`ce2a587fda46eb1e91002d8346323bc2b1ce22cf3cd1373ee2c927e7940db2c9`.
The local preparation and rolled-back validations did not capture either
correction live. The main workstream subsequently captured and `ACCEPT`ed
both children. Their new revision IDs are current, while the old packet
was already imported in the order above. Each corrected child needs
fresh, independently reviewed link candidates; do not carry forward
old candidate IDs or publication decisions.
The `304963`/`304964` A/C PDFs flag image content needing review, so this
assessment uses visible text.

The pinned NCS catalogue offers manual **search targets** for the
corrected roles. For `304956` p5, inspect
`2001030101_19v3` IT시스템 운영 기획 (duty 21),
`2001030111_19v4` IT시스템 통합운영관리 and
`2001030105_19v4` 응용SW 운영관리 (duty 22),
`2001030107_19v4` NW 운영관리 and `2001030108_19v3` DB 운영관리
(duty 23), and `2001030109_19v3` 보안 운영관리 plus
`2001110105_23v2` 개인정보보호 운영 (duty 24). The IT JD at
`attachment_3_3074889:121-129` expressly names those job families
and several unit numbers; each complete NCS definition still needs
review against the cited duty before creating a link.

For `304963` p1, inspect `2001010506_19v3` 통계 기반 데이터 분석 and
`0201030311_18v3` 응용 통계분석 for duties 0/7: JD
`attachment_3_3074952:17,20-21` names statistical analysis,
multivariate/data-mining knowledge and model skills. Its duty 4 says
public-data quality/standards; `2001030407_24v3` 빅데이터 품질 관리
and `2001021109_19v2` 데이터 품질 검증 are only candidates because
their definitions require big-data/DB diagnosis and improvement not
shown in that duty. The model's `2001020409_16v3` 데이터 표준화
match incorrectly targeted administrative budget/personnel duty 5.
Notice line 12 also says `데이터분석 기획 및 활용 지원`; catalogue
`2001010703_24v3` 빅데이터 분석 기획 is worth inspecting, but the
current extraction has no separate planning duty fragment to link.
Avoid catalogue units explicitly marked `구버전`.

### Manual NCS selections for the accepted children

After the corrected revisions were accepted, an independent full-definition
audit staged `/tmp/jobtology-cs-child-manual-ncs-proposals-20260915.json`
(SHA-256 `1bb1d5ec2277b33aaa1981b34def0d5216606c371d46c81b98b15764218fda86`).
It contains the current revision and source hashes, complete NCS
definitions, exact duty indices, source IDs and proposal reasons. The
three **local-only** selections are:

| Accepted child role | Duty | Current NCS code | Supported overlap |
|---|---:|---|---|
| `304956 p5` 기관운영(정보화전략) | 22, `정보시스템 관리` | `2001030111_19v4` IT시스템 통합운영관리 | Notice `attachment_1_3074887:22` assigns system/infrastructure operation; JD `attachment_3_3074889:129` assigns information-system management. This overlaps the NCS system-operation core, without proving every service-quality subprocess. |
| `304956 p5` 기관운영(정보화전략) | 24, `정보보안 및 개인정보 관리` | `2001030109_19v3` 보안 운영관리 | Notice `:22` and JD `:129` assign security management; JD `:138` requires security inspection, log analysis and account-permission skills. This overlaps system security operation, without asserting a complete security program. |
| `304963 p1` 통계 | 0, statistical analysis | `2001010506_19v3` 통계 기반 데이터 분석 | Notice `attachment_1_3074950:12` and JD `attachment_3_3074952:17` assign data/statistical analysis; JD `:20-21` requires advanced statistics and model skills. This supports the core analysis activity, without proving every model/evaluation step. |

The same file records twelve reasoned abstentions. In particular,
`304956`'s generic infrastructure duty does not establish NW traffic
work or DB tuning, and its privacy duty does not establish a privacy
system/incident/education program. `304963`'s public-data standards
duty does not establish DB design or big-data quality diagnosis; its
policy-use analysis duty is not a distinct modeling activity. The
current corrected revisions had zero `link_candidate` rows at this
audit. The selections are proposals for independent review, not
accepted or published links. The JD's unversioned ability-unit list
helps identify candidates but does not by itself establish that a
specific catalogue version applies.

## Second ambiguous A/C queue, downloaded and parsed without models

The pinned ALIO run `4eae07ed-1b70-4146-8e4f-75291c6b6b13`
has six A/C notice/JD files across these postings. The other five
metadata entries are forms or supporting `Z` documents. Deployed
download/parser HWF hashes matched local artifacts; the parser's
read-only health endpoint returned revision
`7541e87c0b45d8d209cd3c110f7bf09c72666779-hop3`.

After graph publication exited successfully, the native download
workflow `attachments/download_snapshot.hwf` planned exactly six files
with `BATCH_ID=cs-second-docs-20260915-a`, this `JOB_RUN_ID`,
`POSTING_IDS=304933|304913|304942`, `MAX_FILES=6`, and
`EXECUTE_DOWNLOADS=N`; its `Y` rerun under the same batch exited 0.
All six were `ARCHIVED_ONLY` with HTTP 200 and immutable raw hashes.
The native parser workflow `attachments/parse_documents.hwf` planned
exactly those six with `BATCH_ID=cs-second-parse-20260915-a`,
`ATTACHMENT_BATCH_IDS=cs-second-docs-20260915-a`, that parser revision,
`MAX_DOCUMENTS=6`, and `EXECUTE_PARSING=N`; its `Y` rerun exited 0.
Five results are `PARSED`; the 304933 outer JD ZIP is `NO_TEXT` with
warning `UNSUPPORTED_ARCHIVE_MEMBER`. Originals remain archived. No
model request, scope decision or graph-link review was made here.

| Posting | A notice file | C job description | Inline CS evidence |
|---|---|---|---|
| `304933` 국토안전관리원, 18 hires | PDF `3074827`, ordinal 3, `PARSED` | JD ZIP `3074757`, ordinal 2, initially `NO_TEXT` under hop3; now `PARSED` under hop4 | **One CS vacancy:** the notice roster explicitly names `정보보안` in `행정/전산`, one hire at Jinju HQ (A Markdown line 24; total 18 line 38). Eligibility repeats `정보보안/행정(전산)` at line 60. |
| `304913` 한국환경공단, one hire | HWP `3074633`, ordinal 1, `PARSED` | HWP `3074635`, ordinal 3, `PARSED` | **No CS vacancy:** roster says environmental temporary employee supporting wastewater e-manifest system operations (A lines 15–16). JD duties are program administration, education/publicity, vehicle-verification hardware installation/field checks and citizen guidance (C lines 1–10), rather than IT/system engineering. Computer certificates are preferred, not a separate role (A lines 294–295). |
| `304942` 의료기관평가인증원, two hires | PDF `3074795`, ordinal 1, `PARSED` | Clinical education evaluator JD PDF `3074801`, ordinal 3, `PARSED` | **No CS vacancy:** the only roster row is two clinical-education institution evaluation researchers (A lines 17–22). JD duties are evaluation standards, field evaluation and project administration; AI tools, data analysis and statistics are supporting skills, and the qualification is a related medical/health/education master's degree (C lines 12–16). |

The 304933 JD archive raw SHA-256 is
`918c143cbe245d98453e26f8a564ee660ce5c01de0b636ccd35ca3fb7fd5c694`.
Read-only inspection showed it contains three nested ZIPs (high-school,
experienced and entry-level), which the then-active hop3 parser did not
recurse into. Inside the entry-level ZIP is exactly one
`신입직/5. ..._신입직(정보보안).pdf`; extracting that PDF **locally for
diagnosis only** yielded SHA-256
`0a30c351b9678ea8bd8462918f91370f82f2cb01698de07c39838937b1e4f162`.
Its two-page JD names the job family `IT` and job `정보보안`; it defines
cyber-attack and vulnerability mitigation, information-security system
operation and data-integrity protection (local layout text lines 3–10).
Tasks include firewall/IPS/segmented-network operation (lines 52–60),
server/OS/DBMS and source-code vulnerability checks (lines 79–94),
plus privacy protection. CS-related preferred majors include
information security, computer engineering, information communications
and software (lines 126–134). This confirms the vacancy is within scope.
The local PDF inspection preceded the native Hop parser record and
source-bound `enrichment.input_bundle` described below.

A one-level nested-ZIP change was implemented in
`services/document-parser/worker.py` in this repository; the upstream
`../document-processor` library stays untouched. It keeps flat member
metadata for the existing Hop input contract, with a raw-hash/name/ordinal
chain for each nested leaf. Fast adapter tests pass. An offline run on this
exact immutable archive with the pinned upstream library parsed all 16 PDFs
(19 flat entries including three ZIP containers) into 48,766 Markdown
characters and 147 contiguous, independently hashed sections, with no
warnings. The information-security PDF leaf hash matched the diagnostic
extraction above. A diagnostic worker response using proposed suffix
`7541e87c0b45d8d209cd3c110f7bf09c72666779-hop4` is saved locally at
`/tmp/jobtology-cs-second-304933-parser-hop4.json` (7,788,074 bytes, SHA-256
`60618320906257c978a7b9ed0e376ca9e19d6fb66ce667178e51323f06559094`).
This diagnostic result preceded the reviewed live deployment. The other two
postings need no paid extraction for the CS cohort.

After confirming zero `RUNNING` parser rows and attachment writers and
coordinating with the other completed parser batch, the private parser
container was replaced with image `jobtology-document-parser:20260915-4`.
Hop read `/health` revision
`7541e87c0b45d8d209cd3c110f7bf09c72666779-hop4`. The Docker
network `coolify`, aliases `jobtology-document-parser` and `parser`,
read-only attachment mount, 2 GiB memory/4 GiB swap/2 CPUs/256 PIDs,
read-only root, 512 MiB `/tmp` tmpfs, dropped capabilities, security
setting, restart and log limits match the prior container. No port was
published. The old image `20260914-3` remains available for rollback.

Native `attachments/parse_documents.hwf` created immutable batch
`cs-second-parse-20260915-hop4-a` over archive batch
`cs-second-docs-20260915-a`, with `MAX_DOCUMENTS=6`,
`REUSE_SUCCESS_FROM_BATCH=cs-second-parse-20260915-a`, and exact hop4
revision. The `EXECUTE_PARSING=N` run exited 0 and showed five prior
`PARSED` hop3 files reused plus only ZIP `3074757` `PLANNED`. The `Y`
rerun exited 0 after exactly one parser request; all six are `PARSED`.
`attachment.verify_processor` passed and no attachment writer remained.
The ZIP result is contract `document-processor-v1`, raw hash
`918c143cbe245d98453e26f8a564ee660ce5c01de0b636ccd35ca3fb7fd5c694`,
result hash
`1002ebd51af31a57d605f0896662fad4e52ac90fcc567f1c10cdfb3cb8b357a2`,
and Markdown text hash
`a7729d2d3661513ef7cd6929940a1347cb4a23fdedfe541b85bdc3de08ebdd5d`.
It has 48,766 characters, 147 pinned sections, 19 archive members and no
warnings; the information-security leaf hash and chain match the offline
diagnostic. The five reused results retain their original hop3 revision,
as required by the provenance contract.

Native `attachments/prepare_processor_inputs.hwf` then used exact
`JOB_RUN_ID=4eae07ed-1b70-4146-8e4f-75291c6b6b13`, this completed
`PROCESSOR_BATCH_ID`, `POSTING_IDS=304933`, `POSTING_LIMIT=1`, blank
`DATASET_ID` and `NCS_RUN_ID=LATEST`. It exited 0 and froze one bundle:

```text
bundle_id   691608e57c169b43e07a0bf42410c8e61ba5a6765f6c327a59acfaf753e9375d
source_hash 73d7e15977a324a8fecf1f88437884a241f02640a14eeedcf1cb0dd32cb0a239
```

`attachment.verify_input_bundle` passed. Its manifest contract is
`document-processor-input-v2`, input contract `attachment-input-v2`,
and it records three source documents: the JD ZIP and notice PDF supply
two parsed fields (`attachment_2_3074757` and
`attachment_3_3074827`); the form remains an outcome without source text.
The ZIP field has the 19 archive-member summaries and exact nested leaf
hash chain. Source JSON is 331,206 characters; pure no-request passage
and document-packet projections are 173,380 and 162,499 characters.
These sizes help plan a future bounded model call; no paid model request
or extraction/link review was made in this pass.

A read-only reconstruction of the installed `ko-link-v1` extraction
request with the prior Luna settings (`openai/gpt-5.6-luna`, provider
`openai`, 8,192 output-token cap, no temperature/reasoning/extra params)
measured 226,522 characters before trace fields and 227,172 with
representative fixed-length session/trace fields. This is below the
prior `MAX_INPUT_CHARS=300000` limit by about 72,828 characters. The
reconstruction queried pure source/prompt/schema functions and made no
enrichment batch or paid request. It includes the 17,747-character
source-bound response schema and 192,066-character user content. The
information-security JD begins at passage `attachment_2_3074757:656`,
names its `IT/정보보안` role at `:668`, and ends before the next member
heading `:791`. The advertised one-hire vacancy is at notice passage
`attachment_3_3074827:24`, with eligibility at `:60`. These locators
identify source passages for the later independent review; they are
not themselves a semantic acceptance decision.

## Targeted extraction and source review

After the frozen inputs were verified, two **one-request** Luna extraction runs
used `openai/gpt-5.6-luna`, provider `openai`, `ko-link-v1`, exact posting and
bundle IDs, `REUSE_CACHE=Y`, `ACCEPTANCE_POLICY=REVIEW` and a request/cost cap.
The 304933 batch `0824ab14-7539-4eb7-aab7-294bfa4cfa14` reported
`$0.0284467`; the 304922 batch `c10e28f6-07c4-4b85-aed7-ec86565efa67`
reported `$0.0184406`. Both extraction attempts were HTTP 200 and
`VALIDATED`. Their batches were `PARTIAL` because the one-request cap deliberately
blocked paid categorization, so the item-level `REJECTED` status means
`CATEGORIZATION_NOT_VALIDATED`, **not** an invalid extraction. No second model
call was needed to identify NCS candidates.

The 304933 model extraction found nine JD roles but **missed** the one-hire
information-security vacancy at notice `attachment_3_3074827:24`. Captured
original revision `99afffa4533ecb579363c20a21d13cbdf004dbac71f17dde4554d6cb0847f862`
was independently `REJECT`ed. A source-exact, p10-only correction from its saved
response, file `data/cs/extraction-correction-304933-security-scoped-20260915.json`,
passed schema and evidence validation in a rolled-back PostgreSQL preview and
was imported and `ACCEPT`ed as revision
`32183132d26748618d2b8cb5baf49c3b7e0d9ed711be412beda36b7e6b430f89`.
It binds four explicit duties from its own JD at passages `:709`, `:711`,
`:733` and `:744`; the other 17 hires remain in immutable source records, with
no claim of completed extraction for their positions. Native scope decision
`225` selected `304933/p10` as `SECURITY`.

The 304922 validated output contained all five advertised vacancy rows and
position p2's own IT strategy, technical-support and project duties at JD
`attachment_2_3074695:35,41`. Original revision
`b968fa65f20a479afa2ce8f0fe5061fa0745fc1caa9f411c9fc7361375c8fcca`
was captured and independently `ACCEPT`ed. Native scope decision `226`
selected only the two-hire p2 IT position as `IT_SYSTEMS`.

No-call manual NCS packet import
`9aa18e4f2b405fa8dcfb671ac9ebe47971771216eb02fe307fecdc79d8c9c65b`
accepted two current security units for `304933/p10` and two current
system-support units for `304922/p2`, after exact-duty and full-definition
review. The related qualification view maps the 304933 security units to
`정보보안산업기사` C325 with three loaded 2026 exam sessions. The 304922 units
show `FETCHED_NO_MAPPING`; a qualification should not be invented for them.
These are related *through NCS*, not employer-mandated credentials.
