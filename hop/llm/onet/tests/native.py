"""Owned native Hop/PG/Neo4j/HTTP-mock proof on an INTERNAL Docker network."""
# Fixture literals mirror native SQL and Java; no production credentials.
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from hop.llm.onet.prompt import PROMPT_HASH, admitted_fields, build_request  # noqa: E402


def module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


resources = module("onet_match_resources", ROOT / "hop/ingestions/jobkorea/tests/native.py")
catalog = module("onet_match_catalog_fixture", ROOT / "hop/ingestions/onet/tests/core_sql.py")
REMOTE = resources.REMOTE
q = catalog.quote


def js(value: object) -> str:
    return q(json.dumps(value, ensure_ascii=False)) + "::jsonb"


MOCK = r"""
import com.sun.net.httpserver.HttpServer;
import java.nio.file.*;import java.net.*;import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;import java.util.concurrent.atomic.*;
public class OnetMock {
 static AtomicInteger active=new AtomicInteger(),maximum=new AtomicInteger(),count=new AtomicInteger();static Path root;
 static synchronized void stats() throws java.io.IOException {Files.writeString(root.resolve("stats.json"),"{\"requests\":"+count.get()+",\"active\":"+active.get()+",\"maximum\":"+maximum.get()+"}");}
 public static void main(String[] args) throws Exception {
  root=Paths.get(args[0]);HttpServer server=HttpServer.create(new InetSocketAddress(18080),0);server.setExecutor(Executors.newFixedThreadPool(20));
  server.createContext("/chat/completions",exchange->{
   exchange.getRequestBody().readAllBytes();int n=count.incrementAndGet();int now=active.incrementAndGet();maximum.accumulateAndGet(now,Math::max);
   synchronized(OnetMock.class){Files.writeString(root.resolve("requests.ndjson"),"{}\n",StandardOpenOption.CREATE,StandardOpenOption.APPEND);stats();}
   String mode=Files.readString(root.resolve("mode")).trim();boolean first=Files.readString(root.resolve("first")).trim().equals(Integer.toString(n));
   String output=Files.readString(root.resolve("output.json"));
   String escaped=output.replace("\\","\\\\").replace("\"","\\\"").replace("\n","\\n");
   String cost=mode.equals("unknown")&&first?"":"\"cost\":0.00001,";
   String body="{\"id\":\"isolated-onet-mock\",\"model\":\"openai/gpt-5.6-luna\",\"provider\":\"OpenAI\",\"choices\":[{\"finish_reason\":\"stop\",\"message\":{\"content\":\""+escaped+"\"}}],\"usage\":{\"prompt_tokens\":100,\"completion_tokens\":40,"+cost+"\"is_byok\":true,\"cost_details\":{\"upstream_inference_cost\":0.0002}}}";
   try{Thread.sleep(mode.equals("unknown")&&first?50:750);}catch(InterruptedException ignored){}
   byte[] bytes=body.getBytes(StandardCharsets.UTF_8);exchange.getResponseHeaders().set("Content-Type","application/json");
   try{exchange.sendResponseHeaders(200,bytes.length);exchange.getResponseBody().write(bytes);}finally{exchange.close();active.decrementAndGet();try{stats();}catch(Exception ignored){}}
  });server.start();
 }
}
"""


class Fixture(resources.Fixture):
    def __init__(self, input_file: Path):
        super().__init__(input_file)
        self.prefix = "jobtology-onet-test-" + self.token
        self.network, self.pg, self.neo, self.hop, self.mock = (
            self.prefix + suffix for suffix in ("-net", "-pg", "-neo", "-hop", "-mock")
        )
        self.receipt.update(
            kind="ISOLATED_ONET_MATCHING_NATIVE",
            artifact_sha256={
                str(path.relative_to(ROOT / "hop")): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted((ROOT / "hop/llm/onet").rglob("*"))
                if path.suffix in (".sql", ".hpl", ".hwf")
            },
        )

    def stage(self):
        super().stage()
        project = self.work / "project"
        for folder in ("llm/onet", "ingestions/onet"):
            shutil.copytree(
                ROOT / "hop" / folder,
                project / folder,
                ignore=shutil.ignore_patterns("tools", "tests", "__pycache__", "*.pyc"),
            )
        for kind in ("pipeline", "workflow"):
            shutil.copyfile(
                ROOT / f"hop/metadata/{kind}-run-configuration/onet-local.json",
                project / f"metadata/{kind}-run-configuration/onet-local.json",
            )

    def boot(self):
        super().boot()
        mock = self.work / "mock"
        mock.mkdir(mode=0o700)
        (mock / "OnetMock.java").write_text(MOCK)
        (mock / "mode").write_text("valid")
        (mock / "first").write_text("1")
        self.command(
            ["javac", "--release", "17", str(mock / "OnetMock.java")], "compile-internal-mock"
        )
        self.command(
            [
                "docker",
                "run",
                "-d",
                "--pull",
                "never",
                "--network",
                self.network,
                "--name",
                self.mock,
                "--user",
                "root",
                "-v",
                str(mock) + ":/mock",
                "--entrypoint",
                "java",
                "apache/hop:latest",
                "-cp",
                "/mock",
                "OnetMock",
                "/mock",
            ],
            "start-internal-mock",
        )

    def native(self, filename: str, label: str, params: dict | None = None, success=True):
        self.command(
            [
                "docker",
                "exec",
                "-e",
                "HOP_CONFIG_FOLDER=" + REMOTE + "/config",
                "-e",
                "HOP_OPTIONS=-Xmx1024m",
                "-e",
                "ONET_MATCHING_ISOLATED_TOKEN=" + self.token,
                "-w",
                "/opt/hop",
                self.hop,
                "bash",
                "hop-run.sh",
                "-j",
                "jobkorea-test",
                "-r",
                "onet-local",
                "-f",
                REMOTE + "/project/" + filename,
                "-p",
                ",".join(key + "=" + str(value) for key, value in (params or {}).items()),
                "-l",
                "Basic",
            ],
            label,
            success=success,
            timeout=300,
        )
        self.expect(True, label)

    def cypher(self, statement: str, label="graph") -> str:
        return self.command(
            ["docker", "exec", "-i", self.neo, "cypher-shell", "--format", "plain"],
            label,
            statement + ";\n",
        )

    def count(self):
        file = self.work / "mock/requests.ndjson"
        return len(file.read_text().splitlines()) if file.exists() else 0

    def close(self):
        logs = subprocess.run(
            ["docker", "logs", self.mock], text=True, capture_output=True, check=False
        )
        (self.logs / "internal-mock.log").write_text(logs.stdout + logs.stderr)
        subprocess.run(["docker", "rm", "-fv", self.mock], capture_output=True, check=False)
        shutil.rmtree(self.work / "mock", ignore_errors=True)
        super().close()
        if (
            subprocess.run(
                ["docker", "inspect", self.mock], capture_output=True, check=False
            ).returncode
            == 0
        ):
            raise RuntimeError("Owned mock cleanup incomplete")


def check(f: Fixture):
    f.sql(
        "CREATE SCHEMA retention; CREATE TABLE retention.plan(plan_id text PRIMARY KEY,state text NOT NULL,owner_id text); CREATE TABLE retention.writer(writer_id text PRIMARY KEY,kind text NOT NULL,target_id text NOT NULL,started_at timestamptz NOT NULL DEFAULT clock_timestamp())",
        "retention-minimal-schema",
    )
    canonical = (ROOT / "hop/retention/sql/001_retention.sql").read_text()
    for name in ("gate", "freeze_writes", "enter_writer", "leave_writer"):
        body = re.search(
            rf"CREATE OR REPLACE FUNCTION retention\.{name}\(.*?\$\$;", canonical, re.DOTALL
        )
        assert body
        f.sql(body.group(), "retention-" + name)
    for path in sorted((ROOT / "hop/ingestions/onet/sql").glob("*.sql")):
        f.sql(path.read_text(), "catalog-install-" + path.stem)
    payload = catalog.small_payload()
    release = payload["release_id"]
    f.sql("SELECT classification.import_onet_catalog(" + js(payload) + ")", "seed-local-reference")
    f.native(
        "ingestions/onet/replay_catalog.hwf",
        "native-catalogue-graph",
        {"RELEASE_ID": release, "NEO4J_CONNECTION": "jobtology-neo4j"},
    )
    database = f.sql("SELECT database_id FROM classification.catalog_current", "graph-database-pin")
    f.sql(
        "CREATE SCHEMA ingestion; CREATE TABLE ingestion.source_graph_projection(run_id text PRIMARY KEY,source_id text,state text,loader_version text,content_sha256 text,verified_at timestamptz); CREATE TABLE ingestion.source_graph_membership(run_id text,record_id text,identity_id text,kind text); CREATE TABLE ingestion.source_graph_record_evidence(run_id text,record_id text,source_record_id text); INSERT INTO ingestion.source_graph_projection VALUES('fixture-source','jobkorea','READY','hop-graph-batchfree-v1',repeat('a',64),clock_timestamp()); CREATE TABLE ingestion.legacy_sentinel(id integer PRIMARY KEY,value jsonb); INSERT INTO ingestion.legacy_sentinel VALUES(1,'{\"typed\":[1,null,true,\"한글\"]}'); CREATE FUNCTION ingestion.legacy_function() RETURNS integer LANGUAGE sql IMMUTABLE AS 'SELECT 17'",
        "source-and-legacy-stubs",
    )
    before_pg = f.sql(
        "SELECT row_to_json(x) FROM(SELECT (SELECT jsonb_agg(x) FROM ingestion.legacy_sentinel x) AS rows,(SELECT to_jsonb(p) FROM pg_proc p WHERE oid='ingestion.legacy_function()'::regprocedure) AS function) x",
        "legacy-pg-before",
    )
    f.native("llm/onet/install.hwf", "native-matcher-install")
    f.native("llm/onet/install.hwf", "native-matcher-install-replay")
    term = next(value for value in payload["terms"] if value["term_kind"] == "OCCUPATION")
    candidate = {
        "occupation_code": term["code"],
        "term_id": term["term_id"],
        "label": term["preferred_label"],
        "description": term["description"],
    }
    output = {
        "outcome": "matched",
        "matches": [
            {
                "occupation_code": term["code"],
                "match_rank": 1,
                "reason": "Synthetic chief-executive vacancy.",
                "evidence": [{"field": "title", "quote": "최고경영자"}],
            }
        ],
        "abstain_reason": "",
    }
    (f.work / "mock/output.json").write_text(json.dumps(output, ensure_ascii=False))
    (f.work / "inputs/key.csv").write_text("api_key\nfixture_never_a_real_secret\n")
    manifest = []
    source_nodes = []
    for index in range(29):
        identity = "jobkorea:posting:" + str(index).zfill(3)
        facts = {"title": "최고경영자 " + str(index)}
        digest = f.sql(
            "SELECT encode(sha256(convert_to(" + js(facts) + "::text,'UTF8')),'hex')",
            "source-facts-hash-" + str(index),
        )
        fields = admitted_fields(facts)
        manifest.append(
            {
                "posting_identity": identity,
                "source_id": "jobkorea",
                "source_run_id": "fixture-source",
                "source_record_id": str(index),
                "source_facts": facts,
                "source_facts_sha256": digest,
                "source_fields": fields,
                "candidates": [candidate],
                "request_body": build_request(fields, [candidate]),
            }
        )
        f.sql(
            "INSERT INTO ingestion.source_graph_membership VALUES('fixture-source',"
            + q(str(index))
            + ","
            + q(identity)
            + ",'JobPosting'); INSERT INTO ingestion.source_graph_record_evidence VALUES('fixture-source',"
            + q(str(index))
            + ","
            + q(str(index))
            + ")",
            "source-proof-" + str(index),
        )
        source_nodes.append(
            "CREATE (:entity:jobPosting {id:"
            + json.dumps(identity)
            + ",kind:'JobPosting',source_facts_sha256:"
            + json.dumps(digest)
            + ",value:17})",
        )
    f.cypher(";\n".join(source_nodes), "seed-all-source-endpoints")
    source_before = f.cypher(
        "MATCH(n) WITH n ORDER BY elementId(n) RETURN collect([elementId(n),labels(n),properties(n)])",
        "all-nodes-before",
    )
    settings = {
        "max_cost_usd": 1,
        "request_reserve_usd": 0.01,
        "max_output_tokens": 1024,
        "max_matches": 3,
        "endpoint": "http://" + f.mock + ":18080/chat/completions",
        "model": "openai/gpt-5.6-luna",
        "prompt_hash": PROMPT_HASH,
        "retrieval_hash": "b" * 64,
        "read_timeout_ms": 5000,
        "request_delay_ms": 0,
        "execute_requests": "Y",
        "frozen_input_count": len(manifest),
    }
    f.sql(
        "SELECT onet_matching.create_task('native-task',"
        + q(release)
        + ","
        + q(database)
        + ","
        + js(settings)
        + "); SELECT onet_matching.freeze_inputs('native-task',"
        + js(manifest)
        + "); SELECT onet_matching.finalize_freeze('native-task',29)",
        "freeze-exact-native-inputs",
    )
    ids = [row["posting_identity"] for row in manifest]
    f.sql(
        "SELECT onet_matching.plan_batch('native-task','pilot',"
        + js(ids[:13])
        + ",'PILOT',13,0.25)",
        "plan-native-pilot",
    )
    f.native(
        "llm/onet/execute_matches.hwf",
        "native-four-worker-pilot",
        {
            "ONET_BATCH_ID": "pilot",
            "REQUEST_WORKERS": "4",
            "API_KEY_FILE": REMOTE + "/inputs/key.csv",
        },
    )
    f.expect(f.count() == 13, "thirteen-single-posts-no-retry")
    stats = json.loads((f.work / "mock/stats.json").read_text())
    f.expect(2 <= stats["maximum"] <= 4, "actual-bounded-concurrency")
    f.expect(
        f.sql(
            "SELECT count(*) FROM onet_matching.attempt WHERE batch_id='pilot' AND state='VALIDATED' AND cost_usd=0.00021",
            "native-combined-ledger",
        )
        == "13",
        "native-byok-upstream-plus-router",
    )
    f.sql(
        "SELECT onet_matching.approve_scale('native-task','assistant','Individually inspected synthetic pilot and measured accounting')",
        "measured-pilot-scale-gate",
    )
    rejected = f.sql(
        "SELECT attempt_id FROM onet_matching.attempt WHERE batch_id='pilot' ORDER BY ordinal LIMIT 1",
        "individual-reject-attempt",
    )
    accepted = f.sql(
        "SELECT attempt_id FROM onet_matching.attempt WHERE batch_id='pilot' ORDER BY ordinal OFFSET 1 LIMIT 1",
        "individual-accept-attempt",
    )
    f.sql(
        "SELECT onet_matching.decide_candidate("
        + q(rejected)
        + ","
        + q(term["code"])
        + ",'REJECT','assistant','assistant','Synthetic negative decision'); SELECT onet_matching.decide_candidate("
        + q(accepted)
        + ","
        + q(term["code"])
        + ",'ACCEPT','assistant','assistant','Individual synthetic review')",
        "individual-only-review-decisions",
    )
    collision = json.loads(
        f.sql(
            "SELECT to_jsonb(g) FROM onet_matching.graph_rows('native-task') g ORDER BY edge_id LIMIT 1",
            "collision-plan-row",
        )
    )
    f.cypher(
        "MATCH (p:entity {id:"
        + json.dumps(ids[-1])
        + "}) MATCH(o:entity {id:"
        + json.dumps(term["term_id"])
        + "}) CREATE(p)-[:INFERRED_ONET_OCCUPATION {id:"
        + json.dumps(collision["edge_id"])
        + ",managed_by:'jobtology-onet-matching-v1',occupation_code:"
        + json.dumps(term["code"])
        + ",release_id:"
        + json.dumps(release)
        + ",task_id:'foreign-owner-lookalike'}]->(o)",
        "seed-adversarial-owned-id-wrong-endpoints",
    )
    f.native(
        "llm/onet/publish_matches.hwf",
        "native-reject-wrong-endpoint-collision",
        {"ONET_TASK_ID": "native-task", "NEO4J_CONNECTION": "jobtology-neo4j"},
        success=False,
    )
    f.expect(
        f.cypher(
            "MATCH ()-[r:INFERRED_ONET_OCCUPATION]->() RETURN count(r)",
            "collision-before-write-count",
        ).splitlines()[-1]
        == "1",
        "wrong-endpoint-collision-rejected-before-any-write",
    )
    f.expect(
        f.sql("SELECT count(*) FROM retention.writer", "collision-writer-cleanup") == "0",
        "failed-native-publication-releases-only-own-writer",
    )
    f.cypher(
        "MATCH ()-[r:INFERRED_ONET_OCCUPATION {task_id:'foreign-owner-lookalike'}]->() DELETE r",
        "remove-owned-fixture-collision",
    )
    f.cypher(
        "MATCH(p:entity {id:"
        + json.dumps(collision["posting_identity"])
        + "}) SET p.source_facts_sha256='stale-fixture-hash'",
        "seed-adversarial-stale-endpoint",
    )
    f.native(
        "llm/onet/publish_matches.hwf",
        "native-reject-stale-source-endpoint",
        {"ONET_TASK_ID": "native-task", "NEO4J_CONNECTION": "jobtology-neo4j"},
        success=False,
    )
    f.expect(
        f.cypher(
            "MATCH ()-[r:INFERRED_ONET_OCCUPATION]->() RETURN count(r)", "stale-before-write-count"
        ).splitlines()[-1]
        == "0",
        "stale-source-rejected-before-any-write",
    )
    f.expect(
        f.sql("SELECT count(*) FROM retention.writer", "stale-writer-cleanup") == "0",
        "stale-failure-writer-released",
    )
    f.cypher(
        "MATCH(p:entity {id:"
        + json.dumps(collision["posting_identity"])
        + "}) SET p.source_facts_sha256="
        + json.dumps(collision["properties"]["source_facts_sha256"]),
        "restore-only-fixture-source-endpoint",
    )
    f.native(
        "llm/onet/publish_matches.hwf",
        "native-flat-publication",
        {"ONET_TASK_ID": "native-task", "NEO4J_CONNECTION": "jobtology-neo4j"},
    )
    f.expect(
        "12"
        in f.cypher(
            "MATCH ()-[r:INFERRED_ONET_OCCUPATION]->() RETURN count(r)", "first-edge-count"
        ),
        "rejected-match-excluded",
    )
    edge_before = f.cypher(
        "MATCH ()-[r:INFERRED_ONET_OCCUPATION]->() WITH r ORDER BY r.id RETURN collect([elementId(r),properties(r)])",
        "first-exact-edge-snapshot",
    )
    f.native(
        "llm/onet/publish_matches.hwf",
        "native-flat-exact-replay",
        {"ONET_TASK_ID": "native-task", "NEO4J_CONNECTION": "jobtology-neo4j"},
    )
    f.expect(
        edge_before
        == f.cypher(
            "MATCH ()-[r:INFERRED_ONET_OCCUPATION]->() WITH r ORDER BY r.id RETURN collect([elementId(r),properties(r)])",
            "replayed-exact-edge-snapshot",
        ),
        "relationship-ids-and-properties-exact-replay",
    )
    f.expect(
        source_before
        == f.cypher(
            "MATCH(n) WITH n ORDER BY elementId(n) RETURN collect([elementId(n),labels(n),properties(n)])",
            "all-nodes-after",
        ),
        "no-node-writes-or-scaffolding",
    )
    f.expect(
        "true"
        in f.cypher(
            "MATCH ()-[r:INFERRED_ONET_OCCUPATION]->() RETURN all(x IN collect(r) WHERE x.confidence IS NULL AND x.confidence_state='UNASSESSED' AND x.stage='STAGING' AND x.basis='METADATA_INFERRED')",
            "inference-semantics",
        ).lower(),
        "null-unassessed-staging-inferred-only",
    )
    f.expect(
        f.cypher(
            "MATCH ()-[r:INFERRED_ONET_OCCUPATION]->() RETURN count(CASE WHEN r.review_status='UNREVIEWED' THEN r END),count(CASE WHEN r.review_status='ASSISTANT_REVIEWED' THEN r END)",
            "individual-review-counts",
        ).splitlines()[-1]
        == "11, 1",
        "bulk-unreviewed-individual-only-reviewed",
    )
    f.expect(
        before_pg
        == f.sql(
            "SELECT row_to_json(x) FROM(SELECT (SELECT jsonb_agg(x) FROM ingestion.legacy_sentinel x) AS rows,(SELECT to_jsonb(p) FROM pg_proc p WHERE oid='ingestion.legacy_function()'::regprocedure) AS function) x",
            "legacy-pg-after",
        ),
        "legacy-table-and-function-metadata-preserved",
    )
    f.sql(
        "SELECT onet_matching.plan_batch('native-task','resume',"
        + js(ids[26:29])
        + ",'FULL',3,0.1)",
        "plan-never-sent-resume-fixture",
    )
    old_token = json.loads(
        f.sql(
            "SELECT onet_matching.start_execution('resume',4)",
            "own-then-interrupt-unsent-execution",
        )
    )["execution_token"]
    f.sql(
        "SELECT onet_matching.stop_execution("
        + q(old_token)
        + "::uuid,'FIXTURE_OWNED_PROCESS_ABSENT_BEFORE_FIRST_REQUEST')",
        "stop-unsent-owned-dispatcher",
    )
    before_resume = f.count()
    f.native(
        "llm/onet/execute_matches.hwf",
        "native-resume-never-sent-only",
        {
            "ONET_BATCH_ID": "resume",
            "ONET_RESUME": "Y",
            "REQUEST_WORKERS": "4",
            "API_KEY_FILE": REMOTE + "/inputs/key.csv",
        },
    )
    f.expect(
        f.count() == before_resume + 3
        and f.sql(
            "SELECT count(*) FROM onet_matching.execution WHERE batch_id='resume'",
            "append-only-resume-token-count",
        )
        == "2",
        "resume-uses-new-token-and-only-never-sent-inputs",
    )
    f.sql(
        "SELECT onet_matching.plan_batch('native-task','unknown',"
        + js(ids[13:26])
        + ",'FULL',13,0.25)",
        "plan-unknown-charge-fixture",
    )
    (f.work / "mock/mode").write_text("unknown")
    (f.work / "mock/first").write_text(str(f.count() + 1))
    before_count = f.count()
    f.native(
        "llm/onet/execute_matches.hwf",
        "native-unknown-charge-stop",
        {
            "ONET_BATCH_ID": "unknown",
            "REQUEST_WORKERS": "4",
            "API_KEY_FILE": REMOTE + "/inputs/key.csv",
        },
    )
    f.expect(
        1 <= f.count() - before_count <= 4, "unknown-charge-only-already-admitted-workers-settle"
    )
    f.expect(
        f.sql(
            "SELECT count(*) FROM onet_matching.attempt WHERE batch_id='unknown' AND reserved_at IS NOT NULL AND cost_usd IS NULL",
            "unknown-ledger-count",
        )
        == "1",
        "native-unknown-charge-hold",
    )
    f.native(
        "llm/onet/execute_matches.hwf",
        "native-unknown-no-resume",
        {
            "ONET_BATCH_ID": "unknown",
            "ONET_RESUME": "Y",
            "REQUEST_WORKERS": "4",
            "API_KEY_FILE": REMOTE + "/inputs/key.csv",
        },
        success=False,
    )
    f.expect(f.count() - before_count <= 4, "unknown-paid-attempt-never-retried")
    f.expect(
        f.sql("SELECT count(*) FROM retention.writer", "all-writers-absent") == "0",
        "writers-settled",
    )


def main():
    with tempfile.TemporaryDirectory(prefix="onet-match-synthetic-") as scratch:
        source = Path(scratch) / "source.json"
        source.write_text("[]\n")
        f = Fixture(source)
        try:
            f.boot()
            check(f)
            f.receipt["status"] = "PASSED_ONET_MATCHING_NATIVE"
        except Exception as failure:
            f.receipt.update(status="FAILED", error=type(failure).__name__ + ": " + str(failure))
            raise
        finally:
            f.close()
            print(str(f.work / "receipt.json"), flush=True)


if __name__ == "__main__":
    main()
