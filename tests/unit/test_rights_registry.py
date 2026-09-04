from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from jobtology_db.connectors.sources import SOURCE_IDS
from jobtology_db.rights import (
    SOURCE_ID_ORDER,
    ContentScope,
    RightsRegistryLoadError,
    SourcePolicies,
    SourceRightsBlockedError,
    SourceRightsPolicy,
    SourceRightsRegistry,
    UnknownSourceRightsError,
    load_source_rights_registry,
)

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "source_rights.yaml"
DATA_GO_SOURCE_IDS = (
    "ncs_competency",
    "ncs_qualification",
    "qnet_schedule",
    "ncs_career_path",
    "job_alio",
    "alio_organization",
)


@pytest.fixture
def registry() -> SourceRightsRegistry:
    return load_source_rights_registry(REGISTRY_PATH)


def test_checked_in_registry_has_exactly_all_external_sources(
    registry: SourceRightsRegistry,
) -> None:
    assert SOURCE_ID_ORDER == SOURCE_IDS
    assert tuple(SourcePolicies.model_fields) == SOURCE_ID_ORDER
    assert registry.schema_version == 1
    assert registry.policy_revision == "2026-09-05.1"

    for source_id in SOURCE_ID_ORDER:
        assert registry.policy_for(source_id).source_id == source_id


def test_data_go_api_and_file_body_policies_are_allowed(
    registry: SourceRightsRegistry,
) -> None:
    for source_id in DATA_GO_SOURCE_IDS:
        policy = registry.policy_for(source_id)
        check = registry.require_activation(source_id)

        assert policy.license_code == "DATA_GO_KR_NO_RESTRICTION"
        assert policy.permissions.activation_blockers() == ()
        assert policy.backup_retention_days > 0
        assert check.allowed is True
        assert check.policy_hash == registry.policy_hash


def test_saramin_and_work24_are_blocked_on_unresolved_written_permissions(
    registry: SourceRightsRegistry,
) -> None:
    expected_blockers = (
        "raw_retention",
        "normalized_fact_storage",
        "evidence_excerpt_storage_display",
        "model_processing",
    )
    for source_id in ("saramin", "work24_training"):
        policy = registry.policy_for(source_id)
        check = registry.check_activation(source_id)

        assert policy.written_permission_required is True
        assert policy.written_permission_reference is None
        assert policy.backup_retention_days == 0
        assert check.allowed is False
        assert check.blocking_permissions == expected_blockers
        with pytest.raises(SourceRightsBlockedError) as raised:
            registry.require_activation(source_id)
        assert raised.value.check == check


def test_job_alio_allows_api_json_and_metadata_but_blocks_attachment_bytes(
    registry: SourceRightsRegistry,
) -> None:
    policy = registry.policy_for("job_alio")

    assert policy.content_scope.api_json_body is True
    assert policy.content_scope.attachment_metadata is True
    assert policy.content_scope.attachment_bytes is False
    assert registry.require_activation(
        "job_alio",
        required_content=("api_json_body", "attachment_metadata"),
    ).allowed

    check = registry.check_activation(
        "job_alio",
        required_content=("attachment_bytes",),
    )
    assert check.allowed is False
    assert check.out_of_scope_content == ("attachment_bytes",)
    with pytest.raises(SourceRightsBlockedError, match="attachment_bytes"):
        registry.require_activation(
            "job_alio",
            required_content=("attachment_bytes",),
        )


def test_job_alio_scope_cannot_be_widened_to_attachment_bytes(
    registry: SourceRightsRegistry,
) -> None:
    bad_scope = ContentScope(
        api_json_body=True,
        api_xml_body=False,
        file_body=False,
        attachment_metadata=True,
        attachment_bytes=True,
    )
    bad_job_policy = registry.sources.job_alio.model_copy(update={"content_scope": bad_scope})

    with pytest.raises(ValidationError, match="attachment bytes"):
        SourcePolicies(
            ncs_competency=registry.sources.ncs_competency,
            ncs_qualification=registry.sources.ncs_qualification,
            qnet_schedule=registry.sources.qnet_schedule,
            ncs_career_path=registry.sources.ncs_career_path,
            job_alio=bad_job_policy,
            alio_organization=registry.sources.alio_organization,
            saramin=registry.sources.saramin,
            work24_training=registry.sources.work24_training,
        )


def test_policy_hash_is_deterministic_and_changes_with_policy(
    registry: SourceRightsRegistry,
) -> None:
    same_policy = SourceRightsRegistry.model_validate(
        registry.model_dump(mode="python", exclude_none=False),
        strict=True,
    )
    changed_policy = registry.model_copy(update={"policy_revision": "2026-09-05.2"})

    assert len(registry.policy_hash) == 64
    assert same_policy.policy_hash == registry.policy_hash
    assert changed_policy.policy_hash != registry.policy_hash


def test_policy_models_reject_extra_fields_and_inconsistent_activation(
    registry: SourceRightsRegistry,
) -> None:
    registry_document: dict[str, object] = registry.model_dump(mode="python")
    registry_document["unexpected"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SourceRightsRegistry.model_validate(registry_document, strict=True)

    blocked_policy_document: dict[str, object] = registry.sources.saramin.model_dump(mode="python")
    blocked_policy_document["activation_status"] = "ALLOWED"
    blocked_policy_document["blocking_reason"] = None
    with pytest.raises(ValidationError, match="activation_status must be BLOCKED"):
        SourceRightsPolicy.model_validate(blocked_policy_document, strict=True)


def test_unknown_source_and_malformed_registry_fail_closed(
    registry: SourceRightsRegistry,
    tmp_path: Path,
) -> None:
    with pytest.raises(UnknownSourceRightsError):
        registry.check_activation("not_a_source")

    malformed = tmp_path / "source_rights.yaml"
    malformed.write_text("schema_version: 1\nunexpected: true\n", encoding="utf-8")
    with pytest.raises(RightsRegistryLoadError):
        load_source_rights_registry(malformed)
