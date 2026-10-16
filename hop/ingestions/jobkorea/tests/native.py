# ruff: noqa: E501
"""Native JobKorea dry run in unique disposable PostgreSQL/Neo4j/Hop containers.

Only local images and a supplied local JSON file are used. All containers attach
solely to a new INTERNAL network; no ports are exposed, secrets copied, source
URLs requested, paid APIs called, or production resources modified. Python
orchestrates fixtures; production row loading runs in Hop Java and PostgreSQL.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
import xml.etree.ElementTree as E
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
REMOTE = "/fixture"


class Fixture:
    def __init__(self, input_file):
        self.token = uuid.uuid4().hex[:12]
        self.prefix = "jobtology-jobkorea-test-" + self.token
        self.network = self.prefix + "-net"
        self.pg = self.prefix + "-pg"
        self.database = "jobkorea_dryrun_" + self.token
        self.neo = self.prefix + "-neo"
        self.hop = self.prefix + "-hop"
        state = Path.home() / ".local/state/jobtology-hop"
        state.mkdir(parents=True, exist_ok=True)
        self.work = state / ("jobkorea-dry-run-" + self.token)
        self.work.mkdir(mode=0o700)
        self.input = input_file.resolve(strict=True)
        self.logs = self.work / "logs"
        self.logs.mkdir(mode=0o700)
        self.receipt = {
            "status": "RUNNING",
            "isolated": True,
            "network_internal": True,
            "no_source_requests": True,
            "no_paid_calls": True,
            "production_writes": False,
            "checks": [],
        }

    def command(self, args, label, input_text=None, success=True, timeout=120):
        result = subprocess.run(
            args, input=input_text, text=True, capture_output=True, check=False, timeout=timeout
        )
        (self.logs / (label + ".log")).write_text(result.stdout + result.stderr)
        if (result.returncode == 0) != success:
            raise RuntimeError(
                "Fixture check failed: "
                + label
                + "; protected log: "
                + str(self.logs / (label + ".log"))
            )
        return result.stdout.strip()

    def sql(self, statement, label="sql"):
        return self.command(
            [
                "docker",
                "exec",
                "-i",
                self.pg,
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
            label,
            statement,
        )

    def expect(self, condition, label):
        if not condition:
            raise AssertionError(label)
        self.receipt["checks"].append(label)
        print(label + " passed", flush=True)

    def boot(self):
        images = {
            "pg": os.environ.get("JOBKOREA_TEST_PG_IMAGE", "postgres:18-alpine"),
            "neo": os.environ.get("JOBKOREA_TEST_NEO_IMAGE", "neo4j:2026.06.0"),
            "hop": os.environ.get("JOBKOREA_TEST_HOP_IMAGE", "apache/hop:latest"),
        }
        self.receipt["images"] = {}
        for kind, image in images.items():
            identity = self.command(
                ["docker", "image", "inspect", image, "--format", "{{.Id}}"], "image-" + kind
            )
            self.receipt["images"][kind] = identity
            images[kind] = identity
        self.stage()
        self.command(["docker", "network", "create", "--internal", self.network], "create-network")
        self.command(
            [
                "docker",
                "run",
                "-d",
                "--pull",
                "never",
                "--network",
                self.network,
                "--name",
                self.pg,
                "-e",
                "POSTGRES_HOST_AUTH_METHOD=trust",
                "-e",
                "POSTGRES_DB=" + self.database,
                images["pg"],
            ],
            "start-pg",
        )
        self.command(
            [
                "docker",
                "run",
                "-d",
                "--pull",
                "never",
                "--network",
                self.network,
                "--name",
                self.neo,
                "-e",
                "NEO4J_AUTH=none",
                "-e",
                "NEO4J_server_memory_heap_initial__size=256m",
                "-e",
                "NEO4J_server_memory_heap_max__size=512m",
                "-e",
                "NEO4J_server_memory_pagecache_size=256m",
                images["neo"],
            ],
            "start-neo",
        )
        self.command(
            [
                "docker",
                "run",
                "-d",
                "--pull",
                "never",
                "--network",
                self.network,
                "--name",
                self.hop,
                "--user",
                "root",
                "-v",
                str(self.work) + ":" + REMOTE,
                "--entrypoint",
                "/bin/sleep",
                images["hop"],
                "infinity",
            ],
            "start-hop",
        )
        internal = self.command(
            ["docker", "network", "inspect", self.network, "--format", "{{.Internal}}"],
            "network-internal",
        )
        self.expect(internal == "true", "internal-network")
        for container in (self.pg, self.neo, self.hop):
            networks = json.loads(
                self.command(
                    [
                        "docker",
                        "inspect",
                        container,
                        "--format",
                        "{{json .NetworkSettings.Networks}}",
                    ],
                    "networks-" + container,
                )
            )
            self.expect(
                set(networks) == {self.network},
                "single-private-network-" + container.rsplit("-", 1)[1],
            )
        for _ in range(150):
            pg = subprocess.run(
                [
                    "docker",
                    "exec",
                    self.pg,
                    "pg_isready",
                    "-h",
                    "127.0.0.1",
                    "-U",
                    "postgres",
                    "-d",
                    self.database,
                ],
                capture_output=True,
            )
            neo = subprocess.run(
                ["docker", "exec", self.neo, "cypher-shell", "RETURN 1"], capture_output=True
            )
            if pg.returncode == neo.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Disposable databases did not become ready")
        self.receipt["postgres_version"] = self.sql("SHOW server_version", "pg-version")
        self.expect(self.receipt["postgres_version"].startswith("18."), "postgres-18")
        self.sql(
            "ALTER DATABASE "
            + self.database
            + " SET jobtology.isolated_fixture='"
            + self.token
            + "'",
            "isolated-database-marker",
        )

    def stage(self):
        project = self.work / "project"
        project.mkdir(mode=0o700)
        for folder in ("ingestions/jobkorea", "graph"):
            shutil.copytree(
                ROOT / "hop" / folder,
                project / folder,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests", "tools"),
            )
        (project / "retention").mkdir()
        for name in ("enter_graph_writer.hpl", "leave_graph_writer.hpl"):
            shutil.copyfile(ROOT / "hop/retention" / name, project / "retention" / name)
        (project / "operations").mkdir()
        shutil.copyfile(
            ROOT / "hop/operations/record_graph_export.hpl",
            project / "operations/record_graph_export.hpl",
        )
        for kind in ("pipeline", "workflow"):
            dest = project / f"metadata/{kind}-run-configuration"
            dest.mkdir(parents=True)
            for name in ("jobkorea-local", "graph-local", "retention-local"):
                shutil.copyfile(
                    ROOT / "hop" / dest.relative_to(project) / (name + ".json"),
                    dest / (name + ".json"),
                )
        rdbms = project / "metadata/rdbms"
        rdbms.mkdir()
        (rdbms / "jobtology-postgres.json").write_text(
            json.dumps(
                {
                    "name": "jobtology-postgres",
                    "rdbms": {
                        "POSTGRESQL": {
                            "pluginId": "POSTGRESQL",
                            "pluginName": "PostgreSQL",
                            "accessType": 0,
                            "hostname": self.pg,
                            "databaseName": self.database,
                            "port": "5432",
                            "manualUrl": "jdbc:postgresql://" + self.pg + ":5432/" + self.database,
                            "username": "postgres",
                            "password": "",
                            "sshTunnelEnabled": False,
                            "attributes": {
                                "SUPPORTS_BOOLEAN_DATA_TYPE": "Y",
                                "SUPPORTS_TIMESTAMP_DATA_TYPE": "Y",
                            },
                        }
                    },
                }
            )
        )
        neo = project / "metadata/neo4j-connection"
        neo.mkdir()
        (neo / "jobtology-neo4j.json").write_text(
            json.dumps(
                {
                    "name": "jobtology-neo4j",
                    "server": self.neo,
                    "databaseName": "neo4j",
                    "boltPort": "7687",
                    "username": "neo4j",
                    "password": "test-auth-disabled",
                    "automatic": False,
                    "routing": False,
                    "usingEncryption": False,
                    "manualUrls": ["bolt://" + self.neo + ":7687"],
                    "connectionTimeout": "10000",
                    "maxTransactionRetryTime": "0",
                }
            )
        )
        (project / "project-config.json").write_text(
            json.dumps({"metadataBaseFolder": "${PROJECT_HOME}/metadata", "variables": []})
        )
        config = self.work / "config"
        config.mkdir(mode=0o700)
        (config / "hop-config.json").write_text(
            json.dumps(
                {
                    "projectsConfig": {
                        "enabled": True,
                        "projectMandatory": True,
                        "defaultProject": "jobkorea-test",
                        "projectConfigurations": [
                            {
                                "projectName": "jobkorea-test",
                                "projectHome": REMOTE + "/project",
                                "configFilename": "project-config.json",
                                "readOnly": False,
                            }
                        ],
                        "lifecycleEnvironments": [],
                        "projectLifecycles": [],
                    }
                }
            )
        )
        inputs = self.work / "inputs"
        inputs.mkdir(mode=0o700)
        shutil.copyfile(self.input, inputs / "sample.json")
        (inputs / "sample.json").chmod(0o400)
        self.receipt["input_sha256"] = hashlib.sha256(
            (inputs / "sample.json").read_bytes()
        ).hexdigest()
        self.receipt["input_bytes"] = (inputs / "sample.json").stat().st_size
        (self.work / "raw").mkdir(mode=0o700)

    def install(self):
        files = [
            ROOT / "docs/hop-migration/schema.sql",
            ROOT / "docs/hop-migration/checks.sql",
            ROOT / "docs/hop-migration/operations.sql",
        ]
        files += sorted((ROOT / "hop/llm/sql").glob("*.sql"))
        files += [
            ROOT / "docs/hop-migration/operations.sql",
            ROOT / "hop/retention/sql/001_retention.sql",
            ROOT / "hop/cs/sql/001_common_postings.sql",
        ]
        for index, file in enumerate(files):
            self.sql(file.read_text(), "install-" + str(index) + "-" + file.name)
        legacy_checks = subprocess.run(
            ["git", "show", "HEAD:docs/hop-migration/checks.sql"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        self.sql(legacy_checks, "install-legacy-shared-checks")
        self.expect(
            (ROOT / "hop/ingestions/jobkorea/sql/005_shared_checks.sql").read_bytes()
            == (ROOT / "docs/hop-migration/checks.sql").read_bytes(),
            "generated-shared-check-consistency",
        )
        self.expect(True, "shared-schema-installer")
        self.run("install.hwf", "native-source-installer")
        self.run("install.hwf", "native-source-installer-replay")

    def run(
        self, filename, label, success=True, input_name="sample.json", extra=None, isolated=True
    ):
        params = {
            "INPUT_FILE": REMOTE + "/inputs/" + input_name,
            "RAW_ROOT": REMOTE + "/raw",
            "MODE": "DRY_RUN",
            "MAX_FILE_BYTES": "16777216",
        }
        params.update(extra or {})
        result = self.command(
            [
                "docker",
                "exec",
                "-e",
                "HOP_CONFIG_FOLDER=" + REMOTE + "/config",
                "-e",
                "HOP_OPTIONS=-Xmx1024m",
                "-e",
                "JOBKOREA_ISOLATED_CONTEXT=" + str(isolated).lower(),
                "-e",
                "JOBKOREA_ISOLATED_TOKEN=" + self.token,
                "-w",
                "/opt/hop",
                self.hop,
                "bash",
                "hop-run.sh",
                "-j",
                "jobkorea-test",
                "-r",
                "jobkorea-local",
                "-f",
                REMOTE + "/project/ingestions/jobkorea/" + filename,
                "-p",
                ",".join(k + "=" + str(v) for k, v in params.items()),
                "-l",
                "Basic",
            ],
            label,
            success=success,
            timeout=1800,
        )
        self.expect(True, label)
        return result

    def close(self):
        # Root Hop owns restrictive evidence directories. Remove only the four
        # fixture scratch directories while that exact container still exists.
        subprocess.run(
            [
                "docker",
                "exec",
                "-u",
                "root",
                self.hop,
                "rm",
                "-rf",
                "--",
                REMOTE + "/inputs",
                REMOTE + "/raw",
                REMOTE + "/project",
                REMOTE + "/config",
            ],
            capture_output=True,
            check=False,
        )
        for container in (self.hop, self.neo, self.pg):
            subprocess.run(["docker", "rm", "-fv", container], capture_output=True, check=False)
        subprocess.run(["docker", "network", "rm", self.network], capture_output=True, check=False)
        for folder in ("inputs", "raw", "project", "config"):
            shutil.rmtree(self.work / folder, ignore_errors=True)
        scratch_removed = all(
            not (self.work / folder).exists() for folder in ("inputs", "raw", "project", "config")
        )
        containers_removed = all(
            subprocess.run(["docker", "inspect", container], capture_output=True).returncode != 0
            for container in (self.hop, self.neo, self.pg)
        )
        network_removed = (
            subprocess.run(
                ["docker", "network", "inspect", self.network], capture_output=True
            ).returncode
            != 0
        )
        self.receipt["private_scratch_removed"] = scratch_removed
        self.receipt["disposable_resources_removed"] = containers_removed and network_removed
        (self.work / "receipt.json").write_text(json.dumps(self.receipt, indent=2) + "\n")
        if not scratch_removed or not self.receipt["disposable_resources_removed"]:
            raise RuntimeError(
                "Disposable fixture cleanup incomplete; protected receipt: "
                + str(self.work / "receipt.json")
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, default=ROOT.parent / "jobtology/j_muwj57zxdc6o3utkq.json"
    )
    parser.add_argument(
        "--import-only",
        action="store_true",
        help="Useful while developing; full graph verification is the default.",
    )
    args = parser.parse_args()
    os.umask(0o077)
    fixture = Fixture(args.input)
    try:
        fixture.boot()
        fixture.install()
        from sql_contract import check

        check(fixture)
        fixture.run("import_local.hpl", "native-source-import")
        run_id = fixture.sql(
            "SELECT run_id FROM ingestion.run WHERE source_id='jobkorea' AND state='READY'",
            "ready-run",
        )
        fixture.expect(bool(run_id) and "\n" not in run_id, "exact-ready-run")
        fixture.receipt["run_id"] = run_id
        # Only generated native run IDs are interpolated; supplied source fields
        # never appear in command lines, logs printed to stdout, or fixture SQL.
        before = fixture.sql(
            "SELECT md5(coalesce(jsonb_agg(to_jsonb(r) ORDER BY locator)::text,'')) FROM ingestion.record r",
            "digest-before",
        )
        fixture.run("import_local.hpl", "native-source-replay")
        fixture.expect(
            before
            == fixture.sql(
                "SELECT md5(coalesce(jsonb_agg(to_jsonb(r) ORDER BY locator)::text,'')) FROM ingestion.record r",
                "digest-after",
            ),
            "immutable-source-replay",
        )
        fixture.expect(
            fixture.sql(
                "SELECT count(*) FROM ingestion.run WHERE source_id='jobkorea'", "run-count"
            )
            == "1",
            "idempotent-run",
        )
        fixture.sql((ROOT / "docs/hop-migration/operations.sql").read_text(), "replay-operations")
        fixture.sql(
            (ROOT / "hop/retention/sql/000_operations.sql").read_text(),
            "replay-retention-operations",
        )
        fixture.expect(
            fixture.sql("SELECT count(*) FROM ingestion.request_attempt", "request-count") == "0",
            "zero-source-requests",
        )
        fixture.receipt["record_count"] = int(
            fixture.sql("SELECT count(*) FROM ingestion.record", "record-count")
        )
        fixture.expect(
            fixture.sql("SELECT count(*) FROM ingestion.validation_issue", "issue-count") == "0",
            "zero-validation-issues",
        )
        fixture.expect(
            fixture.sql(
                "SELECT count(*) FROM ingestion.document WHERE transport='LOCAL_FILE' AND http_status IS NULL AND provider_result IS NULL AND verified_at IS NOT NULL",
                "local-origin",
            )
            == "1",
            "verified-local-file-origin",
        )
        fixture.receipt["source_outcomes"] = json.loads(
            fixture.sql(
                "SELECT jsonb_build_object('total',count(*),'missing_starts',count(*) FILTER(WHERE NOT source_payload ? 'application_start_date'),'policy_rolling',count(*) FILTER(WHERE normalized->>'deadline_kind'='ROLLING' AND normalized->>'deadline_basis'='USER_POLICY'),'fixed_dates',count(*) FILTER(WHERE normalized->>'deadline_kind'='FIXED_DATE'),'missing_descriptions',count(*) FILTER(WHERE normalized->>'content_status'='MISSING'),'extraction_eligible',count(*) FILTER(WHERE normalized->'extraction_eligible'='true'::jsonb),'rejected',(SELECT count(*) FROM ingestion.rejected_row)) FROM ingestion.record",
                "source-outcomes",
            )
        )
        fixture.receipt["timestamps"] = json.loads(
            fixture.sql(
                "SELECT jsonb_build_object('received_at',received_at,'imported_at',imported_at,'processed_at',processed_at,'scraped_at',scraped_at) FROM ingestion.jobkorea_import",
                "source-timestamps",
            )
        )
        fixture.expect(
            fixture.receipt["timestamps"]["scraped_at"] is None, "unknown-scrape-time-preserved"
        )
        if (
            fixture.receipt["input_sha256"]
            == "934b51137ad3e4d38fb369719ae1ff654af932ea4b9f4c4d5e83ed21626bde95"
        ):
            expected = {
                "total": 887,
                "missing_starts": 288,
                "policy_rolling": 79,
                "fixed_dates": 808,
                "missing_descriptions": 887,
                "extraction_eligible": 0,
                "rejected": 0,
            }
            fixture.expect(
                fixture.receipt["source_outcomes"] == expected, "supplied-sample-outcomes"
            )
        if not args.import_only:
            fixture.run("full.hwf", "native-graph-load")
            fixture.expect(
                fixture.sql("SELECT count(*) FROM ingestion.graph_export", "checkpoint-count")
                == "1",
                "durable-graph-checkpoint",
            )
            fixture.receipt["graph_records"] = int(
                fixture.sql("SELECT count(*) FROM ingestion.graph_record", "graph-record-count")
            )
            fixture.receipt["graph_references"] = int(
                fixture.sql(
                    "SELECT count(*) FROM ingestion.graph_reference", "graph-reference-count"
                )
            )
            if fixture.receipt["source_outcomes"]["total"] == 887:
                fixture.expect(
                    fixture.receipt["graph_records"] == fixture.receipt["graph_references"] == 887,
                    "sample-graph-projection-counts",
                )

            def neo_scope(label):
                query = (
                    "MATCH (b:ingestionBatch {id:'"
                    + run_id
                    + "'}) OPTIONAL MATCH (b)-[:HAS_RECORD]->(r) "
                )
                query += "WITH b,count(r) AS records OPTIONAL MATCH (b)-[:HAS_RECORD]->()-[ref:REFERS_TO]->(entity) "
                query += "WITH b,records,count(ref) AS references,count(DISTINCT entity) AS identities RETURN toString(records)+'|'+toString(references)+'|'+b.state+'|'+b.serving_scope+'|'+toString(identities) AS scope;"
                output = fixture.command(
                    ["docker", "exec", fixture.neo, "cypher-shell", "--format", "plain", query],
                    label,
                )
                lines = output.splitlines()
                scope = next((line.strip('"') for line in lines if "|READY|STAGING|" in line), None)
                identities = fixture.sql(
                    "SELECT count(DISTINCT identity_id) FROM ingestion.graph_reference",
                    label + "-identities",
                )
                expected = (
                    str(fixture.receipt["graph_records"])
                    + "|"
                    + str(fixture.receipt["graph_references"])
                    + "|READY|STAGING|"
                    + identities
                )
                fixture.expect(scope == expected, label)
                fixture.receipt[label] = {
                    "records": fixture.receipt["graph_records"],
                    "references": fixture.receipt["graph_references"],
                    "identities": int(identities),
                    "state": "READY",
                    "serving_scope": "STAGING",
                }
                return scope

            initial_scope = neo_scope("independent-neo-scope")
            fixture.run("full.hwf", "native-graph-replay")
            fixture.expect(
                fixture.sql(
                    "SELECT count(*) FROM ingestion.graph_export", "replayed-checkpoint-count"
                )
                == "1",
                "idempotent-graph-checkpoint",
            )
            fixture.expect(
                neo_scope("independent-replayed-neo-scope") == initial_scope,
                "stable-graph-replay-counts",
            )
            fixture.expect(
                before
                == fixture.sql(
                    "SELECT md5(coalesce(jsonb_agg(to_jsonb(r) ORDER BY locator)::text,'')) FROM ingestion.record r",
                    "graph-replay-record-digest",
                ),
                "graph-replay-preserves-record-identities",
            )
            checkpoint_before = fixture.sql(
                "SELECT to_jsonb(g)::text FROM ingestion.graph_export g",
                "checkpoint-before-failure",
            )
            records_pipeline = fixture.work / "project/graph/load_records.hpl"
            original_pipeline = records_pipeline.read_bytes()
            try:
                pipeline = E.parse(records_pipeline)
                pipeline.find(
                    "transform[name='Merge graph record']/cypher"
                ).text = "RETURN false AS record_matches"
                pipeline.write(records_pipeline, encoding="UTF-8", xml_declaration=True)
                fixture.run("full.hwf", "native-graph-failure-gate", success=False)
                fixture.expect(
                    checkpoint_before
                    == fixture.sql(
                        "SELECT to_jsonb(g)::text FROM ingestion.graph_export g",
                        "checkpoint-after-failure",
                    ),
                    "graph-failure-skips-checkpoint",
                )
                fixture.expect(
                    fixture.sql(
                        "SELECT state FROM ingestion.run WHERE source_id='jobkorea'",
                        "state-after-graph-failure",
                    )
                    == "READY",
                    "graph-failure-preserves-postgres-ready",
                )
            finally:
                records_pipeline.write_bytes(original_pipeline)
            fixture.run("full.hwf", "native-graph-failure-recovery")
            neo_scope("independent-recovered-neo-scope")
        inputs = fixture.work / "inputs"
        fixtures = {
            "duplicate-key.json": b'[{"url":"https://example.invalid/Recruit/GI_Read/1","x":1,"x":2}]',
            "invalid-utf8.json": b'["\xff"]',
            "invalid-json.json": b"[{",
            "non-array.json": b"{}",
        }
        for name, data in fixtures.items():
            (inputs / name).write_bytes(data)
            fixture.run(
                "import_local.hpl",
                "reject-" + name.removesuffix(".json"),
                success=False,
                input_name=name,
            )
        fixture.run(
            "import_local.hpl", "reject-byte-bound", success=False, extra={"MAX_FILE_BYTES": "32"}
        )
        fixture.run("import_local.hpl", "reject-unisolated-dryrun", success=False, isolated=False)
        valid_fixture = {
            "product_page_url": "https://www.jobkorea.co.kr/Recruit/GI_Read/99990001",
            "job_title": "Synthetic fixture",
            "company_name": "Example",
            "application_end_date": "invalid",
        }
        (inputs / "malformed-date.json").write_text(json.dumps([valid_fixture]))
        fixture.run(
            "full.hwf",
            "reject-malformed-source-before-graph",
            success=False,
            input_name="malformed-date.json",
        )
        fixture.expect(
            fixture.sql(
                "SELECT count(*) FROM ingestion.run WHERE state='REVIEW_REQUIRED' AND source_id='jobkorea'",
                "review-count",
            )
            == "1",
            "malformed-source-review-required",
        )
        fixture.expect(
            fixture.sql(
                "SELECT count(*) FROM ingestion.graph_export g JOIN ingestion.run r USING(run_id) WHERE r.state<>'READY'",
                "no-review-checkpoint",
            )
            == "0",
            "review-required-skips-graph-checkpoint",
        )
        fixture.expect(
            fixture.sql("SELECT count(*) FROM ingestion.request_attempt", "final-no-http-ledger")
            == "0",
            "failure-gates-make-zero-source-requests",
        )
        archived_remote = (
            REMOTE + "/raw/jobkorea/" + fixture.receipt["input_sha256"] + "/source.json"
        )
        fixture.command(
            ["docker", "exec", "-u", "root", fixture.hop, "chmod", "600", archived_remote],
            "fixture-make-archive-writable",
        )
        fixture.command(
            ["docker", "exec", "-u", "root", "-i", fixture.hop, "tee", archived_remote],
            "fixture-change-archive",
            input_text="[]",
        )
        fixture.run("import_local.hpl", "reject-archive-hash-conflict", success=False)
        fixture.expect(
            before
            == fixture.sql(
                "SELECT md5(coalesce(jsonb_agg(to_jsonb(r) ORDER BY locator)::text,'')) FROM ingestion.record r",
                "digest-final",
            ),
            "failure-preserves-ready-evidence",
        )
        fixture.receipt["status"] = "PASSED_IMPORT_ONLY" if args.import_only else "PASSED"
    except BaseException:
        fixture.receipt["status"] = "FAILED"
        raise
    finally:
        fixture.close()
        print("Protected dry-run receipt: " + str(fixture.work / "receipt.json"), flush=True)


if __name__ == "__main__":
    main()
