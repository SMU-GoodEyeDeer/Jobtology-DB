#!/usr/bin/env python3
"""Read protected native logs without changing the original benchmark receipt."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_archived_routine import parse_workflow, sha
from prepare_performance_readback import transform_counters, verifier_counters
from profile_archived_postgres import write_json

OWNERS = ("clear_source_edges", "verify_totals")
ACCEPTED = ("warm-baseline", "warm-1-candidate", "warm-2-baseline")


def owner_counters(log: str, pipeline: str, expected: int, batch: int) -> dict:
    finishes = list(re.finditer(r"\s" + re.escape(pipeline)
                               + r"\s*-\s*Pipeline duration\s*:", log))
    if len(finishes) != 1:
        raise RuntimeError("Owner pipeline section missing or ambiguous")
    end = finishes[0].start()
    start = log.rfind("Pipeline duration", 0, end)
    section = log[max(0, start):end]
    reader = transform_counters(section, "Read entity names")
    if reader["W"] != expected:
        raise RuntimeError("Owner reader count differs from frozen SQL scope")
    counts = verifier_counters(section, dict(batch_size=str(batch),
        operation_name="Set entity names", filter_name="Check result",
        success_name="Complete"), expected)
    return dict(reader=reader, batch_size=batch, final_batch_rows=expected % batch or batch,
                **counts)


def qualify(path: Path, acceptance: Path | None, output: Path) -> None:
    if output.exists():
        raise FileExistsError("Never overwrite a qualification receipt")
    receipt = json.loads(path.read_text())
    if receipt["kind"] != "BORROWED_NETWORK_NONE_NATIVE_GRAPH_COSTS":
        raise RuntimeError("Unexpected native receipt kind")
    work = path.parent
    samples = []
    for sample in receipt["samples"]:
        if sample["result"] != "PASSED":
            raise RuntimeError("A recorded native workflow failed")
        log_path = work / "logs" / (sample["label"] + ".log")
        log = log_path.read_text()
        parsed = parse_workflow(log)
        if parsed["pipeline_seconds"] != sample["pipeline_seconds"]:
            raise RuntimeError("Native log durations differ from original receipt")
        counters = {}
        for name in OWNERS:
            artifact = work / (("baseline-" if sample["variant"] == "baseline"
                               else "transport-") + name + ".hpl")
            batch = int(ET.parse(artifact).getroot().findtext(
                "transform[type='Neo4jCypherOutput']/batch_size"))
            expected_hash = (receipt["transport_baseline_sha256"][name]
                if sample["variant"] == "baseline"
                else receipt["candidate_artifact_sha256"]["graph/" + name + ".hpl"])
            if sha(artifact) != expected_hash:
                raise RuntimeError("Frozen owner pipeline hash differs")
            counters[name] = dict(artifact_sha256=expected_hash,
                **owner_counters(log, name, receipt["expected_rows"]["owners"], batch))
        samples.append(dict(label=sample["label"], variant=sample["variant"],
            wall_seconds=sample["wall_seconds"], pipeline_seconds=sample["pipeline_seconds"],
            log_path=str(log_path), log_sha256=sha(log_path), owner_counters=counters,
            accepted_for_gain=sample["label"] in ACCEPTED))
    accepted = [s for s in samples if s["label"] in ACCEPTED]
    if {s["label"] for s in accepted} != set(ACCEPTED):
        raise RuntimeError("Required clean B/C/B timings absent")
    gains = {}
    for key in ("wall_seconds", *OWNERS):
        def value(s, key=key):
            return s[key] if key == "wall_seconds" else s["pipeline_seconds"][key]
        baseline = mean(value(s) for s in accepted if s["variant"] == "baseline")
        candidate = mean(value(s) for s in accepted if s["variant"] == "candidate")
        gains[key] = dict(baseline_mean=baseline, candidate=candidate,
                          decrease_percent=100 * (baseline - candidate) / baseline)
    graph = {}
    for kind in ("nodes", "edges", "scaffold", "inferred_element_ids"):
        paths = [work / "logs" / (prefix + "-" + kind + ".log") for prefix in (
            "graph-before", "owner-boundary-original", "owner-boundary-restored")]
        if len({p.read_bytes() for p in paths}) != 1:
            raise RuntimeError("Exact Nara graph preservation logs differ")
        graph[kind] = [dict(path=str(p), sha256=sha(p)) for p in paths]
    for key in ("owned_native_resources_removed", "private_scratch_removed",
                "borrowed_container_id_preserved_and_none_restored",
                "borrowed_database_timeout_restored"):
        if receipt.get(key) is not True:
            raise RuntimeError("Original fixture cleanup/isolation failed")
    if receipt.get("cleanup_failures"):
        raise RuntimeError("Original fixture cleanup errors")
    result = dict(status="TIMING_COUNTERS_AND_NARA_GRAPH_QUALIFIED_PENDING_ACCEPTANCE",
        kind="NATIVE_OWNER_TRANSPORT_READBACK", raw_receipt_path=str(path),
        raw_receipt_sha256=sha(path), raw_receipt_status=receipt["status"],
        launched_helper_sha256=sha(Path(__file__)), samples=samples, gains=gains,
        graph_preservation=graph, candidate_artifact_sha256=receipt["candidate_artifact_sha256"],
        exclusion=dict(label="warm-0-candidate", reason="Own host-only nested-log parser "
            "occupied one CPU during this sample; it made no database requests. Exact "
            "termination timestamp was not recorded. Sample preserved and excluded.",
            pid=821799), limits=["Two clean baseline samples and one clean candidate sample; "
            "no balanced ABBA or production-capacity claim.", "Raw failed receipt remains "
            "FAILED: its empty-owner oracle parser expected omitted zero-input summaries."])
    if acceptance:
        proof = json.loads(acceptance.read_text())
        recovered = proof.get("recovered_nara_preservation", {})
        if (proof["status"] != "PASSED_NATIVE_GRAPH_COSTS_COMPLETE_CLEANUP"
            or not proof.get("disposable_resources_removed")
            or proof.get("proof_before") != proof.get("proof_after")
            or proof.get("owner_batch_independent_correctness", {}).get("status") != "PASSED"
            or recovered.get("prior_receipt_sha256") != sha(path)
            or not recovered.get("all_protected_tables_equal")
            or not recovered.get("complete_source_proof_equal")
            or recovered.get("proof") != receipt["proof_before"]
            or proof.get("fresh_compatibility", {}).get("counts") != dict(
                ready="READY", records=3, issues=0, requests=0, proof_equal=True)
            or proof["run_id"] != "18cb0086-5800-4a2b-870f-db8d74c62fbf"
            or proof["expected_rows"]["edges"] <= 0
            or proof["borrowed_postgres"] != receipt["borrowed_postgres"]
            or proof["candidate_artifact_sha256"] != receipt["candidate_artifact_sha256"]):
            raise RuntimeError("Final independent compatibility/cleanup acceptance absent")
        result.update(status="QUALIFIED_WITH_INDEPENDENT_ACCEPTANCE_AND_COMPLETE_CLEANUP",
                      acceptance_path=str(acceptance), acceptance_sha256=sha(acceptance))
        identity_paths = [work / "logs/borrowed-pg-inspect.log",
                          acceptance.parent / "logs/borrowed-pg-inspect.log"]
        reused = proof.get("reused_native_installer_proof")
        if reused:
            previous = Path(reused["path"])
            if sha(previous) != reused["sha256"]:
                raise RuntimeError("Referenced native installer proof changed")
            identity_paths.append(previous.parent / "logs/borrowed-pg-inspect.log")
        identities = [json.loads(p.read_text())["Id"] for p in identity_paths]
        if len(set(identities)) != 1:
            raise RuntimeError("Actual PostgreSQL container identity changed")
        result["actual_postgres_identity_preserved"] = dict(container_id=identities[0],
            inspect_logs=[dict(path=str(p), sha256=sha(p)) for p in identity_paths])
        post_path = acceptance.parent / "post-native-nara-readback.json"
        post = json.loads(post_path.read_text())
        if (post.get("status") != "PASSED" or not post.get("authoritative_assert_passed")
            or not post.get("complete_manifest_equal")
            or post.get("proof") != receipt["proof_before"]
            or post["prior_receipt_sha256"] != sha(path)
            or post["container_id"] != identities[0]
            or post["acceptance_receipt_sha256"] !=
                proof.get("native_receipt_sha256_before_cleanup_seal")):
            raise RuntimeError("Post-native exact Nara authoritative proof differs")
        for suffix, field in (("sql", "sql_sha256"), ("log", "log_sha256")):
            if sha(acceptance.parent / ("post-native-nara-readback." + suffix)) != post[field]:
                raise RuntimeError("Post-native Nara statement/log changed")
        result["post_native_nara_authoritative_proof"] = dict(
            path=str(post_path), sha256=sha(post_path))
        compatibility = []
        for sample in proof["samples"]:
            log_path = acceptance.parent / "logs" / (sample["label"] + ".log")
            log = log_path.read_text()
            if (sample["result"] != "PASSED" or sample["variant"] != "candidate"
                or parse_workflow(log)["pipeline_seconds"] != sample["pipeline_seconds"]):
                raise RuntimeError("Full JOBALIO native compatibility log differs")
            compatibility.append(dict(label=sample["label"], log_sha256=sha(log_path),
                owner_counters={name: owner_counters(log, name,
                    proof["expected_rows"]["owners"], 500) for name in OWNERS}))
        if {s["label"] for s in compatibility} != {"prime", "warm-candidate"}:
            raise RuntimeError("Full JOBALIO prime and warm compatibility must both pass")
        result["full_jobalio_native_owner_counters"] = compatibility
    os.umask(0o077)
    write_json(output, result)
    output.chmod(0o400)
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--acceptance", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    qualify(args.receipt, args.acceptance, args.output)
