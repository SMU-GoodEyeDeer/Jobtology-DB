"""Local catalogue framing, hierarchy and immutable provenance checks."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "onet_catalog_parser", ROOT / "hop/ingestions/onet/tools/prepare_catalog.py"
)
assert SPEC is not None and SPEC.loader is not None
parser = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(parser)


def sample() -> tuple[bytes, bytes, bytes]:
    rows = [
        {
            "onetsoc_code": "11-1011.00",
            "title": "Chief Executives",
            "description": "Direct organizations.",
        },
        {
            "onetsoc_code": "11-1011.03",
            "title": "Chief Sustainability Officers",
            "description": "Coordinate sustainability.",
        },
    ]
    occupations = parser.canonical_bytes({"row": rows})
    terms = [
        {
            "@id": f"https://www.onetcenter.org/ctdl/resources/{row['onetsoc_code']}",
            "@type": "ceterms:Occupation",
            "ceterms:codedNotation": row["onetsoc_code"],
            "ceterms:name": {"en-US": row["title"]},
            "ceterms:description": {"en-US": row["description"]},
        }
        for row in rows
    ]
    collection = {
        "@id": "https://www.onetcenter.org/ctdl/resources/collection",
        "@type": "ceterms:Collection",
        "ceterms:name": {"en-US": "O*NET-SOC 2019 Occupations"},
        "ceasn:dateModified": "2025-01-16T00:00:00Z",
        "ceterms:hasMember": [row["@id"] for row in terms],
    }
    taxonomy = parser.canonical_bytes(
        {"@context": "https://example.invalid/do-not-fetch", "@graph": [collection, *terms]}
    )
    structure = (
        ",".join(parser.STRUCTURE_HEADER) + "\r\n"
        "11-0000,,,,,Management Occupations\r\n"
        ",11-1000,,,,Top Executives\r\n"
        ",,11-1010,,,Chief Executives\r\n"
        ",,,11-1011,,Chief Executives\r\n"
        ",,,,11-1011.03,Chief Sustainability Officers\r\n"
    ).encode()
    return occupations, taxonomy, structure


def sources() -> list[dict[str, object]]:
    return [
        {"file_id": file_id, "source_uri": uri}
        for file_id, uri in (
            ("occupation_data", parser.OCCUPATION_URI),
            ("taxonomy", parser.TAXONOMY_URI),
            ("soc_structure", parser.STRUCTURE_URI),
        )
    ]


def test_official_structure_creates_distinct_groups_and_occupation_subtypes() -> None:
    payload = parser.prepare_payload(
        *sample(), release_id="test-onet-31.0", source_version="31.0", sources=sources()
    )
    assert payload["scheme_id"] == "ONET"
    assert len(payload["terms"]) == 5
    assert len(payload["hierarchy"]) == 4
    occupations = [row for row in payload["terms"] if row["term_kind"] == "OCCUPATION"]
    assert len(occupations) == 2
    extension = next(row for row in occupations if row["code"].endswith(".03"))
    relation = next(row for row in payload["hierarchy"] if row["child_id"] == extension["term_id"])
    assert relation["parent_id"] == parser.occupation_id("11-1011.00")
    assert relation["source_locator"] == "csv:lines:6-6"
    assert extension["source_attributes"]["hierarchy_level"] == 5
    assert extension["source_attributes"]["title_matches_taxonomy"] is True


def test_taxonomy_disagreement_preserves_both_descriptions() -> None:
    occupation, taxonomy, structure = sample()
    document = json.loads(taxonomy)
    document["@graph"][1]["ceterms:description"]["en-US"] = "Older source description."
    payload = parser.prepare_payload(
        occupation,
        parser.canonical_bytes(document),
        structure,
        release_id="test",
        source_version="31.0",
        sources=sources(),
    )
    term = next(row for row in payload["terms"] if row["code"] == "11-1011.00")
    assert term["description"] == "Direct organizations."
    assert term["source_attributes"]["description_matches_taxonomy"] is False
    assert term["source_attributes"]["taxonomy_description"] == {
        "en-US": "Older source description."
    }


def test_duplicate_json_key_and_membership_mismatch_rejected() -> None:
    with pytest.raises(parser.CatalogInputError, match="JSON_DUPLICATE_KEY"):
        parser.parse_json(b'{"row":[],"row":[]}')
    occupation, taxonomy, structure = sample()
    document = json.loads(taxonomy)
    document["@graph"][0]["ceterms:hasMember"].pop()
    with pytest.raises(parser.CatalogInputError, match="TAXONOMY_MEMBERSHIP_MISMATCH"):
        parser.prepare_payload(
            occupation,
            parser.canonical_bytes(document),
            structure,
            release_id="test",
            source_version="31.0",
            sources=sources(),
        )


def test_incomplete_or_ambiguous_hierarchy_rejected() -> None:
    header = ",".join(parser.STRUCTURE_HEADER) + "\n"
    with pytest.raises(parser.CatalogInputError, match="STRUCTURE_PARENT_MISSING"):
        parser.structure_rows((header + ",,,11-1011,,Chief Executives\n").encode())
    with pytest.raises(parser.CatalogInputError, match="STRUCTURE_ONE_CODE_REQUIRED"):
        parser.structure_rows((header + "11-0000,11-1000,,,,Ambiguous\n").encode())


def test_structure_cannot_omit_a_known_occupation() -> None:
    occupation, taxonomy, structure = sample()
    structure = b"\r\n".join(structure.split(b"\r\n")[:-2]) + b"\r\n"
    with pytest.raises(parser.CatalogInputError, match="OCCUPATION_STRUCTURE_CODE_MISMATCH"):
        parser.prepare_payload(
            occupation,
            taxonomy,
            structure,
            release_id="test",
            source_version="31.0",
            sources=sources(),
        )


def test_source_version_cannot_relabel_frozen_31_bytes() -> None:
    with pytest.raises(parser.CatalogInputError, match="UNSUPPORTED_SOURCE_VERSION"):
        parser.prepare_payload(
            *sample(), release_id="test", source_version="32.0", sources=sources()
        )


def test_immutable_bundle_preserves_raw_bytes_acquisition_times_and_replay(tmp_path: Path) -> None:
    source_files: list[Path] = []
    for ordinal, (name, uri, body) in enumerate(
        zip(
            ("occupation_data.json", "occupation_taxonomy.jsonld", "soc_structure.csv"),
            (parser.OCCUPATION_URI, parser.TAXONOMY_URI, parser.STRUCTURE_URI),
            sample(),
            strict=True,
        )
    ):
        source = tmp_path / name
        source.write_bytes(body)
        source.with_name(name + ".receipt.json").write_bytes(
            parser.canonical_bytes(
                {
                    "url": uri,
                    "sha256": parser.sha256(body),
                    "byte_count": len(body),
                    "retrieved_at": f"2026-10-14T04:45:0{ordinal}+00:00",
                }
            )
        )
        source_files.append(source)
    output = tmp_path / "bundle"
    first = parser.prepare_bundle(*source_files, output, "test-onet-31.0")
    frozen = {
        str(path.relative_to(output)): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    }
    second = parser.prepare_bundle(*source_files, output, "test-onet-31.0")
    assert first == second
    assert frozen == {
        str(path.relative_to(output)): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    }
    assert first["sources"][0]["downloaded_at"] == "2026-10-14T04:45:00+00:00"
    assert first["counts"] == {"terms": 5, "hierarchy": 4, "occupations": 2, "groups": 3}
    assert first["catalogue_sha256"] == parser.sha256((output / "catalogue.json").read_bytes())
    assert len(first["download_receipts"]) == 3
    with pytest.raises(parser.CatalogInputError, match="IMMUTABLE_BUNDLE_CONFLICT"):
        parser.prepare_bundle(*source_files, output, "a-different-release")


def test_missing_receipt_and_source_symlink_fail_before_bundle_write(tmp_path: Path) -> None:
    files = [tmp_path / name for name in ("occupation.json", "taxonomy.json", "structure.csv")]
    for path, body in zip(files, sample(), strict=True):
        path.write_bytes(body)
    output = tmp_path / "bundle"
    with pytest.raises(parser.CatalogInputError, match="DOWNLOAD_RECEIPT_REQUIRED"):
        parser.prepare_bundle(*files, output, "test")
    assert not output.exists()
    link = tmp_path / "link.json"
    link.symlink_to(files[0])
    with pytest.raises(parser.CatalogInputError, match="SOURCE_SYMLINK_FORBIDDEN"):
        parser.local_bytes(link)
