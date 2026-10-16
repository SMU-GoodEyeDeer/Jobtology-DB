"""Generate additive query-local source validation/selection from canonical rules.

The public all-run views remain the independent compatibility oracle. Generated
exact-run rules deliberately share only one SQL statement's current base rows;
there is no durable or session cache. Regenerate after changing canonical checks.
"""
# SQL literals retain canonical formatting for exact, reviewed replacements.
# ruff: noqa: E501

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "hop/graph/sql/003_source_query_sharing.sql"


def view_body(source: str, name: str) -> str:
    return source.split("CREATE OR REPLACE VIEW " + name + " AS\n", 1)[1].split(";", 1)[0]


def function(source: str, name: str) -> str:
    start = source.index("CREATE OR REPLACE FUNCTION ingestion." + name + "(")
    stop = source.index("$$;", start) + 3
    return source[start:stop]


def replace_once(source: str, before: str, after: str) -> str:
    assert source.count(before) == 1, before
    return source.replace(before, after)


def scoped_shared(checks: str) -> str:
    query = view_body(checks, "ingestion.validation_issue")
    for table, alias in (
        ("run", "runs"),
        ("partition", "partitions"),
        ("document", "documents"),
        ("record", "records"),
        ("dependency", "dependencies"),
        ("rejected_row", "rejected"),
    ):
        query = query.replace("ingestion." + table + " ", alias + " ")
    # The dependency's owner is scoped; its input run must remain independently
    # visible, including a wrong-source or non-READY run outside the target.
    query = replace_once(
        query,
        "FROM dependencies d JOIN runs u ON u.run_id = d.input_run_id",
        "FROM dependencies d JOIN ingestion.run u ON u.run_id = d.input_run_id",
    )
    query = query.replace("selected AS NOT MATERIALIZED", "selected AS MATERIALIZED")
    query = query.replace("facts AS NOT MATERIALIZED", "facts AS MATERIALIZED")
    # A CTE does not retain a table primary key's GROUP BY functional dependency.
    # Aggregate the same selected documents before joining the scoped partitions.
    query = replace_once(
        query,
        "partition_counts AS (\n"
        "    SELECT p.*, count(d.document_id) AS documents,\n"
        "           min(d.page_no) AS first_page, max(d.page_no) AS last_page\n"
        "    FROM partitions p\n"
        "    LEFT JOIN selected d USING (run_id, partition_id)\n"
        "    GROUP BY p.run_id, p.partition_id\n)",
        "document_counts AS (SELECT run_id,partition_id,count(document_id) AS documents,\n"
        " min(page_no) AS first_page,max(page_no) AS last_page FROM selected\n"
        " GROUP BY run_id,partition_id),\n"
        "partition_counts AS (SELECT p.*,coalesce(c.documents,0) AS documents,\n"
        " c.first_page,c.last_page FROM partitions p\n"
        " LEFT JOIN document_counts c USING(run_id,partition_id))",
    )
    query = replace_once(
        query,
        "WITH selected AS",
        "WITH\n"
        + ",\n".join(
            alias + " AS MATERIALIZED (SELECT * FROM ingestion." + table + " WHERE run_id=jobs)"
            for table, alias in (
                ("run", "runs"),
                ("partition", "partitions"),
                ("document", "documents"),
                ("record", "records"),
                ("dependency", "dependencies"),
                ("rejected_row", "rejected"),
            )
        )
        + ",\nselected AS",
    )
    query = replace_once(
        query,
        "ingestion.local_file_validation_issue()",
        "ingestion.source_graph_local_validation_issue(jobs)",
    )
    return (
        "CREATE OR REPLACE FUNCTION ingestion.source_graph_validation_issue(jobs text)\n"
        "RETURNS TABLE(run_id text,issue text,location text)\n"
        "LANGUAGE sql STABLE SET jit=off AS $$\n" + query + "\n$$;"
    )


def scoped_jobkorea(checks: str, ndjson: str) -> str:
    query = view_body(checks, "ingestion.jobkorea_validation_issue")
    for table, alias in (
        ("run", "runs"),
        ("jobkorea_import", "imports"),
        ("jobkorea_issue", "issues"),
        ("document", "documents"),
        ("partition", "partitions"),
        ("record", "records"),
        ("rejected_row", "rejected"),
    ):
        query = query.replace("ingestion." + table + " ", alias + " ")
    query = replace_once(
        query,
        "ingestion.jobkorea_row_manifest(i.run_id)",
        "(SELECT m.digest FROM manifests m WHERE m.run_id=i.run_id)",
    )
    ndquery = (
        function(ndjson, "jobkorea_ndjson_validation_issue")
        .split("AS $$\n", 1)[1]
        .rsplit("\n$$;", 1)[0]
    )
    ndquery = ndquery.replace("ingestion.jobkorea_import i", "imports i")
    ndquery = replace_once(
        ndquery,
        "ingestion.jobkorea_ndjson_row_manifest(i.run_id)",
        "(SELECT m.digest FROM manifests m WHERE m.run_id=i.run_id)",
    )
    query = replace_once(
        query, "SELECT * FROM ingestion.jobkorea_ndjson_validation_issue()", ndquery.strip()
    )
    # The collision helper is dynamic because CS may be absent. It receives the
    # exact target so the existing public zero-argument helper stays unchanged.
    query = replace_once(
        query,
        "ingestion.jobkorea_cs_collision_issue()",
        "ingestion.source_graph_jobkorea_collision_issue(jobs)",
    )
    prefix = ",\n".join(
        alias + " AS MATERIALIZED (SELECT * FROM ingestion." + table + " WHERE run_id=jobs)"
        for table, alias in (
            ("run", "runs"),
            ("jobkorea_import", "imports"),
            ("jobkorea_issue", "issues"),
            ("document", "documents"),
            ("partition", "partitions"),
            ("record", "records"),
            ("rejected_row", "rejected"),
        )
    )
    prefix += (
        ",\nmanifests AS MATERIALIZED (SELECT i.run_id, CASE WHEN i.file_format='NDJSON'\n"
        " THEN ingestion.jobkorea_ndjson_row_manifest(i.run_id)\n"
        " WHEN i.loaded THEN ingestion.jobkorea_row_manifest(i.run_id) END AS digest FROM imports i)"
    )
    return (
        "CREATE OR REPLACE FUNCTION ingestion.source_graph_jobkorea_validation_issue(jobs text)\n"
        "RETURNS TABLE(run_id text,issue text,location text)\n"
        "LANGUAGE sql STABLE SET jit=off AS $$\nWITH " + prefix + "\n" + query + "\n$$;"
    )


def manifest(graph: str, schema: str) -> str:
    # Reuse the canonical reference branches against one exact-run READY and
    # selected record pass. No normalized facts/proof key/order changes.
    refs = view_body(schema, "ingestion.graph_reference")
    refs = refs.replace("ingestion.ready_record r", "ready r")
    refs += (
        "\nUNION ALL\nSELECT 'hop:'||r.run_id||':'||r.record_id::text,r.run_id,\n"
        " 'qnet:exam-session:'||encode(sha256(convert_to(r.source_record_id,'UTF8')),'hex'),\n"
        " 'ExamSession',r.source_record_id,'source_record_id' FROM ready r WHERE r.source_id='qnet_schedule'"
    )
    evidence = view_body(graph, "ingestion.source_graph_live_record_evidence")
    evidence = replace_once(
        evidence,
        "FROM ingestion.graph_record g JOIN ingestion.ready_record r USING(run_id,record_id)\nJOIN ingestion.document d USING(run_id,document_id)",
        "FROM ready r CROSS JOIN LATERAL (SELECT 'hop:'||r.run_id||':'||r.record_id::text AS id,\n"
        " r.source_record_id,(CASE WHEN r.source_id='jobkorea' THEN ingestion.jobkorea_graph_facts(r.normalized)\n"
        " ELSE r.normalized-ARRAY['definition','eligibility_text','disqualification_text','preference_text',\n"
        " 'selection_text','address','website','source_url'] END)::text AS facts_json) g\n"
        " JOIN selected_documents d USING(run_id,document_id)",
    )
    evidence = evidence.replace("g.run_id", "r.run_id")
    original = function(graph, "source_graph_manifest")
    original = replace_once(
        original,
        "WITH records AS MATERIALIZED (",
        "WITH target AS MATERIALIZED (\n"
        " SELECT u.run_id,u.source_id FROM ingestion.run u WHERE live AND u.run_id=jobs\n"
        " AND u.state='READY' AND u.mode<>'SMOKE'\n), selected_documents AS MATERIALIZED (\n"
        " SELECT d.* FROM ingestion.document d JOIN target u USING(run_id) WHERE d.selected\n"
        "), ready AS MATERIALIZED (\n"
        " SELECT r.*,u.source_id FROM ingestion.record r JOIN target u USING(run_id)\n"
        " JOIN selected_documents d USING(run_id,document_id)\n), live_records AS (\n"
        + evidence
        + "\n), live_members AS (\n"
        + refs
        + "\n), records AS MATERIALIZED (",
    )
    original = original.replace(
        "ingestion.source_graph_live_record_evidence", "live_records"
    ).replace("ingestion.source_graph_reference", "live_members")
    original = replace_once(original, "LANGUAGE sql STABLE", "LANGUAGE plpgsql STABLE")
    original = replace_once(
        original,
        "AS $$\n",
        "AS $$\nBEGIN\n IF live THEN PERFORM ingestion.source_graph_assert_query_contract(); END IF;\n RETURN QUERY\n",
    )
    return replace_once(original, "\n$$;", ";\nEND $$;")


def selection_prefix(graph: str, schema: str) -> str:
    candidate = view_body(graph, "ingestion.source_graph_candidate")
    prefix = candidate.split("\nSELECT q.record_id", 1)[0]
    before = "records AS MATERIALIZED(SELECT r.run_id,r.record_id,r.source_id,r.source_record_id,r.normalized,u.created_at\n FROM ingestion.ready_record r JOIN eligible_runs u USING(run_id)),\nrefs AS MATERIALIZED(SELECT q.*,substring(q.record_id from '[^:]+$')::bigint AS numeric_record_id\n FROM ingestion.source_graph_reference q JOIN eligible_runs u USING(run_id))"
    references = view_body(schema, "ingestion.graph_reference").replace(
        "ingestion.ready_record r", "records r"
    )
    references += (
        "\nUNION ALL\nSELECT 'hop:'||r.run_id||':'||r.record_id::text,r.run_id,\n"
        " 'qnet:exam-session:'||encode(sha256(convert_to(r.source_record_id,'UTF8')),'hex'),\n"
        " 'ExamSession',r.source_record_id,'source_record_id' FROM records r WHERE r.source_id='qnet_schedule'"
    )
    after = (
        "selected_documents AS MATERIALIZED(SELECT d.run_id,d.document_id\n"
        " FROM ingestion.document d JOIN eligible_runs u USING(run_id) WHERE d.selected),\n"
        "records AS MATERIALIZED(SELECT r.run_id,r.record_id,u.source_id,r.source_record_id,r.normalized,u.created_at\n"
        " FROM ingestion.record r JOIN eligible_runs u USING(run_id)\n"
        " JOIN selected_documents d USING(run_id,document_id)),\n"
        "raw_refs AS (\n" + references + "\n),\n"
        "refs AS MATERIALIZED(SELECT q.*,substring(q.record_id from '[^:]+$')::bigint AS numeric_record_id FROM raw_refs q)"
    )
    prefix = replace_once(
        prefix,
        "SELECT u.run_id,u.created_at FROM ingestion.run u",
        "SELECT u.run_id,u.source_id,u.created_at FROM ingestion.run u",
    )
    prefix = replace_once(prefix, before, after)
    prefix = replace_once(prefix, " AND ingestion.source_graph_run_is_valid(u.run_id)", "")
    # Source-qualified posting namespaces have no cross-source identity joins.
    # Keep the complete ALIO/JOB and NCS/Q-Net connected groups so a newer owner
    # can introduce an endpoint with authoritative facts in a different run.
    # All checkpointed/unknown targets and unknown future source IDs overinclude.
    prefix = replace_once(
        prefix,
        "WITH eligible_runs AS MATERIALIZED(",
        "WITH target_source AS MATERIALIZED(SELECT source_id FROM ingestion.run WHERE run_id=jobs),\n"
        "eligible_runs AS MATERIALIZED(",
    )
    prefix = replace_once(
        prefix,
        "WHERE u.state='READY' AND u.mode<>'SMOKE'",
        "WHERE u.state='READY' AND u.mode<>'SMOKE'\n AND (jobs='ALL_CHECKPOINTED'\n"
        " OR NOT EXISTS(SELECT 1 FROM target_source)\n"
        " OR u.source_id NOT IN('alio_organization','job_alio','nara_job','jobkorea','ncs_career_path','ncs_competency','ncs_qualification','qnet_schedule')\n"
        " OR EXISTS(SELECT 1 FROM target_source t WHERE t.source_id=u.source_id\n"
        " OR t.source_id NOT IN('alio_organization','job_alio','nara_job','jobkorea','ncs_career_path','ncs_competency','ncs_qualification','qnet_schedule')\n"
        " OR (t.source_id IN('alio_organization','job_alio') AND u.source_id IN('alio_organization','job_alio'))\n"
        " OR (t.source_id IN('ncs_career_path','ncs_competency','ncs_qualification','qnet_schedule')\n"
        " AND u.source_id IN('ncs_career_path','ncs_competency','ncs_qualification','qnet_schedule'))))",
    )
    return prefix.replace("eligible_runs", "ready_runs")


def assessed_edges(query: str) -> str:
    """Validate target membership, then only runs that can own touched identities."""
    target = (
        "target_assessments AS MATERIALIZED(SELECT u.run_id,\n"
        " ingestion.source_graph_run_is_valid(u.run_id) AS valid FROM ready_runs u\n"
        " WHERE u.run_id=jobs OR (jobs='ALL_CHECKPOINTED' AND EXISTS(SELECT 1 FROM ingestion.graph_export g WHERE g.run_id=u.run_id))),\n"
    )
    original = "touched AS MATERIALIZED(SELECT DISTINCT identity_id FROM refs q WHERE run_id=jobs OR (jobs='ALL_CHECKPOINTED' AND EXISTS(SELECT 1 FROM ingestion.graph_export g WHERE g.run_id=q.run_id))),"
    replacement = (
        target + " touched AS MATERIALIZED(SELECT DISTINCT q.identity_id FROM refs q\n"
        " JOIN target_assessments a USING(run_id) WHERE a.valid),\n"
        "needed_edge_runs AS MATERIALIZED(SELECT DISTINCT q.run_id FROM refs q JOIN touched t USING(identity_id)),\n"
        "edge_assessments AS MATERIALIZED(SELECT * FROM target_assessments UNION ALL\n"
        " SELECT u.run_id,ingestion.source_graph_run_is_valid(u.run_id) FROM ready_runs u\n"
        " JOIN needed_edge_runs n USING(run_id) WHERE NOT EXISTS(SELECT 1 FROM target_assessments a WHERE a.run_id=u.run_id)),\n"
    )
    query = replace_once(query, original, replacement)
    # Nara/JobKorea metadata has no source-stated identity relationship. These
    # owners can never pass the canonical target-kind branches, so exclude them
    # before expanding self/target references; cleanup still enumerates them in
    # the independent graph_source_edge_owners API with an empty expected set.
    query = replace_once(
        query,
        "r.source_id IN('job_alio','nara_job','jobkorea') AND q.kind='JobPosting'",
        "r.source_id='job_alio' AND q.kind='JobPosting'",
    )
    return replace_once(
        query,
        "FROM refs q JOIN touched t USING(identity_id)\n",
        "FROM refs q JOIN touched t USING(identity_id)\n JOIN edge_assessments a ON a.run_id=q.run_id AND a.valid\n",
    )


def edge_selection(graph: str, schema: str) -> str:
    original = function(graph, "graph_source_edges")
    query = original.split("AS $$\n", 1)[1].rsplit("\n$$;", 1)[0]
    prefix = query.split("\n touched AS", 1)[0]
    # Canonical edge/candidate prefixes differ only in whitespace.
    original = assessed_edges(
        replace_once(original, prefix, " " + selection_prefix(graph, schema) + ",")
    )
    original = replace_once(original, "LANGUAGE sql STABLE", "LANGUAGE plpgsql STABLE")
    original = replace_once(
        original,
        "AS $$\n",
        "AS $$\n#variable_conflict use_column\nBEGIN\n PERFORM ingestion.source_graph_assert_query_contract();\n RETURN QUERY\n",
    )
    return replace_once(original, "\n$$;", ";\nEND $$;")


def entity_selection(graph: str, schema: str) -> str:
    candidate = view_body(graph, "ingestion.source_graph_candidate")
    _, select = candidate.split("\nSELECT q.record_id", 1)
    prefix = selection_prefix(graph, schema)
    edge = function(graph, "graph_source_edges")
    edgequery = edge.split("AS $$\n", 1)[1].rsplit("\n$$;", 1)[0]
    edgeprefix, _ = edgequery.split("\n SELECT owner_id,source_id,run_id", 1)
    edgeprefix = assessed_edges("touched AS" + edgeprefix.split("\n touched AS", 1)[1])
    # Edge rows here are used only for wanted endpoints, so the unchanged edge
    # key/digest SELECT remains in the standalone independently fresh API.
    shared = (
        prefix + ",\n " + edgeprefix + ",\n"
        " current_edges AS MATERIALIZED(SELECT from_id,to_id FROM dedup),\n"
    )
    original = function(graph, "graph_source_entities")
    # The canonical SQL edge selection now lives inside this PL/pgSQL function.
    # Its unqualified source/identity sort keys are column names, while only jobs
    # is a function input. Preserve SQL resolution for the output-name overlap.
    original = replace_once(original, "AS $$\nBEGIN", "AS $$\n#variable_conflict use_column\nBEGIN")
    original = replace_once(
        original, "\nBEGIN\n", "\nBEGIN\n PERFORM ingestion.source_graph_assert_query_contract();\n"
    )
    original = replace_once(
        original,
        "WITH current_edges AS MATERIALIZED(SELECT from_id,to_id FROM ingestion.graph_source_edges(jobs)),\n",
        shared + "\n",
    )
    original = replace_once(
        original,
        "wanted AS MATERIALIZED(SELECT DISTINCT q.identity_id FROM ingestion.source_graph_reference q WHERE q.run_id=jobs OR (jobs='ALL_CHECKPOINTED' AND EXISTS(SELECT 1 FROM ingestion.graph_export g WHERE g.run_id=q.run_id))",
        "wanted AS MATERIALIZED(SELECT q.identity_id FROM refs q JOIN target_assessments a USING(run_id) WHERE a.valid",
    )
    select = select.replace(
        "JOIN eligible_runs u ON u.run_id=r.run_id",
        "JOIN ready_runs u ON u.run_id=r.run_id\nJOIN candidate_assessments a ON a.run_id=r.run_id AND a.valid",
    )
    candidates = (
        "needed_candidate_runs AS MATERIALIZED(SELECT DISTINCT q.run_id FROM refs q JOIN wanted w USING(identity_id)),\n"
        "candidate_assessments AS MATERIALIZED(SELECT * FROM edge_assessments UNION ALL\n"
        " SELECT u.run_id,ingestion.source_graph_run_is_valid(u.run_id) FROM ready_runs u\n"
        " JOIN needed_candidate_runs n USING(run_id) WHERE NOT EXISTS(SELECT 1 FROM edge_assessments a WHERE a.run_id=u.run_id)),\n"
        "candidate_rows AS MATERIALIZED(SELECT q.record_id" + select + "),\n"
    )
    original = replace_once(
        original, "candidates AS MATERIALIZED(", candidates + "candidates AS MATERIALIZED("
    )
    original = original.replace("ingestion.source_graph_candidate c", "candidate_rows c")
    # This is the same selected READY relation used to create candidates, with
    # the same source/run/posting join and representation aggregation/order.
    return original.replace(
        "FROM ingestion.ready_record r JOIN current_facts f", "FROM records r JOIN current_facts f"
    )


def fenced_validators(checks: str, jk: str, nd: str) -> str:
    """Bind generated rules to installed originals; later hook changes fall back.

    Only definition fingerprints are bound. Every successful call still reads
    current source rows, and every writer/verifier calls independently.
    """
    local_body = function(jk, "local_file_validation_issue").split("AS $$", 1)[1].split("$$;", 1)[0]
    local_literal = "'" + local_body.replace("'", "''") + "'"
    nd_body = (
        function(nd, "jobkorea_ndjson_validation_issue").split("AS $$", 1)[1].split("$$;", 1)[0]
    )

    nd_literal = "'" + nd_body.replace("'", "''") + "'"
    collision_body = (
        function(jk, "jobkorea_cs_collision_issue").split("AS $$", 1)[1].split("$$;", 1)[0]
    )
    collision_literal = "'" + collision_body.replace("'", "''") + "'"
    shared = scoped_shared(checks).replace(
        "ingestion.source_graph_validation_issue(jobs text)",
        "ingestion.source_graph_scoped_validation_issue(jobs text)",
    )
    # Parsing the canonical view under the installed schema ensures the scoped
    # generator never silently binds an already-different shared ruleset.
    return (
        shared
        + "\n\n"
        + """DO $bind_rules$ DECLARE shared_hash text; jk_hash text; hook_hash text; nd_hash text; collision_hash text;
 wrapper text; local_wrapper text;
BEGIN
 CREATE TEMP VIEW source_query_expected_validation AS
"""
        + view_body(checks, "ingestion.validation_issue")
        + ";\n"
        + """
 IF pg_get_viewdef('source_query_expected_validation'::regclass,true)
  IS DISTINCT FROM pg_get_viewdef('ingestion.validation_issue'::regclass,true)
 THEN RAISE EXCEPTION 'SOURCE_GRAPH_CANONICAL_VALIDATION_DRIFT'; END IF;
 DROP VIEW source_query_expected_validation;
 shared_hash:=md5(pg_get_viewdef('ingestion.validation_issue'::regclass,true));
 wrapper:=$definition$
CREATE OR REPLACE FUNCTION ingestion.source_graph_validation_issue(jobs text)
RETURNS TABLE(run_id text,issue text,location text) LANGUAGE plpgsql STABLE SET jit=off AS $body$
BEGIN
 IF md5(pg_get_viewdef('ingestion.validation_issue'::regclass,true))=__SHARED_HASH__ THEN
  RETURN QUERY SELECT * FROM ingestion.source_graph_scoped_validation_issue(jobs);
 ELSE
  RETURN QUERY SELECT v.* FROM ingestion.validation_issue v WHERE v.run_id=jobs;
 END IF;
END $body$;
$definition$;
 EXECUTE replace(wrapper,'__SHARED_HASH__',quote_literal(shared_hash));
 IF to_regprocedure('ingestion.source_graph_jobkorea_validation_issue(text)') IS NOT NULL
  AND (SELECT p.prosrc FROM pg_proc p WHERE p.oid='ingestion.local_file_validation_issue()'::regprocedure)
    ="""
        + local_literal
        + "\n AND (SELECT p.prosrc FROM pg_proc p WHERE p.oid=to_regprocedure('ingestion.jobkorea_ndjson_validation_issue()'))="
        + nd_literal
        + "\n AND (SELECT p.prosrc FROM pg_proc p WHERE p.oid=to_regprocedure('ingestion.jobkorea_cs_collision_issue()'))="
        + collision_literal
        + " THEN\n"
        + """
  CREATE TEMP VIEW source_query_expected_jobkorea AS
"""
        + view_body(jk, "ingestion.jobkorea_validation_issue")
        + ";\n"
        + """
  IF pg_get_viewdef('source_query_expected_jobkorea'::regclass,true)
   IS DISTINCT FROM pg_get_viewdef('ingestion.jobkorea_validation_issue'::regclass,true)
  THEN RAISE EXCEPTION 'SOURCE_GRAPH_CANONICAL_JOBKOREA_VALIDATION_DRIFT'; END IF;
  DROP VIEW source_query_expected_jobkorea;
  jk_hash:=md5(pg_get_viewdef('ingestion.jobkorea_validation_issue'::regclass,true));
  hook_hash:=md5(pg_get_functiondef('ingestion.local_file_validation_issue()'::regprocedure));
  nd_hash:=md5(pg_get_functiondef('ingestion.jobkorea_ndjson_validation_issue()'::regprocedure));
  collision_hash:=md5(pg_get_functiondef('ingestion.jobkorea_cs_collision_issue()'::regprocedure));
 END IF;
 local_wrapper:=$definition$
CREATE OR REPLACE FUNCTION ingestion.source_graph_local_validation_issue(jobs text)
RETURNS TABLE(run_id text,issue text,location text) LANGUAGE plpgsql STABLE SET jit=off AS $body$
BEGIN
 IF __HOOK_HASH__ IS NOT NULL
  AND md5(pg_get_functiondef(to_regprocedure('ingestion.local_file_validation_issue()')))=__HOOK_HASH__
  AND md5(pg_get_viewdef(to_regclass('ingestion.jobkorea_validation_issue'),true))=__JK_HASH__
  AND md5(pg_get_functiondef(to_regprocedure('ingestion.jobkorea_ndjson_validation_issue()')))=__ND_HASH__
  AND md5(pg_get_functiondef(to_regprocedure('ingestion.jobkorea_cs_collision_issue()')))=__COLLISION_HASH__ THEN
  RETURN QUERY EXECUTE 'SELECT * FROM ingestion.source_graph_jobkorea_validation_issue($1)' USING jobs;
 ELSE
  RETURN QUERY SELECT v.* FROM ingestion.local_file_validation_issue() v WHERE v.run_id=jobs;
 END IF;
END $body$;
$definition$;
 EXECUTE replace(replace(replace(replace(local_wrapper,'__HOOK_HASH__',quote_nullable(hook_hash)),
  '__JK_HASH__',quote_nullable(jk_hash)),'__ND_HASH__',quote_nullable(nd_hash)),
  '__COLLISION_HASH__',quote_nullable(collision_hash));
END $bind_rules$;
"""
    )


def fenced_selection(graph: str, schema: str) -> str:
    """Refuse source selection when canonical view membership/branches change."""
    definitions = [
        ("ingestion.ready_record", view_body(schema, "ingestion.ready_record")),
        ("ingestion.graph_record", view_body(schema, "ingestion.graph_record")),
        ("ingestion.graph_reference", view_body(schema, "ingestion.graph_reference")),
        ("ingestion.source_graph_reference", view_body(graph, "ingestion.source_graph_reference")),
        (
            "ingestion.source_graph_live_record_evidence",
            view_body(graph, "ingestion.source_graph_live_record_evidence"),
        ),
    ]
    checks: list[str] = []
    for name, query in definitions:
        checks.append(
            "CREATE TEMP VIEW source_query_expected_selection AS\n" + query + ";\n"
            " IF pg_get_viewdef('source_query_expected_selection'::regclass,true)\n"
            " IS DISTINCT FROM pg_get_viewdef('" + name + "'::regclass,true)\n"
            " THEN\n"
            " -- pg_dump/restore can add aliases to unnamed UNION literals.\n"
            " -- Parse exactly one canonical deparse round trip as the second\n"
            " -- accepted form, without discarding any predicates or branches.\n"
            " EXECUTE 'CREATE OR REPLACE TEMP VIEW source_query_expected_selection AS '\n"
            " ||pg_get_viewdef('source_query_expected_selection'::regclass,true);\n"
            " IF pg_get_viewdef('source_query_expected_selection'::regclass,true)\n"
            " IS DISTINCT FROM pg_get_viewdef('" + name + "'::regclass,true)\n"
            " THEN RAISE EXCEPTION 'SOURCE_GRAPH_CANONICAL_SELECTION_DRIFT'; END IF;\n END IF;\n"
            " DROP VIEW source_query_expected_selection;\n"
        )
    guard = (
        "CREATE OR REPLACE FUNCTION ingestion.source_graph_assert_query_contract() RETURNS void\n"
        "LANGUAGE plpgsql STABLE SET jit=off AS $body$ BEGIN\n"
    )
    for index, (name, _) in enumerate(definitions):
        guard += (
            " IF md5(pg_get_viewdef(to_regclass('" + name + "'),true))\n"
            " IS DISTINCT FROM __VIEW" + str(index) + "__\n"
            " THEN RAISE EXCEPTION 'SOURCE_GRAPH_QUERY_CONTRACT_CHANGED'; END IF;\n"
        )
    guard += "END $body$;"
    bindings = "definition:=$definition$\n" + guard + "\n$definition$;\n"
    for index, (name, _) in enumerate(definitions):
        bindings += (
            " definition:=replace(definition,'__VIEW" + str(index) + "__',\n"
            " quote_literal(md5(pg_get_viewdef('" + name + "'::regclass,true))));\n"
        )
    return (
        "DO $selection_contract$ DECLARE definition text; BEGIN\n"
        + "\n".join(checks)
        + bindings
        + " EXECUTE definition;\nEND $selection_contract$;"
    )


def build() -> str:
    graph = (ROOT / "hop/graph/sql/002_batchfree_source_graph.sql").read_text()
    checks = (ROOT / "docs/hop-migration/checks.sql").read_text()
    jk = (ROOT / "hop/ingestions/jobkorea/sql/003_checks.sql").read_text()
    nd = (ROOT / "hop/ingestions/jobkorea/sql/006_ndjson.sql").read_text()
    schema = (ROOT / "docs/hop-migration/schema.sql").read_text()
    dates = (ROOT / "hop/graph/sql/001_posting_ingestion_dates.sql").read_text()
    collision = function(jk, "jobkorea_cs_collision_issue").replace(
        "jobkorea_cs_collision_issue()", "source_graph_jobkorea_collision_issue(jobs text)"
    )
    collision = replace_once(
        collision, "WHERE u.source_id='jobkorea'", "WHERE u.source_id='jobkorea' AND r.run_id=$1"
    )
    collision = replace_once(collision, "$query$;", "$query$ USING jobs;")
    parts = [
        "-- GENERATED by tools/build_source_queries.py; install after 002.\n"
        "-- Query-local sharing only. Public all-run validation views are unchanged.\nBEGIN;",
        collision,
        "-- JobKorea is optional. A graph-only install keeps the original fail-closed\n"
        "-- local hook; install this additive file again after its adapter is added.\n"
        "DO $optional_jobkorea$ BEGIN\n"
        " IF to_regclass('ingestion.jobkorea_import') IS NOT NULL\n"
        " AND to_regprocedure('ingestion.jobkorea_ndjson_row_manifest(text)') IS NOT NULL THEN\n"
        " EXECUTE $definition$\n" + scoped_jobkorea(jk, nd) + "\n$definition$;\n"
        " END IF;\nEND $optional_jobkorea$;",
        # Create the hook before SQL parsing the scoped shared rules. It is
        # rebound below after compatibility fingerprints are proven.
        "CREATE OR REPLACE FUNCTION ingestion.source_graph_local_validation_issue(jobs text)\n"
        "RETURNS TABLE(run_id text,issue text,location text)\n"
        "LANGUAGE sql STABLE AS $$ SELECT v.* FROM ingestion.local_file_validation_issue() v\n"
        " WHERE v.run_id=jobs $$;",
        fenced_validators(checks, jk, nd),
        fenced_selection(graph, schema),
        manifest(graph, schema),
    ]
    for name in (
        "source_graph_run_is_valid",
        "source_graph_projection_guard",
        "assert_source_graph_content",
        "begin_source_graph_projection",
    ):
        original = function(graph, name)
        original = original.replace(
            "ingestion.validation_issue WHERE run_id=jobs",
            "ingestion.source_graph_validation_issue(jobs)",
        )
        original = original.replace(
            "ingestion.validation_issue WHERE run_id=NEW.run_id",
            "ingestion.source_graph_validation_issue(NEW.run_id)",
        )
        parts.append(original)
    for name in (
        "posting_ingestion_insert_guard",
        "jobkorea_collection_time_guard",
        "record_posting_ingestion_observations",
    ):
        original = function(dates, name)
        for target in ("jobs", "u.run_id", "n.run_id"):
            original = original.replace(
                "ingestion.validation_issue v WHERE v.run_id=" + target,
                "ingestion.source_graph_validation_issue(" + target + ") v",
            )
        parts.append(original)
    parts += [edge_selection(graph, schema), entity_selection(graph, schema), "COMMIT;\n"]
    result = "\n\n".join(parts)
    OUTPUT.write_text(result)
    return result


if __name__ == "__main__":
    build()
