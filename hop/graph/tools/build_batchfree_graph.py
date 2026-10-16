"""Generate the permanent PostgreSQL-ledger/business-graph Hop workflows."""
# SQL/Cypher literals mirror generated native artifacts.
# ruff: noqa: E501

import argparse
import itertools
import re
import xml.etree.ElementTree as E
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "hop/graph"
ENTITY_FIELDS = (
    "identity_id",
    "kind",
    "code",
    "entity_name",
    "entity_title",
    "name_source_run_id",
    "name_source_record_id",
    "source_id",
    "source_run_id",
    "source_record_id",
    "source_created_at",
    "source_facts_json",
    "source_facts_sha256",
)
EDGE_FIELDS = (
    "owner_id",
    "source_id",
    "source_run_id",
    "source_record_id",
    "from_id",
    "to_id",
    "edge_kind",
    "edge_key",
    "edge_facts_json",
)
EDGE_TYPES = (
    "EMPLOYER",
    "CLASSIFIED_AS",
    "HAS_CAREER_COMPETENCY",
    "QUALIFICATION_MAPPING",
    "HAS_EXAM_SESSION",
)
ENTITY_BATCH_SIZE = 500


def put(node, key, value):
    child = node.find(key)
    if child is None:
        child = E.SubElement(node, key)
    child.text = str(value)


def save(node, name):
    E.indent(node, space="  ")
    E.ElementTree(node).write(OUT / name, encoding="UTF-8", xml_declaration=True)


def hop(parent, source, target, evaluation="Y", unconditional="N"):
    row = E.SubElement(parent, "hop")
    for key, value in (("from", source), ("to", target), ("enabled", "Y")):
        put(row, key, value)
    if parent.tag == "hops":
        put(row, "evaluation", evaluation)
        put(row, "unconditional", unconditional)


def params(node, fields, tag="parameter"):
    parent = node.find(tag)
    if parent is None:
        parent = E.SubElement(node, tag)
    parent.clear()
    for field, datatype in fields:
        row = E.SubElement(parent, "field")
        put(row, "name", field)
        put(row, "type", datatype)


def cypher_transform(node, cypher, fields, read_only, batched=False, per_row=False):
    if per_row and not batched:
        raise ValueError("Per-owner checks require bounded row batching")
    if batched:
        # Hop sends the last partial batch too. Count every supplied row rather
        # than accepting a batch when just one valid identity survives WHERE.
        cypher = "UNWIND $rows AS row\n" + cypher
        names = {field for field, _ in fields}
        cypher = re.sub(
            r"\$([A-Za-z_][A-Za-z_0-9]*)",
            lambda match: "row." + match[1] if match[1] in names else match[0],
            cypher,
        )
        put(node, "unwind_map", "rows")
    elif node.find("unwind_map") is not None:
        node.remove(node.find("unwind_map"))
    if per_row:
        # A subquery emits one Boolean even when MATCH finds no owner. Imported
        # row scope survives inner WITH clauses, and repeated input rows remain
        # distinct calls rather than collapsing in a grouped aggregate.
        prefix, body = cypher.split("\n", 1)
        cypher = (
            prefix + "\nCALL (row) {\n" + body
            + "\nRETURN count(i)=1 AS row_matches\n}"
            + "\nRETURN size($rows)>0 AND count(*)=size($rows) "
            + "AND all(matched IN collect(row_matches) WHERE matched) AS entity_matches"
        )
    else:
        expected = "size($rows)" if batched else "1"
        cypher += f"\nRETURN count(i)={expected} AS entity_matches"
    put(node, "cypher", cypher)
    put(node, "batch_size", ENTITY_BATCH_SIZE if batched else 1)
    put(node, "unwind", "Y" if batched else "N")
    put(node, "read_only", "Y" if read_only else "N")
    node.find("mappings").clear()
    for field, datatype in fields:
        row = E.SubElement(node.find("mappings"), "mapping")
        for key, value in (("parameter", field), ("field", field), ("type", datatype)):
            put(row, key, value)


def pipeline(template, name, sql, cypher=None, fields=(), read_only=False, batched=False,
             per_row=False):
    p = deepcopy(template)
    put(p.find("info"), "name", name)
    put(
        p.find("info"),
        "description",
        "Batch-free source graph; immutable membership remains in PostgreSQL.",
    )
    query = p.find("transform[name='Read entity names']")
    put(query, "sql", sql)
    output = p.find("transform[name='Set entity names']")
    if cypher is None:
        p.remove(output)
    else:
        cypher_transform(output, cypher, fields, read_only, batched, per_row)
    order = p.find("order")
    order.clear()
    hop(order, "Snapshot", "Read entity names")
    if cypher is not None:
        hop(order, "Read entity names", "Set entity names")
        hop(order, "Set entity names", "Check result")
    else:
        hop(order, "Read entity names", "Check result")
    hop(order, "Check result", "Complete")
    hop(order, "Check result", "Check failed")
    put(
        p.find("transform[name='Check failed']"),
        "message",
        "Source business projection differs from accepted PostgreSQL evidence; replay exact RUN_ID.",
    )
    save(p, name + ".hpl")
    return p


def owner_cleanup(template):
    pipeline(
        template,
        "clear_source_edges",
        "SELECT * FROM ingestion.graph_source_edge_owners(?)",
        'MATCH (i:entity {id:$owner_id})\nOPTIONAL MATCH (i)-[r]-() WHERE r.source_graph=true AND r.owner_id=$owner_id AND r.source_id=$source_id AND NOT r.edge_key IN split($expected_edge_keys,",")\nWITH i,collect(r) AS old_edges FOREACH (r IN old_edges | DELETE r)',
        [("owner_id", "String"), ("source_id", "String"), ("expected_edge_keys", "String")],
        batched=True,
        per_row=True,
    )


def owner_totals(template):
    pipeline(
        template,
        "verify_totals",
        "SELECT owner_id,source_id,CASE WHEN expected_edge_keys='' THEN 0 "
        "ELSE array_length(string_to_array(expected_edge_keys,','),1) END::bigint AS expected_edges "
        "FROM ingestion.graph_source_edge_owners(?)",
        "MATCH (i:entity {id:$owner_id})\nOPTIONAL MATCH (i)-[r]-() WHERE r.source_graph=true AND r.owner_id=$owner_id AND r.source_id=$source_id\nWITH i,count(r) AS actual_edges WHERE actual_edges=$expected_edges",
        [("owner_id", "String"), ("source_id", "String"), ("expected_edges", "Integer")],
        True,
        batched=True,
        per_row=True,
    )


def build_owner_batches():
    """Regenerate only the two owner pipelines, leaving every other byte alone."""
    template = E.parse(OUT / "load_entity_names.hpl").getroot()
    owner_cleanup(template)
    owner_totals(template)


def build():
    template = E.parse(OUT / "load_entity_names.hpl").getroot()
    fields = [(field, "String") for field in ENTITY_FIELDS]
    labels = "".join(
        f"\nFOREACH (_ IN CASE WHEN i.kind='{kind}' THEN [1] ELSE [] END | SET i:{label})"
        for kind, label in (
            ("Organization", "organization"),
            ("JobPosting", "jobPosting"),
            ("Occupation", "occupation"),
            ("Competency", "ncsCompetency"),
            ("Qualification", "qualification"),
            ("ExamSession", "examSession"),
        )
    )
    matching = "i.kind=$kind AND i.code=$code"
    label_check = " OR ".join(
        f"(i.kind='{kind}' AND '{label}' IN labels(i))"
        for kind, label in (
            ("Organization", "organization"),
            ("JobPosting", "jobPosting"),
            ("Occupation", "occupation"),
            ("Competency", "ncsCompetency"),
            ("Qualification", "qualification"),
            ("ExamSession", "examSession"),
        )
    )
    assignments = (
        "i.name=$entity_name,i.title=$entity_title,i.name_source_run_id=$name_source_run_id,"
        "i.name_source_record_id=$name_source_record_id,\n"
        "i.source_id=$source_id,i.source_run_id=$source_run_id,i.source_record_id=$source_record_id,\n"
        "i.source_created_at=datetime($source_created_at),i.source_facts_json=$source_facts_json,"
        "i.source_facts_sha256=$source_facts_sha256"
    )
    entity_sql = "SELECT * FROM ingestion.graph_source_entities(?)"
    load = (
        "MERGE (i:entity {id:$identity_id}) ON CREATE SET i.kind=$kind,i.code=$code\nWITH row,i WHERE "
        + matching
        + labels
        + "\nSET "
        + assignments
    )
    verify = (
        "MATCH (i:entity {id:$identity_id}) WHERE "
        + matching
        + " AND ("
        + label_check
        + ")\nAND "
        + " AND ".join(
            f"((properties(i)['{prop}'] IS NULL AND ${field} IS NULL) OR i.{prop}={expr})"
            for prop, field, expr in (
                ("name", "entity_name", "$entity_name"),
                ("title", "entity_title", "$entity_title"),
                ("name_source_run_id", "name_source_run_id", "$name_source_run_id"),
                ("name_source_record_id", "name_source_record_id", "$name_source_record_id"),
                ("source_id", "source_id", "$source_id"),
                ("source_run_id", "source_run_id", "$source_run_id"),
                ("source_record_id", "source_record_id", "$source_record_id"),
                ("source_created_at", "source_created_at", "datetime($source_created_at)"),
                ("source_facts_json", "source_facts_json", "$source_facts_json"),
                ("source_facts_sha256", "source_facts_sha256", "$source_facts_sha256"),
            )
        )
    )
    # Compatibility entrypoints cannot recreate the retired record layer.
    for name in ("load_records", "load_entity_names"):
        pipeline(template, name, entity_sql, load, fields, batched=True)
    for name in ("verify_records", "verify_entity_names"):
        pipeline(template, name, entity_sql, verify, fields, True, batched=True)
    pipeline(
        template,
        "begin_batch",
        "SELECT CASE WHEN ?='ALL_CHECKPOINTED' THEN ingestion.begin_source_graph_migration() "
        "ELSE ingestion.begin_source_graph_projection(?) END AS entity_matches",
    )
    pipeline(
        template,
        "finish_batch",
        "SELECT CASE WHEN ?='ALL_CHECKPOINTED' THEN ingestion.finish_source_graph_migration() "
        "ELSE ingestion.finish_source_graph_projection(?) END AS entity_matches",
    )
    pipeline(
        template,
        "mark_failed",
        "SELECT CASE WHEN ?='ALL_CHECKPOINTED' THEN ingestion.fail_source_graph_migration() "
        "ELSE ingestion.fail_source_graph_projection(?) END AS entity_matches",
    )
    for name in ("begin_batch", "finish_batch", "mark_failed"):
        p = E.parse(OUT / (name + ".hpl")).getroot()
        params(
            p.find("transform[name='Read entity names']"),
            [("run_id", "String"), ("run_id", "String")],
        )
        save(p, name + ".hpl")
    owner_cleanup(template)
    edge_props = (
        "r.source_graph=true,r.owner_id=$owner_id,r.source_id=$source_id,"
        "r.source_run_id=$source_run_id,r.source_record_id=$source_record_id,"
        "r.facts_json=$edge_facts_json"
    )
    edge_load = "MATCH (a:entity {id:$from_id}) WITH a MATCH (b:entity {id:$to_id})\n"
    for kind in EDGE_TYPES:
        edge_load += f"FOREACH (_ IN CASE WHEN $edge_kind='{kind}' THEN [1] ELSE [] END | MERGE (a)-[r:{kind} {{edge_key:$edge_key}}]->(b) SET {edge_props})\n"
    edge_load += "WITH a,b MATCH (a)-[i]->(b) WHERE i.edge_key=$edge_key AND i.source_graph=true"
    edge_verify = (
        "MATCH (a:entity {id:$from_id})-[i]->(b:entity {id:$to_id})\n"
        "WHERE type(i)=$edge_kind AND i.edge_key=$edge_key AND i.source_graph=true "
        "AND i.owner_id=$owner_id AND i.source_id=$source_id AND i.source_run_id=$source_run_id "
        "AND i.source_record_id=$source_record_id AND i.facts_json=$edge_facts_json"
    )
    fields = [(field, "String") for field in EDGE_FIELDS]
    edge_sql = "SELECT * FROM ingestion.graph_source_edges(?)"
    pipeline(template, "load_references", edge_sql, edge_load, fields)
    pipeline(template, "verify_references", edge_sql, edge_verify, fields, True)
    owner_totals(template)
    # Keep only stable entity uniqueness; legacy label upgrade has no batch writes.
    p = E.parse(OUT / "constraints.hpl").getroot()
    keep = (
        "Snapshot",
        "Inspect identity",
        "identity uniqueness exists",
        "identity name available",
        "Create identity constraint",
        "Constraint conflict",
        "Constraints complete",
    )
    for t in list(p.findall("transform")):
        if t.findtext("name") not in keep:
            p.remove(t)
    p.find("order").clear()
    for source, target in (
        ("Snapshot", "Inspect identity"),
        ("Inspect identity", "identity uniqueness exists"),
        ("identity uniqueness exists", "identity name available"),
        ("identity uniqueness exists", "Constraints complete"),
        ("identity name available", "Create identity constraint"),
        ("identity name available", "Constraint conflict"),
        ("Create identity constraint", "Constraints complete"),
    ):
        hop(p.find("order"), source, target)
    save(p, "constraints.hpl")
    p = deepcopy(template)
    put(p.find("info"), "name", "upgrade_labels")
    put(
        p.find("info"),
        "description",
        "Relabel only stable business identities; graph history labels are retired by the migration operator.",
    )
    for t in list(p.findall("transform")):
        if t.findtext("name") not in ("Snapshot", "Set entity names"):
            p.remove(t)
    p.find("order").clear()
    hop(p.find("order"), "Snapshot", "Set entity names")
    cypher_transform(
        p.find("transform[name='Set entity names']"),
        "MATCH (i) WHERE 'HopMigrationIdentity' IN labels(i) SET i:entity REMOVE i:HopMigrationIdentity"
        + labels,
        [],
        False,
    )
    save(p, "upgrade_labels.hpl")
    # Existing action names preserve native wrappers and date generator contracts.
    w = E.parse(OUT / "load_snapshot.hwf").getroot()
    actions = w.find("actions")
    if actions.find("action[name='Clear current source relationships']") is None:
        a = deepcopy(actions.find("action[name='Load identity references']"))
        put(a, "name", "Clear current source relationships")
        put(a, "filename", "${PROJECT_HOME}/graph/clear_source_edges.hpl")
        actions.append(a)
    for a in list(actions):
        if a.findtext("name") in ("Load source records", "Verify record properties"):
            actions.remove(a)
    steps = [
        "Start",
        "Enter retention writer guard",
        "Validate PostgreSQL snapshot",
        "Ensure graph constraints",
        "Upgrade legacy labels",
        "Begin graph batch",
        "Set readable entity names",
        "Set posting ingestion dates",
        "Clear current source relationships",
        "Load identity references",
        "Verify identity references",
        "Verify entity names",
        "Verify posting ingestion dates",
        "Verify graph membership",
        "Accept graph snapshot",
        "Leave retention writer guard",
        "Success",
    ]
    w.find("hops").clear()
    for source, target in itertools.pairwise(steps):
        hop(w.find("hops"), source, target, unconditional="Y" if source == "Start" else "N")
        if source not in ("Start", "Leave retention writer guard"):
            failure = (
                "Release failed graph writer"
                if source in ("Enter retention writer guard", "Validate PostgreSQL snapshot")
                else "Record graph failure"
            )
            hop(w.find("hops"), source, failure, "N")
    hop(w.find("hops"), "Record graph failure", "Release failed graph writer", unconditional="Y")
    hop(w.find("hops"), "Release failed graph writer", "Abort", unconditional="Y")
    put(
        actions.find("action[name='Abort']"),
        "message",
        "Source graph failed; PostgreSQL evidence/checkpoints retain exact replay scope.",
    )
    save(w, "load_snapshot.hwf")
    snapshot = E.parse(OUT / "check_snapshot.hpl").getroot()
    check = snapshot.find("transform[name='Read accepted snapshot']/sql")
    check.text = check.text.replace(
        "ingestion.validation_issue v WHERE v.run_id=i.run_id",
        "ingestion.source_graph_validation_issue(i.run_id) v",
    )
    save(snapshot, "check_snapshot.hpl")
    # Write current entities once for the complete existing graph, preserve dates.
    m = deepcopy(w)
    put(m, "name", "Migrate all checkpointed source identities to a batch-free graph")
    parameter = m.find("parameters/parameter[name='RUN_ID']")
    put(parameter, "default_value", "ALL_CHECKPOINTED")
    for a in list(m.find("actions")):
        if a.findtext("name") in (
            "Validate PostgreSQL snapshot",
            "Set posting ingestion dates",
            "Verify posting ingestion dates",
            "Load source records",
            "Verify record properties",
        ):
            m.find("actions").remove(a)
    m.find("hops").clear()
    steps = [
        s
        for s in steps
        if s
        not in (
            "Validate PostgreSQL snapshot",
            "Set posting ingestion dates",
            "Verify posting ingestion dates",
            "Load source records",
            "Verify record properties",
        )
    ]
    for source, target in itertools.pairwise(steps):
        hop(m.find("hops"), source, target, unconditional="Y" if source == "Start" else "N")
        if source not in ("Start", "Leave retention writer guard"):
            hop(
                m.find("hops"),
                source,
                "Release failed graph writer"
                if source == "Enter retention writer guard"
                else "Record graph failure",
                "N",
            )
    hop(m.find("hops"), "Record graph failure", "Release failed graph writer", unconditional="Y")
    hop(m.find("hops"), "Release failed graph writer", "Abort", unconditional="Y")
    save(m, "migrate_source_graph.hwf")
    # Minimal canonical source-only SQL installer.
    installer = E.parse(OUT / "install_posting_dates.hwf").getroot()
    action = installer.find("actions/action[type='SQL']")
    actions = installer.find("actions")
    # The focused date installer carries the complete canonical migration chain.
    # Rebuild this chain from its first SQL action without duplicating successors.
    for existing in list(actions):
        if existing is not action and existing.findtext("type") == "SQL":
            actions.remove(existing)
    new = deepcopy(action)
    put(new, "name", "Install permanent source business graph SQL")
    put(new, "sqlfilename", "${PROJECT_HOME}/graph/sql/002_batchfree_source_graph.sql")
    actions.append(new)
    optimized = deepcopy(action)
    put(optimized, "name", "Install query-local source validation and selection")
    put(optimized, "sqlfilename", "${PROJECT_HOME}/graph/sql/003_source_query_sharing.sql")
    actions.append(optimized)
    replay = deepcopy(action)
    put(replay, "name", "Install verified source proof replay")
    put(replay, "sqlfilename", "${PROJECT_HOME}/graph/sql/004_verified_proof_replay.sql")
    actions.append(replay)
    worksets = deepcopy(action)
    put(worksets, "name", "Install scoped validation worksets")
    put(worksets, "sqlfilename", "${PROJECT_HOME}/graph/sql/005_validation_worksets.sql")
    actions.append(worksets)
    jobalio = deepcopy(action)
    put(jobalio, "name", "Install JOB-ALIO validation worksets")
    put(jobalio, "sqlfilename", "${PROJECT_HOME}/graph/sql/006_jobalio_validation_worksets.sql")
    actions.append(jobalio)
    capture = deepcopy(action)
    put(capture, "name", "Install capture guard worksets")
    put(capture, "sqlfilename", "${PROJECT_HOME}/graph/sql/007_capture_guard_worksets.sql")
    actions.append(capture)
    readers = deepcopy(action)
    put(readers, "name", "Install source reader worksets")
    put(readers, "sqlfilename", "${PROJECT_HOME}/graph/sql/008_reader_worksets.sql")
    actions.append(readers)
    facts = deepcopy(action)
    put(facts, "name", "Install entity reader fact worksets")
    put(facts, "sqlfilename", "${PROJECT_HOME}/graph/sql/009_reader_fact_worksets.sql")
    actions.append(facts)
    installer.find("hops").clear()
    for source, target in (
        ("Start", action.findtext("name")),
        (action.findtext("name"), new.findtext("name")),
        (new.findtext("name"), optimized.findtext("name")),
        (optimized.findtext("name"), replay.findtext("name")),
        (replay.findtext("name"), worksets.findtext("name")),
        (worksets.findtext("name"), jobalio.findtext("name")),
        (jobalio.findtext("name"), capture.findtext("name")),
        (capture.findtext("name"), readers.findtext("name")),
        (readers.findtext("name"), facts.findtext("name")),
        (facts.findtext("name"), "Success"),
    ):
        hop(installer.find("hops"), source, target, unconditional="Y" if source == "Start" else "N")
    for a in (action, new, optimized, replay, worksets, jobalio, capture, readers, facts):
        hop(installer.find("hops"), a.findtext("name"), "Abort", "N")
    put(installer, "name", "Install permanent batch-free source graph contracts")
    save(installer, "install.hwf")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-batches-only", action="store_true")
    args = parser.parse_args()
    if args.owner_batches_only:
        build_owner_batches()
    else:
        build()
