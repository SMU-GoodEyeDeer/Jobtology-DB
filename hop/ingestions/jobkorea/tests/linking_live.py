"""Opt-in native OpenRouter pilot in disposable databases; no job-board requests.

The first run processes five real supplied metadata observations. An optional
one-posting synthetic narrative checks extraction/categorization compatibility.
No review is accepted and nothing is published. Private responses remain in the
protected fixture directory for review; the receipt contains counts and costs.
"""
# ruff: noqa: E501

import argparse
import csv
import json
import os
import subprocess
from decimal import Decimal
from pathlib import Path

from linking_native import LinkingFixture, q
from native import REMOTE, ROOT

MODEL = "openai/gpt-5.6-luna"
ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
KEY_CONTAINER = "ibbwv593fijblilse127wnqd-051002227248"
KEY_FILE = "/usr/local/tomcat/webapps/ROOT/config/secrets/openrouter.csv"


def amount(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    parsed = Decimal(str(value))
    return parsed if parsed.is_finite() and parsed >= 0 else None


def costs(row):
    usage = row.get("usage") or {}
    router = amount(usage.get("cost"))
    upstream = amount((usage.get("cost_details") or {}).get("upstream_inference_cost"))
    byok = usage.get("is_byok")
    total = (router + upstream if router is not None and upstream is not None else None) if byok is True else router
    details = usage.get("prompt_tokens_details") or {}
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    cached = details.get("cached_tokens")
    written = details.get("cache_write_tokens")
    estimate = None
    if row.get("actual_model") in (MODEL, MODEL.removeprefix("openai/")) and isinstance(prompt, int) and isinstance(completion, int):
        cached_for_estimate = cached if isinstance(cached, int) and 0 <= cached <= prompt else 0
        written_for_estimate = written if isinstance(written, int) and 0 <= written <= prompt else 0
        if cached_for_estimate + written_for_estimate <= prompt:
            estimate = (Decimal(prompt - cached_for_estimate - written_for_estimate) * Decimal("0.20") + Decimal(cached_for_estimate) * Decimal("0.02") + Decimal(written_for_estimate) * Decimal("0.25") + Decimal(completion) * Decimal("1.20")) / Decimal(1000000)
    return dict(stage=row["stage"], state=row["state"], http_status=row["http_status"],
                actual_model=row.get("actual_model"), provider=row.get("provider"),
                issues=row["issues"], is_byok=byok, prompt_tokens=prompt, completion_tokens_including_reasoning=completion,
                prompt_cached_tokens=cached, prompt_cache_write_tokens=written, reasoning_tokens=(usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
                router_cost_usd=str(router) if router is not None else None,
                upstream_inference_cost_usd=str(upstream) if upstream is not None else None,
                reported_total_usd=str(total) if total is not None else None,
                ledger_cost_usd=row.get("ledger_cost_usd"), accounted_cost_usd=row.get("accounted_cost_usd"),
                router_fee_not_in_legacy_ledger=byok is True and router is not None and router > 0,
                token_price_estimate_usd=str(estimate) if estimate is not None else None,
                estimate_is_actual_charge=False)


class LiveFixture(LinkingFixture):
    def __init__(self, input_file):
        super().__init__(input_file)
        self.egress = self.prefix + "-model-egress"
        self.secret = None
        self.receipt.update(native_model_execution=True,
                            review_decisions_written=False, graph_publication=False,
                            local_accounting_cap_usd="1.00", model=MODEL, endpoint=ENDPOINT)

    def enable_model_access(self, container, filename):
        secret_dir = self.work / "config/secrets"
        secret_dir.mkdir(mode=0o700)
        target = secret_dir / "openrouter.csv"
        self.command(["docker", "cp", container + ":" + filename, str(target)], "private-existing-key-copy")
        target.chmod(0o600)
        if target.is_symlink() or not target.is_file() or target.stat().st_size > 4096:
            raise RuntimeError("Invalid protected key file")
        with target.open(newline="", encoding="utf-8") as file:
            rows = list(csv.DictReader(file))
        if len(rows) != 1 or set(rows[0]) != {"api_key"} or not rows[0]["api_key"].strip():
            raise RuntimeError("Expected one protected api_key row")
        self.secret = rows[0]["api_key"]
        self.command(["docker", "network", "create", self.egress], "create-model-egress")
        self.command(["docker", "network", "connect", self.egress, self.hop], "connect-hop-model-egress")
        self.receipt.pop("network_internal", None)
        self.receipt.update(database_network_internal=True, all_containers_internal_only=False, model_egress_hop_only=True)
        for container_name in (self.pg, self.neo):
            networks = json.loads(self.command(["docker", "inspect", container_name, "--format", "{{json .NetworkSettings.Networks}}"], "verify-isolated-" + container_name.rsplit("-", 1)[1]))
            self.expect(set(networks) == {self.network}, "database-internal-network-only-" + container_name.rsplit("-", 1)[1])

    def capture(self, batch, label):
        rows = json.loads(self.sql(f"""SELECT coalesce(jsonb_agg(jsonb_build_object(
 'item_id',i.item_id,'posting_id',i.posting_id,'source_data',i.source_data,
 'attempt_id',a.attempt_id,'stage',a.stage,'state',a.state,'http_status',a.http_status,'issues',a.issues,
 'actual_model',a.actual_model,'provider',a.provider,'raw_output',a.raw_output,'parsed_output',a.parsed_output,
 'ledger_cost_usd',a.cost_usd::text,'accounted_cost_usd',enrichment.accounted_cost(a.state,a.cost_usd,a.reserved_usd)::text,
 'reserved_at',a.reserved_at,'response_body',a.response_body)
 ORDER BY i.ordinal,a.stage),'[]'::jsonb) FROM enrichment.item i JOIN enrichment.attempt a ON a.item_id=i.item_id
 WHERE i.batch_id={q(batch)}""", "capture-private-" + label))
        for row in rows:
            body = row.pop("response_body", None)
            try:
                envelope = json.loads(body) if body else None
            except (ValueError, TypeError):
                envelope = None
                row["nonjson_response_text"] = body
            row["envelope"] = envelope
            row["usage"] = envelope.get("usage") if isinstance(envelope, dict) else None
        private = self.work / (label + "-responses.private.json")
        private.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
        private.chmod(0o600)
        records = [costs(row) for row in rows]
        charged = [record for row, record in zip(rows, records, strict=True) if row["reserved_at"] is not None]
        totals = [Decimal(record["reported_total_usd"]) for record in charged if record["reported_total_usd"] is not None]
        valid = sum(row["state"] == "VALIDATED" for row in rows)
        complete = len(totals) == len(charged)
        total = sum(totals, Decimal(0))
        listing_count = len({row["posting_id"] for row in rows})
        return dict(batch_id=batch, response_review_file=private.name, request_records=records,
                    distinct_listings=listing_count, charged_or_uncertain_requests=len(charged), validated_outputs=valid,
                    reported_cost_complete=complete, reported_total_usd=str(total) if complete else None,
                    known_reported_subtotal_usd=str(total),
                    min_reported_request_usd=str(min(totals)) if totals else None,
                    max_reported_request_usd=str(max(totals)) if totals else None,
                    mean_reported_request_usd=str(total / len(totals)) if totals else None,
                    cost_per_1000_listings_usd=str(total * 1000 / listing_count) if complete and listing_count else None,
                    cost_per_1000_validated_outputs_usd=str(total * 1000 / valid) if complete and valid else None,
                    scaling_denominator="Separate distinct-listing and validated-output denominators; includes rejected/failed charged attempts",
                    unknown_charge_requests=len(charged) - len(totals))

    def paid(self, params, label, source_run):
        self.receipt["no_paid_calls"] = None
        try:
            self.run("prepare_linking.hwf", "native-paid-" + label, extra=params)
        finally:
            batch = self.sql("SELECT batch_id FROM enrichment.batch WHERE settings->>'execute_requests'='Y' AND job_run_id=" + q(source_run) + " ORDER BY created_at DESC LIMIT 1", "capture-paid-batch-" + label)
            if batch:
                self.receipt[label] = self.capture(batch, label)
                groups = [self.receipt[key] for key in ("real_metadata", "synthetic_narrative_illustration") if key in self.receipt]
                self.receipt["charged_or_uncertain_requests"] = sum(group["charged_or_uncertain_requests"] for group in groups)
                self.receipt["no_paid_calls"] = self.receipt["charged_or_uncertain_requests"] == 0
                return_batch = batch
            else:
                return_batch = None
        return return_batch

    def close(self):
        # Strip a secret if a provider/transport unexpectedly echoed it; never
        # retain or print that value in a report or exception.
        if self.secret:
            for path in list(self.logs.glob("*.log")) + list(self.work.glob("*.private.json")):
                body = path.read_text()
                if self.secret in body:
                    path.write_text(body.replace(self.secret, "[REDACTED_SECRET]"))
                    self.receipt["unexpected_secret_echo_redacted"] = True
        try:
            super().close()
        finally:
            subprocess.run(["docker", "network", "rm", self.egress], capture_output=True, check=False)
            removed = subprocess.run(["docker", "network", "inspect", self.egress], capture_output=True, check=False).returncode != 0
            self.receipt["model_egress_removed"] = removed
            (self.work / "receipt.json").write_text(json.dumps(self.receipt, indent=2) + "\n")
            if not removed:
                raise RuntimeError("Disposable model egress network was not removed")


def check(fixture, args):
    fixture.run("import_local.hpl", "native-real-sample-import-no-source-graph")
    jobs = fixture.sql("SELECT run_id FROM ingestion.latest_ready_run WHERE source_id='jobkorea'", "real-source-pin")
    fixture.expect(fixture.sql(f"SELECT count(*) FROM ingestion.ready_record WHERE run_id={q(jobs)}", "real-source-count") == "887", "real-887-local-observations")
    ncs = fixture.seed_ncs()
    fixture.run("install_linking.hwf", "native-live-linking-installer")
    params = dict(JOB_RUN_ID=jobs, NCS_RUN_ID=ncs, PILOT_LIMIT=5, EXTRACT_MODEL=MODEL, CATEGORIZE_MODEL=MODEL,
                  ENDPOINT=ENDPOINT, PROVIDER_ONLY="openai", MAX_COST_USD=1, DAILY_BUDGET_USD=1,
                  REQUEST_RESERVE_USD=.10, MAX_REQUESTS=5, REUSE_CACHE="N")
    fixture.run("prepare_linking.hwf", "native-dry-before-paid", extra=params | dict(EXECUTE_REQUESTS="N", API_KEY_FILE="/does-not-exist"))
    fixture.expect(fixture.sql("SELECT count(*) FROM enrichment.attempt WHERE reserved_at IS NOT NULL", "dry-no-reservations") == "0", "dry-no-key-or-model-call")
    fixture.enable_model_access(args.key_container, args.key_file)
    batch = fixture.paid(params | dict(EXECUTE_REQUESTS="Y", API_KEY_FILE=REMOTE + "/config/secrets/openrouter.csv"), "real_metadata", jobs)
    if batch is None:
        raise RuntimeError("No paid batch was created")
    fixture.receipt["real_metadata"]["requested_postings"] = 5
    fixture.receipt["real_metadata"]["scope_preview"] = json.loads(fixture.sql(f"SELECT enrichment.jobkorea_linking_preview({q(jobs)},{q(ncs)},5)", "post-paid-scope-preview"))
    fixture.receipt["real_metadata"]["duties_extracted"] = int(fixture.sql(f"SELECT coalesce(sum(jsonb_array_length(coalesce(a.parsed_output->'duties','[]'::jsonb))),0) FROM enrichment.attempt a WHERE batch_id={q(batch)} AND stage='extract'", "real-duty-count"))
    provider_blocked = any(row["http_status"] in (401,402,403,429) for row in fixture.receipt["real_metadata"]["request_records"])
    if args.synthetic_pair and provider_blocked:
        fixture.receipt["synthetic_pair_skipped"] = "Provider/authentication/credit/rate limit error; no automatic retry"
    if args.synthetic_pair and not provider_blocked:
        toy = [dict(product_page_url="https://www.jobkorea.co.kr/Recruit/GI_Read/90000009", job_title="SYNTHETIC 데이터베이스 개발자",
                    company_name="SYNTHETIC FIXTURE EMPLOYER", description_text="담당 업무\n데이터베이스와 테이블을 설계하고 구축한다")]
        file = fixture.work / "inputs/synthetic-live-posting.json"
        file.write_text(json.dumps(toy, ensure_ascii=False))
        fixture.run("import_local.hpl", "native-synthetic-narrative-import", input_name=file.name)
        toy_jobs = fixture.sql("SELECT run_id FROM ingestion.latest_ready_run WHERE source_id='jobkorea'", "synthetic-source-pin")
        fixture.paid(params | dict(JOB_RUN_ID=toy_jobs, PILOT_LIMIT=1, MAX_REQUESTS=2, EXECUTE_REQUESTS="Y", API_KEY_FILE=REMOTE + "/config/secrets/openrouter.csv"), "synthetic_narrative_illustration", toy_jobs)
        fixture.receipt["synthetic_narrative_illustration"]["representative_full_description_benchmark"] = False
    fixture.expect(fixture.sql("SELECT count(*) FROM ingestion.request_attempt", "no-source-http") == "0", "zero-job-board-request-ledger")
    fixture.expect(fixture.sql("SELECT count(*) FROM enrichment.extraction_decision", "no-extraction-acceptance") == "0" and fixture.sql("SELECT count(*) FROM enrichment.link_decision", "no-link-acceptance") == "0", "no-review-acceptance-or-publication")
    fixture.receipt["token_price_estimate_basis"] = dict(model=MODEL, prompt_per_million_usd="0.20", completion_per_million_usd="1.20", cached_prompt_per_million_usd="0.02", cache_write_per_million_usd="0.25", actual_charge=False)
    fixture.receipt["billing_note"] = "BYOK reported totals add numeric router fee and upstream cost; existing ledger records upstream only. Missing billing data remains unknown and reserved. Token-price estimates are separate."
    fixture.receipt["status"] = "COMPLETED_NATIVE_PAID_PILOT_AWAITING_REVIEW"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT.parent / "jobtology/j_muwj57zxdc6o3utkq.json")
    parser.add_argument("--key-container", default=KEY_CONTAINER)
    parser.add_argument("--key-file", default=KEY_FILE)
    parser.add_argument("--execute-paid", action="store_true", help="Explicitly perform the coordinated, user-authorized paid pilot.")
    parser.add_argument("--synthetic-pair", action="store_true", help="Also measure one clearly synthetic extraction/matching pair.")
    args = parser.parse_args()
    if not args.execute_paid:
        parser.error("--execute-paid is required; this command sends paid model requests")
    os.umask(0o077)
    fixture = LiveFixture(args.input)
    try:
        fixture.boot()
        fixture.install()
        check(fixture, args)
    except Exception:
        fixture.receipt["status"] = "FAILED_NATIVE_PAID_PILOT"
        raise
    finally:
        fixture.close()
        print("Protected live-pilot receipt: " + str(fixture.work / "receipt.json"), flush=True)


if __name__ == "__main__":
    main()
