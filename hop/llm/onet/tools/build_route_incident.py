"""Generate a narrow additive known-router/bounded-upstream route recovery."""

# Native SQL literals and guard hashes are intentionally explicit.
# ruff: noqa: E501
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as E
from pathlib import Path

OUT = Path(__file__).resolve().parents[1]

HEADER = r"""-- Reviewed router fallback incident; unknown first BYOK exposure stays conservatively held.
BEGIN;
SELECT retention.gate();
CREATE TABLE IF NOT EXISTS onet_matching.route_incident_acknowledgement (
 acknowledgement_id text PRIMARY KEY, attempt_id text NOT NULL UNIQUE REFERENCES onet_matching.attempt,
 response_sha256 text NOT NULL CHECK(response_sha256 ~ '^[0-9a-f]{64}$'),
 attempt_hash text NOT NULL, input_hash text NOT NULL, settings_hash text NOT NULL,
 known_router_cost_usd numeric NOT NULL CHECK(known_router_cost_usd>0),
 total_accounting_bound_usd numeric NOT NULL CHECK(total_accounting_bound_usd>=known_router_cost_usd),
 provisional_exposure_usd numeric NOT NULL CHECK(provisional_exposure_usd=total_accounting_bound_usd-known_router_cost_usd),
 pinned_byok_cost_bound_usd numeric NOT NULL CHECK(pinned_byok_cost_bound_usd>0),
 basis text NOT NULL CHECK(basis='REVIEWED_KNOWN_ROUTER_BOUNDED_BYOK_EXPOSURE'),
 actor text NOT NULL CHECK(length(btrim(actor))>0), notes text NOT NULL CHECK(length(btrim(notes))>0),
 evidence jsonb NOT NULL CHECK(jsonb_typeof(evidence)='object'),
 acknowledged_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE OR REPLACE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON onet_matching.route_incident_acknowledgement
 FOR EACH ROW EXECUTE FUNCTION onet_matching.immutable();
CREATE OR REPLACE TRIGGER immutable_truncate BEFORE TRUNCATE ON onet_matching.route_incident_acknowledgement
 FOR EACH STATEMENT EXECUTE FUNCTION onet_matching.immutable();
CREATE OR REPLACE TRIGGER retention_freeze BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON onet_matching.route_incident_acknowledgement
 FOR EACH STATEMENT EXECUTE FUNCTION retention.freeze_writes();

CREATE OR REPLACE FUNCTION onet_matching.assert_route_incident_acknowledgement(aid text,response_hash text,actor text,notes text,evidence jsonb)
RETURNS numeric LANGUAGE plpgsql SET jit=off AS $$
DECLARE a onet_matching.attempt; t onet_matching.task; i onet_matching.input;
 envelope jsonb; generation jsonb; attestation jsonb; confirmed_at timestamptz; bound numeric;
BEGIN
 PERFORM retention.gate(); PERFORM pg_advisory_xact_lock(hashtextextended('jobtology-onet-matching-accounting',0));
 SELECT * INTO STRICT a FROM onet_matching.attempt WHERE attempt_id=aid FOR UPDATE;
 SELECT * INTO STRICT t FROM onet_matching.task WHERE task_id=a.task_id;
 SELECT * INTO STRICT i FROM onet_matching.input WHERE task_id=a.task_id AND posting_identity=a.posting_identity;
 IF a.state IS DISTINCT FROM 'REJECTED' OR a.http_status IS DISTINCT FROM 200
  OR a.issues IS DISTINCT FROM '["EXPECTED_OPENAI_BYOK_ROUTE"]'::jsonb OR a.is_byok IS DISTINCT FROM false
  OR a.reserved_at IS NULL OR a.completed_at IS NULL OR a.response_id IS NULL
  OR a.actual_model IS DISTINCT FROM 'openai/gpt-5.6-luna' OR lower(a.provider) IS DISTINCT FROM 'openai'
  OR a.cost_usd IS NULL OR a.cost_usd<=0 OR a.router_cost_usd IS DISTINCT FROM a.cost_usd
  OR a.reserve_usd IS NULL OR a.parsed_output IS NULL
  OR response_hash IS DISTINCT FROM encode(sha256(convert_to(a.response_body,'UTF8')),'hex')
  OR NOT coalesce(a.response_body IS JSON OBJECT WITH UNIQUE KEYS,false)
  OR i.request_body->>'model' IS DISTINCT FROM 'openai/gpt-5.6-luna'
  OR i.request_body->'stream' IS DISTINCT FROM 'false'::jsonb
  OR i.request_body#>'{provider,only}' IS DISTINCT FROM '["openai"]'::jsonb
  OR i.request_body#>'{provider,allow_fallbacks}' IS DISTINCT FROM 'false'::jsonb
  OR i.request_body#>'{provider,require_parameters}' IS DISTINCT FROM 'true'::jsonb
  OR i.request_body#>'{provider,max_price,prompt}' IS DISTINCT FROM '0.20'::jsonb
  OR i.request_body#>'{provider,max_price,completion}' IS DISTINCT FROM '1.20'::jsonb
  OR i.request_body->'max_tokens' IS DISTINCT FROM t.settings->'max_output_tokens'
  OR onet_matching.schema_issues(a.parsed_output,i.request_body#>'{response_format,json_schema,schema}')<>'[]'::jsonb
  OR onet_matching.output_issues(a.parsed_output,i.source_fields,i.candidates,(t.settings->>'max_matches')::integer)<>'[]'::jsonb
 THEN RAISE EXCEPTION 'ONET_MATCHING_ROUTE_ACK_REQUIRES_EXACT_FULLY_COSTED_ROUTE_REJECTION'; END IF;
 envelope:=a.response_body::jsonb;
 IF envelope->>'id' IS DISTINCT FROM a.response_id OR envelope->>'model' IS DISTINCT FROM a.actual_model
  OR lower(envelope->>'provider') IS DISTINCT FROM 'openai'
  OR envelope#>'{usage,is_byok}' IS DISTINCT FROM 'false'::jsonb
  OR envelope#>'{usage,cost}' IS DISTINCT FROM to_jsonb(a.cost_usd)
  OR onet_matching.response_cost(envelope) IS DISTINCT FROM a.cost_usd
 THEN RAISE EXCEPTION 'ONET_MATCHING_ROUTE_ACK_RESPONSE_ACCOUNTING_MISMATCH'; END IF;
 IF nullif(onet_matching.python_strip(actor),'') IS NULL OR nullif(onet_matching.python_strip(notes),'') IS NULL
  OR jsonb_typeof(evidence) IS DISTINCT FROM 'object'
  OR evidence->>'basis' IS DISTINCT FROM 'REVIEWED_KNOWN_ROUTER_BOUNDED_BYOK_EXPOSURE'
  OR evidence->>'user_attestation_sha256' !~ '^[0-9a-f]{64}$'
  OR evidence->>'generation_sha256' !~ '^[0-9a-f]{64}$'
  OR evidence->>'user_attestation_sha256' IS DISTINCT FROM encode(sha256(convert_to(evidence->>'user_attestation_body','UTF8')),'hex')
  OR evidence->>'generation_sha256' IS DISTINCT FROM encode(sha256(convert_to(evidence->>'generation_body','UTF8')),'hex')
  OR NOT coalesce((evidence->>'user_attestation_body') IS JSON OBJECT WITH UNIQUE KEYS,false)
  OR NOT coalesce((evidence->>'generation_body') IS JSON OBJECT WITH UNIQUE KEYS,false)
 THEN RAISE EXCEPTION 'ONET_MATCHING_ROUTE_ACK_INVALID_IMMUTABLE_EVIDENCE'; END IF;
 attestation:=(evidence->>'user_attestation_body')::jsonb;
 generation:=(evidence->>'generation_body')::jsonb->'data';
 IF attestation->>'evidence_kind' IS DISTINCT FROM 'USER_REPORTED_ACCOUNT_SETTING_CHANGE'
  OR attestation->>'provider' IS DISTINCT FROM 'openai'
  OR attestation->>'setting' IS DISTINCT FROM 'Shared capacity fallback'
  OR attestation->>'requested_value' IS DISTINCT FROM 'Never use shared capacity for any model on this provider'
  OR attestation->>'user_reply' IS DISTINCT FROM 'Saved the BYOK-only setting'
  OR attestation->'credentials_changed_by_agent' IS DISTINCT FROM 'false'::jsonb
  OR attestation->'independent_management_api_readback' IS DISTINCT FROM 'false'::jsonb
 THEN RAISE EXCEPTION 'ONET_MATCHING_ROUTE_ACK_REQUIRES_USER_REPORTED_BYOK_ONLY_SETTING'; END IF;
 BEGIN confirmed_at:=(attestation->>'recorded_at')::timestamptz;
 EXCEPTION WHEN OTHERS THEN RAISE EXCEPTION 'ONET_MATCHING_ROUTE_ACK_INVALID_CONFIRMATION_TIME'; END;
 IF confirmed_at IS NULL OR confirmed_at<a.completed_at OR confirmed_at>clock_timestamp()
 THEN RAISE EXCEPTION 'ONET_MATCHING_ROUTE_ACK_INVALID_CONFIRMATION_TIME'; END IF;
 IF jsonb_typeof(generation) IS DISTINCT FROM 'object' OR generation->>'id' IS DISTINCT FROM a.response_id
  OR generation->'is_byok' IS DISTINCT FROM 'false'::jsonb
  OR generation->>'provider_name' IS DISTINCT FROM 'OpenAI'
  OR generation->>'model' IS DISTINCT FROM 'openai/gpt-5.6-luna-20260709'
  OR generation->'total_cost' IS DISTINCT FROM to_jsonb(a.cost_usd)
  OR generation->'upstream_inference_cost' IS DISTINCT FROM '0'::jsonb
  OR jsonb_typeof(generation->'provider_responses') IS DISTINCT FROM 'array'
 THEN RAISE EXCEPTION 'ONET_MATCHING_ROUTE_ACK_REQUIRES_EXACT_TWO_ROUTE_GENERATION'; END IF;
 IF jsonb_array_length(generation->'provider_responses')<>2
  OR generation#>'{provider_responses,0,is_byok}' IS DISTINCT FROM 'true'::jsonb
  OR generation#>'{provider_responses,0,status}' IS DISTINCT FROM '504'::jsonb
  OR generation#>>'{provider_responses,0,provider_name}' IS DISTINCT FROM 'OpenAI'
  OR generation#>>'{provider_responses,0,model_permaslug}' IS DISTINCT FROM generation->>'model'
  OR generation#>'{provider_responses,1,is_byok}' IS DISTINCT FROM 'false'::jsonb
  OR generation#>'{provider_responses,1,status}' IS DISTINCT FROM '200'::jsonb
  OR generation#>>'{provider_responses,1,provider_name}' IS DISTINCT FROM 'OpenAI'
  OR generation#>>'{provider_responses,1,model_permaslug}' IS DISTINCT FROM generation->>'model'
  OR generation#>>'{provider_responses,0,endpoint_id}' IS NULL
  OR generation#>>'{provider_responses,0,endpoint_id}' IS DISTINCT FROM generation#>>'{provider_responses,1,endpoint_id}'
 THEN RAISE EXCEPTION 'ONET_MATCHING_ROUTE_ACK_REQUIRES_EXACT_TWO_ROUTE_GENERATION'; END IF;
 bound:=1.05*(0.25*(octet_length(i.request_body::text)+256)+1.20*(t.settings->>'max_output_tokens')::integer)/1000000;
 IF bound<=0 OR bound+a.cost_usd>a.reserve_usd OR a.reserve_usd IS DISTINCT FROM (t.settings->>'request_reserve_usd')::numeric
 THEN RAISE EXCEPTION 'ONET_MATCHING_ROUTE_ACK_UPSTREAM_EXPOSURE_NOT_BOUNDED'; END IF;
 RETURN bound;
END $$;

CREATE OR REPLACE FUNCTION onet_matching.acknowledge_route_incident(aid text,response_hash text,actor text,notes text,evidence jsonb)
RETURNS jsonb LANGUAGE plpgsql SET jit=off AS $$
DECLARE a onet_matching.attempt; i onet_matching.input; t onet_matching.task;
 existing onet_matching.route_incident_acknowledgement; bound numeric; id text; attempt_digest text;
BEGIN
 bound:=onet_matching.assert_route_incident_acknowledgement(aid,response_hash,actor,notes,evidence);
 SELECT * INTO STRICT a FROM onet_matching.attempt WHERE attempt_id=aid;
 SELECT * INTO STRICT i FROM onet_matching.input WHERE task_id=a.task_id AND posting_identity=a.posting_identity;
 SELECT * INTO STRICT t FROM onet_matching.task WHERE task_id=a.task_id;
 attempt_digest:=onet_matching.hash(to_jsonb(a));
 id:=onet_matching.hash(jsonb_build_array('reviewed-route-incident-v1',aid,response_hash,attempt_digest,i.input_hash,t.settings_hash,a.cost_usd,a.reserve_usd,bound,actor,notes,evidence));
 SELECT * INTO existing FROM onet_matching.route_incident_acknowledgement WHERE attempt_id=aid;
 IF FOUND AND existing.acknowledgement_id<>id THEN RAISE EXCEPTION 'ONET_MATCHING_ROUTE_ACK_IS_IMMUTABLE'; END IF;
 INSERT INTO onet_matching.route_incident_acknowledgement(acknowledgement_id,attempt_id,response_sha256,attempt_hash,input_hash,settings_hash,known_router_cost_usd,total_accounting_bound_usd,provisional_exposure_usd,pinned_byok_cost_bound_usd,basis,actor,notes,evidence)
 VALUES(id,aid,response_hash,attempt_digest,i.input_hash,t.settings_hash,a.cost_usd,a.reserve_usd,a.reserve_usd-a.cost_usd,bound,'REVIEWED_KNOWN_ROUTER_BOUNDED_BYOK_EXPOSURE',actor,notes,evidence) ON CONFLICT DO NOTHING;
 RETURN jsonb_build_object('acknowledgement_id',id,'attempt_id',aid,'original_state',a.state,'known_router_cost_usd',a.cost_usd,'total_accounting_bound_usd',a.reserve_usd,'provisional_exposure_usd',a.reserve_usd-a.cost_usd,'pinned_byok_cost_bound_usd',bound,'basis','REVIEWED_KNOWN_ROUTER_BOUNDED_BYOK_EXPOSURE');
END $$;
CREATE OR REPLACE FUNCTION onet_matching.route_incident_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE a onet_matching.attempt; i onet_matching.input; t onet_matching.task; bound numeric; attempt_digest text;
BEGIN
 bound:=onet_matching.assert_route_incident_acknowledgement(NEW.attempt_id,NEW.response_sha256,NEW.actor,NEW.notes,NEW.evidence);
 SELECT * INTO STRICT a FROM onet_matching.attempt WHERE attempt_id=NEW.attempt_id;
 SELECT * INTO STRICT i FROM onet_matching.input WHERE task_id=a.task_id AND posting_identity=a.posting_identity;
 SELECT * INTO STRICT t FROM onet_matching.task WHERE task_id=a.task_id;
 attempt_digest:=onet_matching.hash(to_jsonb(a));
 IF (NEW.attempt_hash,NEW.input_hash,NEW.settings_hash,NEW.known_router_cost_usd,NEW.total_accounting_bound_usd,NEW.provisional_exposure_usd,NEW.pinned_byok_cost_bound_usd,NEW.basis)
  IS DISTINCT FROM (attempt_digest,i.input_hash,t.settings_hash,a.cost_usd,a.reserve_usd,a.reserve_usd-a.cost_usd,bound,'REVIEWED_KNOWN_ROUTER_BOUNDED_BYOK_EXPOSURE')
  OR NEW.acknowledgement_id IS DISTINCT FROM onet_matching.hash(jsonb_build_array('reviewed-route-incident-v1',NEW.attempt_id,NEW.response_sha256,attempt_digest,i.input_hash,t.settings_hash,a.cost_usd,a.reserve_usd,bound,NEW.actor,NEW.notes,NEW.evidence))
 THEN RAISE EXCEPTION 'ONET_MATCHING_ROUTE_ACK_INSERT_NOT_VERIFIED'; END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER verified_route_incident_insert BEFORE INSERT ON onet_matching.route_incident_acknowledgement
 FOR EACH ROW EXECUTE FUNCTION onet_matching.route_incident_insert_guard();

CREATE OR REPLACE VIEW onet_matching.accounted_attempt AS
 SELECT a.*,coalesce(ack.total_accounting_bound_usd,a.cost_usd,r.effective_cost_usd) AS effective_cost_usd,r.reconciliation_id,
  coalesce(a.cost_usd,r.effective_cost_usd) AS known_cost_usd,
  coalesce(ack.provisional_exposure_usd,0) AS provisional_exposure_usd,ack.acknowledgement_id AS route_acknowledgement_id
 FROM onet_matching.attempt a LEFT JOIN onet_matching.no_dispatch_reconciliation r USING(attempt_id)
 LEFT JOIN onet_matching.route_incident_acknowledgement ack USING(attempt_id);
"""


def original(name):
    match = re.search(
        r"CREATE OR REPLACE FUNCTION onet_matching\." + name + r"\(.*?\$\$;",
        (OUT / "sql/005_no_dispatch_reconciliation.sql").read_text(),
        re.DOTALL,
    )
    assert match, name
    return match.group()


def body_hash(source):
    return hashlib.md5(source.split("$$", 2)[1].encode(), usedforsecurity=False).hexdigest()


def generate():
    functions = []
    for name, signature in [
        ("request_context", "text,uuid"),
        ("task_status", "text"),
        ("batch_status", "text"),
    ]:
        old = original(name)
        new = old
        if name == "request_context":
            needle = "x.is_byok IS DISTINCT FROM true AND x.reconciliation_id IS NULL"
            assert old.count(needle) == 1
            new = new.replace(needle, needle + " AND x.route_acknowledgement_id IS NULL")
        else:
            needle = (
                "sum(a.effective_cost_usd)" if name == "task_status" else "sum(effective_cost_usd)"
            )
            assert old.count(needle) == 1
            new = new.replace(needle, needle.replace("effective_cost_usd", "known_cost_usd"))
            needle = "  'unknown_holds'"
            additions = (
                "  'provisional_exposure_usd',coalesce((SELECT sum(a.provisional_exposure_usd) FROM onet_matching.accounted_attempt a JOIN onet_matching.task x USING(task_id) WHERE x.budget_key=t.budget_key),0),\n  'provisional_route_incidents',(SELECT count(*) FROM onet_matching.accounted_attempt a JOIN onet_matching.task x USING(task_id) WHERE x.budget_key=t.budget_key AND a.route_acknowledgement_id IS NOT NULL),\n"
                if name == "task_status"
                else "  'provisional_exposure_usd',coalesce((SELECT sum(provisional_exposure_usd) FROM onet_matching.accounted_attempt WHERE batch_id=id),0),\n  'provisional_route_incidents',(SELECT count(*) FROM onet_matching.accounted_attempt WHERE batch_id=id AND route_acknowledgement_id IS NOT NULL),\n"
            )
            assert old.count(needle) == 1
            new = new.replace(needle, additions + needle)
        functions.append((name, signature, old, new))
    guard = "DO $qualified_base$ BEGIN\n"
    for name, signature, old, new in functions:
        guard += f" IF NOT EXISTS(SELECT 1 FROM pg_proc WHERE oid=to_regprocedure('onet_matching.{name}({signature})') AND md5(prosrc) IN('{body_hash(old)}','{body_hash(new)}')) THEN RAISE EXCEPTION 'ONET_MATCHING_ROUTE_ACK_BASE_DRIFT: {name}'; END IF;\n"
    guard += "END $qualified_base$;\n"
    sql = HEADER.replace("SELECT retention.gate();", "SELECT retention.gate();\n" + guard, 1)
    sql += "\n".join(new for _, _, _, new in functions) + "\nCOMMIT;\n"
    (OUT / "sql/006_route_incident_acknowledgement.sql").write_text(sql)
    root = E.parse(OUT / "install_reconciliation.hwf").getroot()
    root.find(
        "name"
    ).text = "Install separately qualified bounded O*NET route-incident acknowledgement"
    action = next(node for node in root.find("actions") if node.findtext("type") == "SQL")
    old_name = action.findtext("name")
    new_name = "006_route_incident_acknowledgement"
    action.find("name").text = new_name
    action.find(
        "sqlfilename"
    ).text = "${PROJECT_HOME}/llm/onet/sql/006_route_incident_acknowledgement.sql"
    for hop in root.find("hops"):
        for key in ["from", "to"]:
            if hop.findtext(key) == old_name:
                hop.find(key).text = new_name
    E.indent(root, space="  ")
    E.ElementTree(root).write(
        OUT / "install_route_incident.hwf", encoding="UTF-8", xml_declaration=True
    )


if __name__ == "__main__":
    generate()
