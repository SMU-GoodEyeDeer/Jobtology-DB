from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Annotated, Literal, Self, cast

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    ValidationError,
    model_validator,
)

SourceId = Literal[
    "ncs_competency",
    "ncs_qualification",
    "qnet_schedule",
    "ncs_career_path",
    "job_alio",
    "alio_organization",
    "saramin",
    "work24_training",
]
ActivationStatus = Literal["ALLOWED", "BLOCKED"]
PermissionStatus = Literal["PERMITTED", "PROHIBITED", "UNKNOWN"]
ContentKind = Literal[
    "api_json_body",
    "api_xml_body",
    "file_body",
    "attachment_metadata",
    "attachment_bytes",
]
ActivationPermissionName = Literal[
    "retrieval",
    "raw_retention",
    "normalized_fact_storage",
    "evidence_excerpt_storage_display",
    "model_processing",
]

NonEmptyStr = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1),
]
PolicyRevision = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^\d{4}-\d{2}-\d{2}\.\d+$"),
]
Sha256Hex = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$"),
]

SOURCE_ID_ORDER: tuple[SourceId, ...] = (
    "ncs_competency",
    "ncs_qualification",
    "qnet_schedule",
    "ncs_career_path",
    "job_alio",
    "alio_organization",
    "saramin",
    "work24_training",
)
CONTENT_KIND_ORDER: tuple[ContentKind, ...] = (
    "api_json_body",
    "api_xml_body",
    "file_body",
    "attachment_metadata",
    "attachment_bytes",
)
ACTIVATION_PERMISSION_NAMES: tuple[ActivationPermissionName, ...] = (
    "retrieval",
    "raw_retention",
    "normalized_fact_storage",
    "evidence_excerpt_storage_display",
    "model_processing",
)

DEFAULT_RIGHTS_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "source_rights.yaml"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ContentScope(_StrictModel):
    """Content categories to which a source policy applies."""

    api_json_body: bool
    api_xml_body: bool
    file_body: bool
    attachment_metadata: bool
    attachment_bytes: bool

    @model_validator(mode="after")
    def require_covered_content(self) -> Self:
        if not any(getattr(self, name) for name in CONTENT_KIND_ORDER):
            raise ValueError("content_scope must include at least one content kind")
        return self

    def permits(self, content_kind: ContentKind) -> bool:
        return cast(bool, getattr(self, content_kind))


class RightsPermissions(_StrictModel):
    retrieval: PermissionStatus
    commercial_use: PermissionStatus
    derivative_use: PermissionStatus
    raw_retention: PermissionStatus
    normalized_fact_storage: PermissionStatus
    evidence_excerpt_storage_display: PermissionStatus
    model_processing: PermissionStatus
    redistribution: PermissionStatus

    def activation_blockers(self) -> tuple[ActivationPermissionName, ...]:
        return tuple(
            permission_name
            for permission_name in ACTIVATION_PERMISSION_NAMES
            if getattr(self, permission_name) != "PERMITTED"
        )


class SourceRightsPolicy(_StrictModel):
    source_id: SourceId
    policy_version: int = Field(ge=1)
    source_owner: NonEmptyStr
    dataset_id: NonEmptyStr
    dataset_url: HttpUrl
    license_code: NonEmptyStr
    license_url: HttpUrl
    observed_on: date
    rights_basis: NonEmptyStr
    attribution_text: NonEmptyStr
    required_source_link: HttpUrl | None
    content_scope: ContentScope
    scope_note: NonEmptyStr
    permissions: RightsPermissions
    written_permission_required: bool
    written_permission_reference: NonEmptyStr | None
    deletion_correction_contact: NonEmptyStr
    deletion_correction_procedure: NonEmptyStr
    backup_retention_days: int = Field(ge=0)
    activation_status: ActivationStatus
    blocking_reason: NonEmptyStr | None

    @model_validator(mode="after")
    def validate_activation_status(self) -> Self:
        blockers = self.permissions.activation_blockers()
        expected_status: ActivationStatus = "BLOCKED" if blockers else "ALLOWED"
        if self.activation_status != expected_status:
            raise ValueError(
                f"activation_status must be {expected_status} for permissions {blockers!r}"
            )
        if self.activation_status == "BLOCKED" and self.blocking_reason is None:
            raise ValueError("a blocked source requires blocking_reason")
        if self.activation_status == "ALLOWED" and self.blocking_reason is not None:
            raise ValueError("an allowed source cannot have blocking_reason")

        if self.permissions.raw_retention == "PERMITTED":
            if self.backup_retention_days < 1:
                raise ValueError("permitted raw retention requires positive backup_retention_days")
        elif self.backup_retention_days != 0:
            raise ValueError("backup_retention_days must be zero unless raw retention is permitted")

        if (
            self.activation_status == "ALLOWED"
            and self.written_permission_required
            and self.written_permission_reference is None
        ):
            raise ValueError("allowed source requiring written permission needs its reference")
        return self


class SourcePolicies(_StrictModel):
    ncs_competency: SourceRightsPolicy
    ncs_qualification: SourceRightsPolicy
    qnet_schedule: SourceRightsPolicy
    ncs_career_path: SourceRightsPolicy
    job_alio: SourceRightsPolicy
    alio_organization: SourceRightsPolicy
    saramin: SourceRightsPolicy
    work24_training: SourceRightsPolicy

    @model_validator(mode="after")
    def validate_source_keys_and_job_alio_scope(self) -> Self:
        for source_id in SOURCE_ID_ORDER:
            policy = cast(SourceRightsPolicy, getattr(self, source_id))
            if policy.source_id != source_id:
                raise ValueError(
                    f"source policy key {source_id!r} does not match {policy.source_id!r}"
                )

        job_scope = self.job_alio.content_scope
        if not (
            job_scope.api_json_body
            and job_scope.attachment_metadata
            and not job_scope.api_xml_body
            and not job_scope.file_body
            and not job_scope.attachment_bytes
        ):
            raise ValueError(
                "job_alio must cover only API JSON and attachment metadata; attachment bytes "
                "are excluded"
            )
        return self

    def policy_for(self, source_id: SourceId) -> SourceRightsPolicy:
        return cast(SourceRightsPolicy, getattr(self, source_id))


class SourceActivationCheck(_StrictModel):
    source_id: SourceId
    status: ActivationStatus
    allowed: bool
    policy_version: int = Field(ge=1)
    registry_revision: PolicyRevision
    policy_hash: Sha256Hex
    requested_content: tuple[ContentKind, ...]
    out_of_scope_content: tuple[ContentKind, ...]
    blocking_permissions: tuple[ActivationPermissionName, ...]
    reason: NonEmptyStr | None

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.allowed != (self.status == "ALLOWED"):
            raise ValueError("allowed must agree with status")
        if self.allowed and (
            self.out_of_scope_content or self.blocking_permissions or self.reason is not None
        ):
            raise ValueError("an allowed activation check cannot contain blockers")
        if not self.allowed and self.reason is None:
            raise ValueError("a blocked activation check requires a reason")
        return self


class SourceRightsRegistry(_StrictModel):
    schema_version: Literal[1]
    policy_revision: PolicyRevision
    reviewed_on: date
    sources: SourcePolicies

    @model_validator(mode="after")
    def validate_registry_dates(self) -> Self:
        expected_prefix = f"{self.reviewed_on.isoformat()}."
        if not self.policy_revision.startswith(expected_prefix):
            raise ValueError("policy_revision date must match reviewed_on")
        for source_id in SOURCE_ID_ORDER:
            policy = self.sources.policy_for(source_id)
            if policy.observed_on > self.reviewed_on:
                raise ValueError(f"{source_id} observed_on cannot follow registry reviewed_on")
        return self

    @property
    def policy_hash(self) -> str:
        """SHA-256 of the validated registry's canonical semantic JSON."""

        canonical = json.dumps(
            self.model_dump(mode="json", exclude_none=False),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def policy_for(self, source_id: str) -> SourceRightsPolicy:
        typed_source_id = _source_id(source_id)
        return self.sources.policy_for(typed_source_id)

    def check_activation(
        self,
        source_id: str,
        *,
        required_content: Iterable[ContentKind] = (),
    ) -> SourceActivationCheck:
        typed_source_id = _source_id(source_id)
        requested_content = _content_kinds(required_content)
        policy = self.sources.policy_for(typed_source_id)
        blocking_permissions = policy.permissions.activation_blockers()
        out_of_scope_items: list[ContentKind] = []
        for content_kind in requested_content:
            if not policy.content_scope.permits(content_kind):
                out_of_scope_items.append(content_kind)
        out_of_scope = tuple(out_of_scope_items)
        allowed = policy.activation_status == "ALLOWED" and not out_of_scope

        reasons: list[str] = []
        if policy.blocking_reason is not None:
            reasons.append(policy.blocking_reason)
        if out_of_scope:
            reasons.append(f"content outside policy scope: {', '.join(out_of_scope)}")
        reason = "; ".join(reasons) or None

        return SourceActivationCheck(
            source_id=typed_source_id,
            status="ALLOWED" if allowed else "BLOCKED",
            allowed=allowed,
            policy_version=policy.policy_version,
            registry_revision=self.policy_revision,
            policy_hash=self.policy_hash,
            requested_content=requested_content,
            out_of_scope_content=out_of_scope,
            blocking_permissions=blocking_permissions,
            reason=reason,
        )

    def require_activation(
        self,
        source_id: str,
        *,
        required_content: Iterable[ContentKind] = (),
    ) -> SourceActivationCheck:
        check = self.check_activation(source_id, required_content=required_content)
        if not check.allowed:
            raise SourceRightsBlockedError(check)
        return check


class RightsRegistryLoadError(ValueError):
    pass


class UnknownSourceRightsError(KeyError):
    pass


class SourceRightsBlockedError(RuntimeError):
    def __init__(self, check: SourceActivationCheck) -> None:
        self.check = check
        super().__init__(f"source {check.source_id} is blocked: {check.reason}")


def load_source_rights_registry(
    path: str | Path = DEFAULT_RIGHTS_REGISTRY_PATH,
) -> SourceRightsRegistry:
    registry_path = Path(path)
    try:
        document: object = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        return SourceRightsRegistry.model_validate(document, strict=True)
    except (OSError, UnicodeError, yaml.YAMLError, ValidationError) as error:
        raise RightsRegistryLoadError(
            f"invalid source rights registry at {registry_path}: {error}"
        ) from error


def _source_id(value: str) -> SourceId:
    if value not in SOURCE_ID_ORDER:
        raise UnknownSourceRightsError(f"no rights policy for source {value!r}")
    return value


def _content_kinds(values: Iterable[ContentKind]) -> tuple[ContentKind, ...]:
    if isinstance(values, str):
        candidates: tuple[str, ...] = (values,)
    else:
        candidates = tuple(values)
    unknown = sorted(set(candidates).difference(CONTENT_KIND_ORDER))
    if unknown:
        raise ValueError(f"unknown content kinds: {', '.join(unknown)}")
    requested = set(candidates)
    return tuple(kind for kind in CONTENT_KIND_ORDER if kind in requested)
