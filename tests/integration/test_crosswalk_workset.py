"""Actual 036/crosswalk + qualified 038 adapter in an owned isolated PG fixture."""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_crosswalk_pair_workset_actual_adapter_and_replay() -> None:
    host = os.environ.get("JOBTOLOGY_REPLACEMENT_TEST_SSH")
    if not host and os.environ.get("JOBTOLOGY_REPLACEMENT_TEST_DOCKER") != "1":
        pytest.skip("Opt in to an exclusively owned network-disabled PostgreSQL fixture")
    prefix = ["ssh", "-o", "BatchMode=yes", host] if host else []
    name = "jobkorea-crosswalk039-" + uuid.uuid4().hex

    def command(args: list[str], data: bytes | None = None):
        result = subprocess.run(prefix + ([shlex.join(args)] if host else args),
                                input=data, capture_output=True, timeout=90, check=False)
        if result.returncode:
            raise AssertionError(result.stderr.decode())
        return result

    command(["docker", "run", "--pull", "never", "--name", name, "--network", "none",
             "--cpus", "1", "--memory", "1g", "-e", "POSTGRES_HOST_AUTH_METHOD=trust",
             "-d", "postgres:18-alpine"])
    try:
        command(["docker", "exec", name, "sh", "-c",
                 "for i in $(seq 1 30); do pg_isready -U postgres >/dev/null && exit 0; "
                 "sleep 1; done; exit 1"])
        fixtures = ROOT / "tests/integration/fixtures"
        policy = (ROOT / "hop/llm/sql/038_replacement_policy.sql").read_bytes()
        sql = ROOT / "hop/ontology/sql"
        old = (sql / "036_crosswalk_reader_performance.sql").read_bytes()
        new = (sql / "039_crosswalk_pair_workset.sql").read_bytes()
        seed = ((fixtures / "replacement_policy.sql").read_bytes() + policy
                + (fixtures / "replacement_policy_assertions.sql").read_bytes()
                + (fixtures / "crosswalk_workset.sql").read_bytes()
                + (sql / "034_ncs_onet_crosswalk.sql").read_bytes() + old)
        snapshot = b"""
CREATE TEMP TABLE qualified_before AS SELECT replacement_matching.qualified_hashes() hashes,
 replacement_matching.definition_hash() definition;
CREATE TEMP TABLE json_before AS SELECT node,lim,off,
 catalog.ncs_onet_crosswalk_v1(node,lim,off) answer FROM
 unnest(ARRAY['ncs:occupation:20010701','urn:jobtology:onet:occupation:15-1253.00']) node
 CROSS JOIN unnest(ARRAY[6,100]) lim CROSS JOIN unnest(ARRAY[0,1]) off;
"""
        assertions = b"""
SELECT pg_temp.assert(replacement_matching.ready(),'ready after additive039');
SELECT pg_temp.assert((SELECT hashes=replacement_matching.qualified_hashes()
 AND definition=replacement_matching.definition_hash() FROM qualified_before),
 'all3qualified signatures and immutablev1 definition unchanged');
SELECT pg_temp.assert(NOT EXISTS(SELECT1 FROM json_before
 WHERE answer IS DISTINCT FROM catalog.ncs_onet_crosswalk_v1(node,lim,off)),
 'full public JSON exactly equal across both anchors/pagination');
""".replace(b"SELECT1", b"SELECT 1")
        data = (seed + snapshot + new + new + assertions + old + new + policy + new
                + assertions + (fixtures / "crosswalk_workset_assertions.sql").read_bytes())
        data += b"""
SELECT jsonb_build_object('qualified_hashes',replacement_matching.qualified_hashes(),
 'policy_definition_hash',replacement_matching.definition_hash(),'policy_ready',replacement_matching.ready(),
 'function_bindings',(SELECT jsonb_object_agg(p.oid::regprocedure::text,
 jsonb_build_object('sha256',encode(sha256(convert_to(pg_get_functiondef(p.oid),'UTF8')),'hex'),
 'definition',pg_get_functiondef(p.oid),'public_execute',EXISTS(SELECT 1 FROM
 aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
 WHERE a.grantee=0 AND a.privilege_type='EXECUTE')))
 FROM pg_proc p WHERE p.oid IN('catalog._crosswalk_pair_rows(text)'::regprocedure,
 'catalog._ncs_onet_shared_posting_proposals(text)'::regprocedure)));
"""
        result = command(["docker", "exec", "-i", name, "psql", "-X", "-qAt", "-v",
                          "ON_ERROR_STOP=1", "-U", "postgres"], data)
        assert b"CROSSWALK_WORKSET_ASSERTIONS_PASSED" in result.stdout
        destination = os.environ.get("JOBTOLOGY_CROSSWALK039_QUALIFICATION_DIR")
        if destination:
            directory = Path(destination)
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            bindings = next(value for line in result.stdout.decode().splitlines()
                            if line.startswith("{")
                            and "function_bindings" in (value := json.loads(line)))
            bindings["sql039_sha256"] = hashlib.sha256(new).hexdigest()
            path = directory / "fixture-function-bindings.json"
            path.write_text(json.dumps(bindings, indent=2) + "\n")
            path.chmod(0o600)
    finally:
        command(["docker", "rm", "-f", "-v", name])
