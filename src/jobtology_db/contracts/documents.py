"""Source-neutral parsed documents and exact, independently verifiable text evidence."""

from __future__ import annotations

import hashlib
import unicodedata
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from jobtology_db.contracts.processing import Contract, digest

SCHEMA_VERSION = "canonical-v1"
Identifier = Annotated[str, Field(min_length=1, max_length=512, pattern=r"^\S+$")]
NonEmpty = Annotated[str, Field(min_length=1)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TextBlock(Contract):
    block_id: Identifier
    # JSON pointer, CSV logical-record/column, HTML selector, or PDF page from the adapter.
    locator: NonEmpty
    text: NonEmpty
    sha256: Sha256
    normalization_version: Literal["nfc-lf-v1"] = "nfc-lf-v1"

    @model_validator(mode="after")
    def verify_text(self) -> Self:
        normalized = unicodedata.normalize(
            "NFC", self.text.replace("\r\n", "\n").replace("\r", "\n")
        )
        if normalized != self.text or text_hash(self.text) != self.sha256:
            raise ValueError("TEXT_ARTIFACT_INTEGRITY_FAILED")
        return self


class SourceDocument(Contract):
    schema_version: Literal["canonical-v1"] = SCHEMA_VERSION
    document_id: Sha256
    source_id: Identifier
    source_record_id: Identifier
    snapshot_id: Identifier
    parser_version: Identifier
    record_locator: NonEmpty
    # Retrieval time, source URL, MIME, raw hash/path and rights are in the fetch ledger.
    # Observation membership is stored separately: the same document can be fetched again.
    blocks: Annotated[list[TextBlock], Field(min_length=1)]

    @model_validator(mode="after")
    def verify_identity(self) -> Self:
        if len({b.block_id for b in self.blocks}) != len(self.blocks):
            raise ValueError("DUPLICATE_TEXT_BLOCK")
        if self.document_id != digest(self.model_dump(mode="json", exclude={"document_id"})):
            raise ValueError("DOCUMENT_ID_MISMATCH")
        return self


class EvidenceSpan(Contract):
    evidence_id: Sha256
    document_id: Sha256
    block_id: Identifier
    artifact_sha256: Sha256
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    excerpt: NonEmpty
    excerpt_sha256: Sha256

    @model_validator(mode="after")
    def verify_shape(self) -> Self:
        if self.end <= self.start or self.end - self.start != len(self.excerpt):
            raise ValueError("INVALID_SPAN_LENGTH")
        if text_hash(self.excerpt) != self.excerpt_sha256:
            raise ValueError("EXCERPT_HASH_MISMATCH")
        if self.evidence_id != digest(self.model_dump(mode="json", exclude={"evidence_id"})):
            raise ValueError("EVIDENCE_ID_MISMATCH")
        return self

    def verify_document(self, document: SourceDocument) -> None:
        blocks = {b.block_id: b for b in document.blocks}
        block = blocks.get(self.block_id)
        if (
            document.document_id != self.document_id
            or block is None
            or block.sha256 != self.artifact_sha256
            or self.end > len(block.text)
            or block.text[self.start : self.end] != self.excerpt
        ):
            raise ValueError("EVIDENCE_SPAN_NOT_IN_DOCUMENT")
