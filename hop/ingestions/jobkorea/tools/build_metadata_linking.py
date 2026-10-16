# ruff: noqa: E501
"""Generate inferred-only native occupation workflow; execution defaults off."""

import hashlib
import json
import xml.etree.ElementTree as E
from copy import deepcopy

from build_linking import (
    OUT,
    ROOT,
    Pipeline,
    child,
    database,
    log,
    put,
    remember,
    save,
    transform,
    variables,
    workflow,
)

JAVA = r'''
void require(boolean condition, String code) throws Exception {
 if(!condition) throw new Exception(code);
}

String keyFile(String file) throws Exception {
 java.nio.file.Path path=java.nio.file.Paths.get(file);
 require(path.isAbsolute(),"KEY_PATH_REQUIRED");
 java.nio.file.Path current=path.getRoot();
 for(java.nio.file.Path part:path){current=current.resolve(part);require(!java.nio.file.Files.isSymbolicLink(current),"KEY_SYMLINK_FORBIDDEN");}
 require(java.nio.file.Files.isRegularFile(path,java.nio.file.LinkOption.NOFOLLOW_LINKS)
  && java.nio.file.Files.size(path)<=8192,"KEY_FILE_INVALID");
 String csv=java.nio.file.Files.readString(path,java.nio.charset.StandardCharsets.UTF_8);
 if(csv.endsWith("\r\n"))csv=csv.substring(0,csv.length()-2);
 else if(csv.endsWith("\n"))csv=csv.substring(0,csv.length()-1);
 String[] lines=csv.split("\r?\n",-1);
 require(lines.length==2 && "api_key".equals(lines[0].trim()),"KEY_ROWS_INVALID");
 String key=lines[1].trim();
 if(key.startsWith("\"") && key.endsWith("\""))key=key.substring(1,key.length()-1);
 require(key.matches("[A-Za-z0-9_-]{10,2048}"),"KEY_INVALID");
 return key;
}

void saveResponse(java.sql.Connection jdbc,String attempt,int status,String body,long elapsed) throws Exception {
 java.sql.PreparedStatement save=jdbc.prepareStatement("SELECT enrichment.save_response(?,?::integer,?,?::bigint)");
 try {save.setString(1,attempt);save.setInt(2,status);save.setString(3,body);save.setLong(4,elapsed);save.execute();}
 finally{save.close();}
}

public boolean processRow() throws HopException {
 Object[] row=getRow();if(row==null){setOutputDone();return false;}
 org.apache.hop.core.database.Database db=null;
 boolean reserved=false;
 String attempt=get(Fields.In,"attempt_id").getString(row);
 String finalState="NOT_SENT";
 try {
  org.apache.hop.core.database.DatabaseMeta meta=(org.apache.hop.core.database.DatabaseMeta)
   getPipelineMeta().getMetadataProvider().getSerializer(org.apache.hop.core.database.DatabaseMeta.class).load("jobtology-postgres");
  db=new org.apache.hop.core.database.Database(getParent(),getParent(),meta);db.connect();
  java.sql.Connection jdbc=db.getConnection();
  java.sql.PreparedStatement eligible=jdbc.prepareStatement("SELECT b.settings->>'endpoint',b.settings->>'read_timeout_ms',b.settings->>'request_delay_ms',current_setting('jobtology.isolated_fixture',true) FROM enrichment.attempt a JOIN enrichment.batch b USING(batch_id) WHERE a.attempt_id=? AND a.stage='categorize' AND a.state='PLANNED' AND b.state='RUNNING' AND b.settings->>'execute_requests'='Y' AND b.settings->>'metadata_scope'='NCS_OCCUPATION_INFERENCE_V1' AND EXISTS(SELECT 1 FROM ingestion.latest_ready_run WHERE source_id='jobkorea' AND run_id=b.job_run_id) AND EXISTS(SELECT 1 FROM ingestion.latest_ready_run WHERE source_id='ncs_competency' AND run_id=b.ncs_run_id) AND NOT EXISTS(SELECT 1 FROM enrichment.attempt stopped WHERE stopped.batch_id=b.batch_id AND ((stopped.reserved_at IS NOT NULL AND stopped.state IN ('ERROR','RESERVED','REJECTED')) OR stopped.state='BUDGET_BLOCKED'))");
  eligible.setString(1,attempt);java.sql.ResultSet selected=eligible.executeQuery();
  String endpoint=null;String fixture=null;long timeout=0;long delay=0;
  try{if(selected.next()){endpoint=selected.getString(1);timeout=Long.parseLong(selected.getString(2));delay=Long.parseLong(selected.getString(3));fixture=selected.getString(4);}}
  finally{selected.close();eligible.close();}
  // This gate precedes any key read, including direct accidental dry-run invocation.
  if(endpoint!=null){
   boolean production="https://openrouter.ai/api/v1/chat/completions".equals(endpoint);
   String token=System.getenv("JOBKOREA_ISOLATED_TOKEN");
   boolean isolated=token!=null && token.matches("[0-9a-f]{12}") && token.equals(fixture)
    && endpoint.matches("http://jobtology-jobkorea-test-"+token+"-mock:[0-9]{1,5}/chat/completions");
   require(production || isolated,"MODEL_ENDPOINT_FORBIDDEN");
   require(timeout>=1000 && timeout<=600000 && delay>=0 && delay<=60000,"REQUEST_TIMEOUT_INVALID");
   String key=keyFile(getParent().resolve(getVariable("API_KEY_FILE","")));
   java.sql.PreparedStatement reserve=jdbc.prepareStatement("SELECT enrichment.reserve_request(?)");
   try{reserve.setString(1,attempt);reserve.execute();}finally{reserve.close();}
   java.sql.PreparedStatement read=jdbc.prepareStatement("SELECT request_body::text FROM enrichment.attempt WHERE attempt_id=? AND state='RESERVED'");
   read.setString(1,attempt);java.sql.ResultSet requestRow=read.executeQuery();String request=null;
   try{if(requestRow.next())request=requestRow.getString(1);}finally{requestRow.close();read.close();}
   if(request!=null){
    reserved=true;if(delay>0)Thread.sleep(delay);
    long started=System.nanoTime();int status=0;String body=null;
    org.apache.hc.client5.http.impl.classic.CloseableHttpClient http=null;
    org.apache.hc.core5.http.ClassicHttpResponse response=null;
    try {
     org.apache.hc.client5.http.config.RequestConfig config=org.apache.hc.client5.http.config.RequestConfig.custom()
      .setConnectionRequestTimeout(org.apache.hc.core5.util.Timeout.ofMilliseconds(10000))
      .setConnectTimeout(org.apache.hc.core5.util.Timeout.ofMilliseconds(10000))
      .setResponseTimeout(org.apache.hc.core5.util.Timeout.ofMilliseconds(timeout)).build();
     http=org.apache.hc.client5.http.impl.classic.HttpClients.custom().disableAutomaticRetries().disableRedirectHandling()
      .setDefaultRequestConfig(config).build();
     org.apache.hc.client5.http.classic.methods.HttpPost post=new org.apache.hc.client5.http.classic.methods.HttpPost(endpoint);
     post.setHeader("Authorization","Bearer "+key);post.setHeader("Content-Type","application/json");
     post.setEntity(new org.apache.hc.core5.http.io.entity.StringEntity(request,org.apache.hc.core5.http.ContentType.APPLICATION_JSON));
     response=http.executeOpen(null,post,null);status=response.getCode();
     require(response.getEntity()!=null,"EMPTY_MODEL_RESPONSE");
     java.io.InputStream input=response.getEntity().getContent();
     java.io.ByteArrayOutputStream bytes=new java.io.ByteArrayOutputStream();byte[] buffer=new byte[8192];int count;
     try{while((count=input.read(buffer))!=-1){require(bytes.size()+count<=8388608,"MODEL_RESPONSE_TOO_LARGE");bytes.write(buffer,0,count);}}
     finally{input.close();}
     body=java.nio.charset.StandardCharsets.UTF_8.newDecoder().onMalformedInput(java.nio.charset.CodingErrorAction.REPORT)
      .onUnmappableCharacter(java.nio.charset.CodingErrorAction.REPORT).decode(java.nio.ByteBuffer.wrap(bytes.toByteArray())).toString();
    } catch(Exception transport){status=0;body=null;}
    finally{if(response!=null)try{response.close();}catch(Exception ignored){} if(http!=null)try{http.close();}catch(Exception ignored){}}
    saveResponse(jdbc,attempt,status,body,(System.nanoTime()-started)/1000000);reserved=false;
    java.sql.PreparedStatement done=jdbc.prepareStatement("SELECT state FROM enrichment.attempt WHERE attempt_id=?");
    done.setString(1,attempt);java.sql.ResultSet result=done.executeQuery();
    try{require(result.next(),"RESPONSE_RESULT_MISSING");finalState=result.getString(1);}finally{result.close();done.close();}
   } else finalState="BUDGET_OR_PROVIDER_BLOCKED";
  }
  Object[] output=createOutputRow(row,data.outputRowMeta.size());get(Fields.Out,"request_state").setValue(output,finalState);
  putRow(data.outputRowMeta,output);return true;
 } catch(Exception failure){
  // A save failure after POST keeps its RESERVED accounting hold. Never retry.
  throw new HopException("Inferred occupation request failed; inspect the attempt ledger before retrying ("+failure.getClass().getSimpleName()+", reservation="+reserved+")");
 } finally{if(db!=null)db.close();}
}
'''

PARAMETERS = [
    ("BATCH_ID", "", "Optional immutable batch identity; blank creates one."),
    ("JOB_RUN_ID", "LATEST", "Exact current READY supplied JobKorea snapshot."),
    ("NCS_RUN_ID", "LATEST", "Exact current READY NCS snapshot."),
    ("POSTING_LIMIT", "5", "Listing count 1..10000; includes unknown lexical scope and closed listings."),
    ("POSTING_IDS", "", "Optional exact pipe-separated posting identities."),
    ("CATEGORIZE_MODEL", "openai/gpt-5.6-luna", "Existing OpenRouter model."),
    ("PROMPT_VERSION", "ko-metadata-occupation-v1", "Immutable inference prompt version: ko-metadata-occupation-v1 or ko-metadata-occupation-v2; v1 is the default."),
    ("RETRIEVAL_REVISION", "", "Blank preserves legacy retrieval/replay; metadata-occupation-lexical-v3 selects corrected new-batch retrieval."),
    ("ENDPOINT", "https://openrouter.ai/api/v1/chat/completions", "Exact OpenRouter HTTPS endpoint; isolated internal mocks only in tests."),
    ("API_KEY_FILE", "${HOP_CONFIG_FOLDER}/secrets/openrouter.csv", "Protected CSV read only after execute=Y eligibility."),
    ("EXECUTE_REQUESTS", "N", "Y enables capped sequential model requests; N has no key read or HTTP."),
    ("MAX_COST_USD", "0.05", "This immutable batch accounting cap; maximum $50. Choose full-run budget after the pilot."),
    ("DAILY_BUDGET_USD", "4.75", "Shared rolling 24-hour accounting cap; default $4.75, maximum $50."),
    ("REQUEST_RESERVE_USD", "0.005", "Unknown costs retain this hold; admission verifies conservative byte/token cost bound."),
    ("MAX_REQUESTS", "5", "Maximum charged or uncertain requests in this batch."),
    ("MAX_INPUT_CHARS", "16000", "Complete request bound; inputs are rejected instead of truncated."),
    ("MAX_OUTPUT_TOKENS", "768", "Maximum output including reasoning per request."),
    ("CANDIDATE_LIMIT", "12", "Exact bounded occupation shortlist, 1..30."),
    ("MAX_MATCHES", "1", "Maximum inferred occupations: 1..2 for v1/v2, 1..3 for explicit v3."),
    ("TEMPERATURE", "", "Optional compatible temperature."),
    ("REASONING_EFFORT", "none", "Optional reasoning effort; compact classification defaults none."),
    ("PROVIDER_ONLY", "openai", "Standard OpenAI routing; fallback and service tier alternatives disabled."),
    ("EXTRA_PARAMS_JSON", "{}", "Allowlisted numeric options only."),
    ("REUSE_CACHE", "Y", "Reuse exact metadata/candidate/NCS/prompt/model-option outputs; revalidate per posting."),
    ("REQUEST_DELAY_MS", "250", "Spacing between one-attempt sequential requests."),
    ("READ_TIMEOUT_MS", "180000", "Finite request timeout; uncertain outcomes stop further sends in this batch."),
]


def build_sql():
    prompt = (ROOT / "hop/llm/prompts/categorize-ko-metadata-occupation-v1.txt").read_text()
    schema = json.loads((ROOT / "hop/llm/prompts/categorize-ko-metadata-occupation-v1.schema.json").read_text())
    encoded = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256((prompt + "\n" + encoded).encode()).hexdigest()
    validation = (ROOT / "hop/llm/sql/004_validation.sql").read_text()
    start = validation.index("CREATE OR REPLACE FUNCTION enrichment.response_cost")
    stop = validation.index("CREATE OR REPLACE FUNCTION enrichment.finish_batch", start)
    body = (OUT / "tools/sql/metadata_occupation_native_body.sql").read_text()
    text = "-- Generated by tools/build_metadata_linking.py; inferred-only native transport/planner.\nBEGIN;\n"
    text += "INSERT INTO enrichment.prompt(version,stage,system_prompt,output_schema,content_hash) VALUES\n"
    text += "('ko-metadata-occupation-v1','categorize',$metadata_prompt$" + prompt + "$metadata_prompt$,$metadata_schema$" + encoded + "$metadata_schema$::jsonb,'" + digest + "')\n"
    text += "ON CONFLICT(version,stage) DO NOTHING;\n"
    text += "DO $prompt_identity$ BEGIN IF NOT EXISTS(SELECT 1 FROM enrichment.prompt WHERE version='ko-metadata-occupation-v1' AND stage='categorize' AND system_prompt=$metadata_prompt$" + prompt + "$metadata_prompt$ AND output_schema=$metadata_schema$" + encoded + "$metadata_schema$::jsonb AND content_hash='" + digest + "') THEN RAISE EXCEPTION 'METADATA_PROMPT_VERSION_IS_IMMUTABLE'; END IF; END $prompt_identity$;\n"
    text += validation[start:stop] + "\n" + body + "\nCOMMIT;\n"
    (ROOT / "hop/llm/sql/030_metadata_occupation_native.sql").write_text(text)


def build():
    build_sql()
    options = [(key.lower(), key) for key, _, _ in PARAMETERS if key != "API_KEY_FILE"]
    p = Pipeline("prepare_inferred_occupations", "Freeze supplied metadata, exact NCS occupations and separate inference requests; no keys or HTTP.")
    p.add(variables(options))
    names = [field for field, _ in options]
    sql = """WITH opts AS(SELECT jsonb_strip_nulls(jsonb_build_object(
     'limit',?::integer,'posting_ids',nullif(?,''),'categorize_model',?::text,'prompt_version',?::text,'retrieval_revision',nullif(?,''),'endpoint',?::text,'execute_requests',?::text,
     'max_cost_usd',?::numeric,'daily_budget_usd',?::numeric,'request_reserve_usd',?::numeric,'max_requests',?::integer,
     'max_input_chars',?::integer,'max_output_tokens',?::integer,'candidate_limit',?::integer,'max_matches',?::integer,
     'temperature',nullif(?,''),'reasoning_effort',nullif(?,''),'provider_only',nullif(?,''),'extra_params',?::jsonb,
     'reuse_cache',?::text,'request_delay_ms',?::integer,'read_timeout_ms',?::integer)) AS settings),
     prepared AS(SELECT enrichment.plan_metadata_occupation_batch(coalesce(nullif(?,''),gen_random_uuid()::text),?,?,settings) AS result FROM opts)
     SELECT result->>'batch_id' AS planned_batch_id,result::text AS preparation_json FROM prepared"""
    p.add(database("Freeze inference requests", sql, names[3:] + names[:3]))
    p.add(remember([("planned_batch_id", "METADATA_OCCUPATION_BATCH_ID")]))
    p.add(log("Prepared inferred occupation requests", "Separate metadata inference requests prepared. Confidence remains unassessed; semantic review is separate.", ["planned_batch_id", "preparation_json"]))
    p.save("prepare_inferred_occupations")

    root = E.parse(ROOT / "hop/llm/run_categorize.hpl").getroot()
    put(root.find("info"), "name", "run_inferred_occupations")
    put(root.find("info"), "description", "Execute inferred-only requests sequentially with disabled HTTP retries and redirects.")
    for node in root.findall("transform"):
        if node.findtext("type") == "GetVariable":
            put(node.find("fields/field"), "variable", "${METADATA_OCCUPATION_BATCH_ID}")
        elif node.findtext("name") == "Pending requests":
            put(node, "sql", "SELECT a.attempt_id FROM enrichment.attempt a JOIN enrichment.batch b USING(batch_id) JOIN enrichment.item i ON i.item_id=a.item_id WHERE a.batch_id=? AND a.stage='categorize' AND a.state='PLANNED' AND b.state='RUNNING' AND b.settings->>'execute_requests'='Y' AND b.settings->>'metadata_scope'='NCS_OCCUPATION_INFERENCE_V1' ORDER BY i.ordinal")
        elif node.findtext("type") == "PipelineExecutor":
            put(node, "filename", "${PROJECT_HOME}/ingestions/jobkorea/request_inferred_occupation.hpl")
            put(node, "run_configuration", "jobkorea-local")
    save(root, OUT / "run_inferred_occupations.hpl")

    p = Pipeline("request_inferred_occupation", "One inferred-only paid HTTP attempt; no automatic retry or redirect, no dry-run key read.")
    parameters = p.root.find("info/parameters")
    child(parameters, "parameter", {"name": "ATTEMPT_ID", "default_value": "", "description": "Exact planned inference attempt."})
    p.add(variables([("attempt_id", "ATTEMPT_ID")]))
    java = transform("UserDefinedJavaClass", "Send one reserved inference request")
    put(java, "clear_result_fields", "N")
    put(java, "java_target_version", 17)
    definition = child(E.SubElement(java, "definitions"), "definition", {"class_type": "TRANSFORM_CLASS", "class_name": "MetadataOccupationRequest", "class_source": JAVA})
    assert definition is not None
    fields = E.SubElement(java, "fields")
    child(fields, "field", {"field_name": "request_state", "field_type": "String", "field_length": -1, "field_precision": -1})
    p.add(java)
    p.add(log("Inference attempt state", "One model attempt completed or safely withheld. Inspect the immutable request ledger for details.", ["attempt_id", "request_state"]))
    p.save("request_inferred_occupation")

    p = Pipeline("finish_inferred_occupations", "Capture evidence-validated inferred outcomes without semantic approval; report actual shared-ledger cost.")
    p.add(variables([("batch_id", "METADATA_OCCUPATION_BATCH_ID")]))
    p.add(database("Finish separate inference batch", "SELECT enrichment.finish_metadata_occupation_batch(?)::text AS report_json", ["batch_id"]))
    p.add(log("Inference batch report", "Inferred occupation outcomes recorded with METADATA_INFERRED basis and unassessed confidence. Independent review remains explicit.", ["batch_id", "report_json"]))
    p.save("finish_inferred_occupations")
    workflow("execute_inferred_occupations", "Prepare and optionally execute separate supplied-metadata to NCS occupation inference. Default N makes no key read or model call.", [
        ("Freeze inferred occupation inputs", "ingestions/jobkorea/prepare_inferred_occupations.hpl"),
        ("Send capped sequential inference requests", "ingestions/jobkorea/run_inferred_occupations.hpl"),
        ("Record inferred outcomes and costs", "ingestions/jobkorea/finish_inferred_occupations.hpl"),
    ], PARAMETERS)

    root = E.parse(OUT / "install_linking.hwf").getroot()
    put(root, "name", "Install separate inferred NCS occupation adapter")
    actions = root.find("actions")
    template = deepcopy(next(node for node in actions if node.findtext("type") == "SQL"))
    for node in list(actions):
        if node.findtext("type") == "SQL":
            actions.remove(node)
    labels = ["Start"]
    for filename in ("029_metadata_occupation_links", "030_metadata_occupation_native", "031_metadata_occupation_workers", "032_metadata_occupation_context", "033_metadata_occupation_roles", "034_metadata_occupation_pm", "035_metadata_occupation_terminal_status", "036_batchfree_graph_publication", "037_metadata_occupation_multimatch"):
        node = deepcopy(template)
        put(node, "name", filename)
        put(node, "sqlfilename", "${PROJECT_HOME}/llm/sql/" + filename + ".sql")
        actions.append(node)
        labels.append(filename)
    hops = root.find("hops")
    hops.clear()
    for index, label in enumerate(labels):
        child(hops, "hop", {"from": label, "to": labels[index + 1] if index + 1 < len(labels) else "Success", "enabled": "Y", "evaluation": "Y", "unconditional": "Y" if index == 0 else "N"})
        if index:
            child(hops, "hop", {"from": label, "to": "Abort", "enabled": "Y", "evaluation": "N", "unconditional": "N"})
    save(root, OUT / "install_inferred_occupations.hwf")


if __name__ == "__main__":
    from build_metadata_multimatch import build as build_multimatch

    build_multimatch()
    build()
