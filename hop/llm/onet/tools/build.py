"""Generate separate native Hop O*NET transport and publication workflows."""
# SQL and Java are mirrored verbatim in native artifacts.
# ruff: noqa: E501

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as E
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / "hop/llm/onet"
sys.path.insert(0, str(ROOT / "hop/ingestions/onet/tools"))
from build import (  # noqa: E402
    Pipeline,
    child,
    cypher,
    database,
    execute,
    property_sql,
    put,
    remember,
    require_result,
    transform,
)

sys.path.insert(0, str(ROOT / "hop/ingestions/jobkorea/tools"))
from build_metadata_concurrency import worker_java  # noqa: E402


def save(root: E.Element, filename: str) -> None:
    E.indent(root, space="  ")
    E.ElementTree(root).write(OUT / filename, encoding="UTF-8", xml_declaration=True)


def finish_pipeline(p: Pipeline) -> None:
    E.SubElement(p.root, "transform_error_handling")
    E.SubElement(p.root, "attributes")
    save(p.root, p.name + ".hpl")


def variables(fields: list[tuple[str, str]]) -> E.Element:
    node = transform("GetVariable", "Exact O*NET operation options")
    target = E.SubElement(node, "fields")
    for field, variable in fields:
        child(
            target,
            "field",
            {
                "name": field,
                "variable": "${" + variable + "}",
                "type": "String",
                "length": -1,
                "precision": -1,
                "trim_type": "none",
            },
        )
    return node


def workflow(
    name: str, stages: list[tuple[str, str]], parameters: dict[str, str], fail: str | None = None
) -> None:
    # Keep the canonical local runner's action format and error semantics.
    root = E.parse(ROOT / "hop/ingestions/onet/load_catalog.hwf").getroot()
    put(root, "name", name)
    put(
        root,
        "description",
        "Separate O*NET inferred occupation operation; frozen local evidence, bounded accounting and explicit review.",
    )
    params = root.find("parameters")
    assert params is not None
    params.clear()
    for key, value in parameters.items():
        child(params, "parameter", {"name": key, "default_value": value, "description": key})
    actions = root.find("actions")
    hops = root.find("hops")
    assert actions is not None and hops is not None
    pipeline_template = next(action for action in actions if action.findtext("type") == "PIPELINE")
    kept = [
        deepcopy(action)
        for action in actions
        if action.findtext("name") in ("Start", "Success", "Abort")
    ]
    actions.clear()
    actions.extend(kept)
    hops.clear()
    previous = "Start"
    for label, filename in stages:
        action = deepcopy(pipeline_template)
        put(action, "name", label)
        put(action, "filename", "${PROJECT_HOME}/llm/onet/" + filename)
        put(action, "run_configuration", "onet-local")
        actions.append(action)
        child(
            hops,
            "hop",
            {
                "from": previous,
                "to": label,
                "enabled": "Y",
                "evaluation": "Y",
                "unconditional": "Y" if previous == "Start" else "N",
            },
        )
        child(
            hops,
            "hop",
            {
                "from": label,
                "to": fail or "Abort",
                "enabled": "Y",
                "evaluation": "N",
                "unconditional": "N",
            },
        )
        previous = label
    child(
        hops,
        "hop",
        {
            "from": previous,
            "to": "Success",
            "enabled": "Y",
            "evaluation": "Y",
            "unconditional": "N",
        },
    )
    if fail:
        action = deepcopy(pipeline_template)
        put(action, "name", fail)
        put(action, "filename", "${PROJECT_HOME}/llm/onet/fail_graph.hpl")
        put(action, "run_configuration", "onet-local")
        actions.append(action)
        for result in ("Y", "N"):
            child(
                hops,
                "hop",
                {
                    "from": fail,
                    "to": "Abort",
                    "enabled": "Y",
                    "evaluation": result,
                    "unconditional": "N",
                },
            )
    save(root, name + ".hwf")


def build_transport() -> None:
    p = Pipeline(
        "start_execution",
        "Own an initial dispatcher or resume only never-sent requests after process cleanup.",
    )
    p.add(
        variables(
            [
                ("batch_id", "ONET_BATCH_ID"),
                ("workers", "REQUEST_WORKERS"),
                ("resume", "ONET_RESUME"),
            ]
        )
    )
    p.add(
        database(
            "Own O*NET execution",
            "SELECT started->>'execution_token' AS execution_token FROM (SELECT onet_matching.start_execution(?,?::integer,?='Y') AS started) s",
            [("batch_id", "String"), ("workers", "String"), ("resume", "String")],
        )
    )
    p.add(remember("execution_token", "ONET_EXECUTION_TOKEN"))
    finish_pipeline(p)

    root = E.parse(ROOT / "hop/ingestions/jobkorea/run_inferred_occupation_workers.hpl").getroot()
    put(root.find("info"), "name", "run_requests")
    put(
        root.find("info"),
        "description",
        "Stream planned request identities into 1..16 bounded native workers; reserve immediately before one POST.",
    )
    for node in root.findall("transform"):
        if node.findtext("type") == "GetVariable":
            put(node.find("fields/field"), "variable", "${ONET_BATCH_ID}")
        elif node.findtext("name") == "Pending requests":
            put(
                node,
                "sql",
                "SELECT a.attempt_id FROM onet_matching.attempt a JOIN onet_matching.task t USING(task_id) WHERE a.batch_id=? AND a.state='PLANNED' AND t.settings->>'execute_requests'='Y' ORDER BY a.ordinal",
            )
        elif node.findtext("type") == "PipelineExecutor":
            put(node, "filename", "${PROJECT_HOME}/llm/onet/request_worker.hpl")
            put(node, "run_configuration", "onet-local")
    save(root, "run_requests.hpl")

    root = E.parse(
        ROOT / "hop/ingestions/jobkorea/request_inferred_occupation_worker.hpl"
    ).getroot()
    put(root.find("info"), "name", "request_worker")
    java = worker_java().replace(
        "enrichment.metadata_occupation_request_context", "onet_matching.request_context"
    )
    java = java.replace(
        "enrichment.admit_metadata_occupation_request", "onet_matching.admit_request"
    )
    java = java.replace(
        "enrichment.stop_metadata_occupation_execution", "onet_matching.stop_execution"
    )
    java = java.replace("enrichment.save_response", "onet_matching.save_response")
    java = java.replace("enrichment.attempt", "onet_matching.attempt")
    java = java.replace("METADATA_OCCUPATION_EXECUTION_TOKEN", "ONET_EXECUTION_TOKEN")
    java = java.replace("JOBKOREA_ISOLATED_TOKEN", "ONET_MATCHING_ISOLATED_TOKEN")
    java = java.replace("jobtology-jobkorea-test-", "jobtology-onet-test-")
    java = java.replace(
        "SELECT request_body::text FROM onet_matching.attempt WHERE attempt_id=? AND state='RESERVED'",
        "SELECT i.request_body::text FROM onet_matching.attempt a JOIN onet_matching.input i USING(task_id,posting_identity) WHERE a.attempt_id=? AND a.state='RESERVED'",
    )
    java = java.replace(
        '"ERROR".equals(finalState)||"REJECTED".equals(finalState)||result.getBoolean(2)',
        '"ERROR".equals(finalState)||result.getBoolean(2)',
    )
    java = java.replace(
        "java.sql.PreparedStatement read=",
        "reserved=admitted;\n   java.sql.PreparedStatement read=",
    )
    java_node = root.find("transform[type='UserDefinedJavaClass']/definitions/definition")
    assert java_node is not None
    put(java_node, "class_source", java)
    save(root, "request_worker.hpl")

    p = Pipeline(
        "end_execution", "Report settled execution; unknown charges remain accounting holds."
    )
    p.add(variables([("token", "ONET_EXECUTION_TOKEN")]))
    p.add(
        database(
            "End O*NET execution",
            "SELECT CASE WHEN nullif(?,'') IS NULL THEN '{}'::jsonb ELSE onet_matching.end_execution(nullif(?,'')::uuid) END::text AS status_json",
            [("token", "String"), ("token", "String")],
        )
    )
    finish_pipeline(p)
    workflow(
        "execute_matches",
        [
            ("Own bounded dispatcher", "start_execution.hpl"),
            ("Run bounded requests", "run_requests.hpl"),
            ("Settle dispatcher", "end_execution.hpl"),
        ],
        {
            "ONET_BATCH_ID": "",
            "ONET_RESUME": "N",
            "REQUEST_WORKERS": "1",
            "API_KEY_FILE": "${HOP_CONFIG_FOLDER}/secrets/openrouter.csv",
            "ONET_EXECUTION_TOKEN": "",
        },
    )


def build_install() -> None:
    root = E.parse(ROOT / "hop/ingestions/onet/install.hwf").getroot()
    put(root, "name", "Install separate O*NET posting inference")
    actions = root.find("actions")
    hops = root.find("hops")
    assert actions is not None and hops is not None
    sql = next(action for action in actions if action.findtext("type") == "SQL")
    kept = [
        deepcopy(action)
        for action in actions
        if action.findtext("name") in ("Start", "Success", "Abort")
    ]
    actions.clear()
    actions.extend(kept)
    hops.clear()
    previous = "Start"
    # Base installer remains frozen; separately qualified successors have their
    # own additive installers and must never be folded into the original HWF.
    for basename in (
        "001_matching.sql",
        "002_results.sql",
        "003_publication.sql",
        "004_prompt_contract.sql",
    ):
        filename = OUT / "sql" / basename
        label = filename.stem
        action = deepcopy(sql)
        put(action, "name", label)
        put(action, "sqlfilename", "${PROJECT_HOME}/llm/onet/sql/" + filename.name)
        actions.append(action)
        child(
            hops,
            "hop",
            {
                "from": previous,
                "to": label,
                "enabled": "Y",
                "evaluation": "Y",
                "unconditional": "Y" if previous == "Start" else "N",
            },
        )
        child(
            hops,
            "hop",
            {"from": label, "to": "Abort", "enabled": "Y", "evaluation": "N", "unconditional": "N"},
        )
        previous = label
    child(
        hops,
        "hop",
        {
            "from": previous,
            "to": "Success",
            "enabled": "Y",
            "evaluation": "Y",
            "unconditional": "N",
        },
    )
    save(root, "install.hwf")


def build_contract() -> None:
    sys.path.insert(0, str(ROOT))
    from hop.llm.onet.prompt import PROMPT_HASH, PROMPT_TEXT, PROMPT_VERSION, SCHEMA

    # Exact original validator body, scoped into the new namespace. Existing
    # enrichment helpers and their execution metadata remain untouched.
    validation = (ROOT / "hop/llm/sql/004_validation.sql").read_text()
    body = re.search(
        r"CREATE OR REPLACE FUNCTION enrichment\.schema_issues\(.*?\$\$;", validation, re.DOTALL
    )
    assert body
    encoded = json.dumps(SCHEMA, ensure_ascii=False, separators=(",", ":"))
    sql = "-- Generated from pinned O*NET prompt.py and original strict schema helper.\nBEGIN;\nSELECT retention.gate();\n"
    sql += body.group().replace("enrichment.schema_issues", "onet_matching.schema_issues") + "\n"
    sql += "CREATE TABLE IF NOT EXISTS onet_matching.prompt_contract(version text PRIMARY KEY,prompt_text text NOT NULL,prompt_hash text NOT NULL,schema jsonb NOT NULL);\n"
    sql += (
        "INSERT INTO onet_matching.prompt_contract VALUES("
        + "'"
        + PROMPT_VERSION
        + "',$onet_prompt$"
        + PROMPT_TEXT
        + "$onet_prompt$,'"
        + PROMPT_HASH
        + "',$onet_schema$"
        + encoded
        + "$onet_schema$::jsonb) ON CONFLICT DO NOTHING;\n"
    )
    sql += (
        "DO $verify$ BEGIN IF NOT EXISTS(SELECT 1 FROM onet_matching.prompt_contract WHERE version='"
        + PROMPT_VERSION
        + "' AND prompt_text=$onet_prompt$"
        + PROMPT_TEXT
        + "$onet_prompt$ AND prompt_hash='"
        + PROMPT_HASH
        + "' AND schema=$onet_schema$"
        + encoded
        + "$onet_schema$::jsonb) THEN RAISE EXCEPTION 'ONET_MATCHING_PROMPT_CHANGED'; END IF; END $verify$;\n"
    )
    sql += "CREATE OR REPLACE TRIGGER immutable_prompt BEFORE UPDATE OR DELETE ON onet_matching.prompt_contract FOR EACH ROW EXECUTE FUNCTION onet_matching.immutable();\n"
    sql += "CREATE OR REPLACE TRIGGER immutable_truncate BEFORE TRUNCATE ON onet_matching.prompt_contract FOR EACH STATEMENT EXECUTE FUNCTION onet_matching.immutable();\n"
    sql += "CREATE OR REPLACE TRIGGER retention_freeze BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON onet_matching.prompt_contract FOR EACH STATEMENT EXECUTE FUNCTION retention.freeze_writes();\nCOMMIT;\n"
    (OUT / "sql/004_prompt_contract.sql").write_text(sql)


def build_publication() -> None:
    owner, namespace = "jobtology-onet-matching-v1", "urn:jobtology:inferred-onet-occupation:"
    p = Pipeline(
        "begin_graph", "Freeze one exact flat O*NET relationship plan and acquire only its writer."
    )
    p.add(variables([("task_id", "ONET_TASK_ID")]))
    p.add(
        database(
            "Freeze exact O*NET graph rows",
            "SELECT result->>'publication_id' AS publication_id FROM (SELECT onet_matching.begin_graph(?) AS result) s",
            [("task_id", "String")],
        )
    )
    p.add(remember("publication_id", "ONET_PUBLICATION_ID"))
    finish_pipeline(p)

    def options() -> E.Element:
        return variables([("publication_id", "ONET_PUBLICATION_ID")])

    prefix = "CALL db.info() YIELD id AS actual_database_id\nUNWIND $rows AS row\nWITH row,actual_database_id WHERE row.database_id=actual_database_id\n"
    decode = """WITH row,split(row.property_data,'|') AS fields
WHERE size(fields)=row.property_count*3
WITH row,[i IN range(0,size(fields)-1,3) | {key:replace(replace(fields[i],'%7C','|'),'%25','%'),
type:fields[i+1],text:replace(replace(fields[i+2],'%7C','|'),'%25','%')}] AS fields
WITH row,[p IN fields | {key:p.key,valid:p.type IN ['string','integer','number','boolean'],
value:CASE p.type WHEN 'string' THEN p.text WHEN 'integer' THEN toInteger(p.text)
WHEN 'number' THEN toFloat(p.text) WHEN 'boolean' THEN toBoolean(p.text) END}] AS expected_properties
WHERE all(p IN expected_properties WHERE p.valid AND p.value IS NOT NULL)
"""
    endpoints = """MATCH (posting:entity:jobPosting {id:row.posting_identity,kind:'JobPosting'})
WITH row,expected_properties,posting
MATCH (occupation:entity:onetCatalogObject:occupation {id:row.occupation_identity})
WHERE posting.source_facts_sha256=row.source_facts_sha256
AND occupation.managed_by='jobtology-onet-catalog-v1' AND occupation.scheme_id='ONET'
AND occupation.release_id=row.release_id AND occupation.current=true
AND occupation.content_hash=row.occupation_content_hash
"""
    equality = "size(keys(object))=row.property_count AND all(p IN expected_properties WHERE object[p.key]=p.value AND valueType(object[p.key])=valueType(p.value))"
    fields = [
        (key, "String")
        for key in (
            "database_id",
            "edge_id",
            "posting_identity",
            "occupation_identity",
            "source_facts_sha256",
            "release_id",
            "occupation_content_hash",
            "property_data",
        )
    ] + [("property_count", "Integer")]
    rows_sql = (
        "SELECT g.database_id,e.edge_id,e.posting_identity,e.occupation_identity,e.properties->>'source_facts_sha256' AS source_facts_sha256,e.properties->>'release_id' AS release_id,e.properties->>'occupation_content_hash' AS occupation_content_hash,"
        + property_sql("e.properties")
        + " AS property_data,(SELECT count(*) FROM jsonb_object_keys(e.properties))::bigint AS property_count FROM onet_matching.graph_edge e JOIN onet_matching.graph_guard g USING(publication_id) WHERE e.publication_id=? ORDER BY edge_id"
    )
    for name, tail, readonly in (
        (
            "preflight_edges",
            endpoints
            + "OPTIONAL MATCH (posting)-[object:INFERRED_ONET_OCCUPATION {id:row.edge_id}]->(occupation)\nRETURN count(posting)=size($rows) AND count(DISTINCT row.edge_id)=size($rows) AND all(valid IN collect(object IS NULL OR object.managed_by='"
            + owner
            + "') WHERE valid) AS verified",
            True,
        ),
        (
            "write_edges",
            endpoints
            + "MERGE (posting)-[object:INFERRED_ONET_OCCUPATION {id:row.edge_id}]->(occupation)\nON CREATE SET object.managed_by='"
            + owner
            + "'\nWITH row,expected_properties,object WHERE object.managed_by='"
            + owner
            + "'\nFOREACH (key IN [key IN keys(object) WHERE NOT key IN [p IN expected_properties | p.key]] | SET object[key]=null)\nFOREACH (property IN expected_properties | SET object[property.key]=property.value)\nRETURN count(object)=size($rows) AND count(DISTINCT row.edge_id)=size($rows) AS verified",
            False,
        ),
        (
            "verify_edges",
            endpoints
            + "OPTIONAL MATCH (posting)-[object:INFERRED_ONET_OCCUPATION {id:row.edge_id}]->(occupation)\nRETURN count(object)=size($rows) AND count(DISTINCT row.edge_id)=size($rows) AND all(valid IN collect(coalesce("
            + equality
            + ",false)) WHERE valid) AS verified",
            True,
        ),
    ):
        p = Pipeline(
            name,
            "Verify exact indexed endpoints and complete typed properties in bounded 500-row batches.",
        )
        p.add(options())
        p.add(
            execute(
                "Check frozen graph plan once",
                "SELECT onet_matching.check_graph(?)",
                ["publication_id"],
            )
        )
        p.add(database("Read frozen graph plan", rows_sql, [("publication_id", "String")]))
        operation_prefix = prefix
        if name == "preflight_edges":
            # Detect an owned-looking ID on a different pair of endpoints too.
            # Scan candidates once before expanding each 500-row native batch.
            operation_prefix = (
                "CALL db.info() YIELD id AS actual_database_id\nCALL () {\nOPTIONAL MATCH (a)-[r]->(b) WHERE r.id STARTS WITH '"
                + namespace
                + "'\nRETURN collect({edge_id:r.id,start_id:a.id,end_id:b.id,owner:r.managed_by}) AS collisions\n}\nUNWIND $rows AS row\nWITH row,collisions,actual_database_id WHERE actual_database_id=row.database_id AND size([c IN collisions WHERE c.edge_id=row.edge_id])<=1 AND all(c IN collisions WHERE c.edge_id IS NULL OR c.edge_id<>row.edge_id OR (c.start_id=row.posting_identity AND c.end_id=row.occupation_identity AND c.owner='"
                + owner
                + "'))\nWITH row\n"
            )
        p.add(
            cypher(
                "Apply bounded O*NET graph operation",
                operation_prefix + decode + tail,
                fields,
                readonly=readonly,
                batched=True,
            )
        )
        require_result(p)
        finish_pipeline(p)

    p = Pipeline(
        "preflight_scope",
        "Reject global collisions in the separately owned inferred relationship namespace before any graph writes.",
    )
    p.add(options())
    p.add(
        execute(
            "Check frozen graph plan once",
            "SELECT onet_matching.check_graph(?)",
            ["publication_id"],
        )
    )
    p.add(
        database(
            "Read exact graph target",
            "SELECT database_id,task_id FROM onet_matching.graph_guard WHERE publication_id=?",
            [("publication_id", "String")],
        )
    )
    query = (
        "CALL db.info() YIELD id AS actual_database_id\nOPTIONAL MATCH (a)-[r]->(b) WHERE r.id STARTS WITH '"
        + namespace
        + "' OR type(r)='INFERRED_ONET_OCCUPATION' OR r.managed_by='"
        + owner
        + "'\nWITH actual_database_id,collect(r IS NULL OR (type(r)='INFERRED_ONET_OCCUPATION' AND r.managed_by='"
        + owner
        + "' AND r.id STARTS WITH '"
        + namespace
        + "' AND a:entity AND a:jobPosting AND b:entity AND b:onetCatalogObject AND b:occupation AND r.occupation_code=b.code AND r.release_id=b.release_id)) AS valid_flags,count(r) AS actual_count,count(DISTINCT r.id) AS unique_count\nRETURN actual_database_id=$database_id AND all(valid IN valid_flags WHERE valid) AND actual_count=unique_count AS verified"
    )
    p.add(
        cypher(
            "Preflight inferred namespace once", query, [("database_id", "String")], readonly=True
        )
    )
    require_result(p)
    finish_pipeline(p)

    p = Pipeline(
        "finish_graph",
        "Compare actual owned task relationship count before marking this publication VERIFIED.",
    )
    p.add(options())
    p.add(
        execute(
            "Check frozen graph plan once",
            "SELECT onet_matching.check_graph(?)",
            ["publication_id"],
        )
    )
    p.add(
        database(
            "Read exact task graph target",
            "SELECT database_id,task_id,expected_count FROM onet_matching.graph_guard WHERE publication_id=?",
            [("publication_id", "String")],
        )
    )
    p.add(
        cypher(
            "Count exact owned task edges",
            "CALL db.info() YIELD id AS actual_database_id\nOPTIONAL MATCH ()-[r:INFERRED_ONET_OCCUPATION]->() WHERE r.managed_by='"
            + owner
            + "' AND r.task_id=$task_id\nWITH actual_database_id,count(r) AS verified_count\nRETURN actual_database_id=$database_id AND verified_count=$expected_count AS verified,verified_count",
            [("database_id", "String"), ("task_id", "String"), ("expected_count", "Integer")],
            readonly=True,
            returns=(("verified", "Boolean"), ("verified_count", "Integer")),
        )
    )
    require_result(p)
    p.add(
        execute(
            "Finish exact graph publication",
            "SELECT onet_matching.finish_graph(?,?::bigint)",
            ["publication_id", "verified_count"],
        )
    )
    finish_pipeline(p)

    p = Pipeline(
        "fail_graph",
        "Release only this owned graph writer; retain partial failed publication evidence.",
    )
    p.add(options())
    p.add(
        execute(
            "Fail only own O*NET publication",
            "SELECT onet_matching.fail_graph(nullif(?,''))",
            ["publication_id"],
        )
    )
    finish_pipeline(p)
    workflow(
        "publish_matches",
        [
            ("Freeze publication", "begin_graph.hpl"),
            ("Preflight inferred namespace", "preflight_scope.hpl"),
            ("Preflight all exact endpoints", "preflight_edges.hpl"),
            ("Write flat inferred edges", "write_edges.hpl"),
            ("Verify every typed relationship", "verify_edges.hpl"),
            ("Finish exact publication", "finish_graph.hpl"),
        ],
        {"ONET_TASK_ID": "", "ONET_PUBLICATION_ID": "", "NEO4J_CONNECTION": "jobtology-neo4j"},
        fail="Fail own O*NET publication",
    )


if __name__ == "__main__":
    build_contract()
    build_transport()
    build_publication()
    build_install()
