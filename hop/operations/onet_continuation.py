"""Explicitly pinned continuation scopes; no provider calls or database writes."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import migrate_batchfree_graph as graph
import run_onet_matches as runner


def bound_json(evidence: dict[str, Any]) -> Any:
    path = Path(evidence["path"])
    actual = runner.file_identity(path)
    if actual["sha256"] != evidence["sha256"] or (
        "byte_length" in evidence and actual["byte_length"] != evidence["byte_length"]
    ):
        raise RuntimeError("Pinned continuation evidence bytes changed")
    return json.loads(path.read_bytes())


def source_row(row: dict[str, Any]) -> dict[str, Any]:
    return {"posting_id": row.get("posting_id", row.get("posting_identity")),
            **{key: row[key] for key in ("source_id", "source_run_id", "source_record_id",
                                       "source_facts_sha256")},
            "source_facts": row.get("source_facts", row.get("source_fields"))}


def row_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {source_row(row)["posting_id"]: source_row(row) for row in rows}
    if len(result) != len(rows):
        raise RuntimeError("Duplicate continuation source identity")
    return result


def verify_partition(original: list[dict[str, Any]], current: list[dict[str, Any]],
                     remainder: list[dict[str, Any]], excluded: list[str]) -> None:
    old, live, left = row_map(original), row_map(current), row_map(remainder)
    if len(excluded) != len(set(excluded)) or not set(excluded) <= set(old):
        raise RuntimeError("Invalid or duplicate predecessor selection")
    if set(live) != set(old) or set(left) != set(old) - set(excluded):
        raise RuntimeError("Continuation must partition the exact original posting scope")
    for identity, row in left.items():
        if runner.canonical(row) != runner.canonical(live[identity]):
            raise RuntimeError("Continuation source facts/provenance differ from current snapshot")


def verify_current_snapshot(original: list[dict[str, Any]], current: list[dict[str, Any]],
                            arrivals: list[dict[str, Any]],
                            live_rows: list[dict[str, Any]]) -> None:
    live, old, current_map, arrivals_map = (row_map(value) for value in
                                          (live_rows, original, current, arrivals))
    if (set(live) != set(old) | set(arrivals_map) or
        any(runner.canonical(row) != runner.canonical(live.get(identity))
            for mapping in (current_map, arrivals_map) for identity, row in mapping.items())):
        raise RuntimeError("Continuation current evidence differs from independent graph snapshot")


def load_proof(path: Path, expected_sha256: str) -> dict[str, Any]:
    proof = bound_json({"path": str(path), "sha256": expected_sha256})
    if (proof.get("status") != "DERIVED_CURRENT_ORIGINAL_REMAINDER_COHORT" or
        proof.get("contract_version") != "onet-metadata-continuation-v1"):
        raise RuntimeError("Unsupported continuation scope proof")
    proof["task_predecessor"] = proof["predecessor_task_id"]
    proof["original_manifest"] = proof["predecessor_manifest"]
    proof["current_graph_assessment"] = proof["assessment"]
    proof["continuation_source_export"] = dict(proof["source_export"],
        count=proof["continuation_input_count"], source_counts=proof["counts"])
    if not proof.get("checks") or not all(value is True for value in proof["checks"].values()):
        raise RuntimeError("Continuation scope proof has failed checks")
    runner.identity(proof["task_predecessor"])
    original = bound_json(proof["original_source_export"])
    current = bound_json(proof["current_original_cohort"])
    remainder = bound_json(proof["continuation_source_export"])
    selection = bound_json(proof["completed_selection"])
    excluded = selection if isinstance(selection, list) else selection["posting_ids"]
    counts = proof["continuation_source_export"]["source_counts"]
    runner.check_cohort(original)
    runner.check_cohort(current)
    runner.check_cohort(remainder, counts)
    if (len(original), len(excluded), len(remainder)) != (
        proof["original_input_count"], proof["completed_selection"]["count"],
        proof["continuation_source_export"]["count"]
    ) or len(original) != len(excluded) + len(remainder):
        raise RuntimeError("Continuation scope counts disagree with retained evidence")
    verify_partition(original, current, remainder, excluded)
    # The original manifest is hash checked without loading its large request array.
    original_identity = runner.file_identity(Path(proof["original_manifest"]["path"]))
    if original_identity["sha256"] != proof["original_manifest"]["sha256"]:
        raise RuntimeError("Original predecessor manifest changed")
    assessment = bound_json(proof["current_graph_assessment"])
    if (assessment.get("status") != "VERIFIED_FROZEN_COHORT_DRIFT_ASSESSMENT" or
        assessment.get("task_id") != proof["task_predecessor"] or
        assessment.get("source_cohort_sha256") != proof["original_source_export"]["sha256"] or
        not all(value is True for value in assessment.get("checks", {}).values()) or
        not assessment.get("checks")):
        raise RuntimeError("Current graph assessment does not back the continuation")
    arrivals = bound_json(proof["excluded_later_arrivals"])
    arrival_ids = {row.get("posting_id", row.get("posting_identity")) for row in arrivals}
    if (len(arrivals) != proof["excluded_later_arrivals"]["count"] or
        len(arrival_ids) != len(arrivals) or arrival_ids & set(row_map(original)) or
        arrival_ids & set(row_map(remainder))):
        raise RuntimeError("Later source arrivals must remain outside the original cohort")
    live_rows, _ = current_sources(Path(proof["assessment"]["path"]),
        proof["assessment"]["sha256"], proof["original_source_export"]["sha256"],
        proof["original_contract"]["database_id"])
    verify_current_snapshot(original, current, arrivals, live_rows)
    proof["_excluded_ids"] = excluded
    proof["_counts"] = counts
    proof["_rows"] = remainder
    return proof


def verify_contract(proof: dict[str, Any], settings: dict[str, Any],
                    code: dict[str, Any], task_id: str, release_id: str,
                    database_id: str) -> None:
    original = proof["original_contract"]
    contract = proof.get("authorized_contract", original)
    if (contract["release_id"], contract["database_id"]) != (
        original["release_id"], original["database_id"]
    ):
        raise RuntimeError("Continuation successor changed catalogue/database")
    if "authorized_contract" in proof:
        qualification = bound_json(proof["contract_qualification"])
        if qualification.get("status") != "QUALIFIED_CONTINUATION_CONTRACT" or (
            runner.canonical(qualification.get("authorized_contract")) != runner.canonical(contract)
        ):
            raise RuntimeError("Continuation contract successor is not explicitly qualified")
        variable = {"prompt_hash", "request_hash", "prompt_file_sha256", "retrieval_hash",
                    "lexicon_file_sha256", "hint_hash", "admission_policy_sha256",
                    "admission_policy_version", "physician_eligibility_policy_sha256",
                    "physician_eligibility_policy_version"}
        if ({key: value for key, value in original["settings"].items() if key not in variable} !=
            {key: value for key, value in contract["settings"].items() if key not in variable}):
            raise RuntimeError("Continuation successor changed model/routing/schema/accounting")
    clean_settings = {key: value for key, value in settings.items()
                      if key not in ("continuation_proof_sha256", "predecessor_task_id")}
    if (task_id == proof["task_predecessor"] or
        task_id != proof["continuation_task_id"] or
        release_id != contract["release_id"] or database_id != contract["database_id"] or
        runner.canonical(clean_settings) != runner.canonical(contract["settings"]) or
        runner.canonical(code) != runner.canonical(contract["code_artifacts"])):
        raise RuntimeError("Continuation changed the explicitly retained inference contract")


def verify_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    evidence = manifest["continuation_proof"]
    proof = load_proof(Path(evidence["path"]), evidence["sha256"])
    verify_partition(bound_json(proof["original_source_export"]),
                     bound_json(proof["current_original_cohort"]), manifest["rows"],
                     proof["_excluded_ids"])
    if (manifest["counts"] != proof["_counts"] or
        manifest["source_export"]["sha256"] != proof["continuation_source_export"]["sha256"] or
        manifest["settings"].get("continuation_proof_sha256") != evidence["sha256"] or
        manifest["settings"].get("predecessor_task_id") != proof["task_predecessor"]):
        raise RuntimeError("Frozen continuation manifest differs from its scope proof")
    verify_contract(proof, manifest["settings"], manifest["code_artifacts"],
                    manifest["task_id"], manifest["release_id"], manifest["database_id"])
    return proof


def require_terminal_predecessor(pg: str, manifest: dict[str, Any]) -> dict[str, Any]:
    proof = verify_manifest(manifest)
    task = runner.identity(proof["task_predecessor"])
    snapshot = runner.sql_json(pg, "jsonb_build_object('task',onet_matching.task_status('" +
        task + "'),'attempts',(SELECT coalesce(jsonb_agg(jsonb_build_object(" +
        "'posting_identity',posting_identity,'state',state,'reserved_at',reserved_at," +
        "'cost_usd',cost_usd,'is_byok',is_byok) ORDER BY posting_identity),'[]'::jsonb) " +
        "FROM onet_matching.attempt WHERE task_id='" + task + "'))")
    validate_terminal(snapshot, proof["_excluded_ids"])
    return snapshot


def validate_terminal(snapshot: dict[str, Any], expected_ids: list[str]) -> None:
    task = snapshot["task"]
    attempts = snapshot["attempts"]
    if (task.get("state") != "STOPPED" or
        task.get("unknown_requests", task.get("unknown_holds", 0)) or
        len(attempts) != len(expected_ids) or
        {row["posting_identity"] for row in attempts} != set(expected_ids)):
        raise RuntimeError("Predecessor must be stopped with the exact terminal selection")
    for row in attempts:
        if row["state"] not in ("VALIDATED", "REJECTED", "SKIPPED") or (
            row["state"] == "SKIPPED" and row["reserved_at"] is not None
        ) or (row["reserved_at"] is not None and (
            row["cost_usd"] is None or row["is_byok"] is not True
        )) or (row["state"] != "SKIPPED" and row["reserved_at"] is None):
            raise RuntimeError("Unsent, failed, unknown-charge or non-BYOK predecessor remains")


def current_sources(assessment_path: Path, sha256: str, original_sha256: str,
                    database_id: str) -> tuple[list[dict[str, Any]], list[int]]:
    assessment = bound_json({"path": str(assessment_path), "sha256": sha256})
    if (assessment.get("status") != "VERIFIED_FROZEN_COHORT_DRIFT_ASSESSMENT" or
        assessment.get("source_cohort_sha256") != original_sha256 or
        assessment["counts"]["database_id"] != database_id or
        not assessment.get("checks") or
        not all(value is True for value in assessment["checks"].values())):
        raise RuntimeError("Independent current-source assessment is not qualified")
    evidence = assessment["artifacts"]["postrefresh-current-source.csv"]
    csv_path = assessment_path.parent / "postrefresh-current-source.csv"
    if runner.file_identity(csv_path) != evidence:
        raise RuntimeError("Current-source snapshot changed")
    sources = []
    seen_count = False
    counts = assessment["counts"]
    with csv_path.open(newline="", encoding="utf8") as stream:
        for columns in csv.reader(stream):
            if len(columns) != 1:
                raise RuntimeError("Unexpected current-source native snapshot row")
            if columns[0].startswith("COUNT"):
                values = graph.unpack(columns[0][5:])
                if seen_count or values != [str(counts[key]) for key in
                    ("nodes", "relationships", "ncs_edges", "onet_edges", "database_id")]:
                    raise RuntimeError("Current-source snapshot counts/database differ")
                seen_count = True
                continue
            if not columns[0].startswith("SOURCE"):
                raise RuntimeError("Unexpected current-source native snapshot signature")
            posting, source, kind, run, record, facts_hash, facts, label = graph.unpack(
                columns[0][6:])
            if kind != "JobPosting" or label != "true":
                raise RuntimeError("Current source snapshot lost a posting kind/label")
            sources.append({"posting_id": posting, "source_id": source, "source_run_id": run,
                            "source_record_id": record, "source_facts_sha256": facts_hash,
                            "source_facts": json.loads(facts)})
    if not seen_count or len(row_map(sources)) != sum(assessment["current_source_counts"].values()):
        raise RuntimeError("Incomplete current-source snapshot")
    runner.check_cohort(sources, assessment["current_source_counts"])
    return sources, [counts["nodes"], counts["relationships"], counts["ncs_edges"]]
