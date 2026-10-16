#!/usr/bin/env python3
"""Compare complete typed readers on one explicitly released archived clone.

Use existing analyzed statistics, unchanged sixty-second statement bounds and
one persistent backend. Never restore an archive, access production, request
source content, or make graph/model calls. Full results and plans stay private.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from benchmark_first_capture import statistic_identity
from profile_archived_postgres import Session, plan_summary, quote, write_json

ROOT = Path(__file__).resolve().parents[2]
RUNS = (
    "9419ffbf-0102-4a44-8c3b-ee28685f1a35",
    "18cb0086-5800-4a2b-870f-db8d74c62fbf",
    "4a9262a3-aee6-47b9-ad90-6ed8e4c6b2c1",
    "jobkorea-ndjson-83bdacb6f319187632a8f1b3228a94d49429966443a41a423e8ca2da7e0c5a4c",
)
READERS = (
    "graph_source_entities",
    "graph_source_edges",
    "graph_source_edge_owners",
    "graph_posting_ingestion_dates",
)


def run(container: str, directory: Path) -> Path:
    os.umask(0o077)
    inspected = json.loads(
        subprocess.run(
            ["docker", "inspect", container, "--format", "{{json .}}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    if (
        not re.fullmatch(r"jobtology-routine-archive-nara-[0-9a-f]+", container)
        or inspected["HostConfig"]["NetworkMode"] != "none"
        or set(inspected["NetworkSettings"]["Networks"]) != {"none"}
    ):
        raise ValueError("Use the explicitly leased network-none archived clone")
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    spec = importlib.util.spec_from_file_location(
        "reader_generator", ROOT / "hop/graph/tools/build_reader_worksets.py"
    )
    assert spec and spec.loader
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    expected = generator.build()
    if generator.OUTPUT.read_text() != expected:
        raise ValueError("Generated reader candidate differs from sealed source")
    frozen = directory / "launched-reader.sql"
    frozen.write_text(expected)
    frozen.chmod(0o400)
    shutil.copyfile(Path(__file__), directory / "launched-helper.py")
    receipt = dict(
        status="RUNNING",
        container=container,
        container_id=inspected["Id"],
        created_at=datetime.now(UTC).isoformat(),
        statement_timeout_seconds=60,
        source_requests=0,
        paid_requests=0,
        production_writes=0,
        candidate_sha256=hashlib.sha256(frozen.read_bytes()).hexdigest(),
        samples=[],
        candidate_plans={},
        limits=[
            "Ordered full-query diagnostics, not balanced SQL performance evidence.",
            "Candidate EXPLAIN instrumentation excludes PL/pgSQL preconditions.",
            "All historical candidates/validity assessments remain in scope.",
        ],
    )
    path = directory / "receipt.json"
    session = Session(container, directory, 60)
    try:
        session.execute(
            "SET jit=off; SET max_parallel_workers_per_gather=0; "
            "SET plan_cache_mode=force_generic_plan;"
        )
        receipt["statistics_before"] = statistic_identity(session)
        source = generator.SOURCE.read_text()
        originals = [generator.definition(source, name) for name in generator.NAMES]
        session.execute("\n".join(originals))
        snapshots = {}
        for variant in ("baseline", "candidate"):
            if variant == "candidate":
                session.execute(frozen.read_text())
            for index, jobs in enumerate(RUNS):
                for reader in READERS:
                    query = (
                        "SELECT coalesce(jsonb_agg(to_jsonb(v) ORDER BY to_jsonb(v)::text),'[]') "
                        "FROM ingestion." + reader + "(" + quote(jobs) + ") v"
                    )
                    started = time.monotonic()
                    raw = session.execute(query)
                    wall = time.monotonic() - started
                    value = json.loads(raw)
                    out = directory / f"{variant}-{index}-{reader}.json"
                    out.write_text(raw + "\n")
                    sample = dict(
                        variant=variant,
                        run_id=jobs,
                        reader=reader,
                        wall_seconds=wall,
                        rows=len(value),
                        result_sha256=hashlib.sha256(out.read_bytes()).hexdigest(),
                    )
                    receipt["samples"].append(sample)
                    key = (jobs, reader)
                    if variant == "baseline":
                        snapshots[key] = (value, sample["result_sha256"])
                    elif (value, sample["result_sha256"]) != snapshots[key]:
                        raise RuntimeError("Exact typed full reader bag differs: " + reader)
                    write_json(path, receipt)
                    print(json.dumps(sample), flush=True)
        for reader in generator.NAMES:
            candidate = generator.candidate(source, reader)
            query = candidate.split("RETURN QUERY\n", 1)[1].rsplit(";\nEND $$;", 1)[0]
            prepared = "reader_" + reader
            session.execute("PREPARE " + prepared + "(text) AS " + re.sub(r"\bjobs\b", "$1", query))
            plan = json.loads(
                session.execute(
                    "EXPLAIN(ANALYZE,BUFFERS,TIMING OFF,FORMAT JSON) EXECUTE "
                    + prepared
                    + "("
                    + quote(RUNS[0])
                    + ")"
                )
            )[0]
            write_json(directory / (reader + "-candidate-plan.json"), plan)
            receipt["candidate_plans"][reader] = plan_summary(plan)
        receipt["statistics_after"] = statistic_identity(session)
        if receipt["statistics_before"] != receipt["statistics_after"]:
            raise RuntimeError("Analyzed statistics changed")
        receipt.update(status="PASSED", exact_typed_reader_bags=True, fixed_statistics=True)
    except BaseException as exc:
        receipt.update(status="FAILED", failure_type=type(exc).__name__)
        raise
    finally:
        session.close()
        receipt["finished_at"] = datetime.now(UTC).isoformat()
        write_json(path, receipt)
        print(path, flush=True)
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    run(args.container, args.directory)
