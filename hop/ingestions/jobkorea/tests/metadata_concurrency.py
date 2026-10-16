# ruff: noqa: E501
"""Private-network SQL race and native 1/4/8-worker tests; synthetic inputs only."""

import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import metadata_native as native_mock
from linking_native import js, q
from native import REMOTE, ROOT

MOCK = r'''
import com.sun.net.httpserver.HttpServer;
import java.nio.file.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
public class MetadataMock {
 static AtomicInteger active=new AtomicInteger(),maximum=new AtomicInteger(),count=new AtomicInteger();
 static Path root;
 static synchronized void stats() throws java.io.IOException {
  Files.writeString(root.resolve("stats.json"),"{\"requests\":"+count.get()+",\"active\":"+active.get()+",\"maximum\":"+maximum.get()+"}");
 }
 public static void main(String[] args) throws Exception {
  root=Paths.get(args[0]);HttpServer server=HttpServer.create(new InetSocketAddress(18080),0);
  server.setExecutor(Executors.newFixedThreadPool(12));
  server.createContext("/chat/completions",exchange->{
   exchange.getRequestBody().readAllBytes();int n=count.incrementAndGet();int current=active.incrementAndGet();maximum.accumulateAndGet(current,Math::max);
   synchronized(MetadataMock.class){Files.writeString(root.resolve("count.ndjson"),"{}\n",StandardOpenOption.CREATE,StandardOpenOption.APPEND);stats();}
   String mode=Files.readString(root.resolve("mode")).trim();boolean first=Files.readString(root.resolve("first")).trim().equals(Integer.toString(n));
   String output="{\"outcome\":\"matched\",\"matches\":[{\"occupation_code\":\"20010204\",\"reason\":\"제목의 데이터베이스 역할\",\"evidence\":[{\"field\":\"title\",\"quote\":\"데이터베이스\"}]}],\"abstain_reason\":\"\"}";
   if(mode.equals("invalid")&&first)output=output.replace("\"quote\":\"데이터베이스\"","\"quote\":\"위조인용\"");
   String escaped=output.replace("\\","\\\\").replace("\"","\\\"");
   String cost=(mode.equals("unknown")&&first)?"":"\"cost\":0.00001,";
   String body="{\"id\":\"isolated-concurrency-mock\",\"model\":\"fixture/metadata\",\"choices\":[{\"finish_reason\":\"stop\",\"message\":{\"content\":\""+escaped+"\"}}],\"usage\":{\"prompt_tokens\":100,\"completion_tokens\":40,"+cost+"\"is_byok\":true,\"cost_details\":{\"upstream_inference_cost\":0.0002}}}";
   int status=200;
   if(mode.equals("429")&&first){status=429;body="{\"error\":{\"message\":\"isolated rate limit\"}}";}
   try{Thread.sleep((!mode.equals("valid")&&first)?100:1500);}catch(InterruptedException ignored){}
   byte[] response=body.getBytes(StandardCharsets.UTF_8);exchange.getResponseHeaders().set("Content-Type","application/json");
   try{exchange.sendResponseHeaders(status,response.length);exchange.getResponseBody().write(response);}
   finally{exchange.close();active.decrementAndGet();try{stats();}catch(Exception ignored){}}
  });server.start();
 }
}
'''


class ConcurrencyFixture(native_mock.MetadataFixture):
    def install(self):
        files = [ROOT / "docs/hop-migration" / name for name in ("schema.sql", "checks.sql", "operations.sql")]
        files += sorted((ROOT / "hop/llm/sql").glob("*.sql"))
        files += [ROOT / "docs/hop-migration/operations.sql", ROOT / "hop/retention/sql/001_retention.sql", ROOT / "hop/cs/sql/001_common_postings.sql"]
        for index, file in enumerate(files):
            self.sql(file.read_text(), "install-concurrency-" + str(index) + "-" + file.name)
        self.run("install.hwf", "native-concurrency-source-installer")
        self.run("install_inferred_occupation_workers.hwf", "native-worker-installer")
        self.run("install_inferred_occupation_workers.hwf", "native-worker-installer-replay")

    def execute_workers(self, jobs, ncs, batch, workers, *, mode="valid", reuse="N", execute="Y"):
        self.mode(mode)
        (self.work / "mock/first").write_text(str(self.count() + 1))
        return self.run("execute_inferred_occupation_workers.hwf", "native-workers-" + batch,
                        extra={"BATCH_ID": batch, "JOB_RUN_ID": jobs, "NCS_RUN_ID": ncs,
                               "POSTING_LIMIT": "13", "EXECUTE_REQUESTS": execute,
                               "ENDPOINT": "http://" + self.mock + ":18080/chat/completions",
                               "API_KEY_FILE": REMOTE + "/inputs/key.csv" if execute == "Y" else "/never-read/nonexistent-key.csv",
                               "REUSE_CACHE": reuse, "CATEGORIZE_MODEL": "fixture/metadata",
                               "REQUEST_DELAY_MS": "0", "READ_TIMEOUT_MS": "5000",
                               "MAX_REQUESTS": "13", "MAX_COST_USD": "0.15", "REQUEST_WORKERS": str(workers),
                               "POSTING_IDS": self.ids})

    def race(self, calls):
        with ThreadPoolExecutor(max_workers=16) as executor:
            return list(executor.map(lambda row: self.sql(row[1], row[0]), calls))

    def plan(self, jobs, ncs, name, **changes):
        options = dict(categorize_model="fixture/metadata", provider_only="openai", extra_params={"seed": 1},
                       limit=13, posting_ids=self.ids, candidate_limit=12, max_matches=1, max_input_chars=16000,
                       max_output_tokens=768, max_requests=13, request_reserve_usd=0.005, max_cost_usd=0.15,
                       daily_budget_usd=4.75, request_delay_ms=0, read_timeout_ms=5000, execute_requests="Y", reuse_cache="N",
                       endpoint="http://" + self.mock + ":18080/chat/completions") | changes
        self.sql(f"SELECT enrichment.plan_metadata_occupation_batch({q(name)},{q(jobs)},{q(ncs)},{js(options)})", "plan-" + name)
        return self.sql(f"SELECT execution_token FROM jsonb_to_record(enrichment.start_metadata_occupation_execution({q(name)},8)) AS r(execution_token text)", "start-" + name)

    def attempts(self, name):
        return self.sql(f"SELECT string_agg(a.attempt_id,'|' ORDER BY i.ordinal) FROM enrichment.attempt a JOIN enrichment.item i USING(item_id) WHERE a.batch_id={q(name)}", "attempts-" + name).split("|")

    def settle(self, ids):
        output = dict(outcome="matched", matches=[dict(occupation_code="20010204", reason="Synthetic role", evidence=[dict(field="title", quote="데이터베이스")])], abstain_reason="")
        envelope = dict(model="fixture/metadata", choices=[dict(finish_reason="stop", message=dict(content=json.dumps(output, ensure_ascii=False)))],
                        usage=dict(prompt_tokens=100, completion_tokens=40, cost=0.00001, is_byok=True, cost_details=dict(upstream_inference_cost=0.0002)))
        for index, attempt in enumerate(ids):
            self.sql(f"SELECT enrichment.save_response({q(attempt)},200,{q(json.dumps(envelope, ensure_ascii=False))},1)", "settle-" + str(index))

    def reject(self, query, expected):
        try:
            self.sql(query, "reject-" + expected)
        except RuntimeError:
            log = (self.logs / ("reject-" + expected + ".log")).read_text()
            self.expect(expected in log, expected)
        else:
            raise AssertionError(expected)


def check(f):
    f.install()
    f.run("import_local.hpl", "native-concurrent-synthetic-source")
    jobs = f.sql("SELECT run_id FROM ingestion.latest_ready_run WHERE source_id='jobkorea'", "pin-concurrent-jobs")
    ncs = f.seed_ncs()
    f.sql(f"SELECT enrichment.prepare_jobkorea_input_bundle({q(jobs)},'ext-jobkorea-'||enrichment.hash(source_record_id)) FROM ingestion.ready_record WHERE run_id={q(jobs)} AND source_id='jobkorea'", "freeze-concurrent-metadata")
    f.ids = f.sql(f"SELECT string_agg(posting_id,'|' ORDER BY posting_id) FROM enrichment.input_bundle WHERE job_run_id={q(jobs)}", "concurrent-ids")
    f.expect(len(f.ids.split("|")) == 13, "thirteen-frozen-synthetic-listings")
    (f.work / "inputs/key.csv").write_text("api_key\nfixture_not_a_real_secret\n")

    token = f.plan(jobs, ncs, "budget-race", max_cost_usd=0.011)
    ids = f.attempts("budget-race")[:8]
    replies = f.race([(f"budget-race-{i}", f"SELECT enrichment.admit_metadata_occupation_request({q(a)},{q(token)}::uuid)") for i, a in enumerate(ids)])
    f.expect(replies.count("t") == 2, "concurrent-batch-budget-atomically-limits-two-reservations")
    f.expect(f.sql("SELECT sum(enrichment.accounted_cost(state,cost_usd,reserved_usd))<=0.011 AND count(*)=2 FROM enrichment.attempt WHERE batch_id='budget-race' AND reserved_at IS NOT NULL", "race-budget-sum") == "t", "concurrent-reservations-stay-under-cap")
    f.expect(f.sql("SELECT count(*) FROM enrichment.attempt WHERE batch_id='budget-race' AND state='BUDGET_BLOCKED'", "race-budget-blocked") == "1", "first-budget-block-stops-new-admissions")
    f.settle([a for a, reply in zip(ids, replies, strict=True) if reply == "t"])
    f.sql(f"SELECT enrichment.end_metadata_occupation_execution({q(token)}::uuid);SELECT enrichment.finish_metadata_occupation_batch('budget-race')", "finish-budget-race")

    token = f.plan(jobs, ncs, "duplicate-race")
    attempt = f.attempts("duplicate-race")[0]
    replies = f.race([(f"duplicate-race-{i}", f"SELECT enrichment.admit_metadata_occupation_request({q(attempt)},{q(token)}::uuid)") for i in range(8)])
    f.expect(replies.count("t") == 1, "same-attempt-eight-racers-one-admission")
    f.expect(f.sql("SELECT count(*) FROM enrichment.metadata_occupation_request_owner WHERE batch_id='duplicate-race'", "duplicate-owner") == "1", "one-immutable-reservation-owner")
    f.settle([attempt])
    f.sql(f"SELECT enrichment.end_metadata_occupation_execution({q(token)}::uuid);SELECT enrichment.finish_metadata_occupation_batch('duplicate-race')", "finish-duplicate-race")
    f.reject("SELECT enrichment.start_metadata_occupation_execution('duplicate-race',4)", "METADATA_EXECUTION_NOT_RUNNING")

    token = f.plan(jobs, ncs, "capacity-race")
    f.sql(f"SELECT enrichment.stop_metadata_occupation_execution({q(token)}::uuid,'TEST_STOP')", "stop-test-owned-dispatch")
    f.expect(f.sql(f"SELECT enrichment.admit_metadata_occupation_request({q(f.attempts('capacity-race')[0])},{q(token)}::uuid)", "stopped-admission") == "f", "explicit-execution-stop-blocks-new-admissions")
    f.reject(f"UPDATE enrichment.metadata_occupation_execution SET workers=4 WHERE execution_token={q(token)}::uuid", "METADATA_OCCUPATION_EXECUTION_IS_APPEND_ONLY")
    f.reject("SELECT enrichment.start_metadata_occupation_execution('capacity-race',4)", "METADATA_EXECUTION_ALREADY_STARTED")

    token = f.plan(jobs, ncs, "pin-race")
    attempt = f.attempts("pin-race")[0]
    f.sql(f"UPDATE ingestion.run SET state='FAILED' WHERE run_id={q(ncs)}", "temporarily-change-ncs-pin")
    f.expect(f.sql(f"SELECT enrichment.admit_metadata_occupation_request({q(attempt)},{q(token)}::uuid)", "changed-pin-admission") == "f", "per-request-admission-rechecks-exact-ready-pins")
    f.sql(f"UPDATE ingestion.run SET state='READY' WHERE run_id={q(ncs)}", "restore-synthetic-ncs-pin")
    f.expect(f.sql(f"SELECT state FROM enrichment.attempt WHERE attempt_id={q(attempt)}", "changed-pin-never-sent") == "PLANNED", "changed-pin-attempt-remains-never-sent")

    token = f.plan(jobs, ncs, "orphan")
    attempt = f.attempts("orphan")[0]
    f.sql(f"SELECT enrichment.reserve_request({q(attempt)})", "create-synthetic-orphan-hold")
    f.expect(f.sql(f"SELECT enrichment.admit_metadata_occupation_request({q(f.attempts('orphan')[1])},{q(token)}::uuid)", "orphan-admission") == "f", "unowned-reservation-stops-current-dispatch")
    f.reject("SELECT enrichment.start_metadata_occupation_execution('orphan',4)", "METADATA_EXECUTION_ORPHAN_RESERVATION")

    f.execute_workers(jobs, ncs, "dry-four", 4, execute="N")
    f.expect(f.count() == 0, "four-worker-dry-run-no-key-no-http")
    before = f.count()
    f.execute_workers(jobs, ncs, "valid-four", 4, reuse="Y")
    f.expect(f.count() - before == 12, "four-workers-deduplicate-identical-metadata-one-http-per-cache-key")
    f.expect(f.sql("SELECT state FROM enrichment.batch WHERE batch_id='valid-four'", "four-batch-state") == "COMPLETE", "four-workers-complete-all-thirteen-per-posting-results")
    f.expect(f.sql("SELECT count(*) FROM enrichment.metadata_occupation_request_owner WHERE batch_id='valid-four'", "four-owners") == "12", "native-four-worker-every-http-has-one-owner")
    stats = json.loads((f.work / "mock/stats.json").read_text())
    f.expect(stats["maximum"] == 4, "native-four-workers-reach-bounded-concurrency-four")
    before = f.count()
    f.execute_workers(jobs, ncs, "cached-four", 4, reuse="Y")
    f.expect(f.count() == before, "new-worker-batch-reuses-validated-cache-with-no-http")
    f.expect(f.sql("SELECT count(*) FROM enrichment.metadata_occupation_result r JOIN enrichment.item i USING(item_id) WHERE i.batch_id='cached-four'", "cached-four-results") == "13", "cached-outputs-revalidated-for-every-posting")
    before = f.count()
    f.execute_workers(jobs, ncs, "valid-eight", 8)
    f.expect(f.count() - before == 13, "eight-workers-exactly-one-http-per-planned-attempt")
    stats = json.loads((f.work / "mock/stats.json").read_text())
    f.expect(stats["maximum"] == 8, "native-eight-workers-reach-bounded-concurrency-eight")

    for mode, state in (("invalid", "REJECTED"), ("429", "ERROR"), ("unknown", "VALIDATED")):
        before = f.count()
        f.execute_workers(jobs, ncs, "stop-" + mode, 4, mode=mode)
        sent = f.count() - before
        f.expect(1 <= sent <= 4, mode + "-first-failure-at-most-three-existing-inflight-finish")
        f.expect(f.sql(f"SELECT count(*) FROM enrichment.attempt WHERE batch_id={q('stop-'+mode)} AND reserved_at IS NULL AND state='PLANNED'", mode + "-never-sent") == str(13 - sent), mode + "-unsent-attempts-stay-planned")
        f.expect(f.sql(f"SELECT count(*) FROM enrichment.attempt WHERE batch_id={q('stop-'+mode)} AND reserved_at IS NOT NULL AND state={q(state)}", mode + "-failure-state") == (str(sent) if mode == "unknown" else "1"), mode + "-first-failure-retained-without-retry")
        f.expect(f.sql(f"SELECT state FROM enrichment.metadata_occupation_execution_end e JOIN enrichment.metadata_occupation_execution x USING(execution_token) WHERE x.batch_id={q('stop-'+mode)}", mode + "-stop-record") == "STOPPED", mode + "-execution-ended-stopped")
        if mode == "unknown":
            f.expect(f.sql("SELECT enrichment.accounted_cost(state,cost_usd,reserved_usd) FROM enrichment.attempt WHERE batch_id='stop-unknown' AND cost_usd IS NULL AND reserved_at IS NOT NULL", "unknown-held-cost") == "0.005", "validated-unknown-cost-keeps-reservation-and-stops-admission")
    f.expect(f.sql("SELECT count(*) FROM ingestion.request_attempt", "concurrent-source-http-count") == "0", "concurrent-fixture-zero-source-requests")
    f.receipt.update(status="PASSED_NATIVE_METADATA_CONCURRENCY", mock_http_requests=f.count(), worker_limits=[1, 4, 8])


def main():
    os.umask(0o077)
    native_mock.MOCK_JAVA = MOCK
    with tempfile.TemporaryDirectory(prefix="jobkorea-concurrency-fixture-") as temp:
        source = Path(temp) / "synthetic.json"
        rows = [dict(product_page_url="https://www.jobkorea.co.kr/Recruit/GI_Read/" + str(91000001 + i),
                     job_title="데이터베이스 개발자 " + str(i if i != 12 else 0)) for i in range(13)]
        source.write_text(json.dumps(rows, ensure_ascii=False))
        fixture = ConcurrencyFixture(source)
        try:
            fixture.boot()
            (fixture.work / "mock/first").write_text("1")
            check(fixture)
        finally:
            fixture.close()
        print("Protected receipt:", fixture.work / "receipt.json", flush=True)


if __name__ == "__main__":
    main()
