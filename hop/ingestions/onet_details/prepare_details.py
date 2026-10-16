"""Build an offline, source-pinned O*NET 31.0 SW/IT reference detail bundle.

Only supplied local CSV bytes are read. URLs are inert provenance. Associations
describe reference occupations; they do not assert requirements of job postings.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, overload

CONTRACT = "jobtology-onet-details-v1"
BUNDLE_CONTRACT = "hop-onet-details-bundle-v1"
PREFIX = "urn:jobtology:onet-detail:"
BASE_PREFIX = "urn:jobtology:onet:occupation:"
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_ROWS = 200000
MAX_NODES = 20000
MAX_EDGES = 50000
RATING_HEADER = [
    "O*NET-SOC Code",
    "Title",
    "Element ID",
    "Element Name",
    "Scale ID",
    "Scale Name",
    "Data Value",
    "N",
    "Standard Error",
    "Lower CI Bound",
    "Upper CI Bound",
    "Recommend Suppress",
    "Not Relevant",
    "Date",
    "Domain Source",
]
HEADERS = {
    "software_skills": [
        "O*NET-SOC Code",
        "Title",
        "Workplace Example",
        "Element ID",
        "Element Name",
        "Hot Technology",
        "In Demand",
    ],
    "essential_skills": RATING_HEADER,
    "transferable_skills": RATING_HEADER,
    "knowledge": RATING_HEADER,
    "task_statements": [
        "O*NET-SOC Code",
        "Title",
        "Task ID",
        "Task",
        "Task Type",
        "Incumbents Responding",
        "Date",
        "Domain Source",
    ],
    "task_ratings": [
        "O*NET-SOC Code",
        "Title",
        "Task ID",
        "Task",
        "Scale ID",
        "Scale Name",
        "Category",
        "Data Value",
        "N",
        "Standard Error",
        "Lower CI Bound",
        "Upper CI Bound",
        "Recommend Suppress",
        "Date",
        "Domain Source",
    ],
    "content_model_reference": ["Element ID", "Element Name", "Description"],
    "scales_reference": ["Scale ID", "Scale Name", "Minimum", "Maximum"],
    "task_categories": ["Scale ID", "Scale Name", "Category", "Category Description"],
    "level_scale_anchors": [
        "Element ID",
        "Element Name",
        "Scale ID",
        "Scale Name",
        "Anchor Value",
        "Anchor Description",
    ],
}
RATED = {
    "essential_skills": "ONET_ESSENTIAL_SKILL",
    "transferable_skills": "ONET_TRANSFERABLE_SKILL",
    "knowledge": "ONET_KNOWLEDGE",
    "task_ratings": "ONET_TASK_RATING",
}


class DetailInputError(ValueError):
    """Frozen evidence or its normalization violates the detail contract."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise DetailInputError(code)


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        + "\n"
    ).encode("utf-8")


def sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def parse_json(body: bytes) -> Any:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            require(key not in result, "JSON_DUPLICATE_KEY")
            result[key] = value
        return result

    def finite_float(value: str) -> float:
        result = float(value)
        require(math.isfinite(result), "JSON_NONFINITE")
        return result

    try:
        return json.loads(
            body.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_float=finite_float,
            parse_constant=lambda _: require(False, "JSON_NONFINITE"),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DetailInputError("SOURCE_JSON_INVALID") from error


def local_bytes(path: Path) -> bytes:
    require(path.is_absolute(), "ABSOLUTE_LOCAL_PATH_REQUIRED")
    require(all(not part.is_symlink() for part in (path, *path.parents)), "SYMLINK_FORBIDDEN")
    require(path.is_file() and 0 < path.stat().st_size <= MAX_SOURCE_BYTES, "SOURCE_FILE_BOUND")
    body = path.read_bytes()
    require(0 < len(body) <= MAX_SOURCE_BYTES, "SOURCE_FILE_BOUND")
    return body


def rows(body: bytes, file_id: str) -> list[tuple[str, dict[str, str]]]:
    require(0 < len(body) <= MAX_SOURCE_BYTES and body.endswith(b"\n"), "CSV_FILE_BOUND_OR_LF")
    try:
        reader = csv.reader(io.StringIO(body.decode("utf-8"), newline=""), strict=True)
        require(next(reader) == HEADERS[file_id], "CSV_HEADER:" + file_id)
        result: list[tuple[str, dict[str, str]]] = []
        for values in reader:
            end = reader.line_num
            start = result[-1][0].split("-")[-1] if result else "1"
            require(
                len(values) == len(HEADERS[file_id])
                and all("\x00" not in value and len(value) <= 20000 for value in values),
                "CSV_ROW_FIELDS:" + file_id,
            )
            result.append(
                (
                    f"csv:lines:{int(start) + 1}-{end}",
                    dict(zip(HEADERS[file_id], values, strict=True)),
                )
            )
            require(len(result) <= MAX_ROWS, "CSV_ROW_BOUND")
        require(bool(result), "CSV_EMPTY")
        return result
    except (UnicodeDecodeError, csv.Error, StopIteration) as error:
        raise DetailInputError("CSV_INVALID:" + file_id) from error


@overload
def number(
    value: str, *, nullable: Literal[False] = False, integer: bool = False
) -> int | float: ...


@overload
def number(value: str, *, nullable: Literal[True], integer: bool = False) -> int | float | None: ...


def number(value: str, *, nullable: bool = False, integer: bool = False) -> int | float | None:
    if nullable and value == "":
        return None
    require(bool(re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", value)), "NUMBER_INVALID")
    decimal = Decimal(value)
    require(decimal.is_finite(), "NUMBER_NONFINITE")
    if integer:
        require(decimal == decimal.to_integral_value() and decimal >= 0, "INTEGER_INVALID")
        return int(decimal)
    result = float(decimal)
    require(math.isfinite(result) and Decimal(str(result)) == decimal, "NUMBER_PRECISION")
    return result


def flag(value: str, *, nullable: bool = False) -> bool | None:
    require(value in ({"Y", "N", ""} if nullable else {"Y", "N"}), "FLAG_INVALID")
    return None if value == "" else value == "Y"


def scope(catalogue: dict[str, Any]) -> dict[str, str]:
    require(
        catalogue.get("contract_version") == "jobtology-onet-catalog-v1"
        and catalogue.get("source_version") == "31.0"
        and catalogue.get("scheme_id") == "ONET",
        "CATALOGUE_PIN",
    )
    result: dict[str, str] = {}
    for term in catalogue["terms"]:
        if term["term_kind"] == "OCCUPATION":
            code = term["code"]
            require(
                code not in result and term["term_id"] == BASE_PREFIX + code,
                "CATALOGUE_OCCUPATION_DUPLICATE",
            )
            result[code] = term["preferred_label"]
    return result


def selected_codes(occupations: dict[str, str]) -> list[str]:
    return sorted(
        code
        for code in occupations
        if code.startswith("15-12") or code in {"11-3021.00", "15-2051.00", "17-2061.00"}
    )


def prepare_payload(
    bodies: dict[str, bytes],
    *,
    catalogue_body: bytes,
    release_id: str,
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    require(bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", release_id)), "RELEASE_ID")
    require(set(bodies) == set(HEADERS), "SOURCE_SET")
    require(
        len(sources) == len(HEADERS) and {s["file_id"] for s in sources} == set(HEADERS),
        "SOURCE_METADATA_SET",
    )
    source_map = {s["file_id"]: s for s in sources}
    for file_id, body in bodies.items():
        item = source_map[file_id]
        require(
            item["source_uri"]
            == f"https://www.onetcenter.org/dl_files/database/db_31_0_csv/{file_id}.csv"
            and item["archive_path"] == f"sources/{file_id}.csv"
            and item["encoding"] == "UTF-8"
            and item["sha256"] == sha256(body)
            and item["byte_length"] == len(body),
            "SOURCE_PIN:" + file_id,
        )
        require(
            datetime.fromisoformat(item["downloaded_at"]).utcoffset() is not None,
            "SOURCE_TIMESTAMP",
        )
    catalogue = parse_json(catalogue_body)
    occupations = scope(catalogue)
    codes = selected_codes(occupations)
    require(len(codes) == 31, "SCOPE_COUNT")
    tables = {file_id: rows(body, file_id) for file_id, body in bodies.items()}
    elements = {r["Element ID"]: (loc, r) for loc, r in tables["content_model_reference"]}
    scales = {r["Scale ID"]: (loc, r) for loc, r in tables["scales_reference"]}
    tasks = {r["Task ID"]: (loc, r) for loc, r in tables["task_statements"]}
    require(
        len(elements) == len(tables["content_model_reference"])
        and len(scales) == len(tables["scales_reference"])
        and len(tasks) == len(tables["task_statements"]),
        "REFERENCE_DUPLICATE",
    )
    nodes: dict[str, Any] = {}
    edges: dict[str, Any] = {}
    used_elements: set[str] = set()
    used_scales: set[str] = set()
    software_types: set[str] = set()
    coverage = {
        code: Counter({file_id: 0 for file_id in ["software_skills", *RATED, "task_statements"]})
        for code in codes
    }

    def provenance(file_id: str, loc: str, row: dict[str, str]) -> dict[str, Any]:
        return dict(
            file_id=file_id,
            source_locator=loc,
            source_uri=source_map[file_id]["source_uri"],
            source_values_json=canonical_bytes(row).decode().rstrip("\n"),
        )

    def node(kind: str, key: str, properties: dict[str, Any]) -> str:
        identity = PREFIX + kind.lower() + ":" + key
        value = dict(id=identity, type=kind, properties=properties)
        require(identity not in nodes or nodes[identity] == value, "NODE_ID_COLLISION")
        nodes[identity] = value
        return identity

    def edge(
        kind: str,
        source_id: str,
        target_id: str,
        properties: dict[str, Any],
        discriminator: str = "",
    ) -> None:
        key = sha256(canonical_bytes([kind, source_id, target_id, discriminator]))
        identity = PREFIX + "edge:" + key
        require(identity not in edges, "EDGE_DUPLICATE")
        edges[identity] = dict(
            id=identity, source_id=source_id, target_id=target_id, type=kind, properties=properties
        )

    def validate_reference(row: dict[str, str]) -> None:
        if "O*NET-SOC Code" in row:
            require(
                row["O*NET-SOC Code"] in occupations
                and row["Title"] == occupations[row["O*NET-SOC Code"]],
                "OCCUPATION_REFERENCE",
            )
        if "Element ID" in row:
            require(
                row["Element ID"] in elements
                and row["Element Name"] == elements[row["Element ID"]][1]["Element Name"],
                "ELEMENT_REFERENCE",
            )
        if "Scale ID" in row:
            require(
                row["Scale ID"] in scales
                and row["Scale Name"] == scales[row["Scale ID"]][1]["Scale Name"],
                "SCALE_REFERENCE",
            )
        if "Date" in row:
            require(
                bool(re.fullmatch(r"(0[1-9]|1[0-2])/[0-9]{4}", row["Date"]))
                and bool(row["Domain Source"]),
                "UPDATE_DATE_OR_DOMAIN_SOURCE",
            )

    for file_id, table in tables.items():
        seen: set[tuple[str, ...]] = set()
        for loc, row in table:
            properties: dict[str, Any]
            validate_reference(row)
            if file_id in RATED:
                key = (
                    row["O*NET-SOC Code"],
                    row.get("Element ID", row.get("Task ID", "")),
                    row["Scale ID"],
                    row.get("Category", ""),
                )
            elif file_id == "software_skills":
                key = (row["O*NET-SOC Code"], row["Element ID"], row["Workplace Example"])
            else:
                key = tuple(row.values())
            require(key not in seen, "SOURCE_ROW_DUPLICATE:" + file_id)
            seen.add(key)
            if file_id in RATED:
                value = number(row["Data Value"])
                minimum = number(scales[row["Scale ID"]][1]["Minimum"])
                maximum = number(scales[row["Scale ID"]][1]["Maximum"])
                require(minimum <= value <= maximum, "RATING_RANGE")
                properties = dict(
                    domain=file_id,
                    scale_id=row["Scale ID"],
                    scale_name=row["Scale Name"],
                    data_value=value,
                    n=number(row["N"], nullable=True, integer=True),
                    standard_error=number(row["Standard Error"], nullable=True),
                    lower_ci_bound=number(row["Lower CI Bound"], nullable=True),
                    upper_ci_bound=number(row["Upper CI Bound"], nullable=True),
                    recommend_suppress=flag(row["Recommend Suppress"], nullable=True),
                    not_relevant=flag(row.get("Not Relevant", ""), nullable=True),
                    category=number(row.get("Category", ""), nullable=True, integer=True),
                    date=row["Date"],
                    domain_source=row["Domain Source"],
                )
                if file_id == "task_ratings":
                    require(
                        row["Task ID"] in tasks
                        and all(
                            row[field] == tasks[row["Task ID"]][1][field]
                            for field in ["O*NET-SOC Code", "Task"]
                        ),
                        "TASK_REFERENCE",
                    )
                    require(
                        (row["Scale ID"] == "FT" and properties["category"] in range(1, 8))
                        or (row["Scale ID"] in {"IM", "RT"} and properties["category"] is None),
                        "TASK_CATEGORY_REFERENCE",
                    )
            elif file_id == "software_skills":
                properties = dict(
                    hot_technology=flag(row["Hot Technology"]), in_demand=flag(row["In Demand"])
                )
                require(bool(row["Workplace Example"]), "SOFTWARE_EXAMPLE_EMPTY")
            elif file_id == "task_statements":
                require(row["Task Type"] in {"Core", "Supplemental", ""}, "TASK_TYPE")
                properties = dict(
                    task_id=number(row["Task ID"], integer=True),
                    task=row["Task"],
                    task_type=row["Task Type"] or None,
                    incumbents_responding=number(
                        row["Incumbents Responding"], nullable=True, integer=True
                    ),
                    date=row["Date"],
                    domain_source=row["Domain Source"],
                )
                require(bool(row["Task"]), "TASK_EMPTY")
            elif file_id == "content_model_reference":
                require(
                    bool(re.fullmatch(r"[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*", row["Element ID"]))
                    and bool(row["Element Name"]),
                    "CONTENT_MODEL_FIELDS",
                )
                continue
            elif file_id == "scales_reference":
                require(
                    bool(row["Scale ID"])
                    and bool(row["Scale Name"])
                    and number(row["Minimum"]) <= number(row["Maximum"]),
                    "SCALE_RANGE",
                )
                continue
            elif file_id == "task_categories":
                require(
                    row["Scale ID"] == "FT"
                    and number(row["Category"], integer=True) in range(1, 8)
                    and bool(row["Category Description"]),
                    "TASK_CATEGORY_REFERENCE",
                )
                continue
            elif file_id == "level_scale_anchors":
                value = number(row["Anchor Value"], integer=True)
                require(
                    row["Scale ID"] == "LV"
                    and number(scales["LV"][1]["Minimum"])
                    <= value
                    <= number(scales["LV"][1]["Maximum"])
                    and bool(row["Anchor Description"]),
                    "ANCHOR_RANGE",
                )
                continue
            else:
                continue
            code = row["O*NET-SOC Code"]
            if code not in coverage:
                continue
            coverage[code][file_id] += 1
            properties.update(provenance(file_id, loc, row))
            properties["occupation_code"] = code
            if "Element ID" in row:
                used_elements.add(row["Element ID"])
            if "Scale ID" in row:
                used_scales.add(row["Scale ID"])
            if file_id in RATED:
                target = (
                    PREFIX + "task:" + row["Task ID"]
                    if file_id == "task_ratings"
                    else PREFIX + "element:" + row["Element ID"]
                )
                edge(
                    RATED[file_id],
                    BASE_PREFIX + code,
                    target,
                    properties,
                    row["Scale ID"] + ":" + row.get("Category", ""),
                )
            elif file_id == "task_statements":
                target = node("TASK", row["Task ID"], properties)
                edge("ONET_TASK", BASE_PREFIX + code, target, provenance(file_id, loc, row))
            else:
                # A software example's official classification is part of its identity.
                key = sha256(canonical_bytes([row["Workplace Example"], row["Element ID"]]))
                target = node(
                    "SOFTWARE",
                    key,
                    dict(workplace_example=row["Workplace Example"], element_id=row["Element ID"]),
                )
                edge("ONET_SOFTWARE_EXAMPLE", BASE_PREFIX + code, target, properties)
                element_edge = (
                    "ONET_SOFTWARE_TYPE",
                    target,
                    PREFIX + "element:" + row["Element ID"],
                )
                if target not in software_types:
                    edge(*element_edge, {})
                    software_types.add(target)

    # Include only referenced concepts and their official outline ancestry.
    for element_id in list(used_elements):
        parent = element_id
        while "." in parent:
            parent = parent.rsplit(".", 1)[0]
            require(parent in elements, "ELEMENT_ANCESTRY_REFERENCE")
            used_elements.add(parent)
    for element_id in sorted(used_elements):
        loc, row = elements[element_id]
        target = node(
            "ELEMENT",
            element_id,
            dict(
                element_id=element_id,
                element_name=row["Element Name"],
                description=row["Description"],
                **provenance("content_model_reference", loc, row),
            ),
        )
        if "." in element_id:
            edge(
                "ONET_DETAIL_PARENT", target, PREFIX + "element:" + element_id.rsplit(".", 1)[0], {}
            )
    for loc, row in tables["level_scale_anchors"]:
        if row["Element ID"] in used_elements:
            value = number(row["Anchor Value"], integer=True)
            used_scales.add(row["Scale ID"])
            identity = node(
                "LEVEL_ANCHOR",
                row["Element ID"] + ":" + row["Scale ID"] + ":" + str(value),
                dict(
                    element_id=row["Element ID"],
                    scale_id=row["Scale ID"],
                    anchor_value=value,
                    anchor_description=row["Anchor Description"],
                    **provenance("level_scale_anchors", loc, row),
                ),
            )
            edge("ONET_ANCHOR_ELEMENT", identity, PREFIX + "element:" + row["Element ID"], {})
            edge("ONET_ANCHOR_SCALE", identity, PREFIX + "scale:" + row["Scale ID"], {})
    for loc, row in tables["task_categories"]:
        if row["Scale ID"] in used_scales:
            category = number(row["Category"], integer=True)
            identity = node(
                "TASK_CATEGORY",
                row["Scale ID"] + ":" + str(category),
                dict(
                    scale_id=row["Scale ID"],
                    category=category,
                    category_description=row["Category Description"],
                    **provenance("task_categories", loc, row),
                ),
            )
            edge("ONET_CATEGORY_SCALE", identity, PREFIX + "scale:" + row["Scale ID"], {})
    for scale_id in sorted(used_scales):
        loc, row = scales[scale_id]
        node(
            "SCALE",
            scale_id,
            dict(
                scale_id=scale_id,
                scale_name=row["Scale Name"],
                minimum=number(row["Minimum"]),
                maximum=number(row["Maximum"]),
                **provenance("scales_reference", loc, row),
            ),
        )
    endpoints = set(nodes) | {BASE_PREFIX + code for code in codes}
    require(
        all(e["source_id"] in endpoints and e["target_id"] in endpoints for e in edges.values()),
        "GRAPH_ENDPOINT_REFERENCE",
    )
    require(0 < len(nodes) <= MAX_NODES and 0 < len(edges) <= MAX_EDGES, "GRAPH_COUNT_BOUND")
    return dict(
        contract_version=CONTRACT,
        release_id=release_id,
        base_release_id=catalogue["release_id"],
        base_catalogue_sha256=sha256(catalogue_body),
        source_version="31.0",
        scheme_id="ONET",
        scope_codes=codes,
        scope_coverage=[
            dict(
                occupation_code=code,
                counts=dict(coverage[code]),
                status="AVAILABLE" if sum(coverage[code].values()) else "NO_SOURCE_ROWS",
            )
            for code in codes
        ],
        sources=sorted(sources, key=lambda s: s["file_id"]),
        nodes=sorted(nodes.values(), key=lambda n: n["id"]),
        edges=sorted(edges.values(), key=lambda e: e["id"]),
    )


def write_immutable(path: Path, body: bytes) -> None:
    if path.exists():
        require(local_bytes(path) == body, "IMMUTABLE_OUTPUT_DIFFERS")
        return
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400), "wb") as stream:
        stream.write(body)


def prepare_bundle(
    source_dir: Path, catalogue_path: Path, output_dir: Path, release_id: str
) -> dict[str, Any]:
    sources = parse_json(local_bytes(source_dir / "download-sources.json"))
    bodies = {name: local_bytes(source_dir / "sources" / f"{name}.csv") for name in HEADERS}
    catalogue_body = local_bytes(catalogue_path)
    payload = prepare_payload(
        bodies, catalogue_body=catalogue_body, release_id=release_id, sources=sources
    )
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(not output_dir.is_symlink(), "SYMLINK_FORBIDDEN")
    (output_dir / "sources").mkdir(mode=0o700, exist_ok=True)
    for name, body in bodies.items():
        write_immutable(output_dir / "sources" / f"{name}.csv", body)
    receipts: list[dict[str, Any]] = []
    for name in HEADERS:
        filename = f"sources/{name}.receipt.json"
        body = local_bytes(source_dir / filename)
        receipt = parse_json(body)
        require(
            all(
                receipt[k] == v for k, v in next(s for s in sources if s["file_id"] == name).items()
            )
            and receipt["http_status"] == 200
            and receipt["response_url"] == receipt["source_uri"],
            "DOWNLOAD_RECEIPT_PIN",
        )
        write_immutable(output_dir / filename, body)
        receipts.append(dict(archive_path=filename, sha256=sha256(body), byte_length=len(body)))
    write_immutable(output_dir / "base_catalogue.json", catalogue_body)
    body = canonical_bytes(payload)
    write_immutable(output_dir / "details.json", body)
    descriptor = dict(
        contract_version=BUNDLE_CONTRACT,
        release_id=release_id,
        base_release_id=payload["base_release_id"],
        base_catalogue_sha256=payload["base_catalogue_sha256"],
        base_catalogue_byte_length=len(catalogue_body),
        source_version="31.0",
        scheme_id="ONET",
        details_file="details.json",
        details_sha256=sha256(body),
        details_byte_length=len(body),
        scope_codes=payload["scope_codes"],
        sources=payload["sources"],
        download_receipts=receipts,
        node_count=len(payload["nodes"]),
        edge_count=len(payload["edges"]),
    )
    path = output_dir / "descriptor.json"
    descriptor["prepared_at"] = (
        parse_json(local_bytes(path))["prepared_at"]
        if path.exists()
        else datetime.now(UTC).isoformat()
    )
    write_immutable(path, canonical_bytes(descriptor))
    return descriptor


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            prepare_bundle(args.source_dir, args.catalogue, args.output_dir, args.release_id),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
