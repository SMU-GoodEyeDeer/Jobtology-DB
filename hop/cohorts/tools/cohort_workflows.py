"""Loaded by build.py. The builder installer requires editorial + preparation."""
params=[('RELEASE_ID','','Exact unsealed release with all prerequisite memberships frozen.'),
        ('OCCUPATION_ID','','One of the four exact product occupation URNs.'),('AS_OF','','Inclusive KST date, YYYY-MM-DD.')]
p=Pipe('build_cohort','Persist one deterministic cohort and its normalized track/claim support.',{k:v for k,v,_ in params})
fields=[(k.lower(),'${'+k+'}','String') for k,_,_ in params]
p.chain(variables('Cohort choices',fields),db('Build persisted cohort',
    "SELECT ontology.build_posting_cohort_v1(?::text,?::text,nullif(?::text,'')::date) AS cohort_id",[(k,t) for k,_,t in fields]),
    log('Cohort stored',['cohort_id'],'Selection is persisted. Demand statistics and publication remain separate.'))
p.save();workflow('build_cohort.hwf','Build posting cohort',params,[('Build cohort','build_cohort.hpl')],False)

for name,extras,arguments in [
    ('posting_cohort',[('AS_AT','','Optional timestamp with time zone for active/fresh count; blank means now.')],
     ["coalesce(nullif(?::text,'')::timestamptz,statement_timestamp())"]),
    ('cohort_members',[('CURSOR','','Opaque next_cursor from the preceding page; blank for the first page.'),
                       ('PAGE_SIZE','100','Rows per page, from 1 through 100.')],["nullif(?::text,'')",'?::integer'])]:
    params=[('RELEASE_ID','','Exact release; blank means only the active published release.'),('COHORT_ID','','Exact stored cohort ID.'),
            ('PREVIEW','N','Y explicitly reads a draft.')]+extras
    fields=[(k.lower(),'${'+k+'}','Integer' if k=='PAGE_SIZE' else 'String') for k,_,_ in params]
    p=Pipe('read_'+name,'Read persisted cohort decisions and evidence.',{k:v for k,v,_ in params})
    p.chain(variables('Read choices',fields),db('Read cohort JSON','SELECT ontology.query_'+name+'_v1('+','.join(
        ['?::text','?::text',"CASE ?::text WHEN 'Y' THEN true WHEN 'N' THEN false ELSE NULL END"]+arguments)+')::text AS result_json',
        [(k,t) for k,_,t in fields]),node('Dummy','Preview JSON here'))
    p.save();workflow('read_'+name+'.hwf','Read '+name,params,[('Read result','read_'+name+'.hpl')],False)

w=E.Element('workflow');put(w,'name','Install persisted cohort builder');actions=E.SubElement(w,'actions');hops=E.SubElement(w,'hops')
child(actions,'action',dict(name='Start',type='SPECIAL',start='Y',repeat='N',xloc=80,yloc=80,draw='Y'));previous='Start'
for i,path in enumerate(sorted((OUT/'sql/cohort').glob('*.sql')),1):
    name=path.stem
    child(actions,'action',dict(name=name,type='SQL',connection='jobtology-postgres',sql='',sqlfromfile='Y',
        sqlfilename='${PROJECT_HOME}/cohorts/sql/cohort/'+path.name,sqlfilename_encoding='UTF-8',useVariableSubstitution='N',
        sendOneStatement='Y',xloc=80+i*260,yloc=80,draw='Y'))
    child(hops,'hop',{'from':previous,'to':name,'enabled':'Y','evaluation':'Y','unconditional':'Y' if previous=='Start' else 'N'})
    child(hops,'hop',{'from':name,'to':'Abort','enabled':'Y','evaluation':'N','unconditional':'N'});previous=name
child(actions,'action',dict(name='Success',type='SUCCESS',xloc=1120,yloc=80,draw='Y'))
child(actions,'action',dict(name='Abort',type='ABORT',message='Cohort builder installation failed; inspect SQL log and prerequisite installers.',xloc=1120,yloc=260,draw='Y'))
child(hops,'hop',{'from':previous,'to':'Success','enabled':'Y','evaluation':'Y','unconditional':'N'});save(w,OUT/'install_builder.hwf')
