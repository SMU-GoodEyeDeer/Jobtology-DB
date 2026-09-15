# Remaining ALIO CS scope review, 2026-09-15

The latest READY ALIO snapshot `4eae07ed-1b70-4146-8e4f-75291c6b6b13`
had 19 advertised positions at `cs.current_scope.scope_status = NEEDS_REVIEW`
when this pass began. I exported their frozen role/source contexts with native
`cs/export_scope_review.hwf`, inspected the pinned attachment text and parsed
role duties, then imported 10 explicit assistant decisions with native
`cs/import_scope_review.hwf`. No LLM request or graph publication was involved.

The successful import receipt is
`7049a31e2587513e6f311bfaaa8edaf7119fc130035af035cd0b60ee2e9b9215`
(`new_decisions=10`, `unchanged_decisions=0`, `replayed=false`). The runtime
review files are
`data/cs/scope-review-uncertain-20260915.json` and
`data/cs/scope-review-uncertain-completed-20260915.json` under the mounted Hop
project. The completed file changes only reviewer fields and the 10 explicit
case decisions, families and notes; all 19 source-bound contexts are unchanged.
The [packet workflow](../../hop/cs/REVIEW_PACKETS.md) explains the immutable
review contract and how to export a fresh packet after a source refresh.

| ALIO posting / role | Decision | Pinned source evidence and reason |
| --- | --- | --- |
| `304387/p1` medical-device integrated system operator | `IN_SCOPE / IT_SYSTEMS` | `attachment_1_3071990` assigns operation of public and administrative information systems; information-system experience and a computer/IT major are preferred. |
| `304387/p2` medical-device system management | `IN_SCOPE / IT_SYSTEMS` | The same attachment separately assigns system-operations support, information/privacy protection and data quality, with IT experience/major preferred. |
| `304432/p3` AI recruitment unit | `IN_SCOPE / AI` | `attachment_1_3072234` advertises six separate AI hires, examined in AI fundamentals, machine learning, algorithm analysis and AI systems. **There is no unit-specific duty JD**, so this scope decision does not establish any NCS link. |
| `304606/p7` railway D-SMS researcher | `IN_SCOPE / DATA` | `attachment_2_3073057` assigns D-SMS system development, database/DBMS construction and implementation of evaluation-model features; the notice requires computer, communications, IT or AI education/experience. |
| `304687/p1` KDI invited researcher | `IN_SCOPE / AI` | `attachment_2_3073519` assigns AI evaluation-system design and prototype implementation; `attachment_1_3073518` asks for AI-system/prototype research experience. |
| `304632/p3n09` KISA vulnerability-check programme support | `OUT_OF_SCOPE` | `attachment_2_3073186` choice 9 assigns support-centre and vulnerability-check **programme** support; it does not assign the intern actual technical testing. |
| `304632/p4s05` KISA SME AI-threat market survey | `OUT_OF_SCOPE` | The same attachment's Seoul choice 5 is technology and market-trend survey for a support programme, without detection, model development or security operation. |
| `304713/p9` seed-vault biological research | `OUT_OF_SCOPE` | `attachment_1_3073606` uses a DB for seed storage/inventory and conservation coordination; no database/system engineering is assigned. |
| `304833/p3` vessel-safety research support | `OUT_OF_SCOPE` | Role-specific `attachment_2_3074215` assigns project/design review and evaluating AI/data technology applicability. AI model training appears in generic NCS unit lists, not in the hire's assigned duties. |
| `304901/p3` Jeonbuk emergency-care researcher | `OUT_OF_SCOPE` | `attachment_1_3074582` defines council/performance-report support and Excel/statistical-program data processing. It does not assign substantive computational or statistical analysis. |

After import, the live `cs.current_scope` view reported 64 `IN_SCOPE`, 9
`NEEDS_REVIEW`, 93 `OUT_OF_SCOPE`, and 1,791
`OUT_OF_SCOPE_CANDIDATE` role rows across the current ALIO source. The nine
remaining cases have sparse or mixed wording:

| ALIO posting / role | Why it remains in review |
| --- | --- |
| `304632/p1n07` | Software supply-chain security policy and technology-trend survey; actual technical assessment is unspecified. |
| `304632/p3n01` | LLM optimization is coupled with asset inventory; no concrete model/system action is described. |
| `304632/p3n03` | Disclosure-system “management” could mean technical operation or administrative reporting. |
| `304632/p3n04` | Quantum-cryptography trend survey may be technical research, but no technical work product is assigned. |
| `304632/p3n06` | AI DevSecOps technology-trend survey does not state pipeline engineering or security operation. |
| `304632/p3n10` | Security-threat and industry-regulation trends are mixed, with no direct incident analysis assigned. |
| `304632/p3n11` | Pseudonymous-data institution inspection and hub-building support do not separate data engineering from programme support. |
| `304680/p4` | A distinct `IT` bank-intern placement is advertised, but `attachment_1_3073461` gives only generic “banking-business support” duties. |
| `304913/posting` | The title says electronic-handoff-system operation, but the current snapshot has no prepared duty/JD extraction for this newly fetched posting. |

These nine are an explicit small review tail. A future JD or accepted corrected
extraction can resolve them with a newly exported native scope packet. In
particular, do not infer an NCS link for `304432/p3` from its AI title/exam or
for `304913/posting` from its title alone.

## Source-bound extraction follow-up, 2026-09-16

The four source-backed positions `304387/p1,p2`, `304606/p7` and `304687/p1`
needed accepted extraction revisions before duty-level NCS review. No model
call, NCS decision or graph write was made in this follow-up.

- Native `llm/export_link_review.hwf` and `llm/import_link_review.hwf` captured
  and accepted `304387` revision
  `f662e7e366ae1add993b20af3edfb70e3fc39a3cf4b4faf5f61de5519fc06e92`
  with seven advertised roles and 13 source-exact duties (p1 `D0–D1`, p2
  `D2–D3`); receipt
  `6ba82f97cf7d1d564fd01b539c1f8c502bdad241614c3beb1dd881fc2e36ca40`.
  The same workflows accepted `304687` revision
  `2ba3ce93d3515b1bf33cbc8ce9f3b75990e3261f93a4fa75e53fed7507f691fc`
  with one role and seven duties (`D0–D6`; AI prototype work `D3–D5`);
  receipt
  `85bcff3120a5b7d0220037edd8407bc4d0365fbd11c833a3e149e5c5c13b5952`.
  Their previously accepted scope decisions were rebound after revision capture
  with native `cs/import_scope_review.hwf`, receipt
  `3429e53e43070ca30643aebe63f8edae29d40c838ed066d3579a5a34c430fb18`.
- The prior `304606` model revision
  `a117b11fdadba5790e61ba4168bb09cc282891c1410ea1d90896c6446f6d940b`
  remains **REJECTED** (decision row `32`): it extracted 40 unrelated
  agency-wide roles from the integrated recruitment attachment. Native
  `llm/import_correction.hwf` appended a source-bound child containing only
  the advertised 철도안전처 `위촉연구원4급` role `p7` and its six exact duties:
  revision
  `a9c5a0533f2869bf78d2508dc081351be579d63d3ddbcb50d3067540b6f90437`.
  All seven position/duty evidence quotes occur exactly in pinned
  `attachment_1_3073056` or `attachment_2_3073057`. Native
  `llm/review_extraction.hwf` accepted this child (decision row `170`). Its
  zero-based indices are D-SMS development `D2`, **database/DBMS construction
  `D3`**, evaluation-model integration `D4` and weighted-inspection feature
  implementation `D5`. Native scope rebind restored `304606/p7` to
  `IN_SCOPE / DATA` on the accepted child, receipt
  `cbe0ad3d790bbe075ad60a2c715fc57292053b283ad84d8e90e182fb332e8af8`.

A read-only live check confirmed all four exact role rows remain `IN_SCOPE`
and point to the accepted revisions above. The new `304606` duty indices
replace the rejected revision's old D6–D11 indices; old model link candidates
must not be imported onto the child.
