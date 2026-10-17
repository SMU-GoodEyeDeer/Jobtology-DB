#!/usr/bin/env python3
"""Plan/apply the bounded JobKorea public runtime package; execute no SQL or jobs.

Both commands hold the existing scheduler lock. Apply streams a full PostgreSQL
backup, replaces only fixed public files, and verifies legacy-data fingerprints.
The native source and linking installers are separate operator actions.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import reconcile_runtime as common

ROOT = common.ROOT
STATE = common.STATE
PROJECT = common.PROJECT
ALLOWLIST = (
    # Focused flat ontology writers, verification and safe compatibility installers.
    "ontology/sql/000_retention_dependency.sql",
    "ontology/sql/001_observation_sources.sql",
    "ontology/sql/004_graph_inventory.sql",
    "ontology/sql/009_refresh_observation_hook.sql",
    "ontology/sql/019_catalog_approval.sql",
    "ontology/sql/020_catalog_source_graph.sql",
    "ontology/sql/024_sealed_catalog.sql",
    "ontology/sql/catalog_reader_grants.psql",
    "ontology/sql/028_flat_graph_projection.sql",
    "ontology/sql/028_product_role_demand_base.sql",
    "ontology/sql/029_flat_catalog_compatibility.sql",
    "ontology/sql/030_live_ncs_unit.sql",
    "ontology/install.hwf",
    "ontology/install_flat_graph.hwf",
    "ontology/load_release.hwf",
    "ontology/stage_flat_release.hwf",
    "ontology/finalize_flat_release.hwf",
    "ontology/graph_constraint.hpl",
    "ontology/graph_edges.hpl",
    "ontology/graph_fail.hpl",
    "ontology/graph_finish.hpl",
    "ontology/graph_nodes.hpl",
    "ontology/graph_resume.hpl",
    "ontology/graph_root.hpl",
    "ontology/graph_stage.hpl",
    "ontology/graph_start.hpl",
    "ontology/graph_verify_edges.hpl",
    "ontology/graph_verify_legacy_edges.hpl",
    "ontology/graph_verify_legacy_nodes.hpl",
    "ontology/graph_verify_nodes.hpl",
    "ontology/write_edge_arrays.hpl",
    "ontology/write_edge_scalars.hpl",
    "ontology/write_node_arrays.hpl",
    "ontology/write_node_scalars.hpl",
    "ontology/verify_claims.hpl",
    "ontology/verify_edge_arrays.hpl",
    "ontology/verify_edge_scalars.hpl",
    "ontology/verify_legacy_edge_arrays.hpl",
    "ontology/verify_legacy_edge_scalars.hpl",
    "ontology/verify_legacy_node_arrays.hpl",
    "ontology/verify_legacy_node_scalars.hpl",
    "ontology/verify_node_arrays.hpl",
    "ontology/verify_node_scalars.hpl",
    # Permanent batch-free writers and compatibility entry points. The migration
    # coordinator installs their additive SQL while holding the same host lock.
    "graph/sql/002_batchfree_source_graph.sql",
    "graph/sql/003_source_query_sharing.sql",
    "graph/sql/004_verified_proof_replay.sql",
    "graph/install.hwf",
    "graph/migrate_source_graph.hwf",
    "graph/begin_batch.hpl",
    "graph/finish_batch.hpl",
    "graph/mark_failed.hpl",
    "graph/constraints.hpl",
    "graph/upgrade_labels.hpl",
    "graph/load_entity_names.hpl",
    "graph/verify_entity_names.hpl",
    "graph/load_records.hpl",
    "graph/verify_records.hpl",
    "graph/load_references.hpl",
    "graph/verify_references.hpl",
    "graph/verify_totals.hpl",
    "graph/clear_source_edges.hpl",
    "llm/sql/036_batchfree_graph_publication.sql",
    "retention/sql/002_batchfree_retention.sql",
    "retention/verify_source_projections.hpl",
    "retention/archive_nodes.hpl",
    "retention/archive_references.hpl",
    "retention/delete_graph.hpl",
    "retention/delete_files.hpl",
    "retention/enter_graph_writer.hpl",
    "retention/execute.hwf",
    "retention/graph_constraints.hpl",
    "retention/graph_target.hpl",
    "retention/verify_archive.hpl",
    "retention/verify_deleted_graph.hpl",
    "graph/sql/001_posting_ingestion_dates.sql",
    "graph/load_posting_dates.hpl",
    "graph/verify_posting_dates.hpl",
    "graph/update_posting_dates.hwf",
    "graph/install_posting_dates.hwf",
    "graph/load_snapshot.hwf",
    *(
        f"ingestions/jobkorea/sql/{name}.sql"
        for name in (
            "001_schema",
            "002_operations",
            "003_checks",
            "004_integration",
            "005_shared_checks",
            "006_ndjson",
            "007_dataset_provenance",
            "008_ready_statistics",
        )
    ),
    "llm/sql/003_planning.sql",
    "llm/sql/004_validation.sql",
    "llm/sql/005_review_eval.sql",
    "llm/sql/017_input_bundles.sql",
    "llm/sql/021_link_publication.sql",
    "llm/sql/027_jobkorea_inputs.sql",
    "llm/sql/028_jobkorea_linking.sql",
    "llm/sql/029_metadata_occupation_links.sql",
    "llm/sql/030_metadata_occupation_native.sql",
    "llm/sql/031_metadata_occupation_workers.sql",
    "llm/sql/032_metadata_occupation_context.sql",
    "llm/sql/033_metadata_occupation_roles.sql",
    "llm/sql/034_metadata_occupation_pm.sql",
    "llm/sql/035_metadata_occupation_terminal_status.sql",
    "llm/sql/037_metadata_occupation_multimatch.sql",
    "llm/prompts/categorize-ko-metadata-occupation-v1.txt",
    "llm/prompts/categorize-ko-metadata-occupation-v1.schema.json",
    "llm/prompts/categorize-ko-metadata-occupation-v2.txt",
    "llm/prompts/categorize-ko-metadata-occupation-v2.schema.json",
    "llm/prompts/categorize-ko-metadata-occupation-v3.txt",
    "llm/prompts/categorize-ko-metadata-occupation-v3.schema.json",
    # Keep future canonical installer replay safe; neither is replayed here.
    "cs/sql/001_common_postings.sql",
    "retention/sql/000_operations.sql",
    "retention/install.hwf",
    "metadata/pipeline-run-configuration/jobkorea-local.json",
    "metadata/workflow-run-configuration/jobkorea-local.json",
    "ingestions/jobkorea/import_local.hpl",
    "ingestions/jobkorea/preview_linking_scope.hpl",
    "ingestions/jobkorea/preview_linking_requests.hpl",
    "ingestions/jobkorea/prepare_linking_pilot.hpl",
    "ingestions/jobkorea/full.hwf",
    "ingestions/jobkorea/preview_linking.hwf",
    "ingestions/jobkorea/prepare_linking.hwf",
    "ingestions/jobkorea/prepare_inferred_occupations.hpl",
    "ingestions/jobkorea/run_inferred_occupations.hpl",
    "ingestions/jobkorea/request_inferred_occupation.hpl",
    "ingestions/jobkorea/finish_inferred_occupations.hpl",
    "ingestions/jobkorea/execute_inferred_occupations.hwf",
    "ingestions/jobkorea/execute_inferred_occupation_workers.hwf",
    "ingestions/jobkorea/start_inferred_occupation_execution.hpl",
    "ingestions/jobkorea/run_inferred_occupation_workers.hpl",
    "ingestions/jobkorea/request_inferred_occupation_worker.hpl",
    "ingestions/jobkorea/end_inferred_occupation_execution.hpl",
    "ingestions/jobkorea/acquire_inferred_occupation_graph.hpl",
    "ingestions/jobkorea/begin_inferred_occupation_graph.hpl",
    "ingestions/jobkorea/load_inferred_occupation_graph.hpl",
    "ingestions/jobkorea/verify_inferred_occupation_graph.hpl",
    "ingestions/jobkorea/finish_inferred_occupation_graph.hpl",
    "ingestions/jobkorea/fail_inferred_occupation_graph.hpl",
    "ingestions/jobkorea/publish_inferred_occupations.hwf",
    # Installers follow all of their dependencies.
    "ingestions/jobkorea/install.hwf",
    "ingestions/jobkorea/install_linking.hwf",
    "ingestions/jobkorea/install_batchfree_graph_publication.hwf",
    "ingestions/jobkorea/install_inferred_occupations.hwf",
    "ingestions/jobkorea/install_inferred_occupation_workers.hwf",
    "llm/install.hwf",
)
ENTRYPOINTS = (
    "ontology/install.hwf",
    "ontology/install_flat_graph.hwf",
    "ontology/load_release.hwf",
    "ontology/stage_flat_release.hwf",
    "ontology/finalize_flat_release.hwf",
    "graph/install.hwf",
    "graph/migrate_source_graph.hwf",
    "graph/load_snapshot.hwf",
    "retention/execute.hwf",
    "retention/install.hwf",
    "graph/install_posting_dates.hwf",
    "graph/update_posting_dates.hwf",
    "ingestions/jobkorea/full.hwf",
    "ingestions/jobkorea/preview_linking.hwf",
    "ingestions/jobkorea/prepare_linking.hwf",
    "ingestions/jobkorea/install.hwf",
    "ingestions/jobkorea/install_linking.hwf",
    "ingestions/jobkorea/install_batchfree_graph_publication.hwf",
    "ingestions/jobkorea/install_inferred_occupations.hwf",
    "ingestions/jobkorea/install_inferred_occupation_workers.hwf",
    "ingestions/jobkorea/execute_inferred_occupations.hwf",
    "ingestions/jobkorea/execute_inferred_occupation_workers.hwf",
    "ingestions/jobkorea/publish_inferred_occupations.hwf",
    "llm/install.hwf",
)
PUBLIC_PATH = re.compile(
    r"(?:ingestions/jobkorea|llm|graph|operations|retention|ontology)/"
    r"[A-Za-z0-9_./-]+\.(?:hpl|hwf|sql)"
)


def dependencies() -> tuple[str, ...]:
    """Resolve public native references and reject traversal/private paths."""
    pending: list[str] = list(ENTRYPOINTS)
    seen: set[str] = set()
    while pending:
        relative = pending.pop()
        if relative in seen:
            continue
        if not PUBLIC_PATH.fullmatch(relative) or ".." in Path(relative).parts:
            raise RuntimeError("Unexpected native runtime dependency")
        path = ROOT / relative
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"Missing public runtime dependency: {relative}")
        seen.add(relative)
        if path.suffix not in (".hpl", ".hwf"):
            continue
        for element in ET.fromstring(path.read_bytes()).iter():
            if element.tag not in ("filename", "sqlfilename"):
                continue
            value = element.text or ""
            if value.startswith("${PROJECT_HOME}/"):
                pending.append(value.removeprefix("${PROJECT_HOME}/"))
    return tuple(sorted(seen))


def remote_bytes(hop: str, relative: str) -> bytes | None:
    if relative not in ALLOWLIST and relative not in dependencies():
        raise RuntimeError("Artifact is outside the JobKorea runtime package")
    script = b"""set -eu
path="$1"; project="$2"; current="$path"
while :; do
 test ! -L "$current" || exit 1
 test "$current" != "$project" || break
 current=$(dirname "$current")
done
if test -e "$path"; then
 test -f "$path" || exit 1
 printf 'PRESENT\\n'; cat "$path"
else
 printf 'ABSENT\\n'
fi
"""
    output = common.command(
        ["docker", "exec", "-i", hop, "sh", "-s", "--", f"{PROJECT}/{relative}", PROJECT],
        data=script,
    )
    marker, data = output.split(b"\n", 1)
    if marker == b"ABSENT":
        return None
    if marker != b"PRESENT":
        raise RuntimeError("Unrecognized runtime artifact response")
    return data


def snapshot(runtime: dict[str, str]) -> tuple[dict[str, Any], dict[str, bytes | None]]:
    entries: dict[str, Any] = {}
    previous: dict[str, bytes | None] = {}
    for relative in dict.fromkeys((*dependencies(), *ALLOWLIST)):
        desired = (ROOT / relative).read_bytes()
        old = remote_bytes(runtime["hop"], relative)
        before = None if old is None else common.digest(old)
        after = common.digest(desired)
        if relative not in ALLOWLIST and before != after:
            raise RuntimeError(f"Unexpected unchanged dependency drift: {relative}")
        entries[relative] = {"before": before, "after": after, "change": before != after}
        previous[relative] = old
    return entries, previous


def sql(pg: str, query: str) -> str:
    return (
        common.command(
            [
                "docker",
                "exec",
                "-i",
                pg,
                "psql",
                "-X",
                "-qAt",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "postgres",
                "-d",
                "jobtology",
            ],
            data=query.encode(),
        )
        .decode()
        .strip()
    )


def preservation_state(pg: str) -> dict[str, Any]:
    """Preserve the legacy baseline used around additive local ingestion.

    JobKorea source rows/input bundles and the added document transport column
    remain excluded here because the local load supervisor relies on that scope.
    File deployment uses full_preservation_state instead.
    """
    names = json.loads(
        sql(
            pg,
            """BEGIN READ ONLY;
SELECT jsonb_agg(n.nspname||'.'||c.relname ORDER BY n.nspname,c.relname)
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE c.relkind='r' AND n.nspname IN('enrichment','catalog');
COMMIT;""",
        )
    )
    protected = {
        "ingestion.run": "WHERE x.source_id<>'jobkorea'",
        "ingestion.dependency": "JOIN ingestion.run r USING(run_id) WHERE r.source_id<>'jobkorea'",
        "ingestion.partition": "JOIN ingestion.run r USING(run_id) WHERE r.source_id<>'jobkorea'",
        "ingestion.document": "JOIN ingestion.run r USING(run_id) WHERE r.source_id<>'jobkorea'",
        "ingestion.record": "JOIN ingestion.run r USING(run_id) WHERE r.source_id<>'jobkorea'",
        "ingestion.rejected_row": (
            "JOIN ingestion.run r USING(run_id) WHERE r.source_id<>'jobkorea'"
        ),
        "ingestion.request_attempt": "",
        "ingestion.graph_export": (
            "JOIN ingestion.run r USING(run_id) WHERE r.source_id<>'jobkorea'"
        ),
        "ingestion.refresh_policy": "",
        "ingestion.refresh_execution": "",
        "ontology.active_release": "",
        "ontology.activation_event": "",
        "cs.posting_input": "",
        "cs.source_snapshot": "",
    }
    for name in names:
        if not re.fullmatch(r"(?:enrichment|catalog)\.[a-z][a-z_0-9]*", name):
            raise RuntimeError("Unexpected protected relation")
        protected[name] = (
            "JOIN ingestion.run r ON r.run_id=x.job_run_id WHERE r.source_id<>'jobkorea'"
            if name == "enrichment.input_bundle"
            else ""
        )
    clauses: list[str] = []
    for name, condition in protected.items():
        row = "to_jsonb(x)-'transport'" if name == "ingestion.document" else "to_jsonb(x)"
        clauses.append(
            f"SELECT '{name}' AS name,count(*) AS count,"
            f"md5(coalesce(string_agg(row_hash,'' ORDER BY row_hash),'')) AS digest "
            f"FROM (SELECT md5(({row})::text) AS row_hash FROM {name} x {condition}) hashes"
        )
    result = sql(
        pg,
        "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\n"
        "SET LOCAL statement_timeout='180s';\n"
        "SELECT jsonb_object_agg(name,jsonb_build_object('count',count,'digest',digest)) "
        "FROM (" + " UNION ALL ".join(clauses) + ") fingerprints;\nCOMMIT;",
    )
    return json.loads(result)


def full_preservation_state(pg: str) -> dict[str, Any]:
    """Fingerprint every application table for the file-only deployment.

    This includes the loaded JobKorea snapshot, its frozen inputs and any new
    inference tables already present. No SQL or paid work runs in this helper;
    every captured row must remain identical during public-file installation.
    Only counts and digests are returned, never source values or credentials.
    """
    names = json.loads(
        sql(
            pg,
            """BEGIN READ ONLY;
SELECT jsonb_agg(n.nspname||'.'||c.relname ORDER BY n.nspname,c.relname)
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE c.relkind IN('r','p')
AND n.nspname IN('attachment','catalog','cs','enrichment','ingestion','ontology','retention');
COMMIT;""",
        )
    )
    clauses: list[str] = []
    for name in names:
        if not re.fullmatch(
            r"(?:attachment|catalog|cs|enrichment|ingestion|ontology|retention)\.[a-z][a-z_0-9]*",
            name,
        ):
            raise RuntimeError("Unexpected protected relation")
        clauses.append(
            f"SELECT '{name}' AS name,count(*) AS count,"
            f"md5(coalesce(string_agg(row_hash,'' ORDER BY row_hash),'')) AS digest "
            f"FROM (SELECT md5(to_jsonb(x)::text) AS row_hash FROM {name} x) hashes"
        )
    result = sql(
        pg,
        "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\n"
        "SET LOCAL statement_timeout='180s';\n"
        "SELECT jsonb_object_agg(name,jsonb_build_object('count',count,'digest',digest)) "
        "FROM (" + " UNION ALL ".join(clauses) + ") fingerprints;\nCOMMIT;",
    )
    return json.loads(result)


def backup_database(pg: str, directory: Path) -> dict[str, Any]:
    path = directory / "database-before.dump"
    with path.open("xb") as output:
        result = subprocess.run(
            [
                "docker",
                "exec",
                pg,
                "pg_dump",
                "-U",
                "postgres",
                "-d",
                "jobtology",
                "--format=custom",
            ],
            stdout=output,
            stderr=subprocess.PIPE,
            check=False,
        )
    path.chmod(0o600)
    if result.returncode or path.stat().st_size == 0:
        raise RuntimeError("PostgreSQL backup failed")
    with path.open("rb") as source:
        result = subprocess.run(
            ["docker", "exec", "-i", pg, "pg_restore", "--list"],
            stdin=source,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
    if result.returncode:
        raise RuntimeError("PostgreSQL backup validation failed")
    with path.open("rb") as source:
        sha256 = hashlib.file_digest(source, "sha256").hexdigest()
    return {
        "path": str(path),
        "byte_length": path.stat().st_size,
        "sha256": sha256,
        "format": "POSTGRES_CUSTOM_FULL",
        "listing_validated": True,
    }


def ensure_parent(hop: str, relative: str) -> None:
    """Create only missing public parents, preserving all existing permissions."""
    script = b"""set -eu
project="$1"; relative="$2"; current="$project"
test -d "$project"; test ! -L "$project"
old_ifs="$IFS"; IFS=/
for part in $relative; do
 current="$current/$part"
 test ! -L "$current"
 if test -e "$current"; then test -d "$current"; else
  mkdir "$current"; chown 501:501 "$current"; chmod 755 "$current"
 fi
done
IFS="$old_ifs"
"""
    common.command(
        [
            "docker",
            "exec",
            "-u",
            "root",
            "-i",
            hop,
            "sh",
            "-s",
            "--",
            PROJECT,
            str(Path(relative).parent),
        ],
        data=script,
    )


def plan_manifest(
    runtime: dict[str, str], state: dict[str, Any], entries: dict[str, Any]
) -> dict[str, Any]:
    """Keep the version-1 loader baseline while adding stricter file-only proof."""
    return {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "containers": runtime,
        "catalog_context": state["catalog_context"],
        "db_state": state,
        "artifacts": entries,
        "preservation_state": preservation_state(runtime["pg"]),
        "full_preservation_state": full_preservation_state(runtime["pg"]),
    }


def apply(manifest_path: Path, runtime: dict[str, str], state: dict[str, Any]) -> Path:
    manifest = json.loads(manifest_path.read_bytes())
    if manifest.get("version") != 1 or manifest.get("containers") != runtime:
        raise RuntimeError("Manifest version or runtime identity changed")
    if manifest.get("catalog_context") != state["catalog_context"]:
        raise RuntimeError("Approved catalogue changed since planning")
    entries, previous = snapshot(runtime)
    common.assert_same_plan(manifest.get("artifacts"), entries)
    legacy_before = preservation_state(runtime["pg"])
    before = full_preservation_state(runtime["pg"])
    if legacy_before != manifest.get("preservation_state"):
        raise RuntimeError("Protected data changed since planning; produce a new plan")
    if before != manifest.get("full_preservation_state"):
        raise RuntimeError("Full file-deployment baseline changed or absent; produce a new plan")
    directory = STATE / ("jobkorea-runtime-applied-" + uuid.uuid4().hex)
    directory.mkdir(mode=0o700)
    receipt_path = directory / "receipt.json"
    receipt: dict[str, Any] = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "manifest": str(manifest_path.resolve()),
        "containers": runtime,
        "artifacts": entries,
        "preservation_state": legacy_before,
        "full_preservation_state": before,
        "catalog_context": state["catalog_context"],
        "installed": [],
        "status": "BACKING_UP",
        "executed_sql": False,
        "executed_jobs": False,
    }
    common.write_json(receipt_path, receipt)
    staged: dict[str, str] = {}
    try:
        changed = [p for p in ALLOWLIST if entries[p]["change"]]
        for relative in changed:
            old_bytes = previous[relative]
            if old_bytes is not None:
                backup = directory / "before" / relative
                backup.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                backup.write_bytes(old_bytes)
                backup.chmod(0o600)
        receipt["database_backup"] = backup_database(runtime["pg"], directory)
        common.write_json(receipt_path, receipt)
        common.idle_cli(runtime["hop"])
        common.db_state(runtime["pg"])
        common.assert_same_plan(entries, snapshot(runtime)[0])
        token = uuid.uuid4().hex
        receipt["status"] = "INSTALLING"
        for relative in changed:
            receipt["current_artifact"] = relative
            common.write_json(receipt_path, receipt)
            ensure_parent(runtime["hop"], relative)
            temporary = f"{PROJECT}/{relative}.jobkorea-deploy-{token}"
            staged[relative] = temporary
            common.command(["docker", "cp", str(ROOT / relative), runtime["hop"] + ":" + temporary])
            for tool, argument in (("chown", "501:501"), ("chmod", "644")):
                common.command(
                    ["docker", "exec", "-u", "root", runtime["hop"], tool, argument, temporary]
                )
            actual = (
                common.command(["docker", "exec", runtime["hop"], "sha256sum", temporary])
                .decode()
                .split()[0]
            )
            if actual != entries[relative]["after"]:
                raise RuntimeError("Staged artifact hash mismatch")
            if remote_bytes(runtime["hop"], relative) != previous[relative]:
                raise RuntimeError("Runtime artifact changed during deployment")
            common.command(
                [
                    "docker",
                    "exec",
                    "-u",
                    "root",
                    runtime["hop"],
                    "mv",
                    "--",
                    temporary,
                    f"{PROJECT}/{relative}",
                ]
            )
            del staged[relative]
            receipt["installed"].append(relative)
            common.write_json(receipt_path, receipt)
        if any(e["before"] != e["after"] for e in snapshot(runtime)[0].values()):
            raise RuntimeError("Deployed artifact verification failed")
        final_state = common.db_state(runtime["pg"])
        if final_state["catalog_context"] != state["catalog_context"]:
            raise RuntimeError("Approved catalogue changed during deployment")
        if full_preservation_state(runtime["pg"]) != before:
            raise RuntimeError("Protected data changed during deployment")
        receipt["status"] = "VERIFIED"
        receipt["db_state"] = final_state
    except BaseException as error:
        receipt["status"] = "FAILED_REVIEW_RECEIPT_BEFORE_RETRY"
        receipt["failure"] = {
            "artifact": receipt.get("current_artifact"),
            "error_type": type(error).__name__,
        }
        raise RuntimeError(
            f"Deployment stopped; inspect protected receipt {receipt_path}"
        ) from error
    finally:
        for temporary in staged.values():
            try:
                common.command(
                    ["docker", "exec", "-u", "root", runtime["hop"], "rm", "-f", "--", temporary]
                )
            except RuntimeError:
                receipt.setdefault("cleanup_pending", []).append(temporary)
        receipt["finished_at"] = datetime.now(UTC).isoformat()
        common.write_json(receipt_path, receipt)
    return receipt_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "apply"))
    parser.add_argument("manifest", nargs="?", type=Path)
    args = parser.parse_args()
    if (args.mode == "apply") != (args.manifest is not None):
        parser.error("apply requires a manifest; plan does not accept one")
    os.umask(0o077)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE / "refresh.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Scheduler lock is busy") from None
        runtime = common.containers()
        common.idle_cli(runtime["hop"])
        state = common.db_state(runtime["pg"])
        if args.mode == "plan":
            entries, _ = snapshot(runtime)
            directory = STATE / ("jobkorea-runtime-plan-" + uuid.uuid4().hex)
            directory.mkdir(mode=0o700)
            path = directory / "manifest.json"
            common.write_json(
                path,
                plan_manifest(runtime, state, entries),
            )
            print(path)
            count = sum(e["change"] for e in entries.values())
            print(f"{count} changed public files; no runtime writes")
        else:
            print(apply(args.manifest, runtime, state))


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
