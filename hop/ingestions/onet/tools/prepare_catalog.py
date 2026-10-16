"""Prepare a bounded, immutable O*NET catalogue from three frozen official files.

This parser reads local evidence only. JSON-LD contexts and source URLs are inert;
it selects catalogue occupations and the supplied SOC hierarchy, not rated data.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CONTRACT = "jobtology-onet-catalog-v1"
BUNDLE_CONTRACT = "hop-onet-bundle-v1"
NAMESPACE = "urn:jobtology:onet:"
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_TERMS = 20000
OCCUPATION_URI = "https://www.onetcenter.org/dl_files/database/db_31_0_json/occupation_data.json"
TAXONOMY_URI = "https://www.onetcenter.org/ctdl/graph/ce-8350d6ad-bc2a-11ef-8f5a-005056bdd76e"
STRUCTURE_URI = "https://www.onetcenter.org/taxonomy/2019/structure/SOC_Structure.csv?fmt=csv"
STRUCTURE_HEADER = [
    "Major Group",
    "Minor Group",
    "Broad Occupation",
    "Detailed Occupation",
    "Detailed O*NET-SOC",
    "SOC or O*NET-SOC 2019 Title",
]
OCCUPATION_CODE = re.compile(r"[0-9]{2}-[0-9]{4}\.[0-9]{2}\Z")
SOC_CODE = re.compile(r"[0-9]{2}-[0-9]{4}\Z")


class CatalogInputError(ValueError):
    """A local file does not satisfy the source-specific catalogue contract."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise CatalogInputError(code)


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        + "\n"
    ).encode("utf-8")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def local_bytes(path: Path) -> bytes:
    require(path.is_absolute(), "ABSOLUTE_LOCAL_PATH_REQUIRED")
    for ancestor in (path, *path.parents):
        require(not ancestor.is_symlink(), "SOURCE_SYMLINK_FORBIDDEN")
    with path.open("rb") as stream:
        info = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(info.st_mode) and 0 < info.st_size <= MAX_SOURCE_BYTES, "SOURCE_FILE_BOUND"
        )
        body = stream.read(MAX_SOURCE_BYTES + 1)
    require(0 < len(body) <= MAX_SOURCE_BYTES, "SOURCE_FILE_BOUND")
    return body


def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def parse_json(body: bytes) -> Any:
    try:
        return json.loads(
            body.decode("utf-8"),
            object_pairs_hook=no_duplicate_keys,
            parse_constant=lambda _: (_ for _ in ()).throw(CatalogInputError("JSON_NONFINITE")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CatalogInputError("SOURCE_JSON_INVALID") from error


def text(value: Any, code: str, limit: int = 20000) -> str:
    require(isinstance(value, str) and 0 < len(value) <= limit and "\x00" not in value, code)
    return value


def language_text(value: Any, code: str) -> str:
    require(isinstance(value, dict) and "en-US" in value, code)
    return text(value["en-US"], code)


def occupation_id(code: str) -> str:
    return NAMESPACE + "occupation:" + code


def group_id(code: str) -> str:
    return NAMESPACE + "group:" + code


def occupation_rows(body: bytes) -> dict[str, tuple[int, dict[str, str]]]:
    document = parse_json(body)
    require(
        isinstance(document, dict) and isinstance(document.get("row"), list),
        "OCCUPATION_ROWS_REQUIRED",
    )
    rows = document["row"]
    require(0 < len(rows) <= MAX_TERMS, "OCCUPATION_COUNT_BOUND")
    result: dict[str, tuple[int, dict[str, str]]] = {}
    for ordinal, row in enumerate(rows):
        require(
            isinstance(row, dict) and set(row) == {"onetsoc_code", "title", "description"},
            "OCCUPATION_ROW_FIELDS",
        )
        code = text(row["onetsoc_code"], "OCCUPATION_CODE", 10)
        require(
            OCCUPATION_CODE.fullmatch(code) is not None and code not in result,
            "OCCUPATION_CODE_DUPLICATE_OR_INVALID",
        )
        result[code] = (
            ordinal,
            {
                "onetsoc_code": code,
                "title": text(row["title"], "OCCUPATION_TITLE"),
                "description": text(row["description"], "OCCUPATION_DESCRIPTION"),
            },
        )
    return result


def taxonomy_rows(body: bytes) -> tuple[dict[str, Any], dict[str, tuple[int, dict[str, Any]]]]:
    document = parse_json(body)
    require(
        isinstance(document, dict) and isinstance(document.get("@graph"), list),
        "TAXONOMY_GRAPH_REQUIRED",
    )
    graph = document["@graph"]
    require(1 < len(graph) <= MAX_TERMS + 1, "TAXONOMY_COUNT_BOUND")
    collections = [
        item
        for item in graph
        if isinstance(item, dict) and item.get("@type") == "ceterms:Collection"
    ]
    require(len(collections) == 1, "TAXONOMY_COLLECTION_REQUIRED")
    collection = collections[0]
    language_text(collection.get("ceterms:name"), "TAXONOMY_NAME")
    require(isinstance(collection.get("ceterms:hasMember"), list), "TAXONOMY_MEMBERS_REQUIRED")
    result: dict[str, tuple[int, dict[str, Any]]] = {}
    uri_set: set[str] = set()
    for ordinal, row in enumerate(graph):
        require(isinstance(row, dict), "TAXONOMY_ROW_REQUIRED")
        if row is collection:
            continue
        require(row.get("@type") == "ceterms:Occupation", "TAXONOMY_UNEXPECTED_TYPE")
        code = text(row.get("ceterms:codedNotation"), "TAXONOMY_CODE", 10)
        uri = text(row.get("@id"), "TAXONOMY_URI")
        require(
            OCCUPATION_CODE.fullmatch(code) is not None
            and code not in result
            and uri.startswith("https://www.onetcenter.org/ctdl/resources/")
            and uri not in uri_set,
            "TAXONOMY_ID_DUPLICATE_OR_INVALID",
        )
        language_text(row.get("ceterms:name"), "TAXONOMY_OCCUPATION_NAME")
        language_text(row.get("ceterms:description"), "TAXONOMY_OCCUPATION_DESCRIPTION")
        result[code] = (ordinal, row)
        uri_set.add(uri)
    members = collection["ceterms:hasMember"]
    require(
        all(isinstance(item, str) for item in members)
        and len(members) == len(set(members))
        and set(members) == uri_set,
        "TAXONOMY_MEMBERSHIP_MISMATCH",
    )
    return collection, result


def structure_rows(body: bytes) -> list[dict[str, Any]]:
    try:
        decoded = body.decode("utf-8-sig")
        source = io.StringIO(decoded, newline="")
        reader = csv.reader(source, strict=True)
        require(next(reader, None) == STRUCTURE_HEADER, "STRUCTURE_HEADER")
        result: list[dict[str, Any]] = []
        ancestors: list[str | None] = [None] * 5
        seen: set[str] = set()
        while True:
            previous_line = reader.line_num
            row = next(reader, None)
            if row is None:
                break
            require(len(row) == 6, "STRUCTURE_ROW_FIELDS")
            populated = [index for index, value in enumerate(row[:5]) if value]
            require(len(populated) == 1, "STRUCTURE_ONE_CODE_REQUIRED")
            level = populated[0]
            code = row[level]
            require(
                (OCCUPATION_CODE if level == 4 else SOC_CODE).fullmatch(code) is not None,
                "STRUCTURE_CODE_INVALID",
            )
            require(code not in seen, "STRUCTURE_DUPLICATE_CODE")
            name = text(row[5], "STRUCTURE_NAME")
            require(level == 0 or ancestors[level - 1] is not None, "STRUCTURE_PARENT_MISSING")
            parent = ancestors[level - 1] if level else None
            if level:
                require(parent is not None and parent[:2] == code[:2], "STRUCTURE_BRANCH_MISMATCH")
            if level == 4:
                require(
                    parent is not None and code[:7] == parent and not code.endswith(".00"),
                    "STRUCTURE_DETAILED_ONET_PARENT",
                )
            normalized_code = code + ".00" if level == 3 else code
            result.append(
                {
                    "code": normalized_code,
                    "source_code": code,
                    "level": level,
                    "name": name,
                    "parent_code": parent + ".00" if level == 4 else parent,
                    "source_locator": f"csv:lines:{previous_line + 1}-{reader.line_num}",
                }
            )
            require(len(result) <= MAX_TERMS, "STRUCTURE_COUNT_BOUND")
            seen.add(code)
            ancestors[level] = code
            for index in range(level + 1, 5):
                ancestors[index] = None
        require(bool(result), "STRUCTURE_EMPTY")
        return result
    except (UnicodeDecodeError, csv.Error) as error:
        raise CatalogInputError("STRUCTURE_CSV_INVALID") from error


def prepare_payload(
    occupation: bytes,
    taxonomy: bytes,
    structure: bytes,
    *,
    release_id: str,
    source_version: str,
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    require(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}", release_id) is not None,
        "RELEASE_ID_INVALID",
    )
    require(source_version == "31.0", "UNSUPPORTED_SOURCE_VERSION")
    occupations = occupation_rows(occupation)
    collection, taxonomy = taxonomy_rows(taxonomy)
    require(set(occupations) == set(taxonomy), "OCCUPATION_TAXONOMY_CODE_MISMATCH")
    structure = structure_rows(structure)
    require(
        {row["code"] for row in structure if row["level"] >= 3} == set(occupations),
        "OCCUPATION_STRUCTURE_CODE_MISMATCH",
    )
    structure_uri = next(
        source["source_uri"] for source in sources if source["file_id"] == "soc_structure"
    )
    terms: list[dict[str, Any]] = []
    hierarchy: list[dict[str, Any]] = []
    for row in structure:
        code, level = row["code"], row["level"]
        term_id = group_id(code) if level < 3 else occupation_id(code)
        attributes: dict[str, Any] = {
            "structure_file_id": "soc_structure",
            "structure_locator": row["source_locator"],
            "structure_code": row["source_code"],
            "structure_level": level,
            "hierarchy_level": level + 1,
            "structure_label": row["name"],
            "taxonomy_collection_uri": collection["@id"],
            "taxonomy_modified_at": collection.get("ceasn:dateModified"),
            "hierarchy_basis": "SOURCE_STRUCTURE",
            "language": "en-US",
        }
        if level < 3:
            name, description, uri, file_id, locator = (
                row["name"],
                None,
                structure_uri,
                "soc_structure",
                row["source_locator"],
            )
        else:
            ordinal, occupation = occupations[code]
            graph_ordinal, term = taxonomy[code]
            name, description, uri, file_id, locator = (
                occupation["title"],
                occupation["description"],
                term["@id"],
                "occupation_data",
                f"json:/row/{ordinal}",
            )
            attributes.update(
                {
                    "taxonomy_file_id": "taxonomy",
                    "taxonomy_locator": f"json:/@graph/{graph_ordinal}",
                    "taxonomy_uri": term["@id"],
                    "taxonomy_name": term["ceterms:name"],
                    "taxonomy_description": term["ceterms:description"],
                    "taxonomy_ctid": term.get("ceterms:ctid"),
                    "occupation_file_locator": locator,
                    "title_matches_taxonomy": name
                    == language_text(term["ceterms:name"], "TAXONOMY_NAME"),
                    "description_matches_taxonomy": description
                    == language_text(term["ceterms:description"], "TAXONOMY_DESCRIPTION"),
                }
            )
        terms.append(
            {
                "term_id": term_id,
                "code": code,
                "term_kind": "GROUP" if level < 3 else "OCCUPATION",
                "preferred_label": name,
                "description": description,
                "source_uri": uri,
                "file_id": file_id,
                "source_locator": locator,
                "source_attributes": attributes,
            }
        )
        parent = row["parent_code"]
        if parent is not None:
            parent_id = occupation_id(parent) if level == 4 else group_id(parent)
            hierarchy.append(
                {
                    "child_id": term_id,
                    "parent_id": parent_id,
                    "file_id": "soc_structure",
                    "source_locator": row["source_locator"],
                    "source_uri": structure_uri,
                    "source_attributes": {
                        "child_source_code": row["source_code"],
                        "structure_level": level,
                        "hierarchy_level": level + 1,
                        "hierarchy_basis": "SOURCE_STRUCTURE",
                    },
                }
            )
    return {
        "contract_version": CONTRACT,
        "release_id": release_id,
        "scheme_id": "ONET",
        "source_version": source_version,
        "taxonomy_version": "O*NET-SOC2019",
        "sources": sources,
        "terms": sorted(terms, key=lambda item: item["term_id"]),
        "hierarchy": sorted(hierarchy, key=lambda item: (item["child_id"], item["parent_id"])),
    }


def write_immutable(path: Path, body: bytes) -> None:
    if path.exists():
        require(not path.is_symlink() and path.read_bytes() == body, "IMMUTABLE_BUNDLE_CONFLICT")
        return
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def prepare_bundle(
    occupation_file: Path,
    taxonomy_file: Path,
    structure_file: Path,
    output_dir: Path,
    release_id: str,
    source_version: str = "31.0",
) -> dict[str, Any]:
    require(
        output_dir.is_absolute() and not output_dir.is_symlink(), "ABSOLUTE_PRIVATE_BUNDLE_REQUIRED"
    )
    for ancestor in output_dir.parents:
        require(not ancestor.is_symlink(), "BUNDLE_SYMLINK_FORBIDDEN")
    inputs = [
        ("occupation_data", occupation_file, OCCUPATION_URI, "sources/occupation_data.json"),
        ("taxonomy", taxonomy_file, TAXONOMY_URI, "sources/taxonomy.jsonld"),
        ("soc_structure", structure_file, STRUCTURE_URI, "sources/soc_structure.csv"),
    ]
    bodies = [local_bytes(path) for _, path, _, _ in inputs]
    sources: list[dict[str, Any]] = []
    receipts: list[tuple[str, bytes]] = []
    for (file_id, path, uri, archive_path), body in zip(inputs, bodies, strict=True):
        receipt_path = path.with_name(path.name + ".receipt.json")
        require(receipt_path.exists(), "DOWNLOAD_RECEIPT_REQUIRED")
        receipt_body = local_bytes(receipt_path)
        receipt = parse_json(receipt_body)
        require(
            isinstance(receipt, dict)
            and receipt.get("url") == uri
            and receipt.get("sha256") == sha256(body)
            and receipt.get("byte_count") == len(body),
            "DOWNLOAD_RECEIPT_MISMATCH",
        )
        downloaded_at = receipt.get("retrieved_at")
        try:
            require(
                isinstance(downloaded_at, str)
                and datetime.fromisoformat(downloaded_at).tzinfo is not None,
                "DOWNLOAD_TIME_INVALID",
            )
        except ValueError as error:
            raise CatalogInputError("DOWNLOAD_TIME_INVALID") from error
        receipts.append((f"sources/{file_id}.receipt.json", receipt_body))
        sources.append(
            {
                "file_id": file_id,
                "source_uri": uri,
                "archive_path": archive_path,
                "sha256": sha256(body),
                "byte_length": len(body),
                "encoding": "UTF-8",
                "downloaded_at": downloaded_at,
            }
        )
    payload = prepare_payload(
        *bodies, release_id=release_id, source_version=source_version, sources=sources
    )
    catalogue = canonical_bytes(payload)
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(
        stat.S_IMODE(output_dir.stat().st_mode) & 0o077 == 0, "BUNDLE_DIRECTORY_PRIVATE_REQUIRED"
    )
    source_dir = output_dir / "sources"
    require(not source_dir.is_symlink(), "BUNDLE_SYMLINK_FORBIDDEN")
    source_dir.mkdir(mode=0o700, exist_ok=True)
    for source, body in zip(sources, bodies, strict=True):
        write_immutable(output_dir / source["archive_path"], body)
    for relative, body in receipts:
        write_immutable(output_dir / relative, body)
    write_immutable(output_dir / "catalogue.json", catalogue)
    descriptor = {
        "contract_version": BUNDLE_CONTRACT,
        "release_id": release_id,
        "source_version": source_version,
        "prepared_at": datetime.now(UTC).isoformat(),
        "catalogue_file": "catalogue.json",
        "catalogue_sha256": sha256(catalogue),
        "catalogue_byte_length": len(catalogue),
        "sources": sources,
        "download_receipts": [
            {"archive_path": relative, "sha256": sha256(body), "byte_length": len(body)}
            for relative, body in receipts
        ],
        "counts": {
            "terms": len(payload["terms"]),
            "hierarchy": len(payload["hierarchy"]),
            "occupations": sum(term["term_kind"] == "OCCUPATION" for term in payload["terms"]),
            "groups": sum(term["term_kind"] == "GROUP" for term in payload["terms"]),
        },
        "attribution": (
            "O*NET 31.0 Database, U.S. Department of Labor, "
            "Employment and Training Administration (USDOL/ETA)."
        ),
        "database_license_uri": "https://creativecommons.org/licenses/by/4.0/",
        "database_license_source": "https://www.onetcenter.org/license_db.html",
        "modifications": [
            "Selected occupation code, title and description catalogue only.",
            "Converted official source structure into explicit BROADER relations "
            "and stable ONET identities.",
            "Added local hashes, provenance and processing metadata; no posting matches.",
        ],
    }
    descriptor_path = output_dir / "descriptor.json"
    if descriptor_path.exists():
        existing = parse_json(local_bytes(descriptor_path))
        require(isinstance(existing, dict), "IMMUTABLE_BUNDLE_CONFLICT")
        descriptor["prepared_at"] = existing.get("prepared_at")
    write_immutable(descriptor_path, canonical_bytes(descriptor))
    return descriptor


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--occupation-file", type=Path, required=True)
    parser.add_argument("--taxonomy-file", type=Path, required=True)
    parser.add_argument("--structure-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--source-version", default="31.0")
    args = parser.parse_args()
    descriptor = prepare_bundle(
        args.occupation_file,
        args.taxonomy_file,
        args.structure_file,
        args.output_dir,
        args.release_id,
        args.source_version,
    )
    print(
        json.dumps(
            {
                key: descriptor[key]
                for key in ("release_id", "catalogue_sha256", "catalogue_byte_length", "counts")
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
