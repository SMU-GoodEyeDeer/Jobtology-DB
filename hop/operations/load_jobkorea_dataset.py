#!/usr/bin/env python3
"""Load one reviewed private composed dataset with native Hop and freeze its inputs.

Holds the existing scheduler lock across deployment, native SQL installation,
archive verification, import/graph verification and deterministic input freezing.
Only the two JobKorea installers, full import and read-only graph checks execute.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import deploy_jobkorea_runtime as deployment

TOOLS = deployment.ROOT / "ingestions/jobkorea/tools"
sys.path.insert(0, str(TOOLS))
import prepare_inputs  # noqa: E402

common = deployment.common
APP = "/usr/local/tomcat/webapps/ROOT"
RAW_ROOT = deployment.PROJECT + "/data/jobkorea-raw"


def file_identity(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Archive files must be regular non-symlink files")
    with path.open("rb") as handle:
        sha256 = hashlib.file_digest(handle, "sha256").hexdigest()
    return {"sha256": sha256, "byte_length": path.stat().st_size}


def composition_identity(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError("Composed archive must be a non-symlink directory")
    provenance = json.loads((path / "provenance.json").read_bytes())
    descriptor = json.loads((path / "composition.json").read_bytes())
    if provenance.get("contract") != "jobkorea-dataset-provenance-v1":
        raise RuntimeError("Unexpected composition provenance contract")
    for name, prefix in (
        ("snapshot.ndjson", "snapshot"),
        ("occurrences.ndjson", "occurrences"),
        ("composition.json", "descriptor"),
    ):
        identity = file_identity(path / name)
        expected = {
            "sha256": provenance[prefix + "_sha256"],
            "byte_length": provenance[prefix + "_byte_length"],
        }
        if identity != expected:
            raise RuntimeError("Composed dataset digest/length changed")
    if (
        descriptor.get("selected_count") != provenance.get("selected_count")
        or provenance.get("archive_relative_root")
        != "jobkorea/datasets/" + provenance["descriptor_sha256"]
    ):
        raise RuntimeError("Composed dataset row count/archive root changed")
    expected_names = {
        "snapshot.ndjson",
        "occurrences.ndjson",
        "composition.json",
        "provenance.json",
    }
    for item in descriptor["source_inventory"]:
        name = item["file"]
        if not isinstance(name, str) or Path(name).name != name or name in (".", ".."):
            raise RuntimeError("Invalid original archive filename")
        original = "originals/" + name
        if file_identity(path / original) != {
            "sha256": item["sha256"],
            "byte_length": item["bytes"],
        }:
            raise RuntimeError("Archived original file changed")
        expected_names.add(original)
    inventory = {}
    for entry in path.rglob("*"):
        if entry.is_symlink():
            raise RuntimeError("Archive symlinks are forbidden")
        if entry.is_file():
            inventory[str(entry.relative_to(path))] = file_identity(entry)
        elif not entry.is_dir():
            raise RuntimeError("Unexpected archive object")
    if set(inventory) != expected_names:
        raise RuntimeError("Composed archive file inventory changed")
    return provenance, inventory


def remote_inventory(hop: str, root: str) -> dict[str, Any]:
    script = b"""set -eu
root="$1"; project="$2"; current="$root"
while :; do
 test ! -L "$current" || exit 1
 test "$current" != "$project" || break
 current=$(dirname "$current")
done
if test ! -e "$root"; then printf 'ABSENT\\n'; exit 0; fi
test -d "$root"
test -z "$(find "$root" -type l -print -quit)"
cd "$root"
find . -type f -exec sha256sum {} +
printf 'SIZES\\n'
find . -type f -exec stat -c '%s %n' {} +
"""
    raw = common.command(
        ["docker", "exec", "-i", hop, "sh", "-s", "--", root, deployment.PROJECT], data=script
    ).decode()
    if raw == "ABSENT\n":
        return {}
    hashes, sizes = raw.split("SIZES\n", 1)
    inventory = {}
    for line in hashes.splitlines():
        digest, name = line.split("  ", 1)
        inventory[name.removeprefix("./")] = {"sha256": digest}
    for line in sizes.splitlines():
        size, name = line.split(" ", 1)
        inventory[name.removeprefix("./")]["byte_length"] = int(size)
    return inventory


def archive_composition(
    hop: str, source: Path, provenance: dict[str, Any], inventory: dict[str, Any]
) -> str:
    destination = RAW_ROOT + "/" + provenance["archive_relative_root"]
    previous = remote_inventory(hop, destination)
    if previous:
        if previous != inventory:
            raise RuntimeError("Existing immutable composition archive differs")
        return destination
    # Missing private evidence parents only; preserve every existing directory.
    relative = str(Path(destination).relative_to(deployment.PROJECT))
    script = b"""set -eu
project="$1"; relative="$2"; current="$project"
old_ifs="$IFS"; IFS=/
for part in $relative; do
 current="$current/$part"; test ! -L "$current"
 if test -e "$current"; then test -d "$current"; else
  mkdir "$current"; chown 501:501 "$current"; chmod 700 "$current"
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
            deployment.PROJECT,
            str(Path(relative).parent),
        ],
        data=script,
    )
    temporary = destination + ".stage-" + uuid.uuid4().hex
    common.command(["docker", "exec", "-u", "root", hop, "mkdir", "--", temporary])
    try:
        common.command(["docker", "cp", str(source) + "/.", hop + ":" + temporary])
        for kind, mode in (("d", "700"), ("f", "600")):
            for tool, value in (("chown", "501:501"), ("chmod", mode)):
                common.command(
                    [
                        "docker",
                        "exec",
                        "-u",
                        "root",
                        hop,
                        "find",
                        temporary,
                        "-type",
                        kind,
                        "-exec",
                        tool,
                        value,
                        "{}",
                        "+",
                    ]
                )
        if remote_inventory(hop, temporary) != inventory:
            raise RuntimeError("Staged private archive failed digest/length verification")
        if remote_inventory(hop, destination):
            raise RuntimeError("Archive destination appeared during staging")
        common.command(
            ["docker", "exec", "-u", "root", hop, "mv", "-T", "--", temporary, destination]
        )
    finally:
        # Only our exact newly staged directory; accepted immutable archives stay.
        common.command(["docker", "exec", "-u", "root", hop, "rm", "-rf", "--", temporary])
    if remote_inventory(hop, destination) != inventory:
        raise RuntimeError("Installed immutable archive failed verification")
    return destination


def native(
    hop: str,
    workflow: str,
    directory: Path,
    name: str,
    params: str = "",
    *,
    configuration: str = "jobkorea-local",
) -> Path:
    log = directory / (name + ".log")
    args = [
        "docker",
        "exec",
        "-e",
        "HOP_OPTIONS=-Xmx1024m",
        "-w",
        APP,
        hop,
        "bash",
        "hop-run.sh",
        "-j",
        "default",
        "-r",
        configuration,
        "-f",
        workflow,
        "-l",
        "Basic",
    ]
    if params:
        args += ["-p", params]
    print(json.dumps({"phase": name, "status": "RUNNING", "log": str(log)}), flush=True)
    with log.open("xb") as handle:
        log.chmod(0o600)
        result = subprocess.run(args, stdout=handle, stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        raise RuntimeError("Native Hop failed; inspect protected log " + str(log))
    print(json.dumps({"phase": name, "status": "PASSED"}), flush=True)
    return log


def verify_graph(hop: str, runs: list[str], directory: Path, label: str) -> Path:
    """Use the installed native read-only totals verifier and private connections."""
    root = ET.parse(deployment.ROOT / "ingestions/jobkorea/full.hwf").getroot()
    root.find("name").text = "Read-only source graph totals"
    root.find("parameters").clear()
    parameters = root.find("parameters")
    parameter = ET.SubElement(parameters, "parameter")
    ET.SubElement(parameter, "name").text = "NEO4J_CONNECTION"
    ET.SubElement(parameter, "default_value").text = "jobtology-neo4j"
    actions = root.find("actions")
    templates = {action.findtext("type"): action for action in actions}
    actions.clear()
    import copy

    for kind in ("SPECIAL", "SUCCESS", "ABORT"):
        actions.append(copy.deepcopy(templates[kind]))
    names = ["Start"]
    for number, run in enumerate(runs):
        action = copy.deepcopy(templates["PIPELINE"])
        name = f"Verify graph totals {number + 1}"
        action.find("name").text = name
        action.find("filename").text = "${PROJECT_HOME}/graph/verify_totals.hpl"
        action.find("run_configuration").text = "graph-local"
        mapped = action.find("parameters")
        mapped.clear()
        ET.SubElement(mapped, "pass_all_parameters").text = "Y"
        parameter = ET.SubElement(mapped, "parameter")
        ET.SubElement(parameter, "name").text = "RUN_ID"
        ET.SubElement(parameter, "value").text = run
        actions.append(action)
        names.append(name)
    hops = root.find("hops")
    hops.clear()
    for index, name in enumerate(names):
        for target, evaluation in (
            (names[index + 1] if index + 1 < len(names) else "Success", "Y"),
            *(([("Abort", "N")]) if index else []),
        ):
            hop_node = ET.SubElement(hops, "hop")
            for key, value in (
                ("from", name),
                ("to", target),
                ("evaluation", evaluation),
                ("enabled", "Y"),
                ("unconditional", "Y" if index == 0 else "N"),
            ):
                ET.SubElement(hop_node, key).text = value
    local = directory / (label + ".hwf")
    ET.ElementTree(root).write(local, encoding="utf-8", xml_declaration=True)
    remote = "/tmp/jobkorea-read-graph-" + uuid.uuid4().hex + ".hwf"
    common.command(["docker", "cp", str(local), hop + ":" + remote])
    common.command(["docker", "exec", "-u", "root", hop, "chown", "501:501", remote])
    try:
        return native(hop, remote, directory, label, configuration="graph-local")
    finally:
        common.command(["docker", "exec", "-u", "root", hop, "rm", "-f", "--", remote])


def load(manifest_path: Path, composition: Path, work: Path) -> Path:
    provenance, inventory = composition_identity(composition)
    manifest = json.loads(manifest_path.read_bytes())
    runtime = common.containers()
    common.idle_cli(runtime["hop"])
    state = common.db_state(runtime["pg"])
    if manifest["containers"] != runtime or manifest["catalog_context"] != state["catalog_context"]:
        raise RuntimeError("Reviewed runtime/catalogue identity changed")
    before = deployment.preservation_state(runtime["pg"])
    if before != manifest["preservation_state"]:
        raise RuntimeError("Protected data changed since reviewed plan")
    entries, _ = deployment.snapshot(runtime)
    if any(e["before"] != e["after"] for e in entries.values()):
        artifact_receipt = deployment.apply(manifest_path, runtime, state)
    else:
        if {p: e["after"] for p, e in entries.items()} != {
            p: e["after"] for p, e in manifest["artifacts"].items()
        }:
            raise RuntimeError("Reviewed artifact hashes changed")
        artifact_receipt = None
    directory = work / ("execution-" + uuid.uuid4().hex)
    directory.mkdir(mode=0o700)
    receipt_path = directory / "receipt.json"
    receipt: dict[str, Any] = {
        "status": "RUNNING",
        "started_at": datetime.now(UTC).isoformat(),
        "containers": runtime,
        "composition_provenance": provenance,
        "deployment_receipt": None if artifact_receipt is None else str(artifact_receipt),
        "preservation_before": before,
        "catalog_before": state,
        "logs": {},
    }
    common.write_json(receipt_path, receipt)
    try:
        legacy = json.loads(
            deployment.sql(
                runtime["pg"],
                "BEGIN READ ONLY; SELECT jsonb_agg(run_id "
                "ORDER BY source_id) FROM ingestion.latest_ready_run "
                "WHERE source_id<>'jobkorea'; COMMIT;",
            )
        )
        receipt["logs"]["legacy_graph_before"] = str(
            verify_graph(runtime["hop"], legacy, directory, "legacy-graph-before")
        )
        for name in ("install", "install_linking"):
            receipt["phase"] = name
            common.write_json(receipt_path, receipt)
            receipt["logs"][name] = str(
                native(
                    runtime["hop"],
                    deployment.PROJECT + "/ingestions/jobkorea/" + name + ".hwf",
                    directory,
                    name,
                )
            )
        if deployment.preservation_state(runtime["pg"]) != before:
            raise RuntimeError("Protected data changed during native installation")
        receipt["phase"] = "archive"
        common.write_json(receipt_path, receipt)
        archive = archive_composition(runtime["hop"], composition, provenance, inventory)
        receipt["archive"] = {"root": archive, "files": inventory}
        receipt["phase"] = "native-import"
        common.write_json(receipt_path, receipt)
        params = (
            f"INPUT_FILE={archive}/snapshot.ndjson,RAW_ROOT={RAW_ROOT},"
            "INPUT_FORMAT=NDJSON,MODE=IMPORT"
        )
        receipt["logs"]["full"] = str(
            native(
                runtime["hop"],
                deployment.PROJECT + "/ingestions/jobkorea/full.hwf",
                directory,
                "full-import",
                params,
            )
        )
        runner = prepare_inputs.Database(runtime["pg"], "jobtology", directory)
        result = runner(
            "SELECT jsonb_build_object('runs',jsonb_agg(run_id)) FROM "
            "ingestion.jobkorea_import WHERE file_sha256="
            + prepare_inputs.quoted(provenance["snapshot_sha256"])
            + ";"
        )
        runs = result["runs"]
        if not isinstance(runs, list) or len(runs) != 1:
            raise RuntimeError("Expected one exact supplied-file run identity")
        jobs = runs[0]
        receipt["job_run_id"] = jobs
        # This helper verifies local descriptor/map/snapshot hashes before registration.
        prepare_inputs.register_provenance(runner, jobs, composition)
        receipt["phase"] = "freeze-all-inputs"
        common.write_json(receipt_path, receipt)
        prepared = prepare_inputs.Preparation(
            runner,
            jobs,
            work / "prepared-inputs",
            250,
            require_provenance=True,
            target=runtime["pg"] + "/jobtology",
        ).run()
        if prepared["status"] != "VERIFIED" or prepared["prepared"] != provenance["selected_count"]:
            raise RuntimeError("Complete prepared-input coverage failed")
        receipt["input_preparation_receipt"] = str(work / "prepared-inputs/receipt.json")
        receipt["logs"]["source_graph_after"] = str(
            verify_graph(runtime["hop"], [*legacy, jobs], directory, "source-graph-after")
        )
        report = runner(
            "SELECT jsonb_build_object('run_id',u.run_id,'state',u.state,'mode',u.mode,"
            "'records',(SELECT count(*) FROM ingestion.ready_record r WHERE r.run_id=u.run_id),"
            "'validation_issues',(SELECT count(*) FROM ingestion.validation_issue v "
            "WHERE v.run_id=u.run_id),"
            "'graph_checkpoint',to_jsonb(g),'import_receipt',to_jsonb(i)) "
            "FROM ingestion.run u JOIN ingestion.jobkorea_import i USING(run_id) "
            "LEFT JOIN ingestion.graph_export g USING(run_id) WHERE u.run_id="
            + prepare_inputs.quoted(jobs)
            + ";"
        )
        if (
            report["state"] != "READY"
            or report["records"] != provenance["selected_count"]
            or report["validation_issues"] != 0
            or not report["graph_checkpoint"]
        ):
            raise RuntimeError("Native source acceptance/checkpoint verification failed")
        after = deployment.preservation_state(runtime["pg"])
        final = common.db_state(runtime["pg"])
        if after != before or final["catalog_context"] != state["catalog_context"]:
            raise RuntimeError("Legacy data/catalogue preservation failed")
        receipt.update(
            status="VERIFIED",
            source=report,
            preservation_after=after,
            catalog_after=final,
            no_source_requests=True,
            no_model_calls=True,
            no_key_reads=True,
            no_llm_parse=True,
            no_semantic_links=True,
        )
    except BaseException as error:
        receipt["status"] = "FAILED_REVIEW_RECEIPT_BEFORE_RETRY"
        receipt["failure"] = {"error_type": type(error).__name__, "message": str(error)}
        receipt["recovery"] = {
            "automatic_rollback": False,
            "scheduler_lock_required": str(deployment.STATE / "refresh.lock"),
            "loading_run_guard": (
                "This supervisor rejects all existing LOADING runs. Inspect the exact run and "
                "protected native log; use the native archive-only resume before retrying."
            ),
            "native_workflow": deployment.PROJECT + "/ingestions/jobkorea/full.hwf",
            "native_run_configuration": "jobkorea-local",
            "native_resume_parameters": (
                f"RESUME_RUN_ID=EXACT_RUN_ID,RAW_ROOT={RAW_ROOT},INPUT_FORMAT=NDJSON,MODE=IMPORT"
            ),
            "native_log_level": "Basic",
            "input_checkpoints": str(work / "prepared-inputs"),
            "ready_graph_recovery": (
                "An accepted PostgreSQL READY run is preserved on graph failure. Resume the "
                "same exact archived run to verify its graph and checkpoint."
            ),
        }
        try:
            diagnostic = deployment.sql(
                runtime["pg"],
                "BEGIN READ ONLY; SELECT jsonb_agg(jsonb_build_object('run_id',u.run_id,"
                "'state',u.state,'next_byte_offset',i.next_byte_offset,"
                "'next_line_number',i.next_line_number,'batch_count',i.batch_count,"
                "'loaded',i.loaded,'error_code',i.error_code)) "
                "FROM ingestion.jobkorea_import i JOIN ingestion.run u USING(run_id) "
                "WHERE i.file_sha256="
                + prepare_inputs.quoted(provenance["snapshot_sha256"])
                + "; COMMIT;",
            )
            receipt["recovery"]["source_state"] = json.loads(diagnostic)
        except (RuntimeError, ValueError):
            receipt["recovery"]["source_state"] = "Inspect after failed installation is resolved"
        raise RuntimeError(
            "Load stopped; inspect protected receipt " + str(receipt_path)
        ) from error
    finally:
        receipt["finished_at"] = datetime.now(UTC).isoformat()
        common.write_json(receipt_path, receipt)
    return receipt_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--composition-dir", required=True, type=Path)
    parser.add_argument("--checkpoint-dir", required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    args.checkpoint_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.checkpoint_dir.is_symlink() or args.checkpoint_dir.stat().st_mode & 0o077:
        raise RuntimeError("Use a private non-symlink checkpoint directory")
    with (deployment.STATE / "refresh.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(
            load(args.manifest, args.composition_dir.absolute(), args.checkpoint_dir.resolve()),
            flush=True,
        )


if __name__ == "__main__":
    main()
