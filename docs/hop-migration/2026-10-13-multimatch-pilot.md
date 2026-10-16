# Real metadata occupation v3 pilot — 2026-10-13

The paid pilot processed **15 distinct frozen listings with 15 requests**, under
`ko-metadata-occupation-v3`, the existing lighter model/provider routing,
`MAX_MATCHES=3` and 1,536 output tokens. Four responses passed validation: two
matched listings with four candidate occupations, and two abstentions. Eleven
responses were rejected. Independent review accepted **one candidate** and
rejected three. **Current v3 is not ready to scale.** No Neo4j publication occurred.

Only the supplied local listing `title`, `role` and `job_functions` fields were
used. This assessment measures consistency with that metadata and the pinned NCS
catalogue; it does not establish full-description truth, source-stated duties,
competency evidence or population precision. Confidence remains NULL/UNASSESSED.
Multiple NCS occupations can describe independently supported, nonoverlapping
roles within one hybrid vacancy; separate vacancies are not required.

The exact JobKorea pin is
`jobkorea-ndjson-83bdacb6f319187632a8f1b3228a94d49429966443a41a423e8ca2da7e0c5a4c`;
the current NCS pin is `64c20b47-0575-476e-9a28-d58d16d8c939`. Preparation created
new current-pin catalogue/bindings while preserving historical NCS
`ba32f673-255c-4990-80d4-8dbef6008e2f`, all 8,434 frozen bundles and old source,
prompt, result, review and 5,878-row legacy publication fingerprints. No job-board
HTTP, O*NET import, credential or account change occurred.

The supervisor's accounting fix now includes **all metadata-inference batches
across job/NCS pins and prompt versions**, including unknown reservation holds.
`current_pin_cost` is diagnostic; admission requires
`task_cost_scope=ALL_METADATA_INFERENCE_BATCHES_V1`. Defaults remain unchanged.
The host helper SHA256 is
`d26ed71980b38f824baa327f1c733f5549b5386ef69b50ffb513cc3fdc946fa2`;
its nine focused tests and Ruff passed.

| Accounting | USD |
|---|---:|
| Native all-scope spending before pilot | 4.08154925 |
| Pilot: all 15 charged responses, including rejections/abstentions | 0.00952315 |
| Native spending after pilot | 4.09107240 |
| Separate historical health probe | 0.00000780 |
| Combined task total | 4.09108020 |
| Combined $5 cap remaining | 0.90891980 |
| Observed cost per 1,000 processed postings | 0.63487667 |

All pilot charges were reported upstream BYOK inference costs; reported router
fees were zero. There are no unknown costs or unsettled reservations. The pilot's
incremental ceiling was $0.15; the native task ceiling remains $4.9999922, leaving
the probe within the combined $5 cap. Cost uses all 15 processed postings as its
denominator. This purposive small sample does not establish representative cost
or accuracy. Total usage was 25,180 prompt and 2,692 completion tokens; all 15
finish reasons were `stop`, so no output truncation was observed.

The original paid batch stopped after one charged structural rejection, leaving
14 rows PLANNED and unsent. Its immutable PARTIAL state remains unchanged. After
explicit coordinator review, those 14 never-sent postings were processed once
each in fresh singleton batches, capped at one request/$0.005 each. No charged
posting was retried. A `COMPLETE` supervisor receipt describes stage completion;
individual batch and attempt states determine classification outcomes.

Ten listings failed the identical-anchor evidence requirement: a `role_anchor`
object must appear unchanged in its own evidence array; a longer quotation
containing the anchor does not satisfy the contract. Several rejected responses
proposed plausible PM/developer, web/operations or IT/general-affairs occupation
pairs. Other failures caught duplicate occupation codes, a nonliteral corrected
source spelling, reused/overlapping anchors and repeated rank one. These format
failures are separate from semantic problems: ambiguous PM meanings, overlapping
QA/testing scope, and unsupported AI or security specializations. Structural
success also allowed an unresolved operations-title/developer-role conflict and
unsupported training-data construction. The two abstentions were the explicit
training course and a conservatively unresolved maintenance-PM listing.

The original 20-row dry selection exposed five shortlist gaps before payment;
these rows were excluded from the paid set, without widening retrieval or retrying:

| Source record ID | Missing occupation coverage |
|---|---|
| 50017236 | IT project management, 20010401 |
| 50127168 | IT project management, 20010401 |
| 49932761 | IT project management, 20010401 |
| 50014722 | Application SW engineering 20010202; UI/UX engineering 20010207 |
| 50127009 | Application SW engineering, 20010202 |

Root independently reviewed all 15 proposals and the four captured candidates
against the pinned NCS scope. The append-only decisions were recorded atomically
and read back using reviewer `codex-root-20261013-multimatch-pilot`, kind
`assistant`, with unchanged pins/bindings/ledger and historical fingerprints:

| Decision ID | NCS occupation | Actual decision and reason |
|---|---|---|
| 1 | 20010705 AI service implementation | ACCEPT: explicit AI service development engineer/service developer supports this broad metadata inference. |
| 2 | 20010702 AI service planning | REJECT: AI content solution planning versus content creation using AI remains unresolved. |
| 3 | 20010704 AI service operations management | REJECT: explicit operations title conflicts with AI developer role. |
| 4 | 20010706 AI learning-data construction | REJECT: data classification does not establish training-data construction; source conflict also remains. |

There is one assistant-reviewed candidate in the current-pin PostgreSQL projection;
no new graph edges were published. Review completion does not change source or
competency evidence, confidence, or the strict explicit-duty `ko-link-v1` path.

Evidence is protected outside Git. The
[compact 15-listing packet](/home/maxjo/.local/state/jobtology-hop/multimatch-real-pilot-20261013-ae457be8c7cc/final-compact-review-packet.json)
contains exact source/binding references, every parsed response and issue, retrieved
code/name lists and NCS context. The
[original dry-plan receipt](/home/maxjo/.local/state/jobtology-hop/inferred-occupations/20261013T034344Z-plan-283a2ce7eaf4/receipt.json),
[first paid receipt](/home/maxjo/.local/state/jobtology-hop/inferred-occupations/20261013T035423Z-execute-06964d9afaad/receipt.json)
and
[14-singleton continuation receipt](/home/maxjo/.local/state/jobtology-hop/multimatch-real-pilot-20261013-ae457be8c7cc/continuation-singleton-execution.json)
retain the execution ledger. The
[sealed independent root review](/home/maxjo/.local/state/jobtology-hop/multimatch-real-pilot-20261013-ae457be8c7cc/root-review-decisions.json),
[assessment clarification](/home/maxjo/.local/state/jobtology-hop/multimatch-real-pilot-20261013-ae457be8c7cc/final-quality-assessment-clarification.json)
and
[successful four-decision receipt](/home/maxjo/.local/state/jobtology-hop/multimatch-real-pilot-20261013-ae457be8c7cc/root-review-write-receipt-corrected.json)
record review provenance. The first review-recording transaction had a quoting
error in its extra script guard and rolled back with zero writes; its failed
receipt remains historical. The corrected transaction completed at
`2026-10-13T04:23:41.679606Z` and verified decisions 1–4. It made no paid request.

Required follow-up before scaling:

1. Introduce a new immutable prompt/request/cache identity with explicit format
   examples for exact anchor objects, ranks and unique occupation codes. Preserve
   frozen v3 prompt/SQL and all pilot responses; any normalization change must be
   independently versioned and tested, with no silent evidence repair.
2. Improve bounded shortlist coverage of every explicit role, including the five
   observed gaps. Test compound/abbreviated roles while keeping unrelated labels
   from supplying unsupported occupations.
3. Strengthen PM ambiguity, title/role conflict and occupation-scope abstention:
   distinguish product/project management, AI service/content work, training-data
   construction, QA/test governance and security-product certification. A hybrid
   vacancy alone is not a rejection reason.
4. Run focused offline/native regression tests, then freeze the revised prompt,
   selection and explicit incremental budget within the remaining combined task
   cap for coordinator review before another bounded paid assessment. Measure all
   charged failures and independent candidate review outcomes before deciding
   whether to scale or publish. No additional paid run or publication was performed
   in this pilot.
