"""Real native Hop/file/PG integration in fresh disposable containers; no provider calls."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'hop/ontology/tests'))
import run

# Assign before boot AND before importing native (which captures run.PG).
suffix = uuid.uuid4().hex[:10]
run.PG = 'jobtology-editorial-pg-' + suffix
import native
native.PG = run.PG
native.HOP = 'jobtology-editorial-hop-' + suffix
native.NET = 'jobtology-editorial-' + suffix
q, js, sql, err = run.q, run.js, run.sql, run.expect_error

def hashes(raw):
    return hashlib.sha256(raw).hexdigest(), hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()

def capture(raw):
    sha, blob = hashes(raw)
    return 'SELECT editorial.capture_v1(decode('+q(raw.hex())+",'hex'),"+q(sha)+','+q(blob)+')'

def review(snapshot, choice='ACCEPT', actor='synthetic-human', kind='human', review_id=None):
    values = [review_id or str(uuid.uuid4()), snapshot, choice, actor, kind,
              'Synthetic fixture only: reviewed source and fictitious main-branch merge.', '1'*40, 'fixture:main-merge']
    return 'SELECT editorial.review_v1('+','.join(q(v) for v in values)+')'

def protected():
    return sql("SELECT ontology.hash(jsonb_build_object('sources',(SELECT jsonb_agg(r ORDER BY run_id) FROM ingestion.run r),"
               "'records',(SELECT jsonb_agg(r ORDER BY record_id) FROM ingestion.record r),"
               "'attempts',(SELECT count(*) FROM enrichment.attempt),'active',(SELECT count(*) FROM ontology.corpus_release WHERE state='ACTIVE')))" )

def main(after=None):
    try:
        run.boot(); run.check()
        original = protected()
        native.stage()
        native.run('../editorial/install.hwf', {}, 'native-editorial-install')
        raw = (ROOT/'hop/editorial/catalogues/product-occupations.v1.yaml').read_bytes()
        document = json.loads(raw)
        sha, blob = hashes(raw)
        actual_git = subprocess.run(['git','hash-object','--stdin'], input=raw, capture_output=True, check=True).stdout.decode().strip()
        assert actual_git == blob
        params = dict(EXPECTED_SHA256=sha, EXPECTED_GIT_BLOB=blob)
        native.run('../editorial/import_catalogue.hwf', params, 'native-editorial-import')
        assert sql('SELECT encode(raw_bytes,\'hex\') FROM editorial.snapshot WHERE snapshot_id='+q(sha)) == raw.hex()
        assert sql('SELECT count(*) FROM editorial.item') == '5'
        assert sql('SELECT review_state FROM editorial.catalogue_status') == 'PENDING'
        assert sql("SELECT count(*) FROM ontology.entity WHERE code LIKE 'product:%'") == '0'
        before = sql('SELECT ontology.hash(jsonb_agg(i ORDER BY entity_id)) FROM editorial.item i')
        native.run('../editorial/import_catalogue.hwf', params, 'native-editorial-replay')
        assert before == sql('SELECT ontology.hash(jsonb_agg(i ORDER BY entity_id)) FROM editorial.item i')
        assert sql('SELECT count(*) FROM editorial.snapshot') == '1'
        native.run('../editorial/import_catalogue.hwf', params|dict(EXPECTED_SHA256='0'*64), 'native-editorial-wrong-hash', False)
        native.run('../editorial/import_catalogue.hwf', params|dict(CATALOGUE_FILE=native.REMOTE+'/missing-file.yaml'), 'native-editorial-missing-file', False)
        err(capture(b'{"a":1,"a":2}'), 'EDITORIAL_JSON_OBJECT_REQUIRED')
        err(capture(b'\xff'), 'invalid byte sequence')
        err(capture(json.dumps(document|dict(reviewed=True)).encode()), 'INVALID_EDITORIAL_DOCUMENT')
        bad = json.loads(raw); bad['occupations'][1]['code'] = 'AI_ENGINEER'
        err(capture(json.dumps(bad).encode()), 'EDITORIAL_FOUR_DISTINCT_OCCUPATIONS_REQUIRED')
        bad = json.loads(raw); bad['occupations'][0]['name'] = ' '
        err(capture(json.dumps(bad).encode()), 'EDITORIAL_BLANK_TEXT')
        err(capture(raw+b'\n'), 'EDITORIAL_VERSION_IS_IMMUTABLE')
        err('SELECT editorial.pin_v1(\'fixture-release\','+q(sha)+')', 'EDITORIAL_HUMAN_REVIEW_REQUIRED')
        err(review(sha, actor='assistant:codex', kind='assistant'), 'INDEPENDENT_EDITORIAL_REVIEW_REQUIRED')
        err("SELECT editorial.review_v1(gen_random_uuid(),"+q(sha)+",'ACCEPT','synthetic-human','human','Fixture',NULL,NULL)", 'EDITORIAL_MERGE_ATTESTATION_REQUIRED')
        sql(review(sha, actor='synthetic-assistant-reviewer', kind='assistant'))
        assert sql('SELECT review_state FROM editorial.catalogue_status') == 'ASSISTANT_REVIEWED'
        err('SELECT editorial.pin_v1(\'fixture-release\','+q(sha)+')', 'EDITORIAL_HUMAN_REVIEW_REQUIRED')
        review_id = str(uuid.uuid4())
        native.run('../editorial/review_catalogue.hwf', dict(REVIEW_ID=review_id, SNAPSHOT_ID=sha, DECISION='ACCEPT',
            REVIEWER='synthetic-human', REVIEWER_KIND='human', NOTES='Synthetic catalogue and fictitious Git merge, fixture only.',
            GIT_COMMIT='1'*40, MERGE_EVIDENCE='fixture:main-merge'), 'native-editorial-review')
        native.run('../editorial/pin_catalogue.hwf', dict(RELEASE_ID='fixture-release', SNAPSHOT_ID=sha), 'native-editorial-pin')
        membership = sql("SELECT manifest_hash FROM editorial.release_pin WHERE release_id='fixture-release'")
        assert sql("SELECT count(*) FROM editorial.revision_support WHERE release_id='fixture-release'") == '5'
        assert sql("SELECT count(*) FROM ontology.release_revision m JOIN ontology.entity e USING(entity_id) WHERE m.release_id='fixture-release' AND e.scheme_id='urn:jobtology:conceptScheme:product-occupations'") == '4'
        assert sql("SELECT count(*) FROM ontology.source_relation WHERE predicate='CLASSIFIED_AS' AND subject_id LIKE '%product:%'") == '0'
        err("UPDATE ontology.corpus_release SET manifest='{}',manifest_hash='pretend' WHERE release_id='fixture-release'", 'EDITORIAL_GRAPH_INTEGRATION_REQUIRED')
        # Later rejections do not rewrite frozen history, but block new selections.
        sql(review(sha, choice='REJECT'))
        sql("SELECT editorial.pin_v1('fixture-release',"+q(sha)+')')
        assert sql("SELECT manifest_hash FROM editorial.release_pin WHERE release_id='fixture-release'") == membership
        sql("SELECT ontology.prepare_release('editorial-next'); SELECT ontology.assemble_sources('editorial-next')")
        err("SELECT editorial.pin_v1('editorial-next',"+q(sha)+')', 'EDITORIAL_HUMAN_REVIEW_REQUIRED')
        sql(review(sha))
        v2 = json.loads(raw); v2['catalogue_version'] = 2
        v2['occupations'][0]['aliases'].append('인공지능 개발 엔지니어')
        raw2 = (json.dumps(v2, ensure_ascii=False, indent=2)+'\n').encode()
        sha2 = sql(capture(raw2))
        err("SELECT editorial.pin_v1('editorial-next',"+q(sha)+')', 'EDITORIAL_CURRENT_REVISION_REQUIRED')
        err("SELECT editorial.pin_v1('editorial-next',"+q(sha2)+')', 'EDITORIAL_HUMAN_REVIEW_REQUIRED')
        sql(review(sha2))
        sql("SELECT editorial.pin_v1('editorial-next',"+q(sha2)+')')
        err("SELECT editorial.pin_v1('fixture-release',"+q(sha2)+')', 'EDITORIAL_RELEASE_PIN_IS_IMMUTABLE')
        assert sql("SELECT count(DISTINCT entity_id) FROM editorial.item") == '5'
        assert sql("SELECT count(DISTINCT revision_id) FROM editorial.item") == '10'
        err('UPDATE editorial.snapshot SET catalogue_version=5', 'IMMUTABLE_ONTOLOGY_RECORD')
        err("BEGIN; ALTER TABLE editorial.item DISABLE TRIGGER USER; UPDATE editorial.item SET source_pointer='/wrong'; SELECT editorial.verify_pin_v1('fixture-release'); COMMIT", 'EDITORIAL_MEMBERSHIP_CHANGED')
        assert protected() == original, 'Source ingestion, provider attempts or active release changed'
        for file in sorted((ROOT/'hop/editorial/sql').glob('*.sql')):
            sql(file.read_text())
        sql("SELECT editorial.verify_pin_v1('fixture-release'); SELECT editorial.verify_pin_v1('editorial-next')")
        report = dict(result='PASS', production_changes=False, provider_calls=0, original_git_blob=blob,
                      snapshots=2, stable_entities=5, revision_count=10, synthetic_release_pins=2,
                      incomplete_manifest_rejected=True,
                      native_log_directory=str(native.WORK))
        (native.WORK/'editorial-report.json').write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(report), flush=True)
        if after is not None:after(native)
    finally:
        subprocess.run(['docker','rm','-fv',native.HOP,run.PG], capture_output=True)
        subprocess.run(['docker','network','rm',native.NET], capture_output=True)

if __name__ == '__main__':
    main()
