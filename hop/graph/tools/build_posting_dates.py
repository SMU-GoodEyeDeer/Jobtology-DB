"""Generate native identity-date workflows without touching source graph facts."""

import re
import xml.etree.ElementTree as E
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "hop/graph"
DATE_BATCH_SIZE = 500
FIELDS = (
    "identity_id",
    "first_ingested_at",
    "last_ingested_at",
    "latest_ingestion_run_id",
    "ingestion_batch_date",
    "ingestion_time_basis",
    "scraped_at",
    "scraped_at_basis",
    "scraped_at_evidence_reference",
)


def put(node, key, value):
    target = node.find(key)
    if target is None:
        target = E.SubElement(node, key)
    target.text = str(value)


def save(node, path):
    E.indent(node, space="  ")
    E.ElementTree(node).write(path, encoding="UTF-8", xml_declaration=True)


def hop(parent, source, target, evaluation="Y", unconditional="N"):
    item = E.SubElement(parent, "hop")
    for key, value in (("from", source), ("to", target), ("enabled", "Y")):
        put(item, key, value)
    if parent.tag == "hops":
        put(item, "evaluation", evaluation)
        put(item, "unconditional", unconditional)


def pipeline(verify):
    p = E.parse(OUT / "load_entity_names.hpl").getroot()
    name = "verify_posting_dates" if verify else "load_posting_dates"
    put(p.find("info"), "name", name)
    put(
        p.find("info"),
        "description",
        "Project and verify accepted posting ingestion events independently of display names.",
    )
    query = p.find("transform[name='Read entity names']")
    put(query, "name", "Read posting dates")
    put(query, "sql", "SELECT * FROM ingestion.graph_posting_ingestion_dates(?)")
    output = p.find("transform[name='Set entity names']")
    put(output, "name", "Verify posting dates" if verify else "Set posting dates")
    put(output, "read_only", "Y" if verify else "N")
    base = "MATCH (i:entity:jobPosting {id:$identity_id,kind:'JobPosting'})\n"
    if verify:
        clauses = [
            "i.first_ingested_at=datetime($first_ingested_at)",
            "i.last_ingested_at=datetime($last_ingested_at)",
            "i.latest_ingestion_run_id=$latest_ingestion_run_id",
            "i.ingestion_batch_date=date($ingestion_batch_date)",
            "i.ingestion_time_basis=$ingestion_time_basis",
        ]
        for field in ("scraped_at", "scraped_at_basis", "scraped_at_evidence_reference"):
            expected = f"datetime(${field})" if field == "scraped_at" else f"${field}"
            clauses.append(
                f"((properties(i)['{field}'] IS NULL AND ${field} IS NULL) OR i.{field}={expected})"
            )
        cypher = base + "WHERE " + "\nAND ".join(clauses)
    else:
        cypher = (
            base
            + "SET i.first_ingested_at=datetime($first_ingested_at),"
            "i.last_ingested_at=datetime($last_ingested_at),\n"
        )
        cypher += (
            "i.latest_ingestion_run_id=$latest_ingestion_run_id,"
            "i.ingestion_batch_date=date($ingestion_batch_date),\n"
        )
        cypher += "i.ingestion_time_basis=$ingestion_time_basis,\n"
        cypher += (
            "i.scraped_at=CASE WHEN $scraped_at IS NULL THEN NULL ELSE datetime($scraped_at) END,\n"
        )
        cypher += (
            "i.scraped_at_basis=$scraped_at_basis,"
            "i.scraped_at_evidence_reference=$scraped_at_evidence_reference"
        )
    # The entity template is independently batched. Reset its complete transport
    # contract here so every date field (including NULLs) uses the current row.
    cypher = re.sub(
        r"\$([A-Za-z_][A-Za-z_0-9]*)",
        lambda match: "row." + match[1] if match[1] in FIELDS else match[0],
        cypher,
    )
    put(output, "cypher", "UNWIND $rows AS row\n" + cypher
        + "\nRETURN count(i)=size($rows) AS entity_matches")
    put(output, "batch_size", DATE_BATCH_SIZE)
    put(output, "unwind", "Y")
    put(output, "unwind_map", "rows")
    output.find("mappings").clear()
    for field in FIELDS:
        mapping = E.SubElement(output.find("mappings"), "mapping")
        for key, value in (("parameter", field), ("field", field), ("type", "String")):
            put(mapping, key, value)
    order = p.find("order")
    order.clear()
    if not verify:
        capture = deepcopy(query)
        put(capture, "name", "Capture accepted posting events")
        put(
            capture,
            "sql",
            "SELECT ingestion.record_posting_ingestion_observations(?) AS captured_observations",
        )
        p.append(capture)
        hop(order, "Snapshot", "Capture accepted posting events")
        hop(order, "Capture accepted posting events", "Read posting dates")
    else:
        # The read function requires exact READY scope and complete retained membership.
        put(query, "sql", "SELECT * FROM ingestion.graph_posting_ingestion_dates(?)")
        hop(order, "Snapshot", "Read posting dates")
    out_name = output.findtext("name")
    for source, target in (
        ("Read posting dates", out_name),
        (out_name, "Check result"),
        ("Check result", "Complete"),
        ("Check result", "Check failed"),
    ):
        hop(order, source, target)
    put(
        p.find("transform[name='Check failed']"),
        "message",
        "A posting identity is missing or its ingestion or collection date provenance "
        "differs from accepted events.",
    )
    save(p, OUT / f"{name}.hpl")


def build():
    pipeline(False)
    pipeline(True)
    snapshot = E.parse(OUT / "load_snapshot.hwf").getroot()
    actions = snapshot.find("actions")
    for label, filename in (
        ("Set posting ingestion dates", "load_posting_dates.hpl"),
        ("Verify posting ingestion dates", "verify_posting_dates.hpl"),
    ):
        if actions.find(f"action[name='{label}']") is None:
            action = deepcopy(actions.find("action[name='Set readable entity names']"))
            put(action, "name", label)
            put(action, "filename", "${PROJECT_HOME}/graph/" + filename)
            actions.append(action)
    hops = snapshot.find("hops")
    # The permanent source graph projects entities directly. Keep generation
    # compatible with historical templates without introducing an action that
    # no longer exists in the current workflow.
    source_successor = (
        "Clear current source relationships"
        if actions.find("action[name='Clear current source relationships']") is not None
        else "Verify record properties"
    )
    for predecessor, successor, inserted in (
        ("Set readable entity names", source_successor, "Set posting ingestion dates"),
        ("Verify entity names", "Verify graph membership", "Verify posting ingestion dates"),
    ):
        direct = hops.find(f"hop[from='{predecessor}'][to='{successor}']")
        if direct is not None:
            put(direct, "to", inserted)
        if hops.find(f"hop[from='{inserted}'][to='{successor}']") is None:
            hop(hops, inserted, successor)
            hop(hops, inserted, "Record graph failure", "N")
    save(snapshot, OUT / "load_snapshot.hwf")

    installer = E.parse(ROOT / "hop/retention/install.hwf").getroot()
    put(installer, "name", "Install posting identity date projection")
    put(
        installer,
        "description",
        "Add immutable posting ingestion and supplemental collection-time ledgers; "
        "execute no source or model requests.",
    )
    retained = {"Start", "Success", "Abort"}
    action = deepcopy(installer.find("actions/action[type='SQL']"))
    for element in list(installer.find("actions")):
        if element.findtext("name") not in retained:
            installer.find("actions").remove(element)
    put(action, "name", "Install posting identity date SQL")
    put(action, "sqlfilename", "${PROJECT_HOME}/graph/sql/001_posting_ingestion_dates.sql")
    installer.find("actions").append(action)
    put(
        installer.find("actions/action[name='Abort']"),
        "message",
        "Posting identity date installation failed; inspect the SQL action.",
    )
    installer.find("hops").clear()
    hop(installer.find("hops"), "Start", action.findtext("name"), unconditional="Y")
    previous = action
    for name, filename in (
        ("Install permanent source business graph SQL", "002_batchfree_source_graph.sql"),
        ("Install query-local source validation and selection", "003_source_query_sharing.sql"),
        ("Install verified source proof replay", "004_verified_proof_replay.sql"),
        ("Install scoped validation worksets", "005_validation_worksets.sql"),
        ("Install JOB-ALIO validation worksets", "006_jobalio_validation_worksets.sql"),
        ("Install capture guard worksets", "007_capture_guard_worksets.sql"),
        ("Install source reader worksets", "008_reader_worksets.sql"),
        ("Install entity reader fact worksets", "009_reader_fact_worksets.sql"),
    ):
        following = deepcopy(action)
        put(following, "name", name)
        put(following, "sqlfilename", "${PROJECT_HOME}/graph/sql/" + filename)
        installer.find("actions").append(following)
        hop(installer.find("hops"), previous.findtext("name"), name)
        hop(installer.find("hops"), previous.findtext("name"), "Abort", "N")
        previous = following
    hop(installer.find("hops"), previous.findtext("name"), "Success")
    hop(installer.find("hops"), previous.findtext("name"), "Abort", "N")
    save(installer, OUT / "install_posting_dates.hwf")

    date_only = deepcopy(snapshot)
    put(date_only, "name", "Update posting identity dates from accepted ingestion events")
    put(
        date_only,
        "description",
        "Set and verify only posting date properties. "
        "Preserve business entities, facts, names and enrichment.",
    )
    names = {
        "Start",
        "Success",
        "Abort",
        "Enter retention writer guard",
        "Leave retention writer guard",
        "Release failed graph writer",
        "Set posting ingestion dates",
        "Verify posting ingestion dates",
    }
    for action in list(date_only.find("actions")):
        if action.findtext("name") not in names:
            date_only.find("actions").remove(action)
    put(
        date_only.find("actions/action[name='Abort']"),
        "message",
        "Posting identity date update failed. Partial date changes can be replayed "
        "from the same immutable ingestion events.",
    )
    hops = date_only.find("hops")
    hops.clear()
    steps = [
        "Start",
        "Enter retention writer guard",
        "Set posting ingestion dates",
        "Verify posting ingestion dates",
        "Leave retention writer guard",
        "Success",
    ]
    for index, source in enumerate(steps[:-1]):
        hop(hops, source, steps[index + 1], unconditional="Y" if index == 0 else "N")
        if index:
            hop(hops, source, "Release failed graph writer", "N")
    hop(hops, "Release failed graph writer", "Abort")
    hop(hops, "Release failed graph writer", "Abort", "N")
    save(date_only, OUT / "update_posting_dates.hwf")


if __name__ == "__main__":
    build()
