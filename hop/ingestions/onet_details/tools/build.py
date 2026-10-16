"""Generate additive native details workflows using the qualified scalar transport."""

# ruff: noqa: E501
import importlib.util
import xml.etree.ElementTree as E
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / "hop/ingestions/onet_details"
SPEC = importlib.util.spec_from_file_location(
    "onet_catalogue_build", ROOT / "hop/ingestions/onet/tools/build.py"
)
assert SPEC and SPEC.loader
b = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(b)
OWNER = "jobtology-onet-details-v1"
PREFIX = "urn:jobtology:onet-detail:"
TYPES = "['ONET_DETAIL_PARENT','ONET_SOFTWARE_EXAMPLE','ONET_SOFTWARE_TYPE','ONET_ESSENTIAL_SKILL','ONET_TRANSFERABLE_SKILL','ONET_KNOWLEDGE','ONET_TASK','ONET_TASK_RATING','ONET_ANCHOR_ELEMENT','ONET_ANCHOR_SCALE','ONET_CATEGORY_SCALE']"


def adapt(text):
    text = (
        text.replace("classification.", "onet_detail.")
        .replace("jobtology-onet-catalog-v1", OWNER)
        .replace("urn:jobtology:onet:", PREFIX)
        .replace("onetCatalogObject", "onetDetail")
        .replace("/ingestions/onet/", "/ingestions/onet_details/")
    )
    text = text.replace("type(r) IN ['IN_SCHEME','BROADER']", f"type(r) IN {TYPES}")
    text = text.replace(
        f"startNode(r).managed_by='{OWNER}'",
        f"(startNode(r).managed_by='{OWNER}' OR (startNode(r).managed_by='jobtology-onet-catalog-v1' AND startNode(r):occupation))",
    )
    text = text.replace(
        f"a.managed_by='{OWNER}' AND b.managed_by='{OWNER}'",
        f"(a.managed_by='{OWNER}' OR (a.managed_by='jobtology-onet-catalog-v1' AND a:occupation)) AND b.managed_by='{OWNER}'",
    )
    return text


def save(node, name):
    E.indent(node, space="  ")
    text = adapt(E.tostring(node, encoding="unicode"))
    (OUT / name).write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + text)


b.OUT = OUT
b.save = save
# Generation itself retains old globals so a single strict serialization rewrite
# adjusts namespaces. Reuse of helpers makes primitive transport byte-identical.
b.LOCAL_JAVA = (
    b.LOCAL_JAVA.replace('payload.path("sources").size()==3', 'payload.path("sources").size()==10')
    .replace("boundedRead(archived,16777216)", "boundedRead(archived,67108864)")
    .replace('payload.path("terms").size()', 'payload.path("nodes").size()')
)

b.LOCAL_JAVA = (
    b.LOCAL_JAVA.replace(
        'stage="DATABASE_IMPORT_FAILED";',
        'byte[] baseBytes=boundedRead(evidence.resolve("base_catalogue.json"),16777216);\n'
        '    require(payload.path("base_catalogue_sha256").asText().equals(digest(baseBytes)),"BASE_CATALOGUE_BYTES_MISMATCH");\n'
        '    stage="DATABASE_IMPORT_FAILED";',
    )
    .replace("import_onet_catalog(?::jsonb)", "import_onet_catalog(?::jsonb,?)")
    .replace(
        "statement.setString(1,new String(bytes,java.nio.charset.StandardCharsets.UTF_8));",
        "statement.setString(1,new String(bytes,java.nio.charset.StandardCharsets.UTF_8));\n"
        "      statement.setString(2,new String(baseBytes,java.nio.charset.StandardCharsets.UTF_8));",
    )
)

b.LOCAL_JAVA = (
    b.LOCAL_JAVA.replace('receipt.path("url")', 'receipt.path("source_uri")')
    .replace('receipt.path("byte_count")', 'receipt.path("byte_length")')
    .replace('receipt.path("retrieved_at")', 'receipt.path("downloaded_at")')
)


# Collect only IDs in this bounded batch. The full reserved namespace gate still
# precedes every mutation; colliding type/endpoints/duplicate IDs remain visible.
b.EDGE_PREFLIGHT_PREFIX = b.EDGE_PREFLIGHT_PREFIX.replace(
    "WHERE object.id STARTS WITH '" + b.NAMESPACE + "' OR object.managed_by='" + b.OWNER + "'",
    "WHERE (object.id STARTS WITH '" + b.NAMESPACE + "' OR object.managed_by='" + b.OWNER + "')\n"
    " AND object.id IN [batch_row IN $rows | batch_row.edge_id]",
)


def build():
    b.build_import()
    b.build_graph()
    # Freeze occupation properties in PG plan once, then use normal full typed verifier.
    p = b.Pipeline(
        "graph_preflight_occupations",
        "Verify exact existing catalogue occupations without changing them.",
    )
    p.add(b.token())
    p.add(
        b.database(
            "Require readable pinned endpoint plan",
            "SELECT classification.assert_readable_graph_load(?) AS checked_token",
            [("load_id", "String")],
        )
    )
    sql = b.rendered_rows("nodes").replace(
        "classification.graph_load_nodes", "classification.graph_load_occupations"
    )
    p.add(b.database("Read pinned catalogue endpoints", sql, [("load_id", "String")]))
    q = f"""OPTIONAL MATCH (object:entity {{id:row.node_id}})
RETURN count(object)=size($rows) AND count(DISTINCT row.node_id)=size($rows)
AND all(ok IN collect(coalesce(({b.EXPECTED}) AND ({b.NODE_LABELS}),false)) WHERE ok) AS verified"""
    p.add(
        b.cypher(
            "Verify complete typed catalogue endpoints",
            b.PREFIX + b.DECODE + q,
            b.NODE_FIELDS,
            True,
            True,
        )
    )
    b.require_result(p)
    p.save()
    steps = [
        ("Acquire exact details writer", "graph_start.hpl"),
        ("Preflight detail namespace", "graph_preflight_scope.hpl"),
        ("Verify existing catalogue occupations", "graph_preflight_occupations.hpl"),
        ("Preflight all detail nodes", "graph_preflight_nodes.hpl"),
        ("Preflight all detail relationships", "graph_preflight_edges.hpl"),
        ("Require entity identity uniqueness", "graph_constraint.hpl"),
        ("Write detail reference nodes", "graph_nodes.hpl"),
        ("Write official detail associations", "graph_edges.hpl"),
        ("Verify every typed detail node", "graph_verify_nodes.hpl"),
        ("Verify every typed detail relationship", "graph_verify_edges.hpl"),
        ("Verify occupations remain exact", "graph_preflight_occupations.hpl"),
        ("Checkpoint complete details graph", "graph_finish.hpl"),
        ("Select verified details", "graph_activate.hpl"),
    ]
    b.workflow(
        "load_details",
        "Load frozen official O*NET reference details; existing occupations and postings remain unchanged.",
        [("Import exact local details", "import_local.hpl"), *steps],
        b.IMPORT_PARAMETERS + b.PARAMETERS,
        True,
    )
    b.workflow(
        "replay_details",
        "Replay an immutable READY detail release through full native verification.",
        steps,
        b.PARAMETERS,
        True,
    )
    b.workflow(
        "verify_details",
        "Read-only exact detail inventory and occupation endpoint verification.",
        [
            ("Require verified details token", "graph_require_verified.hpl"),
            ("Verify every typed detail node", "graph_verify_nodes.hpl"),
            ("Verify every typed detail relationship", "graph_verify_edges.hpl"),
            ("Verify catalogue endpoints", "graph_preflight_occupations.hpl"),
            ("Verify complete detail scope", "graph_verify_scope.hpl"),
        ],
        [("ONET_LOAD_ID", "", "Explicit verified detail graph load token."), *b.PARAMETERS],
    )
    # Reuse installer template without invoking old workflow generation.
    root = E.parse(ROOT / "hop/ingestions/onet/install.hwf").getroot()
    b.put(root, "name", "Install additive official O*NET detail schema")
    actions = root.find("actions")
    for action in list(actions):
        if action.findtext("type") == "SQL":
            actions.remove(action)
    start = root.find("hops")
    start.clear()
    names = ["Start"]
    template = (
        E.parse(ROOT / "hop/ingestions/onet/install.hwf")
        .getroot()
        .find("actions/action[type='SQL']")
    )
    from copy import deepcopy

    for file in sorted((OUT / "sql").glob("*.sql")):
        action = deepcopy(template)
        label = "Install details " + file.stem
        b.put(action, "name", label)
        b.put(action, "sqlfilename", "${PROJECT_HOME}/ingestions/onet_details/sql/" + file.name)
        actions.append(action)
        names.append(label)
    names.append("Success")
    for i, name in enumerate(names[:-1]):
        b.child(
            start,
            "hop",
            {
                "from": name,
                "to": names[i + 1],
                "enabled": "Y",
                "evaluation": "Y",
                "unconditional": "Y" if i == 0 else "N",
            },
        )
        if i:
            b.child(
                start,
                "hop",
                {
                    "from": name,
                    "to": "Abort",
                    "enabled": "Y",
                    "evaluation": "N",
                    "unconditional": "N",
                },
            )
    save(root, "install.hwf")
    # A details load may exceed the catalogue's 16MiB default bound.
    for file in OUT.glob("*.hwf"):
        text = file.read_text().replace(
            "<default_value>16777216</default_value>", "<default_value>67108864</default_value>"
        )
        file.write_text(text)


if __name__ == "__main__":
    build()
