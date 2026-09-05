# Collection status and data structure

Snapshot: **2026-09-06 KST**

The fetching milestone is complete for the six usable official sources. Responses are preserved in
the immutable raw store and indexed in the PostgreSQL fetch ledger. These runs correctly remain at
`state=RUNNING, stage=FETCHED`: parsing, schema matching, grounding, release publication, and the
Neo4j load have not been implemented yet.

## Selected collection runs

| Source | Selected run | Result | Collected scope |
| --- | --- | ---: | --- |
| NCS career path | `c19960d8-71b6-45d9-a282-8085bb9f05a0` | 1/1 requests | 12,864 unique rows covering 1,072 job codes |
| NCS competency | `de3d746a-4b2f-43ae-95d3-ea0bf0d30c2e` | 16/16 requests | 15,520 rows; 15,520 unique `ncsClCd` values |
| NCS qualification | `f506c795-fcba-4109-b6e0-54d4f38b4e14` | 237/237 requests | 87 rows, 85 unique NCS/qualification pairs, 31 item codes |
| Q-Net schedule | `1095603e-8120-41a7-afdb-f46c27ac9504` | 104/104 requests | 56 schedule rows for 31 item codes across 2026–2027 |
| ALIO organizations | `7af03ee3-a191-4a0b-8b85-06223e0fa548` | 4/4 requests | 355 public institutions |
| JOB-ALIO postings | `35dfb121-83c9-417d-8e54-fbd66eb6c563` | 516/516 requests | 510 active postings: 6 list pages plus every detail |

The result column reports successful ledger requests, not source-record counts. Empty NCS and Q-Net
partitions were deliberately fetched twice, which explains the higher request totals. The ledger
contains 584 source-scoped snapshots deduplicated into 583 physical objects (17,060,633 bytes),
including selected runs, smoke tests, retries, and rejected diagnostics. Saramin remains pending on
API approval. Work24 is outside the MVP because the required API access is not available to this
school-project account.

## Current structure

```text
Official APIs / NCS file
  -> source connector and deterministic request plan
  -> raw/sha256/<aa>/<bb>/<full-sha256>       immutable response bytes
  -> PostgreSQL control + raw_manifest        runs, requests, observations, snapshots
  -> generated partition configuration        139 NCS codes -> 31 Q-Net codes
  -> [next] parse -> normalize -> ground -> validate -> publish -> Neo4j
```

The PostgreSQL ledger currently consists of:

- `control.connector_run`: run identity, source policy, mode, state, and stage.
- `control.connector_request`: deterministic planned requests and their progress.
- `raw_manifest.fetch_observation`: every HTTP attempt and response metadata.
- `raw_manifest.source_snapshot`: the selected immutable raw object for a logical request.

The dependent collection chain is:

```text
NCS competency snapshot
  -> config/ncs_qualification_codes.txt (139)
  -> NCS-to-qualification snapshot
  -> config/qnet_item_codes.txt (31)
  -> Q-Net schedules (2026–2027)
```

Derivation fails closed if a full snapshot has missing pages, mismatched manifests, corrupt raw
objects, or duplicate NCS IDs. An earlier NCS run exposed unstable provider page ordering and was
rejected; no pages from different runs were combined. In the future normalized model,
`(ncsClCd, jmCd, organStdVerCd)` must identify an NCS-to-qualification mapping because
`(ncsClCd, jmCd)` is not unique in the live data. Q-Net records must also retain their request
partition because some responses omit the qualification identity.

## Deployment and remaining work

- The current PostgreSQL 17 instance and local raw directory are development fixtures only.
  Production PostgreSQL 18 will be managed inside the Coolify stack; Neo4j and operator tools stay
  private/Tailscale-gated while the separate frontend remains publicly exposed through its domain.
- There is no batch scheduler or cron job yet. Coolify Scheduled Tasks will be added after parsing
  and idempotent publication exist.
- The next implementation milestone is deterministic parsers and normalized staging records,
  followed by schema matching/grounding, quality gates, versioned releases, and the Neo4j loader.
