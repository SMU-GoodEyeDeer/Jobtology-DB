#!/usr/bin/env python3
"""Plan/apply the October 2026 runtime artifact reconciliation; never run migrations.

Run `python3 hop/operations/reconcile_runtime.py plan`, review its protected JSON
manifest, then `python3 hop/operations/reconcile_runtime.py apply MANIFEST`.
Both commands use the scheduler's host lock. Only the fixed public artifact list
and its host adapter may change; private metadata and data are never copied.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE = Path.home() / ".local/state/jobtology-hop"
ADAPTER = Path.home() / ".local/bin/jobtology-hop-refresh"
VOLUME = "ibbwv593fijblilse127wnqd-hop-config"
PG_NAME = "j89dw8prq97uiec629avd6w5"
PROJECT = "/usr/local/tomcat/webapps/ROOT/config/projects/default"
ALLOWLIST = (
    "ontology/sql/019_catalog_approval.sql",
    "ontology/sql/020_catalog_source_graph.sql",
    "ontology/sql/021_scoped_validation.sql",
    "ontology/sql/022_scoped_posting_census.sql",
    "ontology/sql/023_scoped_catalog_edges.sql",
    "ontology/sql/024_sealed_catalog.sql",
    "ontology/sql/025_live_source_feed.sql",
    "ontology/sql/026_live_ncs_demand.sql",
    "ontology/sql/027_product_role_inputs.sql",
    "ontology/sql/catalog_reader_grants.psql",
    "ingestions/nara_job/sql/003_checks.sql",
    "operations/refresh_nara_job.hwf",
    # Replace the installer last, after all of its dependencies are available.
    "ontology/install.hwf",
)
ADAPTER_KEY = "@host-refresh-adapter"


def command(args: list[str], *, data: bytes | None = None) -> bytes:
    result = subprocess.run(args, input=data, capture_output=True, check=False)
    if result.returncode:
        # Do not echo arguments or captured output: service tooling can contain secrets.
        raise RuntimeError(f"{args[0]} command failed with status {result.returncode}")
    return result.stdout


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def installer_dependencies(data: bytes) -> tuple[str, ...]:
    paths = []
    for action in ET.fromstring(data).findall("./actions/action"):
        if action.findtext("type") != "SQL":
            continue
        filename = action.findtext("sqlfilename", "")
        if not re.fullmatch(r"\$\{PROJECT_HOME\}/ontology/sql/[0-9]{3}_[a-z_]+\.sql", filename):
            raise RuntimeError("Unexpected ontology installer SQL dependency")
        paths.append(filename.removeprefix("${PROJECT_HOME}/"))
    if not paths or len(paths) != len(set(paths)):
        raise RuntimeError("Missing or duplicate ontology installer SQL dependencies")
    if paths[-1] != "ontology/sql/027_product_role_inputs.sql":
        raise RuntimeError("Ontology installer does not reach migration 027")
    return tuple(paths)


def containers() -> dict[str, str]:
    result = {}
    for kind, selector in (("hop", f"volume={VOLUME}"), ("pg", f"name=^/{PG_NAME}$")):
        identity = command(["docker", "ps", "--filter", selector, "--format", "{{.ID}}"])
        value = identity.decode().strip()
        if not re.fullmatch(r"[0-9a-f]{12}", value):
            raise RuntimeError(f"Expected exactly one running {kind} container")
        result[kind] = value
    mounts = json.loads(
        command(["docker", "inspect", result["hop"], "--format", "{{json .Mounts}}"])
    )
    if not any(
        m.get("Name") == VOLUME
        and m.get("Destination") == PROJECT.rsplit("/projects/", 1)[0]
        and m.get("RW")
        for m in mounts
    ):
        raise RuntimeError("Hop persistent project mount does not match this reconciliation")
    return result


def remote_bytes(hop: str, relative: str) -> bytes | None:
    if relative not in ALLOWLIST and relative not in installer_dependencies(
        (ROOT / "ontology/install.hwf").read_bytes()
    ):
        raise RuntimeError("Artifact is outside the reconciliation allowlist")
    # Check ancestors too: a public path must never resolve through a private symlink.
    script = b"""set -eu
path="$1"; project="$2"; current="$path"
while :; do
 test ! -L "$current" || exit 1
 test "$current" != "$project" || break
 current=$(dirname "$current")
done
if test -e "$path"; then
 test -f "$path" || exit 1
 printf 'PRESENT\\n'
 cat "$path"
else
 printf 'ABSENT\\n'
fi
"""
    output = command(
        ["docker", "exec", "-i", hop, "sh", "-s", "--", f"{PROJECT}/{relative}", PROJECT],
        data=script,
    )
    marker, data = output.split(b"\n", 1)
    if marker == b"ABSENT":
        return None
    if marker != b"PRESENT":
        raise RuntimeError("Unrecognized runtime artifact response")
    return data


def host_bytes() -> bytes | None:
    if ADAPTER.is_symlink():
        raise RuntimeError("Host refresh adapter must not be a symlink")
    return ADAPTER.read_bytes() if ADAPTER.exists() else None


def db_state(pg: str) -> dict[str, Any]:
    query = b"""BEGIN READ ONLY;
SET LOCAL statement_timeout='30s';
SELECT jsonb_build_object(
 'catalog_context',catalog.catalog_context_v1(),
 'active_release_count',(SELECT count(*) FROM ontology.active_release),
 'unfinished_refresh',(SELECT count(*) FROM ingestion.refresh_execution WHERE finished_at IS NULL),
 'loading_runs',(SELECT count(*) FROM ingestion.run WHERE state='LOADING'),
 'retention_writers',(SELECT count(*) FROM retention.writer),
 'maintenance',ingestion.maintenance_active(),
 'validation_hints',(SELECT
  (length(pg_get_viewdef(oid))-
   length(replace(pg_get_viewdef(oid),'NOT MATERIALIZED','')))/length('NOT MATERIALIZED')
  FROM pg_class WHERE oid='ingestion.validation_issue'::regclass),
 'reader_schema_leaks',(SELECT count(*) FROM pg_namespace
  WHERE nspname IN ('ontology','ingestion','cs')
   AND has_schema_privilege('jobtology_catalog_reader',oid,'USAGE')),
 'reader_table_leaks',(SELECT count(*) FROM pg_class c
  JOIN pg_namespace n ON c.relnamespace=n.oid WHERE n.nspname='catalog'
   AND has_table_privilege('jobtology_catalog_reader',c.oid,
     'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')),
 'reader_hidden_function_leaks',(SELECT count(*) FROM pg_proc p
  JOIN pg_namespace n ON p.pronamespace=n.oid WHERE n.nspname='catalog'
   AND (left(p.proname,1)='_' OR p.proname='approve_catalog_release')
   AND has_function_privilege('jobtology_catalog_reader',p.oid,'EXECUTE')),
 'reader_public_functions',(SELECT count(*) FROM pg_proc p
  JOIN pg_namespace n ON p.pronamespace=n.oid WHERE n.nspname='catalog'
   AND p.proname IN ('catalog_context_v1','catalog_entities_v1','catalog_entity_v1',
    'catalog_relations_v1','catalog_summary_v1','live_postings_v1','live_posting_v1',
    'live_exam_sessions_v1','live_ncs_demand_v1','product_role_inputs_v1')
   AND has_function_privilege('jobtology_catalog_reader',p.oid,'EXECUTE'))
);
COMMIT;
"""
    output = command(
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
        data=query,
    )
    state = json.loads(output)
    assert_db_state(state)
    return state


def assert_db_state(state: dict[str, Any]) -> None:
    zeroes = (
        "active_release_count",
        "unfinished_refresh",
        "loading_runs",
        "retention_writers",
        "reader_schema_leaks",
        "reader_table_leaks",
        "reader_hidden_function_leaks",
    )
    if any(state[key] != 0 for key in zeroes) or state["maintenance"]:
        raise RuntimeError("Runtime is busy or catalogue publication/privilege invariants changed")
    context = state["catalog_context"]
    if (
        context["release_id"] != "ontology-catalog-source-20261001"
        or context["source_profile"]["kind"] != "SOURCE_ONLY"
        or context["source_profile"]["analysis_available"] is not False
        or state["validation_hints"] != 2
        or state["reader_public_functions"] != 10
    ):
        raise RuntimeError("Approved source catalogue or validation/reader contract changed")


def idle_cli(hop: str) -> None:
    processes = command(["docker", "top", hop, "-eo", "pid,args"]).decode()
    if re.search(r"hop-run\.sh|org\.apache\.hop\.run\.HopRun", processes):
        raise RuntimeError("A manual or scheduled Hop CLI execution is still running")


def snapshot(runtime: dict[str, str]) -> tuple[dict[str, Any], dict[str, bytes | None]]:
    sources = {path: (ROOT / path).read_bytes() for path in ALLOWLIST}
    sources[ADAPTER_KEY] = (ROOT / "operations/refresh.sh").read_bytes()
    dependencies = installer_dependencies(sources["ontology/install.hwf"])
    previous = {
        path: remote_bytes(runtime["hop"], path)
        for path in dict.fromkeys((*dependencies, *ALLOWLIST))
    }
    previous[ADAPTER_KEY] = host_bytes()
    entries = {}
    for path, old in previous.items():
        desired = sources[path] if path in sources else (ROOT / path).read_bytes()
        before = None if old is None else digest(old)
        after = digest(desired)
        if path not in sources and before != after:
            raise RuntimeError(f"Unexpected existing installer dependency drift: {path}")
        entries[path] = {"before": before, "after": after, "change": before != after}
    return entries, previous


def assert_same_plan(planned: dict[str, Any], actual: dict[str, Any]) -> None:
    if planned != actual:
        raise RuntimeError("Artifacts changed since planning; produce and review a new manifest")


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    path.chmod(0o600)


def apply(manifest_path: Path, runtime: dict[str, str], state: dict[str, Any]) -> Path:
    manifest = json.loads(manifest_path.read_bytes())
    if manifest.get("version") != 1 or manifest.get("containers") != runtime:
        raise RuntimeError("Manifest version or runtime container identity changed")
    if manifest.get("catalog_context") != state["catalog_context"]:
        raise RuntimeError("Approved catalogue changed since planning")
    entries, previous = snapshot(runtime)
    assert_same_plan(manifest.get("artifacts"), entries)
    receipt_dir = STATE / ("runtime-reconciliation-applied-" + uuid.uuid4().hex)
    receipt_dir.mkdir(mode=0o700)
    receipt = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "manifest": str(manifest_path.resolve()),
        "containers": runtime,
        "artifacts": entries,
        "installed": [],
        "status": "BACKING_UP",
    }
    receipt_path = receipt_dir / "receipt.json"
    write_json(receipt_path, receipt)
    changed = [path for path, entry in entries.items() if entry["change"]]
    staged: dict[str, str] = {}
    try:
        for path in changed:
            receipt["current_action"] = {
                "phase": "BACKING_UP",
                "operation": "backup-artifact",
                "artifact": path,
            }
            old = previous[path]
            if old is not None:
                backup = (
                    receipt_dir
                    / "before"
                    / ("host/jobtology-hop-refresh" if path == ADAPTER_KEY else path)
                )
                backup.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                backup.write_bytes(old)
                backup.chmod(0o600)
        receipt["current_action"] = {"phase": "BACKING_UP", "operation": "backup-schema"}
        dump = command(
            [
                "docker",
                "exec",
                runtime["pg"],
                "pg_dump",
                "-U",
                "postgres",
                "-d",
                "jobtology",
                "--schema-only",
                "--format=custom",
            ]
        )
        archive = receipt_dir / "database-schema.dump"
        archive.write_bytes(dump)
        archive.chmod(0o600)
        receipt["current_action"] = {"phase": "BACKING_UP", "operation": "validate-schema-backup"}
        command(["docker", "exec", "-i", runtime["pg"], "pg_restore", "--list"], data=dump)
        receipt["schema_backup_sha256"] = digest(dump)
        receipt["current_action"] = {"phase": "STAGING", "operation": "recheck-runtime"}
        assert_same_plan(entries, snapshot(runtime)[0])
        idle_cli(runtime["hop"])
        db_state(runtime["pg"])
        receipt["status"] = "STAGING"
        write_json(receipt_path, receipt)
        token = uuid.uuid4().hex
        for path in changed:
            receipt["current_action"] = {
                "phase": "STAGING",
                "operation": "stage-artifact",
                "artifact": path,
            }
            source = ROOT / ("operations/refresh.sh" if path == ADAPTER_KEY else path)
            if path == ADAPTER_KEY:
                temporary = ADAPTER.with_name(f".jobtology-hop-refresh-{token}")
                shutil.copyfile(source, temporary)
                temporary.chmod(0o700)
                staged[path] = str(temporary)
            else:
                temporary = f"{PROJECT}/{path}.reconcile-{token}"
                command(["docker", "cp", str(source), runtime["hop"] + ":" + temporary])
                staged[path] = temporary
                command(
                    ["docker", "exec", "-u", "root", runtime["hop"], "chown", "501:501", temporary]
                )
                command(["docker", "exec", "-u", "root", runtime["hop"], "chmod", "644", temporary])
                if (
                    command(["docker", "exec", runtime["hop"], "sha256sum", temporary])
                    .decode()
                    .split()[0]
                    != entries[path]["after"]
                ):
                    raise RuntimeError("Staged runtime artifact hash mismatch")
        # Keep the scheduler adapter last so its new workflow is already installed.
        ordered = [path for path in ALLOWLIST if path in changed]
        if ADAPTER_KEY in changed:
            ordered.append(ADAPTER_KEY)
        receipt["status"] = "INSTALLING"
        write_json(receipt_path, receipt)
        for path in ordered:
            receipt["current_action"] = {
                "phase": "INSTALLING",
                "operation": "verify-before-replace",
                "artifact": path,
            }
            current = host_bytes() if path == ADAPTER_KEY else remote_bytes(runtime["hop"], path)
            if current != previous[path]:
                raise RuntimeError("Runtime artifact changed during staging")
            receipt["current_action"] = {
                "phase": "INSTALLING",
                "operation": "atomic-rename",
                "artifact": path,
            }
            if path == ADAPTER_KEY:
                if digest(Path(staged[path]).read_bytes()) != entries[path]["after"]:
                    raise RuntimeError("Staged adapter hash mismatch")
                os.replace(staged[path], ADAPTER)
            else:
                command(
                    [
                        "docker",
                        "exec",
                        "-u",
                        "root",
                        runtime["hop"],
                        "mv",
                        "--",
                        staged[path],
                        f"{PROJECT}/{path}",
                    ]
                )
            del staged[path]
            receipt["installed"].append(path)
            write_json(receipt_path, receipt)
        receipt["current_action"] = {"phase": "VERIFYING", "operation": "verify-artifact-hashes"}
        after_entries, _ = snapshot(runtime)
        if any(entry["before"] != entry["after"] for entry in after_entries.values()):
            raise RuntimeError("Deployed runtime artifact verification failed")
        receipt["current_action"] = {"phase": "VERIFYING", "operation": "verify-catalog-context"}
        final_state = db_state(runtime["pg"])
        if final_state["catalog_context"] != state["catalog_context"]:
            raise RuntimeError("Approved catalogue changed during deployment")
        receipt["db_state"] = final_state
        receipt["status"] = "VERIFIED"
    except BaseException as error:
        receipt["status"] = "FAILED_REVIEW_RECEIPT_BEFORE_RETRY"
        receipt["failure"] = {
            "action": receipt.get("current_action"),
            "error_type": type(error).__name__,
        }
        raise RuntimeError(
            f"Deployment stopped; inspect protected receipt {receipt_path}"
        ) from error
    finally:
        for path, temporary in staged.items():
            try:
                if path == ADAPTER_KEY:
                    Path(temporary).unlink(missing_ok=True)
                else:
                    command(
                        [
                            "docker",
                            "exec",
                            "-u",
                            "root",
                            runtime["hop"],
                            "rm",
                            "-f",
                            "--",
                            temporary,
                        ]
                    )
            except (OSError, RuntimeError):
                receipt.setdefault("cleanup_pending", []).append(temporary)
        receipt["finished_at"] = datetime.now(UTC).isoformat()
        write_json(receipt_path, receipt)
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
        runtime = containers()
        idle_cli(runtime["hop"])
        state = db_state(runtime["pg"])
        if args.mode == "plan":
            entries, _ = snapshot(runtime)
            directory = STATE / ("runtime-reconciliation-plan-" + uuid.uuid4().hex)
            directory.mkdir(mode=0o700)
            path = directory / "manifest.json"
            write_json(
                path,
                {
                    "version": 1,
                    "containers": runtime,
                    "catalog_context": state["catalog_context"],
                    "db_state": state,
                    "artifacts": entries,
                },
            )
            print(path)
            count = sum(entry["change"] for entry in entries.values())
            print(f"{count} changed artifacts; no runtime writes")
        else:
            print(apply(args.manifest, runtime, state))


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
