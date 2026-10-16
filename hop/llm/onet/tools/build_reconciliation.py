"""Generate the additive, separately qualified pre-dispatch accounting successor."""

# Audited SQL literals and original function bytes are retained exactly.
# ruff: noqa: E501
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as E
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / "hop/llm/onet"

HEADER = r"""
-- Additive reviewed reconciliation; original terminal cost/response/history stays exact.
BEGIN;
SELECT retention.gate();
CREATE TABLE IF NOT EXISTS onet_matching.no_dispatch_reconciliation (
 reconciliation_id text PRIMARY KEY, attempt_id text NOT NULL UNIQUE REFERENCES onet_matching.attempt,
 response_sha256 text NOT NULL CHECK(response_sha256 ~ '^[0-9a-f]{64}$'),
 effective_cost_usd numeric NOT NULL CHECK(effective_cost_usd=0),
 basis text NOT NULL CHECK(basis='OPENROUTER_PRE_DISPATCH_PARAMETER_FILTER'),
 actor text NOT NULL CHECK(length(btrim(actor))>0), notes text NOT NULL CHECK(length(btrim(notes))>0),
 evidence jsonb NOT NULL CHECK(jsonb_typeof(evidence)='object'),
 reconciled_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS onet_matching.task_stop (
 task_id text PRIMARY KEY REFERENCES onet_matching.task, actor text NOT NULL CHECK(length(btrim(actor))>0),
 notes text NOT NULL CHECK(length(btrim(notes))>0), stopped_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
DO $install$ DECLARE tab text; BEGIN
 FOREACH tab IN ARRAY ARRAY['no_dispatch_reconciliation','task_stop'] LOOP
  EXECUTE format('DROP TRIGGER IF EXISTS immutable_history ON onet_matching.%I',tab);
  EXECUTE format('CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON onet_matching.%I FOR EACH ROW EXECUTE FUNCTION onet_matching.immutable()',tab);
  EXECUTE format('DROP TRIGGER IF EXISTS immutable_truncate ON onet_matching.%I',tab);
  EXECUTE format('CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON onet_matching.%I FOR EACH STATEMENT EXECUTE FUNCTION onet_matching.immutable()',tab);
  EXECUTE format('DROP TRIGGER IF EXISTS retention_freeze ON onet_matching.%I',tab);
  EXECUTE format('CREATE TRIGGER retention_freeze BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON onet_matching.%I FOR EACH STATEMENT EXECUTE FUNCTION retention.freeze_writes()',tab);
 END LOOP;
END $install$;

-- Exact Python 3.12 str.strip() Unicode whitespace set. Raw quote lengths stay
-- unchanged: only the nonblank check uses trimming, as in the pinned Python code.
CREATE OR REPLACE FUNCTION onet_matching.python_strip(value text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$
 SELECT btrim(value,(SELECT string_agg(chr(code),'') FROM unnest(ARRAY[
  9,10,11,12,13,28,29,30,31,32,133,160,5760,8192,8193,8194,8195,8196,8197,8198,
  8199,8200,8201,8202,8232,8233,8239,8287,12288]) code))
$$;
CREATE OR REPLACE VIEW onet_matching.accounted_attempt AS
 SELECT a.*,coalesce(a.cost_usd,r.effective_cost_usd) AS effective_cost_usd,r.reconciliation_id
 FROM onet_matching.attempt a LEFT JOIN onet_matching.no_dispatch_reconciliation r USING(attempt_id);

CREATE OR REPLACE FUNCTION onet_matching.no_dispatch_response_issue(status integer,body text) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE envelope jsonb; funnel jsonb; entry jsonb; ordinal integer:=0; previous integer:=2147483647; count_now integer;
 expected text[]:=ARRAY['Initial Endpoints','Filter by Regional Surcharge','Filter by Tier Endpoint Rows','Filter by Allowed Providers'];
BEGIN
 IF status IS DISTINCT FROM 404 OR NOT coalesce(body IS JSON OBJECT WITH UNIQUE KEYS,false)
 THEN RETURN 'NOT_EVIDENCED_PRE_DISPATCH_404'; END IF;
 envelope:=body::jsonb;
 IF (SELECT count(*) FROM jsonb_object_keys(envelope))<>1 OR NOT envelope ? 'error'
  OR jsonb_typeof(envelope->'error') IS DISTINCT FROM 'object' THEN RETURN 'NOT_ROUTER_ONLY_ERROR'; END IF;
 IF envelope#>'{error,code}' IS DISTINCT FROM '404'::jsonb
  OR strpos(coalesce(envelope#>>'{error,message}',''),'No endpoints found that can handle the requested parameters.') IS DISTINCT FROM 1
  OR envelope#>>'{error,metadata,failed_routing_step}' IS DISTINCT FROM 'Filter by Parameters'
  OR jsonb_typeof(envelope#>'{error,metadata}') IS DISTINCT FROM 'object'
 THEN RETURN 'NOT_PARAMETER_FILTER_NO_ENDPOINT'; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_object_keys(envelope->'error') k WHERE k NOT IN('message','code','metadata'))
  OR EXISTS(SELECT 1 FROM jsonb_object_keys(envelope#>'{error,metadata}') k WHERE k NOT IN('routing_funnel','failed_routing_step'))
 THEN RETURN 'UNEXPECTED_ROUTING_OR_PROVIDER_EVIDENCE'; END IF;
 funnel:=envelope#>'{error,metadata,routing_funnel}';
 IF jsonb_typeof(funnel) IS DISTINCT FROM 'array' OR jsonb_array_length(funnel)<>4 THEN RETURN 'ROUTING_FUNNEL_REQUIRED'; END IF;
 FOR entry IN SELECT value FROM jsonb_array_elements(funnel) LOOP
  ordinal:=ordinal+1;
  IF jsonb_typeof(entry) IS DISTINCT FROM 'object' OR entry->>'step' IS DISTINCT FROM expected[ordinal]
   OR coalesce(entry->>'endpoint_count','') !~ '^[1-9][0-9]{0,3}$'
   OR EXISTS(SELECT 1 FROM jsonb_object_keys(entry) k WHERE k NOT IN('step','endpoint_count','reason'))
  THEN RETURN 'ROUTING_FUNNEL_NOT_EXACT_PRE_DISPATCH_SHAPE'; END IF;
  count_now:=(entry->>'endpoint_count')::integer;
  IF count_now>previous OR ordinal=4 AND count_now<>1 THEN RETURN 'ROUTING_FUNNEL_COUNTS_INCONSISTENT'; END IF;
  previous:=count_now;
 END LOOP;
 RETURN NULL;
EXCEPTION WHEN OTHERS THEN RETURN 'INVALID_ROUTING_EVIDENCE';
END $$;
CREATE OR REPLACE FUNCTION onet_matching.reconcile_no_dispatch(aid text,response_hash text,actor text,notes text,evidence jsonb)
RETURNS jsonb LANGUAGE plpgsql SET jit=off AS $$
DECLARE a onet_matching.attempt; t onet_matching.task; i onet_matching.input; r onet_matching.no_dispatch_reconciliation;
 issue text; digest text; id text; before_at timestamptz; after_at timestamptz; key text;
BEGIN
 PERFORM retention.gate(); PERFORM pg_advisory_xact_lock(hashtextextended('jobtology-onet-matching-accounting',0));
 SELECT * INTO STRICT a FROM onet_matching.attempt WHERE attempt_id=aid FOR UPDATE;
 SELECT * INTO STRICT t FROM onet_matching.task WHERE task_id=a.task_id;
 SELECT * INTO STRICT i FROM onet_matching.input WHERE task_id=a.task_id AND posting_identity=a.posting_identity;
 digest:=encode(sha256(convert_to(a.response_body,'UTF8')),'hex');
 IF a.state IS DISTINCT FROM 'ERROR' OR a.http_status IS DISTINCT FROM 404 OR a.reserved_at IS NULL
  OR a.cost_usd IS NOT NULL OR a.response_id IS NOT NULL OR a.actual_model IS NOT NULL OR a.provider IS NOT NULL
  OR a.router_cost_usd IS NOT NULL OR a.upstream_cost_usd IS NOT NULL OR a.prompt_tokens IS NOT NULL
  OR a.completion_tokens IS NOT NULL OR a.parsed_output IS NOT NULL
  OR response_hash IS DISTINCT FROM digest
  OR t.settings->>'endpoint' IS DISTINCT FROM 'https://openrouter.ai/api/v1/chat/completions'
  OR i.request_body->>'model' IS DISTINCT FROM 'openai/gpt-5.6-luna'
  OR i.request_body#>'{provider,only}' IS DISTINCT FROM '["openai"]'::jsonb
  OR i.request_body#>'{provider,allow_fallbacks}' IS DISTINCT FROM 'false'::jsonb
  OR i.request_body#>'{provider,require_parameters}' IS DISTINCT FROM 'true'::jsonb
 THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_REQUIRES_EXACT_UNCHARGED_ROUTER_ATTEMPT'; END IF;
 issue:=onet_matching.no_dispatch_response_issue(a.http_status,a.response_body);
 IF issue IS NOT NULL THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_NOT_NO_DISPATCH: %',issue; END IF;
 IF nullif(onet_matching.python_strip(actor),'') IS NULL OR nullif(onet_matching.python_strip(notes),'') IS NULL
  OR jsonb_typeof(evidence) IS DISTINCT FROM 'object' OR NOT evidence ?& ARRAY[
   'basis','response_export_sha256','accounting_before_sha256','accounting_after_sha256',
   'accounting_before_basis','checked_before_at','checked_after_at','router_usage_before_usd',
   'router_usage_after_usd','byok_usage_before_usd','byok_usage_after_usd']
  OR evidence->>'basis' IS DISTINCT FROM 'OPENROUTER_PRE_DISPATCH_PARAMETER_FILTER'
  OR evidence->>'accounting_before_basis' IS DISTINCT FROM 'RETAINED_TOOL_RESPONSE_TRANSCRIPT'
 THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_INVALID_REVIEW_EVIDENCE'; END IF;
 FOREACH key IN ARRAY ARRAY['response_export_sha256','accounting_before_sha256','accounting_after_sha256'] LOOP
  IF coalesce(evidence->>key,'') !~ '^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_INVALID_REVIEW_EVIDENCE'; END IF;
 END LOOP;
 FOREACH key IN ARRAY ARRAY['router_usage_before_usd','router_usage_after_usd','byok_usage_before_usd','byok_usage_after_usd'] LOOP
  IF coalesce(evidence->>key,'') !~ '^[0-9]{1,20}(\.[0-9]{1,20})?$' THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_INVALID_REVIEW_EVIDENCE'; END IF;
 END LOOP;
 BEGIN
  before_at:=(evidence->>'checked_before_at')::timestamptz; after_at:=(evidence->>'checked_after_at')::timestamptz;
 EXCEPTION WHEN OTHERS THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_INVALID_REVIEW_EVIDENCE'; END;
 IF before_at IS NULL OR after_at IS NULL OR before_at>=a.reserved_at OR after_at<a.completed_at
  OR (evidence->>'router_usage_before_usd')::numeric<>(evidence->>'router_usage_after_usd')::numeric
  OR (evidence->>'byok_usage_before_usd')::numeric<>(evidence->>'byok_usage_after_usd')::numeric
 THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_COUNTERS_OR_OBSERVATION_TIMES_INCONSISTENT'; END IF;
 id:=onet_matching.hash(jsonb_build_array('reviewed-no-dispatch-v1',aid,digest,actor,notes,evidence));
 SELECT * INTO r FROM onet_matching.no_dispatch_reconciliation WHERE attempt_id=aid;
 IF FOUND AND r.reconciliation_id<>id THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_IS_IMMUTABLE'; END IF;
 INSERT INTO onet_matching.no_dispatch_reconciliation(reconciliation_id,attempt_id,response_sha256,effective_cost_usd,basis,actor,notes,evidence)
 VALUES(id,aid,digest,0,'OPENROUTER_PRE_DISPATCH_PARAMETER_FILTER',actor,notes,evidence) ON CONFLICT DO NOTHING;
 RETURN jsonb_build_object('reconciliation_id',id,'attempt_id',aid,'response_sha256',digest,'effective_cost_usd',0,
  'original_cost_usd',a.cost_usd,'original_state',a.state,'basis','OPENROUTER_PRE_DISPATCH_PARAMETER_FILTER');
END $$;
CREATE OR REPLACE FUNCTION onet_matching.stop_task(id text,actor text,notes text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE token uuid; BEGIN
 PERFORM retention.gate(); PERFORM pg_advisory_xact_lock(hashtextextended('jobtology-onet-matching-accounting',0));
 IF nullif(onet_matching.python_strip(actor),'') IS NULL OR nullif(onet_matching.python_strip(notes),'') IS NULL
 THEN RAISE EXCEPTION 'ONET_MATCHING_TASK_STOP_REQUIRES_REVIEW'; END IF;
 INSERT INTO onet_matching.task_stop(task_id,actor,notes) VALUES(id,actor,notes) ON CONFLICT DO NOTHING;
 FOR token IN SELECT e.execution_token FROM onet_matching.execution e JOIN onet_matching.batch b USING(batch_id)
  WHERE b.task_id=id AND NOT EXISTS(SELECT 1 FROM onet_matching.execution_end finish WHERE finish.execution_token=e.execution_token) LOOP
  INSERT INTO onet_matching.execution_stop(execution_token,reason) VALUES(token,'TASK_ABANDONED_BY_COORDINATOR') ON CONFLICT DO NOTHING;
 END LOOP;
 RETURN onet_matching.task_status(id);
END $$;
"""


def original(name: str, filename: str) -> str:
    match = re.search(
        r"CREATE OR REPLACE FUNCTION onet_matching\." + name + r"\(.*?\$\$;",
        (OUT / "sql" / filename).read_text(),
        re.DOTALL,
    )
    assert match, name
    return match.group()


def body_hash(source: str) -> str:
    return hashlib.md5(source.split("$$", 2)[1].encode(), usedforsecurity=False).hexdigest()


def exact_native_variant(source: str) -> str:
    # Match the measured Hop SQL parser variant, without normalizing arbitrary
    # installed bodies. Only these two sealed comment lines are elided.
    for comment in (
        " -- Never reserve the entire cohort. Each worker reserves only its next POST.",
        " -- Same frozen paid request cannot be retried under a fresh task identity.",
    ):
        assert source.count(comment + "\n") == 1
        source = source.replace(comment + "\n", " \n")
    return source


def generate() -> None:
    upgrades = []
    for name, signature, filename in (
        ("task_status", "text", "001_matching.sql"),
        ("batch_status", "text", "001_matching.sql"),
        ("start_execution", "text,integer,boolean", "001_matching.sql"),
        ("request_context", "text,uuid", "001_matching.sql"),
        ("admit_request", "text,uuid", "001_matching.sql"),
        ("approve_scale", "text,text,text", "001_matching.sql"),
        ("eligible_inputs", "text", "002_results.sql"),
        ("output_issues", "jsonb,jsonb,jsonb,integer", "002_results.sql"),
    ):
        base = original(name, filename)
        new = base
        if name == "output_issues":
            new = new.replace("btrim(", "onet_matching.python_strip(")
        else:
            new = new.replace("FROM onet_matching.attempt", "FROM onet_matching.accounted_attempt")
            new = new.replace(
                "SELECT * INTO STRICT a FROM onet_matching.accounted_attempt",
                "SELECT * INTO STRICT a FROM onet_matching.attempt",
            )
            new = re.sub(r"(?<![A-Za-z0-9_'])cost_usd(?![A-Za-z0-9_'])", "effective_cost_usd", new)
        if name == "task_status":
            new = new.replace(
                "'scale_approved',",
                "'state',CASE WHEN EXISTS(SELECT 1 FROM onet_matching.task_stop WHERE task_id=id) THEN 'STOPPED' ELSE 'ACTIVE' END,'no_dispatch_reconciliations',(SELECT count(*) FROM onet_matching.no_dispatch_reconciliation r JOIN onet_matching.attempt a USING(attempt_id) WHERE a.task_id=id),'scale_approved',",
            )
        elif name == "start_execution":
            new = new.replace(
                "PERFORM onet_matching.assert_catalog(t.release_id,t.database_id);",
                "PERFORM onet_matching.assert_catalog(t.release_id,t.database_id);\n IF EXISTS(SELECT 1 FROM onet_matching.task_stop WHERE task_id=t.task_id) THEN RAISE EXCEPTION 'ONET_MATCHING_TASK_STOPPED'; END IF;",
            )
        elif name == "request_context":
            new = new.replace(
                "IF NOT FOUND THEN RETURN NULL; END IF;",
                "IF NOT FOUND THEN RETURN NULL; END IF;\n IF EXISTS(SELECT 1 FROM onet_matching.task_stop WHERE task_id=t.task_id) THEN RETURN NULL; END IF;",
            )
            new = new.replace(
                "x.is_byok IS DISTINCT FROM true",
                "(x.is_byok IS DISTINCT FROM true AND x.reconciliation_id IS NULL)",
            )
        elif name == "approve_scale":
            new = new.replace(
                "IF accounting IS NULL OR",
                "IF accounting IS NULL OR EXISTS(SELECT 1 FROM onet_matching.task_stop WHERE task_id=id) OR",
            )
            new = new.replace(
                "a.reserved_at IS NOT NULL\n    AND (",
                "a.reserved_at IS NOT NULL AND a.reconciliation_id IS NULL\n    AND (",
            )
        elif name == "eligible_inputs":
            new = new.replace(
                "WHERE i.task_id=id AND",
                "WHERE i.task_id=id AND NOT EXISTS(SELECT 1 FROM onet_matching.task_stop WHERE task_id=id) AND",
            )
        upgrades.append((name, signature, base, new))
    guard = "DO $qualified_base$ BEGIN\n"
    for name, signature, base, new in upgrades:
        hashes = [body_hash(base), body_hash(new)]
        if name == "admit_request":
            hashes += [body_hash(exact_native_variant(base)), body_hash(exact_native_variant(new))]
            assert hashes[2] == "dc1c58b84d2f33a32b0cf9f5c953171f"
        quoted_hashes = ",".join("'" + value + "'" for value in hashes)
        guard += f" IF NOT EXISTS(SELECT 1 FROM pg_proc WHERE oid=to_regprocedure('onet_matching.{name}({signature})') AND md5(prosrc) IN({quoted_hashes})) THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_BASE_DRIFT: {name}'; END IF;\n"
    guard += "END $qualified_base$;\n"
    # The guard precedes every mutation; exact replay admits only original or
    # independently qualified successor bodies, never arbitrary replacements.
    header = HEADER
    function_start = header.index("CREATE OR REPLACE FUNCTION onet_matching.reconcile_no_dispatch(")
    body_start = header.index("DECLARE a onet_matching.attempt;", function_start)
    review_end = header.index(
        " id:=onet_matching.hash(jsonb_build_array('reviewed-no-dispatch-v1'", body_start
    )
    helper = "CREATE OR REPLACE FUNCTION onet_matching.assert_no_dispatch_reconciliation(aid text,response_hash text,actor text,notes text,evidence jsonb) RETURNS void LANGUAGE plpgsql SET jit=off AS $$\n"
    helper += header[body_start:review_end] + " RETURN;\nEND $$;\n"
    # Callable and table-level paths use the same complete evidence validator.
    # Direct INSERT cannot release an unrelated unknown/transport charge hold.
    header = (
        header[:function_start]
        + helper
        + header[function_start:body_start]
        + "DECLARE a onet_matching.attempt; r onet_matching.no_dispatch_reconciliation; digest text; id text;\nBEGIN\n PERFORM onet_matching.assert_no_dispatch_reconciliation(aid,response_hash,actor,notes,evidence);\n SELECT * INTO STRICT a FROM onet_matching.attempt WHERE attempt_id=aid;\n digest:=encode(sha256(convert_to(a.response_body,'UTF8')),'hex');\n"
        + header[review_end:]
    )
    trigger = """
CREATE OR REPLACE FUNCTION onet_matching.reconciliation_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM onet_matching.assert_no_dispatch_reconciliation(NEW.attempt_id,NEW.response_sha256,NEW.actor,NEW.notes,NEW.evidence);
 IF NEW.effective_cost_usd IS DISTINCT FROM 0 OR NEW.basis IS DISTINCT FROM 'OPENROUTER_PRE_DISPATCH_PARAMETER_FILTER'
  OR NEW.reconciliation_id IS DISTINCT FROM onet_matching.hash(jsonb_build_array('reviewed-no-dispatch-v1',
    NEW.attempt_id,NEW.response_sha256,NEW.actor,NEW.notes,NEW.evidence))
 THEN RAISE EXCEPTION 'ONET_MATCHING_RECONCILIATION_INSERT_NOT_VERIFIED'; END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER verified_reconciliation_insert BEFORE INSERT ON onet_matching.no_dispatch_reconciliation
 FOR EACH ROW EXECUTE FUNCTION onet_matching.reconciliation_insert_guard();
"""
    header += trigger
    sql = header.replace("SELECT retention.gate();", "SELECT retention.gate();\n" + guard, 1)
    sql += "\n".join(new for _, _, _, new in upgrades) + "\nCOMMIT;\n"
    (OUT / "sql/005_no_dispatch_reconciliation.sql").write_text(sql)
    root = E.parse(OUT / "install.hwf").getroot()
    root.find("name").text = "Install separately qualified O*NET no-dispatch reconciliation"
    actions = root.find("actions")
    hops = root.find("hops")
    assert actions is not None and hops is not None
    template = deepcopy(next(action for action in actions if action.findtext("type") == "SQL"))
    for action in list(actions):
        if action.findtext("type") == "SQL":
            actions.remove(action)
    template.find("name").text = "005_no_dispatch_reconciliation"
    template.find(
        "sqlfilename"
    ).text = "${PROJECT_HOME}/llm/onet/sql/005_no_dispatch_reconciliation.sql"
    actions.append(template)
    hops.clear()
    for source, target, outcome, unconditional in (
        ("Start", "005_no_dispatch_reconciliation", "Y", "Y"),
        ("005_no_dispatch_reconciliation", "Success", "Y", "N"),
        ("005_no_dispatch_reconciliation", "Abort", "N", "N"),
    ):
        hop = E.SubElement(hops, "hop")
        for key, value in (
            ("from", source),
            ("to", target),
            ("enabled", "Y"),
            ("evaluation", outcome),
            ("unconditional", unconditional),
        ):
            E.SubElement(hop, key).text = value
    E.indent(root, space="  ")
    E.ElementTree(root).write(
        OUT / "install_reconciliation.hwf", encoding="UTF-8", xml_declaration=True
    )


if __name__ == "__main__":
    generate()
