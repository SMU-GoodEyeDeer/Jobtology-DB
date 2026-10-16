# ruff: noqa: E501
"""Generate optional 1..8 inferred workers without changing request/cache semantics."""

import xml.etree.ElementTree as E
from copy import deepcopy

from build_linking import (
    OUT,
    Pipeline,
    child,
    database,
    log,
    put,
    remember,
    save,
    variables,
    workflow,
)
from build_metadata_linking import JAVA, PARAMETERS


def worker_java():
    text = JAVA.replace('String token=System.getenv("JOBKOREA_ISOLATED_TOKEN")',
                        'String fixtureToken=System.getenv("JOBKOREA_ISOLATED_TOKEN")')
    text = text.replace('boolean isolated=token!=null && token.matches',
                        'boolean isolated=fixtureToken!=null && fixtureToken.matches')
    text = text.replace('token.equals(fixture)', 'fixtureToken.equals(fixture)')
    text = text.replace('"+token+"-mock:', '"+fixtureToken+"-mock:')
    text = text.replace('String finalState="NOT_SENT";',
                        'String finalState="NOT_SENT";\n String token=getParent().resolve(getVariable("METADATA_OCCUPATION_EXECUTION_TOKEN",""));')
    old = text[text.index('  java.sql.PreparedStatement eligible='):text.index('  String endpoint=null;')]
    text = text.replace(old, '''  java.sql.PreparedStatement eligible=jdbc.prepareStatement("SELECT context->>'endpoint',context->>'read_timeout_ms',context->>'request_delay_ms',current_setting('jobtology.isolated_fixture',true) FROM (SELECT enrichment.metadata_occupation_request_context(?,nullif(?,'')::uuid) AS context) s WHERE context IS NOT NULL");
  eligible.setString(1,attempt);eligible.setString(2,token);java.sql.ResultSet selected=eligible.executeQuery();
''')
    text = text.replace('SELECT enrichment.reserve_request(?)', 'SELECT enrichment.admit_metadata_occupation_request(?,?::uuid)')
    text = text.replace('try{reserve.setString(1,attempt);reserve.execute();}finally{reserve.close();}',
                        'boolean admitted=false;\n   try{reserve.setString(1,attempt);reserve.setString(2,token);java.sql.ResultSet accepted=reserve.executeQuery();try{admitted=accepted.next()&&accepted.getBoolean(1);}finally{accepted.close();}}finally{reserve.close();}')
    text = text.replace("WHERE attempt_id=? AND state='RESERVED'", "WHERE attempt_id=? AND state='RESERVED' AND ?::boolean")
    text = text.replace('read.setString(1,attempt);java.sql.ResultSet requestRow=',
                        'read.setString(1,attempt);read.setBoolean(2,admitted);java.sql.ResultSet requestRow=')
    text = text.replace('SELECT state FROM enrichment.attempt WHERE attempt_id=?',
                        'SELECT state,cost_usd IS NULL FROM enrichment.attempt WHERE attempt_id=?')
    text = text.replace('finalState=result.getString(1);',
                        'finalState=result.getString(1);if("ERROR".equals(finalState)||"REJECTED".equals(finalState)||result.getBoolean(2))stopExecution(jdbc,token,"CHARGED_FAILURE_OR_UNKNOWN_COST");')
    text = text.replace(' } catch(Exception failure){\n  // A save failure',
                        ' } catch(Exception failure){\n  if(db!=null&&!token.isEmpty())try{stopExecution(db.getConnection(),token,"WORKER_FAILURE");}catch(Exception ignored){}\n  // A save failure')
    helper = '''
void stopExecution(java.sql.Connection jdbc,String token,String reason) throws Exception {
 java.sql.PreparedStatement stop=jdbc.prepareStatement("SELECT enrichment.stop_metadata_occupation_execution(?::uuid,?)");
 try{stop.setString(1,token);stop.setString(2,reason);stop.execute();}finally{stop.close();}
}
'''
    return helper + text


def build():
    p = Pipeline("start_inferred_occupation_execution", "Start one owned dispatcher for an immutable fresh batch; reject stale holds.")
    p.add(variables([("batch_id", "METADATA_OCCUPATION_BATCH_ID"), ("workers", "REQUEST_WORKERS")]))
    p.add(database("Own bounded inference dispatch", "SELECT started->>'execution_token' AS execution_token,started::text AS dispatch_json FROM (SELECT enrichment.start_metadata_occupation_execution(?,?::integer) AS started) s", ["batch_id", "workers"]))
    p.add(remember([("execution_token", "METADATA_OCCUPATION_EXECUTION_TOKEN")]))
    p.add(log("Owned inference dispatcher", "Bounded dispatcher prepared; paid admission remains atomic in the shared ledger.", ["dispatch_json"]))
    p.save("start_inferred_occupation_execution")

    root = E.parse(OUT / "run_inferred_occupations.hpl").getroot()
    put(root.find("info"), "name", "run_inferred_occupation_workers")
    put(root.find("info"), "description", "Optional bounded 1..8 inferred workers; atomic owned admission, no automatic retry.")
    parameters = root.find("info/parameters")
    child(parameters, "parameter", {"name": "REQUEST_WORKERS", "default_value": "1", "description": "Maximum in-flight paid attempts, 1..8; execution admission validates the bound."})
    for node in root.findall("transform"):
        if node.findtext("type") == "PipelineExecutor":
            put(node, "copies", "${REQUEST_WORKERS}")
            put(node, "filename", "${PROJECT_HOME}/ingestions/jobkorea/request_inferred_occupation_worker.hpl")
    save(root, OUT / "run_inferred_occupation_workers.hpl")

    root = E.parse(OUT / "request_inferred_occupation.hpl").getroot()
    put(root.find("info"), "name", "request_inferred_occupation_worker")
    put(root.find("info"), "description", "One atomically owned inferred attempt; strict shared budget and failure stop.")
    java = root.find("transform[type='UserDefinedJavaClass']")
    put(java.find("definitions/definition"), "class_source", worker_java())
    save(root, OUT / "request_inferred_occupation_worker.hpl")

    p = Pipeline("end_inferred_occupation_execution", "End dispatcher after all child workers settle; unresolved reservations remain held.")
    p.add(variables([("token", "METADATA_OCCUPATION_EXECUTION_TOKEN")]))
    p.add(database("End bounded inference dispatch", "SELECT CASE WHEN nullif(?,'') IS NULL THEN '{\"execute_requests\":\"N\"}'::jsonb ELSE enrichment.end_metadata_occupation_execution(nullif(?,'')::uuid) END::text AS dispatch_json", ["token", "token"]))
    p.add(log("Inference dispatcher report", "Dispatcher completed or stopped. Never-sent rows remain pending for a fresh batch.", ["dispatch_json"]))
    p.save("end_inferred_occupation_execution")

    descriptions = {
        "EXECUTE_REQUESTS": "Y enables bounded native requests; N has no key read or HTTP.",
        "REQUEST_DELAY_MS": "Per-worker delay before a single reserved POST; the worker bound limits concurrent attempts.",
    }
    parameters = [(name, default, descriptions.get(name, description)) for name, default, description in PARAMETERS]
    parameters.append(("REQUEST_WORKERS", "1", "Bounded in-flight workers 1..8; default one, no automatic retries."))
    workflow("execute_inferred_occupation_workers", "Optional bounded native occupation workers; default one and execution off, same prompt and cache identity.", [
        ("Freeze inferred occupation inputs", "ingestions/jobkorea/prepare_inferred_occupations.hpl"),
        ("Own bounded inference dispatch", "ingestions/jobkorea/start_inferred_occupation_execution.hpl"),
        ("Send bounded inferred occupation requests", "ingestions/jobkorea/run_inferred_occupation_workers.hpl"),
        ("End bounded inference dispatch", "ingestions/jobkorea/end_inferred_occupation_execution.hpl"),
        ("Record inferred outcomes and costs", "ingestions/jobkorea/finish_inferred_occupations.hpl"),
    ], parameters)

    root = E.parse(OUT / "install_inferred_occupations.hwf").getroot()
    put(root, "name", "Install optional inferred worker admission")
    actions = root.find("actions")
    sql_actions = [node for node in actions if node.findtext("type") == "SQL"]
    template = deepcopy(sql_actions[0])
    for node in sql_actions:
        actions.remove(node)
    put(template, "name", "031_metadata_occupation_workers")
    put(template, "sqlfilename", "${PROJECT_HOME}/llm/sql/031_metadata_occupation_workers.sql")
    actions.append(template)
    hops = root.find("hops")
    hops.clear()
    for source, target, success in (("Start", "031_metadata_occupation_workers", "Y"),
                                    ("031_metadata_occupation_workers", "Success", "Y"),
                                    ("031_metadata_occupation_workers", "Abort", "N")):
        child(hops, "hop", {"from": source, "to": target, "enabled": "Y", "evaluation": success, "unconditional": "N"})
    save(root, OUT / "install_inferred_occupation_workers.hwf")


if __name__ == "__main__":
    build()
