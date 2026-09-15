"""Convert one archived file using the existing document-processor library.

No downloads or model calls. The HTTP parent isolates this worker with a timeout.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unicodedata
import zipfile
import xml.etree.ElementTree as ET


def json_safe(value, changes, path="$",):
    """PostgreSQL JSONB cannot store NUL; record each normalization explicitly."""
    if isinstance(value, str):
        if "\x00" in value:
            changes.append({"path": path, "count": value.count("\x00")})
            return value.replace("\x00", "\ufffd")
        return value
    if isinstance(value, list):
        return [json_safe(v, changes, path+"["+str(i)+"]") for i, v in enumerate(value)]
    if isinstance(value, dict):
        if any("\x00" in k for k in value):
            raise ValueError("NUL_IN_METADATA_KEY")
        return {k: json_safe(v, changes, path+"."+k) for k, v in value.items()}
    return value


def project(doc):
    changes = []
    semantic = json_safe(doc.to_semantic().model_dump(mode="json", exclude_none=True), changes, "semantic")
    # Freeze the exact text given to the LLM and retain each original block locator.
    sections, parts, offset = [], [], 0
    for block in semantic["blocks"]:
        text = unicodedata.normalize("NFC", block["text"].replace("\r\n", "\n").replace("\r", "\n"))
        if not text.strip():
            continue
        if parts:
            offset += 2
        sections.append({
            "section_no": len(sections) + 1,
            "locator_kind": "document_block",
            "locator": block["node_id"],
            "kind": block["kind"],
            "page_number": block.get("page_number"),
            "debug_path": block.get("debug_path"),
            "start": offset, "end": offset + len(text),
            "content_hash": hashlib.sha256(text.encode()).hexdigest(),
        })
        parts.append(text)
        offset += len(text)
    markdown = "\n\n".join(parts)
    # The full structural JSON preserves merged-cell spans and native anchors.
    # Binary image assets are unnecessary for text linking and are never sent back.
    structure = json_safe(doc.model_dump(mode="json", exclude={"assets"}, exclude_none=True), changes, "structure")
    structure.pop("source_path", None)
    semantic.pop("source_path", None)
    warnings = []
    if changes:
        warnings.append("NUL_REPLACED_WITH_U_FFFD")
    if any(block["kind"] == "image" for block in semantic["blocks"]):
        warnings.append("IMAGE_CONTENT_REQUIRES_REVIEW")
    text_blocks = [b for b in semantic["blocks"] if b["kind"] in {"paragraph", "table"} and b["text"].strip()]
    return {"state": "PARSED" if text_blocks else "NO_TEXT", "markdown": markdown,
            "text_hash": hashlib.sha256(markdown.encode()).hexdigest(),
            "sections": sections, "semantic": semantic, "structure": structure,
            "warnings": warnings, "normalization": {"nul_replacements": changes}}


def parse_document(path, extension, parser):
    try:
        return project(parser.from_file(path, doc_type=extension))
    except ET.ParseError:
        if extension != "hwp":
            raise
        # A bundled-converter defect emits raw NULs in an XML Command parameter.
        # Keep the original HWP untouched; normalize a derived HWPX container and
        # feed it straight back to the existing parser. Never repair arbitrary XML.
        from document_processor.core.hwp_converter import convert_hwp_to_hwpx_bytes
        original = convert_hwp_to_hwpx_bytes(path)
        target = io.BytesIO()
        changes = []
        with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(target, "w") as output:
            for entry in source.infolist():
                content = source.read(entry)
                if entry.filename.endswith(".xml"):
                    normalized, count = re.subn(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]", "\ufffd".encode(), content)
                    if count:
                        changes.append(dict(entry=entry.filename, count=count,
                            original_hash=hashlib.sha256(content).hexdigest(),
                            normalized_hash=hashlib.sha256(normalized).hexdigest()))
                        content = normalized
                output.writestr(entry, content)
        if not changes:
            raise
        result = project(parser.from_file(target.getvalue(), doc_type="hwpx"))
        result["normalization"]["converted_xml_controls"] = changes
        result["warnings"].append("CONVERTED_XML_CONTROLS_REPLACED")
        return result


def main():
    request = json.load(sys.stdin)
    # Java converters sometimes print to stdout. Keep the response file separate.
    with contextlib.redirect_stdout(sys.stderr):
        from document_processor import DocIR
        if request["extension"] == "zip":
            result = project_archive(request["path"], DocIR)
        else:
            result = parse_document(request["path"], request["extension"], DocIR)
    result.update(contract="document-processor-v1", raw_hash=request["raw_hash"],
                  parser_version="document-processor/" + importlib.metadata.version("document-processor"),
                  parser_revision=os.environ.get("PARSER_REVISION", "development"))
    Path(request["result_path"]).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


def project_archive(path, parser):
    """Parse leaves in a ZIP or one nested ZIP without trusting member paths."""
    parts, sections, members, blocks, warnings = [], [], [], [], []
    offset = 0
    parsed = 0
    member_count = 0
    nested_uncompressed = 0

    def member_name(entry):
        name = entry.filename
        # Most Korean legacy ZIPs use CP949 without setting the UTF-8 flag.
        if not entry.flag_bits & 0x800:
            try:
                name = name.encode("cp437").decode("cp949")
            except (UnicodeError, LookupError):
                pass
        return unicodedata.normalize("NFC", name)

    def record_document(archive, entry, source_chain, directory):
        nonlocal offset, parsed, member_count, nested_uncompressed
        member_count += 1
        if member_count > 100:
            raise ValueError("ARCHIVE_MEMBER_COUNT_LIMIT")
        name = member_name(entry)
        ext = Path(name).suffix.lower().lstrip(".")
        source_ordinal = source_chain[-1]["ordinal"]
        # Each chain element retains the source ZIP's ordinal and stored member
        # name; the flat output list keeps build_processor_input_v2 bounded.
        chain = source_chain[:-1] + [{"name": name, "stored_name": entry.filename,
                                      "ordinal": source_ordinal}]
        display_name = "!/".join(x["name"] for x in chain)
        member = {"name": display_name, "stored_name": entry.filename,
                  "ordinal": member_count, "source_ordinal": source_ordinal,
                  "extension": ext, "archive_chain": chain}
        members.append(member)
        if ext not in {"pdf", "hwp", "hwpx", "doc", "docx", "zip"} or (ext == "zip" and len(chain) > 1):
            member.update(state="UNSUPPORTED_FORMAT")
            warnings.append("UNSUPPORTED_ARCHIVE_MEMBER")
            return
        if not 0 < entry.file_size <= 64 * 1024 * 1024:
            member.update(state="DOCUMENT_SIZE_LIMIT")
            warnings.append("UNPARSED_ARCHIVE_MEMBER")
            return
        target = Path(directory) / (str(member_count) + "." + ext)
        data = archive.read(entry)
        target.write_bytes(data)
        member["raw_hash"] = hashlib.sha256(data).hexdigest()
        chain[-1]["raw_hash"] = member["raw_hash"]
        try:
            from server import validate
            validate({"path": str(target), "extension": ext, "raw_hash": member["raw_hash"]}, Path(directory))
        except Exception as error:
            member.update(state="PARSE_ERROR", issue=str(error) if isinstance(error, ValueError) else type(error).__name__)
            warnings.append("UNPARSED_ARCHIVE_MEMBER")
            return
        if ext == "zip":
            # One nested layer is enough for the observed ALIO packages. The
            # same server validation checks encryption, traversal and symlinks
            # before any nested member is read or handed to DocIR.
            member["state"] = "CONTAINER"
            with zipfile.ZipFile(target) as nested:
                children = [child for child in nested.infolist() if not child.is_dir()]
                nested_uncompressed += sum(child.file_size for child in children)
                if member_count + len(children) > 100:
                    raise ValueError("ARCHIVE_MEMBER_COUNT_LIMIT")
                if nested_uncompressed > 256 * 1024 * 1024:
                    raise ValueError("ARCHIVE_SIZE_LIMIT")
                member["member_count"] = len(children)
                for child_ordinal, child in enumerate(children, 1):
                    record_document(nested, child, chain + [{"ordinal": child_ordinal}], directory)
            return
        try:
            output = parse_document(str(target), ext, parser)
        except Exception as error:
            member.update(state="PARSE_ERROR", issue=type(error).__name__)
            warnings.append("UNPARSED_ARCHIVE_MEMBER")
            return
        member.update(state=output["state"], structure=output["structure"], semantic=output["semantic"],
                      text_hash=output["text_hash"], warnings=output["warnings"], normalization=output["normalization"])
        warnings.extend(output["warnings"])
        parsed += output["state"] == "PARSED"
        if not output["markdown"]:
            return
        heading = "## " + display_name
        chunk = heading + "\n\n" + output["markdown"]
        if parts:
            offset += 2
        locator = ":".join(str(x["ordinal"]) for x in chain)
        sections.append(dict(section_no=len(sections)+1, locator_kind="archive_member", locator=locator,
                             kind="member_name", archive_member=display_name,
                             archive_chain=chain, start=offset, end=offset+len(heading),
                             content_hash=hashlib.sha256(heading.encode()).hexdigest()))
        base = offset + len(heading) + 2
        for section in output["sections"]:
            sections.append(section | {"section_no": len(sections)+1, "locator_kind": "archive_member_block",
                "locator": locator+":"+section["locator"], "archive_member": display_name,
                "archive_chain": chain, "member_raw_hash": member["raw_hash"],
                "start": base+section["start"], "end": base+section["end"]})
        blocks.extend(block | {"archive_member": display_name, "archive_chain": chain} for block in output["semantic"]["blocks"])
        parts.append(chunk)
        offset += len(chunk)

    with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory(prefix="members-") as directory:
        files = [entry for entry in archive.infolist() if not entry.is_dir()]
        if len(files) > 100:
            raise ValueError("ARCHIVE_MEMBER_COUNT_LIMIT")
        for ordinal, entry in enumerate(files, 1):
            record_document(archive, entry, [{"ordinal": ordinal}], directory)
    markdown = "\n\n".join(parts)
    return dict(state="PARSED" if parsed else "NO_TEXT", markdown=markdown,
                text_hash=hashlib.sha256(markdown.encode()).hexdigest(), sections=sections,
                structure={"format": "zip", "members": members}, semantic={"blocks": blocks},
                warnings=sorted(set(warnings)))


if __name__ == "__main__":
    main()
