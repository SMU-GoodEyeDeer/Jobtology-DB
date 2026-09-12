# NCS qualification mappings

Run `full.hwf` with `reference-local` and Basic logging. It pins one accepted NCS
competency snapshot, selects all versioned units in the eleven occupations listed
in `ingestion.qualification_scope`, and fetches every page for every unit. An empty
partition needs two successful confirmations. No source code list is typed into Hop.

Install `schema.sql`, `reference-support.sql`, `checks.sql` and `operations.sql`
from `docs/hop-migration` first. Use the private `jobtology-postgres` metadata
connection and the existing protected `${HOP_CONFIG_FOLDER}/secrets/data-go-kr.csv`.

| Parameter | Default | Meaning |
|---|---|---|
| `MODE` | `FULL` | `SMOKE` fetches one partition's first page and stays outside READY data. |
| `INPUT_RUN_ID` | blank | Pin latest READY NCS snapshot, or supply an exact accepted run. |
| `MAX_PAGES` | `1000` | Total request cap for this run, also limited by rolling source quota. |
| `RAW_ROOT` | `${PROJECT_HOME}/data/ncs_qualification-raw` | Persistent original response files. |
| `API_KEY_FILE` | protected CSV above | Exactly one decoded key under `service_key`. |

The source identity includes the full competency code, qualification code **and
standard version**. Hours and unit type remain facts of that particular mapping.
`ingestion.qualification_mapping` exposes accepted snapshots; filter by `run_id`.
The `dependency` table records the input NCS snapshot.

For ingestion followed by Neo4j loading, use
`operations/refresh_ncs_qualification.hwf`. The scheduler normally refreshes this
source every seven days. See [operations](../../operations/README.md).
