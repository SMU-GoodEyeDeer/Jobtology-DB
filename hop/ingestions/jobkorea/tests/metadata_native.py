# ruff: noqa: E501
"""Network-isolated native inferred-occupation request and accounting proof.

Uses synthetic local listings, a disposable HTTP mock and no real credentials,
job-board requests, paid APIs or production database writes.
"""

import json
import os
import subprocess
from pathlib import Path

from linking_native import LinkingFixture, js, q
from native import REMOTE

MOCK_JAVA = r'''
import com.sun.net.httpserver.HttpServer;
import java.nio.file.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
public class MetadataMock {
 public static void main(String[] args) throws Exception {
  Path root=Paths.get(args[0]);HttpServer server=HttpServer.create(new InetSocketAddress(18080),0);
  server.createContext("/chat/completions",exchange->{
   byte[] request=exchange.getRequestBody().readAllBytes();
   Files.writeString(root.resolve("count.ndjson"),"{}\n",StandardOpenOption.CREATE,StandardOpenOption.APPEND);
   String mode=Files.readString(root.resolve("mode")).trim();
   String output="{\"outcome\":\"matched\",\"matches\":[{\"occupation_code\":\"20010204\",\"reason\":\"제목의 데이터베이스 역할\",\"evidence\":[{\"field\":\"title\",\"quote\":\"데이터베이스\"}]}],\"abstain_reason\":\"\"}";
   if(mode.equals("invalid"))output=output.replace("\"quote\":\"데이터베이스\"","\"quote\":\"위조인용\"");
   String escaped=output.replace("\\","\\\\").replace("\"","\\\"");
   String body="{\"id\":\"isolated-native-mock\",\"model\":\"fixture/metadata\",\"choices\":[{\"finish_reason\":\"stop\",\"message\":{\"content\":\""+escaped+"\"}}],\"usage\":{\"prompt_tokens\":100,\"completion_tokens\":40,\"cost\":0.00001,\"is_byok\":true,\"cost_details\":{\"upstream_inference_cost\":0.0002}}}";
   int status=200;
   if(mode.equals("429")){status=429;body="{\"error\":{\"message\":\"isolated rate limit\"}}";}
   if(mode.equals("302")){status=302;body="{}";exchange.getResponseHeaders().set("Location","http://127.0.0.1:18080/chat/completions");}
   if(mode.equals("timeout"))try{Thread.sleep(2500);}catch(InterruptedException ignored){}
   byte[] response=body.getBytes(StandardCharsets.UTF_8);exchange.getResponseHeaders().set("Content-Type","application/json");
   try{exchange.sendResponseHeaders(status,response.length);exchange.getResponseBody().write(response);}finally{exchange.close();}
  });server.start();
 }
}
'''


class MetadataFixture(LinkingFixture):
    def __init__(self, source):
        super().__init__(source)
        self.mock = self.prefix + "-mock"

    def boot(self):
        super().boot()
        mock_root = self.work / "mock"
        mock_root.mkdir(mode=0o700)
        (mock_root / "MetadataMock.java").write_text(MOCK_JAVA)
        (mock_root / "mode").write_text("valid")
        self.command(["javac", "--release", "17", str(mock_root / "MetadataMock.java")], "compile-isolated-http-mock")
        self.command(["docker", "run", "-d", "--pull", "never", "--network", self.network,
                      "--name", self.mock, "--user", "root", "-v", str(mock_root) + ":/mock",
                      "--entrypoint", "java", "apache/hop:latest", "-cp", "/mock", "MetadataMock", "/mock"], "start-isolated-http-mock")

    def count(self):
        file = self.work / "mock/count.ndjson"
        return len(file.read_text().splitlines()) if file.exists() else 0

    def mode(self, name):
        (self.work / "mock/mode").write_text(name)

    def execute(self, jobs, ncs, batch, *, mode="valid", execute="Y", reuse="N", reserve="0.005", cost="0.05", timeout="5000", ids="", limit="3"):
        self.mode(mode)
        return self.run("execute_inferred_occupations.hwf", "native-inference-" + batch,
                        extra={"BATCH_ID": batch, "JOB_RUN_ID": jobs, "NCS_RUN_ID": ncs,
                               "POSTING_LIMIT": limit, "POSTING_IDS": ids, "EXECUTE_REQUESTS": execute,
                               "ENDPOINT": "http://" + self.mock + ":18080/chat/completions",
                               "API_KEY_FILE": REMOTE + "/inputs/key.csv" if execute == "Y" else "/never-read/nonexistent-key.csv",
                               "REUSE_CACHE": reuse, "CATEGORIZE_MODEL": "fixture/metadata",
                               "REQUEST_DELAY_MS": "0", "READ_TIMEOUT_MS": timeout,
                               "MAX_REQUESTS": "3", "REQUEST_RESERVE_USD": reserve, "MAX_COST_USD": cost})

    def close(self):
        mock_log = subprocess.run(["docker", "logs", self.mock], text=True, capture_output=True, check=False)
        (self.logs / "isolated-http-mock.log").write_text(mock_log.stdout + mock_log.stderr)
        diagnostic = subprocess.run(["docker", "exec", self.pg, "psql", "-X", "-qAt", "-U", "postgres", "-d", self.database,
                                     "-c", "SELECT jsonb_build_object('batch',batch_id,'state',state,'issues',issues,'http_status',http_status,'cost_usd',cost_usd) FROM enrichment.attempt ORDER BY created_at"],
                                    text=True, capture_output=True, check=False)
        (self.logs / "isolated-attempt-states.log").write_text(diagnostic.stdout + diagnostic.stderr)
        subprocess.run(["docker", "rm", "-fv", self.mock], capture_output=True, check=False)
        mock_root = self.work / "mock"
        if mock_root.exists():
            import shutil

            shutil.rmtree(mock_root)
        super().close()


def check(fixture):
    fixture.install()
    fixture.run("import_local.hpl", "native-inferred-synthetic-source")
    jobs = fixture.sql("SELECT run_id FROM ingestion.latest_ready_run WHERE source_id='jobkorea'", "pin-synthetic-jobs")
    ncs = fixture.seed_ncs()
    fixture.run("install_inferred_occupations.hwf", "native-inferred-installer")
    fixture.run("install_inferred_occupations.hwf", "native-inferred-installer-replay")
    fixture.sql(f"SELECT enrichment.prepare_jobkorea_input_bundle({q(jobs)},'ext-jobkorea-'||enrichment.hash(source_record_id)) FROM ingestion.ready_record WHERE run_id={q(jobs)} AND source_id='jobkorea'", "freeze-synthetic-metadata")
    ids = fixture.sql(f"SELECT string_agg(posting_id,'|' ORDER BY posting_id) FROM enrichment.input_bundle WHERE job_run_id={q(jobs)}", "all-synthetic-postings")
    fixture.expect(bool(ids) and len(ids.split("|")) == 3, "three-frozen-synthetic-listings")
    fixture.execute(jobs, ncs, "dry", execute="N", reuse="Y", ids=ids)
    fixture.expect(fixture.count() == 0, "dry-run-no-key-read-no-http")
    attempt = fixture.sql("SELECT attempt_id FROM enrichment.attempt WHERE batch_id='dry' AND state='PLANNED' ORDER BY attempt_id LIMIT 1", "dry-attempt")
    fixture.run("request_inferred_occupation.hpl", "native-direct-dry-request-no-key", extra={"ATTEMPT_ID": attempt, "API_KEY_FILE": "/never-read/nonexistent-key.csv"})
    fixture.expect(fixture.count() == 0, "direct-dry-attempt-gate-precedes-key-read")
    options = json.loads(fixture.sql("SELECT settings FROM enrichment.batch WHERE batch_id='dry'", "bound-options"))
    wire_reserve = fixture.sql("SELECT (1.05*(0.25*(octet_length(request_body::text)+256)+1.20*768)/1000000 + 1.05*(0.25*(octet_length((request_body-'session_id'-'trace')::text)+256)+1.20*768)/1000000)/2 FROM enrichment.attempt WHERE batch_id='dry' AND state='PLANNED' LIMIT 1", "full-wire-reservation-midpoint")
    options.update(request_reserve_usd=wire_reserve, reuse_cache="N")
    fixture.sql(f"SELECT enrichment.plan_metadata_occupation_batch('full-wire-bound',{q(jobs)},{q(ncs)},{js(options)})", "full-wire-trace-cost-bound")
    fixture.expect(fixture.sql("SELECT count(*) FROM enrichment.attempt WHERE batch_id='full-wire-bound' AND state='REJECTED' AND issues ? 'INPUT_OR_COST_BOUND_EXCEEDED'", "full-wire-bound-rejections") == "2", "reservation-bound-includes-final-session-and-trace-json")
    (fixture.work / "inputs/key.csv").write_text("api_key\nfixture_not_a_real_secret\n")
    fixture.execute(jobs, ncs, "budget", cost="0.001", ids=ids)
    fixture.expect(fixture.count() == 0, "budget-cap-blocks-before-http")
    fixture.expect(fixture.sql("SELECT count(*) FROM enrichment.attempt WHERE batch_id='budget' AND state='BUDGET_BLOCKED'", "budget-first-blocked") == "1", "first-budget-block-stops-later-reservations")
    fixture.expect(fixture.sql("SELECT count(*) FROM enrichment.attempt WHERE batch_id='budget' AND state='PLANNED' AND reserved_at IS NULL", "budget-later-never-sent") == "1", "later-budget-withheld-request-remains-never-sent")
    fixture.execute(jobs, ncs, "valid", reuse="Y", ids=ids)
    fixture.expect(fixture.count() == 1, "same-three-metadata-fields-one-http-attempt")
    fixture.expect(fixture.sql("SELECT count(*) FROM enrichment.metadata_occupation_result r JOIN enrichment.item i USING(item_id) WHERE i.batch_id='valid'", "all-results") == "3", "per-posting-results-including-no-candidate-abstention")
    fixture.expect(fixture.sql("SELECT state FROM enrichment.batch WHERE batch_id='valid'", "batch-complete") == "COMPLETE", "native-batch-complete")
    fixture.expect(fixture.sql("SELECT cost_usd FROM enrichment.attempt WHERE batch_id='valid' AND reserved_at IS NOT NULL", "settled-byok-cost") == "0.00021", "byok-upstream-plus-router-fee-settles-reservation")
    fixture.expect(fixture.sql("SELECT bool_and(extraction_id IS NULL) FROM enrichment.item WHERE batch_id='valid'", "no-duty-extraction") == "t", "inferred-stage-has-no-duty-extraction")
    fixture.expect(fixture.sql("SELECT bool_and(confidence IS NULL AND confidence_state='UNASSESSED') FROM enrichment.metadata_occupation_result", "confidence-unassessed") == "t", "numeric-confidence-never-invented")
    fixture.module("install.hwf", "native-canonical-llm-installer-replay")
    fixture.expect(fixture.sql("SELECT position('metadata_occupation_output_issues' in pg_get_functiondef('enrichment.save_response(text,integer,text,bigint)'::regprocedure))>0 AND enrichment.response_cost('{\"usage\":{\"cost\":0.00001,\"is_byok\":true,\"cost_details\":{\"upstream_inference_cost\":0.0002}}}')=0.00021", "canonical-dispatch-fee-identity") == "t", "canonical-replay-retains-inferred-dispatch-and-fees")
    fixture.execute(jobs, ncs, "cached", reuse="Y", ids=ids)
    fixture.expect(fixture.count() == 1, "validated-metadata-cache-reuse-no-paid-request")
    fixture.execute(jobs, ncs, "exhausted", reuse="Y")
    fixture.expect(fixture.sql("SELECT count(*) FROM enrichment.item WHERE batch_id='exhausted'", "exhausted-count") == "0", "default-selection-skips-completed-metadata")
    fixture.execute(jobs, ncs, "invalid", mode="invalid", ids=ids)
    fixture.expect(fixture.count() == 2, "invalid-citation-stops-further-paid-requests")
    fixture.expect(fixture.sql("SELECT count(*) FROM enrichment.attempt WHERE batch_id='invalid' AND state='REJECTED'", "invalid-citation-states") == "1", "inferred-dispatch-rejects-nonliteral-source-quotes")
    fixture.expect(fixture.sql("SELECT count(*) FROM enrichment.attempt WHERE batch_id='invalid' AND state='PLANNED' AND reserved_at IS NULL", "invalid-later-not-sent") == "1", "invalid-charged-output-preserves-later-never-sent-row")
    fixture.expect(fixture.sql("SELECT count(*) FROM enrichment.metadata_occupation_result r JOIN enrichment.item i USING(item_id) WHERE i.batch_id='invalid' AND r.output->>'outcome'='matched'", "invalid-citation-no-results") == "0", "invalid-quoted-matches-create-no-result")
    fixture.execute(jobs, ncs, "limited", mode="429", ids=ids)
    fixture.expect(fixture.count() == 3, "http429-one-wire-request-no-internal-retry")
    fixture.expect(fixture.sql("SELECT count(*) FROM enrichment.attempt WHERE batch_id='limited' AND reserved_at IS NOT NULL", "limited-reservations") == "1", "provider-error-stops-further-request-reservations")
    fixture.expect(fixture.sql("SELECT enrichment.accounted_cost(state,cost_usd,reserved_usd) FROM enrichment.attempt WHERE batch_id='limited' AND reserved_at IS NOT NULL", "unknown-cost-hold") == "0.005", "unknown-provider-cost-retains-reservation")
    fixture.execute(jobs, ncs, "redirect", mode="302", ids=ids)
    fixture.expect(fixture.count() == 4, "http-redirect-not-followed")
    fixture.execute(jobs, ncs, "timeout", mode="timeout", timeout="1000", ids=ids)
    fixture.expect(fixture.count() == 5, "transport-timeout-one-wire-request")
    fixture.expect(fixture.sql("SELECT count(*) FROM enrichment.attempt WHERE batch_id='timeout' AND http_status=0 AND reserved_at IS NOT NULL", "timeout-hold") == "1", "uncertain-transport-hold-and-stop")
    fixture.expect(json.loads(fixture.sql("""SELECT jsonb_build_array(
     enrichment.response_cost('{"usage":{"cost":0.0002,"is_byok":true,"cost_details":{"upstream_inference_cost":0.003}}}'),
     enrichment.response_cost('{"usage":{"is_byok":true,"cost_details":{"upstream_inference_cost":0.003}}}'),
     enrichment.response_cost('{"usage":{"cost":-0.0002,"is_byok":true,"cost_details":{"upstream_inference_cost":0.003}}}'))""", "fee-regressions")) == [0.0032, None, None], "router-positive-missing-negative-fee-regressions")
    fixture.expect(fixture.sql("SELECT count(*) FROM ingestion.request_attempt", "source-http-count") == "0", "zero-source-request-ledger")
    fixture.receipt["status"] = "PASSED_NATIVE_INFERRED_TRANSPORT"
    fixture.receipt["mock_http_requests"] = fixture.count()


def main():
    os.umask(0o077)
    import tempfile

    with tempfile.TemporaryDirectory(prefix="jobkorea-inferred-fixture-") as temp:
        source = Path(temp) / "synthetic.json"
        rows = [dict(product_page_url="https://www.jobkorea.co.kr/Recruit/GI_Read/90000001", job_title="데이터베이스 개발자"),
                dict(product_page_url="https://www.jobkorea.co.kr/Recruit/GI_Read/90000002", job_title="데이터베이스 개발자"),
                dict(product_page_url="https://www.jobkorea.co.kr/Recruit/GI_Read/90000003", job_title="행사 스태프")]
        source.write_text(json.dumps(rows, ensure_ascii=False))
        fixture = MetadataFixture(source)
        try:
            fixture.boot()
            check(fixture)
        finally:
            fixture.close()
        print("Protected receipt:", fixture.work / "receipt.json", flush=True)


if __name__ == "__main__":
    main()
