"""Qualify only exact raw/Hop guard installation forms in a schema-only database."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
COMMENTS = (
    " -- Transition tables can span runs. Fence each exact run before constructing",
    " -- live proof, rather than rebuilding whole history for every inserted slice.",
    " -- Compare the complete batch: EXISTS startup plans repeatedly scan genuine",
    " -- rows. bool_or preserves rejection when any exact row differs or is absent.",
)
NEW_COMMENTS = (
    *COMMENTS[:2],
    " -- Group complete inserted/live rows by the original SQL equality keys.",
    " -- Every live duplicate must match; NULL keys remain unmatched.",
)


def definition(source: str) -> str:
    start = source.index("CREATE OR REPLACE FUNCTION ingestion.source_graph_insert_guard()")
    return source[start:source.index("END $$;", start) + len("END $$;")]


def body(source: str) -> str:
    return source.split("AS $$", 1)[1].rsplit("$$;", 1)[0]


def exact_hop(source: str, comments: tuple[str, ...]) -> str:
    # Independent finite fixture transformation, not installed-body normalization.
    for comment in comments:
        assert source.count(comment + "\n") == 1
        source = source.replace(comment + "\n", " \n")
    return source


def run(container: str, directory: Path, semantic_launch: Path) -> Path:
    os.umask(0o077)
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    spec = importlib.util.spec_from_file_location(
        "compatibility_oracle", ROOT / "hop/graph/tests/source_queries_native.py"
    )
    assert spec and spec.loader
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    inspected = json.loads(subprocess.run(
        ["docker", "inspect", container, "--format", "{{json .}}"],
        text=True, capture_output=True, check=True,
    ).stdout)
    if not container.startswith("jobtology-routine-archive-nara-") or (
        inspected["HostConfig"]["NetworkMode"] != "none"
        or set(inspected["NetworkSettings"]["Networks"]) != {"none"}
    ):
        raise ValueError("Use only the explicitly leased network-none archived clone")
    oracle = native.Oracle(container, directory)
    migration = (ROOT / "hop/graph/sql/007_capture_guard_worksets.sql").read_text()
    old = definition((ROOT / "hop/graph/sql/002_batchfree_source_graph.sql").read_text())
    new = definition(migration)
    qualified = semantic_launch / "hop/graph/sql/007_capture_guard_worksets.sql"
    prior = definition(qualified.read_text())
    assert new == prior, "Compatibility revision changed the qualified function definition"
    forms = {"raw-old": old, "raw-new": new,
             "hop-old": exact_hop(old, COMMENTS), "hop-new": exact_hop(new, NEW_COMMENTS)}
    assert hashlib.md5(body(forms["hop-old"]).encode()).hexdigest() == (
        "6a7657e4685d2741814d77453466eeab"
    )
    receipt = dict(
        status="RUNNING", created_at=datetime.now(UTC).isoformat(), container=container,
        container_id=inspected["Id"], database=oracle.database, checks=oracle.checks,
        sql007_sha256=hashlib.sha256(migration.encode()).hexdigest(),
        qualified_definition_unchanged=True,
        qualified_definition_sha256=hashlib.sha256(new.encode()).hexdigest(),
        form_md5={name: hashlib.md5(body(value).encode()).hexdigest()
                  for name, value in forms.items()},
        source_requests=0, paid_calls=0, production_writes=0,
    )
    path = directory / "receipt.json"
    created = False
    try:
        schema = subprocess.run([
            "docker", "exec", container, "pg_dump", "-s", "--no-owner", "--no-privileges",
            "-U", "postgres", "-d", "jobtology",
        ], capture_output=True, check=True).stdout
        (directory / "schema.sql").write_bytes(schema)
        oracle.sql('CREATE DATABASE "' + oracle.database + '"', database="postgres")
        created = True
        oracle.sql(schema.decode())
        metadata = (
            "SELECT (to_jsonb(p)-'prosrc')::text FROM pg_proc p WHERE "
            "p.oid='ingestion.source_graph_insert_guard()'::regprocedure"
        )
        before = oracle.sql(metadata)
        for name, value in forms.items():
            oracle.sql(value + migration)
            oracle.check("exact-install-form-" + name, oracle.sql(metadata) == before)
        oracle.sql(migration)
        oracle.check("exact-candidate-reinstall", oracle.sql(metadata) == before)
        for name, drift in (
            ("hop-blank-line-trim", forms["hop-old"].replace(" \n", "\n", 1)),
            ("different-comment", old.replace(COMMENTS[0], " -- unapproved comment")),
            ("partial-comment-removal", old.replace(COMMENTS[0] + "\n", " \n")),
            ("different-return", forms["hop-new"].replace("RETURN NULL", "RETURN NEW")),
        ):
            oracle.sql("BEGIN;" + drift + migration,
                       failure="SOURCE_GRAPH_CAPTURE_WORKSET_BASELINE_DRIFT")
            oracle.check("unapproved-body-refused-" + name, True)
        for name in forms:
            oracle.sql("BEGIN;" + forms[name] +
                       "ALTER FUNCTION ingestion.source_graph_insert_guard() COST 99;" + migration,
                       failure="SOURCE_GRAPH_CAPTURE_WORKSET_BASELINE_DRIFT")
            oracle.check("cost-drift-refused-" + name, True)
        receipt["status"] = "PASSED"
    except BaseException as exc:
        receipt.update(status="FAILED", failure_type=type(exc).__name__)
        raise
    finally:
        if created:
            oracle.sql('DROP DATABASE "' + oracle.database + '" WITH(FORCE)', database="postgres")
            receipt["database_removed"] = True
        receipt["finished_at"] = datetime.now(UTC).isoformat()
        path.write_text(json.dumps(receipt, indent=2) + "\n")
        print(path, flush=True)
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--semantic-launch", type=Path, required=True)
    args = parser.parse_args()
    run(args.container, args.directory, args.semantic_launch)
