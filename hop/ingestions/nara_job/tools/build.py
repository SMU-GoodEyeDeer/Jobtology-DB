"""Regenerate native Hop artifacts for the 나라일터 PblJobService adapter."""
from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as E

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "hop/ingestions/job_alio"
OUT = ROOT / "hop/ingestions/nara_job"
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "sql/003_checks.sql").write_text((ROOT / "docs/hop-migration/checks.sql").read_text())


def save(root, path):
    E.indent(root, space="  ")
    E.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)


def clone(name):
    text = (SRC / name).read_text()
    for old, new in [
        ("JOB_ALIO_RUN_ID", "NARA_JOB_RUN_ID"),
        ("job-alio-local", "nara-job-local"),
        ("ingestions/job_alio", "ingestions/nara_job"),
        ("JOB-ALIO", "나라일터"),
        ("job_alio", "nara_job"),
    ]:
        text = text.replace(old, new)
    return E.fromstring(text)


def transform(root, name):
    return next(n for n in root.findall("transform") if n.findtext("name") == name)


def put(node, tag, value):
    child = node.find(tag)
    if child is None:
        child = E.SubElement(node, tag)
    child.text = str(value)


def sql(root, name, value):
    put(transform(root, name), "sql", value)


def fields(node, specs):
    target = node.find("fields")
    target.clear()
    for name, variable, kind in specs:
        f = E.SubElement(target, "field")
        for key, value in (("name", name), ("variable", variable), ("type", kind),
                           ("length", -1), ("precision", -1), ("trim_type", "none")):
            put(f, key, value)


def params(node, specs):
    target = node.find("parameter")
    target.clear()
    for name, kind in specs:
        f = E.SubElement(target, "field")
        put(f, "name", name); put(f, "type", kind)


def args(node, names):
    target = node.find("arguments")
    target.clear()
    for name in names:
        a = E.SubElement(target, "argument"); put(a, "name", name)


def rest_params(node, specs):
    target = node.find("parameters")
    target.clear()
    for field, name in specs:
        p = E.SubElement(target, "parameter"); put(p, "field", field); put(p, "name", name)


def rename(node, name):
    put(node, "name", name)


def rename_transform(root, old, new):
    rename(transform(root, old), new)
    for hop in root.findall("./order/hop"):
        if hop.findtext("from") == old: put(hop, "from", new)
        if hop.findtext("to") == old: put(hop, "to", new)
    for node in root.findall("transform"):
        for tag in ("send_true_to", "send_false_to", "execution_result_target_transform"):
            if node.findtext(tag) == old: put(node, tag, new)


# Start a bounded recent-window snapshot. Blank dates resolve at run start in KST.
root = clone("start_run.hpl")
fields(transform(root, "Run options"), [
    ("mode", "${MODE}", "String"), ("raw_root", "${RAW_ROOT}", "String"),
    ("begin_choice", "${BEGIN_DATE}", "String"), ("end_choice", "${END_DATE}", "String"),
    ("max_pages", "${MAX_PAGES}", "Integer"), ("max_requests", "${MAX_REQUESTS}", "Integer")])
resolve = transform(root, "Resolve employer snapshot"); rename_transform(root, "Resolve employer snapshot", "Resolve date window")
sql(root, "Resolve date window", """WITH raw AS (SELECT ?::text mode,?::text raw_root,?::text begin_choice,?::text end_choice,?::integer max_pages,?::integer max_requests),
dates AS (SELECT *,CASE WHEN coalesce(begin_choice,'')='' THEN ((clock_timestamp() AT TIME ZONE 'Asia/Seoul')::date-120) WHEN begin_choice~'^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN begin_choice::date END begin_date,
 CASE WHEN coalesce(end_choice,'')='' THEN (clock_timestamp() AT TIME ZONE 'Asia/Seoul')::date WHEN end_choice~'^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN end_choice::date END end_date FROM raw)
SELECT gen_random_uuid()::text run_id,'nara_job'::text upstream_run_id,begin_date,end_date,
 mode IN('FULL','SMOKE') AND nullif(raw_root,'') IS NOT NULL AND begin_date IS NOT NULL AND end_date IS NOT NULL
 AND begin_date<=end_date AND max_pages BETWEEN 1 AND 100 AND max_requests BETWEEN 1 AND 10000 AS options_ok FROM dates""")
params(resolve, [(x,t) for x,t in [("mode","String"),("raw_root","String"),("begin_choice","String"),("end_choice","String"),("max_pages","Integer"),("max_requests","Integer")]])
rename_transform(root, "Employer snapshot found", "Date window resolved")
put(transform(root,"Invalid options"),"message","Require FULL/SMOKE, a raw directory, valid YYYY-MM-DD bounds, and request limits within provider quota.")
create = transform(root, "Create run and dependency"); rename_transform(root, "Create run and dependency", "Create run and index")
sql(root, "Create run and index", """WITH new_run AS (
 INSERT INTO ingestion.run(run_id,source_id,mode,parser_version,policy_revision)
 VALUES(?,'nara_job',?,'hop-nara-job-v1','2026-09-16.1') RETURNING run_id)
INSERT INTO ingestion.partition(run_id,partition_id,kind,request_context,page_size)
SELECT run_id,'index','PAGED',jsonb_build_object('resource','list','begin_date',to_char(?::date,'YYYYMMDD'),
 'end_date',to_char(?::date,'YYYYMMDD'),'as_of',to_char(?::date,'YYYYMMDD')),1000 FROM new_run""")
args(create, ["run_id","mode","begin_date","end_date","end_date"])
save(root, OUT / "start_run.hpl")


# List pages.
root = clone("fetch_list.hpl")
fields(transform(root, "Page context"), [
    ("run_id","${NARA_JOB_RUN_ID}","String"),("page_no","${PAGE_NO}","Integer"),
    ("confirmation_no","${CONFIRMATION_NO}","Integer"),("raw_root","${RAW_ROOT}","String"),
    ("max_requests","${MAX_REQUESTS}","Integer")])
sql(root, "Build archive location", """WITH context AS (SELECT ?::text run_id,?::integer page_no,?::integer confirmation_no,?::text raw_root)
SELECT 'index'::text partition_id,'index:'||page_no||':'||confirmation_no||':1' document_id,
 run_id||'/index/page-'||page_no||'-confirm-'||confirmation_no||'-attempt-1.json' raw_path,
 raw_root||'/'||run_id||'/index/page-'||page_no||'-confirm-'||confirmation_no||'-attempt-1.json' raw_filename,
 p.page_size::bigint page_size,'json'::text result_type,p.request_context->>'begin_date' begin_date,
 p.request_context->>'end_date' end_date,'1'::text sort_order,CURRENT_TIMESTAMP retrieved_at
FROM context c JOIN ingestion.run u USING(run_id) JOIN ingestion.partition p USING(run_id)
WHERE u.state='LOADING' AND u.source_id='nara_job' AND p.partition_id='index' AND page_no>0 AND confirmation_no IN(0,1)""")
params(transform(root, "Build archive location"), [("run_id","String"),("page_no","Integer"),("confirmation_no","Integer"),("raw_root","String")])
rest = transform(root, "Fetch 나라일터 page"); put(rest, "url", "https://apis.data.go.kr/1760000/PblJobService/getList")
rest_params(rest, [("service_key","serviceKey"),("result_type","_type"),("page_no","pageNo"),("page_size","numOfRows"),
                   ("begin_date","Begin_de"),("end_date","End_de"),("sort_order","Sort_order")])
save(root, OUT / "fetch_list.hpl")


# Loader: the PostgreSQL function validates and normalizes the complete envelope.
root = clone("load_document.hpl")
sql(root, "Read document manifest", """SELECT ?||'/'||d.raw_path raw_filename,d.run_id,d.document_id,d.http_status,d.byte_length
FROM ingestion.document d JOIN ingestion.run u USING(run_id)
WHERE d.run_id=? AND d.document_id=? AND u.state='LOADING' AND u.source_id='nara_job'""")
loader = transform(root, "Validate envelope")
sql(root, "Validate envelope", "SELECT document_selected AS envelope_valid,item_count,provider_result,error_code AS envelope_error FROM ingestion.load_nara_document(?,?,?::jsonb,?::integer,?::integer,?::text)")
params(loader, [("run_id","String"),("document_id","String"),("envelope_json","String"),("max_pages","Integer"),("max_requests","Integer"),("mode","String")])
keep = {"Document identity","Read document manifest","HTTP success","Read saved JSON","Validate envelope","Envelope accepted","HTTP failure","Envelope failure","Save envelope metadata"}
for node in list(root.findall("transform")):
    if node.findtext("name") not in keep: root.remove(node)
done = transform(root, "Save envelope metadata"); rename(done, "Document loaded"); put(done, "type", "Dummy")
for child in list(done):
    if child.tag not in ("type","name","distribute","copies","GUI","partitioning","attributes"): done.remove(child)
put(transform(root,"Envelope accepted"),"send_true_to","Document loaded")
put(transform(root,"Envelope accepted"),"send_false_to","Envelope failure")
order = root.find("order"); order.clear()
for a,b in [("Document identity","Read document manifest"),("Read document manifest","HTTP success"),
            ("HTTP success","Read saved JSON"),("HTTP success","HTTP failure"),
            ("Read saved JSON","Validate envelope"),("Validate envelope","Envelope accepted"),
            ("Envelope accepted","Document loaded"),("Envelope accepted","Envelope failure")]:
    h=E.SubElement(order,"hop"); put(h,"from",a);put(h,"to",b);put(h,"enabled","Y")
save(root, OUT / "load_document.hpl")


# Remaining list pages.
root = clone("remaining_pages.hpl")
save(root, OUT / "remaining_pages.hpl")


# Validate the list and plan the three companion endpoints for each active row.
root = clone("plan_details.hpl")
sql(root, "Check list completeness", """WITH target AS (
 SELECT u.run_id,u.mode,p.expected_total,p.page_size FROM ingestion.run u
 JOIN ingestion.partition p ON p.run_id=u.run_id AND p.partition_id='index'
 WHERE u.run_id=? AND u.state='LOADING' AND u.source_id='nara_job'), counts AS (
 SELECT t.*,(SELECT count(*) FROM ingestion.document d WHERE d.run_id=t.run_id AND d.partition_id='index' AND d.selected) documents,
  (SELECT count(*) FROM ingestion.record r JOIN ingestion.document d USING(run_id,document_id)
   WHERE r.run_id=t.run_id AND d.partition_id='index' AND d.selected) records,
  (SELECT count(*) FROM ingestion.record r JOIN ingestion.document d USING(run_id,document_id)
   WHERE r.run_id=t.run_id AND d.partition_id='index' AND d.selected AND coalesce((r.normalized->>'ongoing')::boolean,false)) active_records
 FROM target t)
SELECT mode,
 (CASE WHEN expected_total IS NULL OR records<>expected_total OR documents<>ceil(expected_total::numeric/page_size)::integer THEN 1 ELSE 0 END
  +(SELECT count(*) FROM ingestion.rejected_row e JOIN ingestion.document d USING(run_id,document_id)
    WHERE e.run_id=c.run_id AND d.partition_id='index' AND d.selected)
  +(SELECT count(*) FROM (SELECT r.normalized->>'posting_id' FROM ingestion.record r JOIN ingestion.document d USING(run_id,document_id)
    WHERE r.run_id=c.run_id AND d.partition_id='index' AND d.selected GROUP BY r.normalized->>'posting_id' HAVING count(*)<>1) duplicate_ids)
  +(SELECT count(*) FROM ingestion.document d WHERE d.run_id=c.run_id AND d.partition_id='index' AND d.selected
    AND (d.http_status<>200 OR d.provider_result IS DISTINCT FROM '00' OR d.verified_at IS NULL OR d.item_count IS NULL
      OR d.declared_total IS DISTINCT FROM c.expected_total OR d.effective_page<>d.page_no OR d.effective_page_size<>c.page_size
      OR d.item_count<>(SELECT count(*) FROM ingestion.record r WHERE r.run_id=d.run_id AND r.document_id=d.document_id))))::bigint list_issue_count,
 active_records::bigint list_count,documents::bigint list_documents,?::bigint request_limit FROM counts c""")
params(transform(root,"Check list completeness"),[("run_id","String"),("max_requests","Integer")])
sql(root, "Validate detail plan", "SELECT (?::bigint=0 AND ?::bigint>=1 AND ?::bigint+3*?::bigint<=?::bigint) AS plan_valid")
sql(root, "Create detail partitions", """INSERT INTO ingestion.partition(run_id,partition_id,kind,request_context,page_size,expected_total)
SELECT r.run_id,v.resource||'-'||(r.normalized->>'posting_id'),'DETAIL',
 jsonb_build_object('idx',r.normalized->>'posting_id','resource',v.resource,
  'as_of',(SELECT request_context->>'as_of' FROM ingestion.partition x WHERE x.run_id=r.run_id AND x.partition_id='index')),1,1
FROM ingestion.record r JOIN ingestion.document d USING(run_id,document_id) JOIN ingestion.run u USING(run_id)
CROSS JOIN (VALUES('detail'),('positions'),('files')) v(resource)
WHERE r.run_id=? AND u.state='LOADING' AND u.source_id='nara_job' AND d.selected AND d.partition_id='index'
 AND coalesce((r.normalized->>'ongoing')::boolean,false)""")
save(root, OUT / "plan_resources.hpl")


def resource_child(resource, operation):
    root = clone("fetch_detail.hpl")
    root.find("info").find("parameters").find("parameter").find("name").text = "POSTING_ID"
    sql(root, "Build archive location", f"""WITH context AS (SELECT ?::text run_id,?::text posting_id,?::text raw_root)
SELECT p.partition_id,p.partition_id||':1:0:1' document_id,
 c.run_id||'/{resource}/'||encode(sha256(convert_to(posting_id,'UTF8')),'hex')||'.json' raw_path,
 raw_root||'/'||c.run_id||'/{resource}/'||encode(sha256(convert_to(posting_id,'UTF8')),'hex')||'.json' raw_filename,
 1::bigint page_no,0::bigint confirmation_no,1::bigint page_size,'json'::text result_type,CURRENT_TIMESTAMP retrieved_at
FROM context c JOIN ingestion.run u USING(run_id) JOIN ingestion.partition p
 ON p.run_id=c.run_id AND p.partition_id='{resource}-'||c.posting_id
WHERE u.state='LOADING' AND u.source_id='nara_job' AND p.kind='DETAIL'""")
    rest = transform(root, "Fetch 나라일터 page")
    rename_transform(root, "Fetch 나라일터 page", f"Fetch 나라일터 {resource}")
    rest = transform(root, f"Fetch 나라일터 {resource}")
    put(rest, "url", f"https://apis.data.go.kr/1760000/PblJobService/{operation}")
    rest_params(rest, [("service_key","serviceKey"),("result_type","_type"),("posting_id","idx"),
                       ("page_no","pageNo"),("page_size","numOfRows")])
    save(root, OUT / f"fetch_{resource}.hpl")


for resource, operation in [("detail","getItem"),("positions","getItemPosition"),("files","getItemFile")]:
    resource_child(resource, operation)
    root = clone("fetch_details.hpl")
    sql(root, "Read planned postings", f"""SELECT request_context->>'idx' posting_id FROM ingestion.partition p JOIN ingestion.run u USING(run_id)
WHERE p.run_id=? AND u.state='LOADING' AND u.source_id='nara_job' AND p.partition_id LIKE '{resource}-%' ORDER BY partition_id""")
    executor = transform(root, "Run child pipeline")
    put(executor, "filename", "${PROJECT_HOME}/ingestions/nara_job/fetch_"+resource+".hpl")
    put(executor, "copies", "4")
    # Each error branch owns one Abort input, avoiding Hop's empty multi-input
    # polling loop while parallel child requests are still running.
    rename_transform(root,"Child failed","Child error count failed")
    error_abort=transform(root,"Child error count failed")
    result_abort=deepcopy(error_abort);rename(result_abort,"Child result failed");root.append(result_abort)
    put(transform(root,"Child completed"),"send_false_to","Child result failed")
    for hop in root.findall("./order/hop"):
        if hop.findtext("from")=="Child completed" and hop.findtext("to")=="Child error count failed":
            put(hop,"to","Child result failed")
    save(root, OUT / f"fetch_all_{resource}.hpl")


# Final state and report.
root = clone("finalize.hpl")
sql(root, "Summarize validation", """SELECT u.mode,(SELECT count(*) FROM ingestion.validation_issue v WHERE v.run_id=u.run_id
AND NOT(u.mode='SMOKE' AND (v.issue='SMOKE_NOT_FULL' OR (v.issue='PARTITION_INCOMPLETE' AND v.location='index')))) issue_count,
(SELECT count(*) FROM ingestion.rejected_row r WHERE r.run_id=u.run_id) rejected_count,
(SELECT count(*) FROM ingestion.record r WHERE r.run_id=u.run_id) record_count,
(SELECT count(*) FROM ingestion.document d WHERE d.run_id=u.run_id AND d.selected) document_count,
(SELECT count(*) FROM ingestion.record r JOIN ingestion.document d USING(run_id,document_id)
 WHERE r.run_id=u.run_id AND d.selected AND d.partition_id='index' AND coalesce((r.normalized->>'ongoing')::boolean,false)) posting_count,
0::bigint unmatched_employer_count FROM ingestion.run u WHERE u.run_id=? AND u.state='LOADING' AND u.source_id='nara_job'""")
sql(root, "Finalize run state", """UPDATE ingestion.run u SET state=CASE
WHEN EXISTS(SELECT 1 FROM ingestion.rejected_row r WHERE r.run_id=u.run_id) THEN 'REVIEW_REQUIRED'
WHEN (SELECT count(*) FROM ingestion.validation_issue v WHERE v.run_id=u.run_id
 AND NOT(u.mode='SMOKE' AND (v.issue='SMOKE_NOT_FULL' OR (v.issue='PARTITION_INCOMPLETE' AND v.location='index'))))>0 THEN 'FAILED'
WHEN u.mode='SMOKE' THEN 'REVIEW_REQUIRED' ELSE 'READY' END,completed_at=CURRENT_TIMESTAMP
WHERE u.run_id=? AND u.source_id='nara_job' AND u.state='LOADING'""")
rename(transform(root, "나라일터 result"), "나라일터 result")
save(root, OUT / "finalize.hpl")


# Failure path and raw-file verification need only source/path substitutions.
for name in ("verify_files.hpl","mark_failed.hpl"):
    save(clone(name), OUT / name)


# Assemble workflow with three resource passes.
root = clone("full.hwf")
put(root, "name", "나라일터 postings")
put(root, "description", "Fetch a bounded recent index and all detail, position and file metadata for postings open at the snapshot date.")
params_node = root.find("parameters"); params_node.clear()
for name, default, description in [
    ("MAX_PAGES","20","Maximum recent-window list pages."),("BEGIN_DATE","","YYYY-MM-DD; blank means 120 days before the KST run date."),
    ("END_DATE","","YYYY-MM-DD; blank means the KST run date."),("RAW_ROOT","${PROJECT_HOME}/data/nara-job-raw","Persistent raw response directory."),
    ("MAX_REQUESTS","5000","List plus three companion requests per active posting; maximum 10000."),
    ("MODE","FULL","FULL makes a READY snapshot; SMOKE remains REVIEW_REQUIRED."),
    ("API_KEY_FILE","${HOP_CONFIG_FOLDER}/secrets/data-go-kr.csv","CSV with service_key header and one decoded key.")]:
    p=E.SubElement(params_node,"parameter");put(p,"name",name);put(p,"description",description);put(p,"default_value",default)
actions = root.find("actions")
by_name = {a.findtext("name"):a for a in actions.findall("action")}
start_action=by_name["Create run and pin employers"]
plan_action=by_name["Validate list and plan details"]
rename(start_action, "Create run and pin date window")
rename(plan_action, "Validate list and plan resources")
put(plan_action, "filename", "${PROJECT_HOME}/ingestions/nara_job/plan_resources.hpl")
detail_action = by_name["Fetch every posting detail"]
rename(detail_action, "Fetch every posting detail")
put(detail_action,"filename","${PROJECT_HOME}/ingestions/nara_job/fetch_all_detail.hpl")
position_action=deepcopy(detail_action);rename(position_action,"Fetch every posting position");put(position_action,"filename","${PROJECT_HOME}/ingestions/nara_job/fetch_all_positions.hpl");actions.append(position_action)
file_action=deepcopy(detail_action);rename(file_action,"Fetch every posting file list");put(file_action,"filename","${PROJECT_HOME}/ingestions/nara_job/fetch_all_files.hpl");actions.append(file_action)
hops=root.find("hops")
for h in hops.findall("hop"):
    for tag in ("from","to"):
        if h.findtext(tag)=="Create run and pin employers": put(h,tag,"Create run and pin date window")
        if h.findtext(tag)=="Validate list and plan details": put(h,tag,"Validate list and plan resources")
for h in hops.findall("hop"):
    if h.findtext("from")=="Fetch every posting detail" and h.findtext("to")=="Verify all archived files":
        put(h,"to","Fetch every posting position")
for a,b in [("Fetch every posting position","Fetch every posting file list"),("Fetch every posting file list","Verify all archived files")]:
    h=E.SubElement(hops,"hop");put(h,"from",a);put(h,"to",b);put(h,"enabled","Y");put(h,"evaluation","Y");put(h,"unconditional","N")
for a in (position_action,file_action):
    h=E.SubElement(hops,"hop");put(h,"from",a.findtext("name"));put(h,"to","Record failure");put(h,"enabled","Y");put(h,"evaluation","N");put(h,"unconditional","N")
save(root, OUT / "full.hwf")


# One-click additive database installation from Hop Web.
workflow = E.Element("workflow")
for tag,value in (("name","Install 나라일터 ingestion"),("description","Install the source adapter and request policy."),
                  ("workflow_version","1"),("workflow_status","0")):
    put(workflow,tag,value)
E.SubElement(workflow,"parameters"); actions=E.SubElement(workflow,"actions")
def action(name, kind, x, sqlfile=None, message=None):
    a=E.SubElement(actions,"action");put(a,"name",name);put(a,"type",kind)
    if sqlfile:
        put(a,"connection","jobtology-postgres");put(a,"sqlfromfile","Y");put(a,"sqlfilename",sqlfile)
        put(a,"sqlfilename_encoding","UTF-8");put(a,"useVariableSubstitution","N");put(a,"sendOneStatement","Y")
    if message: put(a,"message",message)
    put(a,"xloc",x);put(a,"yloc",80);put(a,"draw","Y");put(a,"parallel","N");E.SubElement(a,"attributes")
    if kind=="SPECIAL": put(a,"start","Y")
    return a
action("Start","SPECIAL",80); action("Success","SUCCESS",1040); action("Abort","ABORT",1040,message="나라일터 adapter installation failed.")
action("Install source schema","SQL",320,"${PROJECT_HOME}/ingestions/nara_job/sql/001_schema.sql")
action("Install request policy","SQL",560,"${PROJECT_HOME}/ingestions/nara_job/sql/002_operations.sql")
action("Install validation checks","SQL",800,"${PROJECT_HOME}/ingestions/nara_job/sql/003_checks.sql")
hops=E.SubElement(workflow,"hops")
for a,b,ok,unconditional in [("Start","Install source schema","Y","Y"),("Install source schema","Install request policy","Y","N"),
                             ("Install source schema","Abort","N","N"),("Install request policy","Install validation checks","Y","N"),
                             ("Install request policy","Abort","N","N"),("Install validation checks","Success","Y","N"),
                             ("Install validation checks","Abort","N","N")]:
    h=E.SubElement(hops,"hop");put(h,"from",a);put(h,"to",b);put(h,"enabled","Y");put(h,"evaluation",ok);put(h,"unconditional",unconditional)
E.SubElement(workflow,"attributes")
save(workflow,OUT/"install.hwf")


# Run configurations are intentionally source-specific for visible Hop choices.
for kind in ("pipeline","workflow"):
    src = ROOT / f"hop/metadata/{kind}-run-configuration/job-alio-local.json"
    text = src.read_text().replace("job-alio-local","nara-job-local").replace("JOB-ALIO","나라일터")
    (ROOT / f"hop/metadata/{kind}-run-configuration/nara-job-local.json").write_text(text)
