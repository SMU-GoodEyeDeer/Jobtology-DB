"""Opt-in PostgreSQL proof on an exclusively owned network-disabled container.

JOBTOLOGY_REPLACEMENT_TEST_SSH=maxjo@goldship selects Docker on that host;
JOBTOLOGY_REPLACEMENT_TEST_DOCKER=1 selects local Docker. Never uses an existing DB.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).with_name("fixtures")


def test_replacement_current_cohort_publication_and_preservation() -> None:
    host = os.environ.get("JOBTOLOGY_REPLACEMENT_TEST_SSH")
    if not host and os.environ.get("JOBTOLOGY_REPLACEMENT_TEST_DOCKER") != "1":
        pytest.skip("Opt in to an exclusively owned disposable Docker PostgreSQL fixture")
    prefix = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host] if host else []
    name = "jobkorea-replacement-sql037-test-" + uuid.uuid4().hex

    def command(args: list[str], data: bytes | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            prefix + ([shlex.join(args)] if host else args), input=data,
            capture_output=True, check=True, timeout=90,
        )

    command(["docker", "run", "--pull", "never", "--name", name, "--network", "none",
             "--cpus", "1", "--memory", "1g", "-e", "POSTGRES_HOST_AUTH_METHOD=trust",
             "-d", "postgres:18-alpine"])
    try:
        # pg_isready can race bootstrap; the shell's bounded loop executes only
        # inside our named, network-disabled disposable container.
        wait_ready = (
            "for i in $(seq 1 30); do pg_isready -U postgres >/dev/null && exit 0; "
            "sleep 1; done; exit 1"
        )
        command(["docker", "exec", name, "sh", "-c", wait_ready])
        fixture = (FIXTURES / "jobkorea_replacement.sql").read_bytes()
        migration = (ROOT / "hop/ontology/sql/037_jobkorea_replacement.sql").read_bytes()
        assertions = (FIXTURES / "jobkorea_replacement_assertions.sql").read_bytes()
        modern = (FIXTURES / "jobkorea_replacement_modern_ncs.sql").read_bytes()
        result = command(["docker", "exec", "-i", name, "psql", "-X", "-qAt", "-v",
                          "ON_ERROR_STOP=1", "-U", "postgres"],
                         fixture + migration + migration + assertions + modern)
        assert b"JOBKOREA_REPLACEMENT_SQL037_PASSED" in result.stdout
        assert b"JOBKOREA_REPLACEMENT_MODERN_NCS_PASSED" in result.stdout
    finally:
        command(["docker", "rm", "-f", "-v", name])
