# Read-only NCS audit: five newly selected roles (2026-09-16)

This audit uses the pinned current NCS catalog run `a32170ed-7485-4e31-82d3-ed48b3398946`, source-bound Hop extraction, and source eligibility text. It makes no live link or scope decision.

| Posting/role | Accepted or pending duty evidence | Semantic verdict |
| --- | --- | --- |
| 304387/p1 | Accepted revision `f662e7e366ae1add993b20af3edfb70e3fc39a3cf4b4faf5f61de5519fc06e92`, D0–D1: medical-device integrated information-system operation, business management, public/admin system operation; `attachment_1_3071990:22`. | **Abstain.** The notice does not describe HW/network/security coordination needed for current `2001030111_19v4` integrated IT operations, or incident diagnosis/action required by `2001030105_19v4` application-SW operations. |
| 304387/p2 | Same accepted revision, D2–D3: business-management/operations support; information protection, privacy, data-quality management; `attachment_1_3071990:26`. | **Abstain.** Privacy and data-quality terms alone do not establish policy-system operation/incident response (`2001110105_23v2`) or data diagnosis/improvement (`2001021109_19v2`). |
| 304432/p3 | Accepted revision `cf4c6f83fdca05507f00ee8279308bcc714c3d36efc817c5675beb5e727fa0cf`, AI role heading `attachment_1_3072234:14`, no role duty text. | **Abstain.** No substantive technical task is available to match a competency unit. |
| 304606/p7 | Saved extraction D9, “철도안전관리 감독체계 데이터베이스 개발 및 DBMS 구축”, `attachment_2_3073057:11`; JD DBMS/MySQL/Oracle knowledge `attachment_2_3073057:17`. Child accepted revision pending. | **IN_SCOPE technical role; strong link candidate:** `2001020405_19v4` 데이터베이스 구현, DB엔지니어링. Definition: “데이터베이스 구현이란 설계된 데이터베이스 모델을 적용하기 위해 DBMS를 설치하고 데이터베이스와 데이터베이스 오브젝트를 생성하는 능력이다.” Direct DBMS/database build overlap. **Separate eligibility caveat:** notice requires relevant PhD, master plus 5 years of research/teaching, or bachelor plus 8 years (`attachment_1_3073056:24`). Publish only after the p7 child extraction is accepted and duty index confirmed. JD says no required certificate (`attachment_2_3073057:20`); no exact-code qualification mapping was found in the current qualification snapshot. |
| 304687/p1 | Accepted revision `2ba3ce93d3515b1bf33cbc8ce9f3b75990e3261f93a4fa75e53fed7507f691fc`, AI-evaluation prototype D3, platform feature/service-model D4, feasibility prototype D5, `attachment_2_3073519:11`. | **IN_SCOPE technically, but no high-confidence NCS link.** D4 partly overlaps `2001070204_22v2` 인공지능 서비스 모델 기획 (definition requires requirements-derived AI component analysis plus model definition and verification); source describes feature definition/service-model design but not requirements analysis or model verification. Saved model D0 suggestion `2001070101_23v2` 인공지능 플랫폼 구축 계획 lacks the definition's schedule and cost planning. **Separate eligibility caveat:** advertised economics/business invited research fellow requires relevant PhD and 15+ years as responsible senior researcher, or equivalent (`attachment_1_3073518:7`, `attachment_2_3073519:18`). No exact-code qualification mapping was found for `2001070204_22v2`. |

The current `cs-it-ai-data-v1` policy classifies technical work; experience and student eligibility are separate attributes (`docs/hop-migration/cs-posting-completion-plan.md:51–65`). Only the 304606 database-building duty supplies a strong current-NCS unit. The remaining selected roles need richer source duties before high-confidence competency publication.

Subsequent native review accepted the p7-only child extraction for `304606`;
its database/DBMS duty is D3 in the child. Manual review receipt
`f45ed1f72ddc043e5be396a846330900ec258c1ac95cfd0f637daa16a1a83710`
accepted the exact `2001020405_19v4` link, and final graph publication
`cs-reviewed-20260916-final-b` read it back. The other four audited roles
remain selected without a supported unit. See the
[execution record](cs-execution-20260915.md) for current counts.
