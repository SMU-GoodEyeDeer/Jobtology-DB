# ALIO CS scope tail audit, 2026-09-16

At audit start, `cs.current_scope` had exactly nine `NEEDS_REVIEW` ALIO
roles. I exported those nine with native `cs/export_scope_review.hwf` to
`data/cs/scope-tail-audit-20260916.json` in the mounted Hop project (SHA-256
`21dff44be6a8b27d30b51b019d1c45d5464f353bc6edc7584d9e54e64cde63c7`).
The audit read the pinned attachment text and the newly parsed `304913` notice
and JD. The five decisions below are **candidates only**; no review import,
model request, or graph write occurred in this audit. A completed five-decision
packet is at `/tmp/cs-scope-tail-audit-completed-20260916.json` (SHA-256
`8b213876fd845f91ca65a1c9b7e6b067a79edbe6d867c51fc25067957a7e2a39`);
the other four cases remain `null`.

The `cs-it-ai-data-v1` policy selects recruited technical work, regardless of
seniority or student eligibility. Trend research, programme support, and a
technical title alone do not establish software, IT-system, security, data, or
AI work.

| Role | Candidate | Exact pinned evidence and reason |
| --- | --- | --- |
| `304632/p1n07` | `OUT_OF_SCOPE` | `attachment_2_3073186:19` assigns a software-supply-chain **security-policy and technology-trend survey**. The knowledge/skill rows `:23–24` describe research, OA and report writing; no software build or security assessment is assigned. |
| `304632/p3n04` | `OUT_OF_SCOPE` | `attachment_2_3073186:62` assigns support for domestic/foreign quantum-cryptography **trend analysis**. Skills at `:66–67` are trend collection and reporting, with no cryptography implementation or security operation. |
| `304632/p3n06` | `OUT_OF_SCOPE` | `attachment_2_3073186:62` assigns AI-based DevSecOps **trend-analysis support**. No pipeline engineering, model implementation or security operation is specified; skills at `:66–67` are research and reporting. |
| `304632/p3n10` | `OUT_OF_SCOPE` | `attachment_2_3073186:62` assigns security-regulation and security-threat **trend-analysis support**. The skill row `:67` does not add direct incident analysis, testing or security operation. |
| `304913/posting` | `OUT_OF_SCOPE` | Newly parsed A notice `attachment_1_3074633:15–16` advertises one environmental support hire. Parsed C JD `attachment_3_3074635:1–10` assigns wastewater e-handoff programme administration, education, vehicle-verification hardware field checks, and citizen guidance. It does not assign information-system engineering or technical operation. The source-only scope packet has no role evidence IDs for this posting, so the parsed A/C IDs should be cited in the review note. |

| Role | Remains `NEEDS_REVIEW` because |
| --- | --- |
| `304632/p3n01` | `attachment_2_3073186:62` couples information-system asset inventory with “LLM optimization support”; there is no concrete model or system task. |
| `304632/p3n03` | The same line says disclosure-system “management” and industry-scheme support. The shared role range at `:58` mentions technical systems operation, but the numbered assignment does not distinguish engineering from administrative disclosure handling. |
| `304632/p3n11` | The same line says pseudonymous-data institution inspection and linked-hub “building support”; it does not say whether the intern builds data infrastructure or supports the programme. |
| `304680/p4` | `attachment_1_3073461:16` recruits a distinct 12-person `IT` bank-intern category, while `:25` gives only generic “banking-business support” duties. Actual IT placement duties or JD are needed. |

The KISA technical-group JD's shared range at `attachment_2_3073186:58`
mentions system-operations support, security/AI trend surveys and scheme support;
its numbered choice at `:62` determines the recruit's own assignment. The five
exclusions rely on the numbered choice and the OA/reporting skill rows. None
provides a duty-level NCS link. The four unresolved cases need a role-specific
JD, placement detail, or accepted corrected extraction before a scope decision.

After this audit, native `cs/import_scope_review.hwf` imported the five named
exclusions without editing frozen context. Receipt
`16ba2149f5dad360d9b32e1cc6abbecc76dadee404a0598e1a3287d0554bcfea`
records five new assistant decisions and zero unchanged decisions. The other
four cases were `null` and remain `NEEDS_REVIEW`; no NCS/graph link was
approved by this import.
