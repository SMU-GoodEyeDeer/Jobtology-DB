"""All-source, no-provider native PostgreSQL/Hop/Neo4j batch-free contracts."""
# ruff: noqa: E501

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


native = module("jobkorea_batchfree_native", ROOT / "hop/ingestions/jobkorea/tests/native.py")
compatibility = module(
    "batchfree_allsource_fixture", ROOT / "hop/ingestions/jobkorea/tests/graph_compatibility.py"
)


def quote(value):
    return "'" + value.replace("'", "''") + "'"


def main():
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="jobtology-batchfree-") as scratch:
        sample = Path(scratch) / "sample.json"
        sample.write_text(
            json.dumps(
                [
                    {
                        "product_page_url": "https://www.jobkorea.co.kr/Recruit/GI_Read/50109422",
                        "job_title": "Backend developer",
                        "company_name": "Example employer",
                    },
                    {
                        "product_page_url": "https://www.jobkorea.co.kr/Recruit/GI_Read/50109423",
                        "job_title": "Data engineer",
                        "company_name": "Example employer",
                    },
                ]
            )
        )
        fixture = native.Fixture(sample)
        fixture.receipt["suite"] = "batchfree-source-graph-v1"
        try:
            fixture.boot()
            fixture.install()
            fixture.sql(
                (ROOT / "hop/graph/sql/002_batchfree_source_graph.sql").read_text(),
                "install-batchfree",
            )
            fixture.run("../../graph/install.hwf", "native-graph-installer")
            fixture.run("../../graph/install.hwf", "native-graph-installer-replay")
            fixture.run("full.hwf", "native-jobkorea-business-graph")
            jobs = fixture.sql("SELECT run_id FROM ingestion.run WHERE source_id='jobkorea'")

            def neo(query, label):
                return (
                    fixture.command(
                        ["docker", "exec", fixture.neo, "cypher-shell", "--format", "plain", query],
                        label,
                    )
                    .splitlines()[-1]
                    .lower()
                )

            def rejected(statement, error, label):
                fixture.command(
                    [
                        "docker",
                        "exec",
                        "-i",
                        fixture.pg,
                        "psql",
                        "-X",
                        "-qAt",
                        "-v",
                        "ON_ERROR_STOP=1",
                        "-U",
                        "postgres",
                        "-d",
                        fixture.database,
                    ],
                    label,
                    statement,
                    success=False,
                )
                fixture.expect(error in (fixture.logs / (label + ".log")).read_text(), label)

            fixture.expect(
                neo(
                    "MATCH (n) WHERE any(l IN labels(n) WHERE l IN ['ingestionBatch','ingestionRecord','archivedRecord']) RETURN count(n)=0",
                    "no-history-nodes",
                )
                == "true",
                "no-history-node-created",
            )
            fixture.expect(
                fixture.sql(
                    "SELECT state FROM ingestion.source_graph_projection WHERE run_id="
                    + quote(jobs)
                )
                == "READY",
                "postgres-projection-ready",
            )
            fixture.expect(
                neo(
                    "MATCH (p:entity:jobPosting) RETURN count(p)=2 AND all(p IN collect(p) WHERE valueType(p.first_ingested_at)='ZONED DATETIME NOT NULL' AND valueType(p.ingestion_batch_date)='DATE NOT NULL')",
                    "posting-dates",
                )
                == "true",
                "typed-posting-dates-retained",
            )
            original = fixture.sql(
                "SELECT md5(jsonb_agg(to_jsonb(r) ORDER BY record_id)::text) FROM ingestion.record r WHERE run_id="
                + quote(jobs)
            )
            fixture.sql(compatibility.FIXTURE, "seven-official-sources")
            fixture.expect(
                fixture.sql("SELECT count(*) FROM ingestion.validation_issue") == "0",
                "all-eight-source-validation",
            )
            fixture.sql(
                "INSERT INTO ingestion.graph_export(run_id,loader_version) SELECT run_id,'hop-graph-v2' FROM ingestion.run WHERE source_id<>'jobkorea'",
                "historical-checkpoints",
            )
            # Multiple current mappings for the same source identity must survive.
            fixture.sql(
                """
INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized)
 SELECT run_id,document_id,'/1',source_record_id||'-second','{}',normalized||CASE source_id
 WHEN 'ncs_qualification' THEN '{"qualification_code":"q2","qualification_name":"Other qualification","minimum_training_hours":42}'::jsonb
 ELSE '{"rank_level":2,"rank_name":"Senior"}'::jsonb END FROM ingestion.ready_record WHERE source_id IN('ncs_qualification','ncs_career_path');
UPDATE ingestion.document SET item_count=2,declared_total=2 WHERE run_id IN('ncs_qualification','ncs_career_path');
UPDATE ingestion.partition SET expected_total=2 WHERE run_id IN('ncs_qualification','ncs_career_path');
""",
                "multivalue-source-facts",
            )
            fixture.expect(
                fixture.sql("SELECT count(*) FROM ingestion.validation_issue") == "0",
                "multivalue-validation",
            )
            fixture.run(
                "../../graph/migrate_source_graph.hwf",
                "native-bulk-business-projection",
                extra={"RUN_ID": "ALL_CHECKPOINTED"},
            )
            fixture.expect(
                fixture.sql(
                    "SELECT count(*) FROM ingestion.source_graph_projection WHERE state='READY'"
                )
                == "8",
                "all-eight-projection-proofs",
            )
            fixture.expect(
                neo(
                    "MATCH (:entity {id:'ncs:unit:unit'})-[r:QUALIFICATION_MAPPING]->(:qualification) RETURN count(r)=2",
                    "qualification-multivalue",
                )
                == "true",
                "qualification-mappings-preserved",
            )
            fixture.expect(
                neo(
                    "MATCH (:occupation {id:'ncs:occupation:occ'})-[r:HAS_CAREER_COMPETENCY]->(:ncsCompetency) RETURN count(r)=2",
                    "career-multivalue",
                )
                == "true",
                "career-ranks-preserved",
            )
            fixture.expect(
                neo(
                    "MATCH (:qualification)-[:HAS_EXAM_SESSION]->(s:entity:examSession) RETURN count(s)=1 AND all(s IN collect(s) WHERE s.kind='ExamSession')",
                    "exam-session",
                )
                == "true",
                "stable-qnet-session-preserved",
            )
            fixture.expect(
                neo(
                    "MATCH (o:occupation {id:'ncs:occupation:occ'}),(q:qualification {id:'qnet:qualification:q'}) RETURN NOT o.source_facts_json CONTAINS 'competency_code' AND NOT q.source_facts_json CONTAINS 'year' AND NOT q.source_facts_json CONTAINS 'minimum_training_hours'",
                    "subject-fact-ownership",
                )
                == "true",
                "referred-identities-have-own-facts",
            )
            fixture.expect(
                neo(
                    "MATCH (:jobPosting {id:'job-alio:posting:123'})-[:EMPLOYER]->(:organization {id:'alio:organization:o'}) RETURN count(*)=1",
                    "posting-employer",
                )
                == "true",
                "explicit-employer-link",
            )
            fixture.expect(
                neo("MATCH (n:organization) RETURN count(n)=1", "no-fabricated-employer") == "true",
                "jobkorea-employer-name-not-identity",
            )
            if "--operator-only" in sys.argv:
                operator = module(
                    "batchfree_operator_native",
                    ROOT / "hop/graph/tests/batchfree_operator_native.py",
                )
                operator.run(fixture)
                fixture.receipt["status"] = "PASSED"
                return
            # Stable IDs and inferred relationship properties survive replay.
            neo(
                "MATCH (p:entity:jobPosting),(o:occupation) WHERE p.id STARTS WITH 'source:posting:jobkorea:' WITH p,o LIMIT 1 MERGE (p)-[r:INFERRED_OCCUPATION {candidate_id:'fixture-protected',review_status:'REVIEWED',confidence_basis:'UNASSESSED'}]->(o) RETURN true",
                "protected-inferred-edge",
            )
            graph_before = neo(
                "MATCH (n:entity) RETURN collect([elementId(n),n.id,properties(n)])",
                "replay-before",
            )
            edges_before = neo(
                "MATCH ()-[r]->() WHERE r.source_graph=true RETURN collect([elementId(r),r.edge_key,properties(r)])",
                "edge-replay-before",
            )
            fixture.run(
                "../../graph/migrate_source_graph.hwf",
                "native-bulk-projection-replay",
                extra={"RUN_ID": "ALL_CHECKPOINTED"},
            )
            fixture.expect(
                graph_before
                == neo(
                    "MATCH (n:entity) RETURN collect([elementId(n),n.id,properties(n)])",
                    "replay-after",
                ),
                "stable-element-ids-and-properties-on-replay",
            )
            fixture.expect(
                edges_before
                == neo(
                    "MATCH ()-[r]->() WHERE r.source_graph=true RETURN collect([elementId(r),r.edge_key,properties(r)])",
                    "edge-replay-after",
                ),
                "stable-direct-relationship-ids-on-replay",
            )
            fixture.expect(
                fixture.sql(
                    "SELECT md5(jsonb_agg(to_jsonb(r) ORDER BY record_id)::text) FROM ingestion.record r WHERE run_id="
                    + quote(jobs)
                )
                == original,
                "frozen-jobkorea-source-unchanged",
            )
            # A newer accepted run clears missing source facts while keeping the
            # richer historical display name; absent postings get no closure.
            fixture.sql(
                """
INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision,state,created_at,completed_at)
 VALUES('nara-new','nara_job','FULL','fixture','READY','2030-01-01Z','2030-01-01Z');
INSERT INTO ingestion.partition SELECT 'nara-new',partition_id,kind,request_context,page_size,expected_total FROM ingestion.partition WHERE run_id='nara_job';
INSERT INTO ingestion.document SELECT 'nara-new',document_id,partition_id,page_no,confirmation_no,attempt_no,raw_path,raw_sha256,byte_length,encoding,http_status,provider_result,retrieved_at,declared_total,effective_page,effective_page_size,item_count,selected,verified_at,transport FROM ingestion.document WHERE run_id='nara_job';
INSERT INTO ingestion.record(run_id,document_id,locator,source_record_id,source_payload,normalized)
 SELECT 'nara-new',document_id,locator,source_record_id,'{}',normalized-'description_text'-'title' FROM ingestion.record WHERE run_id='nara_job';
""",
                "newer-nara-observation",
            )
            fixture.run(
                "../../graph/load_snapshot.hwf",
                "native-newer-current-facts",
                extra={"RUN_ID": "nara-new"},
            )
            fixture.run(
                "../../graph/load_snapshot.hwf",
                "native-old-run-replay",
                extra={"RUN_ID": "nara_job"},
            )
            fixture.expect(
                neo(
                    "MATCH (n:entity:jobPosting) WHERE n.id STARTS WITH 'source:posting:nara_job:' RETURN n.source_run_id='nara-new' AND n.name='Nara' AND NOT n.source_facts_json CONTAINS 'description_text'",
                    "current-no-rollback",
                )
                == "true",
                "old-run-replay-no-current-fact-rollback",
            )
            fixture.expect(
                neo(
                    "MATCH (n:entity:jobPosting) WHERE n.id STARTS WITH 'source:posting:jobkorea:' RETURN count(n)=2 AND all(n IN collect(n) WHERE n.source_run_id="
                    + quote(jobs)
                    + ")",
                    "absent-postings",
                )
                == "true",
                "absent-posting-no-inferred-closure",
            )
            fixture.sql(
                "SELECT ingestion.assert_source_graph_member('nara_job',ingestion.posting_identity('nara_job','123'),'JobPosting')",
                "historical-member-proof",
            )
            fixture.expect(True, "old-pinned-membership-valid-with-new-current-facts")
            # Incomplete, failed and damaged graph recovery stays PG-driven.
            fixture.sql(
                "INSERT INTO ingestion.run(run_id,source_id,mode,policy_revision) VALUES('incomplete','nara_job','FULL','fixture')",
                "incomplete-run",
            )
            fixture.run(
                "../../graph/load_snapshot.hwf",
                "incomplete-fails-before-business-writes",
                success=False,
                extra={"RUN_ID": "incomplete"},
            )
            fixture.expect(
                fixture.sql(
                    "SELECT count(*) FROM ingestion.source_graph_projection WHERE run_id='incomplete'"
                )
                == "0",
                "incomplete-no-projection-accepted",
            )
            fixture.sql(
                "SELECT ingestion.begin_source_graph_projection('ncs_competency'); SELECT ingestion.fail_source_graph_projection('ncs_competency')",
                "failed-projection",
            )
            rejected(
                "SELECT ingestion.assert_source_graph_projection('ncs_competency')",
                "SOURCE_GRAPH_PROJECTION_NOT_READY",
                "failed-proof-refused",
            )
            neo("MATCH (a)-[r:CLASSIFIED_AS]->(b) DELETE r RETURN true", "damage-direct-edge")
            fixture.run(
                "../../graph/load_snapshot.hwf",
                "failed-exact-run-recovery",
                extra={"RUN_ID": "ncs_competency"},
            )
            fixture.expect(
                neo(
                    "MATCH (:ncsCompetency)-[:CLASSIFIED_AS]->(:occupation) RETURN count(*)=1",
                    "recovered-edge",
                )
                == "true",
                "failed-projection-recovery",
            )
            fixture.expect(
                neo(
                    "MATCH ()-[r:INFERRED_OCCUPATION {candidate_id:'fixture-protected'}]->() RETURN count(r)=1 AND all(r IN collect(r) WHERE r.review_status='REVIEWED' AND r.confidence_basis='UNASSESSED')",
                    "protected-inference-after-recovery",
                )
                == "true",
                "inferred-candidate-and-review-preserved",
            )
            rejected(
                "UPDATE ingestion.source_graph_record_evidence SET facts_sha256=repeat('b',64)",
                "IMMUTABLE_SOURCE_GRAPH_EVIDENCE",
                "immutable-record-proof",
            )
            rejected(
                "INSERT INTO ingestion.source_graph_membership VALUES('invented','invented','ncs:unit:fake','code','Competency','fake')",
                "INVALID_SOURCE_GRAPH_EVIDENCE",
                "forged-membership-refused",
            )
            operator = module(
                "batchfree_operator_native", ROOT / "hop/graph/tests/batchfree_operator_native.py"
            )
            if "--entity-batches-only" not in sys.argv:
                operator.run(fixture)
            if any(flag in sys.argv for flag in ("--entity-batches", "--entity-batches-only")):
                batches = module(
                    "source_entity_batches_native",
                    ROOT / "hop/graph/tests/source_entity_batches_native.py",
                )
                batches.run(fixture)
            fixture.sql(
                "UPDATE ingestion.record SET normalized=normalized||'{\"tamper\":true}' WHERE run_id='ncs_competency'",
                "fixture-live-source-tamper",
            )
            rejected(
                "SELECT ingestion.assert_source_graph_projection('ncs_competency')",
                "SOURCE_GRAPH_LIVE_CONTENT_MISMATCH",
                "tampered-live-proof-refused",
            )
            fixture.expect(
                neo(
                    "MATCH (n) WHERE any(l IN labels(n) WHERE l IN ['ingestionBatch','ingestionRecord','archivedRecord']) RETURN count(n)=0",
                    "final-no-history-nodes",
                )
                == "true",
                "no-history-nodes-after-failure-recovery-replay",
            )
            fixture.receipt["status"] = "PASSED"
        except Exception:
            fixture.receipt["status"] = "FAILED"
            raise
        finally:
            fixture.close()
            print(
                json.dumps(
                    {
                        "receipt": str(fixture.work / "receipt.json"),
                        "status": fixture.receipt["status"],
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
