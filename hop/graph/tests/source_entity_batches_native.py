"""Native entity batching checks using only an existing isolated fixture.

Run batchfree_native.py --entity-batches-only. SOURCE_ENTITY_BASELINE optionally points
to a protected pre-change hop/graph directory for exact native A/B measurements.
Timing rows copy the fixture's real eight-source selected facts, but use unique
synthetic IDs/codes; they measure transport, not full source-history selection.
"""
# ruff: noqa: E501

import hashlib
import os
import re
import time
import xml.etree.ElementTree as E
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PREFIX = "fixture:source:entity:"
SYNTHETIC_CLEANUP_CYPHER = (
    "MATCH (n:entity) WHERE n.id STARTS WITH '" + PREFIX + "' "
    "CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 500 ROWS RETURN count(*)"
)


def run(fixture):
    def neo(query, label):
        result = fixture.command(
            ["docker", "exec", fixture.neo, "cypher-shell", "--format", "plain", query],
            label,
        ).splitlines()[-1]
        return result.lower() if result in {"TRUE", "FALSE"} else result

    def graph_state(label):
        return neo(
            "MATCH (n:entity) WHERE n.id STARTS WITH '" + PREFIX + "' "
            "CALL (n) { UNWIND keys(n) AS k WITH n,k ORDER BY k "
            "RETURN collect([k,valueType(n[k]),n[k]]) AS props } "
            "CALL (n) { UNWIND labels(n) AS label WITH label ORDER BY label "
            "RETURN collect(label) AS labels } "
            "WITH n,props,labels ORDER BY n.id "
            "RETURN collect([elementId(n),n.id,labels,props])",
            label,
        )

    before = neo(
        "MATCH (n:entity) WITH n ORDER BY n.id RETURN collect([elementId(n),n.id,properties(n)])",
        "entity-batches-business-before",
    )
    inferred = neo(
        "MATCH ()-[r:INFERRED_OCCUPATION]->() WITH r ORDER BY elementId(r) RETURN collect([elementId(r),properties(r)])",
        "entity-batches-inferences-before",
    )
    # Selection still runs independently for every production writer/verifier.
    # This table exists only in the disposable fixture, outside production SQL.
    selection_seconds = []
    for trial in range(3):
        started = time.perf_counter()
        fixture.sql("SELECT count(*) FROM ingestion.graph_source_entities('ALL_CHECKPOINTED')", "entity-selection-" + str(trial))
        selection_seconds.append(time.perf_counter() - started)
    maximum = 60001
    fixture.sql(
        """
CREATE SCHEMA source_entity_performance;
CREATE TABLE source_entity_performance.seed AS
 SELECT row_number() OVER(ORDER BY identity_id) AS seed_no,e.*
 FROM ingestion.graph_source_entities('ALL_CHECKPOINTED') e;
CREATE TABLE source_entity_performance.expected AS
 SELECT ordinal,'fixture:source:entity:'||ordinal::text AS identity_id,s.kind,
 'fixture-code-'||ordinal::text AS code,s.entity_name,s.entity_title,
 s.name_source_run_id,s.name_source_record_id,s.source_id,s.source_run_id,
 s.source_record_id,s.source_created_at,s.source_facts_json,s.source_facts_sha256
 FROM generate_series(1,60001) ordinal JOIN source_entity_performance.seed s
 ON s.seed_no=1+(ordinal-1)%(SELECT count(*) FROM source_entity_performance.seed);
CREATE UNIQUE INDEX ON source_entity_performance.expected(ordinal);
""",
        "entity-batches-real-source-inputs",
    )
    fixture.expect(
        fixture.sql("SELECT count(DISTINCT kind) FROM source_entity_performance.expected") == "6",
        "entity-batches-all-six-kinds",
    )
    benchmark = {"selection_seconds": selection_seconds, "transport_only": True, "synthetic_ids_and_codes": True, "operations": []}
    fixture.receipt["source_entity_batches"] = benchmark
    variants = {"batched": ROOT / "hop/graph"}
    baseline = os.environ.get("SOURCE_ENTITY_BASELINE")
    if baseline:
        variants["baseline"] = Path(baseline).resolve(strict=True)
    for variant, source in variants.items():
        for action, artifact in (("write", "load_entity_names.hpl"), ("verify", "verify_entity_names.hpl")):
            path = source / artifact
            node = E.parse(path).getroot()
            name = "entity_performance_" + variant + "_" + action
            node.find("info/name").text = name
            node.find("transform[name='Read entity names']/sql").text = (
                "SELECT * FROM source_entity_performance.expected WHERE ordinal<=?::integer ORDER BY ordinal"
            )
            E.indent(node, space="  ")
            E.ElementTree(node).write(fixture.work / "project/graph" / (name + ".hpl"), encoding="UTF-8", xml_declaration=True)
            benchmark[variant + "_" + action + "_artifact_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()

    def operation(variant, action, count, label, success=True):
        started = time.perf_counter()
        fixture.run(
            "../../graph/entity_performance_" + variant + "_" + action + ".hpl",
            label,
            success=success,
            extra={"RUN_ID": str(count), "NEO4J_CONNECTION": "jobtology-neo4j"},
        )
        elapsed = time.perf_counter() - started
        log = (fixture.logs / (label + ".log")).read_text()
        duration = re.search(r"Pipeline duration\s*:\s*([0-9.]+) seconds", log)
        benchmark["operations"].append({"variant": variant, "action": action, "rows": count, "expected_success": success, "wall_seconds": elapsed, "pipeline_seconds": float(duration[1]) if duration else None, "log": label})

    # Empty input must never touch the target; partial and exact batches both
    # need the actual count, rather than a hard-coded full-batch expectation.
    operation("batched", "write", 0, "entity-batches-empty-write")
    operation("batched", "verify", 0, "entity-batches-empty-verify")
    fixture.expect(neo("MATCH (n:entity) WHERE n.id STARTS WITH '" + PREFIX + "' RETURN count(n)=0", "entity-batches-empty-target") == "true", "entity-batches-empty-no-mutation")
    for count in (1, 499, 500, 501, 1001):
        operation("batched", "write", count, "entity-batches-write-" + str(count))
        operation("batched", "verify", count, "entity-batches-verify-" + str(count))
        fixture.expect(neo("MATCH (n:entity) WHERE n.id STARTS WITH '" + PREFIX + "' RETURN count(n)=" + str(count), "entity-batches-count-" + str(count)) == "true", "entity-batches-exact-count-" + str(count))

    # Warm replay timing follows functional boundary checks, on the same input
    # and target. Reverse the second pair to limit run-order bias.
    comparison = 10001
    operation("batched", "write", comparison, "entity-batches-prime-comparison")
    graph = graph_state("entity-batches-comparison-before")
    for trial, order in enumerate((("baseline", "batched"), ("batched", "baseline"))):
        for variant in order:
            if variant not in variants:
                continue
            for action in ("write", "verify"):
                operation(variant, action, comparison, "entity-batches-measure-" + str(trial) + "-" + variant + "-" + action)
            fixture.expect(graph_state("entity-batches-state-" + str(trial) + "-" + variant) == graph, "entity-batches-exact-typed-replay-" + str(trial) + "-" + variant)
    operation("batched", "write", maximum, "entity-batches-large-write")
    operation("batched", "verify", maximum, "entity-batches-large-verify")
    fixture.expect(neo("MATCH (n:entity) WHERE n.id STARTS WITH '" + PREFIX + "' RETURN count(n)=60001", "entity-batches-large-count") == "true", "entity-batches-larger-local-count")

    # A single bad row among 499 valid rows must fail the entire result. Each
    # mutation affects only synthetic test targets, never PostgreSQL evidence.
    for property_name, value, label in (("code", "'wrong-code'", "wrong-code"), ("kind", "'WrongKind'", "wrong-kind"), ("source_facts_json", "17", "wrong-type"), ("source_created_at", "'2030-01-01Z'", "wrong-datetime-type")):
        neo("MATCH (n:entity {id:'" + PREFIX + "333'}) SET n." + property_name + "=" + value + " RETURN true", "entity-batches-tamper-" + label)
        operation("batched", "verify", 501, "entity-batches-reject-" + label, False)
        if property_name in ("kind", "code"):
            operation("batched", "write", 501, "entity-batches-writer-reject-" + label, False)
            column = property_name
            original = fixture.sql("SELECT " + column + " FROM source_entity_performance.expected WHERE ordinal=333")
            neo("MATCH (n:entity {id:'" + PREFIX + "333'}) SET n." + property_name + "='" + original + "' RETURN true", "entity-batches-restore-" + label)
        operation("batched", "write", 501, "entity-batches-recover-" + label)
        operation("batched", "verify", 501, "entity-batches-recovered-" + label)
    neo("MATCH (n:entity {id:'" + PREFIX + "500'}) REMOVE n:organization:jobPosting:occupation:ncsCompetency:qualification:examSession RETURN true", "entity-batches-missing-label")
    operation("batched", "verify", 501, "entity-batches-reject-label", False)
    operation("batched", "write", 501, "entity-batches-recover-label")
    neo("MATCH (n:entity {id:'" + PREFIX + "1001'}) DELETE n RETURN true", "entity-batches-missing-last-partial")
    operation("batched", "verify", 1001, "entity-batches-reject-missing-last-partial", False)
    operation("batched", "write", 1001, "entity-batches-recover-missing-last-partial")
    operation("batched", "verify", 1001, "entity-batches-recovered-missing-last-partial")
    neo("MATCH (n:entity {id:'" + PREFIX + "1'}) SET n.title='stale title' RETURN true", "entity-batches-stale-title")
    fixture.sql("UPDATE source_entity_performance.expected SET entity_title=NULL,name_source_record_id=NULL,source_created_at=NULL,source_facts_json=NULL,source_facts_sha256=NULL WHERE ordinal=1", "entity-batches-null-expected")
    operation("batched", "write", 501, "entity-batches-null-write")
    operation("batched", "verify", 501, "entity-batches-null-verify")
    fixture.expect(neo("MATCH (n:entity {id:'" + PREFIX + "1'}) RETURN all(k IN ['title','name_source_record_id','source_created_at','source_facts_json','source_facts_sha256'] WHERE n[k] IS NULL)", "entity-batches-null-absence") == "true", "entity-batches-null-clears-stale-values")
    fixture.expect(
        neo(SYNTHETIC_CLEANUP_CYPHER, "entity-batches-clean-synthetic-targets") == str(maximum),
        "entity-batches-bounded-synthetic-cleanup",
    )
    fixture.sql("DROP SCHEMA source_entity_performance CASCADE", "entity-batches-clean-synthetic-inputs")
    fixture.expect(before == neo("MATCH (n:entity) WITH n ORDER BY n.id RETURN collect([elementId(n),n.id,properties(n)])", "entity-batches-business-after"), "entity-batches-original-business-properties-preserved")
    fixture.expect(inferred == neo("MATCH ()-[r:INFERRED_OCCUPATION]->() WITH r ORDER BY elementId(r) RETURN collect([elementId(r),properties(r)])", "entity-batches-inferences-after"), "entity-batches-original-ncs-inferences-preserved")
    fixture.receipt["source_entity_batches"] = benchmark
