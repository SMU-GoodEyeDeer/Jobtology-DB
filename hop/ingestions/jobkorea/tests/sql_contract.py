"""Focused PostgreSQL parser contracts; called by the disposable native fixture."""
import json


def quote(value):
    return "'" + value.replace("'", "''") + "'"


def check(fixture):
    def parse(row):
        statement = "SELECT to_jsonb(n) FROM ingestion.normalize_jobkorea_row("
        statement += quote(json.dumps(row, ensure_ascii=False)) + "::jsonb,'/7') n"
        return json.loads(fixture.sql(statement, "parser-contract"))

    base = {
        "product_page_url": "https://www.jobkorea.co.kr/Recruit/GI_Read/50109422",
        "job_title": "Backend developer",
        "company_name": "Example employer",
    }
    missing = parse(base)
    null = parse(base | {"application_end_date": None})
    for parsed in (missing, null):
        normalized = parsed["normalized"]
        fixture.expect(
            parsed["errors"] == []
            and normalized["deadline_kind"] == "ROLLING"
            and normalized["deadline_basis"] == "USER_POLICY"
            and normalized["deadline_date"] is None
            and normalized["deadline_at"] is None
            and normalized["deadline_raw"] is None
            and normalized["deadline_display_label"] == "상시채용",
            "missing-or-null-end-policy",
        )
    fixture.expect(
        missing["field_lineage"]["deadline"]["present"] is False
        and null["field_lineage"]["deadline"]["present"] is True,
        "missing-null-raw-distinction",
    )

    day = parse(base | {"application_end_date": "2026-11-01T00:00:00.000Z"})
    fixture.expect(
        day["errors"] == []
        and day["normalized"]["deadline_kind"] == "FIXED_DATE"
        and day["normalized"]["deadline_date"] == "2026-11-01"
        and day["normalized"]["deadline_at"] is None
        and day["normalized"]["deadline_timezone"] is None
        and day["normalized"]["deadline_precision"] == "DAY",
        "midnight-encoding-remains-date",
    )
    fixed = parse(base | {"application_end_date": "2026-11-01T18:30:00+09:00"})
    fixture.expect(
        fixed["normalized"]["deadline_kind"] == "FIXED_INSTANT"
        and fixed["normalized"]["deadline_date"] is None
        and fixed["normalized"]["deadline_at"] == "2026-11-01T09:30:00.000000Z"
        and fixed["normalized"]["deadline_timezone"] == "+09:00",
        "explicit-offset-instant",
    )
    closed = parse(base | {"source_status": "CLOSED"})
    fixture.expect(
        closed["normalized"]["source_status"] == "CLOSED"
        and closed["normalized"]["deadline_basis"] == "SOURCE_STATUS"
        and "DEADLINE_ASSUMED_ROLLING" not in closed["quality_flags"],
        "closed-status-precedes-policy",
    )
    rolling = parse(base | {"application_end_date": "상시채용"})
    fixture.expect(
        rolling["normalized"]["deadline_kind"] == "ROLLING"
        and rolling["normalized"]["deadline_basis"] == "SOURCE_FIELD"
        and rolling["normalized"]["deadline_raw"] == "상시채용",
        "source-rolling-distinct-from-policy",
    )

    invalid = parse(base | {
        "application_start_date": "",
        "application_end_date": "2026-02-31",
        "salary": [],
        "recruitment_count": -1,
        "company_benefits_tags": ["valid", 7],
    })
    fixture.expect(
        {issue["field"] for issue in invalid["errors"]} == {
            "application_start_date", "application_end_date", "salary",
            "recruitment_count", "company_benefits_tags",
        }
        and invalid["normalized"]["deadline_kind"] == "UNKNOWN"
        and "DEADLINE_ASSUMED_ROLLING" not in invalid["quality_flags"],
        "all-present-field-errors-preserved",
    )
    reversed_dates = parse(base | {
        "application_start_date": "2026-11-02",
        "application_end_date": "2026-11-01",
    })
    fixture.expect(
        any(issue["code"] == "END_BEFORE_START" for issue in reversed_dates["errors"]),
        "end-before-start-rejected",
    )
    category = parse(base | {
        "company_name": "대기업 계열사·자회사",
        "job_position": "홈페이지 지원",
        "job_description_url": "https://example.invalid/?X-Amz-Signature=synthetic-secret",
    })
    fixture.expect(
        category["errors"] == []
        and category["normalized"]["employer_identity_kind"] == "CATEGORY_ONLY"
        and category["normalized"]["organization_name"] is None
        and category["normalized"]["role"] is None
        and category["normalized"]["job_position_raw"] == "홈페이지 지원"
        and "ROLE_IS_APPLICATION_METHOD" in category["quality_flags"]
        and category["normalized"]["content_status"] == "MISSING"
        and category["normalized"]["extraction_eligible"] is False
        and "synthetic-secret" not in json.dumps(category),
        "category-role-and-signed-reference-evidence-gates",
    )
    available = parse(base | {
        "description_text": "Locally supplied description", "recruitment_count": 0,
    })
    fixture.expect(
        available["errors"] == []
        and available["normalized"]["content_status"] == "TEXT_AVAILABLE"
        and available["normalized"]["extraction_eligible"] is True
        and available["normalized"]["description_text"] == "Locally supplied description"
        and available["normalized"]["headcount"] == 0,
        "supplied-local-text-and-zero-headcount",
    )
    malicious = parse(base | {"product_page_url": "https://jobkorea.co.kr.example.invalid/Recruit/GI_Read/50109422"})
    fixture.expect(
        any(issue["code"] == "INVALID_POSTING_REFERENCE" for issue in malicious["errors"]),
        "reference-host-identity-validation",
    )
    nonobject = parse([base])
    fixture.expect(
        nonobject["errors"] == [{"code": "ROW_NOT_OBJECT", "field": ""}],
        "nonobject-row-accounted",
    )
    guarded = fixture.sql("""
DO $$ BEGIN
 BEGIN
  INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state)
  VALUES('jobkorea-test-ready-shortcut','jobkorea','REPLAY','fixture','READY');
  RAISE EXCEPTION 'TEST_READY_INSERT_SUCCEEDED';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM<>'JOBKOREA_READY_INSERT_FORBIDDEN' THEN RAISE; END IF;
 END;
 BEGIN
  INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision)
  VALUES('jobkorea-test-incomplete-publish','jobkorea','REPLAY','fixture');
  UPDATE ingestion.run SET state='READY' WHERE run_id='jobkorea-test-incomplete-publish';
  RAISE EXCEPTION 'TEST_INCOMPLETE_PUBLISH_SUCCEEDED';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM<>'JOBKOREA_READY_VALIDATION_FAILED' THEN RAISE; END IF;
 END;
END $$;
SELECT 'guarded';
""", "ready-publication-guards")
    fixture.expect(guarded == "guarded", "direct-ready-shortcuts-rejected")
    fixture.sql("""
BEGIN;
DO $$ DECLARE body text:='[{"key":1,"key":2}]'; hash text; id text; result record;
BEGIN
 hash:=encode(sha256(convert_to(body,'UTF8')),'hex');
 SELECT run_id INTO id FROM ingestion.begin_jobkorea_import(
  hash,octet_length(body),'jobkorea/'||hash||'/source.json',clock_timestamp());
 SELECT * INTO result FROM ingestion.load_jobkorea_document(id,body);
 IF result.error_code IS DISTINCT FROM 'INVALID_JSON_ARRAY_OR_DUPLICATE_KEYS' THEN
  RAISE EXCEPTION 'TEST_SQL_DUPLICATE_KEYS_ACCEPTED';
 END IF;
END $$;
ROLLBACK;
""", "sql-duplicate-key-guard")
    fixture.expect(True, "sql-duplicate-keys-independently-rejected")
