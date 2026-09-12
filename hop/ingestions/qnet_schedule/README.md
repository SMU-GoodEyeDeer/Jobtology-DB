# Q-Net exam schedules

Run `full.hwf` with `reference-local` and Basic logging. It pins one accepted
qualification-mapping snapshot, selects distinct four-character qualification
codes, and fetches every code for the current and next calendar year in Asia/Seoul.
Qualification codes retain leading zeroes. Empty code/year partitions need two
successful confirmations; they are not silently omitted.

Install `schema.sql`, `reference-support.sql`, `checks.sql` and `operations.sql`
from `docs/hop-migration` first. Connections and API key handling are the same as
[qualification ingestion](../ncs_qualification/README.md).

| Parameter | Default | Meaning |
|---|---|---|
| `MODE` | `FULL` | `SMOKE` fetches one partition's first page; never READY. |
| `INPUT_RUN_ID` | blank | Latest READY qualification snapshot, or an exact accepted run. |
| `YEAR_FROM` / `YEAR_TO` | current / next year | For historical replay, specify two consecutive years. |
| `MAX_PAGES` | `1000` | Total requests for this run, also limited by rolling quota. |
| `RAW_ROOT` | `${PROJECT_HOME}/data/qnet_schedule-raw` | Persistent original responses. |
| `API_KEY_FILE` | `${HOP_CONFIG_FOLDER}/secrets/data-go-kr.csv` | Protected one-key CSV. |

Each run is a complete snapshot of its code/year scope. A changed date in a later
run creates a new historical representation of the same exam-session identity
(`qualification:year:category:round`). Repeating a refresh does not create duplicate
identities within that snapshot. Dates must be valid calendar dates and registration
or examination ranges cannot run backwards. Missing dates stay null.

Read `ingestion.exam_session` by `run_id`, or join it to
`ingestion.latest_ready_run` for the current snapshot. PostgreSQL keeps older runs;
Neo4j keeps their batch membership and source facts.

Use `operations/refresh_qnet_schedule.hwf` for ingestion followed by Neo4j loading.
The scheduler refreshes Q-Net every 24 hours. See [operations](../../operations/README.md).
