# Ten-notice CS source tail audit

Initial read-only audit on 2026-09-16 of the ten lower-priority uncertainties in
[the source screen](cs-pending-source-screen-20260915.md). The frozen ready
JOB-ALIO run remains `4eae07ed-1b70-4146-8e4f-75291c6b6b13`; all ten
`enrichment.linking_status` rows said `PENDING_EXTRACTION` against that
run. At audit start there were zero `attachment.document` rows for these postings. This audit
made no live download, parse, scope, enrichment, review, or graph writes.

The frozen detail records give 19 A/C file IDs. Their original
`opendata.alio.go.kr/recruit/downloadAtchFile` URLs now redirect to the portal
home page (HTTP 200 HTML, identical body for every ID). The official JOB-ALIO
detail pages instead link those same IDs to
`https://www.alio.go.kr/download/download.json?fileNo=<ID>`; all 19 returned
real files with HTTP 200. PDFs were read with `pdftotext -layout`, six HWP
files with local `document-processor` revision
`7541e87c0b45d8d209cd3c110f7bf09c72666779`, and the two image notices
were visually inspected. Local source/text inspection copies are under
`/tmp/jobtology-cs-notice-tail-20260916/`. This was a bounded unpaid source
review, not a production parser batch.

**No source-confirmed IT/AI/data vacancy was missed in these ten notices.**
All ten A/C sources support `OUT_OF_SCOPE` under the existing
`cs-it-ai-data-v1` policy, which requires advertised software, IT-system,
security, data or AI work. Two research notices can be revisited under a
future broader theoretical-CS or quantum-computing policy; neither advertises
an assigned duty in one of the current five families.

| Posting | Exact A/C IDs | Advertised position and decisive evidence | Screen |
|---|---|---|---|
| `304823` | [A `3074155`](https://www.alio.go.kr/download/download.json?fileNo=3074155), [C `3074156`](https://www.alio.go.kr/download/download.json?fileNo=3074156) | Four discrete-mathematics senior researchers. A announcement prioritizes graph theory, combinatorial optimization, matroid theory **and algorithms**; C JD states research in discrete mathematics, without a specific computing duty. | Proposed `OUT_OF_SCOPE` for v1; revisit if a future policy includes theoretical algorithms. |
| `304824` | [A `3074161`](https://www.alio.go.kr/download/download.json?fileNo=3074161), [C `3074162`](https://www.alio.go.kr/download/download.json?fileNo=3074162) | Three senior, three junior and three postdoctoral researchers in trapped-ion apparatus, quantum-information science and laser/optics systems. A describes experimental quantum computer/simulator implementation; C names apparatus/physics research. Programming appears in applicant knowledge/eligibility, not an assigned software duty. | Proposed `OUT_OF_SCOPE` for v1; revisit if a future policy includes experimental quantum computing. |
| `304930` | [A `3074740`](https://www.alio.go.kr/download/download.json?fileNo=3074740) JPEG, [C `3074742`](https://www.alio.go.kr/download/download.json?fileNo=3074742) PDF | A image roster has seven one-hire doctoral education/history fields: English, art, technology, math, ethics/ethics education, Korean and Korean history. C covers education-curriculum, assessment and policy research; its data collection/analysis is general research methodology. | `OUT_OF_CS` source screen; no technical assessment platform, software or data role in the roster/JD. |
| `304938` | [A `3074776`](https://www.alio.go.kr/download/download.json?fileNo=3074776) PDF; no C | Both interns are `사무행정`: one supports HR/general administration, one admissions, alumni and student activities. Information-processing certificates are office-category eligibility. | `OUT_OF_CS` source screen; the one A file contains the complete two-hire roster and duties. |
| `304948` | [A `3074843`](https://www.alio.go.kr/download/download.json?fileNo=3074843), [C `3074845`](https://www.alio.go.kr/download/download.json?fileNo=3074845) PDFs | One exhibition-operations replacement, one administration intern and one exhibition intern. C gives visitor/program operations, administrative planning and exhibition/content research. No digital-collections or IT duty. | `OUT_OF_CS` source screen. |
| `304951` | [A `3074861`](https://www.alio.go.kr/download/download.json?fileNo=3074861) PNG, [C `3074863`](https://www.alio.go.kr/download/download.json?fileNo=3074863) PDF | A image roster: one HR/labor generalist and two electronics research hires. Electronics C JD assigns strategic-goods export classification, sanctions trend analysis, international cooperation and enterprise support. AI/communications equipment specifications are **knowledge of products being assessed**; the institution-wide information-system line is not this position's duty. | `OUT_OF_CS` source screen. |
| `304953` | [A `3074876`](https://www.alio.go.kr/download/download.json?fileNo=3074876), [C `3074877`](https://www.alio.go.kr/download/download.json?fileNo=3074877) HWPs | A accounts for 20 hires: building/facility technical workers and postal machinery operators, guards, cleaners and landscaping. C technical JD covers HVAC, boilers, electrical/building and fire safety equipment; the remaining JDs describe physical-site service. | `OUT_OF_CS` source screen; `기술` means facilities/machinery here. |
| `304966` | [A `3074962`](https://www.alio.go.kr/download/download.json?fileNo=3074962), [C `3074964`](https://www.alio.go.kr/download/download.json?fileNo=3074964) PDFs | Six disability interns support basic document/meeting administration. C `데이터 관리` is clerical record handling alongside filing, printing and shredding. | `OUT_OF_CS` source screen. |
| `304968` | [A `3074970`](https://www.alio.go.kr/download/download.json?fileNo=3074970), [C `3074972`](https://www.alio.go.kr/download/download.json?fileNo=3074972) PDFs | Two operations staff answer livestock-traceability calls, help users operate the existing system, log errors and do general administration. C does not assign software maintenance or data engineering. | `OUT_OF_CS` source screen; remote user help is customer support. |
| `304969` | [A `3074974`](https://www.alio.go.kr/download/download.json?fileNo=3074974), [C `3074976`](https://www.alio.go.kr/download/download.json?fileNo=3074976) PDFs | One part-time disability office/experiment assistant. C is NCS office administration; the shared IT/ADP certificate preference list in A is not a vacancy roster. | `OUT_OF_CS` source screen. |

The v1 proposal covers **57 hires** across ten notices. The theoretical and
quantum research notices account for 13 of those hires and should be reopened
only with a broader versioned scope policy. `PENDING_EXTRACTION` is only the
current automated status, not a reason to send ten paid model requests.

The fresh native `cs/export_scope_review.hwf` export selected exactly the ten
`OUT_OF_SCOPE_CANDIDATE` source-title `posting` cases from the frozen run. Its
completed source-only packet is
`/tmp/jobtology-cs-notice-tail-scope-20260916-completed.json` (SHA-256
`2dfcf6a1f9ecb0ff87caa6d1528b2c42fb6e04ca3be33a8e5fb816b8eaf5eb54`).
Every case proposes `OUT_OF_SCOPE`, leaves `family` null, and cites its own
official A/C file IDs and full raw SHA-256 hashes in `notes`. The native
context was unchanged except for reviewer and those three editable case
fields. The packet was imported after this read-only audit; the final receipt
is below.

Native `cs/import_scope_review.hwf` validated the frozen context and saved all
ten `OUT_OF_SCOPE` source-title decisions. Receipt
`36b6f67e7bf9ff9b724de8e90255be4ff3e443ca6b85393f04204840ddc9c839`
records ten new decisions, zero unchanged decisions and no paid model call.
Live `cs.role_completion` confirms each of the ten `posting` roles is
`OUT_OF_SCOPE` with zero accepted role links. The two research notices stay
excluded **under v1 only** and may be reconsidered under a broader versioned
policy.

Native `attachments/download_snapshot.hwf` first froze, then executed the
immutable `A_C_ONLY` batch `cs-tail-docs-20260916-a` for the same ten postings.
Its 17 supported files were `ARCHIVED_ONLY`, and `attachment.verify_batch`
passed; the two image A notices retain unsupported-format outcomes and were
visually inspected for this decision. Native `attachments/parse_documents.hwf`
froze and executed batch `cs-tail-parse-20260916-a` with the existing
document-processor revision
`7541e87c0b45d8d209cd3c110f7bf09c72666779-hop4`.
All 17 parser documents are `PARSED`, with Markdown and structural JSON
stored in the normal source-provenance database. Parsing made no model calls.

The source hashes for the two scope reviews, in A/C order, are:
`304823` `2bd23a1c01d4fa5bb81c9a3645034becb229759b7811679ccc8202b0f8f0a09a` /
`94586a8b01cefb1fdb80d00c90f522aa3888a17a22756bb7688912c89b2391aa`;
`304824` `9e6ac9bfc31cbee9a51a2c11a7ece5888146b2e7a470163e1fdb61e999c7f716` /
`84e5f822ee9652f6d5855135e5e05e0a695212a4a279005eca07fffefaecebd3`.
