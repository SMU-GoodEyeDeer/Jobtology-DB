"""Offline retrieval and citation invariants for inferred O*NET classification."""

from __future__ import annotations

import copy
import json

import pytest

from hop.llm.onet.prompt import (
    EVIDENCE_FIELDS,
    HINT_HASH,
    PROMPT_HASH,
    PROMPT_TEXT,
    PROMPT_VERSION,
    REQUEST_HASH,
    REQUEST_VERSION,
    SCHEMA,
    admitted_fields,
    build_messages,
    build_request,
    validate_output,
)
from hop.llm.onet.retrieval import (
    ADMISSION_HASH,
    CatalogueIndex,
    admission_decision,
    canonical_hash,
    physician_eligibility,
)


@pytest.fixture
def catalogue() -> dict:
    # Synthetic compact catalogue fixture; no live or protected dataset required.
    rows = (
        ("29-1051.00", "Pharmacists", "Dispense medicines and advise patients."),
        ("29-1123.00", "Physical Therapists", "Provide physical therapy."),
        ("19-2012.00", "Physicists", "Study physical phenomena and physics."),
        ("15-1252.00", "Software Developers", "Develop software applications."),
        ("15-1244.00", "Network and Computer Systems Administrators", "Operate server networks."),
        ("15-1212.00", "Information Security Analysts", "Protect computer information."),
        ("17-2051.00", "Civil Engineers", "Design civil construction projects."),
        ("21-1029.00", "Social Workers, All Other", "Provide social services."),
        ("23-1011.00", "Lawyers", "Represent clients and practice law."),
        ("25-3099.00", "Teachers and Instructors, All Other", "Teach subjects."),
        ("33-9032.00", "Security Guards", "Guard buildings and property."),
        ("35-2012.00", "Cooks, Institution and Cafeteria", "Prepare cafeteria meals."),
        ("37-2011.00", "Janitors and Cleaners, Except Maids and Housekeeping Cleaners", "Clean."),
        (
            "43-3031.00",
            "Bookkeeping, Accounting, and Auditing Clerks",
            "Maintain accounting records.",
        ),
        ("43-9061.00", "Office Clerks, General", "Perform administrative office clerical work."),
        ("49-9071.00", "Maintenance and Repair Workers, General", "Maintain facilities."),
        (
            "51-8031.00",
            "Water and Wastewater Treatment Plant and System Operators",
            "Operate water treatment.",
        ),
        ("51-4121.00", "Welders, Cutters, Solderers, and Brazers", "Weld metal parts."),
        ("53-7051.00", "Industrial Truck and Tractor Operators", "Operate industrial forklifts."),
        ("53-4011.00", "Locomotive Engineers", "Drive railway trains."),
    )
    return {
        "scheme_id": "ONET",
        "release_id": "synthetic-test-v1",
        "terms": [
            {
                "code": code,
                "term_id": "urn:jobtology:onet:occupation:" + code,
                "preferred_label": label,
                "description": description,
                "term_kind": "OCCUPATION",
            }
            for code, label, description in rows
        ],
    }


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ({"title": "계약직 야간당직약사 채용"}, "29-1051.00"),
        ({"title": "Cloud Engineer"}, "15-1244.00"),
        ({"title": "Tomcat 미들웨어 운영"}, "15-1244.00"),
        ({"title": "솔루션 개발자"}, "15-1252.00"),
        ({"title": "정보보호 및 악성코드 분석"}, "15-1212.00"),
        ({"title": "토목직 경력채용"}, "17-2051.00"),
        ({"title": "청사방호 기간제근로자"}, "33-9032.00"),
        ({"title": "공무직 조리원"}, "35-2012.00"),
        ({"title": "미화원 모집"}, "37-2011.00"),
        ({"title": "시설관리 계약직"}, "49-9071.00"),
        ({"title": "상수도 시설운영"}, "51-8031.00"),
        ({"title": "용접 생산직"}, "51-4121.00"),
        ({"title": "지게차 운전원"}, "53-7051.00"),
        ({"title": "채용 재공고", "positions": [{"name": "변호사", "cnt": 1}]}, "23-1011.00"),
    ],
)
def test_broad_korean_english_recall(catalogue: dict, source: dict, expected: str) -> None:
    result = CatalogueIndex(catalogue).shortlist(source, limit=6)
    assert expected in [row["occupation_code"] for row in result]


def test_compound_roles_and_spacing_do_not_match_unrelated_words(catalogue: dict) -> None:
    index = CatalogueIndex(catalogue)
    assert index.shortlist({"title": "물리치료사 채용"}, limit=1)[0]["code"] == "29-1123.00"
    assert index.shortlist({"title": "공공기관 사이트 채용 공고"}) == []


def test_generic_hiring_company_and_industry_are_not_role_queries(catalogue: dict) -> None:
    assert (
        CatalogueIndex(catalogue).shortlist(
            {
                "title": "2026년 기간제근로자 채용 공고",
                "organization_name": "약사 회계 연구원",
                "industry": "software developer",
            }
        )
        == []
    )


def test_deterministic_official_identity_and_duplicate_role(catalogue: dict) -> None:
    index = CatalogueIndex(catalogue)
    a = index.shortlist({"title": "모집", "role": "Cloud Engineer"})
    b = index.shortlist(
        {"job_position_raw": "Cloud Engineer", "role": "Cloud Engineer", "title": "모집"}
    )
    assert a == b
    assert [row["rank"] for row in a] == list(range(1, len(a) + 1))
    assert a[0]["term_id"] == "urn:jobtology:onet:occupation:" + a[0]["code"]
    assert a[0]["retrieval_hints"][0]["basis"] == "LOCAL_RETRIEVAL_HINT"
    assert not any("confidence" in row for row in a)


@pytest.mark.parametrize("limit", [0, 41, True, 1.5])
def test_candidate_limit_is_bounded(catalogue: dict, limit: object) -> None:
    with pytest.raises(ValueError):
        CatalogueIndex(catalogue).shortlist({"title": "약사"}, limit=limit)


def test_catalogue_identity_requires_official_dotted_scheme(catalogue: dict) -> None:
    for key, value in (("scheme_id", "NCS"), ("terms", [])):
        wrong = copy.deepcopy(catalogue)
        wrong[key] = value
        with pytest.raises(ValueError):
            CatalogueIndex(wrong)
    wrong = copy.deepcopy(catalogue)
    wrong["terms"][0]["term_id"] = "wrong-term"
    with pytest.raises(ValueError):
        CatalogueIndex(wrong)


def matched(code: str = "29-1051.00", field: str = "title", quote: str = "약사") -> dict:
    return {
        "outcome": "matched",
        "matches": [
            {
                "occupation_code": code,
                "match_rank": 1,
                "reason": "광고된 약사 직무를 분류합니다.",
                "evidence": [{"field": field, "quote": quote}],
            }
        ],
        "abstain_reason": "",
    }


def test_exact_field_strings_and_nested_positions(catalogue: dict) -> None:
    index = CatalogueIndex(catalogue)
    source = {"title": "약사  모집", "positions": [{"name": "변호사", "cnt": 1}]}
    candidates = index.shortlist(source)
    assert validate_output(matched(), source, candidates) == []
    assert validate_output(matched("23-1011.00", "positions", "변호사"), source, candidates) == []
    bad = matched(quote="약사 모집")
    assert "match_1_citation_1_quote_not_exact" in validate_output(bad, source, candidates)
    assert (
        validate_output(
            {"outcome": "abstained", "matches": [], "abstain_reason": "역할 불명확"},
            source,
            candidates,
        )
        == []
    )


@pytest.mark.parametrize(
    "mutation,issue",
    [
        (lambda x: x.update(confidence=0.9), "output_keys"),
        (lambda x: x["matches"][0].update(confidence=None), "match_1_keys"),
        (
            lambda x: x["matches"][0].update(occupation_code="29-1141.00"),
            "match_1_candidate_not_offered",
        ),
        (lambda x: x["matches"][0].update(match_rank=True), "match_1_match_rank"),
        (
            lambda x: x["matches"][0]["evidence"][0].update(field="ncs_category_names"),
            "match_1_citation_1_field",
        ),
        (
            lambda x: x["matches"][0]["evidence"][0].update(quote="pharmacist"),
            "match_1_citation_1_quote_not_exact",
        ),
        (lambda x: x.update(abstain_reason="unclear"), "matched_outcome_consistency"),
        (
            lambda x: x["matches"].append(copy.deepcopy(x["matches"][0])),
            "match_2_duplicate_occupation",
        ),
    ],
)
def test_output_adversarial_mutations(catalogue: dict, mutation, issue: str) -> None:
    source = {"title": "약사 모집", "ncs_category_names": "보건.의료"}
    candidates = CatalogueIndex(catalogue).shortlist(source)
    value = matched()
    mutation(value)
    assert issue in validate_output(value, source, candidates)


def test_shared_source_quotes_allow_distinct_combined_roles(catalogue: dict) -> None:
    source = {"title": "약사 및 변호사 채용"}
    candidates = CatalogueIndex(catalogue).shortlist(source)
    value = matched(quote=source["title"])
    second = copy.deepcopy(value["matches"][0])
    second.update(occupation_code="23-1011.00", match_rank=2, reason="광고된 변호사 직무.")
    value["matches"].append(second)
    assert validate_output(value, source, candidates) == []
    assert "matches_limit" in validate_output(value, source, candidates, max_matches=1)


def test_request_has_strict_schema_original_evidence_and_pinned_policy(catalogue: dict) -> None:
    source = {
        "title": "약사 모집",
        "positions": [{"name": "변호사", "cnt": 1}],
        "description_text": "한 줄\r\n다음 줄",
        "organization_name": "secret",
        "signed_url": "secret",
        "ncs_category_names": "보건.의료",
    }
    original = copy.deepcopy(source)
    candidates = CatalogueIndex(catalogue).shortlist(source)
    request = build_request(source, candidates, max_matches=2)
    assert source == original
    data = json.loads(request["messages"][1]["content"])
    assert data["source_fields"] == admitted_fields(source)
    assert "organization_name" not in data["source_fields"]
    assert data["source_fields"]["description_text"] == source["description_text"]
    assert "ncs_category_names" not in EVIDENCE_FIELDS
    assert request["model"] == "openai/gpt-5.6-luna"
    assert "temperature" not in request
    assert REQUEST_VERSION == "onet-luna-strict-physician-guard-v1"
    assert request["provider"]["max_price"] == {"prompt": 0.2, "completion": 1.2}
    assert request["provider"]["require_parameters"] is True
    assert request["reasoning"] == {"effort": "none", "exclude": True}
    assert request["stream"] is False
    schema = request["response_format"]["json_schema"]
    assert schema["strict"] is True
    assert schema["schema"]["properties"]["matches"]["maxItems"] == 2
    codes = schema["schema"]["properties"]["matches"]["items"]["properties"]["occupation_code"][
        "enum"
    ]
    assert codes == [row["code"] for row in candidates]
    assert "enum" not in SCHEMA["properties"]["matches"]["items"]["properties"]["occupation_code"]
    assert len(PROMPT_HASH) == len(REQUEST_HASH) == len(HINT_HASH) == 64
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})


def test_prompt_successor_preserves_schema_and_binds_contract() -> None:
    # The paid quality fix changes selection policy, not the structural validator.
    assert canonical_hash(SCHEMA) == (
        "4dd5a6ac5297e6c3fde2f9d0e95b106078bc7537b811d9ae47d87212f113ae5d"
    )
    request = build_request({"title": "generic hiring"}, [])
    assert PROMPT_VERSION == "ko-onet-metadata-occupation-v3"
    assert request["messages"][0]["content"] == PROMPT_TEXT
    assert json.loads(request["messages"][1]["content"])["contract"] == PROMPT_VERSION
    assert (
        canonical_hash({"version": PROMPT_VERSION, "text": PROMPT_TEXT, "schema": SCHEMA})
        == PROMPT_HASH
    )
    # Keep the structured output name pinned: no provider/schema change is required.
    assert request["response_format"]["json_schema"]["name"] == "ko_onet_metadata_occupation_v1"


@pytest.mark.parametrize(
    ("source", "offered_codes", "expected_codes", "reason"),
    [
        (
            {"title": "간호사 또는 약사 채용"},
            ["29-1141.00", "29-1051.00"],
            [],
            "Unresolved occupation alternatives.",
        ),
        (
            {"title": "조리원, 미화원, 경비원, 운전원 채용"},
            ["35-2012.00", "37-2011.00", "33-9032.00"],
            [],
            "Four source roles exceed three, including the unoffered driver role.",
        ),
        (
            {"title": "웹사이트 개발자", "role": "JavaScript frontend and Java backend"},
            ["15-1252.00", "15-1251.00", "15-1254.00"],
            ["15-1254.00"],
            "One website development role with two implementation components.",
        ),
        (
            {"title": "소프트웨어 개발자", "role": "소프트웨어 개발자"},
            ["15-1252.00", "15-1251.00"],
            ["15-1252.00"],
            "One general software role repeated across fields.",
        ),
        (
            {"title": "영선·조경 담당"},
            ["37-3011.00", "49-9071.00"],
            ["49-9071.00", "37-3011.00"],
            "Distinct combined roles in source order, regardless of shortlist order.",
        ),
        (
            {"title": "Software Developer AND Database Administrator"},
            ["15-1242.00", "15-1252.00"],
            ["15-1252.00", "15-1242.00"],
            "Two explicit distinct occupations may be combined in one vacancy.",
        ),
        (
            {"title": "Customer Success Lead"},
            ["43-4051.00"],
            [],
            "Routine customer inquiries are not established by enterprise success leadership.",
        ),
        (
            {"title": "Customer Service Representative", "job_functions": "Handle inquiries"},
            ["43-4051.00"],
            ["43-4051.00"],
            "Explicit customer service and inquiry handling support the occupation.",
        ),
        (
            {"title": "교육행정 직원"},
            ["43-9061.00", "43-6014.00"],
            [],
            "General clerk versus administrative assistant scope remains unresolved.",
        ),
        (
            {"title": "간호사 채용", "description_text": "우편 또는 방문 접수"},
            ["29-1141.00"],
            ["29-1141.00"],
            "OR between application methods does not make the occupation an alternative.",
        ),
    ],
)
def test_selection_expectation_fixtures_preserve_original_inputs_and_output_contract(
    source: dict, offered_codes: list[str], expected_codes: list[str], reason: str
) -> None:
    # These are offline semantic expectations for later paid regression review,
    # not evidence that an uncalled model follows them. The validator checks form
    # and exact citations; independent review must still assess occupation fit.
    candidates = [
        {
            "occupation_code": code,
            "term_id": "urn:jobtology:onet:occupation:" + code,
            "label": "Synthetic candidate",
            "description": "Synthetic description for request/validation invariants.",
        }
        for code in offered_codes
    ]
    request = build_request(source, candidates)
    data = json.loads(request["messages"][1]["content"])
    assert data["source_fields"] == source
    assert [row["occupation_code"] for row in data["candidates"]] == offered_codes
    expected = {
        "outcome": "matched" if expected_codes else "abstained",
        "matches": [
            {
                "occupation_code": code,
                "match_rank": rank,
                "reason": reason,
                "evidence": [{"field": "title", "quote": source["title"]}],
            }
            for rank, code in enumerate(expected_codes, 1)
        ],
        "abstain_reason": "" if expected_codes else reason,
    }
    assert validate_output(expected, source, candidates) == []


def test_grounding_validation_does_not_claim_to_detect_semantic_alternatives(
    catalogue: dict,
) -> None:
    source = {"title": "약사 또는 변호사 채용"}
    candidates = CatalogueIndex(catalogue).shortlist(source)
    value = matched(quote=source["title"])
    second = copy.deepcopy(value["matches"][0])
    second.update(occupation_code="23-1011.00", match_rank=2)
    value["matches"].append(second)
    # This exact-citation response still violates occupation-selection policy.
    # Passing schema checks must never be interpreted as semantic approval.
    assert validate_output(value, source, candidates) == []


def test_empty_shortlist_builds_non_paid_abstention_contract() -> None:
    request = build_request({"title": "모집"}, [])
    matches = request["response_format"]["json_schema"]["schema"]["properties"]["matches"]
    assert matches["maxItems"] == 0
    assert "enum" not in matches["items"]["properties"]["occupation_code"]
    assert len(build_messages({"title": "모집"}, [])) == 2


@pytest.mark.parametrize(
    "source",
    [
        {"title": "로봇 AI 영상기법 산업화 자율주행, 서비스 협동로봇 개발자 과정"},
        {"title": "[국비지원IT분야취업]인공지능/웹개발", "role": "IT개발자 취업지원과정"},
        {"title": "전문가 양성 과정 수강생 모집"},
        {"title": "강사 양성 과정 교육생모집"},
        {"title": "Coding bootcamp enrollment"},
    ],
)
def test_explicit_training_admission_has_exact_original_reason(
    catalogue: dict, source: dict
) -> None:
    decision = admission_decision(source)
    assert decision["outcome"] == "EXCLUDE"
    assert decision["reason_code"] == "EXPLICIT_TRAINING_ENROLLMENT"
    assert decision["policy_sha256"] == ADMISSION_HASH
    evidence = decision["evidence"][0]
    assert evidence["quote"] in source[evidence["field"]]
    assert CatalogueIndex(catalogue).shortlist(source) == []
    assert not any("confidence" in key for key in decision)


@pytest.mark.parametrize(
    "source",
    [
        {"title": "개발자 과정 강사 채용"},
        {"title": "국비지원 교육과정 교육 운영 담당자 모집"},
        {"title": "Coding course instructor wanted"},
        {"title": "Bootcamp graduates welcome, Software Developer hiring"},
        {"title": "K-디지털 훈련 출신 SW 개발자"},
        {"title": "개발자 채용", "description_text": "수강생 모집은 종료되었습니다"},
        {"title": "개발자 과정 수료자 우대 개발자 채용"},
        {"title": "개발자 과정 운영자 채용"},
        {"title": "교육과정 개발자/운영자 채용"},
        {"title": "교육생 모집 담당자 채용"},
        {"title": "주니어 웹 개발자 모집(연수 후 정규채용 연계)", "role": "연수생 모집"},
        {"title": "사내 시스템 개발자 모집"},
    ],
)
def test_admission_preserves_teaching_training_administration_and_graduate_jobs(
    source: dict,
) -> None:
    assert admission_decision(source)["outcome"] == "INCLUDE"


def test_residual_exclusion_keeps_specific_occupation_children(catalogue: dict) -> None:
    modified = copy.deepcopy(catalogue)
    for code, label, description in (
        ("29-1229.00", "Physicians, All Other", "All physicians not listed separately."),
        ("29-1229.02", "Hospitalists", "Provide inpatient medical care."),
        ("29-1229.05", "Preventive Medicine Physicians", "Practice preventive medicine."),
    ):
        modified["terms"].append(
            {
                "code": code,
                "term_id": "urn:jobtology:onet:occupation:" + code,
                "preferred_label": label,
                "description": description,
                "term_kind": "OCCUPATION",
            }
        )
    index = CatalogueIndex(modified)
    assert "29-1229.00" in index.excluded_residual_codes
    assert "29-1229.02" in index.occupations
    assert index.shortlist({"title": "내과 입원전담전문의"})[0]["code"] == "29-1229.02"
    assert index.shortlist({"title": "예방의학과 전문의"})[0]["code"] == "29-1229.05"
    assert not any(
        "all other" in c["label"].casefold()
        for c in index.shortlist({"title": "의사 사회복지사 시간강사"})
    )


@pytest.mark.parametrize(
    ("title", "code", "label"),
    [
        ("산부인과 전문의", "29-1218.00", "Obstetricians and Gynecologists"),
        ("영상의학과 전문의", "29-1224.00", "Radiologists"),
        ("마취통증의학과 전문의", "29-1211.00", "Anesthesiologists"),
        ("소아청소년과 전문의", "29-1221.00", "Pediatricians, General"),
        ("피부과 전문의", "29-1213.00", "Dermatologists"),
        ("신경과 전문의", "29-1217.00", "Neurologists"),
    ],
)
def test_missing_physician_specialties_recall_specific_candidates(
    catalogue: dict, title: str, code: str, label: str
) -> None:
    modified = copy.deepcopy(catalogue)
    modified["terms"].append(
        {
            "code": code,
            "term_id": "urn:jobtology:onet:occupation:" + code,
            "preferred_label": label,
            "description": "Synthetic physician specialty.",
            "term_kind": "OCCUPATION",
        }
    )
    assert CatalogueIndex(modified).shortlist({"title": title}, limit=1)[0]["code"] == code


@pytest.mark.parametrize("source", [
    {"title": "촉탁의 채용"}, {"title": "정규직 의사 모집"},
    {"title": "외과 전문의 초빙"}, {"title": "내시경 전문의 채용"},
    {"title": "인터벤션 전문의 초빙"}, {"title": "공공임상교수 채용"},
    {"title": "Physician wanted"}, {"title": "General surgeon hiring"},
    {"title": "의무직 채용", "ncs_category_names": "보건.의료 내과 가정의학"},
])
def test_unknown_physician_never_invites_adjacent_specialty(catalogue: dict, source: dict) -> None:
    decision = physician_eligibility(source)
    assert decision["physician_only"] is True
    assert decision["eligible_occupation_codes"] == []
    assert CatalogueIndex(catalogue).shortlist(source) == []


@pytest.mark.parametrize(("source", "eligible"), [
    ({"title": "소화기내과 전문의 채용"}, {"29-1216.00"}),
    ({"title": "혈액종양내과 전문의 모집"}, {"29-1216.00"}),
    ({"title": "류마티스내과 진료의사"}, {"29-1216.00"}),
    ({"title": "소화기내시경 세부전문의 채용"}, {"29-1216.00"}),
    ({"title": "심장내과 전문의 채용"}, {"29-1212.00"}),
    ({"title": "알레르기내과 전문의 모집"}, {"29-1229.01"}),
    ({"title": "내과 입원전담전문의"}, {"29-1229.02"}),
    ({"title": "내과 또는 가정의학과 의사"}, {"29-1216.00", "29-1215.00"}),
    ({"positions": [{"name": "심장내과 전문의"}, {"name": "내과 전문의"}]},
     {"29-1212.00", "29-1216.00"}),
    ({"title": "소아외과 전문의"}, {"29-1243.00"}),
    ({"title": "소아정형외과 전문의"}, {"29-1243.00"}),
    ({"title": "정형외과 전문의"}, {"29-1242.00"}),
    ({"title": "예방의학과 의사"}, {"29-1229.05"}),
    ({"title": "재활의학과 전문의"}, {"29-1229.04"}),
    ({"title": "비뇨의학과 전문의"}, {"29-1229.03"}),
    ({"title": "스포츠의학 전문의"}, {"29-1229.06"}),
])
def test_named_physician_scope_preserved_without_cross_specialty_fallback(
    source: dict, eligible: set[str]
) -> None:
    decision = physician_eligibility(source)
    assert set(decision["eligible_occupation_codes"]) == eligible
    for evidence in decision["evidence"]:
        assert evidence["occupation_code"] in eligible
        assert evidence["quote"] in json.dumps(source, ensure_ascii=False)


@pytest.mark.parametrize("source", [
    {"title": "수의사 채용"}, {"title": "치과의사 채용"}, {"title": "한의사 채용"},
    {"title": "치과 전문의 채용"}, {"title": "한방 전문의 채용"},
    {"title": "수의학 전문의 채용"},
    {"title": "내과병동 간호사 채용"},
    {"title": "마포내과의원 사무원 채용"},
    {"title": "간호사 모집", "ncs_category_names": "가정의학 내과"},
    {"title": "의사 모집", "description_text": "자격요건: 내과 전문의 면허 소지자 우대"},
    {"organization_name": "심장내과병원", "title": "소프트웨어 개발자 채용"},
    {"title": "내과 전문의 자격 우대 연구원 채용"},
    {"positions": [{"name": "내과 전문의 자격 우대 연구원"}]},
    {"title": "임상병리사(진단검사의학과) 채용"},
    {"title": "간호부-순환기내과 병동지원 채용"},
    {"title": "보건의료직 방사선사(영상의학과) 채용"},
    {"title": "Internal Medicine Physician Assistant hiring"},
])
def test_nonrole_specialty_context_does_not_admit_physicians(source: dict) -> None:
    assert physician_eligibility(source)["eligible_occupation_codes"] == []


@pytest.mark.parametrize("title", ["치과 전문의 채용", "한방 전문의 채용", "수의학 전문의 채용"])
def test_nonphysician_specialists_do_not_trigger_physician_only_abstention(title: str) -> None:
    decision = physician_eligibility({"title": title})
    assert decision["physician_only"] is False
    assert decision["physician_role_present"] is False


def test_pure_physician_shortlist_never_offers_another_profession(catalogue: dict) -> None:
    modified = copy.deepcopy(catalogue)
    modified["terms"].append({
        "code": "29-1216.00", "term_id": "urn:jobtology:onet:occupation:29-1216.00",
        "preferred_label": "General Internal Medicine Physicians",
        "description": "Diagnose and treat internal diseases.", "term_kind": "OCCUPATION",
    })
    result = CatalogueIndex(modified).shortlist({"title": "내과 전문의 채용"})
    assert [r["code"] for r in result] == ["29-1216.00"]


def test_unrelated_nonmedical_candidate_and_request_bytes_remain_exact(catalogue: dict) -> None:
    index = CatalogueIndex(catalogue)
    source = {"title": "서버 운영 엔지니어 모집", "role": "서버 관리자"}
    before = index.shortlist(source)
    after = index.shortlist(dict(source, organization_name="내과의사협회", ncs_category_names=""))
    assert before == after
    assert build_request(source, before) == build_request(source, after)


@pytest.mark.parametrize("max_matches", [0, 4, True, 1.5])
def test_match_cap_validation(max_matches: object) -> None:
    with pytest.raises(ValueError):
        build_messages({}, [], max_matches=max_matches)
    with pytest.raises(ValueError):
        validate_output({}, {}, [], max_matches=max_matches)
