# Processing pipeline verification

Date: 2026-09-06. Scope: local verification only; no main-server deployment or scheduler activation.

## Results

- Standard suite: 144 tests passed with PostgreSQL 18 and Neo4j integration enabled.
- Added full-corpus end-to-end test: passed in 147.99 seconds.
- The standard suite includes the new fetch-wrapper budget test: zero HTTP requests after the limit.
- Ruff, Pyright, Git whitespace checks, Docker build, and container CLI checks passed.
- The container runs as UID 10001, can write its data directory, reads the six-source schedule,
  and contains no baked-in `.env`. Its foreground worker exited with code 0 on SIGTERM while idle
  after an expected missing-configuration failure.

Together these exercise 145 tests. The full-corpus test is opt-in because it requires the locally
retained source snapshots; ordinary test runs skip it unless explicitly enabled.

## Full-corpus test

The test reads the six selected raw runs documented in [collection-status.md](collection-status.md)
without modifying their original database or files. Every HTTP request is intercepted by a strict
`MockTransport` lookup against saved response bytes. Missing fixtures fail; there is no live-network
fallback. The normal updater, fetch wrapper, dependency partition derivation, parser, staging loader,
and Neo4j loader run against disposable local PostgreSQL 18 and Neo4j databases.

| Scenario | Verified result |
| --- | --- |
| Initial six-source fetch → process → graph staging | All sources READY; 29,902 records |
| Request enumeration | 878 saved HTTP responses replayed, including repeated empty partitions |
| Immediate second updater tick | All sources NOT_DUE; zero additional HTTP requests |
| Process and Neo4j replay | Zero new revisions; all graph manifests still match |
| Simulated change to posting 304534's title | Its matching list/detail representations produce exactly two new revisions |
| Changed-job updater tick | 510 postings retained; JOB-ALIO changed=true; other five sources NOT_DUE |
| Total transport activity | 1,394 replayed requests; zero live upstream requests |

The simulated title change exists only in the disposable test responses. It is not new upstream
data and was not written to the original local collection. Graph loading was staging-only: no
serving corpus, active-release pointer, backend, frontend, or production Neo4j was changed.

## Reproduction

Configure `JOBTOLOGY_TEST_DATABASE_URL` for a disposable database whose name ends with `_test`, and
`JOBTOLOGY_TEST_NEO4J_URI` / `JOBTOLOGY_TEST_NEO4J_PASSWORD` for a disposable Neo4j instance. The local
`.env` still identifies the original **read-only input** collection for the opt-in corpus test.

```bash
uv run pytest -k 'not saved_six_source_corpus_end_to_end'
JOBTOLOGY_TEST_REPLAY_SAVED_CORPUS=1 uv run pytest \
  tests/integration/test_processing_postgres.py::test_saved_six_source_corpus_end_to_end -s
```

The temporary verification containers are removed after testing. The original PostgreSQL 17
development instance and collected raw files are preserved. The existing Docker image remains
available locally as `jobtology-ingestion:verification`.

## Limits

This verifies pipeline behavior with the captured provider contracts, not today's live provider
availability, actual provider quota balances, or the main server's Coolify/network configuration.
It does not establish CS/AI/student eligibility coverage or validate final grounded claims and
serving-corpus publication, which remain later implementation stages.
