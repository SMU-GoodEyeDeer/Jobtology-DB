# ADR 0001: MVP source and collection contracts

- Status: accepted
- Date: 2026-09-05

## Decision

The fetching layer uses the following fixed contracts for the Korean CS/AI student MVP:

1. JOB-ALIO is collected through public-data service `15125273`. The connector enumerates the
   complete active list and then requests the official detail endpoint for every discovered
   `recrutPblntSn`. The former web-page scraping idea is retired.
2. ALIO institution identity is collected through public-data service `15125287`, keyed by
   `instCd`. An exported spreadsheet is not the primary source.
3. NCS career-path data is a pinned, one-time official file. It is fetched once and checked monthly
   for a replacement; it is not represented as a monthly-changing feed.
4. NCS-to-qualification calls are partitioned by full versioned competency-unit code. Q-Net schedule
   calls are partitioned by year and four-character qualification item code so that qualification
   context is retained even when a response omits it.
5. Saramin covers current posting discovery metadata for exactly these MVP search partitions by
   default: AI engineer, backend developer, frontend developer, and data analyst. It is not treated
   as a full job-description or requirement source, and this project does not scrape Saramin pages.
   JOB-ALIO and NCS provide the initial requirement evidence.
6. JOB-ALIO attachment metadata may be retained with the official API body. Attachment bytes are
   excluded until a later rights-policy revision explicitly permits their retrieval and processing.
7. Work24 is not an MVP dependency because its Open API requires an enterprise-member account. Its
   dormant post-MVP connector is limited to NCS division `20` and course-type codes `C0061`, `C0104`,
   and `C0105`; it remains rights-blocked and no credential is expected for this school project.
8. A source must pass the checked-in versioned rights registry before its connector can be planned
   or run. Public-data API/file bodies are enabled. Saramin and Work24 stay blocked until written
   permission covers raw retention, normalized facts, excerpts, and model processing.
9. Saramin's published 500-posting daily allowance is not treated as sufficient for the plan's
   complete-snapshot contract. Its production connector and cadence require a later ADR after the
   provider confirms both rights and an adequate quota; the checked-in connector remains blocked.
10. Live contract probes on 2026-09-06 established two provider details that are stricter than the
    catalog tables: CQ-Net accepts the NCS credential only as lowercase `serviceKey`, and both
    HRDKorea qualification endpoints cap `numOfRows` at 50. The checked-in connectors use those live
    contracts and retain regression tests for them.
11. The CQ-Net competency endpoint can change its implicit row ordering between page requests. A
    downstream partition may be derived only from one `SCHEDULED_FULL` run whose selected row count
    and unique `ncsClCd` count both equal the declared total. Overlapping or missing pages fail closed;
    records from different runs are never unioned to manufacture completeness.

## Consequences

- Collection is reproducible from explicit source partitions rather than UI pages.
- A one-page backfill is only a smoke test. Only an uncapped `scheduled-full` run can proceed toward
  completeness validation.
- Fetch completion leaves a run at `RUNNING/FETCHED`; parsing, record-identity/count reconciliation,
  schema mapping, evidence validation, and publication must succeed before `SUCCEEDED` is allowed.
- Changing endpoints, content scope, or permissions requires a new rights-policy revision and a new
  ADR when it changes these contracts.
