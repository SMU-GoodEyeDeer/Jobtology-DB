#!/usr/bin/env bash
# Host-side scheduler adapter. All source processing and graph loading run in Hop.
# Requires Docker access, flock, PostgreSQL's psql inside its container, and Python
# only for output redaction (never for ETL). Install with a protected runtime.env.
set -euo pipefail
umask 077
config=${JOBTOLOGY_HOP_RUNTIME:-"$HOME/.config/jobtology-hop/runtime.env"}
[[ -r "$config" ]] || { echo "Missing runtime configuration: $config" >&2; exit 1; }
source "$config"
mkdir -p "$STATE_DIR"
exec 9>"$STATE_DIR/refresh.lock"
flock -n 9 || exit 0
hop_id=$(docker ps --filter "volume=$HOP_CONFIG_VOLUME" --format '{{.ID}}')
pg_id=$(docker ps --filter "name=$PG_CONTAINER_NAME" --format '{{.ID}}')
[[ "$hop_id" =~ ^[0-9a-f]{12}$ && "$pg_id" =~ ^[0-9a-f]{12}$ ]] || { echo 'Expected one running Hop and PostgreSQL container.' >&2; exit 1; }
sql() { docker exec -i "$pg_id" psql -X -qAt -U "$PG_USER" -d "$PG_DATABASE" --set=ON_ERROR_STOP=1; }
# Check the actual persistent volume before each source. No automatic raw deletion.
space_ok() {
 local available used
 read -r available used < <(docker exec "$hop_id" df -Pk "$PROJECT_HOME/data" | awk 'NR==2 {gsub(/%/,"",$5);print $4,$5}')
 [[ "$available" =~ ^[0-9]+$ && "$used" =~ ^[0-9]+$ ]] &&
 ((available >= MIN_FREE_KIB && used < MAX_USED_PERCENT))
}
overall=0
for source_id in alio_organization job_alio ncs_competency ncs_qualification qnet_schedule ncs_career_path; do
 row=$(sql <<< "SELECT operation||'|'||coalesce(run_id,'') FROM ingestion.refresh_queue WHERE source_id='$source_id';")
 [[ -n "$row" ]] || continue
 space_ok || { echo 'Refresh stopped: raw-volume reserve or usage limit reached.' >&2; exit 1; }
 IFS='|' read -r operation run_id <<< "$row"
 [[ "$operation" == FETCH || "$operation" == GRAPH ]] || exit 1
 execution_id=$(sql <<< "INSERT INTO ingestion.refresh_execution(source_id,operation) VALUES ('$source_id','$operation') RETURNING execution_id;")
 [[ "$execution_id" =~ ^[0-9]+$ ]] || exit 1
 if [[ "$operation" == FETCH ]]; then
  workflow="$PROJECT_HOME/operations/refresh_$source_id.hwf"; parameters='MODE=FULL'
 else
  [[ "$run_id" =~ ^[0-9a-f-]{36}$ ]] || exit 1
  workflow="$PROJECT_HOME/operations/export_pending.hwf"; parameters="RUN_ID=$run_id"
 fi
 log_path="$STATE_DIR/$(date -u +%Y%m%dT%H%M%SZ)-$source_id-$operation.log"
 echo "Starting $source_id $operation; log: $log_path"
 # The redactor reads the protected key in memory. Raw and URL-encoded forms are
 # removed before anything is written to a log. Never enable Detailed/Rowlevel.
 set +e
 python3 "$REDACTOR" "$hop_id" "$HOP_ROOT" "$API_KEY_FILE" "$workflow" "$parameters" "$log_path"
 code=$?
 set -e
 sql <<< "UPDATE ingestion.refresh_execution SET finished_at=clock_timestamp(),exit_code=$code WHERE execution_id=$execution_id;"
 ((code == 0)) || overall=1
done
exit "$overall"
