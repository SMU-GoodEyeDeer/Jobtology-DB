"""Deterministic, offline Korean/English O*NET occupation candidate retrieval.

The catalogue's English labels and descriptions remain the official evidence.
Locally authored aliases only affect recall; they never assert equivalence with
Korean classifications, supply posting duties, or yield confidence estimates.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from .lexicon import HINT_ROWS, HINT_VERSION

RETRIEVAL_VERSION = "onet-ko-local-bm25-v2"
PHYSICIAN_ELIGIBILITY_VERSION = "onet-physician-evidence-eligibility-v1"
# This is a shortlist admission policy, not a Korean/O*NET taxonomy crosswalk.
# General internal/family medicine are specialties, never generic doctor parents.
_PHYSICIAN_SCOPES = {
    "29-1211.00": r"마취(?:통증의학|과)?|anesthesiologist|anaesthetist",
    "29-1212.00": r"심장\s*내과|순환기\s*내과|cardiologist|cardiology",
    "29-1213.00": r"피부과|dermatologist|dermatology",
    "29-1214.00": r"응급\s*의학|emergency\s+medicine",
    "29-1215.00": r"가정\s*의학(?:과)?|family\s+medicine",
    "29-1216.00": r"내과|소화기\s*내시경|internal\s+medicine|internist|gastroenterolog(?:ist|y)",
    "29-1217.00": r"신경과|neurologist|neurology",
    "29-1218.00": r"산부인(?:과)?|obstetrician|gynecologist|gynaecologist|obstetrics|gynecology",
    "29-1221.00": r"소아(?:청소년과|과)?|pediatrician|paediatrician|pediatrics",
    "29-1222.00": r"병리(?:과)?|pathologist|pathology",
    "29-1223.00": r"정신(?:건강의학|과)|psychiatrist|psychiatry",
    "29-1224.00": r"영상\s*의학(?:과)?|radiologist|radiology",
    "29-1229.01": r"알레르기(?:\s*내과)?|allergist|immunologist|allergy\s+medicine",
    "29-1229.02": r"입원\s*전담|입원\s*의학|hospitalist",
    "29-1229.03": r"비뇨(?:의학|기과)|urologist|urology",
    "29-1229.04": r"재활\s*의학|physical\s+medicine|physiatrist",
    "29-1229.05": r"예방\s*의학|preventive\s+medicine",
    "29-1229.06": r"스포츠\s*의학|sports\s+medicine",
    "29-1241.00": r"안과|ophthalmologist|ophthalmology",
    "29-1242.00": r"정형\s*외과|orthopedic\s+surgeon|orthopaedic\s+surgeon|orthopedic\s+surgery",
    "29-1243.00": (
        r"소아\s*(?:정형|신경|흉부|심장)?\s*외과|"
        r"pediatric\s+(?:orthopedic\s+)?surgeon|pediatric\s+surgery"
    ),
    "29-1299.01": r"자연\s*요법|naturopathic\s+physician|naturopath",
}
PHYSICIAN_OCCUPATION_CODES = frozenset(_PHYSICIAN_SCOPES)
_PHYSICIAN_FIELDS = (
    "title", "role", "job_position_raw", "positions", "duties_text",
    "job_functions", "description_text",
)
_PHYSICIAN_ROLE = (
    r"(?<!수)(?<!치과)(?<!한)의사(?!소통|결정|회|협회)|전문의|촉탁의|진료의|의무직|"
    r"임상\s*교수|진료\s*교수|\bphysician\b|\bmedical\s+doctor\b|"
    r"\bsurgeon\b|\binternist\b|\bhospitalist\b|"
    r"\b(?:anesthesiologist|cardiologist|dermatologist|pediatrician|pathologist|"
    r"psychiatrist|radiologist|urologist|physiatrist|ophthalmologist|neurologist)\b"
)
_NONPHYSICIAN_ROLE = (
    r"수의사|치과\s*의사|한의사|간호(?:사|직|조무|부)|임상\s*병리사|방사선사|"
    r"치위생|물리\s*치료사|작업\s*치료사|정신건강\s*전문요원|병동\s*지원|"
    r"약사|약무|기사|행정|사무|"
    r"연구원|상담사|개발자|엔지니어|교사|강사|\b(?:nurse|dentist|veterinarian|"
    r"pharmacist|engineer|developer|administrator|assistant|technician)\b"
)
_OTHER_MEDICAL_PROFESSION = (
    r"치과|한방|한의|수의(?:사|학)|\b(?:dentist|dental|veterinary|veterinarian)\b"
)
_MEDICAL_ROLE_RECRUITMENT = r"채용|초빙|구인|모집|임용|\b(?:hiring|vacancy|recruitment|wanted)\b"
_MEDICAL_ORGANIZATION_SUFFIX = r"\s*(?:병원|의원|의료원|학회|협회|센터)"
_MEDICAL_QUALIFICATION = r"자격|우대|면허|자격증|\b(?:qualification|preferred|license|licence)\b"
_ROLE_SPLIT = r"[\n\r,;/]|(?:및|또는|혹은|\band\b|\bor\b)"
ADMISSION_VERSION = "onet-title-training-admission-v1"
_TRAINING_PATTERNS = (
    r"(?:개발자|프로그래머|엔지니어|전문가|강사|교사|취업지원|취업연계|취업|코딩|직업훈련)"
    r"\s*(?:양성|교육|훈련)?\s*과정"
    r"(?=\s*(?:[)\].!]*\s*$|(?:수강생|교육생|훈련생|연수생|참가자|참여자)"
    r"\s*(?:모집|등록|접수|신청)\s*[)\].!]*\s*$|"
    r"(?:모집|등록|접수|신청)\s*[)\].!]*\s*$))",
    r"(?:수강생|교육생|훈련생|연수생|교육\s*참여자|교육\s*참가자)"
    r"\s*(?:모집|등록|접수|신청)\s*[)\].!]*\s*$",
    r"(?:국비지원|국비\s*지원|k-디지털)[^\n]*(?:교육|훈련|과정)"
    r"\s*(?:수강|등록|신청|교육생\s*모집|훈련생\s*모집)\s*[)\].!]*\s*$",
    r"(?:무료|국비)\s*(?:교육|훈련)\s*(?:수강|신청|모집|과정)\s*[)\].!]*\s*$",
    r"\b(?:course|bootcamp|training)[^\n]*\b(?:enrollment|enrolment|enroll now|enrol now|"
    r"students? wanted)\s*[)\].!]*\s*$",
)
_TEACHING_VACANCY = (
    r"(?:강사(?!진)|교사|교원|교수|교관|교육\s*(?:과정\s*)?(?:운영|개발)"
    r"(?:자|담당자)?|훈련\s*운영)[^\n]{0,12}(?:채용|초빙|구인|모집)|"
    r"\b(?:instructor|teacher|tutor|training coordinator|course administrator|"
    r"enrollment coordinator|enrollment administrator)\b.{0,25}"
    r"\b(?:wanted|hiring|vacancy|recruitment)\b"
)
_ENROLLMENT_IN_VACANCY = r"수강생|교육생|훈련생|양성\s*과정"
_OCCUPATION_VACANCY = r"(?:개발자|프로그래머|엔지니어)\s*(?:채용|구인|모집)"
_ADMISSION_FIELDS = ("title", "role", "job_position_raw")
SOURCE_FIELDS = (
    "title",
    "role",
    "job_functions",
    "job_position_raw",
    "positions",
    "duties_text",
    "description_text",
    "ncs_category_names",
)
FIELD_WEIGHTS = {
    "title": 1.0,
    "role": 1.0,
    "job_position_raw": 1.0,
    "positions": 1.0,
    "duties_text": 0.9,
    "job_functions": 0.35,
    "description_text": 0.3,
    "ncs_category_names": 0.08,
}
_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "it",
        "of",
        "on",
        "or",
        "other",
        "that",
        "the",
        "their",
        "these",
        "this",
        "to",
        "with",
        "all",
        "except",
        "including",
        "related",
        "may",
        "such",
        "work",
        "workers",
        "occupation",
        "occupations",
        "perform",
        "tasks",
        "activities",
        "duties",
        "job",
        "jobs",
        "hiring",
        "recruit",
        "recruitment",
        "wanted",
        "vacancy",
        "position",
        "apply",
        "application",
        "assistant",
        "associates",
    ]
)
_CODE = re.compile(r"\d{2}-\d{4}\.\d{2}\Z")
_WORD = re.compile(r"[a-z][a-z0-9]*")
_HANGUL = re.compile(r"[가-힣]")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


HINT_HASH = canonical_hash({"version": HINT_VERSION, "rules": HINT_ROWS})
ADMISSION_HASH = canonical_hash(
    {
        "version": ADMISSION_VERSION,
        "fields": _ADMISSION_FIELDS,
        "training_patterns": _TRAINING_PATTERNS,
        "teaching_vacancy_exemption": _TEACHING_VACANCY,
        "enrollment_cancels_exemption": _ENROLLMENT_IN_VACANCY,
        "occupation_vacancy_requires_ambiguity_review": _OCCUPATION_VACANCY,
    }
)
PHYSICIAN_ELIGIBILITY_HASH = canonical_hash(
    {
        "version": PHYSICIAN_ELIGIBILITY_VERSION,
        "scopes": _PHYSICIAN_SCOPES,
        "fields": _PHYSICIAN_FIELDS,
        "role": _PHYSICIAN_ROLE,
        "other_roles": _NONPHYSICIAN_ROLE,
        "other_medical_professions": _OTHER_MEDICAL_PROFESSION,
        "recruitment": _MEDICAL_ROLE_RECRUITMENT,
        "organization_suffix": _MEDICAL_ORGANIZATION_SUFFIX,
        "qualification": _MEDICAL_QUALIFICATION,
        "role_split": _ROLE_SPLIT,
        "internal_exclusions": ["29-1212.00", "29-1229.01", "29-1229.02"],
        "pediatric_surgery_suppresses_general_pediatrics": True,
        "except_pediatric_specialists_exclude_pediatric_scope": True,
        "physician_only_never_offers_nonphysician_fallback": True,
    }
)


def string_leaves(value: Any) -> list[str]:
    """Return exact original strings without joining, coercion or normalization."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for item in cast(list[Any], value) for s in string_leaves(item)]
    if isinstance(value, Mapping):
        return [s for item in cast(Mapping[str, Any], value).values() for s in string_leaves(item)]
    return []


def physician_eligibility(source_fields: Mapping[str, Any]) -> dict[str, Any]:
    """Admit named physician candidates only on original role/practice evidence.

    Neither employer names, broad categories nor a generic doctor title supply
    a specialty. Evidence quotes remain exact strings; this policy does not
    classify a posting or turn an unknown specialty into another occupation.
    """
    eligible: set[str] = set()
    evidence: list[dict[str, str]] = []
    physician_role_present = False
    other_role_present = False
    for field in _PHYSICIAN_FIELDS:
        for leaf in string_leaves(source_fields.get(field)):
            whole_physician = bool(re.search(_PHYSICIAN_ROLE, leaf, re.I))
            # Description qualifications cannot manufacture a vacancy role.
            if field != "description_text":
                other_role_present |= bool(re.search(
                    _NONPHYSICIAN_ROLE + "|" + _OTHER_MEDICAL_PROFESSION, leaf, re.I
                ))
            for part in re.split(_ROLE_SPLIT, leaf, flags=re.I):
                qualification = re.search(_MEDICAL_QUALIFICATION, part, re.I)
                if qualification and not re.search(
                    _MEDICAL_ROLE_RECRUITMENT, part[:qualification.start()], re.I
                ):
                    continue
                if re.search(_OTHER_MEDICAL_PROFESSION, part, re.I):
                    continue
                nonphysician = bool(re.search(_NONPHYSICIAN_ROLE, part, re.I))
                physician = bool(re.search(_PHYSICIAN_ROLE, part, re.I))
                if nonphysician:
                    continue
                if field != "description_text":
                    physician_role_present |= physician
                matches = {
                    code: list(re.finditer(pattern, part, re.I))
                    for code, pattern in _PHYSICIAN_SCOPES.items()
                }
                explicit_scope = any(matches.values())
                role_context = physician or (whole_physician and not nonphysician)
                if field in {"role", "job_position_raw", "positions", "duties_text"}:
                    role_context |= explicit_scope and not nonphysician
                if field == "title":
                    role_context |= explicit_scope and not nonphysician and bool(
                        re.search(_MEDICAL_ROLE_RECRUITMENT, part, re.I)
                    )
                if field == "description_text":
                    role_context |= explicit_scope and not nonphysician and bool(
                        re.search(r"모집\s*분야|채용\s*분야|담당\s*업무|진료", part)
                    )
                if not role_context:
                    continue
                for code, found in matches.items():
                    for match in found:
                        if re.match(_MEDICAL_ORGANIZATION_SUFFIX, part[match.end():], re.I):
                            continue
                        if code == "29-1216.00" and any(
                            matches[k] for k in ("29-1212.00", "29-1229.01", "29-1229.02")
                        ):
                            # A cardiologist/allergist/inpatient title does not
                            # also establish a generic outpatient internist role.
                            continue
                        if code == "29-1221.00" and matches["29-1243.00"]:
                            continue
                        if code in {"29-1241.00", "29-1242.00"} and re.search(
                            r"소아|pediatric|paediatric", part, re.I
                        ):
                            continue
                        eligible.add(code)
                        quote = {"occupation_code": code, "field": field, "quote": match.group(0)}
                        if quote not in evidence:
                            evidence.append(quote)
    return {
        "policy_version": PHYSICIAN_ELIGIBILITY_VERSION,
        "policy_sha256": PHYSICIAN_ELIGIBILITY_HASH,
        "physician_role_present": physician_role_present,
        "physician_only": physician_role_present and not other_role_present,
        "eligible_occupation_codes": sorted(eligible),
        "evidence": evidence,
        "reason_code": "SUPPORTED_PHYSICIAN_SCOPE" if eligible else (
            "UNSPECIFIED_OR_UNAVAILABLE_PHYSICIAN_SCOPE" if physician_role_present
            else "NO_SUPPORTED_PHYSICIAN_ROLE"
        ),
    }


def admission_decision(source_fields: Mapping[str, Any]) -> dict[str, Any]:
    """Exclude explicit enrollment adverts, preserving exact original provenance.

    This narrow admission rule is not an occupation assertion. Ambiguous projects,
    training graduates, employment conditions and source narratives remain eligible.
    Teaching/education-operation roles need classification and are never suppressed.
    """
    values = [
        (field, text)
        for field in _ADMISSION_FIELDS
        for text in string_leaves(source_fields.get(field))
    ]
    base: dict[str, Any] = {
        "outcome": "INCLUDE",
        "policy_version": ADMISSION_VERSION,
        "policy_sha256": ADMISSION_HASH,
        "reason_code": "ELIGIBLE_METADATA",
        "reason": "No unambiguous training-enrollment exclusion applies.",
        "evidence": [],
    }
    if any(
        not re.search(_ENROLLMENT_IN_VACANCY, match.group(0))
        for _, text in values
        for match in re.finditer(_TEACHING_VACANCY, text, re.IGNORECASE)
    ):
        return base
    for field, text in values:
        for pattern in _TRAINING_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                vacancy = next(
                    (
                        (vacancy_field, found)
                        for vacancy_field, value in values
                        if (found := re.search(_OCCUPATION_VACANCY, value))
                    ),
                    None,
                )
                if vacancy:
                    return {
                        **base,
                        "reason_code": "AMBIGUOUS_TRAINING_AND_VACANCY",
                        "reason": "Original fields contain both enrollment and explicit "
                        "occupation recruitment; retain for individual review.",
                        "evidence": [
                            {"field": field, "quote": match.group(0)},
                            {"field": vacancy[0], "quote": vacancy[1].group(0)},
                        ],
                    }
                return {
                    **base,
                    "outcome": "EXCLUDE",
                    "reason_code": "EXPLICIT_TRAINING_ENROLLMENT",
                    "reason": "Original role/title explicitly advertises training or "
                    "enrollment, rather than an occupation vacancy.",
                    "evidence": [{"field": field, "quote": match.group(0)}],
                }
    return base


def _normalized(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def _stem(word: str) -> str:
    # Small transparent inflection normalization, not a language model.
    if len(word) > 5 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _tokens(text: str) -> list[str]:
    return [_stem(w) for w in _WORD.findall(_normalized(text)) if w not in _STOP]


def _alias_pattern(alias: str) -> re.Pattern[str]:
    alias = _normalized(alias)
    if _HANGUL.search(alias):
        # Only explicitly authored word boundaries can vary. Inserting spaces
        # between every syllable would match 기관사 against 기관 사이트.
        return re.compile(r"\s*".join(re.escape(part) for part in alias.split()))
    return re.compile(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])")


def load_catalogue(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("O*NET catalogue must be a JSON object")
    return cast(dict[str, Any], value)


class CatalogueIndex:
    """A bounded shortlist against one frozen official O*NET catalogue."""

    def __init__(self, catalogue: Mapping[str, Any]) -> None:
        if catalogue.get("scheme_id") != "ONET":
            raise ValueError("candidate retrieval requires the ONET scheme")
        self.catalogue_hash = canonical_hash(catalogue)
        self.release_id = str(catalogue.get("release_id", ""))
        self.occupations: dict[str, dict[str, str]] = {}
        self.excluded_residual_codes: set[str] = set()
        terms = catalogue.get("terms")
        if not isinstance(terms, list):
            raise ValueError("O*NET catalogue terms must be an array")
        for term in cast(list[dict[str, Any]], terms):
            if term.get("term_kind") != "OCCUPATION":
                continue
            code, term_id = term.get("code"), term.get("term_id")
            label, description = term.get("preferred_label"), term.get("description")
            if not isinstance(code, str) or not _CODE.fullmatch(code):
                raise ValueError("occupation must have a dotted O*NET code")
            if term_id != "urn:jobtology:onet:occupation:" + code:
                raise ValueError("occupation term_id/code disagreement")
            term_id = cast(str, term_id)
            if code in self.occupations or code in self.excluded_residual_codes:
                raise ValueError("duplicate O*NET occupation code")
            if not isinstance(label, str) or not label or not isinstance(description, str):
                raise ValueError("occupation requires its official label and description")
            if "all other" in label.casefold():
                self.excluded_residual_codes.add(code)
                continue
            self.occupations[code] = {
                "occupation_code": code,
                "code": code,
                "term_id": term_id,
                "label": label,
                "description": description,
            }
        if not self.occupations:
            raise ValueError("O*NET catalogue has no occupations")
        self._documents: dict[str, Counter[str]] = {}
        self._postings: dict[str, list[tuple[str, int]]] = defaultdict(list)
        self._title_words: dict[str, frozenset[str]] = {}
        for code, term in self.occupations.items():
            title_tokens = _tokens(term["label"])
            words = Counter(title_tokens * 4 + _tokens(term["description"]))
            self._documents[code] = words
            self._title_words[code] = frozenset(title_tokens)
            for word, count in words.items():
                self._postings[word].append((code, count))
        self._lengths = {code: sum(words.values()) for code, words in self._documents.items()}
        self._average_length = sum(self._lengths.values()) / len(self.occupations)
        self._rules: list[tuple[tuple[re.Pattern[str], ...], str, tuple[str, ...]]] = [
            (
                tuple(_alias_pattern(alias) for alias in aliases.split("|")),
                english,
                tuple(code for code in codes.split() if code in self.occupations),
            )
            for aliases, english, codes in HINT_ROWS
        ]
        self.hint_hash = HINT_HASH

    def shortlist(
        self, source_fields: Mapping[str, Any], limit: object = 24
    ) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 40:
            raise ValueError("candidate limit must be an integer between 1 and 40")
        if admission_decision(source_fields)["outcome"] == "EXCLUDE":
            return []
        query: dict[str, float] = defaultdict(float)
        bonuses: dict[str, float] = defaultdict(float)
        hints: dict[str, list[dict[str, str]]] = defaultdict(list)
        # role and job_position_raw often repeat the same source text. Repeating
        # evidence must not multiply its score or crowd out independent roles.
        seen_text: dict[str, float] = {}
        inputs: list[tuple[str, str, float]] = []
        for field in SOURCE_FIELDS:
            for original in string_leaves(source_fields.get(field)):
                normalized = _normalized(original)
                weight = FIELD_WEIGHTS[field]
                if normalized in seen_text and seen_text[normalized] >= weight:
                    continue
                seen_text[normalized] = weight
                inputs.append((field, normalized, weight))
        for field, normalized, weight in inputs:
            for token in set(_tokens(normalized)):
                query[token] = max(query[token], weight)
            occurrences: list[tuple[re.Match[str], str, tuple[str, ...]]] = []
            for patterns, english, seeds in self._rules:
                found = [match for pattern in patterns if (match := pattern.search(normalized))]
                if found:
                    occurrence = max(found, key=lambda match: len(match.group(0)))
                    occurrences.append((occurrence, english, seeds))
            for occurrence, english, seeds in occurrences:
                # Prefer a compound role over conflicting embedded words, e.g.
                # 물리치료 over 물리 and 환경미화 over 환경. This only changes
                # retrieval; all exact original strings remain citation evidence.
                if any(
                    longer.start() <= occurrence.start()
                    and longer.end() >= occurrence.end()
                    and len(longer.group(0)) > len(occurrence.group(0))
                    for longer, _, _ in occurrences
                ):
                    continue
                for token in set(_tokens(english)):
                    query[token] = max(query[token], weight * 0.8)
                # Seed bonuses are query hints, never confidence. They outrank
                # broad English description overlap without excluding neighbours.
                for code in seeds:
                    bonuses[code] += 14.0 * weight
                    hint = {
                        "basis": "LOCAL_RETRIEVAL_HINT",
                        "field": field,
                        "matched_alias": occurrence.group(0),
                        "query_expansion": english,
                    }
                    if hint not in hints[code]:
                        hints[code].append(hint)
        scores = dict(bonuses)
        total = len(self.occupations)
        for token, weight in query.items():
            posting = self._postings.get(token, [])
            if not posting:
                continue
            idf = math.log(1.0 + (total - len(posting) + 0.5) / (len(posting) + 0.5))
            for code, tf in posting:
                length = self._lengths[code] / self._average_length
                bm25 = idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length))
                scores[code] = scores.get(code, 0.0) + bm25 * weight
        # No arbitrary occupation is supplied when there is no lexical signal.
        physician_policy = physician_eligibility(source_fields)
        eligible_physicians = set(physician_policy["eligible_occupation_codes"])
        if physician_policy["physician_only"] and not eligible_physicians:
            # This is missing occupational scope, not training/non-vacancy
            # exclusion. Do not invite a different healthcare profession.
            return []
        ordered = [
            code for code in sorted(scores, key=lambda code: (-scores[code], code))
            if (
                code in eligible_physicians
                or (
                    not physician_policy["physician_only"]
                    and code not in PHYSICIAN_OCCUPATION_CODES
                )
            )
        ][:limit]
        result: list[dict[str, Any]] = []
        for rank, code in enumerate(ordered, 1):
            candidate: dict[str, Any] = dict(self.occupations[code])
            candidate.update(
                {
                    "rank": rank,
                    "score": round(scores[code], 6),
                    "retrieval_hints": hints.get(code, []),
                    "retrieval_version": RETRIEVAL_VERSION,
                    "hint_version": HINT_VERSION,
                }
            )
            result.append(candidate)
        return result
