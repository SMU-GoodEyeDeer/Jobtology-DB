"""Independent owner cleanup/totals boundaries in the existing native fixture.

Use scratch copies of the exact staged candidate Cypher, with synthetic rows in
an owned PostgreSQL schema and owned Neo4j entities. No restore or new database
is needed. The synthetic schema, pipelines and graph are removed on completion.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from benchmark_archived_routine import cypher_plain_true, cypher_value
from prepare_performance_readback import transform_counters, verifier_counters
from profile_archived_postgres import quote, write_json

PIPELINES = ("clear_source_edges", "verify_totals")


def owner_counters(log: str, expected: int) -> dict[str, Any]:
    """Keep nonempty batch counts strict; empty streams may omit downstream summaries."""
    if expected:
        return verifier_counters(
            log,
            dict(
                batch_size="500",
                operation_name="Set entity names",
                filter_name="Check result",
                success_name="Complete",
            ),
            expected,
        )
    if transform_counters(log, "Read entity names")["W"] != 0:
        raise RuntimeError("Empty owner input requires an authoritative zero-row reader")
    if "Execution finished on a local pipeline engine" not in log:
        raise RuntimeError("Empty owner pipeline completion is not recorded")
    for summary in re.findall(r"Finished processing \(([^)]*)\)", log):
        errors = re.search(r"\bE\s*=\s*(\d+)", summary)
        if errors is None or errors[1] != "0":
            raise RuntimeError("Empty owner pipeline reported errors or incomplete counters")
    result: dict[str, Any] = dict(
        counter_status="EMPTY_INPUT_NO_GRAPH_BATCH",
        expected_batches=0,
    )
    for field, name in (
        ("operation", "Set entity names"),
        ("result_filter", "Check result"),
        ("success_sink", "Complete"),
    ):
        # Hop omits these summaries when no row arrives. Absence is recorded
        # explicitly, rather than inventing observed zero operation counters.
        if re.search(re.escape(name) + r"\.\d+.*Finished processing \(", log) is None:
            result[field] = None
            continue
        counters = transform_counters(log, name)
        if any(counters.values()):
            raise RuntimeError("Empty owner input unexpectedly reached a downstream transform")
        result[field] = counters
    return result


def run(fixture: Any) -> None:
    token = uuid.uuid4().hex[:12]
    schema = "owner_batch_fixture_" + token
    prefix = "fixture:owner-batch:" + token + ":"
    source = "owner_batch_fixture_" + token
    params = {"RUN_ID": schema, "NEO4J_CONNECTION": "jobtology-neo4j"}
    graph_before = fixture.graph_snapshot("owner-boundary-original")
    scratch: list[Path] = []
    evidence: dict[str, Any] = dict(
        status="RUNNING",
        schema=schema,
        graph_prefix=prefix,
        batch_size=500,
        checks=[],
        native_cases=[],
        no_source_requests=True,
        no_paid_calls=True,
        production_writes=False,
        helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        candidate_sha256={},
        scratch_sha256={},
    )
    fixture.receipt["owner_batch_independent_correctness"] = evidence
    shutil.copyfile(Path(__file__), fixture.work / "launched-owner-boundary-helper.py")

    def save() -> None:
        write_json(fixture.work / "receipt.json", fixture.receipt)

    def check(label: str, condition: bool) -> None:
        if not condition:
            raise AssertionError("owner batch independent check: " + label)
        evidence["checks"].append(label)
        save()

    def neo(statement: str, label: str) -> str:
        return fixture.command(
            ["docker", "exec", fixture.neo, "cypher-shell", "--format", "plain", statement],
            "owner-boundary-" + label,
        )

    def populate(values: list[dict[str, Any]], label: str) -> None:
        supplied = [dict(ordinal=index, **value) for index, value in enumerate(values)]
        fixture.sql(
            "TRUNCATE " + schema + ".rows;INSERT INTO " + schema + ".rows "
            "SELECT * FROM jsonb_to_recordset(" + quote(json.dumps(supplied)) + "::jsonb) "
            "v(ordinal integer,owner_id text,source_id text,expected_edge_keys text,"
            "expected_edges bigint)",
            label + "-input-rows",
        )

    def row(
        number: int = 1, *, keys: str = "", count: int = 0, owner: str | None = None
    ) -> dict[str, Any]:
        return dict(
            owner_id=owner or prefix + str(number),
            source_id=source,
            expected_edge_keys=keys,
            expected_edges=count,
        )

    def execute(
        pipeline: str, label: str, values: list[dict[str, Any]], *, success: bool = True
    ) -> None:
        log_name = "owner-boundary-" + label + "-" + pipeline
        populate(values, log_name)
        fixture.run(
            "../../graph/fixture_owner_" + pipeline + ".hpl",
            log_name,
            success=success,
            extra=params,
        )
        log = (fixture.logs / (log_name + ".log")).read_text()
        if success:
            check(
                label + "-" + pipeline + "-reader-count",
                transform_counters(log, "Read entity names")["W"] == len(values),
            )
            counters = owner_counters(log, len(values))
            evidence["native_cases"].append(
                dict(
                    label=label,
                    pipeline=pipeline,
                    rows=len(values),
                    result="PASSED",
                    **counters,
                )
            )
        else:
            check(
                label + "-" + pipeline + "-false-result-aborts",
                "Source business projection differs from accepted PostgreSQL evidence" in log,
            )
            check(
                label + "-" + pipeline + "-cypher-has-no-error",
                transform_counters(log, "Set entity names")["E"] == 0,
            )
            evidence["native_cases"].append(
                dict(
                    label=label,
                    pipeline=pipeline,
                    rows=len(values),
                    result="EXPECTED_REFUSAL",
                )
            )
        save()

    created_schema = False
    cleanup_errors: list[str] = []
    try:
        for pipeline in PIPELINES:
            path = fixture.work / "project/graph" / (pipeline + ".hpl")
            body = path.read_bytes()
            root = ET.fromstring(body)
            cypher = root.find("transform[type='Neo4jCypherOutput']")
            reader = root.find("transform[name='Read entity names']/sql")
            if (
                cypher is None
                or reader is None
                or cypher.findtext("batch_size") != "500"
                or cypher.findtext("unwind") != "Y"
                or cypher.findtext("unwind_map") != "rows"
            ):
                raise RuntimeError("Stage the exact 500-row owner candidates before this oracle")
            evidence["candidate_sha256"][pipeline] = hashlib.sha256(body).hexdigest()
            root.find("info/name").text = "fixture_owner_" + pipeline
            fields = (
                "owner_id,source_id,expected_edge_keys"
                if pipeline == "clear_source_edges"
                else "owner_id,source_id,expected_edges"
            )
            reader.text = (
                "SELECT " + fields + " FROM " + schema + ".rows "
                "WHERE ?::text IS NOT NULL ORDER BY ordinal"
            )
            target = fixture.work / "project/graph" / ("fixture_owner_" + pipeline + ".hpl")
            ET.indent(root, space="  ")
            ET.ElementTree(root).write(target, encoding="UTF-8", xml_declaration=True)
            scratch.append(target)
            evidence["scratch_sha256"][pipeline] = hashlib.sha256(target.read_bytes()).hexdigest()

        created_schema = True
        fixture.sql(
            "CREATE SCHEMA " + schema + ";CREATE TABLE " + schema + ".rows("
            "ordinal integer,owner_id text,source_id text,expected_edge_keys text,"
            "expected_edges bigint)",
            "owner-boundary-create-schema",
        )
        neo(
            "UNWIND range(1,1001) AS ordinal CREATE(n:entity {id:"
            + cypher_value(prefix)
            + "+toString(ordinal),owner_batch_token:"
            + cypher_value(token)
            + ",kind:'PREEXISTING_WRONG_KIND'}) RETURN count(n)",
            "create-entities",
        )

        for count in (0, 1, 499, 500, 501, 1001):
            values = [row(number) for number in range(1, count + 1)]
            for pipeline in PIPELINES:
                execute(pipeline, "boundary-" + str(count), values)
        check(
            "existing-owner-kind-is-unchanged",
            cypher_plain_true(
                neo(
                    "MATCH(n:entity {owner_batch_token:"
                    + cypher_value(token)
                    + "}) RETURN count(n)=1001 AND all(v IN collect(n.kind) "
                    "WHERE v='PREEXISTING_WRONG_KIND')",
                    "kind-semantics-preserved",
                )
            ),
        )

        duplicate_values = [row() for _ in range(501)]
        for pipeline in PIPELINES:
            execute(pipeline, "duplicate-valid-owner-501", duplicate_values)
            execute(
                pipeline,
                "duplicates-plus-missing-same-batch",
                [row() for _ in range(499)] + [row(owner=prefix + "absent")],
                success=False,
            )
            execute(
                pipeline,
                "last-partial-batch-missing-owner",
                [row(number) for number in range(1, 501)] + [row(owner=prefix + "absent")],
                success=False,
            )

        # NULL edge_key is retained by the unchanged NOT IN predicate. Missing
        # ownership/source/source_graph properties likewise fail its WHERE gate.
        owner, endpoint = cypher_value(prefix + "1"), cypher_value(prefix + "2")
        relationships = (
            ("common", "common", True, source, prefix + "1", "SOURCE_FIXTURE"),
            ("left", "left", True, source, prefix + "1", "SOURCE_FIXTURE"),
            ("right", "right", True, source, prefix + "1", "SOURCE_FIXTURE"),
            ("stale", "stale", True, source, prefix + "1", "SOURCE_FIXTURE"),
            ("null-key", None, True, source, prefix + "1", "SOURCE_FIXTURE"),
            ("wrong-source", "stale", True, "other_source", prefix + "1", "SOURCE_FIXTURE"),
            ("wrong-owner", "stale", True, source, prefix + "different", "SOURCE_FIXTURE"),
            ("non-source", "stale", False, source, prefix + "1", "SOURCE_FIXTURE"),
            ("null-source", "stale", True, None, prefix + "1", "SOURCE_FIXTURE"),
            ("null-owner", "stale", True, source, None, "SOURCE_FIXTURE"),
            ("null-source-graph", "stale", None, source, prefix + "1", "SOURCE_FIXTURE"),
            ("inferred", "stale", None, None, None, "INFERRED_NCS_OCCUPATION"),
        )
        clauses = []
        for label, key, source_graph, source_id, owner_id, kind in relationships:
            properties = dict(
                owner_batch_token=token,
                test_case=label,
                typed_values=["한글", "A"],
                edge_key=key,
                source_graph=source_graph,
                source_id=source_id,
                owner_id=owner_id,
            )
            clauses.append("CREATE(a)-[:" + kind + " " + cypher_value(properties) + "]->(b)")
        neo(
            "MATCH(a:entity {id:"
            + owner
            + "}),(b:entity {id:"
            + endpoint
            + "}) "
            + " ".join(clauses)
            + " CREATE(b)-[:SOURCE_FIXTURE {owner_batch_token:"
            + cypher_value(token)
            + ",test_case:'incoming-stale',edge_key:'incoming-stale',"
            "source_graph:true,source_id:"
            + cypher_value(source)
            + ",owner_id:"
            + owner
            + "}]->(a) RETURN count(a)",
            "create-edge-cases",
        )
        retained = [
            "common",
            "null-key",
            "wrong-source",
            "wrong-owner",
            "non-source",
            "null-source",
            "null-owner",
            "null-source-graph",
            "inferred",
        ]
        protected_query = (
            "MATCH(a)-[r]->(b) WHERE r.owner_batch_token="
            + cypher_value(token)
            + " AND r.test_case IN "
            + cypher_value(retained)
            + " RETURN r.test_case,elementId(a),elementId(r),elementId(b),type(r),properties(r) "
            "ORDER BY r.test_case"
        )
        protected = neo(protected_query, "protected-edges-before")
        execute(
            "clear_source_edges",
            "same-owner-different-keysets",
            [row(keys="common,left"), row(keys="common,right")],
        )
        check(
            "different-keysets-delete-exact-stale-edges",
            cypher_plain_true(
                neo(
                    "MATCH()-[r]->() WHERE r.owner_batch_token="
                    + cypher_value(token)
                    + " RETURN count(r)=9 AND none(v IN collect(r.test_case) "
                    "WHERE v IN ['left','right','stale','incoming-stale'])",
                    "exact-edge-deletions",
                )
            ),
        )
        check(
            "null-and-foreign-and-inferred-edge-identities-properties-preserved",
            neo(protected_query, "protected-edges-after") == protected,
        )
        execute("verify_totals", "retained-null-key-counted", [row(count=2)])
        execute(
            "verify_totals", "null-key-cannot-be-omitted-from-total", [row(count=1)], success=False
        )
        execute(
            "verify_totals",
            "duplicate-owner-different-count-one-fails",
            [row(count=2), row(count=1)],
            success=False,
        )

        # Direct empty rows return a false Boolean, while the native empty SQL
        # stream correctly executes no Cypher batch (verified above).
        for pipeline in PIPELINES:
            root = ET.parse(fixture.work / "project/graph" / (pipeline + ".hpl")).getroot()
            query = root.findtext("transform[type='Neo4jCypherOutput']/cypher")
            output = fixture.command(
                ["docker", "exec", "-i", fixture.neo, "cypher-shell", "--format", "plain"],
                "owner-boundary-empty-query-" + pipeline,
                input_text=":param rows => []\n" + query + ";\n",
            )
            check(
                pipeline + "-explicit-empty-batch-is-false",
                output.splitlines()[-1].strip().lower() == "false",
            )
        evidence["status"] = "PASSED_PENDING_SYNTHETIC_CLEANUP"
    except BaseException as error:
        evidence.update(status="FAILED", failure_type=type(error).__name__)
        raise
    finally:
        try:
            neo(
                "MATCH(n {owner_batch_token:"
                + cypher_value(token)
                + "}) DETACH DELETE n RETURN count(n)",
                "remove-synthetic-graph",
            )
            evidence["synthetic_graph_removed"] = cypher_plain_true(
                neo(
                    "MATCH(n {owner_batch_token:" + cypher_value(token) + "}) RETURN count(n)=0",
                    "synthetic-graph-absence",
                )
            )
        except BaseException as error:
            cleanup_errors.append(type(error).__name__ + ":synthetic_graph")
        if created_schema:
            try:
                fixture.sql(
                    "DROP SCHEMA IF EXISTS " + schema + " CASCADE", "owner-boundary-drop-schema"
                )
                evidence["synthetic_schema_removed"] = (
                    fixture.sql(
                        "SELECT to_regnamespace(" + quote(schema) + ") IS NULL",
                        "owner-boundary-schema-absence",
                    )
                    == "t"
                )
            except BaseException as error:
                cleanup_errors.append(type(error).__name__ + ":synthetic_schema")
        else:
            evidence["synthetic_schema_removed"] = True
        for path in scratch:
            try:
                path.unlink(missing_ok=True)
            except OSError as error:
                cleanup_errors.append(type(error).__name__ + ":scratch_pipeline")
        evidence["scratch_pipelines_removed"] = all(not path.exists() for path in scratch)
        try:
            evidence["exact_original_graph_restored"] = (
                fixture.graph_snapshot("owner-boundary-restored") == graph_before
            )
        except BaseException as error:
            cleanup_errors.append(type(error).__name__ + ":graph_readback")
        evidence["cleanup_errors"] = cleanup_errors
        clean = (
            not cleanup_errors
            and evidence.get("synthetic_graph_removed")
            and evidence.get("synthetic_schema_removed")
            and evidence["scratch_pipelines_removed"]
            and evidence.get("exact_original_graph_restored")
        )
        if evidence["status"] == "PASSED_PENDING_SYNTHETIC_CLEANUP" and clean:
            evidence["status"] = "PASSED"
        save()
        if not clean:
            evidence["status"] = "FAILED"
            save()
            raise RuntimeError("Independent owner batch synthetic cleanup/readback failed")
