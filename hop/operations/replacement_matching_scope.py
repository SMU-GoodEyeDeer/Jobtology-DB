"""Reviewed, fixed-cohort replacement matching admission (no provider I/O).

The independent channel ceilings sum to the combined ceiling. Native O*NET also
enforces its task ceiling; NCS batches receive at most their remaining channel
allocation under the supervisors' shared scheduler lock. Unknown charges retain
their conservative holds and prevent further dispatch.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

SOURCE_SHA = "4343f52738cce2eff0de13d6e9d1f98415db3384532d3a21ff0124ed8b55dfa6"
JOB_RUN = "jobkorea-ndjson-c5633b6d40809cc0b788bea454727dfd99850569f5f5b27ab15bc9426daef62f"
SCOPE = "jobkorea-replacement-20261103-4343f52738cc"
NCS_PREFIX = "jkr-20261103-ncs-"
ONET_TASK = "jkr-20261103-onet"
CAPS = {"ncs": Decimal("5"), "onet": Decimal("7")}
CAP = Decimal("12")
SHA = re.compile(r"[0-9a-f]{64}\Z")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}\Z")


def load(path: Path, expected_sha256: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or not SHA.fullmatch(expected_sha256 or ""):
        raise RuntimeError(
            "Replacement scope requires a regular reviewed manifest and exact SHA256"
        )
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise RuntimeError("Reviewed replacement scope manifest changed")
    value = json.loads(raw)
    fixed = {
        "contract_version": "jobkorea-replacement-matching-v1",
        "scope_id": SCOPE,
        "source_id": "jobkorea",
        "source_file_sha256": SOURCE_SHA,
        "posting_count": 5482,
        "job_run_id": JOB_RUN,
        "ncs_batch_prefix": NCS_PREFIX,
        "onet_task_id": ONET_TASK,
        "target_usd": "10",
        "ceiling_usd": "12",
        "ncs_ceiling_usd": "5",
        "onet_ceiling_usd": "7",
        "reuse_paid_responses": False,
        "pilot_count": 24,
    }
    if not isinstance(value, dict) or any(value.get(k) != v for k, v in fixed.items()):
        raise RuntimeError("Replacement manifest differs from the authorized fixed cohort/budget")
    for key in ("ncs_run_id", "onet_release_id", "onet_database_id"):
        if (
            not isinstance(value.get(key), str)
            or not ID.fullmatch(value[key])
            or value[key] == "LATEST"
        ):
            raise RuntimeError("Replacement manifest requires exact catalogue pins")
    for key in ("cohort_sha256", "onet_catalogue_file_sha256", "onet_catalogue_manifest_sha256"):
        if not isinstance(value.get(key), str) or not SHA.fullmatch(value[key]):
            raise RuntimeError("Replacement manifest requires exact cohort/catalogue hashes")
    if not isinstance(value.get("review_actor"), str) or not value["review_actor"].strip():
        raise RuntimeError("Replacement scope requires a recorded review actor")
    return value


def reference(path: Path, digest: str) -> dict[str, str]:
    load(path, digest)
    return {"path": str(path.resolve()), "sha256": digest}


def from_manifest(manifest: dict[str, Any]) -> dict[str, Any] | None:
    ref = manifest.get("replacement_scope")
    return load(Path(ref["path"]), ref["sha256"]) if ref else None


def state(
    pg: str, query: Callable[[str, str], str], scope: dict[str, Any] | None = None
) -> dict[str, Any]:
    # Fixed identities, allowlisted aggregates only. No source text, keys or URLs.
    result = json.loads(
        query(
            pg,
            f"""BEGIN READ ONLY;
SET LOCAL statement_timeout='30s';
SELECT jsonb_build_object(
 'reinference_gate_installed',to_regprocedure(
  'onet_matching.replacement_reinference_allowed(' ||
  'onet_matching.task,onet_matching.input,onet_matching.input)') IS NOT NULL,
 'policy_installed',to_regprocedure('replacement_matching.runtime()') IS NOT NULL,
 'pins',(SELECT jsonb_object_agg(source_id,run_id) FROM ingestion.latest_ready_run
  WHERE source_id IN('jobkorea','ncs_competency')),
 'source_count',(SELECT count(*) FROM ingestion.ready_record
  WHERE run_id='{JOB_RUN}' AND source_id='jobkorea'),
 'onet_catalogue',(SELECT jsonb_build_object('release_id',c.release_id,
  'database_id',c.database_id,'manifest_sha256',r.manifest_hash)
 FROM classification.catalog_current c JOIN classification.catalog_release r USING(release_id)
 WHERE c.scheme_id='ONET'),
 'ncs',(SELECT jsonb_build_object('accounted_usd',
 coalesce(sum(enrichment.accounted_cost(a.state,a.cost_usd,a.reserved_usd))
 FILTER(WHERE a.reserved_at IS NOT NULL),0)::text,
 'unknown',count(*) FILTER(WHERE a.reserved_at IS NOT NULL AND a.cost_usd IS NULL),
 'foreign_batches',count(*) FILTER(WHERE b.job_run_id IS DISTINCT FROM '{JOB_RUN}'
 OR b.settings->>'metadata_scope' IS DISTINCT FROM 'NCS_OCCUPATION_INFERENCE_V1'))
 FROM enrichment.batch b LEFT JOIN enrichment.attempt a USING(batch_id)
 WHERE left(b.batch_id,{len(NCS_PREFIX)})='{NCS_PREFIX}'),
 'onet',(SELECT jsonb_build_object('accounted_usd',
 coalesce(sum(coalesce(a.effective_cost_usd,a.reserve_usd))
 FILTER(WHERE a.reserved_at IS NOT NULL),0)::text,
 'unknown',count(*) FILTER(WHERE a.reserved_at IS NOT NULL AND a.effective_cost_usd IS NULL))
 FROM onet_matching.accounted_attempt a WHERE a.task_id='{ONET_TASK}'));
COMMIT;""",
        )
    )
    if result.get("policy_installed"):
        result["automated_policy"] = json.loads(query(pg,
            "BEGIN READ ONLY; SET LOCAL statement_timeout='30s'; "
            "SELECT replacement_matching.runtime(); COMMIT;"))
    if scope:
        if (
            result.get("pins")
            != {"jobkorea": scope["job_run_id"], "ncs_competency": scope["ncs_run_id"]}
            or result.get("source_count") != 5482
        ):
            raise RuntimeError("Replacement exact current source/NCS pins or cohort count changed")
        if result.get("onet_catalogue") != {
            "release_id": scope["onet_release_id"],
            "database_id": scope["onet_database_id"],
            "manifest_sha256": scope["onet_catalogue_manifest_sha256"],
        }:
            raise RuntimeError("Replacement exact current O*NET catalogue pin changed")
    return result


def require_policy(snapshot: dict[str, Any]) -> None:
    policy = snapshot.get("automated_policy") or {}
    if (policy.get("ready") is not True
        or policy.get("version") != "jobkorea-evidence-exclusion-v1"
        or policy.get("assessment_kind") != "AUTOMATED_POLICY"):
        raise RuntimeError("Qualified replacement policy SQL038 must be installed and ready")


def remaining(snapshot: dict[str, Any], channel: str) -> Decimal:
    if snapshot["ncs"].get("foreign_batches", 0):
        raise RuntimeError("Replacement accounting prefix is already bound to foreign inputs")
    if any(snapshot[name]["unknown"] for name in CAPS):
        raise RuntimeError("Unknown replacement provider charge requires reconciliation")
    spent = {name: Decimal(str(snapshot[name]["accounted_usd"])) for name in CAPS}
    if any(not v.is_finite() or v < 0 for v in spent.values()):
        raise RuntimeError("Invalid replacement accounting")
    if sum(spent.values()) > CAP or any(spent[k] > CAPS[k] for k in CAPS):
        raise RuntimeError("Replacement combined/channel accounting ceiling exceeded")
    return min(CAPS[channel] - spent[channel], CAP - sum(spent.values()))


def validate_rows(scope: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    if len(rows) != scope["posting_count"] or any(
        row.get("source_id") != "jobkorea" or row.get("source_run_id") != scope["job_run_id"]
        for row in rows
    ):
        raise RuntimeError("Replacement cohort must contain only the exact new JobKorea run")


def pilot_ids(rows: list[dict[str, Any]], eligible: list[str]) -> list[str]:
    allowed = set(eligible)
    ids = [r["posting_identity"] for r in rows if r["posting_identity"] in allowed]
    return sorted(
        ids,
        key=lambda item: (hashlib.sha256((SCOPE + ":pilot:" + item).encode()).hexdigest(), item),
    )[:24]


def ncs_scale_review(path: Path | None, digest: str | None, scope_sha: str) -> dict[str, str]:
    if path is None or path.is_symlink() or not path.is_file() or not SHA.fullmatch(digest or ""):
        raise RuntimeError(
            "Replacement NCS full execution requires a hash-bound independent pilot review"
        )
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise RuntimeError("Replacement NCS pilot review changed")
    value = json.loads(raw)
    if (
        value.get("scope_sha256") != scope_sha
        or value.get("decision") != "APPROVE_SCALE"
        or value.get("reviewed_postings") != 24
        or not isinstance(value.get("review_actor"), str)
        or not value["review_actor"].strip()
        or not isinstance(value.get("notes"), str)
        or not value["notes"].strip()
        or not isinstance(value.get("pilot_batch_ids"), list)
        or not value["pilot_batch_ids"]
        or any(
            not isinstance(batch, str)
            or not batch.startswith(NCS_PREFIX)
            or not ID.fullmatch(batch)
            for batch in value["pilot_batch_ids"]
        )
    ):
        raise RuntimeError(
            "Replacement NCS full execution requires an explicit 24-posting quality/cost review"
        )
    return {"path": str(path.resolve()), "sha256": digest}
