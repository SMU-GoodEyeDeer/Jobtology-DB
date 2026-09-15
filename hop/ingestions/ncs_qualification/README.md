# NCS qualification mappings

Run `full.hwf` with `reference-local` and Basic logging. It pins one accepted NCS
competency snapshot, pins the enabled occupation codes from
`ingestion.active_qualification_scope` into that run, and fetches every versioned
unit in those occupations. The original 11 occupations stay enabled. The current
accepted CS role-link audit adds 11 category-20 occupations; unlinked candidates
stay disabled. Earlier accepted runs keep their original partition scope. An
empty partition needs two successful confirmations.

Install `schema.sql`, `reference-support.sql`, `checks.sql` and `operations.sql`
from `docs/hop-migration`, then install
[`cs/sql/006_qualification_support.sql`](../../cs/sql/006_qualification_support.sql)
through `cs/install.hwf` after the prerequisite CS/LLM SQL. Use the private `jobtology-postgres` metadata
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

To extend the next run, enable only audited NCS occupation codes in
`ingestion.qualification_occupation_policy` for policy `cs-it-ai-data-v1`. Check
that they exist in the chosen NCS snapshot before running. `MAX_PAGES` must cover
the expected units, and the workflow still obeys the reference API quota. The run
stores the exact selected codes in `settings.qualification_scope_codes`; changing
the policy later does not reinterpret that run.

`ingestion.related_qualification_report(links, qualification_run_id, qnet_run_id)`
accepts a JSON array of reviewed links with `source_id`, `source_posting_id`,
`position_id`, `link_id` and `ncs_unit_code`. It keeps providers with the same
native posting ID separate. The report distinguishes an unfetched unit, a fetched
unit with no mapping, an unresolved code and a mapped credential with or without
loaded Q-Net sessions. `RELATED_VIA_NCS` denotes a related credential, not an
employer requirement. Refresh Q-Net after an expanded qualification run to fetch
newly mapped credential schedules.

The source-qualified `cs.current_role_qualification` and
`cs.current_role_qualification_summary` views project this report over current
accepted, IN_SCOPE CS role links. Preview them through `cs/read_qualification.hwf`
and `cs/read_qualification_summary.hwf`; those readers use the latest READY
qualification/Q-Net pair and make no provider requests.

For ingestion followed by Neo4j loading, use
`operations/refresh_ncs_qualification.hwf`. The scheduler normally refreshes this
source every seven days. See [operations](../../operations/README.md).
