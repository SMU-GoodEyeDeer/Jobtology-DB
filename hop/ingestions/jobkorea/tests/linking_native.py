# ruff: noqa: E501
"""Actual local sample planning and synthetic reviewed-link native verification.

All resources are unique disposable containers on an INTERNAL network. Synthetic
model envelopes enter through a test-only guarded Hop JDBC pipeline, never HTTP.
No production connection, source URL, secret or paid API is used.
"""
import argparse
import json
import os
import shutil
import xml.etree.ElementTree as E
from copy import deepcopy
from pathlib import Path

from native import REMOTE, ROOT, Fixture


def q(value):
    return "'" + str(value).replace("'", "''") + "'"


def js(value):
    return q(json.dumps(value, ensure_ascii=False)) + "::jsonb"


class LinkingFixture(Fixture):
    def stage(self):
        super().stage()
        project = self.work / "project"
        shutil.copytree(ROOT / "hop/llm", project / "llm",
                        ignore=shutil.ignore_patterns("tests", "tools", "__pycache__", "*.pyc"))
        for kind in ("pipeline", "workflow"):
            for name in ("llm-local", "link-graph-local"):
                source = ROOT / f"hop/metadata/{kind}-run-configuration/{name}.json"
                if source.exists():
                    shutil.copyfile(source, project / f"metadata/{kind}-run-configuration/{name}.json")
        self.stage_response_pipeline(project)

    def stage_response_pipeline(self, project):
        root = E.parse(project / "ingestions/jobkorea/import_local.hpl").getroot()
        for transform in list(root.findall("transform")):
            root.remove(transform)
        root.find("info/name").text = "fixture_response"
        root.find("info/description").text = "TEST ONLY: synthetic envelope, isolated database guard, no HTTP."
        root.find("info/parameters").clear()
        variables = deepcopy(E.parse(ROOT / "hop/llm/review_extraction.hpl").find("transform[type='GetVariable']"))
        variables.find("name").text = "Synthetic fixture options"
        variables.find("fields").clear()
        for name, variable in (("attempt", "ATTEMPT_ID"), ("file", "RESPONSE_FILE")):
            field = E.SubElement(variables.find("fields"), "field")
            for key, value in (("name", name), ("variable", "${" + variable + "}"), ("type", "String"),
                               ("length", "-1"), ("precision", "-1"), ("trim_type", "none")):
                E.SubElement(field, key).text = value
        root.append(variables)
        java = deepcopy(E.parse(ROOT / "hop/ingestions/jobkorea/import_local.hpl").find("transform[type='UserDefinedJavaClass']"))
        java.find("name").text = "Persist synthetic fixture response"
        java.find("fields").clear()
        java.find("definitions/definition/class_name").text = "SyntheticFixtureResponse"
        java.find("definitions/definition/class_source").text = r'''
public boolean processRow() throws HopException {
 Object[] row=getRow(); if(row==null){setOutputDone();return false;}
 org.apache.hop.core.database.Database db=null;
 try {
  String token=System.getenv("JOBKOREA_ISOLATED_TOKEN");
  if(token==null || !token.matches("[0-9a-f]{12}")) throw new Exception("FIXTURE_REQUIRED");
  org.apache.hop.core.database.DatabaseMeta meta=(org.apache.hop.core.database.DatabaseMeta)
   getPipelineMeta().getMetadataProvider().getSerializer(org.apache.hop.core.database.DatabaseMeta.class).load("jobtology-postgres");
  db=new org.apache.hop.core.database.Database(getParent(),getParent(),meta);db.connect();
  java.sql.Connection jdbc=db.getConnection();
  java.sql.PreparedStatement guard=jdbc.prepareStatement("SELECT current_database()=? AND current_setting('jobtology.isolated_fixture',true)=?");
  guard.setString(1,"jobkorea_dryrun_"+token);guard.setString(2,token);
  java.sql.ResultSet check=guard.executeQuery();boolean isolated=check.next()&&check.getBoolean(1);check.close();guard.close();
  if(!isolated)throw new Exception("FIXTURE_REQUIRED");
  java.nio.file.Path file=java.nio.file.Paths.get(get(Fields.In,"file").getString(row)).normalize();
  if(!file.startsWith(java.nio.file.Paths.get("/fixture/inputs")) || java.nio.file.Files.isSymbolicLink(file)
   || java.nio.file.Files.size(file)>1048576)throw new Exception("FIXTURE_FILE_REQUIRED");
  String body=java.nio.file.Files.readString(file,java.nio.charset.StandardCharsets.UTF_8);
  String attempt=get(Fields.In,"attempt").getString(row);
  java.sql.PreparedStatement reserve=jdbc.prepareStatement("SELECT enrichment.reserve_request(?)");
  reserve.setString(1,attempt);reserve.execute();reserve.close();
  java.sql.PreparedStatement save=jdbc.prepareStatement("SELECT enrichment.save_response(?,200,?,1)");
  save.setString(1,attempt);save.setString(2,body);save.execute();save.close();
  putRow(data.outputRowMeta,row);return true;
 } catch(Exception e){throw new HopException("Synthetic fixture response rejected ("+e.getClass().getSimpleName()+")");}
 finally{if(db!=null)db.close();}
}
'''
        root.append(java)
        order = root.find("order")
        order.clear()
        hop = E.SubElement(order, "hop")
        for key, value in (("from", "Synthetic fixture options"), ("to", "Persist synthetic fixture response"), ("enabled", "Y")):
            E.SubElement(hop, key).text = value
        E.indent(root, space="  ")
        E.ElementTree(root).write(project / "ingestions/jobkorea/fixture_response.hpl", encoding="UTF-8", xml_declaration=True)

    def seed_ncs(self):
        ncs = "synthetic-ncs-" + self.token
        if self.sql(f"SELECT count(*) FROM ingestion.run WHERE run_id={q(ncs)}", "ncs-fixture-existing") == "1":
            return ncs
        rows = [dict(kind="Competency", code="2001020403_24v1", name="데이터베이스 설계",
                     definition="데이터 요구사항에 따라 데이터베이스와 테이블을 설계하는 능력",
                     occupation_code="20010204", occupation_name="DB엔지니어링", level=4),
                dict(kind="Competency", code="2001020404_24v1", name="데이터베이스 구축",
                     definition="데이터베이스 환경과 테이블을 구축하는 능력",
                     occupation_code="20010204", occupation_name="DB엔지니어링", level=4)]
        self.sql(f"""INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state,completed_at)
VALUES({q(ncs)},'ncs_competency','FULL','SYNTHETIC_FIXTURE','READY',clock_timestamp());
INSERT INTO ingestion.partition(run_id,partition_id,kind,page_size,expected_total)
VALUES({q(ncs)},'synthetic','FILE',2,2);
INSERT INTO ingestion.document(run_id,document_id,partition_id,page_no,raw_path,raw_sha256,byte_length,encoding,
 http_status,retrieved_at,declared_total,effective_page,effective_page_size,item_count,selected,verified_at)
VALUES({q(ncs)},'synthetic','synthetic',1,'synthetic-ncs.json',repeat('a',64),1,'UTF-8',200,clock_timestamp(),2,1,2,2,true,clock_timestamp());
""", "synthetic-ncs-ledger")
        for index, row in enumerate(rows):
            self.sql(f"INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) VALUES({q(ncs)},'synthetic',{q('/'+str(index))},{q(row['code'])},{js(row)},{js(row)})", "synthetic-ncs-row")
        self.expect(self.sql(f"SELECT count(*) FROM ingestion.validation_issue WHERE run_id={q(ncs)}", "ncs-validation") == "0", "validated-synthetic-ncs")
        return ncs

    def module(self, filename, label, params=None, success=True):
        self.run("../../llm/" + filename, label, success=success, extra=params or {})

    def synthetic_batch(self, jobs, ncs, ids, bundles):
        settings = dict(job_source_id="jobkorea", extract_model="fixture/synthetic", categorize_model="fixture/synthetic",
                        prompt_version="ko-link-v1", extra_params={}, limit=len(ids.split("|")), candidate_limit=20, max_matches=5,
                        max_input_chars=24000, max_output_tokens=3000, max_requests=10, request_reserve_usd=.05,
                        max_cost_usd=.25, daily_budget_usd=3, execute_requests="Y", reuse_cache="N",
                        endpoint="https://example.invalid/synthetic-never-called/chat/completions", request_delay_ms=1, read_timeout_ms=5000,
                        acceptance_policy="REVIEW", posting_ids=ids, input_bundle_ids=bundles)
        batch = "synthetic-batch-" + self.token + "-" + str(len(self.receipt["checks"]))
        self.sql(f"SELECT enrichment.plan_batch({q(batch)},'ENRICH',NULL,{q(jobs)},{q(ncs)},{js(settings)}); SELECT enrichment.plan_stage({q(batch)},'extract')", "plan-synthetic-extraction")
        return batch

    def response(self, attempt, output, label):
        envelope = dict(id="SYNTHETIC_OFFLINE_" + label, model="fixture/synthetic",
                        choices=[dict(finish_reason="stop", message=dict(content=json.dumps(output, ensure_ascii=False)))],
                        usage=dict(prompt_tokens=100, completion_tokens=30))
        file = self.work / "inputs" / (label + ".json")
        file.write_text(json.dumps(envelope, ensure_ascii=False))
        self.run("fixture_response.hpl", label, extra={"ATTEMPT_ID": attempt, "RESPONSE_FILE": REMOTE + "/inputs/" + file.name})


def check_no_pending(fixture):
    closed = [dict(product_page_url="https://www.jobkorea.co.kr/Recruit/GI_Read/90000000",
                   job_title="SYNTHETIC closed database developer", source_status="CLOSED")]
    (fixture.work / "inputs/synthetic-closed.json").write_text(json.dumps(closed))
    fixture.run("import_local.hpl", "native-closed-fixture-import", input_name="synthetic-closed.json")
    jobs = fixture.sql("SELECT run_id FROM ingestion.latest_ready_run WHERE source_id='jobkorea'", "closed-source-pin")
    ncs = fixture.seed_ncs()
    fixture.run("install_linking.hwf", "native-closed-linking-installer")
    before = fixture.sql("SELECT count(*) FROM enrichment.batch", "no-pending-batch-before")
    fixture.run("prepare_linking.hwf", "native-no-pending-skip",
                extra={"JOB_RUN_ID": jobs, "NCS_RUN_ID": ncs, "API_KEY_FILE": "/does-not-exist"})
    fixture.expect(before == fixture.sql("SELECT count(*) FROM enrichment.batch", "no-pending-batch-after"), "no-pending-successful-no-op")
    fixture.expect(fixture.sql("SELECT count(*) FROM enrichment.attempt WHERE reserved_at IS NOT NULL", "no-pending-reservations") == "0", "no-pending-no-key-or-model-request")


def check(fixture):
    fixture.run("install.hwf", "native-source-installer")
    fixture.run("full.hwf", "native-sample-import")
    jobs = fixture.sql("SELECT run_id FROM ingestion.latest_ready_run WHERE source_id='jobkorea'", "sample-source-pin")
    fixture.expect(fixture.sql(f"SELECT count(*) FROM ingestion.ready_record WHERE run_id={q(jobs)}", "sample-count") == "887", "actual-887-sample-ready")
    ncs = fixture.seed_ncs()
    fixture.run("install_linking.hwf", "native-linking-installer")
    fixture.run("install_linking.hwf", "native-linking-installer-replay")
    before = fixture.sql("SELECT count(*) FROM enrichment.input_bundle", "bundles-before-preview")
    params = {"JOB_RUN_ID": jobs, "NCS_RUN_ID": ncs, "API_KEY_FILE": "/does-not-exist"}
    fixture.run("preview_linking.hwf", "native-read-only-scope", extra=params)
    fixture.expect(before == fixture.sql("SELECT count(*) FROM enrichment.input_bundle", "bundles-after-preview"), "scope-preview-read-only")
    fixture.run("prepare_linking.hwf", "native-default-pilot-preparation", extra=params)
    batch = fixture.sql("SELECT batch_id FROM enrichment.batch ORDER BY created_at DESC LIMIT 1", "pilot-batch")
    report = json.loads(fixture.sql(f"SELECT to_jsonb(b) FROM enrichment.batch b WHERE batch_id={q(batch)}", "pilot-settings"))
    fixture.expect(report["job_run_id"] == jobs and report["ncs_run_id"] == ncs and report["settings"]["execute_requests"] == "N", "exact-pins-and-no-execution")
    fixture.expect(fixture.sql(f"SELECT count(*) FROM enrichment.item WHERE batch_id={q(batch)}", "pilot-size") == "5", "small-five-posting-pilot")
    fixture.expect(fixture.sql("SELECT count(*) FROM enrichment.attempt WHERE reserved_at IS NOT NULL", "no-reservations") == "0", "zero-http-and-charged-reservations")
    ids = report["settings"]["posting_ids"]
    bundles = report["settings"]["input_bundle_ids"]
    fixture.run("prepare_linking.hwf", "native-preparation-replay", extra=params)
    fixture.expect(fixture.sql("SELECT count(*) FROM enrichment.input_bundle", "stable-bundle-count") == "5", "immutable-five-bundle-replay")
    fixture.receipt["scope_preview"] = json.loads(fixture.sql(f"SELECT enrichment.jobkorea_linking_preview({q(jobs)},{q(ncs)},5)", "scope-preview"))
    fixture.receipt["sample_rows"] = 887
    fixture.receipt["pilot_rows"] = 5
    synthetic = fixture.synthetic_batch(jobs, ncs, ids, bundles)
    attempts = json.loads(fixture.sql(f"SELECT jsonb_agg(attempt_id ORDER BY attempt_id) FROM enrichment.attempt WHERE batch_id={q(synthetic)} AND stage='extract'", "synthetic-extract-attempts"))
    for index, attempt in enumerate(attempts):
        fixture.response(attempt, dict(positions=[], duties=[], requirements=[], duties_status="not_stated"), "synthetic-missing-duty-" + str(index))
    fixture.sql(f"SELECT enrichment.plan_stage({q(synthetic)},'categorize'); SELECT enrichment.finish_batch({q(synthetic)})", "finish-synthetic-missing-duty")
    fixture.expect(fixture.sql(f"SELECT count(*) FROM enrichment.attempt WHERE batch_id={q(synthetic)} AND stage='extract' AND state='VALIDATED'", "validated-empty-extractions") == "5", "validated-missing-duty-abstention")
    fixture.expect(fixture.sql(f"SELECT count(*) FROM enrichment.attempt WHERE batch_id={q(synthetic)} AND stage='categorize' AND reserved_at IS NOT NULL", "no-paid-duty-matching") == "0", "missing-duties-never-match-request")
    fixture.expect(fixture.sql(f"SELECT bool_and(cost_usd IS NULL AND enrichment.accounted_cost(state,cost_usd,reserved_usd)=reserved_usd) FROM enrichment.attempt WHERE batch_id={q(synthetic)} AND reserved_at IS NOT NULL", "unknown-cost-accounting") == "t", "unknown-cost-keeps-reservation")
    check_positive(fixture, ncs)


def check_positive(fixture, ncs):
    fixture.run("../../graph/load_snapshot.hwf", "native-pinned-ncs-source-graph",
                extra={"RUN_ID": ncs, "NEO4J_CONNECTION": "jobtology-neo4j"})

    toy = [dict(product_page_url="https://www.jobkorea.co.kr/Recruit/GI_Read/90000001", job_title="데이터베이스 개발자",
                company_name="SYNTHETIC FIXTURE EMPLOYER", description_text="담당 업무\n데이터베이스와 테이블을 설계하고 구축한다")]
    (fixture.work / "inputs/synthetic-posting.json").write_text(json.dumps(toy, ensure_ascii=False))
    fixture.run("full.hwf", "import-synthetic-narrative", input_name="synthetic-posting.json")
    toy_jobs = fixture.sql("SELECT run_id FROM ingestion.latest_ready_run WHERE source_id='jobkorea'", "synthetic-source-pin")
    prepared = json.loads(fixture.sql(f"SELECT enrichment.prepare_jobkorea_linking_pilot({q(toy_jobs)},{q(ncs)},1)", "prepare-synthetic-input"))
    toy_batch = fixture.synthetic_batch(toy_jobs, ncs, prepared["posting_ids"], prepared["bundle_ids"])
    item = json.loads(fixture.sql(f"SELECT to_jsonb(i) FROM enrichment.item i WHERE batch_id={q(toy_batch)}", "synthetic-item"))
    output = dict(positions=[], duties=[dict(position_ids=[], text_parts=["데이터베이스와 테이블을 설계하고 구축한다"], evidence_ids=["description_text:2"])], requirements=[], duties_status="explicit")
    fixture.response(item["extraction_id"], output, "synthetic-explicit-duty")
    fixture.sql(f"SELECT enrichment.plan_stage({q(toy_batch)},'categorize')", "synthetic-match-plan")
    category = fixture.sql(f"SELECT categorization_id FROM enrichment.item WHERE item_id={q(item['item_id'])}", "synthetic-category-id")
    fixture.response(category, dict(matches=[dict(competency_code="2001020403_24v1", duty_index=0, reason="SYNTHETIC FIXTURE: 명시된 데이터베이스 설계 업무")], outcome="matched"), "synthetic-supported-ncs")
    fixture.module("finish_batch.hpl", "native-finish-synthetic-batch", {"LLM_BATCH_ID": toy_batch})
    fixture.module("capture_extraction.hwf", "native-capture-synthetic-revision", {"ITEM_ID": item["item_id"], "ACTOR": "synthetic-fixture-editor", "REASON": "SYNTHETIC OFFLINE response; evidence validation test"})
    revision = fixture.sql(f"SELECT revision_id FROM enrichment.extraction_revision WHERE item_id={q(item['item_id'])}", "synthetic-revision")
    fixture.module("import_model_links.hpl", "native-import-synthetic-link", {"REVISION_ID": revision, "ACTOR": "synthetic-fixture-linker"})
    fixture.expect(fixture.sql("SELECT count(*) FROM enrichment.link_publication_source", "unreviewed-publication-count") == "0", "unreviewed-links-not-publishable")
    fixture.module("review_extraction.hwf", "native-review-synthetic-extraction", {"REVISION_ID": revision, "DECISION": "ACCEPT", "REVIEWER": "synthetic-source-reviewer", "REVIEWER_KIND": "assistant", "NOTES": "SYNTHETIC fixture: exact local narrative checked"})
    candidate = fixture.sql(f"SELECT candidate_id FROM enrichment.link_candidate WHERE revision_id={q(revision)}", "synthetic-candidate")
    fixture.module("review_link.hwf", "native-review-synthetic-link", {"CANDIDATE_ID": candidate, "DECISION": "ACCEPT", "REVIEWER": "synthetic-ncs-reviewer", "REVIEWER_KIND": "assistant", "NOTES": "SYNTHETIC fixture: explicit database design duty and pinned definition overlap"})
    fixture.module("install.hwf", "native-canonical-llm-installer-replay")
    fixture.expect(fixture.sql(f"DO $$ BEGIN PERFORM enrichment.verify_input_bundle({q(prepared['bundle_ids'])}); END $$; SELECT 'valid'", "canonical-bundle-verifier") == "valid", "canonical-replay-keeps-jobkorea-bundle-dispatcher")
    fixture.expect(fixture.sql(f"SELECT enrichment.input_fields(source_data)=source_data-'_input' FROM enrichment.input_bundle WHERE bundle_id={q(prepared['bundle_ids'])}", "canonical-input-fields") == "t", "canonical-replay-keeps-jobkorea-input-fields")
    fixture.expect(fixture.sql(f"SELECT count(*) FROM enrichment.current_reviewed_posting WHERE run_id={q(toy_jobs)} AND posting_id={q(prepared['posting_ids'])} AND revision_id={q(revision)} AND decision='ACCEPT'", "canonical-reviewed-view") == "1", "canonical-replay-keeps-current-reviewed-posting")
    fixture.expect(fixture.sql(f"SELECT p.content_hash=i.source_hash FROM cs.common_posting p JOIN enrichment.item i ON i.posting_id=p.posting_id WHERE p.snapshot_run_id={q(toy_jobs)} AND i.item_id={q(item['item_id'])}", "canonical-cs-hash") == "t", "canonical-replay-keeps-cs-content-hash")
    publication = "synthetic-jobkorea-publication-" + fixture.token
    fixture.module("publish_links.hwf", "native-reviewed-ncs-publication", {"PUBLICATION_ID": publication, "NEO4J_CONNECTION": "jobtology-neo4j"})
    fixture.module("publish_links.hwf", "native-reviewed-ncs-publication-replay", {"PUBLICATION_ID": publication, "NEO4J_CONNECTION": "jobtology-neo4j"})
    count = fixture.command(["docker", "exec", fixture.neo, "cypher-shell", "--format", "plain",
                             "MATCH ()-[r:ALIGNS_WITH_NCS]->() RETURN count(r)"], "independent-reviewed-ncs-count")
    fixture.expect("1" in count.splitlines(), "independent-reviewed-ncs-graph-and-replay")
    before = fixture.sql("SELECT count(*) FROM enrichment.batch", "batch-count-before-exhausted-pilot")
    fixture.run("prepare_linking.hwf", "native-exhausted-pilot-no-op",
                extra={"JOB_RUN_ID": toy_jobs, "NCS_RUN_ID": ncs, "API_KEY_FILE": "/does-not-exist"})
    fixture.expect(before == fixture.sql("SELECT count(*) FROM enrichment.batch", "batch-count-after-exhausted-pilot"), "exhausted-pilot-skips-new-batch-and-key-read")
    fixture.expect(fixture.sql("SELECT count(*) FROM ingestion.request_attempt", "source-request-count") == "0", "no-job-board-requests")
    fixture.receipt["synthetic_responses"] = True
    fixture.receipt["model_http_requests"] = 0
    fixture.receipt["paid_cost_usd"] = 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT.parent / "jobtology/j_muwj57zxdc6o3utkq.json")
    parser.add_argument("--positive-only", action="store_true", help="Target new no-work and positive reviewed-link fixture checks.")
    args = parser.parse_args()
    os.umask(0o077)
    fixture = LinkingFixture(args.input)
    try:
        fixture.boot()
        fixture.install()
        check_no_pending(fixture)
        if args.positive_only:
            check_positive(fixture, fixture.seed_ncs())
        else:
            check(fixture)
        fixture.receipt["status"] = "PASSED_LINKING_PREPARATION"
    except Exception:
        fixture.receipt["status"] = "FAILED"
        raise
    finally:
        fixture.close()
        print("Protected linking receipt: " + str(fixture.work / "receipt.json"), flush=True)


if __name__ == "__main__":
    main()
