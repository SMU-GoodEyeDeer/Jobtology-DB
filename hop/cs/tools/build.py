"""Generate native Hop CS-scope inspection and review workflows."""
from pathlib import Path
import ast
import xml.etree.ElementTree as E

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'hop/cs'
helper_source=(ROOT/'hop/llm/tools/build.py').read_text()
for definition in ast.parse(helper_source).body:
    if isinstance(definition,(ast.FunctionDef,ast.ClassDef)) and definition.name in {
        'put','child','node','Pipe','save','variables','db','execute','log','workflow'
    }:
        code=ast.get_source_segment(helper_source,definition)
        if definition.name=='workflow':
            code=code.replace('/llm/','/cs/').replace('LLM workflow failed. Inspect enrichment.batch_report and enrichment.attempt.',
                'CS scope workflow failed. Inspect the PostgreSQL or Hop log.')
        exec(compile(code,__file__,'exec'),globals())

p=Pipe('assess','Read current source-independent CS-scope and link coverage; no model requests.')
p.chain(variables('Assessment limit',[('limit_rows','${POSITION_LIMIT}','String')]),
 db('Current assessment','SELECT cs.assess_v1(?::integer)::text AS assessment_json', [('limit_rows','String')]),
 node('Dummy','Preview assessment JSON'))
p.save()
workflow('assess.hwf','Assess IT/AI/data positions and reusable NCS work',[
 ('POSITION_LIMIT','1000','Maximum positions returned in the JSON; summary covers all positions.')],
 [('Read assessment','assess.hpl')],False)

p=Pipe('read_scope','Inspect source-bound candidates and reviewed role decisions.')
p.chain(variables('Selection',[('scope_status','${SCOPE_STATUS}','String'),('limit_rows','${POSITION_LIMIT}','String')]),
 db('Current roles',"SELECT source_id,source_posting_id,posting_identity,role_id,role_name,title,binding_hash,"
    "scope_status,screen_status,title_families,duty_families,category_families,selected_family,"
    "extraction_state,review_decision,role_origin,duty_text "
    "FROM cs.current_scope WHERE (?='' OR scope_status=?) "
    "ORDER BY source_id,posting_identity,role_id LIMIT ?::integer",
    [('scope_status','String'),('scope_status','String'),('limit_rows','String')]),
 node('Dummy','Preview roles'))
p.save()
workflow('read_scope.hwf','Read current CS-related advertised roles',[
 ('SCOPE_STATUS','','Optional IN_SCOPE, OUT_OF_SCOPE, NEEDS_REVIEW or OUT_OF_SCOPE_CANDIDATE.'),
 ('POSITION_LIMIT','1000','Limit preview rows; the assessment summary includes all.')],
 [('Read roles','read_scope.hpl')],False)

params=[('POSTING_IDENTITY','','Exact source-qualified posting identity.'),
 ('ROLE_ID','','Exact position ID from read_scope.'),('BINDING_HASH','','Exact current binding hash.'),
 ('DECISION','NEEDS_REVIEW','IN_SCOPE, OUT_OF_SCOPE or NEEDS_REVIEW.'),
 ('FAMILY','','For IN_SCOPE: SOFTWARE, IT_SYSTEMS, SECURITY, DATA or AI.'),
 ('REVIEWER','','Actual reviewer.'),('REVIEWER_KIND','assistant','human, assistant or policy.'),
 ('REASON','','Source/role-grounded explanation.')]
fields=[(k.lower(),'${'+k+'}','String') for k,_,_ in params]
p=Pipe('decide_scope','Save an append-only position-scope decision bound to current evidence.')
p.chain(variables('Decision',fields),
 db('Record scope decision',"SELECT cs.decide_scope_v1(?,?,?,?::text,nullif(?::text,''),?,?,?) AS decision_id",
    [(k,'String') for k,_,_ in params]),
 log('Decision recorded',['decision_id','posting_identity','role_id','decision'],
  'The source-bound role decision was recorded; no enrichment or graph publication ran.'))
p.save()
workflow('decide_scope.hwf','Decide the scope of one advertised position',params,
 [('Record reviewed decision','decide_scope.hpl')],False)

w=E.Element('workflow');put(w,'name','Install source-independent CS scope and reports')
put(w,'description','Install source-independent CS scope and reports')
put(w,'workflow_version','1');put(w,'workflow_status','0')
E.SubElement(w,'parameters');actions=E.SubElement(w,'actions');hops=E.SubElement(w,'hops')
child(actions,'action',dict(name='Start',type='SPECIAL',start='Y',repeat='N',xloc=80,yloc=80,draw='Y'))
previous='Start'
for index,file in enumerate(sorted((OUT/'sql').glob('*.sql')),1):
    name='Install '+file.name
    child(actions,'action',dict(name=name,type='SQL',connection='jobtology-postgres',
        sqlfromfile='Y',sqlfilename='${PROJECT_HOME}/cs/sql/'+file.name,
        sqlfilename_encoding='UTF-8',useVariableSubstitution='N',sendOneStatement='Y',
        xloc=80+index*250,yloc=80,draw='Y',parallel='N'))
    child(hops,'hop',{'from':previous,'to':name,'enabled':'Y','evaluation':'Y',
        'unconditional':'Y' if previous=='Start' else 'N'})
    child(hops,'hop',{'from':name,'to':'Abort','enabled':'Y','evaluation':'N','unconditional':'N'})
    previous=name
child(actions,'action',dict(name='Success',type='SUCCESS',xloc=80+(index+1)*250,yloc=80,draw='Y'))
child(actions,'action',dict(name='Abort',type='ABORT',message='CS scope SQL installation failed.',
    xloc=80+(index+1)*250,yloc=240,draw='Y'))
child(hops,'hop',{'from':previous,'to':'Success','enabled':'Y','evaluation':'Y','unconditional':'N'})
E.SubElement(w,'notepads');E.SubElement(w,'attributes');save(w,OUT/'install.hwf')

exec(compile((OUT/'tools/packet_workflows.py').read_text(),
             str(OUT/'tools/packet_workflows.py'),'exec'),globals())
exec(compile((OUT/'tools/manual_ncs_workflows.py').read_text(),
             str(OUT/'tools/manual_ncs_workflows.py'),'exec'),globals())
exec(compile((OUT/'tools/qualification_workflows.py').read_text(),
             str(OUT/'tools/qualification_workflows.py'),'exec'),globals())
