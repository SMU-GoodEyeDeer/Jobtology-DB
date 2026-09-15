# CS scope screen: false-negative audit

Read-only audit on Goldship, 2026-09-15, against the latest ready ALIO snapshot
`4eae07ed-1b70-4146-8e4f-75291c6b6b13`. The audit exported all 1,954 rows
from `cs.current_scope` with position title, duty text, NCS source categories and
extraction evidence IDs. It then inspected the 1,833 rows whose **screen** result
was `OUT_OF_SCOPE_CANDIDATE`. These counts are a snapshot, not stable review
counts: exporting an NCS link-review packet can create a new extraction revision
and invalidate a source-bound scope decision for that posting. The link-review
work in progress caused 33 such decisions to become stale; the reviewer must
rebind them after importing extraction reviews.

The following rows are missed **advertised-position candidates**. Their saved
extraction duties provide a technical work signal; `IN_SCOPE` still needs an
explicit source-bound decision. NCS matching needs its own definition/duty
review.

| Posting / role | Source evidence | Why the current screen misses it | Audit judgment |
|---|---|---|---|
| `304557/p2` 플랫폼 아키텍처 설계·운영 | `attachment_4_3073355:24`: Kubernetes container-platform design/operation, CI/CD automation, SpringBoot common-service development | No `쿠버네티스`, `CI/CD`, platform architecture or common-service development cue | Clear IT systems/software candidate |
| `304632/p4` 기술 (청년) | `attachment_1_3073185:15`: cyber-threat monitoring, smishing detection, ransomware attack analysis | Existing security cue requires `사이버 보안`, `침해 대응`, etc.; this duty uses `사이버 위협정보` | Clear cybersecurity candidate; physical-product testing is a separate duty |
| `304695/p2` 전산&lt;br&gt;개발 | `attachment_1_3073551:13`: Java/SQL/Python information-system development/operation, UI development | HTML line breaks split the title; software cue misses `정보시스템(...) 개발` | Clear software candidate |
| `304697/p12` 선임 연구원 | `attachment_1_3073553:53`: linked-data collection/operation, structure and standards, quality validation | `데이터 구조 검토` / `품질검증` do not match current data patterns | Clear data-engineering candidate |
| `304697/p13` 연구원 | `attachment_1_3073553:54`: linked-data cleaning, quality checks, extraction/deidentification, metadata | `데이터 정제`, `품질점검`, `메타데이터` are absent | Clear data-operations candidate |
| `304717/p10` 문헌정보 | `attachment_1_3073619:31`: intelligent search-platform build/operation, engineering knowledge-data structure and AI search service | Generic `플랫폼` and `AI 기반` are deliberately absent, but this combined duty is technical | Mixed library/technical role; technical duties are a clear candidate |
| `304859/p3` 퀀트 주식 운용 | `attachment_1_3074376:12`: quant strategy and monitoring-system development/operation, financial-data hypothesis testing, stock portfolio management | Generic `시스템 개발` and `금융 데이터` are deliberately absent | Mixed quant engineering/investment role; count only system/data duties |

These additional rows need evidence or boundary review before deciding whether
they satisfy the technical CS policy:

| Posting / role | Evidence and question |
|---|---|
| `304557/p1` IT 사업 관리·컨설팅 | `attachment_4_3073355:1` covers IT project roadmaps, requirements/scope checks and delivery monitoring. Decide whether technical IT project work is within the intended student-relevant scope; it is not hands-on platform engineering. |
| `304680/p4` IT | Source title says IT internship, but extracted duty is only `은행업무 지원`; inspect its actual placement/JD. Do not match NCS on the title alone. |
| `304687/p1` 초빙연구위원 | `attachment_2_3073519:5` covers an AI policy-idea evaluation-platform prototype and implementation, but also advisory/policy work. Confirm whether the implementation is substantive advertised work. |
| `304697/p1` 중급 기술자 | `attachment_1_3073553` mixes privacy governance and informationization-project preapproval; not clearly technical security or IT operations. |
| `304697/p16` 고급 기술자 | `attachment_1_3073553:63` says `정보화사업 기획ž운영ž유지관리`, without system-level work detail. |
| `304822/p1` 첨단방사선AI융합연구팀 | `attachment_1_3074151:18` says AI-based CBCT image enhancement/registration research plus radiation-device duties; inspect whether AI model/algorithm research is material. |
| `304896/p9` 개인정보보호 | `attachment_3_3074559:294` includes privacy-system use/access checks and incident prevention but mostly policy, audits and education. Decide whether technical security is a material duty. |
| `304432/p7` 고교 정보통신 | No extracted duty text; the track/title is suggestive but cannot support an NCS competency link. |

Do **not** add broad `AI`, `통계`, `정보통신`, `시스템 개발`, `플랫폼`, or
`정보화` matches across titles, duties **and** posting-level categories. They would
promote nontechnical positions in mixed notices. Examples include `304387/p3`
(AI medical-device grant administration), `304403/p4` (reporting illegal horse
racing websites), `304833/p1` (AI vessel standardization and office support),
`304672/p2` (routine official-statistics record management), and `304664/p1`
(ICT aid-project administration). `304851/p1` is LAN cable installation and OA
consumables, rather than software or system administration. A person using a
system is not its developer/operator.

One repeated attachment needs separate source-specific role validation. The
exact `자율주행 데이터 관련 연구과제 업무`, `자동차 통합보안 관련 연구과제 업무`
and metaverse test-environment duties occur as `p36/p37/p39` in **19 different**
한국교통안전공단 notices, including `304541` (single-office administrative title)
and `304634` (자동차정보처 사무보조). These likely came from a shared attachment
listing all agency openings. Do not count those roles in each notice merely
because the extractor emitted them. First verify which vacancy each notice
actually recruits.

The source-only screen has a separate blind spot. `304933` (국토안전관리원
general/professional), `304956` (국가아동권리보장원 staff) and `304958` (LH
graduate hires) are **new `PENDING_EXTRACTION` postings** with generic titles
and source-level `정보통신` categories, but their only fallback `posting` role is
currently `OUT_OF_SCOPE_CANDIDATE`. `304713` is a generic mixed-category notice
with `EXTRACTION_FAILED`. Their category does not prove a technical vacancy,
yet they cannot be confidently excluded without a cheap vacancy/attachment
check. `304913` has a technical-looking system-operation title and is already a
review candidate; it has no saved extraction. These are source-screening
priorities before any new paid extraction call.

## Narrow candidate-screening change

Keep all new matches in `NEEDS_REVIEW`; a regex must never accept a scope role or
NCS link. The current screen uses one function for title, duties **and** the
posting-wide NCS category list. Consider title-only aliases separately so
`IT`, `ICT` or `정보통신` do not elevate every role in an otherwise mixed notice.
Normalize HTML breaks in position titles before matching. These additional
**duty** phrases are narrow enough to queue the clear cases above:

| Family | Candidate cue, restricted to role duty text |
|---|---|
| Software / IT systems | `쿠버네티스`, `CI/CD`, `플랫폼 아키텍처`, `정보시스템.{0,80}개발`, `지능형 검색플랫폼 구축` |
| Security | `사이버 위협정보`, `랜섬웨어`, `스미싱` |
| Data | `데이터 구조 검토`, `데이터 정제`, `데이터 품질(점검\|검증)`, `메타데이터`, `지식 데이터 구조화` |
| AI / software | `AI 기반 ... 평가체계` only when paired with `프로토타입 구현`; quant `시스템 개발 및 운영` only when paired with `퀀트` |

On this frozen export, a sample of the narrow title/duty cues plus a title-only
`IT` token would queue **14 additional positions** from the 1,833 current
exclusions. The sample excludes bare `정보통신`, which needs a separate
source-specific check for `304432/p7`. This is a triage count, not 14 accepted
positions. After adding a
cue, export a new source-bound review packet for those exact identities and
roles, review the vacancy-specific source evidence, and decide the roles.

## Accepted-cohort vacancy check

A follow-up read-only export checked all **47 current `IN_SCOPE` roles in 37 ALIO
postings** against each current ALIO notice title, recruitment/eligibility text,
saved role duty and evidence ID. It compared the duty text of every accepted role
and hashes of the 70 attachment bodies in their exact-current-hash input
bundles. No accepted duty is identical across two different postings, and no
accepted posting shares an exact attachment-body hash with another accepted
posting. **None** of the 19 repeated 한국교통안전공단 roster notices has an accepted
role. There is therefore no *proven* accepted ghost role from the shared-roster
problem in the current 47-role cohort. This evidence check does not prove that
every model-extracted role assignment is correct; source-bound review remains
necessary after new extraction revisions.

Some accepted roles are real vacancies but lie near the edge of the technical
CS scope. Their current acceptance should be reconsidered as a **policy**
question, not automatically deleted as a ghost role:

| Posting / role | Vacancy-specific source check | Boundary question |
|---|---|---|
| `304500/p1` KDN조공E | The AMI notice recruits two KDN조공 and one field assistant. Its JD says modem installation/opening, AMI communications maintenance and simple construction; construction safety training and high-work vehicle ability are relevant. | Is a field communications-equipment worker within CS-related IT systems, or outside the intended network-engineering scope? Likely outside if the intended jobs require system administration or software/network design. |
| `304714/p1` 업무보조원 | The AMI notice explicitly recruits an assistant. The JD includes modem/DCU opening paperwork, remote field support and communications maintenance; construction safety training is listed. | It is a genuine job but much of the work is support paperwork and field-equipment assistance. |
| `304492/p6` 통신 전자 | The mixed new-hire notice's JD covers wireless switching equipment design, procurement, installation/test and system monitoring. | Communications engineering is technical, but the role may be primarily hardware/construction rather than CS IT systems. |
| `304403/p3` AI·빅데이터 전문 청년인턴 | The horse-racing agency notice advertises this intern separately. Duties are chatbot Q&A data preparation, response checking and UI/UX test support. | This is applied AI/data quality work, but little direct model/software engineering; determine whether substantive preprocessing/QA is enough. |
| `304879/p2` 식품위해예측센터장 | The source expressly recruits the centre director. The role **directs** AI prediction-model development and database/forecast-system construction alongside staffing, budgets and policy oversight. | If the policy requires hands-on technical duties, this senior management position may be outside; seniority alone is not an exclusion in the current plan. |

`304254/p1` 항만 forecasts cargo volume with econometric/AI methods and operates
a prediction system alongside policy research, so it is mixed but has a real data
analysis duty. `304833/p2` directly preprocesses maritime big data and analyzes
data quality while supporting an AI-platform trial. Neither is a repeated-roster
ghost; keep their role-specific duties visible when judging NCS links.
