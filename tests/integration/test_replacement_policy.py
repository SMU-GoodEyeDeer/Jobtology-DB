"""Opt-in actual PostgreSQL proof; exclusively owned network-disabled fixture."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import uuid
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_replacement_policy_ledger_publication_and_serving_filters() -> None:
    host = os.environ.get("JOBTOLOGY_REPLACEMENT_TEST_SSH")
    if not host and os.environ.get("JOBTOLOGY_REPLACEMENT_TEST_DOCKER") != "1":
        pytest.skip("Opt in to a disposable network-disabled PostgreSQL")
    prefix = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host] if host else []
    name = "jobkorea-policy-test-" + uuid.uuid4().hex

    def command(args: list[str], data: bytes | None = None):
        result = subprocess.run(
            prefix + ([shlex.join(args)] if host else args),
            input=data,
            capture_output=True,
            timeout=90,
            check=False,
        )
        if result.returncode:
            raise AssertionError(
                "\n".join(
                    line
                    for line in result.stderr.decode().splitlines()
                    if line.startswith(("ERROR:", "DETAIL:", "HINT:"))
                )
            )
        return result

    command(
        [
            "docker",
            "run",
            "--pull",
            "never",
            "--name",
            name,
            "--network",
            "none",
            "--cpus",
            "1",
            "--memory",
            "1g",
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "-d",
            "postgres:18-alpine",
        ]
    )
    try:
        command(
            [
                "docker",
                "exec",
                name,
                "sh",
                "-c",
                "for i in $(seq 1 30); do pg_isready -U postgres >/dev/null && exit 0; "
                "sleep 1; done; exit 1",
            ]
        )
        fixtures = ROOT / "tests/integration/fixtures"
        migration = (ROOT / "hop/llm/sql/038_replacement_policy.sql").read_bytes()
        # Optional canonical replay is a no-op before either matcher exists.
        command(["docker", "exec", "-i", name, "psql", "-X", "-qAt", "-v",
                 "ON_ERROR_STOP=1", "-U", "postgres"], migration)
        data = (
            (fixtures / "replacement_policy.sql").read_bytes()
            + migration
            + migration
            + (fixtures / "replacement_policy_assertions.sql").read_bytes()
            + (fixtures / "replacement_policy_replay_assertions.sql").read_bytes()
        )
        if os.environ.get("JOBTOLOGY_POLICY_BENCHMARK") == "1":
            data += (fixtures / "replacement_policy_performance.sql").read_bytes()
        cases_path = os.environ.get("JOBTOLOGY_POLICY_CASES")
        cases = json.loads(Path(cases_path).read_bytes()) if cases_path else []
        for number, case in enumerate(cases):

            def literal(value):
                return "'" + json.dumps(value, ensure_ascii=False).replace("'", "''") + "'::jsonb"

            query = (
                "SELECT jsonb_build_object('case_index',"
                + str(number)
                + ",'issues',replacement_matching.issues('"
                + case["scheme"]
                + "',"
                + literal(case["fields"])
                + ","
                + literal(case["output"])
                + ","
                + ("1" if case["scheme"] == "NCS" else "3")
                + "));\n"
            )
            data += query.encode()
        result = command(
            [
                "docker",
                "exec",
                "-i",
                name,
                "psql",
                "-X",
                "-qAt",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "postgres",
            ],
            data,
        )
        assert b"REPLACEMENT_POLICY_SQL_PASSED" in result.stdout
        benchmarks = [
            json.loads(line)
            for line in result.stdout.splitlines()
            if line.startswith(b"{") and b'"benchmark"' in line
        ]
        if benchmarks:
            Path(
                os.environ.get(
                    "JOBTOLOGY_POLICY_BENCHMARK_RECEIPT", "/tmp/replacement-policy-benchmark.json"
                )
            ).write_text(json.dumps(benchmarks, indent=2) + "\n")
        if cases:
            evaluated = [
                json.loads(line)
                for line in result.stdout.splitlines()
                if line.startswith(b"{") and b'"case_index"' in line
            ]
            assert len(evaluated) == len(cases)
            counts = Counter()
            records = []
            for row in evaluated:
                case = cases[row["case_index"]]
                blocked = bool(row["issues"])
                decisions = case["decisions"]
                if any(x["decision"] == "REJECT" for x in decisions):
                    assert blocked, "Known unsupported inference escaped: " + case["native_id"]
                for decision in decisions:
                    if decision["decision"] not in ("ACCEPT", "REJECT"):
                        continue
                    key = (
                        case["scheme"],
                        case["phase"],
                        decision["decision"],
                        "BLOCKED" if blocked else "ALLOWED",
                    )
                    counts[key] += 1
                records.append(
                    {
                        "native_id": case["native_id"],
                        "scheme": case["scheme"],
                        "phase": case["phase"],
                        "issues": row["issues"],
                        "decisions": decisions,
                    }
                )
            report = {
                "counts": [
                    {"scheme": k[0], "phase": k[1], "review": k[2], "policy": k[3], "count": n}
                    for k, n in counts.items()
                ],
                "cases": records,
            }
            Path(cases_path).with_name("policy-regression-coverage.json").write_text(
                json.dumps(report, indent=2) + "\n"
            )
    finally:
        command(["docker", "rm", "-f", "-v", name])
