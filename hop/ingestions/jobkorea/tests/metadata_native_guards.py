"""Short network-none PostgreSQL proof for the inferred request price guards."""

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "hop/llm/tests"))
import jobkorea_linking as f  # noqa: E402


def main():
    options = dict(
        categorize_model="openai/gpt-5.6-luna", provider_only="openai", extra_params={},
        limit=1, candidate_limit=12, max_matches=1, max_input_chars=16000,
        max_output_tokens=768, max_requests=1, request_reserve_usd=0.005,
        max_cost_usd=0.05, daily_budget_usd=4.75, request_delay_ms=0,
        read_timeout_ms=1000, execute_requests="N", reuse_cache="N",
        endpoint="https://openrouter.ai/api/v1/chat/completions",
    )

    def rejected(change, issue):
        f.reject(
            "SELECT enrichment.plan_metadata_occupation_batch('price-guard','missing-jobs',"
            + "'missing-ncs'," + f.js(options | change) + ")", issue,
        )

    try:
        f.command([
            "docker", "run", "-d", "--pull", "never", "--network", "none",
            "--name", f.NAME, "-e", "POSTGRES_HOST_AUTH_METHOD=trust",
            os.environ.get("JOBTOLOGY_TEST_POSTGRES_IMAGE", "postgres:18-alpine"),
        ])
        for _ in range(150):
            try:
                if ("PostgreSQL init process complete" in f.command(["docker", "logs", f.NAME])
                        and f.sql("SELECT 1") == "1"):
                    break
            except RuntimeError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("Disposable PostgreSQL did not become ready")
        f.install("docs/hop-migration/schema.sql")
        f.install("docs/hop-migration/checks.sql")
        f.install("hop/llm/sql/001_schema.sql")
        f.sql("CREATE SCHEMA retention; CREATE FUNCTION retention.gate() RETURNS void "
              "LANGUAGE sql AS $$ SELECT NULL::void $$")
        f.install("hop/llm/sql/030_metadata_occupation_native.sql")
        f.install("hop/llm/sql/030_metadata_occupation_native.sql")
        rejected({"categorize_model": "openai/another-model"},
                 "METADATA_OCCUPATION_REQUIRES_PRICED_MODEL_AND_PROVIDER")
        rejected({"provider_only": "openai/fast"},
                 "METADATA_OCCUPATION_REQUIRES_PRICED_MODEL_AND_PROVIDER")
        rejected({}, "LLM_REQUIRES_VALID_READY_SNAPSHOT")
        for cap in (0.001, 4.75, 10, 15, 50):
            rejected({"max_cost_usd": cap, "daily_budget_usd": cap},
                     "LLM_REQUIRES_VALID_READY_SNAPSHOT")
        rejected({"max_cost_usd": 50.000001}, "INVALID_METADATA_OCCUPATION_OPTIONS")
        rejected({"daily_budget_usd": 50.000001}, "INVALID_METADATA_OCCUPATION_OPTIONS")
        rejected({"max_cost_usd": 0}, "INVALID_METADATA_OCCUPATION_OPTIONS")
        token = "123456789abc"
        f.sql("ALTER DATABASE postgres SET jobtology.isolated_fixture='" + token + "'")
        fixture = dict(categorize_model="fixture/metadata",
                       endpoint="http://jobtology-jobkorea-test-" + token
                       + "-mock:18080/chat/completions")
        rejected(fixture, "LLM_REQUIRES_VALID_READY_SNAPSHOT")
        rejected(fixture | {"endpoint": fixture["endpoint"].replace(token, "abcdef123456")},
                 "INVALID_METADATA_OCCUPATION_OPTIONS")
        rejected(fixture | {"categorize_model": "openai/gpt-5.6-luna"},
                 "INVALID_METADATA_OCCUPATION_OPTIONS")
        f.sql("UPDATE enrichment.prompt SET content_hash=repeat('f',64) "
              "WHERE version='ko-metadata-occupation-v1'")
        f.reject((ROOT / "hop/llm/sql/030_metadata_occupation_native.sql").read_text(),
                 "METADATA_PROMPT_VERSION_IS_IMMUTABLE")
        print("Fifteen cap-bound, priced-model/provider, exact fixture endpoint/token "
              "and immutable prompt guards passed")
    finally:
        subprocess.run(["docker", "rm", "-fv", f.NAME], capture_output=True, check=False)


if __name__ == "__main__":
    main()
