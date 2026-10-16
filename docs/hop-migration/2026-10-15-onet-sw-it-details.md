# O*NET 31.0 SW/IT reference details

Status: **production loaded and independently VERIFIED at
2026-10-15 12:09:01.616752 UTC**. All prior PostgreSQL data/metadata and typed
graph objects are preserved exactly; bounded consumer readback follows below.

## Purpose and evidence boundary

The user selected **Assess and load the reference details**. This extends the
existing O*NET 31.0 reference catalogue with software examples, essential and
transferable skills, knowledge, tasks and their official ratings for a bounded
SW/IT occupation scope. It does not rerun occupation matching or require an LLM
call. Reference acquisition and deterministic import have **$0 LLM cost**.

An O*NET occupation-to-software association means that the official occupational
reference lists that software example. Traversing a posting's existing inferred
occupation link to that example does **not** establish an employer requirement,
source-stated skill, duty, proficiency or mandatory/preferred condition. A source
posting's explicit technology mention needs its own original field/span evidence.
Official occupational ratings describe their published population and scale;
they are not posting-specific importance ratings or model confidence.

Existing posting links retain their actual review status, `STAGING`,
`current=false` and NULL/UNASSESSED confidence. No occupation reclassification,
NCS rematching or posting-specific skill extraction is part of this load. Source
and NCS facts, catalogue namespaces and strict explicit-duty contracts remain
separate. Job-board URLs and signed content references remain inert.

## Scope and existing posting coverage

The selection is all catalogue occupation codes beginning `15-12`, plus
`15-2051.00` Data Scientists, `11-3021.00` Computer and Information Systems
Managers and `17-2061.00` Computer Hardware Engineers: **31 catalogue terms**.
The existing final posting plan links **30** of those codes. The remaining
`15-1299.00` Computer Occupations, All Other has no posting link and no detail
rows in any of the six selected official domains; its catalogue term remains.

The assessment uses the immutable October 14 final accepted PostgreSQL plan,
not a claim that current source facts were revalidated on October 15. Its
12,696 links include **5,908 scoped links on 5,835 distinct source postings**:

| Source | Scoped links | Distinct scoped postings |
| --- | ---: | ---: |
| JobKorea | 5,854 | 5,781 |
| Nara | 46 | 46 |
| JOB-ALIO | 8 | 8 |
| Total | 5,908 | 5,835 |

The largest linked occupations are Software Developers (`15-1252.00`, 2,638),
Web Developers (`15-1254.00`, 606), Network and Computer Systems Administrators
(`15-1244.00`, 500), Computer Systems Engineers/Architects (`15-1299.08`, 342)
and Information Security Analysts (`15-1212.00`, 340). These counts concern
existing inferred occupation edges, not validated skill requirements.

The protected local assessment is
`~/.local/state/jobtology-hop/onet-sw-it-local-assessment-20261015/assessment.json`,
SHA256 `e5ad372584494a532d452d761882a53e7c114ca7a0f5500a1771783a3211f14f`.
It binds the full code-level counts, frozen cohort and original selected export.
The accepted-plan file is
`~/.local/state/jobtology-hop/onet-matches/20261014T131612Z-independent-graph-acceptance-2dc174efae95/postgresql-plan.json`,
SHA256 `2d96f45e588e2cc1c50507cdf885f0000aee55795a7ae480152051419a898ac0`.

The separate bounded production readback is **VERIFIED at
12:09:19.412373 UTC on October 15**. It confirms **30 enriched occupations and
16,472 direct reference observations**. Existing scoped links and links whose
frozen source-fact hash matches the current posting were counted separately;
both currently give exactly the table above: **5,908 links on 5,835 postings**.
Thus the historical plan count and actual current-source traversal agree at
this readback; they remain separate measurements, not a promise about future
refreshes. The five exact Software Developers examples **Docker, Kubernetes,
PostgreSQL, Python and React** are present, each with official
`hot_technology=true` and `in_demand=true`. These remain occupational examples,
not automatically posting requirements.

All 12 bounded scalar rows passed, without a source/provider call or database
write. Protected readback receipt:
`~/.local/state/jobtology-hop/onet-sw-it-local-assessment-20261015/postload-readback-a60c08030bd94ad195132749953ae67d/receipt.json`,
SHA256 `5cf25ff3d034491e4a2aeeed471ee1cb8a696eb68f2b157ac123db88c4a6cec9`.

## Available local posting evidence

The selected JobKorea export was rechecked locally: **8,434 rows, 21,951,764
bytes**, SHA256
`6a1d853aaca446a8c9a6081a8bfe3347ad24e496b5915e1ba2e50571b1d33d72`.
It contains no dedicated skills, technology-stack or keyword field, and no
embedded description/duty text. Description URLs are references only. All 8,434
frozen JobKorea facts retain `content_status=MISSING` and
`extraction_eligible=false`. This does not block the reference import.

The frozen metadata contains 8,434 nonempty titles, 6,693 roles, 6,815 raw job
position values and 523 job-function values. The importer removes non-role
logistics when forming `role`, so the raw position count is higher. These fields
can support a later, separately labeled **explicit metadata mention** path with
deterministic aliases first, exact field/span provenance, versioned alias rules
and abstention for ambiguous names. They cannot establish duties or whether a
technology is mandatory, preferred or merely part of a role label.

An illustrative local boundary-matching scan of title/role/job-functions found
855 postings mentioning at least one of Python, Java, JavaScript, C++, C#, SQL,
React or AWS. Per-name counts overlap: Python 90, Java 530, JavaScript 8, C++ 59,
C# 96, SQL 15, React 129 and AWS 63. This is a feasibility observation, not a
validated extraction benchmark or new graph fact. A production mention path
must handle aliases, casing, short tokens, negation, ambiguous product names and
scope before publication. No paid call is needed for deterministic mentions.

## Official inputs

The pinned source release remains **31.0**, matching the existing
`onet-31.0-catalogue-20261014` catalogue. The official archive is
[O*NET 31.0 database](https://www.onetcenter.org/db_releases.html), with CSV
inputs under the official `db_31_0_csv` release path. Acquisition receipts retain
original bytes, SHA256, byte lengths, source URLs and download timestamps outside
Git. Download/import time is not the source survey date; source dates and other
official row metadata are retained separately.

Attribution: O*NET 31.0 Database, U.S. Department of Labor, Employment and
Training Administration (USDOL/ETA), under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), as stated in the
[database license](https://www.onetcenter.org/license_db.html). O*NET® is a
trademark of USDOL/ETA. Jobtology selects this occupation scope, normalizes
identifiers and typed fields, and adds processing provenance and hashes.
USDOL/ETA has not approved, endorsed or tested these modifications. Preserve
the attribution, license and modification notice when redistributing the data.

The selected source domains have 5,837 Software Skills rows, 600 Essential
Skills ratings, 1,500 Transferable Skills ratings, 1,980 Knowledge ratings, 660
Task Statements and 5,895 Task Ratings (4,585 frequency, 655 importance and 655
relevance). Five selected tasks have no supplied ratings. A missing rating is
not zero. Source-wide content model, scales, task-category and level-anchor
reference files provide the row semantics; only reachable references are needed
for this scoped load.

Software Skills includes `Workplace Example`, element identity/name,
`Hot Technology` and `In Demand`. These are separate fields; neither a Boolean
flag nor an example is a proficiency rating. Essential Skills, Transferable
Skills and Knowledge carry their own official scales and statistical metadata.
Task-frequency categories are retained as separate category rows rather than
collapsed to one score. The source's Software Skills file replaces the older
Technology Skills naming; the import follows the actual pinned 31.0 files.
See the official [Software Skills dictionary](https://www.onetcenter.org/dictionary/31.0/csv/software_skills.html),
[Essential Skills dictionary](https://www.onetcenter.org/dictionary/31.0/csv/essential_skills.html)
and [Task Ratings dictionary](https://www.onetcenter.org/dictionary/31.0/csv/task_ratings.html).

## Additive representation

The `onet_detail` PostgreSQL schema holds immutable normalized source evidence,
release pins and native graph checkpoints. Original CSV bytes and acquisition
receipts stay in the protected local bundle. Every selected observation keeps
its source file, URL, physical CSV line locator and original row values.
Numbers, integers and Y/N flags normalize to numeric, integer and Boolean
properties. Source NULL/empty optional values remain explicit in PostgreSQL;
Neo4j omits their properties. Original lexical values remain available in the
row evidence, including statistical precision and update dates.

Detail nodes use `entity:onetDetail` plus their kind label, with identities under
`urn:jobtology:onet-detail:` and owner `jobtology-onet-details-v1`. The existing
`urn:jobtology:onet:` catalogue identities and `onetCatalogObject` labels are
unchanged. The distinct prefix, labels and owner keep existing catalogue scope
guards and posting matcher consumers separate from this detail projection.
Occupation endpoints are read and verified; the detail writer adds direct
reference relationships without modifying occupation properties or labels.

The direct relationships are `ONET_SOFTWARE_EXAMPLE`, `ONET_ESSENTIAL_SKILL`,
`ONET_TRANSFERABLE_SKILL`, `ONET_KNOWLEDGE`, `ONET_TASK` and
`ONET_TASK_RATING`. Software example nodes retain the example and its official
element classification; occupation-specific Hot Technology/In Demand flags stay
on the association. Rated edges keep their scale, category, data value, sample
size, standard error, confidence interval bounds, suppression/relevance flags,
update date and domain source when supplied. Reference nodes also preserve
content-model ancestry, scale bounds, task-frequency categories and relevant
level anchors. No rated observation is collapsed across scales or categories.
The selected scales are Importance (`IM`, 1–5), Level (`LV`, 0–7), Frequency
(`FT`, 0–100 percent for each category) and Relevance (`RT`, 0–100). The import
preserves the published values; it does not rescale all domains to percentages.

The prepared immutable bundle is
`~/.local/state/jobtology-hop/onet-details-bundle-31.0-sw-it-20261015/`.
Its `details.json` has **19,301,339 bytes**, SHA256
`5b1d710bde425a31216f859394b0a2197dd124241f1e2a11f8c7e767ab5ffa03`.
The ten original CSVs total **62,731,552 bytes**. The normalized plan contains
**2,598 detail nodes** and **18,609 relationships**, all independently verified
in the actual production load below.

| Detail node kind | Count |
| --- | ---: |
| Software examples, identified by exact example and classification | 1,517 |
| Tasks | 660 |
| Content-model elements including ancestors | 206 |
| Level anchors | 204 |
| Task-frequency categories | 7 |
| Scales | 4 |

The relationships comprise 5,895 task ratings, 5,837 occupation/software
associations, 1,980 knowledge ratings, 1,517 software/classification links,
1,500 transferable-skill ratings, 660 occupation/tasks, 600 essential-skill
ratings, 205 element/parent links, 204 anchor/element links, 204 anchor/scale
links and seven category/scale links. This is the selected six-domain extension;
abilities, work context, work activities and other full-database domains remain
outside this load.

## Retrieval and browser rendering

Use a table view with selected scalar fields for initial exploration. A single
software-developer occupation has hundreds of software associations; expanding
all linked postings and every reference neighbor can produce a large graph even
when the source import is small. Reference rows are fetched on demand; adding
them does not require returning them in the default posting-list query.

The [runtime README](../../hop/ingestions/onet_details/README.md) includes optional
GraSS captions for software examples, element names, task IDs/statements and
scale names. Keep those kind labels above generic labels in Browser's Results
overview so their caption rules take priority. This is a client display setting;
it does not change the qualified import or graph data.

Start from an exact occupation identity, choose one domain, return 25–50 rows,
and paginate by the stable owned edge ID. Avoid unrestricted variable-length
paths, returning whole nodes with their raw provenance payloads, or automatically
expanding all posting-to-occupation-to-reference neighbors. `LIMIT` bounds the
returned rows; it does not guarantee that an arbitrary sort or broad expansion
has cheap database execution. No browser performance gain is claimed without a
measured comparison.

Consumers must compare the inferred edge's frozen `source_facts_sha256` with the
posting's current hash before presenting the association as based on current
metadata. They must not filter on `r.current=true`, since these inferred links
intentionally remain `STAGING/current=false`. Keep the actual review status
visible alongside the occupation inference.

This first page lists occupation-level software examples. For the next page,
replace the empty cursor with the last `edge_id`:

```cypher
MATCH (o:entity:onetCatalogObject:occupation {
  id:'urn:jobtology:onet:occupation:15-1252.00', current:true
})-[r:ONET_SOFTWARE_EXAMPLE]->(s:onetDetail:software)
WHERE r.current=true AND s.current=true AND r.id > ''
RETURN r.id AS edge_id, o.code AS occupation_code,
       s.workplace_example AS software,
       r.hot_technology AS hot_technology, r.in_demand AS in_demand
ORDER BY edge_id LIMIT 25;
```

Retrieve one rating scale at a time, retaining its actual scale and source
quality flags. Suppressed or not-relevant ratings need explicit display/filter
decisions; the import keeps them as evidence:

```cypher
MATCH (o:entity:onetCatalogObject:occupation {
  id:'urn:jobtology:onet:occupation:15-1252.00', current:true
})-[r:ONET_ESSENTIAL_SKILL]->(e:onetDetail:element)
WHERE r.current=true AND e.current=true AND r.scale_id='IM'
RETURN e.element_name AS skill, r.data_value AS importance,
       r.scale_name AS scale, r.n AS sample_size,
       r.recommend_suppress AS recommend_suppress,
       r.not_relevant AS not_relevant, r.date AS updated
ORDER BY importance DESC, skill LIMIT 25;
```

To inspect a posting, first retrieve its bounded occupation-inference table with
an exact posting identity. The client can then request a selected occupation's
reference page above. This keeps inferred role evidence and occupational
reference examples visible as separate steps:

```cypher
MATCH (p:entity:jobPosting {id:$posting_id})
      -[r:INFERRED_ONET_OCCUPATION]->(o:entity:onetCatalogObject:occupation)
WHERE r.managed_by='jobtology-onet-matching-v1'
  AND r.source_facts_sha256=p.source_facts_sha256
  AND o.current=true
RETURN p.id AS posting_id, p.name AS title, o.code AS occupation_code,
       o.name AS occupation, r.basis AS basis,
       r.review_status AS review_status, r.stage AS stage
ORDER BY r.match_rank LIMIT 10;
```

Separate performance TODO: the coordinator's October 15 read-only observation
found the scheduled Nara refresh `20261015T093002Z` still running at about
10:58 UTC under source-graph writer
`b8d1694a-98cf-4ef9-bd62-1432d527ed2e`. `verify_posting_dates` took 237.888
seconds for 10,396 rows; `verify_totals` began at 10:37:39 UTC and its query
had been active for 1,224 seconds at observation. This identifies unfinished
routine verification work, not its cause. No stop or performance fix belongs
to this reference task. Take a fresh production preservation baseline after
that writer finishes; the historical October 14 source count is not a current
production attestation.

A subsequent read-only inspection at 11:03:36.701 UTC located the active
PostgreSQL work in `ingestion.graph_source_edge_owners`, elapsed 1,556.999
seconds, with no blocker PIDs or reported wait event. EXPLAIN-only inspection
of the live function bodies estimated one owner row; the nested edge path
materialized an estimated 61,940 records and 113,935 references across an
estimated 68 READY runs before downstream selection. These are planner
estimates, not observed row counts or a proven cause. Later isolated profiling
should separate the owner query from nested edge/run assessments, preserve all
validity guards, and compare prepared-parameter and literal plans. No ANALYZE,
query cancellation, production write or concurrent live Hop launch occurred.
The exact query and plans remain protected under
`~/.local/state/jobtology-hop/onet-sw-it-local-assessment-20261015/slow-nara/`;
`diagnostic.json` SHA256
`cc6067bc5a4bad1a7bc2a60ed734ce9c143e1107e8bea67bcef3b673e011e13d`.

At 11:19:39 UTC the same query had reached 2,519.501 seconds. Historical
SQL009 qualification measured Nara owner SQL at 4.070 seconds and native
`verify_totals` at 1.644–1.649 seconds for 10,555 owners on fixed analyzed
statistics. The live record table's last analysis was October 14, with 13,970
subsequent modifications and today's run absent from the `run_id` most-common
values. Fresh-run cardinality/statistics is a grounded hypothesis for later
isolated work, not an established cause or permission to run ANALYZE. The
qualified warm archive does not establish current fresh-READY latency; no
completion ETA follows from these observations. See the
[earlier reader evidence](2026-10-14-entity-reader-performance.md) and protected
`statistics-observation.json` / `prior-owner-comparison.json` in the same folder.

The scheduled run subsequently **completed naturally at 11:24:51 UTC**.
Its log records `verify_totals` at **2,822.874 seconds**, the graph workflow at
6,354.115 seconds and the full scheduled workflow at 6,886.484 seconds.
The coordinator's fresh check under `refresh.lock` at about 11:27:52 UTC passed:
idle CLI, zero retention writers, Nara projection READY with 12,904 records and
12,904 references, content SHA256
`b3b8b7377b671350bcc14bce44b813c8cfded78c82eeb7dd82365e68ceaca606`
and an existing graph-export checkpoint. The `onet_detail` schema was absent.
The source-writer block is resolved. No query cancellation, ANALYZE, archive replay or scheduler change
was performed. The proposed recovery plan remains `NOT_EXECUTED`, superseded
by natural completion; no recovery script was created. The performance cause
remains a separate TODO. Protected `natural-completion.json` binds the log and
these timings in the same diagnostic folder.

## Qualification and recovery

The parser's 13 focused tests and Ruff passed; replaying the real local inputs
produced the same immutable bundle bytes. The full-bundle PostgreSQL core
fixture passed its checks, including atomic invalid-endpoint rollback,
immutable replay/rejection of changed input, exact 2,598-node/18,609-edge
projection and immutable evidence enforcement. The coordinator's 130 focused
tests, Ruff and whitespace checks passed.

Final isolated native qualification **PASSED all 42 checks**, with complete
resource cleanup. It verifies all 2,598 detail nodes and 18,609 relationships,
exact typed preservation of the fixture's 1,599 legacy nodes/3,171 legacy
relationships and all prior PostgreSQL data/function metadata, source and
import atomicity, exact replay, five native edge-negative cases, old catalogue
verifier compatibility and writer cleanup. The positive full load completed
in 49.812 seconds and replay in 111.728 seconds; these are isolated observations,
not production throughput claims. Final proof:
`~/.local/state/jobtology-hop/onet-native-dbe98b0568c9/receipt.json`, SHA256
`ca8169cb0dafca74d8d31ff96cdbea64c58409721dda0aeb177f7f4b02ac7e1b`.
It binds the 22 current public native artifacts and the accepted loader/parser
hashes. The predecessor 32-check proof at `onet-native-5128c4f61702` remains
historical evidence and is not the deployment gate.

The authorized production loader started at 11:45:55 UTC and is
**VERIFIED_ONET_DETAILS at 12:09:01.616752 UTC**. Its 1,513,661,603-byte protected
PostgreSQL backup is retained. The native workflow passed at 12:03:20 UTC in
628.612 seconds. Independent acceptance then verified exact equality of all
**187 preexisting PostgreSQL tables and metadata**, every one of the
**203,145 old nodes and 767,984 old relationships**, and every new detail
object's typed properties, labels, relationship type and endpoints against the
immutable PostgreSQL plan. The graph now has **205,743 nodes and 786,593
relationships**, adding exactly 2,598 nodes/18,609 relationships. Existing
source/NCS/O*NET matching evidence and review status remain unchanged.
Native load ID: `06f23410-c139-4dbf-9517-c24daa86a567`. The operation fence was
removed and its absence verified. Source requests, provider calls and posting
matching calls are all **zero** for this reference task. Production receipt:
`~/.local/state/jobtology-hop/onet-details-load-6ddc16c10052421288bef1cbb80ece2c/receipt.json`,
SHA256 `412ef210b50e74f348cd2470b9b3273be21df2741137664dc8a7788c0df34056`.
The final read-only scheduler check matches its original 143 bytes, SHA256
`5c932e4bc2b6024dcba2945d226491af227e608aee71178d1f9e0d7b784999fd`;
no scheduler change or restoration action occurred.

Production performance TODO: `graph_preflight_edges` took **576.104 seconds**
within the 628.612-second native workflow. In the same log, node preflight took
1.445 seconds, edge writing 4.908 seconds and edge verification 9.350 seconds.
These are logged pipeline observations, not an exclusive operator breakdown.
Read-only diagnostics showed progressing 500-row batches and about one Neo4j
CPU core, with no measured lock/wait in the sampled queries. The exact live
operator cause was not profiled. The qualified isolated preflight still scans
global relationships once per batch; a later scoped performance investigation
should preserve every identity/type/endpoint/property collision guard and use
the actual production graph cardinality. No broader production speedup is
established. Protected diagnostic:
`~/.local/state/jobtology-hop/onet-details-load-6ddc16c10052421288bef1cbb80ece2c/readonly-progress/diagnostic-receipt.json`,
SHA256 `a4847f690dc1a4855b05df3f283456e7e638009d559528d2820071499951837c`.

A separate **isolated preflight** comparison used baseline/narrowed/narrowed/
baseline order: 17.210/2.074/1.640/10.011 seconds. Both variants scanned the
same 21,780 global relationships once per 500-row batch. Narrowing candidates
to that batch reduced the candidate list from 18,609 to 500, per-row filter
hits from 9,304,500 to 250,000, and reported memory from 15,489,984 to 416,272
bytes. This measures only the isolated preflight query; it establishes no
production or whole-load gain. The successor passed full native qualification
above. Protected profile:
`~/.local/state/jobtology-hop/onet-details-profile-20261015/report.json`, SHA256
`fb238e32282e57c56034c142b15b9b3c7a6b2968bb5235269c36af84cd6156d4`.

The additive coordinator requires an exact cleaned isolated native proof,
acquires the operation lock, requires idle writers and takes a protected
PostgreSQL backup. It compares every preexisting application table and typed
graph object, plus every new owned object against the immutable PostgreSQL
plan. The production receipt above records the actual complete acceptance;
prepared counts alone are not a substitute for that proof.

Recovery uses the same immutable READY release through
`replay_details.hwf`, with exact preflight and native readback. Changed evidence
under the same ID is rejected; different-release rollover is currently refused
with `ONET_DETAILS_ROLLOVER_REQUIRES_QUALIFICATION`. There is no qualified
destructive removal command. Retain the backup and receipts for any separately
reviewed recovery; do not delete catalogue, source or matching evidence.
Maintainer commands and workflow parameters are in the
[detail runtime README](../../hop/ingestions/onet_details/README.md).
