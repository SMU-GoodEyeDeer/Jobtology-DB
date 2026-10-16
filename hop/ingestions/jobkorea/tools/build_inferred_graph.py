"""Generate the separate, guarded STAGING metadata occupation graph projection."""

import xml.etree.ElementTree as E
from copy import deepcopy

from build_linking import (
    OUT,
    Pipeline,
    child,
    database,
    put,
    remember,
    save,
    transform,
    variables,
    workflow,
)

MANAGER = "jobtology-metadata-occupation"
PINS = ["jobs", "ncs", "include_unreviewed"]
PIN_SQL = "?,?,?::boolean"
ROWS_SQL = f"enrichment.metadata_occupation_graph_rows({PIN_SQL})"
STATE_SQL = f"""SELECT enrichment.hash(?||':'||?) AS projection_id,
enrichment.metadata_occupation_graph_hash({PIN_SQL}) AS projection_hash,
(SELECT count(*)::bigint FROM {ROWS_SQL}) AS expected_count"""
STATE_ARGS = ["jobs", "ncs", *PINS, *PINS]
EDGE_SQL = f"""SELECT *,payload::text AS payload_json,
enrichment.hash(payload::text) AS payload_hash,
payload->>'occupation_code' AS occupation_code,payload->>'review_status' AS review_status,
payload->>'confidence_state' AS confidence_state,(payload->>'accepted')::boolean AS accepted,
payload->>'result_id' AS result_id,payload->>'bundle_id' AS bundle_id,
payload->>'source_hash' AS source_hash,payload->>'binding_hash' AS binding_hash,
payload->>'catalog_hash' AS catalog_hash,payload->>'occupation_scheme' AS occupation_scheme,
payload->>'rank_basis' AS rank_basis,(payload->>'match_rank')::integer AS match_rank,
(payload->>'original_primary')::boolean AS original_primary,
(payload->>'current_primary')::boolean AS current_primary
FROM {ROWS_SQL} ORDER BY candidate_id"""
EDGE_FIELDS = [
    "jobs",
    "ncs",
    "graph_token",
    "posting_identity",
    "occupation_identity",
    "candidate_id",
    "payload_json",
    "payload_hash",
    "occupation_code",
    "review_status",
    "confidence_state",
    "result_id",
    "bundle_id",
    "source_hash",
    "binding_hash",
    "catalog_hash",
    "occupation_scheme",
    "rank_basis",
]
EDGE_ARGS = [(name, "String") for name in EDGE_FIELDS] + [
    ("accepted", "Boolean"),
    ("match_rank", "Integer"),
    ("original_primary", "Boolean"),
    ("current_primary", "Boolean"),
]
STATE_FIELDS = ["jobs", "ncs", "graph_token", "projection_id", "projection_hash"]
STATE_CYPHER_ARGS = [(name, "String") for name in STATE_FIELDS] + [("expected_count", "Integer")]

# Exact historical source membership and immutable hashes are established in PG
# before each publication phase. Live entities may legitimately reflect a newer
# accepted source run, so compare stable business identity/type here.
ENDPOINT_CHECK = """MATCH (p:entity:jobPosting {id:$posting_identity,kind:'JobPosting'})
WITH p
MATCH (o:entity:occupation {id:$occupation_identity,kind:'Occupation',code:$occupation_code})
WHERE $occupation_scheme IS NULL OR $occupation_scheme='NCS'"""
EDGE_CHECK = """r.payload_json=$payload_json AND r.payload_hash=$payload_hash
AND r.job_run_id=$jobs AND r.ncs_run_id=$ncs AND r.projection_token=$graph_token
AND r.basis='METADATA_INFERRED' AND r.assertion_kind='MODEL_INFERRED'
AND r.serving_scope='STAGING' AND r.stage='STAGING' AND r.current=false
AND r.review_status=$review_status AND r.confidence IS NULL
AND r.confidence_state=$confidence_state AND r.accepted=$accepted
AND r.result_id=$result_id AND r.bundle_id=$bundle_id AND r.source_hash=$source_hash
AND r.binding_hash=$binding_hash AND r.catalog_hash=$catalog_hash
AND (($occupation_scheme IS NULL AND r.occupation_scheme IS NULL AND r.match_rank IS NULL)
 AND r.rank_basis IS NULL AND r.original_primary IS NULL AND r.current_primary IS NULL
 OR (r.occupation_scheme=$occupation_scheme AND r.match_rank=$match_rank
 AND r.rank_basis=$rank_basis
 AND r.original_primary=$original_primary AND r.current_primary=$current_primary))"""


def options():
    node = variables(
        [
            ("jobs", "JOB_RUN_ID"),
            ("ncs", "NCS_RUN_ID"),
            ("include_unreviewed", "INCLUDE_UNREVIEWED"),
            ("graph_token", "GRAPH_TOKEN"),
        ]
    )
    put(node, "name", "Exact projection pins")
    return node


def execute(name, sql, fields):
    node = transform("ExecSql", name)
    for key, value in {
        "connection": "jobtology-postgres",
        "sql": sql,
        "execute_each_row": "Y",
        "single_statement": "Y",
        "set_params": "Y",
        "replace_variables": "N",
        "quoteString": "N",
    }.items():
        put(node, key, value)
    args = E.SubElement(node, "arguments")
    for field in fields:
        child(args, "argument", {"name": field})
    return node


def cypher(name, query, fields, readonly=False, result_field="verified"):
    node = transform("Neo4jCypherOutput", name)
    for key, value in {
        "connection": "${NEO4J_CONNECTION}",
        "cypher": query,
        "batch_size": 1,
        "read_only": "Y" if readonly else "N",
        "retry": "N",
        "nr_retries_on_error": 0,
        "cypher_from_field": "N",
        "unwind": "N",
        "returning_graph": "N",
    }.items():
        put(node, key, value)
    mappings = E.SubElement(node, "mappings")
    for field, kind in fields:
        child(mappings, "mapping", {"parameter": field, "field": field, "type": kind})
    child(
        E.SubElement(node, "returns"),
        "return",
        {
            "name": result_field,
            "type": "Boolean",
            "source_type": "Boolean",
        },
    )
    return node


def verify(pipeline, prefix="", field="verified"):
    check_name = prefix + "Require exact graph result"
    done_name = prefix + "Verified"
    failure_name = prefix + "Graph mismatch"
    check = transform("FilterRows", check_name)
    put(check, "send_true_to", done_name)
    put(check, "send_false_to", failure_name)
    condition = child(
        E.SubElement(check, "compare"),
        "condition",
        {
            "negated": "N",
            "operator": "-",
            "leftvalue": field,
            "function": "=",
        },
    )
    child(
        condition,
        "value",
        {
            "name": "constant",
            "type": "Boolean",
            "text": "Y",
            "length": -1,
            "precision": -1,
            "isnull": "N",
        },
    )
    pipeline.add(check)
    pipeline.add(transform("Dummy", done_name))
    abort = transform("Abort", failure_name)
    for key, value in {
        "message": "Inferred occupation projection differs from its exact frozen pins/evidence.",
        "always_log_rows": "N",
        "abort_option": "ABORT_WITH_ERROR",
        "row_threshold": 0,
    }.items():
        put(abort, key, value)
    pipeline.root.append(abort)
    child(
        pipeline.order,
        "hop",
        {
            "from": check_name,
            "to": failure_name,
            "enabled": "Y",
        },
    )


def build():
    p = Pipeline(
        "acquire_inferred_occupation_graph", "Freeze exact rows and acquire retention writer."
    )
    p.add(options())
    p.add(
        database(
            "Acquire fenced writer",
            f"SELECT enrichment.begin_metadata_occupation_graph({PIN_SQL}) AS acquired_token",
            PINS,
        )
    )
    p.add(remember([("acquired_token", "GRAPH_TOKEN")]))
    p.save("acquire_inferred_occupation_graph")

    p = Pipeline(
        "begin_inferred_occupation_graph",
        "Check PostgreSQL source proofs before own STAGING writes.",
    )
    p.add(options())
    p.add(
        execute(
            "Check immutable projection",
            "SELECT enrichment.check_metadata_occupation_graph(?)",
            ["graph_token"],
        )
    )
    p.add(database("Expected frozen projection", STATE_SQL, STATE_ARGS))
    # PostgreSQL has already checked complete, immutable pinned source evidence.
    begin = f"""MERGE (m:metadataOccupationProjection {{id:$projection_id}})
SET m.managed_by='{MANAGER}',m.job_run_id=$jobs,m.ncs_run_id=$ncs,
m.serving_scope='STAGING',m.state='LOADING',m.projection_token=$graph_token,
m.projection_hash=$projection_hash,m.expected_count=$expected_count
WITH m OPTIONAL MATCH ()-[r:INFERRED_NCS_OCCUPATION {{managed_by:'{MANAGER}',
job_run_id:$jobs,ncs_run_id:$ncs}}]->()
SET r.current=false
RETURN count(DISTINCT m)=1 AS verified"""
    p.add(cypher("Begin own staging projection", begin, STATE_CYPHER_ARGS))
    verify(p)
    p.save("begin_inferred_occupation_graph")

    p = Pipeline(
        "load_inferred_occupation_graph", "Merge only validated pinned metadata inferences."
    )
    p.add(options())
    p.add(
        execute(
            "Recheck exact source membership",
            "SELECT enrichment.check_metadata_occupation_graph(?)",
            ["graph_token"],
        )
    )
    p.add(database("Frozen candidate evidence", EDGE_SQL, PINS))
    merge = (
        ENDPOINT_CHECK
        + f"""
MERGE (p)-[r:INFERRED_NCS_OCCUPATION {{candidate_id:$candidate_id}}]->(o)
SET r.managed_by='{MANAGER}',r.payload_json=$payload_json,r.payload_hash=$payload_hash,
r.job_run_id=$jobs,r.ncs_run_id=$ncs,r.projection_token=$graph_token,
r.basis='METADATA_INFERRED',r.assertion_kind='MODEL_INFERRED',
r.serving_scope='STAGING',r.stage='STAGING',r.projection_state='LOADING',r.current=false,
r.review_status=$review_status,r.confidence=null,r.confidence_state=$confidence_state,
r.accepted=$accepted,r.result_id=$result_id,r.bundle_id=$bundle_id,r.source_hash=$source_hash,
r.binding_hash=$binding_hash,r.catalog_hash=$catalog_hash,
r.occupation_scheme=$occupation_scheme,r.match_rank=$match_rank,r.rank_basis=$rank_basis,
r.original_primary=$original_primary,r.current_primary=$current_primary
RETURN count(r)=1 AS verified"""
    )
    p.add(cypher("Merge inferred occupation", merge, EDGE_ARGS))
    verify(p)
    p.save("load_inferred_occupation_graph")

    p = Pipeline(
        "verify_inferred_occupation_graph", "Read back every exact edge and evidence hash."
    )
    p.add(options())
    p.add(
        execute(
            "Recheck immutable projection",
            "SELECT enrichment.check_metadata_occupation_graph(?)",
            ["graph_token"],
        )
    )
    p.add(database("Expected candidate evidence", EDGE_SQL, PINS))
    readback = (
        ENDPOINT_CHECK
        + f"""
MATCH (p)-[r:INFERRED_NCS_OCCUPATION {{candidate_id:$candidate_id,managed_by:'{MANAGER}'}}]->(o)
WHERE {EDGE_CHECK}
RETURN count(r)=1 AS verified"""
    )
    p.add(cypher("Verify inferred evidence", readback, EDGE_ARGS, readonly=True))
    verify(p)
    p.save("verify_inferred_occupation_graph")

    p = Pipeline(
        "finish_inferred_occupation_graph", "Verify totals without activating a serving release."
    )
    p.add(options())
    p.add(
        execute(
            "Recheck unchanged source and decisions",
            "SELECT enrichment.check_metadata_occupation_graph(?)",
            ["graph_token"],
        )
    )
    p.add(database("Expected exact total", STATE_SQL, STATE_ARGS))
    total_prefix = f"""MATCH (m:metadataOccupationProjection {{id:$projection_id,
managed_by:'{MANAGER}',projection_token:$graph_token,state:'LOADING'}})
WHERE m.projection_hash=$projection_hash AND m.serving_scope='STAGING'
OPTIONAL MATCH ()-[r:INFERRED_NCS_OCCUPATION {{managed_by:'{MANAGER}',
job_run_id:$jobs,ncs_run_id:$ncs,projection_token:$graph_token}}]->()
WITH m,collect(r) AS edges WHERE size(edges)=$expected_count
"""
    p.add(
        cypher(
            "Read only exact totals",
            total_prefix + "RETURN count(m)=1 AS verified",
            STATE_CYPHER_ARGS,
            readonly=True,
        )
    )
    # A second filtered read excludes marker mutation if counts failed.
    verify(p)
    # Continue success path after the verify helper's terminal Dummy.
    p.add(
        cypher(
            "Finish verified staging projection",
            total_prefix
            + """
FOREACH (r IN edges | SET r.current=true,r.projection_state='VERIFIED')
SET m.state='VERIFIED',m.edge_count=$expected_count
RETURN count(m)=1 AS finished""",
            STATE_CYPHER_ARGS,
            result_field="finished",
        )
    )
    verify(p, prefix="Finish ", field="finished")
    # SQL final check will reject concurrent drift even after graph verification.
    p.add(
        execute(
            "Release only own writer",
            "SELECT enrichment.finish_metadata_occupation_graph(?,false)",
            ["graph_token"],
        )
    )
    p.save("finish_inferred_occupation_graph")

    p = Pipeline(
        "fail_inferred_occupation_graph", "Fail only this token and release its own writer."
    )
    p.add(options())
    p.add(
        cypher(
            "Mark own projection failed",
            f"""
OPTIONAL MATCH (m:metadataOccupationProjection {{managed_by:'{MANAGER}',
projection_token:$graph_token}})
SET m.state='FAILED'
WITH m OPTIONAL MATCH ()-[r:INFERRED_NCS_OCCUPATION {{managed_by:'{MANAGER}',
projection_token:$graph_token}}]->()
SET r.current=false,r.projection_state='FAILED'
RETURN true AS verified""",
            [("graph_token", "String")],
        )
    )
    p.add(
        execute(
            "Release failed own writer",
            "SELECT enrichment.finish_metadata_occupation_graph(?,true)",
            ["graph_token"],
        )
    )
    p.save("fail_inferred_occupation_graph")

    parameters = [
        ("JOB_RUN_ID", "", "Exact accepted READY JobKorea run; latest aliases are forbidden."),
        ("NCS_RUN_ID", "", "Exact accepted READY NCS run with both source proofs verified."),
        (
            "INCLUDE_UNREVIEWED",
            "N",
            "Y includes clearly marked validated unreviewed metadata inferences.",
        ),
        ("NEO4J_CONNECTION", "jobtology-neo4j", "Existing protected native graph connection."),
    ]
    steps = [
        ("Acquire exact graph writer", "acquire_inferred_occupation_graph"),
        ("Check source graphs and begin staging", "begin_inferred_occupation_graph"),
        ("Load separate inferred occupations", "load_inferred_occupation_graph"),
        ("Read back exact inference evidence", "verify_inferred_occupation_graph"),
        ("Verify totals and release writer", "finish_inferred_occupation_graph"),
    ]
    workflow(
        "publish_inferred_occupations",
        "Project labeled metadata occupation inferences in STAGING",
        [(label, "ingestions/jobkorea/" + name + ".hpl") for label, name in steps],
        parameters,
    )
    path = OUT / "publish_inferred_occupations.hwf"
    root = E.parse(path).getroot()
    actions = root.find("actions")
    failure = deepcopy(root.find("actions/action[type='PIPELINE']"))
    put(failure, "name", "Fail own inference projection")
    put(
        failure,
        "filename",
        "${PROJECT_HOME}/ingestions/jobkorea/fail_inferred_occupation_graph.hpl",
    )
    actions.append(failure)
    hops = root.find("hops")
    for hop in hops:
        if hop.findtext("to") == "Abort" and hop.findtext("from") != steps[0][0]:
            put(hop, "to", "Fail own inference projection")
    for evaluation in ("Y", "N"):
        child(
            hops,
            "hop",
            {
                "from": "Fail own inference projection",
                "to": "Abort",
                "enabled": "Y",
                "evaluation": evaluation,
                "unconditional": "N",
            },
        )
    save(root, path)


def build_focused_installer():
    """Replay only additive contracts; older model/accounting SQL is untouched."""
    root = E.parse(OUT / "install_inferred_occupations.hwf").getroot()
    put(root, "name", "Install batch-free graph consumers")
    put(
        root,
        "description",
        "Requires existing source, LLM and retention modules. Replays only graph evidence, "
        "batch-free retention and inference publication SQL; no requests.",
    )
    actions = root.find("actions")
    template = deepcopy(actions.find("action[type='SQL']"))
    for node in list(actions):
        if node.findtext("type") not in ("SPECIAL", "SUCCESS", "ABORT"):
            actions.remove(node)
    action = child(
        actions,
        "action",
        {
            "name": "Install graph proof contracts",
            "type": "WORKFLOW",
            "filename": "${PROJECT_HOME}/graph/install.hwf",
            "run_configuration": "jobkorea-local",
            "wait_until_finished": "Y",
            "xloc": 320,
            "yloc": 100,
            "draw": "Y",
            "parallel": "N",
        },
    )
    child(E.SubElement(action, "parameters"), "pass_all_parameters", {})
    put(action.find("parameters"), "pass_all_parameters", "Y")
    steps = ["Start", "Install graph proof contracts"]
    for name, filename in [
        ("Install batch-free retention", "retention/sql/002_batchfree_retention.sql"),
        ("Install batch-free inference publication", "llm/sql/036_batchfree_graph_publication.sql"),
        ("Preserve opt-in multi-match dispatch", "llm/sql/037_metadata_occupation_multimatch.sql"),
    ]:
        node = deepcopy(template)
        put(node, "name", name)
        put(node, "sqlfilename", "${PROJECT_HOME}/" + filename)
        actions.append(node)
        steps.append(name)
    hops = root.find("hops")
    hops.clear()
    for index, name in enumerate(steps):
        target = steps[index + 1] if index + 1 < len(steps) else "Success"
        child(
            hops,
            "hop",
            {
                "from": name,
                "to": target,
                "enabled": "Y",
                "evaluation": "Y",
                "unconditional": "Y" if index == 0 else "N",
            },
        )
        if index:
            child(
                hops,
                "hop",
                {
                    "from": name,
                    "to": "Abort",
                    "enabled": "Y",
                    "evaluation": "N",
                    "unconditional": "N",
                },
            )
    save(root, OUT / "install_batchfree_graph_publication.hwf")


if __name__ == "__main__":
    build()
    build_focused_installer()
