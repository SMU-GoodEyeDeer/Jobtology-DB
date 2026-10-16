"""Focused catalogue/lifecycle contracts in an owned network-disabled PostgreSQL.

The small fixture installs the actual retention gate/writer function bodies with
minimal retention tables. The independent native suite qualifies the full stack.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
ONET = ROOT / "hop/ingestions/onet"


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class Fixture:
    def __init__(self) -> None:
        self.container = "jobtology-onet-core-" + uuid.uuid4().hex[:12]
        self.checks: list[str] = []

    def command(self, args: list[str], *, input: str | None = None) -> str:
        result = subprocess.run(args, input=input, text=True, capture_output=True, check=False)
        if result.returncode:
            raise RuntimeError(result.stderr[-8000:])
        return result.stdout.strip()

    def sql(self, statement: str) -> str:
        return self.command(
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
                "catalogtest",
            ],
            input=statement,
        )

    def boot(self) -> None:
        self.command(
            [
                "docker",
                "run",
                "-d",
                "--network",
                "none",
                "--name",
                self.container,
                "-e",
                "POSTGRES_HOST_AUTH_METHOD=trust",
                "-e",
                "POSTGRES_DB=catalogtest",
                "postgres:18-alpine",
            ]
        )
        for _ in range(100):
            ready = subprocess.run(
                [
                    "docker",
                    "exec",
                    self.container,
                    "pg_isready",
                    "-h",
                    "127.0.0.1",
                    "-U",
                    "postgres",
                    "-d",
                    "catalogtest",
                ],
                capture_output=True,
                check=False,
            )
            if ready.returncode == 0:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("Owned PostgreSQL did not become ready")
        self.sql("""
CREATE SCHEMA retention;
CREATE TABLE retention.plan(plan_id text PRIMARY KEY,state text NOT NULL,owner_id text);
CREATE TABLE retention.writer(writer_id text PRIMARY KEY,kind text NOT NULL,target_id text NOT NULL,
 started_at timestamptz NOT NULL DEFAULT clock_timestamp());
""")
        canonical = (ROOT / "hop/retention/sql/001_retention.sql").read_text()
        for name in ("gate", "freeze_writes", "enter_writer", "leave_writer"):
            body = re.search(
                rf"CREATE OR REPLACE FUNCTION retention\.{name}\(.*?\$\$;",
                canonical,
                re.DOTALL,
            )
            if body is None:
                raise RuntimeError("Canonical retention function missing: " + name)
            self.sql(body.group())
        for path in sorted((ONET / "sql").glob("*.sql")):
            self.sql(path.read_text())

    def expect(self, condition: bool, name: str) -> None:
        if not condition:
            raise AssertionError(name)
        self.checks.append(name)

    def error(self, statement: str, code: str) -> None:
        try:
            self.sql(statement)
        except RuntimeError as error:
            self.expect(code in str(error), code)
        else:
            raise AssertionError("Expected rejection: " + code)

    def import_payload(self, payload: dict) -> str:
        return self.sql(
            "SELECT classification.import_onet_catalog("
            + quote(json.dumps(payload, ensure_ascii=False))
            + "::jsonb)"
        )

    def digest(self, release_id: str) -> str:
        return self.sql(
            "SELECT classification.hash(jsonb_build_object("
            "'release',(SELECT to_jsonb(r) FROM classification.catalog_release r WHERE release_id="
            + quote(release_id)
            + "),"
            "'sources',(SELECT jsonb_agg(f ORDER BY file_id) "
            "FROM classification.source_file f WHERE release_id="
            + quote(release_id)
            + "),"
            "'terms',(SELECT jsonb_agg(t ORDER BY term_id) "
            "FROM classification.term t WHERE release_id="
            + quote(release_id)
            + "),"
            "'hierarchy',(SELECT jsonb_agg(h ORDER BY child_id,parent_id) "
            "FROM classification.hierarchy h WHERE release_id="
            + quote(release_id)
            + ")))"
        )

    def cleanup(self) -> None:
        subprocess.run(["docker", "rm", "-fv", self.container], capture_output=True, check=False)
        absent = subprocess.run(
            ["docker", "inspect", self.container], capture_output=True, check=False
        )
        if absent.returncode == 0:
            raise RuntimeError("Owned PostgreSQL cleanup failed")


def small_payload() -> dict:
    version = "31.0"
    uris = {
        "occupation_data": "https://www.onetcenter.org/dl_files/database/db_31_0_json/occupation_data.json",
        "taxonomy": "https://www.onetcenter.org/ctdl/graph/ce-8350d6ad-bc2a-11ef-8f5a-005056bdd76e",
        "soc_structure": "https://www.onetcenter.org/taxonomy/2019/structure/SOC_Structure.csv?fmt=csv",
    }
    paths = {
        "occupation_data": "occupation_data.json",
        "taxonomy": "taxonomy.jsonld",
        "soc_structure": "soc_structure.csv",
    }
    terms = []
    for level, code, label in [
        (1, "11-0000", "Management Occupations"),
        (2, "11-1000", "Top Executives"),
        (3, "11-1010", "Chief Executives"),
        (4, "11-1011.00", "Chief Executives"),
        (5, "11-1011.03", "Chief Sustainability Officers"),
    ]:
        kind = "GROUP" if level < 4 else "OCCUPATION"
        term_id = "urn:jobtology:onet:" + ("group:" if kind == "GROUP" else "occupation:") + code
        terms.append(
            {
                "term_id": term_id,
                "code": code,
                "term_kind": kind,
                "preferred_label": label,
                "description": None if kind == "GROUP" else "Supplied source description.",
                "source_uri": "https://example.org/official-source-term/" + code,
                "file_id": "soc_structure" if kind == "GROUP" else "occupation_data",
                "source_locator": "/" + str(level),
                "source_attributes": {"hierarchy_level": level, "language": "en-US"},
            }
        )
    hierarchy = [
        {
            "child_id": terms[index]["term_id"],
            "parent_id": terms[index - 1]["term_id"],
            "file_id": "soc_structure",
            "source_locator": "/" + str(index + 1),
            "source_uri": uris["soc_structure"],
            "source_attributes": {"basis": "SOURCE_HIERARCHY"},
        }
        for index in range(1, len(terms))
    ]
    return {
        "contract_version": "jobtology-onet-catalog-v1",
        "release_id": "fixture-onet-31.0",
        "scheme_id": "ONET",
        "source_version": version,
        "taxonomy_version": "O*NET-SOC2019",
        "sources": [
            {
                "file_id": file_id,
                "source_uri": uri,
                "archive_path": "sources/" + paths[file_id],
                "sha256": "a" * 64,
                "byte_length": 1,
                "encoding": "UTF-8",
                "downloaded_at": "2026-10-14T04:00:00Z",
            }
            for file_id, uri in uris.items()
        ],
        "terms": terms,
        "hierarchy": hierarchy,
    }


def check(fixture: Fixture, official: Path | None = None) -> None:
    payload = small_payload()
    release = payload["release_id"]
    fixture.expect(fixture.import_payload(payload) == release, "atomic-import-ready")
    baseline = fixture.digest(release)
    fixture.expect(
        fixture.sql("SELECT count(*) FROM classification.current_term") == "0", "ready-not-current"
    )
    fixture.expect(
        fixture.import_payload(payload) == release and fixture.digest(release) == baseline,
        "idempotent-replay",
    )
    fixture.sql(
        "SET timezone='Asia/Seoul'; SELECT classification.assert_catalog(" + quote(release) + ")"
    )
    fixture.expect(True, "timezone-independent-inventory")
    changed = copy.deepcopy(payload)
    changed["terms"][-1]["preferred_label"] = "Altered label"
    fixture.error(
        "SELECT classification.import_onet_catalog(" + quote(json.dumps(changed)) + "::jsonb)",
        "ONET_RELEASE_REPLAY_CHANGED",
    )
    fixture.error(
        "UPDATE classification.term SET preferred_label='overwrite'",
        "IMMUTABLE_ONET_CATALOG_RECORD",
    )
    fixture.error("DELETE FROM classification.source_file", "IMMUTABLE_ONET_CATALOG_RECORD")
    fixture.error("TRUNCATE classification.hierarchy", "IMMUTABLE_ONET_CATALOG_RECORD")
    for name, mutate, code in [
        ("unknown", lambda p: p.update(extra=True), "ONET_INVALID_PAYLOAD"),
        (
            "foreign",
            lambda p: p["terms"][-1].update(term_id="urn:jobtology:occupation:ncs:11010101"),
            "ONET_INVALID_TERM",
        ),
        (
            "pin",
            lambda p: p["sources"][0].update(
                source_uri="https://www.onetcenter.org/unrelated.json"
            ),
            "ONET_SOURCE_VERSION_PIN_MISMATCH",
        ),
        (
            "path",
            lambda p: p["sources"][0].update(archive_path="sources/../occupation_data.json"),
            "ONET_INVALID_SOURCE_FILE",
        ),
        (
            "language",
            lambda p: p["terms"][-1]["source_attributes"].update(language="ko"),
            "ONET_INVALID_TERM",
        ),
        (
            "level",
            lambda p: p["terms"][-1]["source_attributes"].update(hierarchy_level=4),
            "ONET_INVALID_HIERARCHY_KIND",
        ),
        ("orphan", lambda p: p["hierarchy"].pop(), "ONET_OCCUPATION_PARENT_MISSING"),
    ]:
        invalid = copy.deepcopy(payload)
        invalid["release_id"] = "invalid-" + name
        mutate(invalid)
        fixture.error(
            "SELECT classification.import_onet_catalog(" + quote(json.dumps(invalid)) + "::jsonb)",
            code,
        )
        fixture.expect(
            fixture.sql(
                "SELECT count(*) FROM classification.catalog_release WHERE release_id="
                + quote(invalid["release_id"])
            )
            == "0",
            "invalid-import-atomic-" + name,
        )
    fixture.sql(
        "SELECT classification.begin_graph_load(" + quote(release) + ",'fixture-db','first')"
    )
    context = json.loads(
        fixture.sql("SELECT to_jsonb(c) FROM classification.graph_load_context('first') c")
    )
    fixture.expect(
        context["expected_nodes"] == 6 and context["expected_edges"] == 9, "flat-exact-plan"
    )
    fixture.expect(
        fixture.sql("SELECT count(*) FROM retention.writer") == "1", "scoped-writer-present"
    )
    fixture.error(
        "SELECT classification.activate_catalog(" + quote(release) + ",'fixture-db','first')",
        "ONET_VERIFIED_CURRENT_GRAPH_REQUIRED",
    )
    fixture.error(
        "SELECT classification.finish_graph_load('first',6,9,false)",
        "ONET_GRAPH_VERIFICATION_FAILED",
    )
    fixture.error(
        "SELECT classification.finish_graph_load('first',7,9,true)",
        "ONET_GRAPH_VERIFICATION_FAILED",
    )
    fixture.sql(
        "SELECT classification.finish_graph_load('first',6,9,true); "
        "SELECT classification.activate_catalog("
        + quote(release)
        + ",'fixture-db','first')"
    )
    fixture.expect(
        fixture.sql("SELECT count(*) FROM classification.current_term") == "5",
        "activation-current-view",
    )
    fixture.expect(
        fixture.sql("SELECT count(*) FROM retention.writer") == "0", "scoped-writer-cleaned"
    )
    fixture.sql(
        "SELECT classification.activate_catalog(" + quote(release) + ",'fixture-db','first')"
    )
    fixture.expect(
        fixture.sql("SELECT count(*) FROM classification.activation_event") == "1",
        "activation-replay-no-extra-event",
    )
    rollover = copy.deepcopy(payload)
    rollover["release_id"] = "fixture-onet-31.1"
    rollover["source_version"] = "31.1"
    rollover["sources"][0]["source_uri"] = rollover["sources"][0]["source_uri"].replace(
        "db_31_0", "db_31_1"
    )
    rollover["terms"].pop()
    rollover["hierarchy"].pop()
    fixture.import_payload(rollover)
    fixture.sql("SELECT classification.begin_graph_load('fixture-onet-31.1','fixture-db','second')")
    context = json.loads(
        fixture.sql("SELECT to_jsonb(c) FROM classification.graph_load_context('second') c")
    )
    fixture.expect(
        context["expected_nodes"] == 6
        and context["expected_edges"] == 9
        and context["current_nodes"] == 5
        and context["current_edges"] == 7,
        "rollover-retirement-inventory",
    )
    fixture.expect(
        fixture.sql(
            "SELECT count(*) FROM classification.graph_load_nodes('second') "
            "WHERE properties->'current'='false'::jsonb "
            "AND previous_properties->'current'='true'::jsonb"
        )
        == "1",
        "retirement-preserves-previous-proof",
    )
    fixture.sql(
        "SELECT classification.finish_graph_load('second',6,9,true); "
        "SELECT classification.activate_catalog('fixture-onet-31.1','fixture-db','second')"
    )
    fixture.expect(fixture.digest(release) == baseline, "historical-import-bytes-preserved")
    fixture.error(
        "SELECT classification.activate_catalog(" + quote(release) + ",'fixture-db','first')",
        "ONET_VERIFIED_CURRENT_GRAPH_REQUIRED",
    )
    fixture.error(
        "SELECT classification.begin_graph_load(" + quote(release) + ",'fixture-db','stale')",
        "ONET_STALE_RELEASE_REPLAY",
    )
    fixture.sql(
        "SELECT classification.begin_graph_load('fixture-onet-31.1','fixture-db','failure'); "
        "SELECT classification.fail_graph_load('failure')"
    )
    fixture.expect(
        fixture.sql("SELECT count(*) FROM retention.writer") == "0", "failed-writer-cleaned"
    )
    fixture.expect(
        fixture.sql(
            "SELECT load_id FROM classification.graph_target WHERE database_id='fixture-db'"
        )
        == "second",
        "failure-preserves-target",
    )
    for path in sorted((ONET / "sql").glob("*.sql")):
        fixture.sql(path.read_text())
    fixture.expect(fixture.digest(release) == baseline, "installer-replay-preserves-evidence")
    if official is not None:
        real = json.loads(official.read_text())
        started = time.monotonic()
        fixture.import_payload(real)
        seconds = time.monotonic() - started
        real_id = real["release_id"]
        fixture.expect(
            fixture.sql(
                "SELECT count(*) FROM classification.term WHERE release_id=" + quote(real_id)
            )
            == "1596",
            "full-official-1596-terms",
        )
        fixture.expect(
            fixture.sql(
                "SELECT count(*) FROM classification.hierarchy WHERE release_id=" + quote(real_id)
            )
            == "1573",
            "full-official-1573-hierarchy",
        )
        fixture.expect(
            fixture.sql("SELECT count(*) FROM classification.graph_nodes(" + quote(real_id) + ")")
            == "1597",
            "full-official-1597-flat-nodes",
        )
        fixture.expect(
            fixture.sql("SELECT count(*) FROM classification.graph_edges(" + quote(real_id) + ")")
            == "3169",
            "full-official-3169-flat-edges",
        )
        original = fixture.digest(real_id)
        fixture.import_payload(real)
        fixture.expect(
            fixture.digest(real_id) == original, "full-official-replay-preserves-evidence"
        )
        print(f"Official full catalogue import: {seconds:.3f}s", flush=True)
    print(
        json.dumps(
            {"status": "PASSED", "checks": len(fixture.checks), "contracts": fixture.checks}
        ),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--official-payload", type=Path)
    arguments = parser.parse_args()
    fixture = Fixture()
    try:
        fixture.boot()
        check(fixture, arguments.official_payload)
    finally:
        fixture.cleanup()


if __name__ == "__main__":
    main()
