# CS qualification refresh receipt, 2026-09-15

The source-qualified CS occupation policy was installed through native Hop
`cs/install.hwf` on Goldship at 14:03 UTC. The mounted public files were staged
and renamed in place; the container did not restart. The preceding Hop
`cs/install.hwf` and `ingestions/ncs_qualification/start_run.hpl` are backed up at
`~/.local/state/jobtology-hop/qualification-deploy-HN2ovfXe/prior/`. The new
`cs/sql/006_qualification_support.sql` had no preceding live file. The protected
deployment directory also holds SHA-256 manifests and redacted Basic logs.

The policy has 22 enabled occupation codes: the 11 original qualification
occupations and the 11 category-20 occupations supported by accepted in-scope
CS role links. They select 281 versioned NCS units in the pinned competency run
`a32170ed-7485-4e31-82d3-ed48b3398946`. The old READY qualification run
`2b485d2e-715c-4310-b5fc-4ffbd663de7a` still has exactly 139 expected and
recorded partitions and zero reference-scope issues. No historical partitions
were rewritten.

| Native refresh | New READY run | Input run | Partitions | Confirmed empty | Archived requests | Parsed rows | Graph checkpoint |
|---|---|---|---:|---:|---:|---:|---:|
| NCS qualifications | `1cf7e9e1-1eb9-4978-9335-ccd4a7f8c729` | NCS competency `a32170ed-7485-4e31-82d3-ed48b3398946` | 281 | 199 | 480 | 150 qualification mappings, 48 credential codes | yes |
| Q-Net 2026–2027 | `66aa4bd0-5fca-4fd0-b92f-562a346938e3` | Qualification `1cf7e9e1-1eb9-4978-9335-ccd4a7f8c729` | 96 | 66 | 162 | 85 exam sessions, 30 credential codes | yes |

Both native `operations/refresh_*.hwf` wrappers exited 0 after PostgreSQL
validation and Neo4j verification. Both runs have zero `validation_issue` and
zero `reference_scope_issue`. Every recorded provider request ended as
`RESPONSE_ARCHIVED`; neither refresh made a model request. The qualification
refresh used `MAX_PAGES=1000`; the Q-Net refresh used `MAX_PAGES=300`, the exact
new qualification input, and `YEAR_FROM=2026,YEAR_TO=2027`. Per-source rolling
budgets remained below 1,000 requests in 24 hours.

`ingestion.related_qualification_report` supplies a source-qualified, best-effort
credential path. For example, the accepted link from ALIO posting `304686`,
position `p1`, to NCS unit `2001020231_23v5` resolves to five related
credentials in the new qualification snapshot. All five have Q-Net exam
sessions in the new schedule snapshot. This is an NCS relationship; it does not
claim that the employer requires those credentials.

```sql
SELECT source_id, source_posting_id, position_id, ncs_unit_code,
       qualification_code, qualification_name,
       qualification_status, exam_status,
       jsonb_array_length(exam_sessions) AS sessions
FROM ingestion.related_qualification_report(
 '[{"source_id":"job_alio","source_posting_id":"304686",
    "position_id":"p1","link_id":"example",
    "ncs_unit_code":"2001020231_23v5"}]'::jsonb,
 '1cf7e9e1-1eb9-4978-9335-ccd4a7f8c729',
 '66aa4bd0-5fca-4fd0-b92f-562a346938e3');
```

The source snapshot refresh schedules remain unchanged. Subsequent Q-Net runs
will pin the latest READY qualification run unless given an exact input. The
accepted CS role links can be assessed against the latest READY pair without
new API calls through native `cs/read_qualification.hwf` and
`cs/read_qualification_summary.hwf`. Their source-qualified,
`IN_SCOPE`/role-binding views are installed by
`cs/install_qualification_status.hwf` from `cs/sql/007_qualification_status.sql`.
The exact `POSTING_IDENTITY` parameter is required for both readers. A blank
identity returns zero rows; the native summary finished in 4 seconds with zero
rows, and the native detail returned 11 rows for
`job-alio:posting:304686` in 22 seconds (19 seconds in its database transform).
An unfiltered full-cohort benchmark hit a 120-second database timeout while
evaluating CS scope, so the readers deliberately require one posting identity
until that underlying scope query is optimized. No source or model calls occur
in these reads. The earlier reader artifacts are backed up under
`prior/status-007/readers-before-required-identity/` in the protected
deployment directory.

For the `304686` programming NCS unit, the five related qualifications are
`T2E6` (SW개발 L2), `T3A6` (SW개발 L3), `E801` (임베디드기능사), `C290`
(정보처리산업기사), and `E921` (프로그래밍기능사); each is
`HAS_RELATED_QUALIFICATION` and `HAS_EXAM_SESSION` in the READY pair.
The accepted statistics link for `304964`/`p1` to NCS
`2001010506_19v3` resolves to `T5H0` (빅데이터분석 L5) with
`HAS_RELATED_QUALIFICATION` but `FETCHED_NO_EXAM_SESSION`. An empty
schedule result is recorded as a coverage status, not an employer requirement.

Two newly accepted in-scope links point outside the current 22-code
qualification policy. `304557`/`p2` uses `20020110` (클라우드플랫폼구축, nine
NCS units), and `304697`/`p13` uses `20010211` (데이터아키텍처, ten NCS units).
Their qualification status is `UNFETCHED_QUALIFICATION_PARTITION`, rather
than a confirmed empty mapping. Enable those exact two occupations at the
next reference refresh after the 24-hour API request window; the additional
19 unit partitions are estimated to need about 32 requests at the observed
empty-page rate. Refresh Q-Net only if the new NCS qualification run yields
additional schedulable codes. No additional provider calls were made for
this audit.
