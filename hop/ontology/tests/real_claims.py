"""Projection stress/round-trip test using saved real outputs in a disposable DB.

Requires the six-source fixture already imported into ontologyrealtest. It makes
synthetic local acceptance decisions to exercise projection, NOT semantic gold
labels or production reviews. It never calls a model or writes to Goldship.
"""
from pathlib import Path
import argparse
import json
import time
from run import ROOT, PG, cmd, js, q

DB='ontologyrealtest'
def sql(value):
    return cmd(['docker','exec','-i',PG,'psql','-X','-qAt','-v','ON_ERROR_STOP=1','-U','postgres','-d',DB],input=value)


def check(path, report_path):
    rows=[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert rows and len({r['item']['posting_id'] for r in rows})==len(rows)
    assert all(r['state']=='VALIDATED' and r['settings']['prompt_version']=='ko-v4' for r in rows)
    for file in sorted((ROOT/'hop/ontology/sql').glob('*.sql')):sql(file.read_text())
    batch='real-output-projection-fixture'
    statements=[f"INSERT INTO enrichment.batch(batch_id,mode,job_run_id,ncs_run_id,ncs_hash,settings,state) VALUES({q(batch)},'ENRICH',{q(rows[0]['job_run_id'])},{q(rows[0]['ncs_run_id'])},{q(rows[0]['ncs_hash'])},{js(rows[0]['settings'])},'COMPLETE') ON CONFLICT DO NOTHING;"]
    for row in rows:
        item=row['item'];ident=batch+'-'+item['posting_id'];attempt=ident+'-extract'
        statements.append(f"INSERT INTO enrichment.item(item_id,batch_id,posting_id,source_data,source_hash,ordinal,extraction_id) VALUES({q(ident)},{q(batch)},{q(item['posting_id'])},{js(item['source_data'])},{q(item['source_hash'])},{item['ordinal']},{q(attempt)}) ON CONFLICT DO NOTHING;")
        statements.append(f"INSERT INTO enrichment.attempt(attempt_id,batch_id,item_id,stage,cache_key,request_body,state,raw_output,parsed_output) VALUES({q(attempt)},{q(batch)},{q(ident)},'extract','offline-real-output','{{}}','VALIDATED',{js(row['raw_output'])},{js(row['parsed_output'])}) ON CONFLICT DO NOTHING;")
        statements.append(f"SELECT enrichment.decide_extraction(enrichment.capture_extraction({q(ident)},'synthetic-offline-fixture','Projection test only; not semantic review'),'ACCEPT','synthetic-offline-fixture','policy','Disposable local projection test; not a production decision');")
    start=time.monotonic();sql('BEGIN;\n'+'\n'.join(statements)+'\nCOMMIT;')
    print('Loaded',len(rows),'saved outputs in',round(time.monotonic()-start,2),'seconds',flush=True)
    release='real-reviewed-projection-fixture'
    start=time.monotonic()
    sql(f"SELECT ontology.prepare_release({q(release)}); SELECT ontology.assemble_sources({q(release)}); SELECT ontology.freeze_reviews({q(release)}); SELECT ontology.assemble_claims({q(release)}); SELECT ontology.verify_claims({q(release)})")
    print('Assembled source/claim fixture in',round(time.monotonic()-start,2),'seconds',flush=True)
    counts=json.loads(sql(f"""SELECT jsonb_build_object(
      'postings',(SELECT count(*) FROM ontology.posting_selection WHERE release_id={q(release)}),
      'accepted_fixture_outputs',(SELECT count(*) FROM ontology.posting_selection WHERE release_id={q(release)} AND outcome='ACCEPTED'),
      'claims',(SELECT count(*) FROM ontology.release_claim WHERE release_id={q(release)}),
      'positions',(SELECT count(*) FROM ontology.release_position WHERE release_id={q(release)}),
      'condition_nodes',(SELECT count(*) FROM ontology.condition_node n JOIN ontology.release_claim c USING(claim_id) WHERE c.release_id={q(release)}),
      'evidence_spans',(SELECT count(DISTINCT evidence_id) FROM ontology.evidence_span e JOIN ontology.artifact_source s USING(artifact_id) WHERE s.release_id={q(release)}))"""))
    assert counts['postings']==513 and counts['accepted_fixture_outputs']==len(rows),counts
    # Compare original saved hydration field-for-field, independently of the SQL
    # projection verifier. Acceptance above only drives the code path under test.
    projected=json.loads(sql(f"""SELECT jsonb_agg(jsonb_build_object('posting_id',v.payload->>'posting_id',
      'kind',c.kind,'ordinal',c.ordinal,'text',c.text,'category',c.category,'condition_kind',c.condition_kind,'logic',c.logic,
      'expression',(SELECT coalesce(jsonb_agg(jsonb_build_object('op',n.operator,'text',n.text,'parts',n.parts,
       'children',(SELECT coalesce(jsonb_agg(child_index ORDER BY ordinal),'[]') FROM ontology.condition_child cc WHERE cc.claim_id=n.claim_id AND cc.parent_index=n.node_index)) ORDER BY node_index),'[]') FROM ontology.condition_node n WHERE n.claim_id=c.claim_id)))
      FROM ontology.release_claim m JOIN ontology.claim c USING(claim_id) JOIN ontology.revision v ON v.revision_id=c.posting_revision_id WHERE m.release_id={q(release)}"""))
    expected={(r['item']['posting_id'],kind,index):value
        for r in rows for kind,section in [('DUTY','duties'),('REQUIREMENT','requirements')]
        for index,value in enumerate(r['parsed_output'][section])}
    assert len(projected)==len(expected), (len(projected),len(expected))
    for claim in projected:
        value=expected[(claim['posting_id'],claim['kind'],claim['ordinal'])]
        assert claim['text']==value['text'] and claim['category']==value.get('category')
        assert claim['condition_kind']==value.get('kind') and claim['logic']==value.get('logic')
        assert claim['expression']==value.get('expression',[]),(claim,value)
    spans=json.loads(sql(f"SELECT jsonb_agg(jsonb_build_object('text',a.normalized_text,'excerpt',e.excerpt,'start',e.start_offset,'end',e.end_offset)) FROM ontology.evidence_span e JOIN ontology.text_artifact a USING(artifact_id) WHERE EXISTS(SELECT 1 FROM ontology.artifact_source s WHERE s.release_id={q(release)} AND s.artifact_id=a.artifact_id)"))
    for span in spans:assert span['text'][span['start']:span['end']]==span['excerpt'],span
    report=dict(counts=counts,projection_field_differences=0,evidence_offset_differences=0,
        semantic_quality_evaluation=False,production_reviews_written=0,fixture_path=str(path))
    report_path.write_text(json.dumps(report,indent=2)+'\n')
    print('REAL OUTPUT PROJECTION CHECKS PASSED',json.dumps(report),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('fixture',type=Path);parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();check(args.fixture,args.report)
