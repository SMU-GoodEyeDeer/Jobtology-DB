"""Backend-owned private graph projection. Never a public ingestion entity."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from jobtology_db.contracts.documents import Identifier
from jobtology_db.contracts.processing import Contract


class PersonCapability(Contract):
    target_kind: Literal["Skill", "Credential"]
    target_id: Identifier


class PersonProjection(Contract):
    schema_version: Literal["person-projection-v1"] = "person-projection-v1"
    person_id: UUID
    # Monotonic app outbox sequence; the backend must reject stale updates.
    projection_version: Annotated[int, Field(ge=1)]
    target_occupation_id: Identifier | None = None
    capabilities: list[PersonCapability] = Field(default_factory=list[PersonCapability])

    @model_validator(mode="after")
    def unique_capabilities(self) -> Self:
        keys = [(c.target_kind, c.target_id) for c in self.capabilities]
        if len(set(keys)) != len(keys):
            raise ValueError("DUPLICATE_PERSON_CAPABILITY")
        return self
