"""Freeze every exact READY local JobKorea input, with bounded resumable commits.

Uses only docker-exec/psql and the deterministic input-bundle function. It does
not invoke a linking workflow, create extraction attempts, read keys or call APIs.
Keep the checkpoint directory outside the repository; it contains private IDs.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

Json = dict[str, Any]
POSTING = re.compile(r"ext-jobkorea-[0-9a-f]{64}\Z")
CONTRACT = "jobkorea-full-input-preparation-v1"
MAX_LINE_BYTES = 16 * 1024 * 1024


def quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def encoded(value: Json) -> bytes:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (text + "\n").encode()


def atomic_json(path: Path, value: Json, *, immutable: bool = False) -> None:
    payload = encoded(value)
    if path.is_symlink():
        raise RuntimeError("Checkpoint symlinks are forbidden")
    if immutable and path.exists():
        if path.read_bytes() != payload:
            raise RuntimeError("Immutable batch checkpoint changed")
        return
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())
    if immutable:
        os.link(temporary, path)
        temporary.unlink()
    else:
        os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def local_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Provenance requires regular local files without symlinks")


def file_identity(path: Path) -> tuple[str, int]:
    local_file(path)
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def bounded_json(path: Path, bound: int) -> Json:
    local_file(path)
    if not 0 < path.stat().st_size <= bound:
        raise RuntimeError("Provenance metadata exceeds its local bound")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise RuntimeError("Provenance metadata must be a JSON object")
    return cast(Json, value)


def verify_provenance(directory: Path) -> Json:
    """Verify hash bindings and row alignment locally before any registration."""
    if directory.is_symlink() or not directory.is_dir():
        raise RuntimeError("Provenance requires a local archive directory without symlinks")
    provenance = bounded_json(directory / "provenance.json", 16384)
    if (
        provenance.get("contract") != "jobkorea-dataset-provenance-v1"
        or provenance.get("row_key") != "composed_line"
    ):
        raise RuntimeError("Unknown dataset provenance contract")
    for filename, prefix in (
        ("snapshot.ndjson", "snapshot"),
        ("occurrences.ndjson", "occurrences"),
        ("composition.json", "descriptor"),
    ):
        if file_identity(directory / filename) != (
            provenance.get(prefix + "_sha256"),
            provenance.get(prefix + "_byte_length"),
        ):
            raise RuntimeError("Local provenance hash/length mismatch: " + filename)
    if provenance.get("archive_relative_root") != (
        "jobkorea/datasets/" + str(provenance.get("descriptor_sha256"))
    ):
        raise RuntimeError("Provenance archive locator does not match its descriptor hash")
    descriptor = bounded_json(directory / "composition.json", 16 * 1024 * 1024)
    if (
        descriptor.get("contract") != "jobkorea-composed-dataset-v1"
        or descriptor.get("row_key") != "composed_line"
        or descriptor.get("selected_count") != provenance.get("selected_count")
    ):
        raise RuntimeError("Composition selected count/contract differs from provenance")
    for field in ("snapshot", "occurrences"):
        if descriptor.get(field) != dict(
            sha256=provenance[field + "_sha256"], byte_length=provenance[field + "_byte_length"]
        ):
            raise RuntimeError("Composition file identity differs from provenance")
    originals = directory / "originals"
    if originals.is_symlink() or not originals.is_dir():
        raise RuntimeError("Archived original exports are required")
    inventory: dict[str, Json] = {}
    for item in descriptor["source_inventory"]:
        name = item["file"]
        if not isinstance(name, str) or name != Path(name).name or name in inventory:
            raise RuntimeError("Invalid or repeated archived original filename")
        if file_identity(originals / name) != (item["sha256"], item["bytes"]):
            raise RuntimeError("Archived original hash/length mismatch")
        inventory[name] = item
    count, offset = 0, 0
    with (
        (directory / "snapshot.ndjson").open("rb") as snapshot,
        (directory / "occurrences.ndjson").open("rb") as occurrences,
    ):
        while raw := snapshot.readline(MAX_LINE_BYTES + 1):
            occurrence_raw = occurrences.readline(MAX_LINE_BYTES + 1)
            if (
                len(raw) > MAX_LINE_BYTES
                or not raw.endswith(b"\n")
                or len(occurrence_raw) > MAX_LINE_BYTES
                or not occurrence_raw.endswith(b"\n")
            ):
                raise RuntimeError("Invalid bounded snapshot/occurrence framing")
            mapping = json.loads(occurrence_raw)
            count += 1
            line_hash = hashlib.sha256(raw).hexdigest()
            if (
                mapping["composed_line"] != count
                or mapping["composed_byte_offset"] != offset
                or mapping["composed_byte_length"] != len(raw)
                or mapping["composed_line_sha256"] != line_hash
            ):
                raise RuntimeError("Occurrence map does not bind the exact composed physical line")
            selected = mapping["selected_original"]
            for origin in [selected, *mapping["alternative_occurrences"]]:
                item = inventory.get(origin["file"])
                if (
                    item is None
                    or origin["file_sha256"] != item["sha256"]
                    or not 0 <= origin["byte_offset"] < item["bytes"]
                    or not 0 < origin["byte_length"] <= MAX_LINE_BYTES
                    or origin["byte_offset"] + origin["byte_length"] > item["bytes"]
                    or origin["line"] < 1
                ):
                    raise RuntimeError("Occurrence original-file binding is invalid")
                with (originals / origin["file"]).open("rb") as original:
                    original.seek(origin["byte_offset"])
                    evidence = original.read(origin["byte_length"])
                if hashlib.sha256(evidence).hexdigest() != origin["line_sha256"]:
                    raise RuntimeError("Occurrence original byte range changed")
                if origin is selected and evidence != raw:
                    raise RuntimeError("The selected original line differs from the composed line")
            offset += len(raw)
        if occurrences.read(1) or count != provenance["selected_count"]:
            raise RuntimeError("Snapshot/occurrence selected count differs from provenance")
    return provenance


def register_provenance(sql: Callable[[str], Json], jobs: str, directory: Path) -> Json:
    provenance = verify_provenance(directory)
    literal = quoted(json.dumps(provenance, ensure_ascii=False)) + "::jsonb"
    sql(f"""/* full-input:register-provenance */
WITH registration AS MATERIALIZED (
 SELECT ingestion.register_jobkorea_dataset_provenance({quoted(jobs)},{literal}))
SELECT jsonb_build_object('registered',true) FROM registration;
""")
    return provenance


class Database:
    def __init__(self, container: str, database: str, work: Path) -> None:
        self.container, self.database, self.work = container, database, work

    def __call__(self, statement: str) -> Json:
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                self.container,
                "psql",
                "-X",
                "-qAt",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "postgres",
                "-d",
                self.database,
            ],
            input=statement,
            text=True,
            capture_output=True,
            check=False,
            timeout=1800,
        )
        if result.returncode:
            error = self.work / "last-database-error.log"
            error.write_text(result.stderr)
            error.chmod(0o600)
            raise RuntimeError("Database operation failed; protected diagnostic: " + str(error))
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise RuntimeError("Database response must be a JSON object")
        return cast(Json, value)


class Preparation:
    def __init__(
        self,
        sql: Callable[[str], Json],
        jobs: str,
        work: Path,
        batch_size: int = 250,
        *,
        require_provenance: bool = False,
        target: str = "",
    ) -> None:
        if not jobs or jobs == "LATEST" or not 1 <= batch_size <= 1000:
            raise ValueError("An exact run and batch size between 1 and 1000 are required")
        self.sql, self.jobs, self.work = sql, jobs, work
        self.batch_size = batch_size
        self.require_provenance, self.target = require_provenance, target

    def snapshot(self) -> Json:
        # Full READY validation occurs once before and once after preparation.
        # Each individual bundle still validates its immutable selected evidence.
        return self.sql(f"""/* full-input:snapshot */
DO $$ BEGIN PERFORM enrichment.assert_snapshot({quoted(self.jobs)},'jobkorea'); END $$;
SELECT jsonb_build_object('job_run_id',i.run_id,'file_sha256',i.file_sha256,
 'byte_length',i.byte_length,'row_manifest_sha256',i.row_manifest_sha256,
 'parser_version',i.parser_version,'policy_revision',i.policy_revision,
 'postings',(SELECT count(*) FROM ingestion.record r
  WHERE r.run_id=i.run_id AND r.document_id='local-json'),
 'dataset_provenance',(SELECT provenance FROM ingestion.jobkorea_dataset_provenance p
  WHERE p.run_id=i.run_id))
 FROM ingestion.jobkorea_import i JOIN ingestion.run u USING(run_id)
 WHERE i.run_id={quoted(self.jobs)} AND u.state='READY' AND u.mode='REPLAY'
 AND u.source_id='jobkorea' AND i.loaded AND i.error_code IS NULL;
""")

    def counters(self) -> Json:
        return self.sql("""/* full-input:counters */
SELECT jsonb_build_object(
 'batches',(SELECT count(*) FROM enrichment.batch),
 'items',(SELECT count(*) FROM enrichment.item),
 'attempts',(SELECT count(*) FROM enrichment.attempt),
 'reservations',(SELECT count(*) FROM enrichment.attempt WHERE reserved_at IS NOT NULL),
 'reserved_usd',(SELECT coalesce(sum(reserved_usd),0)::text FROM enrichment.attempt),
 'cost_usd',(SELECT coalesce(sum(cost_usd),0)::text FROM enrichment.attempt),
 'datasets',(SELECT count(*) FROM enrichment.dataset),
 'extraction_decisions',(SELECT count(*) FROM enrichment.extraction_decision),
 'link_decisions',(SELECT count(*) FROM enrichment.link_decision),
 'publications',(SELECT count(*) FROM enrichment.link_publication),
 'source_requests',(SELECT count(*) FROM ingestion.request_attempt));
""")

    def selection(self, cursor: str) -> list[str]:
        result = self.sql(f"""/* full-input:selection */
SELECT jsonb_build_object('posting_ids',
 coalesce(jsonb_agg(posting_id ORDER BY posting_id),'[]'::jsonb))
 FROM (SELECT 'ext-jobkorea-'||enrichment.hash(source_record_id) AS posting_id
  FROM ingestion.record WHERE run_id={quoted(self.jobs)} AND document_id='local-json'
  AND 'ext-jobkorea-'||enrichment.hash(source_record_id)>{quoted(cursor)}
  ORDER BY 'ext-jobkorea-'||enrichment.hash(source_record_id) LIMIT {self.batch_size}) selected;
""")
        ids = result["posting_ids"]
        if not isinstance(ids, list):
            raise RuntimeError("Invalid selected posting identities")
        ids = cast(list[Any], ids)
        if any(not isinstance(p, str) or not POSTING.fullmatch(p) for p in ids):
            raise RuntimeError("Invalid selected posting identities")
        if ids != sorted(set(ids)) or len(ids) > self.batch_size or any(p <= cursor for p in ids):
            raise RuntimeError("Non-monotonic bounded posting selection")
        return ids

    def prepare(self, ids: list[str]) -> Json:
        # The large validation view is deliberately not rescanned for each batch.
        # This is the same per-posting function used by explicit input preparation.
        values = ",".join("(" + quoted(p) + ")" for p in ids)
        return self.sql(f"""/* full-input:prepare */
WITH prepared AS MATERIALIZED (
 SELECT posting_id,
 enrichment.prepare_jobkorea_input_bundle({quoted(self.jobs)},posting_id) AS bundle_id
 FROM (VALUES {values}) AS selected(posting_id) ORDER BY posting_id)
SELECT jsonb_build_object('posting_ids',jsonb_agg(posting_id ORDER BY posting_id),
 'bundle_ids',jsonb_agg(bundle_id ORDER BY posting_id)) FROM prepared;
""")

    def coverage(self) -> Json:
        return self.sql(f"""/* full-input:coverage */
WITH source AS (SELECT 'ext-jobkorea-'||enrichment.hash(source_record_id) AS posting_id
 FROM ingestion.record WHERE run_id={quoted(self.jobs)} AND document_id='local-json'),
bundles AS (SELECT posting_id,bundle_id FROM enrichment.input_bundle
 WHERE job_run_id={quoted(self.jobs)} AND manifest->>'contract'='jobkorea-input-v1')
SELECT jsonb_build_object('source_postings',(SELECT count(*) FROM source),
 'prepared_postings',(SELECT count(DISTINCT posting_id) FROM bundles),
 'bundles',(SELECT count(*) FROM bundles),
 'missing',(SELECT count(*) FROM source s
  WHERE NOT EXISTS(SELECT 1 FROM bundles b WHERE b.posting_id=s.posting_id)),
 'extra',(SELECT count(*) FROM bundles b
  WHERE NOT EXISTS(SELECT 1 FROM source s WHERE s.posting_id=b.posting_id)),
 'missing_dataset_provenance',(SELECT count(*) FROM enrichment.input_bundle b
 WHERE b.job_run_id={quoted(self.jobs)} AND b.manifest->>'contract'='jobkorea-input-v1'
 AND b.manifest->'dataset_provenance' IS DISTINCT FROM
 (SELECT provenance FROM ingestion.jobkorea_dataset_provenance p
  WHERE p.run_id={quoted(self.jobs)})));
""")

    def run(self, *, max_batches: int | None = None) -> Json:
        self.work.mkdir(parents=True, mode=0o700, exist_ok=True)
        if self.work.is_symlink() or self.work.stat().st_mode & 0o077:
            raise RuntimeError("Use a private non-symlink checkpoint directory (mode 0700)")
        with (self.work / "lock").open("a") as lock:
            os.chmod(lock.name, 0o600)
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return self._run(max_batches=max_batches)

    def _run(self, *, max_batches: int | None) -> Json:
        identity = self.snapshot()
        if self.require_provenance and not identity.get("dataset_provenance"):
            raise RuntimeError("Register the archived dataset provenance before preparing inputs")
        if identity["postings"] <= 0:
            raise RuntimeError("The exact snapshot contains no local postings")
        state_file = self.work / "checkpoint.json"
        if state_file.is_symlink():
            raise RuntimeError("Checkpoint symlinks are forbidden")
        state: Json
        if state_file.exists():
            state = json.loads(state_file.read_text())
            expected = (CONTRACT, self.batch_size, self.target, identity)
            actual = (state["contract"], state["batch_size"], state["target"], state["snapshot"])
            if actual != expected:
                raise RuntimeError("Resume checkpoint snapshot, target or batch size changed")
        else:
            state = dict(
                contract=CONTRACT,
                status="RUNNING",
                batch_size=self.batch_size,
                target=self.target,
                snapshot=identity,
                before=self.counters(),
                batches=0,
                prepared=0,
                cursor="",
            )
            atomic_json(state_file, state)
        # Only bounded identities/hashes enter immutable batch receipts.
        total = 0
        cursor = ""
        proof = hashlib.sha256()
        for number in range(1, state["batches"] + 1):
            path = self.work / f"batch-{number:06d}.json"
            payload = path.read_bytes()
            batch = json.loads(payload)
            if batch["number"] != number or batch["job_run_id"] != self.jobs:
                raise RuntimeError("Invalid committed batch receipt")
            ids, bundles = batch["posting_ids"], batch["bundle_ids"]
            if not ids or ids != sorted(set(ids)) or ids[0] <= cursor or len(ids) != len(bundles):
                raise RuntimeError("Invalid committed batch identity sequence")
            total += len(ids)
            cursor = ids[-1]
            proof.update(payload)
        if total != state["prepared"] or cursor != state["cursor"]:
            raise RuntimeError("Checkpoint does not match immutable batch receipts")
        committed_now = 0
        while ids := self.selection(state["cursor"]):
            result = self.prepare(ids)
            bundles = result.get("bundle_ids")
            if result.get("posting_ids") != ids or not isinstance(bundles, list):
                raise RuntimeError("Input preparation did not acknowledge the exact selected batch")
            bundles = cast(list[Any], bundles)
            if len(bundles) != len(ids):
                raise RuntimeError("Input preparation did not acknowledge the exact selected batch")
            if any(not isinstance(b, str) or not re.fullmatch(r"[0-9a-f]{64}", b) for b in bundles):
                raise RuntimeError("Invalid frozen bundle identity")
            batch: Json = dict(
                number=state["batches"] + 1,
                job_run_id=self.jobs,
                posting_ids=ids,
                bundle_ids=bundles,
            )
            path = self.work / f"batch-{batch['number']:06d}.json"
            atomic_json(path, batch, immutable=True)
            proof.update(encoded(batch))
            state.update(
                batches=batch["number"], prepared=state["prepared"] + len(ids), cursor=ids[-1]
            )
            atomic_json(state_file, state)
            print(
                json.dumps(
                    dict(
                        batches=state["batches"],
                        prepared=state["prepared"],
                        total=identity["postings"],
                    )
                ),
                flush=True,
            )
            committed_now += 1
            if max_batches is not None and committed_now >= max_batches:
                return state
        coverage = self.coverage()
        if self.snapshot() != identity:
            raise RuntimeError("Exact source identity changed during preparation")
        after = self.counters()
        if after != state["before"]:
            raise RuntimeError("Requests, attempts, accounting or review counters changed")
        count = identity["postings"]
        if (
            state["prepared"] != count
            or coverage["source_postings"] != count
            or coverage["prepared_postings"] != count
            or coverage["bundles"] != count
            or any(coverage[k] for k in ("missing", "extra", "missing_dataset_provenance"))
        ):
            raise RuntimeError("Full prepared input coverage failed")
        state.update(
            status="VERIFIED",
            after=after,
            coverage=coverage,
            batch_manifest_sha256=proof.hexdigest(),
            verified_at=datetime.now(UTC).isoformat(),
            no_model_calls=True,
            no_key_reads=True,
            no_llm_parse=True,
            no_semantic_links=True,
        )
        atomic_json(state_file, state)
        atomic_json(self.work / "receipt.json", state)
        return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-container", required=True)
    parser.add_argument("--database", default="jobtology")
    parser.add_argument("--job-run-id", required=True)
    parser.add_argument("--checkpoint-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--require-dataset-provenance", action="store_true")
    parser.add_argument("--register-provenance-dir", type=Path)
    args = parser.parse_args()
    args.checkpoint_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    runner = Database(args.postgres_container, args.database, args.checkpoint_dir)
    if args.register_provenance_dir is not None:
        register_provenance(runner, args.job_run_id, args.register_provenance_dir)
    result = Preparation(
        runner,
        args.job_run_id,
        args.checkpoint_dir,
        args.batch_size,
        require_provenance=args.require_dataset_provenance,
        target=args.postgres_container + "/" + args.database,
    ).run()
    print(
        json.dumps(
            dict(
                status=result["status"],
                postings=result["prepared"],
                receipt=str(args.checkpoint_dir / "receipt.json"),
            )
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
