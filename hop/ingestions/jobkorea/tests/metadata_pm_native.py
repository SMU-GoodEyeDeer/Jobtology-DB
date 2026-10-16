# ruff: noqa: E501
"""Focused additive034 native proof: legacy replay plus two v3 mock calls under unchanged immutable v2."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

import metadata_native as native_mock
from linking_native import js, q
from metadata_concurrency import MOCK, ConcurrencyFixture


class JointFixture(ConcurrencyFixture):
    def seed_ncs(self):
        ncs = super().seed_ncs()
        # Synthetic source facts use the production parser's actual array field.
        classes = js(["정보통신", "정보기술", "정보기술개발"])
        self.sql(f"UPDATE ingestion.record SET source_payload=source_payload||jsonb_build_object('classification_names',{classes}),normalized=normalized||jsonb_build_object('classification_names',{classes}) WHERE run_id={q(ncs)}", "seed-source-hierarchy-arrays")
        self.expect(self.sql(f"SELECT count(*) FROM ingestion.validation_issue WHERE run_id={q(ncs)}", "joint-hierarchy-validation") == "0", "joint-synthetic-ncs-hierarchy-valid")
        return ncs

    def execute_joint(self, jobs, ncs, batch, retrieval_revision="metadata-occupation-lexical-v3", execute="Y"):
        self.mode("valid")
        (self.work / "mock/first").write_text(str(self.count() + 1))
        return self.run("execute_inferred_occupation_workers.hwf", "joint-native-" + batch,
                        extra={"BATCH_ID": batch, "JOB_RUN_ID": jobs, "NCS_RUN_ID": ncs,
                               "POSTING_LIMIT": "2", "EXECUTE_REQUESTS": execute,
                               "RETRIEVAL_REVISION": retrieval_revision,
                               "ENDPOINT": "http://" + self.mock + ":18080/chat/completions",
                               "API_KEY_FILE": "/fixture/inputs/key.csv", "REUSE_CACHE": "Y",
                               "CATEGORIZE_MODEL": "fixture/metadata", "REQUEST_DELAY_MS": "0",
                               "READ_TIMEOUT_MS": "5000", "MAX_REQUESTS": "2", "MAX_COST_USD": "0.15",
                               "REQUEST_WORKERS": "4", "PROMPT_VERSION": "ko-metadata-occupation-v2", "POSTING_IDS": self.ids})


def check(f):
    f.install()
    f.module("install.hwf", "joint-canonical-installer")
    f.run("install_inferred_occupations.hwf", "joint-standalone-installer")
    f.run("import_local.hpl", "joint-two-local-metadata")
    jobs = f.sql("SELECT run_id FROM ingestion.latest_ready_run WHERE source_id='jobkorea'", "joint-job-pin")
    ncs = f.seed_ncs()
    f.sql(f"SELECT enrichment.prepare_jobkorea_input_bundle({q(jobs)},'ext-jobkorea-'||enrichment.hash(source_record_id)) FROM ingestion.ready_record WHERE run_id={q(jobs)} AND source_id='jobkorea'", "joint-freeze-two")
    f.ids = f.sql(f"SELECT string_agg(posting_id,'|' ORDER BY posting_id) FROM enrichment.input_bundle WHERE job_run_id={q(jobs)}", "joint-posting-identities")
    f.expect(len(f.ids.split("|")) == 2, "two-distinct-frozen-listings")
    (f.work / "inputs/key.csv").write_text("api_key\nfixture_not_a_real_secret\n")
    f.execute_joint(jobs, ncs, "joint-legacy-dry", retrieval_revision="", execute="N")
    f.expect(f.count() == 0, "legacy-empty-native-revision-has-no-http")
    f.expect(f.sql("SELECT NOT(settings ? 'retrieval_revision') FROM enrichment.batch WHERE batch_id='joint-legacy-dry'", "legacy-native-blank-option-stripped") == "t", "legacy-native-blank-option-preserves-exact-old-settings")
    f.expect(f.sql("SELECT bool_and(NOT(request_body->'trace' ? 'retrieval_revision')) FROM enrichment.attempt WHERE batch_id='joint-legacy-dry'", "legacy-native-no-new-trace-key") == "t", "legacy-native-request-trace-unchanged")
    legacy_hash = f.sql("SELECT enrichment.hash(jsonb_build_object('batch',(SELECT to_jsonb(b) FROM enrichment.batch b WHERE batch_id='joint-legacy-dry'),'attempts',(SELECT jsonb_agg(to_jsonb(a) ORDER BY attempt_id) FROM enrichment.attempt a WHERE batch_id='joint-legacy-dry'),'bindings',(SELECT jsonb_agg(to_jsonb(x) ORDER BY x.item_id) FROM enrichment.metadata_occupation_binding x JOIN enrichment.item i USING(item_id) WHERE i.batch_id='joint-legacy-dry'))::text)", "legacy-native-history-before")
    f.expect(f.sql("SELECT enrichment.plan_metadata_occupation_batch(b.batch_id,b.job_run_id,b.ncs_run_id,b.settings)->>'replay' FROM enrichment.batch b WHERE batch_id='joint-legacy-dry'", "legacy-native-omitted-revision-replay") == "true", "legacy-native-omitted-revision-existing-batch-replay")
    f.expect(f.sql("SELECT enrichment.plan_metadata_occupation_batch(b.batch_id,b.job_run_id,b.ncs_run_id,b.settings||jsonb_build_object('retrieval_revision',''))->>'replay' FROM enrichment.batch b WHERE batch_id='joint-legacy-dry'", "legacy-native-explicit-empty-replay") == "true", "legacy-native-explicit-empty-revision-replay")
    f.execute_joint(jobs, ncs, "joint-two")
    f.expect(f.count() == 2, "joint-two-one-mock-post-per-distinct-metadata")
    f.expect(f.sql("SELECT count(*)=2 AND bool_and(b.settings->>'retrieval_revision'='metadata-occupation-lexical-v3' AND NOT(a.request_body->'trace' ? 'retrieval_revision') AND a.request_body#>>'{trace,release}'='ko-metadata-occupation-v2') FROM enrichment.attempt a JOIN enrichment.batch b USING(batch_id) WHERE b.batch_id='joint-two'", "v3-native-exact-selection-no-wire-expansion") == "t", "v3-native-revision-settings-cache-bound-with-unchanged-wire-trace")
    f.expect(f.sql("SELECT count(*)=2 AND bool_and(old.cache_key<>revised.cache_key) FROM enrichment.attempt old JOIN enrichment.item oi ON oi.item_id=old.item_id JOIN enrichment.item ni ON ni.posting_id=oi.posting_id AND ni.batch_id='joint-two' JOIN enrichment.attempt revised ON revised.item_id=ni.item_id WHERE old.batch_id='joint-legacy-dry'", "v3-native-distinct-cache-identity") == "t", "v3-native-cache-separated-from-identical-legacy-inputs")
    wire_hashes = sorted(hashlib.sha256(path.read_bytes()).hexdigest() for path in (f.work / "mock").glob("request-*.json"))
    ledger_hashes = json.loads(f.sql("SELECT jsonb_agg(enrichment.hash(request_body::text) ORDER BY enrichment.hash(request_body::text)) FROM enrichment.attempt WHERE batch_id='joint-two' AND reserved_at IS NOT NULL", "joint-wire-ledger-hashes"))
    f.expect(len(wire_hashes) == 2 and wire_hashes == ledger_hashes, "v2-exact-native-wire-body-hashes-match-ledger")
    prompt = (Path(__file__).resolve().parents[4] / "hop/llm/prompts/categorize-ko-metadata-occupation-v2.txt").read_text()
    f.expect(f.sql("SELECT count(*)=2 AND bool_and(request_body#>>'{messages,0,content}'=p.system_prompt AND b.settings->>'prompt_version'='ko-metadata-occupation-v2' AND b.settings->>'metadata_scope'='NCS_OCCUPATION_INFERENCE_V1' AND request_body#>'{provider,only}'='[\"openai\"]'::jsonb AND request_body#>>'{provider,allow_fallbacks}'='false') FROM enrichment.attempt a JOIN enrichment.batch b USING(batch_id) CROSS JOIN enrichment.prompt p WHERE a.batch_id='joint-two' AND p.version='ko-metadata-occupation-v2' AND p.stage='categorize'", "joint-v2-exact-prompt-provider") == "t", "v2-installed-system-prompt-scope-and-provider-retained")
    installed_prompt = f.sql("SELECT system_prompt FROM enrichment.prompt WHERE version='ko-metadata-occupation-v2' AND stage='categorize'", "joint-v2-prompt-bytes")
    f.expect(installed_prompt == prompt.strip(), "v2-installed-prompt-equals-immutable-file")
    f.receipt.update(prompt_version="ko-metadata-occupation-v2", system_prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(), wire_request_sha256=wire_hashes)

    stats = json.loads((f.work / "mock/stats.json").read_text())
    f.expect(1 <= stats["maximum"] <= 4, "joint-two-bounded-four-native-workers")
    f.expect(f.sql("SELECT state FROM enrichment.batch WHERE batch_id='joint-two'", "joint-complete-state") == "COMPLETE", "joint-two-complete")
    f.expect(f.sql("SELECT count(*) FROM enrichment.metadata_occupation_request_owner WHERE batch_id='joint-two'", "joint-owner-count") == "2", "joint-two-owned-reservations")
    f.expect(f.sql("SELECT bool_and((request_body#>>'{messages,1,content}')::jsonb#>'{candidates,0,classification_names}'='[\"정보통신\",\"정보기술\",\"정보기술개발\"]'::jsonb) FROM enrichment.attempt WHERE batch_id='joint-two'", "joint-wire-source-hierarchy") == "t", "joint-wire-candidates-have-exact-source-classification-arrays")
    f.expect(f.sql("SELECT count(*) FROM enrichment.metadata_occupation_catalog_context WHERE hierarchy_basis='SOURCE_CLASSIFICATION_NAMES' AND classification_names='[\"정보통신\",\"정보기술\",\"정보기술개발\"]'::jsonb", "joint-bound-hierarchy-context") == "1", "joint-catalog-context-hash-binds-source-hierarchy")
    f.expect(f.sql("SELECT count(*)=2 AND bool_and(confidence IS NULL AND confidence_state='UNASSESSED') FROM enrichment.metadata_occupation_result r JOIN enrichment.item i USING(item_id) WHERE i.batch_id='joint-two'", "joint-confidence-results") == "t", "joint-two-inferred-results-confidence-unassessed")
    f.expect(f.sql("SELECT sum(cost_usd) FROM enrichment.attempt WHERE batch_id='joint-two'", "joint-combined-byok-cost") == "0.00042", "joint-byok-fees-settled-shared-ledger")
    before = f.sql("SELECT enrichment.hash(jsonb_agg(to_jsonb(r) ORDER BY result_id)::text) FROM enrichment.metadata_occupation_result r", "joint-before-replay-results")
    f.module("install.hwf", "joint-canonical-replay-after-results")
    f.run("install_inferred_occupations.hwf", "joint-standalone-replay-after-results")
    f.expect(f.sql("SELECT enrichment.hash(jsonb_agg(to_jsonb(r) ORDER BY result_id)::text) FROM enrichment.metadata_occupation_result r", "joint-after-replay-results") == before, "joint-canonical-standalone-replay-preserve-result-history")
    f.expect(f.sql("SELECT enrichment.hash(jsonb_build_object('batch',(SELECT to_jsonb(b) FROM enrichment.batch b WHERE batch_id='joint-legacy-dry'),'attempts',(SELECT jsonb_agg(to_jsonb(a) ORDER BY attempt_id) FROM enrichment.attempt a WHERE batch_id='joint-legacy-dry'),'bindings',(SELECT jsonb_agg(to_jsonb(x) ORDER BY x.item_id) FROM enrichment.metadata_occupation_binding x JOIN enrichment.item i USING(item_id) WHERE i.batch_id='joint-legacy-dry'))::text)", "legacy-native-history-after-replay") == legacy_hash, "legacy-native-old-settings-requests-bindings-preserved-after-install-replay")
    f.expect(f.sql("SELECT to_regprocedure('enrichment.metadata_occupation_candidates_v3(text,jsonb,integer)') IS NOT NULL AND position('ABSTAINED' IN pg_get_functiondef('enrichment.metadata_occupation_status(text,text)'::regprocedure))>0", "034-effective-native-functions") == "t", "034-canonical-standalone-replay-retains-retrieval-and-status")
    f.expect(f.sql("SELECT enrichment.plan_metadata_occupation_batch(b.batch_id,b.job_run_id,b.ncs_run_id,b.settings)->>'replay' FROM enrichment.batch b WHERE b.batch_id='joint-two'", "joint-v2-existing-batch-options-replay") == "true", "v2-existing-batch-options-replay-immutable")
    f.expect(f.sql("SELECT enrichment.hash(jsonb_agg(to_jsonb(r) ORDER BY result_id)::text) FROM enrichment.metadata_occupation_result r", "joint-after-options-replay-results") == before, "v2-existing-batch-replay-preserves-results")
    f.expect(f.sql("SELECT position('metadata_occupation_output_issues' in pg_get_functiondef('enrichment.save_response(text,integer,text,bigint)'::regprocedure))>0 AND position('metadata_occupation_catalog_context' in pg_get_functiondef('enrichment.metadata_occupation_candidates(text,jsonb,integer)'::regprocedure))>0", "joint-effective-dispatch-context") == "t", "joint-replay-retains-inferred-dispatch-and-hierarchy-context")
    f.execute_joint(jobs, ncs, "joint-cached")
    f.expect(f.count() == 2, "joint-cached-two-no-new-wire-requests")
    f.expect(f.sql("SELECT count(*) FROM enrichment.metadata_occupation_result r JOIN enrichment.item i USING(item_id) WHERE i.batch_id='joint-cached'", "joint-cached-results") == "2", "joint-cached-output-revalidated-per-posting")
    f.expect(f.sql("SELECT count(*) FROM ingestion.request_attempt", "joint-source-http-count") == "0", "joint-zero-source-http-requests")
    f.receipt.update(status="PASSED_NATIVE_METADATA_PM_V3", mock_http_requests=f.count(),
                     distinct_metadata=2, actual_native_workers=4, source_hierarchy_field="classification_names", retrieval_revision="metadata-occupation-lexical-v3", legacy_native_omitted_and_empty_replay=True)


def main():
    os.umask(0o077)
    native_mock.MOCK_JAVA = MOCK.replace('exchange.getRequestBody().readAllBytes();int n=count.incrementAndGet();', 'byte[] request=exchange.getRequestBody().readAllBytes();int n=count.incrementAndGet();Files.write(root.resolve("request-"+n+".json"),request);')
    with tempfile.TemporaryDirectory(prefix="jobkorea-pm-revision-metadata-") as temp:
        source = Path(temp) / "synthetic.json"
        source.write_text(json.dumps([dict(product_page_url="https://www.jobkorea.co.kr/Recruit/GI_Read/" + str(92000001 + i), job_title="데이터베이스 개발자 " + str(i)) for i in range(2)], ensure_ascii=False))
        fixture = JointFixture(source)
        try:
            fixture.boot()
            (fixture.work / "mock/first").write_text("1")
            check(fixture)
        finally:
            fixture.close()
        print("Protected receipt:", fixture.work / "receipt.json", flush=True)


if __name__ == "__main__":
    main()
