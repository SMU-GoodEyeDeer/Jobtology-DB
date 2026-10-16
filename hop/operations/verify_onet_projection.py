#!/usr/bin/env python3
"""Read-only independent source/owned-O*NET graph acceptance via native Hop."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import load_onet_catalogue as catalogue
import migrate_batchfree_graph as graph
import onet_continuation as continuation
import run_onet_matches as runner

BASE_NODES = 202889
BASE_EDGES = 755236
NCS_EDGES = 5878
OWNER = "jobtology-onet-matching-v1"
EDGE_PREFIX = "urn:jobtology:inferred-onet-occupation:"


def query() -> str:
    frame = graph.framed
    counts = "+".join(frame("toString(" + key + ")") for key in ("nodes", "edges", "ncs"))
    counts += "+" + frame("database_id")
    source = "+".join(frame("coalesce(n." + key + ",'')") for key in (
        "id", "source_id", "source_run_id", "source_record_id", "source_facts_sha256",
        "source_facts_json"))
    edge = "+".join(frame(value) for value in (
        "coalesce(r.id,'')", "type(r)", "coalesce(a.id,'')", "coalesce(b.id,'')",
        "toString(endpoints_valid)", "property_signature"))
    return f"""CALL db.info() YIELD id AS database_id
CALL () {{ MATCH(n) RETURN count(n) AS nodes }}
CALL () {{ MATCH()-[r]->() RETURN count(r) AS edges }}
CALL () {{ MATCH()-[r]->() WHERE type(r)='INFERRED_NCS_OCCUPATION'
 RETURN count(r) AS ncs }}
RETURN 'COUNT'+{counts} AS signature
UNION ALL
MATCH(n:entity:jobPosting) WHERE n.kind='JobPosting'
 AND n.source_id IN ['jobkorea','nara_job','job_alio']
 AND n.source_facts_json IS NOT NULL AND n.source_facts_sha256 IS NOT NULL
RETURN 'SOURCE'+{source} AS signature
UNION ALL
MATCH(a)-[r]->(b) WHERE type(r)='INFERRED_ONET_OCCUPATION' OR
 r.managed_by='{OWNER}' OR coalesce(r.id,'') STARTS WITH '{EDGE_PREFIX}'
WITH a,r,b,a:entity AND a:jobPosting AND a.kind='JobPosting' AND
 r.source_facts_sha256=a.source_facts_sha256 AND b:entity AND b:onetCatalogObject AND
 b:occupation AND b.managed_by='jobtology-onet-catalog-v1' AND b.current=true AND
 b.scheme_id='ONET' AND r.occupation_code=b.code AND r.release_id=b.release_id AND
 r.occupation_content_hash=b.content_hash AS endpoints_valid
{graph.dates.signature_expression('r', '[]')}
RETURN 'EDGE'+{edge} AS signature"""


def typed_property(value: Any) -> list[str]:
    if isinstance(value, bool):
        return ["BOOLEAN NOT NULL", "true" if value else "false"]
    if isinstance(value, int):
        return ["INTEGER NOT NULL", str(value)]
    if isinstance(value, str):
        return ["STRING NOT NULL", value]
    raise RuntimeError("Unexpected PostgreSQL owned graph property type")


def verify_rows(rows: list[str], sources: list[dict[str, Any]], plan: list[dict[str, Any]],
                unpublished: bool, database_id: str,
                baseline_counts: list[int] | None = None) -> dict[str, Any]:
    expected_sources = {row.get("posting_id", row.get("posting_identity")): row for row in sources}
    expected_edges = {} if unpublished else {row["edge_id"]: row for row in plan}
    if len(expected_sources) != len(sources) or (
        not unpublished and len(expected_edges) != len(plan)
    ):
        raise RuntimeError("Duplicate expected source or owned edge scope")
    seen_sources: set[str] = set()
    seen_edges: set[str] = set()
    counts = None
    reviews: dict[str, int] = {}
    for row in rows:
        if row.startswith("COUNT"):
            if counts is not None:
                raise RuntimeError("Duplicate graph count result")
            values = graph.unpack(row[5:])
            if len(values) != 4 or values[3] != database_id:
                raise RuntimeError("Independent Neo4j database identity differs from frozen target")
            counts = [int(value) for value in values[:3]]
        elif row.startswith("SOURCE"):
            identity, source_id, run_id, record_id, facts_hash, facts = graph.unpack(row[6:])
            source = expected_sources.get(identity)
            if source is None or identity in seen_sources:
                raise RuntimeError("Foreign or duplicate source posting")
            if (source_id, run_id, record_id, facts_hash, runner.canonical(json.loads(facts))) != (
                source["source_id"], source["source_run_id"], source["source_record_id"],
                source["source_facts_sha256"],
                runner.canonical(source.get("source_facts", source.get("source_fields")))
            ):
                raise RuntimeError("Frozen source posting provenance/facts changed")
            seen_sources.add(identity)
        elif row.startswith("EDGE"):
            identity, kind, posting, occupation, endpoints_valid, signature = graph.unpack(row[4:])
            expected = expected_edges.get(identity)
            if expected is None or identity in seen_edges:
                raise RuntimeError("Foreign, duplicate or unexpected owned O*NET edge")
            if (kind, posting, occupation, endpoints_valid) != (
                "INFERRED_ONET_OCCUPATION", expected["posting_identity"],
                expected["occupation_identity"], "true"
            ):
                raise RuntimeError("Owned O*NET endpoints/types/catalogue backing differ")
            actual = graph.properties(signature)
            properties = {key: typed_property(value)
                          for key, value in expected["properties"].items()
                          if value is not None}
            if actual != properties:
                raise RuntimeError("Owned O*NET typed properties differ from exact PostgreSQL plan")
            # These independent checks retain the inference boundary even if a
            # future SQL plan accidentally introduces an assessed confidence.
            if "confidence" in actual or properties.get("managed_by") != (
                ["STRING NOT NULL", OWNER]
            ) or properties.get("confidence_state") != (
                ["STRING NOT NULL", "UNASSESSED"]
            ) or properties.get("stage") != ["STRING NOT NULL", "STAGING"]:
                raise RuntimeError("Owned O*NET confidence or lifecycle boundary differs")
            review = expected["properties"]["review_status"]
            if review not in ("UNREVIEWED", "ASSISTANT_REVIEWED", "HUMAN_REVIEWED"):
                raise RuntimeError("Unexpected actual review status")
            reviews[review] = reviews.get(review, 0) + 1
            seen_edges.add(identity)
        else:
            raise RuntimeError("Unexpected independent graph row")
    if seen_sources != set(expected_sources) or seen_edges != set(expected_edges):
        raise RuntimeError("Frozen source or owned graph scope is incomplete")
    baseline = baseline_counts or [BASE_NODES, BASE_EDGES, NCS_EDGES]
    if counts != [baseline[0], baseline[1] + len(expected_edges), baseline[2]]:
        raise RuntimeError("Legacy node/relationship/NCS baseline counts changed")
    return {"database_id": database_id, "nodes": counts[0], "relationships": counts[1],
            "ncs_edges": counts[2],
            "frozen_source_postings": len(seen_sources), "owned_onet_edges": len(seen_edges),
            "review_states": reviews, "expect_unpublished": unpublished}


def completed_coverage(attempts: list[dict[str, Any]], original_ids: set[str],
                       complete: bool) -> dict[str, Any]:
    seen: set[str] = set()
    counts: dict[str, int] = {}
    for row in attempts:
        posting = row["posting_identity"]
        if posting not in original_ids or posting in seen:
            raise RuntimeError("Combined tasks repeat a posting or include a later arrival")
        if row["state"] not in ("VALIDATED", "REJECTED", "SKIPPED") or (
            row["state"] == "SKIPPED" and row["reserved_at"] is not None
        ) or (row["state"] != "SKIPPED" and (
            row["reserved_at"] is None or row["cost_usd"] is None or row["is_byok"] is not True
        )):
            raise RuntimeError("Combined task scope has unfinished or unsafe accounting")
        seen.add(posting)
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    if complete and seen != original_ids:
        raise RuntimeError("Combined completed outcomes do not cover the exact original cohort")
    return {"completed_source_postings": len(seen), "scope_complete": seen == original_ids,
            "states": counts}


def execute(args: argparse.Namespace) -> None:
    os.umask(0o077)
    manifest = runner.manifest_inputs(args.manifest)
    original_sources = json.loads(Path(manifest["source_export"]["path"]).read_bytes())
    manifest.pop("rows")  # The requests have passed validation; avoid holding two large arrays.
    manifests = [manifest]
    manifest_paths = [args.manifest]
    continuation_proofs = []
    for path in getattr(args, "additional_manifest", []):
        value = runner.manifest_inputs(path)
        if "continuation_proof" not in value:
            raise RuntimeError("Additional graph tasks require an explicitly pinned continuation")
        proof = continuation.verify_manifest(value)
        if proof["task_predecessor"] != manifest["task_id"]:
            raise RuntimeError("Additional task is not a continuation of the original task")
        proof.pop("_rows")
        continuation_proofs.append(proof)
        value.pop("rows")
        manifests.append(value)
        manifest_paths.append(path)
    if len({value["task_id"] for value in manifests}) != len(manifests):
        raise RuntimeError("Duplicate task in combined projection scope")
    sources, baseline = original_sources, None
    assessment_path = getattr(args, "postrefresh_assessment", None)
    if assessment_path is not None:
        sources, baseline = continuation.current_sources(
            assessment_path, args.assessment_sha256, manifest["source_export"]["sha256"],
            manifest["database_id"])
    with runner.operation_lock():
        runtime = runner.common.containers()
        runner.common.idle_cli(runtime["hop"])
        directory = runner.new_directory("independent-graph-acceptance")
        path = directory / "receipt.json"
        receipt = {"status": "RUNNING", "started_at": runner.now(),
                   "task_id": manifest["task_id"],
                   "task_ids": [value["task_id"] for value in manifests],
                   "manifest_identity": runner.file_identity(args.manifest),
                   "manifests": [{"path": str(path), "task_id": value["task_id"],
                                  **runner.file_identity(path)}
                                 for path, value in zip(manifest_paths, manifests, strict=True)],
                   "database_writes": 0, "provider_calls": 0, "runtime": runtime}
        if assessment_path is not None:
            receipt["postrefresh_assessment"] = {"path": str(assessment_path),
                                                 **runner.file_identity(assessment_path)}
        runner.write_json(path, receipt)
        try:
            task = runner.identity(manifest["task_id"])
            initial_state = runner.runtime_state(runtime["pg"], task)
            runner.require_idle(initial_state)
            if continuation_proofs and initial_state["task"].get("state") != "STOPPED":
                raise RuntimeError("Combined projection predecessor is not durably stopped")
            runner.sql(runtime["pg"], "BEGIN READ ONLY; SET LOCAL statement_timeout='30s'; " +
                "SELECT onet_matching.assert_catalog('" + runner.identity(manifest["release_id"]) +
                "','" + runner.identity(manifest["database_id"]) + "'); COMMIT;")
            plan = []
            attempts = []
            guards = []
            for value in manifests:
                current_task = runner.identity(value["task_id"])
                if (value["release_id"], value["database_id"]) != (
                    manifest["release_id"], manifest["database_id"]
                ):
                    raise RuntimeError("Combined task catalogue/database pins differ")
                snapshot = runner.sql_json(runtime["pg"], "jsonb_build_object('plan'," +
                    "(SELECT coalesce(jsonb_agg(to_jsonb(g)),'[]'::jsonb) FROM " +
                    "onet_matching.graph_rows('" + current_task + "') g),'attempts'," +
                    "(SELECT coalesce(jsonb_agg(jsonb_build_object('posting_identity'," +
                    "posting_identity,'state',state,'reserved_at',reserved_at," +
                    "'cost_usd',cost_usd," +
                    "'is_byok',is_byok)),'[]'::jsonb) FROM onet_matching.attempt WHERE task_id='" +
                    current_task + "'),'guard',(SELECT to_jsonb(g) FROM " +
                    "onet_matching.graph_guard g " +
                    "WHERE task_id='" + current_task + "' ORDER BY started_at DESC LIMIT 1))")
                plan.extend(snapshot["plan"])
                attempts.extend(snapshot["attempts"])
                guards.append(snapshot["guard"])
                if current_task == task:
                    for proof in continuation_proofs:
                        continuation.validate_terminal({"task": initial_state["task"],
                                                        "attempts": snapshot["attempts"]},
                            proof["_excluded_ids"])
            if assessment_path is not None:
                receipt["coverage"] = completed_coverage(
                    attempts, set(continuation.row_map(original_sources)),
                    complete=not args.expect_unpublished)
            runner.write_json(directory / "postgresql-plan.json", plan, immutable=True)
            with catalogue.scalar_snapshot_adapter():
                rows = graph.native_rows(runtime["hop"], query(), directory,
                                         "independent-owned-scope")
            receipt["result"] = verify_rows(rows, sources, plan, args.expect_unpublished,
                                            manifest["database_id"], baseline)
            if assessment_path is not None:
                receipt["result"]["current_source_postings"] = len(sources)
                receipt["result"]["frozen_source_postings"] = len(original_sources)
            receipt["task"] = runner.runtime_state(runtime["pg"], task)["task"]
            if not args.expect_unpublished:
                receipt["publications"] = []
                for value, guard in zip(manifests, guards, strict=True):
                    if not guard or guard["state"] != "VERIFIED":
                        raise RuntimeError("Exact graph publication checkpoint is not VERIFIED")
                    state = runner.publication_state(runtime["pg"], guard["publication_id"],
                                                     value["task_id"])
                    runner.require_publication(state, guard["publication_id"], value["task_id"],
                                               value["database_id"])
                    receipt["publications"].append(state)
            receipt["status"] = "VERIFIED_INDEPENDENT_ONET_GRAPH"
        except BaseException as exc:
            receipt["status"] = "FAILED"
            receipt["error"] = str(exc)
            raise
        finally:
            receipt["finished_at"] = runner.now()
            runner.write_json(path, receipt)
            print(json.dumps({"status": receipt["status"], "receipt": str(path),
                              "result": receipt.get("result")}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--expect-unpublished", action="store_true")
    parser.add_argument("--postrefresh-assessment", type=Path)
    parser.add_argument("--assessment-sha256")
    parser.add_argument("--additional-manifest", type=Path, action="append", default=[])
    args = parser.parse_args()
    if args.postrefresh_assessment is not None and not runner.SHA256.fullmatch(
        args.assessment_sha256 or ""
    ):
        parser.error("--postrefresh-assessment requires its exact --assessment-sha256")
    if args.additional_manifest and args.postrefresh_assessment is None:
        parser.error("Combined task verification requires an explicitly pinned current assessment")
    if args.assessment_sha256 is not None and args.postrefresh_assessment is None:
        parser.error("--assessment-sha256 requires --postrefresh-assessment")
    execute(args)


if __name__ == "__main__":
    main()
