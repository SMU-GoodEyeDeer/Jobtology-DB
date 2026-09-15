"""Compare every reference identity/relation with the exported six-source fixture.

This independently enumerates source keys and checks original field values; it does
not use the SQL candidate functions or aggregate counts as its expected result.
"""
from pathlib import Path
import argparse
import json
from real_claims import sql
from run import q


def check(path, release, report_path):
    records=[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    sources={}
    for record in records:sources.setdefault(record['run']['source_id'],[]).append(record['record']['normalized'])
    identities=set();relations=set();field_checks=[]
    def entity(kind,code):
        value='urn:jobtology:'+kind+':'+str(code);identities.add(value);return value
    def edge(subject,predicate,obj,qualifiers=None):
        relations.add((subject,predicate,obj,json.dumps(qualifiers or {},sort_keys=True,ensure_ascii=False)))
    def fields(ident,row):
        field_checks.append((ident,{k:v for k,v in row.items() if k not in ('kind','representation')}))
    ncs=entity('conceptScheme','ncs');entity('conceptScheme','qnet')
    for row in sources['alio_organization']:fields(entity('organization','alio:'+row['code']),row)
    pairs={}
    for row in sources['job_alio']:
        pairs.setdefault(row['posting_id'],{})[row['representation']]=row
        entity('organization','alio:'+row['organization_code'])
    for code,pair in pairs.items():
        assert set(pair)=={'list','detail'},code
        combined=pair['list']|{k:v for k,v in pair['detail'].items() if v is not None}
        job=entity('jobPosting','job_alio:'+code);fields(job,combined)
        edge(job,'POSTED_BY',entity('organization','alio:'+combined['organization_code']))
    for row in sources['ncs_competency']:
        unit=entity('ncsCompetency',row['code']);fields(unit,row)
        occ=entity('occupation','ncs:'+row['occupation_code'])
        family=entity('ncsUnitFamily',row['code'].split('_')[0])
        edge(unit,'VERSION_OF',family,dict(version_selection='none'))
        edge(unit,'BELONGS_TO_OCCUPATION',occ);edge(ncs,'HAS_MEMBER',occ)
        hierarchy=[entity('ncsClass',row['code'][:length]) for length in [2,4,6,8]]
        for parent,child in zip(hierarchy,hierarchy[1:]):edge(parent,'BROADER_THAN',child)
        edge(unit,'CLASSIFIED_AS',hierarchy[-1]);edge(occ,'CLASSIFIED_AS',entity('ncsClass',row['occupation_code']))
    for row in sources['ncs_qualification']:
        unit=entity('ncsCompetency',row['competency_code'])
        edge(unit,'VERSION_OF',entity('ncsUnitFamily',row['competency_code'].split('_')[0]),dict(version_selection='none'))
        qual=entity('qualification','qnet:'+row['qualification_code'])
        edge(qual,'CURRICULUM_REFERENCES',unit,{k:v for k,v in row.items() if k not in ['kind','qualification_code','qualification_name','competency_code']})
    for row in sources['qnet_schedule']:
        code='qnet:'+':'.join(str(row[k]) for k in ['qualification_code','year','category_code','round'])
        exam=entity('examSession',code);fields(exam,row)
        edge(entity('qualification','qnet:'+row['qualification_code']),'HAS_EXAM_SESSION',exam)
    for row in sources['ncs_career_path']:
        occ=entity('occupation','ncs:'+row['occupation_code'])
        rank=entity('careerRank','ncs:'+row['occupation_code']+':'+str(row['rank_level']))
        edge(occ,'HAS_CAREER_RANK',rank)
        edge(rank,'REFERENCES_UNIT_FAMILY',entity('ncsUnitFamily',row['competency_code']),
            dict(competency_level=row['competency_level'],version_selection='unresolved'))
    actual=json.loads(sql(f"SELECT jsonb_object_agg(m.entity_id,v.payload) FROM ontology.release_revision m JOIN ontology.revision v USING(revision_id) WHERE m.release_id={q(release)}"))
    assert set(actual)==identities,dict(missing=sorted(identities-set(actual)),unexpected=sorted(set(actual)-identities))
    compared=0
    for ident,values in field_checks:
        for key,value in values.items():
            assert actual[ident].get(key)==value,(ident,key,value,actual[ident].get(key));compared+=1
    rows=json.loads(sql(f"SELECT jsonb_agg(r) FROM (SELECT DISTINCT x.subject_id,x.predicate,x.object_id,x.qualifiers FROM ontology.release_relation m JOIN ontology.source_relation x USING(relation_id) WHERE m.release_id={q(release)}) r"))
    actual_relations={(r['subject_id'],r['predicate'],r['object_id'],json.dumps(r['qualifiers'],sort_keys=True,ensure_ascii=False)) for r in rows}
    assert actual_relations==relations,dict(missing=list(relations-actual_relations)[:10],unexpected=list(actual_relations-relations)[:10])
    report=dict(source_records=len(records),entity_identities=len(identities),source_relationships=len(relations),
        original_fields_compared=compared,identity_differences=0,relationship_differences=0,field_differences=0,release_id=release)
    report_path.write_text(json.dumps(report,indent=2)+'\n');print('FULL SOURCE READBACK PASSED',json.dumps(report),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('fixture',type=Path);parser.add_argument('--release',required=True);parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();check(args.fixture,args.release,args.report)
