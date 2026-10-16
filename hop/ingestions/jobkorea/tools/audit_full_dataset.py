#!/usr/bin/env python3
"""Audit supplied local exports without requesting URLs or writing databases.

The output contains hashes, locators, schema counts and posting IDs, never raw
URL values or source text. Write its report outside Git. Source files are read
as bytes; file dates are deliberately not treated as collection timestamps.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

POSTING = re.compile(
    r"^https?://(?:www\.)?jobkorea\.co\.kr/Recruit/GI_Read/([0-9]+)(?:[/?#].*)?$",
    re.IGNORECASE,
)
DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}(T00:00:00(\.0+)?Z)?$")
INSTANT = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$"
)
ROLLING = {"상시채용", "상시", "수시채용"}
UNTIL_FILLED = {"채용시까지", "채용 시까지", "채용시 마감", "채용 시 마감"}
SUPPORTED_TEXT = {
    "company_name",
    "job_position",
    "description_text",
    "job_description_text",
    "salary",
    "experience_level",
    "education_level",
    "employment_type",
    "work_location",
    "work_hours",
    "company_size",
    "company_type",
    "industry",
    "job_functions",
    "application_method",
    "benefits",
}
NARRATIVE = {
    "description_text",
    "job_description_text",
    "duties_text",
    "eligibility_text",
    "preference_text",
    "selection_text",
    "description",
    "job_description",
    "description_html",
    "html",
    "text",
}


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_OBJECT_KEY")
        result[key] = value
    return result


def invalid_constant(_: str) -> None:
    raise ValueError("NON_JSON_CONSTANT")


def scraper_error_envelope(row: dict[str, Any]) -> bool:
    """Only the supplied scraper's envelope shape is excluded as non-listing."""
    return bool({"error", "error_code"} & row.keys()) and row.keys() <= {
        "input",
        "error",
        "error_code",
    }


def date_kind(row: dict[str, Any], key: str) -> str:
    if key not in row:
        return "MISSING_KEY"
    value = row[key]
    if value is None:
        return "NULL"
    if not isinstance(value, str):
        return "INVALID_DATE_TYPE"
    if key == "application_end_date":
        if value in ROLLING:
            return "SOURCE_ROLLING"
        if value in UNTIL_FILLED:
            return "SOURCE_UNTIL_FILLED"
    try:
        if DATE.fullmatch(value):
            date.fromisoformat(value[:10])
            return "ISO_DATE" if len(value) == 10 else "MIDNIGHT_UTC_DATE_ENCODING"
        if INSTANT.fullmatch(value):
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return "EXPLICIT_OFFSET_TIMESTAMP"
    except ValueError:
        pass
    return "INVALID_DATE"


def field_issues(row: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    ref = row.get("product_page_url")
    if not isinstance(ref, str) or not POSTING.fullmatch(ref):
        issues.append("INVALID_POSTING_REFERENCE")
    title = row.get("job_title")
    if not isinstance(title, str) or not title.strip():
        issues.append("MISSING_OR_INVALID_TITLE")
    for key in SUPPORTED_TEXT:
        if row.get(key) is not None and not isinstance(row[key], str):
            issues.append(f"INVALID_TEXT_TYPE:{key}")
    for key in ("application_start_date", "application_end_date"):
        kind = date_kind(row, key)
        if kind.startswith("INVALID"):
            issues.append(f"{kind}:{key}")
    start, end = row.get("application_start_date"), row.get("application_end_date")
    if isinstance(start, str) and isinstance(end, str):
        if DATE.fullmatch(start) and DATE.fullmatch(end):
            try:
                if date.fromisoformat(end[:10]) < date.fromisoformat(start[:10]):
                    issues.append("END_BEFORE_START")
            except ValueError:
                pass
        elif INSTANT.fullmatch(start) and INSTANT.fullmatch(end):
            try:
                if datetime.fromisoformat(end.replace("Z", "+00:00")) < datetime.fromisoformat(
                    start.replace("Z", "+00:00")
                ):
                    issues.append("END_BEFORE_START")
            except ValueError:
                pass
    count = row.get("recruitment_count")
    if count is not None and (type(count) is not int or not 0 <= count <= 2147483647):
        issues.append("INVALID_RECRUITMENT_COUNT")
    if "company_benefits_tags" in row:
        tags = row["company_benefits_tags"]
        if not isinstance(tags, list) or any(
            not isinstance(tag, str) for tag in cast(list[Any], tags)
        ):
            issues.append("INVALID_BENEFITS_TAGS")
    return sorted(issues)


def audit(source: Path) -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    identities: dict[str, list[dict[str, Any]]] = defaultdict(list)
    issues: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    all_fields: Counter[str] = Counter()
    for path in sorted(source.iterdir()):
        if not path.is_file():
            raise ValueError("UNEXPECTED_NON_FILE_ENTRY")
        if path.suffix != ".ndjson":
            raw = path.read_bytes()
            report: dict[str, Any] = {
                "file": path.name,
                "bytes": len(raw),
                "sha256": digest(raw),
                "kind": "METADATA",
                "utf8_valid": True,
            }
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                report["utf8_valid"] = False
                text = ""
            if path.name == "GI_List-codes.txt":
                report["listed_category_codes"] = re.findall(
                    r"\b100[0-9]{4}\b", text.split("====")[0]
                )
                report["explicit_file_category_mappings"] = [
                    {"category_code": match[0], "file_stem": match[1]}
                    for match in re.findall(r"(100[0-9]{4})\s*-\s*(j_[a-z0-9]+)", text)
                ]
            reports.append(report)
            continue
        hasher = hashlib.sha256()
        counts: Counter[str] = Counter()
        fields: Counter[str] = Counter()
        types: dict[str, Counter[str]] = defaultdict(Counter)
        dates: dict[str, Counter[str]] = defaultdict(Counter)
        category_counts: Counter[str] = Counter()
        max_pages: Counter[str] = Counter()
        file_ids: Counter[str] = Counter()
        offset = 0
        max_line = 0
        with path.open("rb") as handle:
            for line_no, raw in enumerate(handle, 1):
                hasher.update(raw)
                loc = {
                    "file": path.name,
                    "line": line_no,
                    "byte_offset": offset,
                    "byte_length": len(raw),
                    "line_sha256": digest(raw),
                }
                offset += len(raw)
                max_line = max(max_line, len(raw))
                counts["physical_lines"] += 1
                framing: list[str] = []
                if not raw.endswith(b"\n"):
                    framing.append("MISSING_TERMINAL_LF")
                if raw.endswith(b"\r\n"):
                    counts["crlf_lines"] += 1
                if not raw.strip():
                    framing.append("BLANK_LINE")
                if raw.startswith(b"\xef\xbb\xbf"):
                    framing.append("BOM")
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    framing.append("INVALID_UTF8")
                    text = ""
                parsed: Any = None
                try:
                    parsed = json.loads(
                        text, object_pairs_hook=unique_object, parse_constant=invalid_constant
                    )
                    if not isinstance(parsed, dict):
                        framing.append("ROW_NOT_OBJECT")
                except (ValueError, RecursionError):
                    framing.append("INVALID_JSON_OR_DUPLICATE_KEYS")
                if framing:
                    issues.append({**loc, "issues": framing})
                    counts["framing_issue_lines"] += 1
                    continue
                row = cast(dict[str, Any], parsed)
                fields.update(row.keys())
                all_fields.update(row.keys())
                for key, value in row.items():
                    types[key][type(value).__name__] += 1
                input_value = row.get("input")
                if isinstance(input_value, dict):
                    inp = cast(dict[str, Any], input_value)
                    code = inp.get("job_category_codes")
                    if isinstance(code, str) and re.fullmatch(r"[0-9,\s]+", code):
                        category_counts[code] += 1
                    elif code == "duty":
                        category_counts["SOURCE_LABEL:duty"] += 1
                    else:
                        category_counts["INVALID_OR_MISSING"] += 1
                    max_pages[str(inp.get("max_pages"))] += 1
                if scraper_error_envelope(row):
                    code = row.get("error_code")
                    code = (
                        code
                        if isinstance(code, str) and re.fullmatch(r"[a-zA-Z0-9_]{1,80}", code)
                        else "REDACTED_OR_MISSING"
                    )
                    quarantined.append(
                        {**loc, "reason": "SCRAPER_ERROR_ENVELOPE", "error_code": code}
                    )
                    counts["scraper_error_rows"] += 1
                    continue
                counts["listing_rows"] += 1
                for key in ("application_start_date", "application_end_date"):
                    dates[key][date_kind(row, key)] += 1
                narrative = [
                    key for key in NARRATIVE if isinstance(row.get(key), str) and row[key].strip()
                ]
                counts["narrative_present_rows" if narrative else "narrative_absent_rows"] += 1
                row_issues = field_issues(row)
                if row_issues:
                    issues.append({**loc, "issues": row_issues})
                    counts["source_field_issue_rows"] += 1
                else:
                    counts["adapter_accepted_candidate_rows"] += 1
                ref = row.get("product_page_url")
                match = POSTING.fullmatch(ref) if isinstance(ref, str) else None
                if match:
                    posting_id = match[1]
                    file_ids[posting_id] += 1
                    content = {
                        k: v for k, v in row.items() if k != "input" and not k.endswith("_url")
                    }
                    fields_hash = {k: digest(canonical(v)) for k, v in row.items()}
                    identities[posting_id].append(
                        {
                            **loc,
                            "posting_id": posting_id,
                            "canonical_payload_sha256": digest(canonical(row)),
                            "listing_content_sha256": digest(canonical(content)),
                            "field_sha256": fields_hash,
                            "adapter_accepted_candidate": not row_issues,
                        }
                    )
        reports.append(
            {
                "file": path.name,
                "kind": "NDJSON",
                "bytes": offset,
                "sha256": hasher.hexdigest(),
                "max_line_bytes": max_line,
                "counts": dict(counts),
                "field_counts": dict(fields),
                "field_types": {key: dict(value) for key, value in sorted(types.items())},
                "dates": {key: dict(value) for key, value in sorted(dates.items())},
                "category_codes": dict(category_counts),
                "max_pages": dict(max_pages),
                "unique_posting_ids": len(file_ids),
                "within_file_duplicate_posting_ids": sum(n > 1 for n in file_ids.values()),
                "within_file_extra_observations": sum(n - 1 for n in file_ids.values()),
            }
        )
    duplicate_groups: list[dict[str, Any]] = []
    for posting_id, observations in sorted(identities.items()):
        if len(observations) < 2:
            continue
        field_names: set[str] = set()
        for obs in observations:
            field_names.update(cast(dict[str, str], obs["field_sha256"]))
        changed = sorted(
            key
            for key in field_names
            if len({obs["field_sha256"].get(key) for obs in observations}) > 1
        )
        contents = {obs["listing_content_sha256"] for obs in observations}
        payloads = {obs["canonical_payload_sha256"] for obs in observations}
        duplicate_groups.append(
            {
                "posting_id": posting_id,
                "cross_file": len({obs["file"] for obs in observations}) > 1,
                "canonical_payload_variants": len(payloads),
                "listing_content_variants": len(contents),
                "changed_fields": changed,
                "classification": "CONTENT_CONFLICT"
                if len(contents) > 1
                else "REFERENCE_OR_CONTEXT_VARIANT"
                if len(payloads) > 1
                else "EXACT_PAYLOAD_DUPLICATE",
                "observations": [
                    {key: value for key, value in obs.items() if key != "field_sha256"}
                    for obs in observations
                ],
            }
        )
    total: Counter[str] = Counter()
    for report in reports:
        total.update(report.get("counts", {}))
    classes = Counter(group["classification"] for group in duplicate_groups)
    return {
        "audit_version": "jobkorea-local-full-audit-v1",
        "audited_at": datetime.now(UTC).isoformat(),
        "actual_scrape_time": None,
        "source_directory": str(source.resolve()),
        "source_requests": 0,
        "model_requests": 0,
        "database_writes": 0,
        "files": reports,
        "totals": dict(total),
        "unique_posting_ids": len(identities),
        "duplicate_posting_ids": len(duplicate_groups),
        "cross_file_duplicate_posting_ids": sum(group["cross_file"] for group in duplicate_groups),
        "extra_observations": sum(len(obs) - 1 for obs in identities.values()),
        "duplicate_classification_counts": dict(classes),
        "all_field_counts": dict(all_fields),
        "source_or_framing_issues": issues,
        "quarantined_scraper_errors": quarantined,
        "duplicate_groups": duplicate_groups,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[4]
    report = args.report.resolve()
    if report == repository or repository in report.parents:
        parser.error("Report must be stored outside the repository")
    result = audit(args.source)
    report.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with report.open("x", encoding="utf-8") as handle:
        report.chmod(0o600)
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "totals",
                    "unique_posting_ids",
                    "duplicate_posting_ids",
                    "cross_file_duplicate_posting_ids",
                    "extra_observations",
                    "duplicate_classification_counts",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
