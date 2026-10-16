"""Check only bounded synthetic cleanup and typed preservation in isolated Neo4j.

This deliberately does not repeat source imports, A/B timings, or the original
99 successful checks. No ports, external networks, provider calls or production
resources are used. All original failed receipts remain unchanged.
"""
# ruff: noqa: E501

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-receipt", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    spec = importlib.util.spec_from_file_location("source_entity_batch_checks", HERE / "source_entity_batches_native.py")
    batches = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(batches)
    name = "jobtology-source-cleanup-" + uuid.uuid4().hex[:12]
    work = Path.home() / ".local/state/jobtology-hop" / name
    work.mkdir(mode=0o700)
    logs = work / "logs"
    logs.mkdir(mode=0o700)
    receipt = {"status": "RUNNING", "scope": "synthetic-cleanup-and-typed-preservation-only", "rows": 60001, "batch_rows": 500, "network": "none", "container_memory_limit": "2g", "no_source_requests": True, "no_paid_calls": True, "production_writes": False, "checks": []}
    volumes = []
    if args.source_receipt:
        data = args.source_receipt.resolve(strict=True).read_bytes()
        prior = json.loads(data)
        receipt["referenced_prior_source_evidence"] = {
            "receipt": str(args.source_receipt.resolve()),
            "sha256": hashlib.sha256(data).hexdigest(),
            "overall_status": prior["status"],
            "passed_checks": len(prior["checks"]),
            "repeated_prior_checks": False,
        }

    def command(args, label, timeout=120):
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        (logs / (label + ".log")).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError("Cleanup fixture failed: " + label + "; protected log " + str(logs / (label + ".log")))
        return result.stdout.strip()

    def neo(query, label):
        rows = command(["docker", "exec", name, "cypher-shell", "-a", "bolt://127.0.0.1:7687", "--format", "plain", query], label).splitlines()
        return rows[-1] if rows else ""

    def check(condition, label):
        if not condition:
            raise AssertionError(label)
        receipt["checks"].append(label)
        print(label + " passed", flush=True)

    def snapshot(label):
        return neo(
            "MATCH (n:entity) WHERE NOT n.id STARTS WITH '" + batches.PREFIX + "' "
            "CALL (n) { UNWIND keys(n) AS k WITH n,k ORDER BY k RETURN collect([k,valueType(n[k]),n[k]]) AS props } "
            "CALL (n) { UNWIND labels(n) AS label WITH label ORDER BY label RETURN collect(label) AS labels } "
            "WITH n,props,labels ORDER BY n.id WITH collect([elementId(n),n.id,labels,props]) AS nodes "
            "MATCH (a)-[r:INFERRED_OCCUPATION]->(b) "
            "CALL (r) { UNWIND keys(r) AS k WITH r,k ORDER BY k RETURN collect([k,valueType(r[k]),r[k]]) AS props } "
            "WITH nodes,collect([elementId(r),a.id,b.id,type(r),props]) AS edges RETURN [nodes,edges]",
            label,
        )

    try:
        image = command(["docker", "image", "inspect", "neo4j:2026.06.0", "--format", "{{.Id}}"], "image")
        receipt["image"] = image
        command(["docker", "run", "-d", "--pull", "never", "--network", "none", "--hostname", "localhost", "--memory", "2g", "--name", name, "-e", "NEO4J_AUTH=none", "-e", "NEO4J_server_memory_heap_initial__size=256m", "-e", "NEO4J_server_memory_heap_max__size=512m", "-e", "NEO4J_server_memory_pagecache_size=256m", image], "boot")
        mounts = json.loads(command(["docker", "inspect", name, "--format", "{{json .Mounts}}"], "fixture-volumes"))
        volumes = [mount["Name"] for mount in mounts if mount["Type"] == "volume"]
        receipt["anonymous_volumes"] = volumes
        for _ in range(90):
            result = subprocess.run(["docker", "exec", name, "cypher-shell", "-a", "bolt://127.0.0.1:7687", "RETURN 1"], capture_output=True, timeout=5)
            (logs / "readiness.log").write_bytes(result.stdout + result.stderr)
            if result.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Isolated Neo4j not ready")
        networks = json.loads(command(["docker", "inspect", name, "--format", "{{json .NetworkSettings.Networks}}"], "network"))
        check(set(networks) == {"none"}, "network-none")
        neo("CREATE CONSTRAINT source_cleanup_entity IF NOT EXISTS FOR (n:entity) REQUIRE n.id IS UNIQUE", "constraint")
        neo("CREATE (p:entity:jobPosting {id:'cleanup-original-posting',kind:'JobPosting',code:'p',name:'대문자 KEEP',source_facts_json:'{\"text\":\"KEEP\",\"nullable\":null}',source_created_at:datetime('2026-10-07T17:48:14Z'),first_ingested_at:datetime('2026-10-08T00:00:00Z'),ingestion_batch_date:date('2026-10-08'),operator_array:['서울','quoted\"value'],operator_dates:[date('2026-10-08'),date('2026-10-11')]}), (o:entity:occupation {id:'cleanup-original-occupation',kind:'Occupation',code:'occ',name:'Occupation KEEP'}), (p)-[:INFERRED_OCCUPATION {candidate_id:'cleanup-protected',review_status:'ASSISTANT_REVIEWED',confidence_basis:'UNASSESSED',lifecycle:'STAGING'}]->(o) RETURN count(*)", "original-business-and-ncs-sentinel")
        before = snapshot("before")
        receipt["original_typed_sha256"] = hashlib.sha256(before.encode()).hexdigest()
        facts = json.dumps({"fixture": "X" * 1024})
        facts_literal = json.dumps(facts)
        fact_hash = hashlib.sha256(facts.encode()).hexdigest()
        query = (
            "UNWIND range(1,60001) AS ordinal "
            "CALL (ordinal) { CREATE (n:entity:qualification {id:'" + batches.PREFIX + "'+toString(ordinal),"
            "kind:'Qualification',code:'fixture-code-'+toString(ordinal),name:'Synthetic KEEP',"
            "name_source_run_id:'fixture-run',name_source_record_id:'fixture-record',source_id:'fixture',"
            "source_run_id:'fixture-run',source_record_id:'fixture-record',source_created_at:datetime('2026-10-07T17:48:14Z'),"
            "source_facts_json:" + facts_literal + ",source_facts_sha256:'" + fact_hash + "'}) } "
            "IN TRANSACTIONS OF 500 ROWS RETURN count(*)"
        )
        check(neo(query, "create-synthetic-bounded") == "60001", "60001-synthetic-rows-created")
        check(snapshot("before-cleanup") == before, "business-and-ncs-preserved-after-create")
        check(neo(batches.SYNTHETIC_CLEANUP_CYPHER, "cleanup-bounded") == "60001", "60001-synthetic-rows-deleted-in-500-row-transactions")
        check(neo("MATCH (n:entity) WHERE n.id STARTS WITH '" + batches.PREFIX + "' RETURN count(n)", "synthetic-count") == "0", "zero-synthetic-targets")
        after = snapshot("after-cleanup")
        check(after == before, "exact-original-ids-labels-properties-types-and-inferred-edge-preserved")
        receipt["after_typed_sha256"] = hashlib.sha256(after.encode()).hexdigest()
        receipt["status"] = "PASSED"
    except Exception:
        receipt["status"] = "FAILED"
        raise
    finally:
        server = subprocess.run(["docker", "logs", name], capture_output=True)
        (logs / "server.log").write_bytes(server.stdout + server.stderr)
        subprocess.run(["docker", "rm", "-fv", name], capture_output=True)
        removed = subprocess.run(["docker", "inspect", name], capture_output=True).returncode != 0
        volumes_removed = all(subprocess.run(["docker", "volume", "inspect", volume], capture_output=True).returncode != 0 for volume in volumes)
        receipt["disposable_container_and_anonymous_volumes_removed"] = removed and volumes_removed
        if not removed or not volumes_removed:
            receipt["status"] = "FAILED"
        (work / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps({"receipt": str(work / "receipt.json"), "status": receipt["status"]}), flush=True)
        if not removed or not volumes_removed:
            raise RuntimeError("Cleanup proof fixture resource removal failed")


if __name__ == "__main__":
    main()
