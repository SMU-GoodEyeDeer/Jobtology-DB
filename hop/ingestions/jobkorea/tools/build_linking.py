# ruff: noqa: E501
"""Generate native JobKorea pilot preparation; all default requests remain offline."""
import xml.etree.ElementTree as E
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / "hop/ingestions/jobkorea"


def put(node, tag, value):
    target = node.find(tag)
    if target is None:
        target = E.SubElement(node, tag)
    target.text = str(value)


def save(node, path):
    E.indent(node, space="  ")
    E.ElementTree(node).write(path, encoding="UTF-8", xml_declaration=True)


def child(node, tag, values):
    target = E.SubElement(node, tag)
    for key, value in values.items():
        put(target, key, value)
    return target


class Pipeline:
    def __init__(self, name, description):
        self.root = E.Element("pipeline")
        info = child(self.root, "info", {
            "name": name, "description": description, "pipeline_type": "Normal", "size_rowset": 100,
        })
        E.SubElement(info, "parameters")
        E.SubElement(self.root, "notepads")
        self.order = E.SubElement(self.root, "order")
        self.names = []

    def add(self, node):
        name = node.findtext("name")
        if self.names:
            child(self.order, "hop", {"from": self.names[-1], "to": name, "enabled": "Y"})
        child(node, "GUI", {"xloc": 80 + len(self.names) * 260, "yloc": 100})
        child(node, "partitioning", {"method": "none", "schema_name": ""})
        put(node, "copies", 1)
        put(node, "distribute", "Y")
        self.root.append(node)
        self.names.append(name)

    def save(self, name):
        E.SubElement(self.root, "transform_error_handling")
        E.SubElement(self.root, "attributes")
        save(self.root, OUT / (name + ".hpl"))


def transform(kind, name):
    return child(E.Element("root"), "transform", {"type": kind, "name": name})


def variables(specs):
    node = transform("GetVariable", "Pilot options")
    fields = E.SubElement(node, "fields")
    for name, variable in specs:
        child(fields, "field", {"name": name, "variable": "${" + variable + "}", "type": "String",
                               "length": -1, "precision": -1, "trim_type": "none"})
    return node


def database(name, sql, fields):
    node = transform("DBJoin", name)
    for key, value in {"connection": "jobtology-postgres", "sql": sql, "cache": "N", "cache_size": 0,
                       "rowlimit": 0, "outer_join": "N", "replace_vars": "N"}.items():
        put(node, key, value)
    parameters = E.SubElement(node, "parameter")
    for name in fields:
        child(parameters, "field", {"name": name, "type": "String"})
    return node


def remember(specs):
    node = transform("SetVariable", "Remember exact pilot pins")
    put(node, "use_formatting", "Y")
    fields = E.SubElement(node, "fields")
    for field, name in specs:
        child(fields, "field", {"field_name": field, "variable_name": name,
                               "variable_type": "PARENT_WORKFLOW", "default_value": ""})
    return node


def log(name, message, fields):
    node = transform("WriteToLog", name)
    for key, value in {"displayHeader": "Y", "limitRows": "N", "limitRowsNumber": 0,
                       "logmessage": message, "loglevel": "Basic"}.items():
        put(node, key, value)
    target = E.SubElement(node, "fields")
    for name in fields:
        child(target, "field", {"name": name})
    return node


PARAMETERS = [
    ("JOB_RUN_ID", "LATEST", "Resolve once, then pin the exact READY JobKorea supplied-file run."),
    ("NCS_RUN_ID", "LATEST", "Resolve once, then pin the exact READY NCS competency run."),
    ("PILOT_LIMIT", "5", "Small IT/software/data candidate pilot, 1..25. Scope remains unverified."),
    ("EXTRACT_MODEL", "openai/gpt-5.6-luna", "Configurable OpenRouter OpenAI BYOK extraction model."),
    ("CATEGORIZE_MODEL", "openai/gpt-5.6-luna", "Configurable OpenRouter OpenAI BYOK NCS matching model."),
    ("ENDPOINT", "https://openrouter.ai/api/v1/chat/completions", "Existing OpenRouter/BYOK chat-completions endpoint."),
    ("API_KEY_FILE", "${HOP_CONFIG_FOLDER}/secrets/openrouter.csv", "Existing protected key file; preview never reads it."),
    ("EXECUTE_REQUESTS", "N", "N prepares requests with zero HTTP. Y explicitly enables existing native runners."),
    ("MAX_COST_USD", "0.25", "Batch accounting cap. Reservations can stop later matching before this cap."),
    ("DAILY_BUDGET_USD", "0.25", "Rolling accounting cap; raise explicitly only when desired."),
    ("REQUEST_RESERVE_USD", "0.05", "Conservative per-request accounting reservation; unknown cost stays reserved."),
    ("MAX_REQUESTS", "10", "Charged or uncertain requests; no automatic retries."),
    ("MAX_INPUT_CHARS", "24000", "Complete input bound; oversized inputs are rejected, never truncated."),
    ("MAX_OUTPUT_TOKENS", "3000", "Maximum output tokens per request."),
    ("CANDIDATE_LIMIT", "20", "NCS shortlist size."),
    ("MAX_MATCHES", "5", "Maximum supported NCS matches per posting."),
    ("TEMPERATURE", "", "Optional model temperature."),
    ("REASONING_EFFORT", "", "Optional model reasoning effort; blank uses configured-provider defaults."),
    ("PROVIDER_ONLY", "openai", "Existing OpenRouter provider routing for OpenAI BYOK; configurable."),
    ("EXTRA_PARAMS_JSON", "{}", "Optional compatible numeric model settings."),
    ("REUSE_CACHE", "Y", "Reuse validated exact source/prompt/model/options outputs."),
    ("REQUEST_DELAY_MS", "250", "Spacing between sequential requests when execution is enabled."),
    ("READ_TIMEOUT_MS", "180000", "Finite request timeout."),
]


def workflow(name, description, steps, parameters, mappings=None):
    root = E.parse(ROOT / "hop/llm/enrich.hwf").getroot()
    put(root, "name", name)
    put(root, "description", description)
    params = root.find("parameters")
    params.clear()
    for key, default, help_text in parameters:
        child(params, "parameter", {"name": key, "default_value": default, "description": help_text})
    actions = root.find("actions")
    templates = {node.findtext("type"): deepcopy(node) for node in actions}
    actions.clear()
    start = deepcopy(templates["SPECIAL"])
    put(start, "name", "Start")
    actions.append(start)
    names = ["Start"]
    for index, (label, filename) in enumerate(steps, 1):
        action = deepcopy(templates["PIPELINE"])
        for key, value in {"name": label, "filename": "${PROJECT_HOME}/" + filename,
                           "run_configuration": "jobkorea-local", "xloc": 80 + (index % 5) * 240,
                           "yloc": 100 + (index // 5) * 180}.items():
            put(action, key, value)
        parameters_node = action.find("parameters")
        parameters_node.clear()
        put(parameters_node, "pass_all_parameters", "Y")
        for key, value in (mappings or {}).get(label, {}).items():
            child(parameters_node, "parameter", {"name": key, "value": value})
        actions.append(action)
        names.append(label)
    for kind, label in (("SUCCESS", "Success"), ("ABORT", "Abort")):
        action = deepcopy(templates[kind])
        put(action, "name", label)
        if kind == "ABORT":
            put(action, "message", "JobKorea pilot preparation failed. Inspect pinned inputs and the batch report before retrying.")
        actions.append(action)
    hops = root.find("hops")
    hops.clear()
    for index, label in enumerate(names):
        target = names[index + 1] if index + 1 < len(names) else "Success"
        child(hops, "hop", {"from": label, "to": target, "enabled": "Y", "evaluation": "Y",
                            "unconditional": "Y" if index == 0 else "N"})
        if index:
            child(hops, "hop", {"from": label, "to": "Abort", "enabled": "Y",
                                "evaluation": "N", "unconditional": "N"})
    save(root, OUT / (name + ".hwf"))


def build_linking():
    p = Pipeline("preview_linking_scope", "Read-only IT/software/data scope coverage; no keys or model requests.")
    p.add(variables([("jobs", "JOB_RUN_ID"), ("ncs", "NCS_RUN_ID"), ("cap", "PILOT_LIMIT")]))
    p.add(database("Read source and pilot coverage", "SELECT enrichment.jobkorea_linking_preview(?,?,?::integer)::text AS preview_json", ["jobs", "ncs", "cap"]))
    p.add(log("Scope coverage", "Metadata scope candidates remain unverified. Missing descriptions require duty abstention.", ["preview_json"]))
    p.save("preview_linking_scope")
    workflow("preview_linking", "Read source scope and a bounded pilot without preparing inputs or making requests.",
             [("Read scope coverage", "ingestions/jobkorea/preview_linking_scope.hpl")], PARAMETERS[:3])

    p = Pipeline("prepare_linking_pilot", "Prepare immutable metadata inputs and remember exact JobKorea/NCS pilot pins.")
    p.add(variables([("jobs", "JOB_RUN_ID"), ("ncs", "NCS_RUN_ID"), ("cap", "PILOT_LIMIT")]))
    p.add(database("Prepare immutable pilot inputs", """WITH p AS (SELECT enrichment.prepare_jobkorea_linking_pilot(?,?,?::integer) AS data)
SELECT data->>'job_run_id' AS pinned_jobs,data->>'ncs_run_id' AS pinned_ncs,
 data->>'posting_ids' AS selected_postings,data->>'bundle_ids' AS selected_bundles,
 data->>'selected_count' AS selected_count,data->>'run_needed' AS run_needed,data::text AS preparation_json FROM p""", ["jobs", "ncs", "cap"]))
    p.add(remember([("pinned_jobs", "JOBKOREA_PINNED_JOB_RUN_ID"), ("pinned_ncs", "JOBKOREA_PINNED_NCS_RUN_ID"),
                    ("selected_postings", "JOBKOREA_PILOT_POSTING_IDS"), ("selected_bundles", "JOBKOREA_PILOT_BUNDLE_IDS"),
                    ("selected_count", "JOBKOREA_PILOT_COUNT"), ("run_needed", "JOBKOREA_PILOT_RUN_NEEDED")]))
    p.add(log("Pilot inputs prepared", "Immutable listing metadata inputs prepared; full-description absence remains explicit.", ["preparation_json"]))
    p.save("prepare_linking_pilot")

    p = Pipeline("preview_linking_requests", "Redacted prepared-request counts and conservative reservation coverage; no API or key reads.")
    p.add(variables([("batch_id", "LLM_BATCH_ID")]))
    p.add(database("Read prepared request accounting", """SELECT b.batch_id,b.state,b.job_run_id,b.ncs_run_id,
 (SELECT count(*) FROM enrichment.item i WHERE i.batch_id=b.batch_id) AS pilot_postings,
 (SELECT count(*) FROM enrichment.attempt a WHERE a.batch_id=b.batch_id AND a.stage='extract') AS extraction_requests,
 (SELECT count(*) FROM enrichment.attempt a WHERE a.batch_id=b.batch_id AND a.stage='categorize') AS matching_requests,
 (SELECT count(*) FROM enrichment.attempt a WHERE a.batch_id=b.batch_id AND a.reserved_at IS NOT NULL) AS charged_or_uncertain_requests,
 b.settings->>'execute_requests' AS execute_requests,b.settings->>'endpoint' AS endpoint,
 b.settings->>'extract_model' AS extract_model,b.settings->>'categorize_model' AS categorize_model,
 b.settings->>'max_cost_usd' AS batch_cap_usd,b.settings->>'request_reserve_usd' AS request_reserve_usd,
 b.settings->>'max_requests' AS request_cap,
 (SELECT count(*) FROM enrichment.attempt a WHERE a.batch_id=b.batch_id AND a.stage='extract')
  * (b.settings->>'request_reserve_usd')::numeric AS extraction_reservation_usd,
 floor(greatest(0,least((b.settings->>'max_cost_usd')::numeric / (b.settings->>'request_reserve_usd')::numeric,
  (b.settings->>'max_requests')::numeric)
  - (SELECT count(*) FROM enrichment.attempt a WHERE a.batch_id=b.batch_id AND a.stage='extract')))::integer AS conservative_batch_matching_capacity
FROM enrichment.batch b WHERE b.batch_id=?""", ["batch_id"]))
    p.add(log("Prepared pilot and budget", "Requests prepared. Missing duties produce no supported match; independent review precedes publication. Reservations can stop later requests at the configured cap.",
              ["batch_id", "state", "job_run_id", "ncs_run_id", "pilot_postings", "extraction_requests", "matching_requests",
               "charged_or_uncertain_requests", "execute_requests", "endpoint", "extract_model", "categorize_model",
               "batch_cap_usd", "request_reserve_usd", "request_cap", "extraction_reservation_usd", "conservative_batch_matching_capacity"]))
    p.save("preview_linking_requests")
    steps = [("Prepare exact pilot inputs", "ingestions/jobkorea/prepare_linking_pilot.hpl")]
    steps += [(label, "llm/" + filename) for label, filename in [
        ("Freeze inputs and options", "start_batch.hpl"), ("Plan extraction", "plan_extract.hpl"),
        ("Extract supported facts", "run_extract.hpl"), ("Retrieve NCS and plan matches", "plan_categorize.hpl"),
        ("Categorize explicit duties", "run_categorize.hpl"), ("Validate and report", "finish_batch.hpl"),
    ]]
    steps += [("Read prepared requests and budget", "ingestions/jobkorea/preview_linking_requests.hpl")]
    mappings = {"Freeze inputs and options": {
        "JOB_RUN_ID": "${JOBKOREA_PINNED_JOB_RUN_ID}", "NCS_RUN_ID": "${JOBKOREA_PINNED_NCS_RUN_ID}",
        "POSTING_IDS": "${JOBKOREA_PILOT_POSTING_IDS}", "INPUT_BUNDLE_IDS": "${JOBKOREA_PILOT_BUNDLE_IDS}",
        "POSTING_LIMIT": "${JOBKOREA_PILOT_COUNT}", "JOB_SOURCE_ID": "jobkorea", "RUN_MODE": "ENRICH",
        "DATASET_ID": "", "PROMPT_VERSION": "ko-link-v1", "ACCEPTANCE_POLICY": "REVIEW", "REPAIR_BATCH_ID": "",
    }}
    workflow("prepare_linking", "Prepare a small pinned IT/software/data pilot. Default N produces requests and budget preview with no HTTP or key reads.", steps, PARAMETERS, mappings)
    root = E.parse(OUT / "prepare_linking.hwf").getroot()
    gate = child(root.find("actions"), "action", {
        "name": "Pilot needs processing", "type": "SIMPLE_EVAL", "valuetype": "variable",
        "fieldtype": "string", "variablename": "${JOBKOREA_PILOT_RUN_NEEDED}", "comparevalue": "Y",
        "successcondition": "equal", "successwhenvarset": "N", "xloc": 350, "yloc": 400,
        "draw": "Y", "parallel": "N",
    })
    child(gate, "attributes", {})
    hops = root.find("hops")
    for hop in hops:
        if hop.findtext("from") == "Prepare exact pilot inputs" and hop.findtext("to") == "Freeze inputs and options":
            put(hop, "to", "Pilot needs processing")
    for target, evaluation in (("Freeze inputs and options", "Y"), ("Success", "N")):
        child(hops, "hop", {"from": "Pilot needs processing", "to": target, "enabled": "Y",
                            "evaluation": evaluation, "unconditional": "N"})
    save(root, OUT / "prepare_linking.hwf")

    root = E.parse(OUT / "install.hwf").getroot()
    put(root, "name", "Install JobKorea semantic input and reviewed linking adapters")
    put(root, "description", "Requires source SQL001-005 and existing LLM/retention modules. Native SQL only; no source or model requests.")
    actions = root.find("actions")
    template = deepcopy(next(action for action in actions if action.findtext("type") == "SQL"))
    for action in list(actions):
        if action.findtext("type") == "SQL":
            actions.remove(action)
    names = ["Start"]
    for filename in ["003_planning", "005_review_eval", "010_independent_review", "013_revision_categorization",
                     "017_input_bundles", "021_link_publication", "027_jobkorea_inputs", "028_jobkorea_linking"]:
        action = deepcopy(template)
        put(action, "name", filename)
        put(action, "sqlfilename", "${PROJECT_HOME}/llm/sql/" + filename + ".sql")
        actions.append(action)
        names.append(filename)
    hops = root.find("hops")
    hops.clear()
    for index, label in enumerate(names):
        child(hops, "hop", {"from": label, "to": names[index + 1] if index + 1 < len(names) else "Success",
                            "enabled": "Y", "evaluation": "Y", "unconditional": "Y" if index == 0 else "N"})
        if index:
            child(hops, "hop", {"from": label, "to": "Abort", "enabled": "Y", "evaluation": "N", "unconditional": "N"})
    save(root, OUT / "install_linking.hwf")


if __name__ == "__main__":
    build_linking()
