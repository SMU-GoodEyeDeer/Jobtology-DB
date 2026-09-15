# Position-specific NCS gap audit, 2026-09-15

Read-only audit of the six `IN_SCOPE` ALIO positions without an accepted
position-specific NCS link. The source snapshot is
`4eae07ed-1b70-4146-8e4f-75291c6b6b13`; the current NCS snapshot is
`a32170ed-7485-4e31-82d3-ed48b3398946`. Codes and duty indexes below
are **review candidates**, not decisions or published graph edges. No API
calls or database writes were made for this audit.

| Posting / role | Supported candidate code and zero-based duty index | Source basis |
| --- | --- | --- |
| `304432` / `p4` ICT | `2001020214_23v6` 애플리케이션 배포 (`21`); `2001020227_23v6` 애플리케이션 테스트 수행 (`21`); `2001020412_19v4` 데이터 전환 (`22`); `2001020601_25v6` 보안 구축 계획 수립 (`23`); `2001020703_25v4` 사용자 리서치 (`24`); `2001020710_25v3` UI/UX 가이드 제작 (`24`); `2001030105_19v4` 응용SW 운영관리 (`25`) | ICT JD `attachment_3_3072236`, lines 110, 117–123, 125–152: explicit deployment/testing, DB conversion, security planning and risk, UX research/guide, and software/system inspection and incident action. |
| `304439` / `p7` 전산 | `2001030313_25v3` 시스템 유지보수관리 (`24` or `25`); `2001030304_25v5` 시스템 장애 대응 (`26`) | 전산 JD `attachment_3_3072270`, lines 148, 155, 157–158: IT technical support classification plus planned maintenance, technical inquiries and 장애처리. `2001030303_25v4` 기술지원 요청 관리 on duty `25` is plausible if the reviewer finds the stated analogous-inquiry handling enough to support issue classification. |
| `304717` / `p9` 전산 | `2001020219_23v6` 애플리케이션 요구사항 분석 (`33`); `2001020221_23v6` 애플리케이션 설계 (`33`); `2001020227_23v6` 애플리케이션 테스트 수행 (`33`); `2001020401_19v4` 데이터베이스 요구사항 분석 (`34`); `2001020403_19v4` 논리 데이터베이스 설계 (`34`); `2001020405_19v4` 데이터베이스 구현 (`34`); `2001070306_23v2` 인공지능 모델 학습 (`35`); `2001060105_19v2` 보안 위험관리 (`36`) | 전산 JD `attachment_3_3073621`, lines 222–242 explicitly names the corresponding work and NCS families. |
| `304836` / `p1` AI활용 신약개발 | `1703060302_21v1` 의약품연구개발 후보화합물 설계·도출 (`4`) | Employer JD `attachment_3_3074242`, lines 6–11: virtual drug screening and lead compound optimization. The NCS unit definition covers compound screening and optimization. Employer explicitly calls its AI molecular-design specialization an NCS-undeveloped field; this candidate is an inferred overlapping activity, not its official exact classification. |

`304474` / `p7` produces dementia-policy statistics and annual indicators
(`attachment_1_3072442`, lines 333–341). The apparent catalog alternatives
require hospital-operations statistics, survey methods, secondary-data
selection, or model-based analysis that the JD does not state. Abstain pending
more specific employer duty evidence or a suitable NCS unit.

`304697` / `p8` supports information-system operation, monitors its state and
answers user complaints (`attachment_1_3073553`, line 43). The nearby IT
units require direct integrated operation, classified technical-support
request management, or monitoring with issue analysis and response planning.
Those extra activities are not stated. Abstain pending better duty evidence.

All six saved categorizations used a 60-entry NCS shortlist shared across
every role in each posting. Current proposed links target other roles. The
supported current NCS units listed above were absent from the corresponding
saved shortlists, which explains why reusing the old model suggestions alone
cannot fill these four positions. Manual candidate proposal and independent
review against the pinned source and NCS snapshots can fill them without a
new paid model call.

## Current selected-role remainder

The earlier six-row audit was a review queue, not the final gap count. After
source-bound corrections, manual NCS imports and scope decisions on 2026-09-15,
`cs.role_completion` reports **eight** `IN_SCOPE` positions with zero accepted
role-specific links. Five are distinct KISA `304632` tracks: `p3n02` AI-security
analysis, `p3n12` spam-data classification verification, `p4s02` cyber-threat
monitoring, `p4s03` smishing-threat detection/analysis and `p4s04` ransomware
attack/group analysis. Their one-line duties identify technical work but do not
establish the incident response, control-operation, training-data or risk-plan
steps required by the nearby current category-20 NCS unit definitions. Keep the
five positions selected while recording a source/catalogue evidence gap.

The other three are `304474/p7`, `304697/p8` and `304697/p12`. The first two
retain the specific abstentions above. The latter's notice
`attachment_1_3073553:53` assigns linked biobank-data collection, structure and
standard-criterion review, verification-result checking and dataset-release
documentation. Current `2001021105_19v2` requires defining and establishing a
data-architecture-based standard policy; `2001021109_19v2` requires diagnosing
and improving data quality. This source says it applies standards and checks
results/errors, not that it creates the policy or diagnoses/improves quality.
No paid model retry can add those missing employer actions to the source.
