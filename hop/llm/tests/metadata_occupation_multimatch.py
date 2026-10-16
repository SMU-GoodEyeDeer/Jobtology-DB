"""Network-none native PostgreSQL proof for opt-in multi-role inference and review."""

# SQL fixtures preserve exact literal source evidence and archived identities.
# ruff: noqa: E501
from __future__ import annotations

import copy
import hashlib
import json
import os
import uuid
import xml.etree.ElementTree as E
from datetime import UTC, datetime
from pathlib import Path

import metadata_occupation_context as context

f = context.f
ROOT = Path(__file__).resolve().parents[3]
VERSION = "ko-metadata-occupation-v3"
TITLE = "웹 개발자 및 데이터베이스 관리자 및 보안사고 분석가"
CODES = ["20010202", "20010204", "20010603"]
QUOTES = ["웹 개발자", "데이터베이스 관리자", "보안사고 분석가"]
FOCUSED_INSTALLER = ROOT / "hop/ingestions/jobkorea/install_batchfree_graph_publication.hwf"


def focused_installer_replay() -> None:
    """Execute the actual focused workflow's SQL actions with its graph prerequisite."""
    root = E.parse(FOCUSED_INSTALLER).getroot()
    workflows = root.findall("actions/action[type='WORKFLOW']")
    assert len(workflows) == 1
    assert workflows[0].findtext("filename") == "${PROJECT_HOME}/graph/install.hwf"
    graph = E.parse(ROOT / "hop/graph/install.hwf").getroot()
    filenames = [node.findtext("sqlfilename") for node in graph.findall("actions/action[type='SQL']")]
    focused_files = [node.findtext("sqlfilename") for node in root.findall("actions/action[type='SQL']")]
    assert [Path(str(filename)).name for filename in focused_files] == [
        "002_batchfree_retention.sql", "036_batchfree_graph_publication.sql", "037_metadata_occupation_multimatch.sql"
    ]
    for filename in [*filenames, *focused_files]:
        assert filename is not None and filename.startswith("${PROJECT_HOME}/")
        relative = filename.removeprefix("${PROJECT_HOME}/")
        f.sql((ROOT / "hop" / relative).read_text())


def fresh_retention_install_checks() -> None:
    """Canonical bootstrap may precede retention; review must fail closed until replay."""
    database = "multimatch_fresh_retention"
    f.sql("CREATE DATABASE " + database)

    def sql(statement: str) -> str:
        return f.command(
            [
                "docker", "exec", "-i", f.NAME, "psql", "-X", "-qAt", "-v",
                "ON_ERROR_STOP=1", "-U", "postgres", "-d", database,
            ],
            statement,
        )

    def denied_review() -> None:
        try:
            sql(
                "INSERT INTO enrichment.metadata_occupation_candidate_decision"
                "(candidate_id,decision,reviewer,reviewer_kind,notes) VALUES"
                "('missing-candidate','ACCEPT','independent-reviewer','human','SYNTHETIC retention gate')"
            )
        except RuntimeError as exc:
            assert "METADATA_OCCUPATION_REINSTALL_FOR_RETENTION_GUARD_REQUIRED" in str(exc), str(exc)
        else:
            raise AssertionError("Review before a valid retention guard was accepted")

    migration = ROOT / "hop/llm/sql/037_metadata_occupation_multimatch.sql"
    try:
        for relative in (
            "docs/hop-migration/schema.sql",
            "docs/hop-migration/checks.sql",
            "docs/hop-migration/operations.sql",
        ):
            sql((ROOT / relative).read_text())
        for path in sorted((ROOT / "hop/llm/sql").glob("*.sql")):
            sql(path.read_text())
        assert sql("SELECT to_regprocedure('retention.freeze_writes()') IS NULL") == "t"
        denied_review()
        sql((ROOT / "hop/retention/sql/001_retention.sql").read_text())
        denied_review()  # Retention installation alone cannot quietly unlock the new table.
        sql(migration.read_text())
        assert sql(
            "SELECT count(*)=1 FROM pg_trigger WHERE "
            "tgrelid='enrichment.metadata_occupation_candidate_decision'::regclass "
            "AND tgname='retention_freeze' AND tgenabled='O' "
            "AND tgfoid=to_regprocedure('retention.freeze_writes()')"
        ) == "t"
        assert sql(
            "SELECT count(*)=1 FROM pg_trigger WHERE "
            "tgrelid='enrichment.metadata_occupation_candidate_decision'::regclass "
            "AND tgname='metadata_candidate_review_guard' AND tgenabled='O' "
            "AND tgfoid=to_regprocedure('enrichment.guard_metadata_occupation_candidate_decision()')"
        ) == "t"
        sql("DROP TRIGGER retention_freeze ON enrichment.metadata_occupation_candidate_decision")
        denied_review()
        sql(
            "CREATE FUNCTION retention.synthetic_wrong_guard() RETURNS trigger LANGUAGE plpgsql "
            "AS $$ BEGIN RETURN NULL; END $$; "
            "CREATE TRIGGER retention_freeze BEFORE INSERT ON "
            "enrichment.metadata_occupation_candidate_decision FOR EACH STATEMENT "
            "EXECUTE FUNCTION retention.synthetic_wrong_guard()"
        )
        denied_review()  # A trigger name alone cannot stand in for the actual freeze function.
        sql(migration.read_text())
        assert sql(
            "SELECT count(*)=1 FROM pg_trigger WHERE "
            "tgrelid='enrichment.metadata_occupation_candidate_decision'::regclass "
            "AND tgname='retention_freeze' AND tgenabled='O' "
            "AND tgfoid=to_regprocedure('retention.freeze_writes()')"
        ) == "t"
    finally:
        f.sql("DROP DATABASE " + database)
    print("Fresh canonical installation before retention, denied review and exact guard replay PASSED", flush=True)


def output(count: int = 2) -> dict:
    return dict(
        outcome="matched",
        abstain_reason="",
        matches=[
            dict(
                occupation_code=code,
                match_rank=rank,
                role_anchor=dict(field="title", quote=quote),
                reason="SYNTHETIC explicitly advertised role",
                evidence=[dict(field="title", quote=quote)],
            )
            for rank, (code, quote) in enumerate(zip(CODES[:count], QUOTES[:count], strict=True), 1)
        ],
    )


def checks() -> None:
    fresh_retention_install_checks()
    f.sql(
        "UPDATE ingestion.record SET normalized="
        + f.js(
            dict(
                kind="Competency",
                code=CODES[0] + "01_24v1",
                name="웹 개발",
                definition="웹 개발",
                occupation_code=CODES[0],
                occupation_name="응용SW엔지니어링",
                classification_names=context.CLASSES,
            )
        )
        + " WHERE run_id='ncs_competency'"
    )
    for index, (code, name) in enumerate(
        zip(CODES[1:], ["DB엔지니어링", "보안사고분석"], strict=True), 1
    ):
        row = dict(
            kind="Competency",
            code=code + "01_24v1",
            name=QUOTES[index],
            definition=QUOTES[index],
            occupation_code=code,
            occupation_name=name,
            classification_names=context.CLASSES,
        )
        f.sql(
            f"INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized) VALUES('ncs_competency','one',{f.quote('/' + str(index))},{f.quote(row['code'])},{f.js(row)},{f.js(row)})"
        )
    f.sql(
        "UPDATE ingestion.partition SET page_size=3,expected_total=3 WHERE run_id='ncs_competency'; UPDATE ingestion.document SET declared_total=3,effective_page_size=3,item_count=3 WHERE run_id='ncs_competency';"
    )
    assert (
        f.sql("SELECT count(*) FROM ingestion.validation_issue WHERE run_id='ncs_competency'")
        == "0"
    )
    body = json.dumps(
        [
            dict(
                job_title=TITLE,
                job_position=TITLE,
                job_functions=TITLE,
                product_page_url="https://www.jobkorea.co.kr/Recruit/GI_Read/50400001",
            )
        ],
        ensure_ascii=False,
    )
    digest = hashlib.sha256(body.encode()).hexdigest()
    jobs = f.sql(
        f"SELECT run_id FROM ingestion.begin_jobkorea_import({f.quote(digest)},{len(body.encode())},'jobkorea/'||{f.quote(digest)}||'/source.json',clock_timestamp())"
    )
    f.sql(
        f"SELECT * FROM ingestion.load_jobkorea_document({f.quote(jobs)},{f.quote(body)}); SELECT ingestion.verify_jobkorea_file({f.quote(jobs)},{f.quote(digest)},{len(body.encode())}); SELECT * FROM ingestion.finalize_jobkorea_import({f.quote(jobs)})"
    )
    posting = "ext-jobkorea-" + hashlib.sha256(b"50400001").hexdigest()
    f.sql(f"SELECT enrichment.prepare_jobkorea_input_bundle({f.quote(jobs)},{f.quote(posting)})")
    for number in range(31, 37):
        f.sql(next((ROOT / "hop/llm/sql").glob(f"{number:03d}_*.sql")).read_text())
    opts = dict(
        categorize_model="openai/gpt-5.6-luna",
        provider_only="openai",
        extra_params={},
        limit=1,
        candidate_limit=12,
        max_matches=1,
        max_input_chars=16000,
        max_output_tokens=768,
        max_requests=1,
        request_reserve_usd=0.005,
        max_cost_usd=0.05,
        daily_budget_usd=4.75,
        request_delay_ms=0,
        read_timeout_ms=5000,
        execute_requests="Y",
        reuse_cache="Y",
        endpoint="https://openrouter.ai/api/v1/chat/completions",
        posting_ids=posting,
        reasoning_effort="none",
        prompt_version="ko-metadata-occupation-v2",
    )

    def plan(batch: str, settings: dict) -> tuple[str, str]:
        f.sql(
            f"SELECT enrichment.plan_metadata_occupation_batch({f.quote(batch)},{f.quote(jobs)},'ncs_competency',{f.js(settings)})"
        )
        row = json.loads(
            f.sql("SELECT row_to_json(i) FROM enrichment.item i WHERE batch_id=" + f.quote(batch))
        )
        return row["item_id"], row["categorization_id"]

    def response(attempt: str, result: dict) -> str:
        envelope = dict(
            id="SYNTHETIC_OFFLINE",
            model=opts["categorize_model"],
            choices=[
                dict(
                    finish_reason="stop",
                    message=dict(content=json.dumps(result, ensure_ascii=False)),
                )
            ],
            usage=dict(
                cost=0.0001,
                is_byok=True,
                cost_details=dict(upstream_inference_cost=0.0002),
                prompt_tokens=100,
                completion_tokens=50,
            ),
        )
        f.sql(
            f"SELECT enrichment.reserve_request({f.quote(attempt)}); SELECT enrichment.save_response({f.quote(attempt)},200,{f.quote(json.dumps(envelope, ensure_ascii=False))},1)"
        )
        return f.sql("SELECT state FROM enrichment.attempt WHERE attempt_id=" + f.quote(attempt))

    def finish(batch: str) -> str:
        f.sql("SELECT enrichment.finish_metadata_occupation_batch(" + f.quote(batch) + ")")
        return f.sql(
            "SELECT result_id FROM enrichment.metadata_occupation_result r JOIN enrichment.item i USING(item_id) WHERE i.batch_id="
            + f.quote(batch)
        )

    def rows() -> list:
        return json.loads(
            f.sql(
                f"SELECT coalesce(jsonb_agg(payload ORDER BY payload->>'match_rank'),'[]') FROM enrichment.metadata_occupation_graph_rows({f.quote(jobs)},'ncs_competency',true)"
            )
        )

    _, old_attempt = plan("multi-old-v2", opts)
    old_output = copy.deepcopy(output(1))
    for m in old_output["matches"]:
        del m["match_rank"], m["role_anchor"]
    assert response(old_attempt, old_output) == "VALIDATED"
    old_result = finish("multi-old-v2")
    f.sql(
        f"SELECT enrichment.decide_metadata_occupation({f.quote(old_result)},'ACCEPT','independent-reviewer','human','SYNTHETIC reviewed old role')"
    )
    legacy = rows()
    history = f.sql(
        "SELECT enrichment.hash(jsonb_agg(to_jsonb(r) ORDER BY result_no)::text) FROM enrichment.metadata_occupation_result r"
    )
    prompt_hashes = f.sql(
        "SELECT jsonb_object_agg(version,content_hash) FROM enrichment.prompt WHERE version IN('ko-link-v1','ko-metadata-occupation-v1','ko-metadata-occupation-v2')"
    )
    migration = ROOT / "hop/llm/sql/037_metadata_occupation_multimatch.sql"
    f.sql(migration.read_text())
    assert rows() == legacy and history == f.sql(
        "SELECT enrichment.hash(jsonb_agg(to_jsonb(r) ORDER BY result_no)::text) FROM enrichment.metadata_occupation_result r"
    )
    assert "occupation_scheme" not in legacy[0]
    focused_installer_replay()
    assert rows() == legacy and history == f.sql(
        "SELECT enrichment.hash(jsonb_agg(to_jsonb(r) ORDER BY result_no)::text) FROM enrichment.metadata_occupation_result r"
    )
    v3 = opts | dict(prompt_version=VERSION, max_matches=3, max_output_tokens=1536)
    f.reject(
        f"SELECT enrichment.plan_metadata_occupation_batch('legacy-cap3',{f.quote(jobs)},'ncs_competency',{f.js(opts | dict(max_matches=3))})",
        "INVALID_METADATA_OCCUPATION_OPTIONS",
    )
    f.reject(
        f"SELECT enrichment.plan_metadata_occupation_batch('v3-cap4',{f.quote(jobs)},'ncs_competency',{f.js(v3 | dict(max_matches=4))})",
        "INVALID_METADATA_OCCUPATION_OPTIONS",
    )
    # Implicit fresh selection does not automatically reclassify terminal history.
    f.sql(
        f"SELECT enrichment.plan_metadata_occupation_batch('v3-implicit',{f.quote(jobs)},'ncs_competency',{f.js(v3 | dict(posting_ids=''))})"
    )
    assert f.sql("SELECT count(*) FROM enrichment.item WHERE batch_id='v3-implicit'") == "0"
    _, attempt = plan("v3-pending", v3)
    assert rows() == legacy
    assert (
        f.sql(
            "SELECT old.cache_key<>new.cache_key FROM enrichment.attempt old CROSS JOIN enrichment.attempt new WHERE old.attempt_id="
            + f.quote(old_attempt)
            + " AND new.attempt_id="
            + f.quote(attempt)
        )
        == "t"
    )
    candidates = json.loads(
        f.sql("SELECT candidates FROM enrichment.attempt WHERE attempt_id=" + f.quote(attempt))
    )
    source = dict(title=TITLE, role=TITLE, job_functions=TITLE)

    def issues(value: dict, fields: dict | None = None, cap: int = 3) -> list:
        return json.loads(
            f.sql(
                f"SELECT enrichment.metadata_occupation_output_issues_v3({f.js(value)},{f.js(fields or source)},{f.js(candidates)},{cap})"
            )
        )

    assert issues(output(2)) == [] and issues(output(3)) == [], (issues(output(2)), issues(output(3)), candidates)
    assert "METADATA_OCCUPATION_MATCH_SHAPE" in issues(
        dict(outcome="matched", matches=["not a match object"], abstain_reason="")
    )
    assert "METADATA_OCCUPATION_OUTPUT_SHAPE" in issues(
        dict(outcome="matched", matches=None, abstain_reason="")
    )
    assert "METADATA_OCCUPATION_MATCH_CAP" in issues(output(3), cap=2)
    duplicate = copy.deepcopy(output(2))
    duplicate["matches"][1]["occupation_code"] = CODES[0]
    assert "METADATA_OCCUPATION_DUPLICATE" in issues(duplicate)
    missing = copy.deepcopy(output(2))
    missing["matches"][1]["evidence"] = []
    assert "METADATA_OCCUPATION_INDEPENDENT_ROLE_EVIDENCE" in issues(missing)
    reused = copy.deepcopy(output(2))
    reused["matches"][1]["role_anchor"] = reused["matches"][0]["role_anchor"]
    assert "METADATA_OCCUPATION_DISTINCT_ORDERED_ROLE_ANCHORS" in issues(reused)
    reordered = copy.deepcopy(output(2))
    reordered["matches"].reverse()
    assert "METADATA_OCCUPATION_MATCH_RANK" in issues(reordered)
    assert "METADATA_OCCUPATION_DISTINCT_ORDERED_ROLE_ANCHORS" in issues(reordered)
    split_fields = copy.deepcopy(output(2))
    split_fields["matches"][1]["role_anchor"]["field"] = "role"
    split_fields["matches"][1]["evidence"][0]["field"] = "role"
    assert "METADATA_OCCUPATION_DISTINCT_ORDERED_ROLE_ANCHORS" in issues(split_fields)
    invented = copy.deepcopy(output(2))
    invented["matches"][1]["evidence"][0]["quote"] = "없는 원문"
    assert "METADATA_OCCUPATION_UNSUPPORTED_CITATION" in issues(invented)
    vague = copy.deepcopy(output(2))
    vague["matches"][0]["reason"] = "Scope is ambiguous"
    assert "METADATA_OCCUPATION_AMBIGUOUS_MATCH" in issues(vague)
    alternative = dict(title=TITLE.replace(" 및 ", " 또는 "), role=TITLE)
    assert "METADATA_OCCUPATION_ALTERNATIVE_OR_CONTRADICTORY_ROLES" in issues(
        output(2), alternative
    )
    assert "METADATA_OCCUPATION_ALTERNATIVE_OR_CONTRADICTORY_ROLES" in issues(
        output(1), dict(title="웹 개발자 또는 데이터베이스 관리자", role="웹 개발자")
    )
    assert issues(output(1), dict(title="웹 개발자 (Java or Kotlin)", role="웹 개발자")) == []
    assert "METADATA_OCCUPATION_ALTERNATIVE_OR_CONTRADICTORY_ROLES" in issues(
        output(1), dict(title="웹 개발자 (not hiring)", role="웹 개발자")
    )
    assert (
        issues(
            dict(outcome="abstained", matches=[], abstain_reason="No independently supported roles")
        )
        == []
    )
    assert response(attempt, duplicate) == "REJECTED"
    finish("v3-pending")
    assert rows() == legacy  # Charged validation failure cannot hide the old edge.
    _, attempt = plan("v3-complete", v3)
    assert response(attempt, output(2)) == "VALIDATED"
    result = finish("v3-complete")
    assert finish("v3-complete") == result
    projected = rows()
    assert len(projected) == 2 and all(
        r["review_status"] == "UNREVIEWED" and r["confidence"] is None for r in projected
    )
    assert [r["match_rank"] for r in projected] == [1, 2] and [
        r["current_primary"] for r in projected
    ] == [True, False]
    assert all(
        r["occupation_scheme"] == "NCS" and r["occupation_scheme_run_id"] == "ncs_competency"
        for r in projected
    )
    assert all(
        r["evidence"][0]["source_hash"] == r["source_hash"]
        and r["evidence"][0]["offset_unit"] == "unicode-codepoint-one-inclusive"
        for r in projected
    )
    reserved_accounting = f.sql(
        "SELECT jsonb_build_array(count(*) FILTER(WHERE reserved_at IS NOT NULL),"
        "sum(enrichment.accounted_cost(state,cost_usd,reserved_usd))) FROM enrichment.attempt"
    )
    prior_candidate_ids = [r["candidate_id"] for r in projected]
    _, reused_attempt = plan("v3-cached-successor", v3)
    assert reused_attempt == attempt and rows() == projected
    cached_result = finish("v3-cached-successor")
    assert cached_result != result
    result, projected = cached_result, rows()
    assert len(projected) == 2 and all(r["review_status"] == "UNREVIEWED" for r in projected)
    assert not set(prior_candidate_ids).intersection(r["candidate_id"] for r in projected)
    assert reserved_accounting == f.sql(
        "SELECT jsonb_build_array(count(*) FILTER(WHERE reserved_at IS NOT NULL),"
        "sum(enrichment.accounted_cost(state,cost_usd,reserved_usd))) FROM enrichment.attempt"
    )  # A new immutable result from cache cannot reserve or charge the old request again.
    f.reject(
        f"SELECT enrichment.decide_metadata_occupation({f.quote(result)},'ACCEPT','reviewer','human','Do not blanket review')",
        "CANDIDATE_REVIEW_REQUIRED",
    )
    first, second = [r["candidate_id"] for r in projected]
    f.reject(
        f"SELECT enrichment.decide_metadata_occupation_candidate({f.quote(first)},'ACCEPT','native-metadata-occupation-planner','assistant','Self review')",
        "INDEPENDENT_REVIEW_REQUIRED",
    )
    decision = f.sql(
        f"SELECT enrichment.decide_metadata_occupation_candidate({f.quote(first)},'REJECT','independent-reviewer','human','SYNTHETIC first role rejected')"
    )
    assert decision == f.sql(
        f"SELECT enrichment.decide_metadata_occupation_candidate({f.quote(first)},'REJECT','independent-reviewer','human','SYNTHETIC first role rejected')"
    )
    projected = rows()
    assert (
        len(projected) == 1
        and projected[0]["match_rank"] == 2
        and projected[0]["current_primary"]
        and not projected[0]["original_primary"]
    )
    assert projected[0]["review_status"] == "UNREVIEWED"
    f.sql(
        f"SELECT enrichment.decide_metadata_occupation_candidate({f.quote(second)},'ACCEPT','independent-second-reviewer','assistant','SYNTHETIC second role individually checked')"
    )
    assert rows()[0]["review_status"] == "ASSISTANT_REVIEWED"
    assert (
        f.sql(
            f"SELECT count(*) FROM enrichment.metadata_occupation_graph_rows({f.quote(jobs)},'ncs_competency',false)"
        )
        == "1"
    )
    assert (
        f.sql(
            f"SELECT outcome FROM enrichment.metadata_occupation_status({f.quote(jobs)},'ncs_competency')"
        )
        == "ACCEPTED_INFERRED_OCCUPATION"
    )
    # Rejected candidate invalidates reuse of the entire cached model response.
    _, after_reject = plan("v3-after-reject", v3)
    assert after_reject != attempt and rows()[0]["candidate_id"] == second
    f.reject(
        f"UPDATE enrichment.metadata_occupation_candidate_decision SET notes='rewritten' WHERE candidate_id={f.quote(first)}",
        "IMMUTABLE_METADATA_OCCUPATION_HISTORY",
    )
    fingerprint = f.sql(
        "SELECT enrichment.hash(jsonb_agg(to_jsonb(c) ORDER BY candidate_id)::text) FROM enrichment.metadata_occupation_candidate c"
    )
    result_history = f.sql(
        "SELECT enrichment.hash(jsonb_agg(to_jsonb(r) ORDER BY result_no)::text) FROM enrichment.metadata_occupation_result r"
    )
    expected_projection = rows()
    focused_installer_replay()
    assert rows() == expected_projection
    assert result_history == f.sql(
        "SELECT enrichment.hash(jsonb_agg(to_jsonb(r) ORDER BY result_no)::text) FROM enrichment.metadata_occupation_result r"
    )
    for _ in range(2):
        for number in range(29, 38):
            f.sql(next((ROOT / "hop/llm/sql").glob(f"{number:03d}_*.sql")).read_text())
        assert fingerprint == f.sql(
            "SELECT enrichment.hash(jsonb_agg(to_jsonb(c) ORDER BY candidate_id)::text) FROM enrichment.metadata_occupation_candidate c"
        )
        assert prompt_hashes == f.sql(
            "SELECT jsonb_object_agg(version,content_hash) FROM enrichment.prompt WHERE version IN('ko-link-v1','ko-metadata-occupation-v1','ko-metadata-occupation-v2')"
        )
        assert rows()[0]["candidate_id"] == second
    # A newly validated explicit abstention replaces current projection, retains history.
    assert (
        response(
            after_reject,
            dict(
                outcome="abstained",
                matches=[],
                abstain_reason="SYNTHETIC unresolved combined roles",
            ),
        )
        == "VALIDATED"
    )
    finish("v3-after-reject")
    assert (
        rows() == []
        and f.sql("SELECT count(*) FROM enrichment.metadata_occupation_candidate") == "5"
    )
    assert (
        f.sql("SELECT count(*) FROM ingestion.request_attempt WHERE run_id=" + f.quote(jobs)) == "0"
    )
    print(
        "037 native multi-role, independent review, immutable replay, cache rejection, pending/failure fallback and abstention proof PASSED; paid calls/source requests/production writes=0",
        flush=True,
    )


if __name__ == "__main__":
    os.umask(0o077)
    directory = (
        Path.home()
        / ".local/state/jobtology-hop"
        / ("multimatch-postgres-" + uuid.uuid4().hex[:12])
    )
    directory.mkdir(mode=0o700, parents=True)
    sql_path = ROOT / "hop/llm/sql/037_metadata_occupation_multimatch.sql"
    sql_hash = hashlib.sha256(sql_path.read_bytes()).hexdigest()
    receipt = dict(
        status="RUNNING",
        started_at=datetime.now(UTC).isoformat(),
        sql_sha256={"llm/sql/037_metadata_occupation_multimatch.sql": sql_hash},
        artifact_hashes={
            "llm/sql/037_metadata_occupation_multimatch.sql": sql_hash,
            "ingestions/jobkorea/install_batchfree_graph_publication.hwf": hashlib.sha256(FOCUSED_INSTALLER.read_bytes()).hexdigest(),
        },
        test_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        isolated=True,
        network_none=True,
        memory_limit_bytes=384 * 1024 * 1024,
        cpus=1,
        paid_calls=0,
        source_requests=0,
        production_writes=0,
        cleanup_confirmed=False,
        overlap="Small proof may overlap untimed archive diagnostics; this is not a paired throughput measurement.",
    )
    original_command = f.command

    def bounded_command(args, value=None):
        if args[:2] == ["docker", "run"]:
            args = [
                *args[:2],
                "--memory",
                "384m",
                "--memory-swap",
                "384m",
                "--cpus",
                "1",
                *args[2:],
            ]
        return original_command(args, value)

    f.command = bounded_command
    context.checks = checks
    try:
        context.main()
        assert sql_hash == hashlib.sha256(sql_path.read_bytes()).hexdigest()
        assert receipt["artifact_hashes"]["ingestions/jobkorea/install_batchfree_graph_publication.hwf"] == hashlib.sha256(FOCUSED_INSTALLER.read_bytes()).hexdigest()
        receipt["status"] = "PASSED"
    except BaseException:
        receipt["status"] = "FAILED"
        raise
    finally:
        receipt["cleanup_confirmed"] = not original_command(
            ["docker", "ps", "-a", "--filter", "name=^/" + f.NAME + "$", "--format", "{{.Names}}"]
        )
        receipt["finished_at"] = datetime.now(UTC).isoformat()
        path = directory / "receipt.json"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump(receipt, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print("Protected PostgreSQL proof:", path, flush=True)
