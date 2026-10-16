"""Exercise generated Cypher in a disposable Neo4j fixture with no network egress.

No production credentials or databases are read, and no source/model requests
are made. The fixture name is generated here and removed even after failure.
"""

from __future__ import annotations

import json
import subprocess
import time
import uuid
import xml.etree.ElementTree as E
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / "hop/ingestions/jobkorea"


def command(args: list[str], text: str | None = None) -> str:
    result = subprocess.run(args, input=text, text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Fixture command failed")
    return result.stdout


def cypher_literal(value: Any) -> str:
    if isinstance(value, dict):
        return (
            "{"
            + ",".join(
                "`" + key + "`:" + cypher_literal(item)
                for key, item in cast(dict[str, Any], value).items()
            )
            + "}"
        )
    if value is None:
        return "null"
    return json.dumps(value, ensure_ascii=False)


def query_from_file(name: str, transform: str) -> str:
    root = E.parse(OUT / (name + ".hpl")).getroot()
    node = next(node for node in root.findall("transform") if node.findtext("name") == transform)
    return str(node.findtext("cypher"))


def main() -> None:
    container = "jobtology-inferred-graph-fixture-" + uuid.uuid4().hex[:12]
    network = container + "-network"
    checks = 0

    def run(query: str, params: dict[str, Any] | None = None) -> str:
        text = (":param " + cypher_literal(params) + "\n" if params else "") + query + ";\n"
        return command(
            [
                "docker",
                "exec",
                "-i",
                container,
                "cypher-shell",
                "-a",
                "bolt://localhost:7687",
                "-u",
                "neo4j",
                "-p",
                "fixture-password",
                "--format",
                "plain",
                "--non-interactive",
            ],
            text,
        )

    def check(query: str, params: dict[str, Any] | None = None, expected: bool = True) -> None:
        nonlocal checks
        result = run(query, params)
        assert ("true" if expected else "false") in result.lower().splitlines(), result
        checks += 1

    begin = query_from_file("begin_inferred_occupation_graph", "Begin own staging projection")
    load = query_from_file("load_inferred_occupation_graph", "Merge inferred occupation")
    verify = query_from_file("verify_inferred_occupation_graph", "Verify inferred evidence")
    totals = query_from_file("finish_inferred_occupation_graph", "Read only exact totals")
    finish = query_from_file(
        "finish_inferred_occupation_graph", "Finish verified staging projection"
    )
    failure = query_from_file("fail_inferred_occupation_graph", "Mark own projection failed")
    params: dict[str, Any] = {
        "jobs": "fixture-job-run",
        "ncs": "fixture-ncs-run",
        "graph_token": "token-one",
        "projection_id": "fixture-projection",
        "projection_hash": "frozen-hash",
        "expected_count": 1,
        "posting_identity": "source:posting:jobkorea:fixture-posting",
        "occupation_identity": "ncs:occupation:20010202",
        "candidate_id": "candidate-one",
        "payload_json": '{"basis":"METADATA_INFERRED"}',
        "payload_hash": "payload-hash",
        "occupation_code": "20010202",
        "review_status": "UNREVIEWED",
        "confidence_state": "UNASSESSED",
        "accepted": False,
        "result_id": "result-one",
        "bundle_id": "bundle-one",
        "source_hash": "source-hash",
        "binding_hash": "binding-hash",
        "catalog_hash": "catalog-hash",
    }
    try:
        command(["docker", "network", "create", "--internal", network])
        command(
            [
                "docker",
                "run",
                "-d",
                "--pull",
                "never",
                "--name",
                container,
                "--network",
                network,
                "--label",
                "jobtology.test=inferred-graph",
                "-e",
                "NEO4J_AUTH=none",
                "-e",
                "NEO4J_server_memory_heap_initial__size=256m",
                "-e",
                "NEO4J_server_memory_heap_max__size=512m",
                "-e",
                "NEO4J_server_memory_pagecache_size=128m",
                "neo4j:2026.06.0",
            ]
        )
        deadline = time.monotonic() + 120
        while True:
            try:
                run("RETURN true AS ready")
                break
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(2)
        run("""CREATE (p:entity:jobPosting {id:'source:posting:jobkorea:fixture-posting',
kind:'JobPosting',
source_run_id:'newer-job-run',source_facts_sha256:'newer-job-hash'}),
(o:entity:occupation {id:'ncs:occupation:20010202',kind:'Occupation',code:'20010202',
source_run_id:'newer-ncs-run',source_facts_sha256:'newer-ncs-hash'})""")
        # Source run pins and membership are checked in PostgreSQL before this
        # Cypher is reached. Updated live facts must still support the old pin.
        check(begin, params)
        check(load, {**params, "occupation_code": "99999999"}, False)
        check(load, params)
        check(verify, params)
        check(verify, {**params, "payload_hash": "tampered-hash"}, False)
        check(totals, {**params, "expected_count": 2}, False)
        check(totals, params)
        check(finish, params)
        check("""MATCH ()-[r:INFERRED_NCS_OCCUPATION]->()
RETURN count(r)=1 AND all(x IN collect(r) WHERE x.current=true
AND x.review_status='UNREVIEWED' AND x.confidence IS NULL
AND x.confidence_state='UNASSESSED' AND x.accepted=false
AND x.serving_scope='STAGING') AS verified""")
        # Replay uses the same candidate identity instead of adding duplicate edges.
        params["graph_token"] = "token-replay"
        check(begin, params)
        check(load, params)
        check(verify, params)
        check(totals, params)
        check(finish, params)
        check("MATCH ()-[r:INFERRED_NCS_OCCUPATION]->() RETURN count(r)=1 AS verified")
        check(
            "MATCH (n) WHERE n:ingestionBatch OR n:ingestionRecord OR n:archivedRecord "
            "RETURN count(n)=0 AS verified"
        )
        # An excluded/rejected latest result yields an empty current projection.
        params.update(graph_token="token-empty", expected_count=0, projection_hash="empty-hash")
        check(begin, params)
        check(totals, params)
        check(finish, params)
        check("""MATCH ()-[r:INFERRED_NCS_OCCUPATION]->()
RETURN count(r)=1 AND all(x IN collect(r) WHERE x.current=false) AS verified""")
        # A failing token cannot hide another token's marker or relation.
        run("""CREATE (:metadataOccupationProjection {id:'other-projection',
managed_by:'jobtology-metadata-occupation',projection_token:'other-token',state:'VERIFIED'})""")
        check(failure, params)
        check("""MATCH (m:metadataOccupationProjection {id:'other-projection'})
RETURN m.state='VERIFIED' AS verified""")
        check("""MATCH (m:metadataOccupationProjection {id:'fixture-projection'})
RETURN m.state='FAILED' AND m.serving_scope='STAGING' AS verified""")
        check("""OPTIONAL MATCH ()-[r]->()
WHERE type(r) IN ['ALIGNS_WITH_NCS','FOR_OCCUPATION']
RETURN count(r)=0 AS verified""")
        print(
            json.dumps(
                {
                    "status": "PASSED",
                    "checks": checks,
                    "production_writes": 0,
                    "source_requests": 0,
                    "paid_requests": 0,
                }
            )
        )
    finally:
        command(["docker", "rm", "-f", container])
        command(["docker", "network", "rm", network])


if __name__ == "__main__":
    main()
