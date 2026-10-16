"""One guarded six-file successor for an interrupted, pre-deletion flat stage.

This module is called by the host operator under its single refresh.lock. It
never stops a process, rewrites an original manifest, or restores graph objects.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FILES = tuple(
    "ontology/" + name + ".hpl"
    for name in (
        "write_edge_scalars",
        "write_edge_arrays",
        "verify_edge_scalars",
        "verify_edge_arrays",
        "verify_legacy_edge_scalars",
        "verify_legacy_edge_arrays",
    )
)
OLD_MATCH = (
    "MATCH (a:ontologyObject {id:row.subject_id})-[n:$(row.predicate) "
    "{id:row.owner_id}]->(b:ontologyObject {id:row.object_id})"
)
NEW_MATCH = (
    "MATCH (a:ontologyObject {id:row.subject_id}) USING INDEX SEEK a:ontologyObject(id) "
    "WITH row,a MATCH (b:ontologyObject {id:row.object_id}) "
    "USING INDEX SEEK b:ontologyObject(id) WITH row,a,b "
    "MATCH (a)-[n:$(row.predicate) {id:row.owner_id}]->(b)"
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def private_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise RuntimeError("Protected immutable amendment evidence required")
    return json.loads(path.read_bytes())


def query_text(query: str) -> str:
    # Preserve quoted tokens exactly, including significant whitespace.
    return re.sub(
        r"'(?:''|\\.|[^'])*'|\"(?:\\.|[^\"])*\"|\s+",
        lambda m: " " if m.group().isspace() else m.group(),
        query,
    ).strip()


def validate_candidate(original: bytes, candidate: bytes) -> None:
    old, new = ET.fromstring(original), ET.fromstring(candidate)
    transforms = [
        next(t for t in document.findall("transform") if t.findtext("type") == "Neo4jCypherOutput")
        for document in (old, new)
    ]
    texts = [t.find("cypher") for t in transforms]
    if any(t is None or t.text is None for t in texts):
        raise RuntimeError("Missing exact native edge-property query")
    old_query, new_query = str(texts[0].text), str(texts[1].text)  # type: ignore[union-attr]
    if old_query.count(OLD_MATCH) != 1 or query_text(new_query) != query_text(
        old_query.replace(OLD_MATCH, NEW_MATCH)
    ):
        raise RuntimeError("Successor query differs beyond exact double endpoint INDEX SEEK")
    for element in texts:
        assert element is not None
        element.text = "VALIDATED_QUERY"
    if ET.tostring(old) != ET.tostring(new):
        raise RuntimeError("Successor native metadata/settings changed outside its query")


def successor_hashes(manifest: dict[str, Any], receipt: dict[str, Any]) -> dict[str, str]:
    """Read-only final/resume gate; incomplete deployment is never accepted."""
    intent = receipt.get("successor_amendment_intent")
    if not intent:
        return {name: entry["after"] for name, entry in manifest["artifacts"].items()}
    if receipt.get("successor_amendment_complete") is not True:
        raise RuntimeError("Incomplete successor amendment requires amend-resume")
    amendment = sealed_amendment(manifest, receipt)
    result = {name: entry["after"] for name, entry in manifest["artifacts"].items()}
    result.update({name: entry["after"] for name, entry in amendment["files"].items()})
    return result


def sealed_amendment(manifest: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    intent = receipt["successor_amendment_intent"]
    path = Path(intent["manifest"])
    amendment = private_json(path)
    if sha(path.read_bytes()) != intent["sha256"]:
        raise RuntimeError("Immutable successor amendment checksum changed")
    original = Path(receipt["manifest"])
    if (
        amendment.get("kind") != "FLAT_STAGE_SIX_FILE_SUCCESSOR"
        or amendment["original_manifest_sha256"] != sha(original.read_bytes())
        or amendment["original_manifest"] != str(original.resolve())
        or amendment["original_graph_sha256"] != manifest["graph"]["sha256"]
        or amendment["database_backup_sha256"] != receipt["database_backup"]["sha256"]
        or amendment["migration_token"] != receipt["token"]
        or set(amendment["files"]) != set(FILES)
        or amendment["flat_inventory"]["sha256"] != receipt["flat_inventory"]["sha256"]
        or amendment["original_artifacts"]
        != {name: entry["after"] for name, entry in manifest["artifacts"].items()}
    ):
        raise RuntimeError("Successor amendment original evidence/scope binding changed")
    result = {name: entry["after"] for name, entry in manifest["artifacts"].items()}
    for name, entry in amendment["files"].items():
        if entry["before"] != result[name]:
            raise RuntimeError("Successor predecessor hash differs from original manifest")
        candidate = Path(entry["candidate"])
        if candidate.is_symlink() or sha(candidate.read_bytes()) != entry["after"]:
            raise RuntimeError("Sealed successor candidate bytes changed")
        predecessor = Path(entry["predecessor"])
        if predecessor.is_symlink() or sha(predecessor.read_bytes()) != entry["before"]:
            raise RuntimeError("Sealed successor predecessor bytes changed")
        validate_candidate(predecessor.read_bytes(), candidate.read_bytes())
    native = Path(amendment["native_proof"])
    proof = private_json(native)
    if (
        sha(native.read_bytes()) != amendment["native_proof_sha256"]
        or proof.get("status") != "PASSED"
        or proof.get("candidate_hpl_sha256")
        != {name: entry["after"] for name, entry in amendment["files"].items()}
    ):
        raise RuntimeError("Sealed native successor validation proof changed")
    return amendment


def reader_closed(o: Any, pg: str, release: str) -> None:
    result = subprocess.run(
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
            "-v",
            "VERBOSITY=verbose",
            "-U",
            "postgres",
            "-d",
            o.PG_DATABASE,
        ],
        input=(
            "BEGIN READ ONLY; SELECT catalog._approved_release("
            + o.dates.quote(release)
            + "); COMMIT;"
        ).encode(),
        capture_output=True,
        check=False,
    )
    if result.returncode == 0 or not re.search(
        r"^ERROR:\s+P0001:\s+FLAT_GRAPH_PROJECTION_NOT_READY\s*$",
        result.stderr.decode(errors="replace"),
        re.MULTILINE,
    ):
        raise RuntimeError("Exact flat not-ready catalogue reader fence required")


def quiescent(o: Any, runtime: dict[str, str], load: dict[str, Any], directory: Path) -> None:
    o.common.idle_cli(runtime["hop"])
    other = json.loads(
        o.deployment.sql(
            runtime["pg"],
            "BEGIN READ ONLY; SELECT jsonb_build_object('refresh',"
            "(SELECT count(*) FROM ingestion.refresh_execution WHERE finished_at IS NULL),"
            "'loading',(SELECT count(*) FROM ingestion.run WHERE state='LOADING'),"
            "'old_ontology',(SELECT count(*) FROM ontology.graph_load WHERE state='RUNNING'),"
            "'maintenance',ingestion.maintenance_active(),"
            "'llm_batches',(SELECT count(*) FROM enrichment.batch WHERE state='RUNNING' "
            "AND created_at>clock_timestamp()-interval '24 hours'),"
            "'llm_reserved',(SELECT count(*) FROM enrichment.attempt WHERE state='RESERVED' "
            "AND reserved_at>clock_timestamp()-interval '24 hours'),"
            "'writers',(SELECT count(*) FROM retention.writer WHERE writer_id<>"
            + o.dates.quote(load["load_id"])
            + ")); COMMIT;",
        )
    )
    if any(other.values()):
        raise RuntimeError("Unaccounted ingestion/ontology/retention writer remains active")
    rows = o.graph.native_rows(
        runtime["hop"],
        "SHOW TRANSACTIONS YIELD database RETURN "
        "toString(count(CASE WHEN database='neo4j' THEN 1 END)) AS signature",
        directory,
        "amendment-quiescence-" + uuid.uuid4().hex,
    )
    if len(rows) != 1 or int(rows[0]) > 1:
        raise RuntimeError("Another Neo4j transaction remains active")
    o.common.idle_cli(runtime["hop"])


def artifact_state(o: Any, runtime: dict[str, str], amendment: dict[str, Any]) -> dict[str, str]:
    entries, _ = o.deployment.snapshot(runtime)
    expected = amendment["original_artifacts"]
    if set(entries) != set(expected):
        raise RuntimeError("Public artifact closure changed outside amendment")
    result: dict[str, str] = {}
    for name, entry in entries.items():
        allowed = {expected[name]}
        if name in amendment["files"]:
            allowed.add(amendment["files"][name]["after"])
        if entry["after"] not in allowed or entry["before"] not in allowed:
            raise RuntimeError("Unrelated public artifact/hash drift during successor amendment")
        result[name] = entry["before"]
    return result


def prove_partial(
    o: Any,
    runtime: dict[str, str],
    original: dict[str, Any],
    receipt: dict[str, Any],
    load: dict[str, Any],
    directory: Path,
    flat: dict[str, Any],
) -> dict[str, Any]:
    if load["state"] not in ("RUNNING", "FAILED"):
        raise RuntimeError("Successor only supports an interrupted pre-deletion flat stage")
    quiescent(o, runtime, load, directory)
    if load["state"] == "RUNNING":
        o.require_staged_tables(runtime["pg"], original["old_tables"], load)
    else:
        o.require_old_tables(original["old_tables"], o.all_old_tables(runtime["pg"]))
    schema = o.dates.schema_preservation(runtime["pg"])
    o.require_schema(original["schema"], schema)
    reader_closed(o, runtime["pg"], original["release_id"])
    snapshot = o.graph.graph_snapshot(runtime["hop"], directory, "amendment-partial")
    preservation = o.require_flat_preserved(
        o.graph.validate_archive(original["graph"]),
        Path(snapshot["path"]),
        flat,
        removed=False,
        partial_new_edge_properties=True,
    )
    if (
        preservation["revision_nodes"] != original["backing"]["revision_nodes"]
        or preservation["legacy_edges"] != original["backing"]["revision_edges"]
    ):
        raise RuntimeError("Original revision inventory changed before successor retry")
    quiescent(o, runtime, load, directory)
    current = o.flat_load(runtime["pg"], original["release_id"], load["database_id"])
    if current != load:
        raise RuntimeError("Exact interrupted flat token/checkpoint changed during proof")
    return {
        "graph": snapshot,
        "preservation": preservation,
        "schema": schema,
        "load": load,
        "all_old_tables_preserved": True,
        "reader_closed": True,
        "migration_token": receipt["token"],
    }


def install_one(o: Any, runtime: dict[str, str], name: str, entry: dict[str, Any]) -> None:
    source = Path(entry["candidate"])
    if source.is_symlink() or sha(source.read_bytes()) != entry["after"]:
        raise RuntimeError("Pinned successor file checksum changed")
    previous = o.deployment.remote_bytes(runtime["hop"], name)
    if previous is None or sha(previous) not in {entry["before"], entry["after"]}:
        raise RuntimeError("Successor public file predecessor drifted")
    if sha(previous) == entry["after"]:
        return
    temporary = o.common.PROJECT + "/" + name + ".flat-successor-" + uuid.uuid4().hex
    try:
        o.common.command(["docker", "cp", str(source), runtime["hop"] + ":" + temporary])
        for command, argument in (("chown", "501:501"), ("chmod", "644")):
            o.common.command(
                ["docker", "exec", "-u", "root", runtime["hop"], command, argument, temporary]
            )
        actual = o.common.command(["docker", "exec", runtime["hop"], "sha256sum", temporary])
        if actual.decode().split()[0] != entry["after"] or (
            o.deployment.remote_bytes(runtime["hop"], name) != previous
        ):
            raise RuntimeError("Successor staged/predecessor file changed before atomic switch")
        o.common.command(
            [
                "docker",
                "exec",
                "-u",
                "root",
                runtime["hop"],
                "mv",
                "--",
                temporary,
                o.common.PROJECT + "/" + name,
            ]
        )
    finally:
        o.common.command(
            ["docker", "exec", "-u", "root", runtime["hop"], "rm", "-f", "--", temporary]
        )


def amend(
    o: Any,
    runtime: dict[str, str],
    receipt_path: Path,
    candidate_dir: Path | None,
    validation_proof: Path | None,
) -> Path:
    """Seal, prove, deploy six successors and fail the owned old token; stay fenced."""
    receipt = private_json(receipt_path)
    original_path = Path(receipt["manifest"])
    original = private_json(original_path)
    fence = private_json(o.common.STATE / o.FENCE_NAME)
    if receipt.get("runtime") != runtime or fence.get("token") != receipt.get("token"):
        raise RuntimeError("Original fenced migration/runtime ownership required")
    if receipt.get("successor_amendment_complete"):
        successor_hashes(original, receipt)
        raise RuntimeError("Successor already complete; use regular resume")
    database = original["catalogue"]["approval"]["database_id"]
    load = o.flat_load(runtime["pg"], original["release_id"], database)
    if not load or load["state"] not in ("RUNNING", "FAILED"):
        raise RuntimeError("Exact interrupted RUNNING/FAILED flat token required")
    if receipt.get("post_removal_graph_verified") or receipt.get("removed_revision_nodes"):
        raise RuntimeError("Successor amendment cannot follow revision removal")
    directory = receipt_path.resolve().parent
    amendment: dict[str, Any]
    intent = receipt.get("successor_amendment_intent")
    if intent:
        amendment_path = Path(intent["manifest"])
        amendment = sealed_amendment(original, receipt)
        if amendment["old_load"]["load_id"] != load["load_id"]:
            raise RuntimeError("Successor old flat token changed during amendment retry")
        work = amendment_path.parent
    else:
        if candidate_dir is None or validation_proof is None:
            raise RuntimeError(
                "Exact candidate bundle and successful native validation proof required"
            )
        work = directory / ("successor-" + uuid.uuid4().hex)
        work.mkdir(mode=0o700)
        native = private_json(validation_proof)
        if native.get("status") != "PASSED" or set(native.get("candidate_hpl_sha256", {})) != set(
            FILES
        ):
            raise RuntimeError("Exact six-pipeline PASSED native successor proof required")
        entries, previous = o.deployment.snapshot(runtime)
        if set(entries) != set(original["artifacts"]) or any(
            e["before"] != original["artifacts"][name]["after"]
            or e["after"] != original["artifacts"][name]["after"]
            for name, e in entries.items()
        ):
            raise RuntimeError("Original public runtime changed before successor amendment")
        files: dict[str, Any] = {}
        for name in FILES:
            candidate = candidate_dir / Path(name).name
            if not candidate.exists():
                candidate = candidate_dir / (Path(name).stem + "-index-hints.hpl")
            if candidate.is_symlink():
                raise RuntimeError("Successor candidates must not be symlinks")
            data = candidate.read_bytes()
            validate_candidate(previous[name], data)
            if sha(data) != native["candidate_hpl_sha256"][name]:
                raise RuntimeError("Native successor proof/file checksum mismatch")
            target = work / "candidates" / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o600)
            old = work / "predecessors" / name
            old.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            old.write_bytes(previous[name])
            old.chmod(0o600)
            files[name] = {
                "before": sha(previous[name]),
                "after": sha(data),
                "candidate": str(target),
                "predecessor": str(old),
            }
        flat = receipt.get("flat_inventory") or o.capture_flat_inventory(
            runtime["pg"], original["release_id"], work
        )
        partial = prove_partial(o, runtime, original, receipt, load, work, flat)
        if (
            o.checksum(Path(receipt["database_backup"]["path"]))
            != receipt["database_backup"]["sha256"]
        ):
            raise RuntimeError("Original reversible PostgreSQL backup checksum changed")
        amendment = {
            "version": 1,
            "kind": "FLAT_STAGE_SIX_FILE_SUCCESSOR",
            "created_at": datetime.now(UTC).isoformat(),
            "original_manifest": str(original_path.resolve()),
            "original_manifest_sha256": sha(original_path.read_bytes()),
            "original_graph_sha256": original["graph"]["sha256"],
            "database_backup_sha256": receipt["database_backup"]["sha256"],
            "migration_token": receipt["token"],
            "old_load": load,
            "files": files,
            "original_artifacts": {name: e["after"] for name, e in original["artifacts"].items()},
            "flat_inventory": flat,
            "partial_proof": partial,
            "native_proof": str(validation_proof.resolve()),
            "native_proof_sha256": sha(validation_proof.read_bytes()),
        }
        amendment_path = work / "manifest.json"
        o.common.write_json(amendment_path, amendment)
        o.graph.event(
            directory,
            receipt,
            "SUCCESSOR_AMENDMENT_SEALED",
            successor_amendment_intent={
                "manifest": str(amendment_path),
                "sha256": sha(amendment_path.read_bytes()),
            },
            flat_inventory=flat,
        )
    attempt = work / ("attempt-" + uuid.uuid4().hex)
    attempt.mkdir(mode=0o700)
    try:
        if sha(original_path.read_bytes()) != amendment["original_manifest_sha256"]:
            raise RuntimeError("Original migration manifest changed after amendment sealing")
        artifact_state(o, runtime, amendment)
        if intent:
            prove_partial(o, runtime, original, receipt, load, attempt, amendment["flat_inventory"])
        else:
            quiescent(o, runtime, load, attempt)
        o.graph.event(directory, receipt, "SUCCESSOR_DEPLOYMENT_STARTING")
        for name in FILES:
            o.graph.event(directory, receipt, "SUCCESSOR_FILE_SWITCH_INTENT", successor_file=name)
            install_one(o, runtime, name, amendment["files"][name])
            o.graph.event(directory, receipt, "SUCCESSOR_FILE_SWITCHED", successor_file=name)
        states = artifact_state(o, runtime, amendment)
        if any(states[name] != amendment["files"][name]["after"] for name in FILES):
            raise RuntimeError("Successor six-file deployment verification failed")
        quiescent(o, runtime, load, attempt)
        current = o.flat_load(runtime["pg"], original["release_id"], database)
        if current != load:
            raise RuntimeError("Flat checkpoint changed before owned old-token failure")
        o.graph.event(
            directory,
            receipt,
            "SUCCESSOR_OLD_TOKEN_FAILURE_INTENT",
            successor_old_load_id=load["load_id"],
        )
        o.deployment.sql(
            runtime["pg"],
            "SELECT ontology.fail_flat_graph_load(" + o.dates.quote(load["load_id"]) + ")",
        )
        current = o.flat_load(runtime["pg"], original["release_id"], database)
        if not current or current["load_id"] != load["load_id"] or current["state"] != "FAILED":
            raise RuntimeError("Owned interrupted flat load did not reach FAILED")
        o.require_old_tables(original["old_tables"], o.all_old_tables(runtime["pg"]))
        if o.dates.schema_preservation(runtime["pg"]) != amendment["partial_proof"]["schema"]:
            raise RuntimeError("PostgreSQL schema changed during six-file successor deployment")
        reader_closed(o, runtime["pg"], original["release_id"])
        o.graph.event(
            directory,
            receipt,
            "SUCCESSOR_VERIFIED_FRESH_STAGE_REQUIRED",
            status="FAILED_RETRY_READY_FENCED",
            successor_amendment_complete=True,
            load=current,
            scheduler_fenced=True,
            successor_old_load_id=load["load_id"],
        )
        return receipt_path
    except BaseException as error:
        o.graph.event(
            directory,
            receipt,
            "SUCCESSOR_FAILED_FENCE_RETAINED",
            status="FAILED",
            failure_type=type(error).__name__,
            failure_message=str(error),
            scheduler_fenced=True,
        )
        raise RuntimeError(
            "Successor stopped; inspect protected original migration receipt"
        ) from error
