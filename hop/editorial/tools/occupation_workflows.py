"""Called by build.py with its native Hop XML helpers; development only."""
params=[('PROPOSAL_FILE','','One UTF-8 JSON proposal file, at most 1 MiB; use the occupation input reader first.')]
p=Pipe('import_occupation','Import one evidence-bound product occupation proposal; no automatic review.')
reader=node('LoadFileInput','Read proposal bytes',IsInFields='Y',DynamicFilenameField='proposal_file',
            IsIgnoreEmptyFile='N',IsIgnoreMissingPath='N',encoding='UTF-8',addresultfile='N',limit=0)
child(E.SubElement(reader,'fields'),'field',dict(name='proposal_bytes',element_type='content',type='Binary',
      length=-1,precision=-1,trim_type='none',repeat='N'))
p.chain(variables('Proposal file',[('proposal_file','${PROPOSAL_FILE}','String')]),reader,
        db('Validate and capture proposal','SELECT ontology.import_occupation_v1(?::bytea) AS proposal_id',[('proposal_bytes','Binary')]),
        log('Proposal imported',['proposal_id'],'Independent review and release freeze are separate steps.'))
p.save();workflow('import_occupation.hwf','Import product occupation proposal',params,[('Import proposal','import_occupation.hpl')],False)

params=[('REVIEW_ID','','New UUID; reuse only to retry the identical decision.'),('PROPOSAL_ID','','Exact proposal ID.'),
        ('DECISION','REJECT','ACCEPT or REJECT.'),('REVIEWER','','Independent reviewer identity.'),
        ('REVIEWER_KIND','human','Actual reviewer kind: human or assistant.'),('NOTES','','Evidence and catalogue review rationale.')]
p=Pipe('review_occupation','Append an independent occupation decision; UUID makes exact retries idempotent.')
p.chain(variables('Review choices',[(k.lower(),'${'+k+'}','String') for k,_,_ in params]),
        db('Record decision','SELECT ontology.decide_occupation_v1(?::uuid,?,?,?,?,?) AS decision_id',[(k.lower(),'String') for k,_,_ in params]),
        log('Decision recorded',['decision_id'],'A later decision affects new freezes only. Confidence remains unassessed.'))
p.save();workflow('review_occupation.hwf','Review product occupation proposal',params,[('Record decision','review_occupation.hpl')],False)

p=Pipe('freeze_occupations','Freeze one current decision or explicit failure outcome for every selected posting.')
p.chain(variables('Release',[('release_id','${RELEASE_ID}','String')]),
        execute('Freeze occupation selection','SELECT ontology.freeze_occupations_v1(?)',['release_id']),
        log('Selection frozen',['release_id'],'Inspect all outcomes. Graph loading and serving activation require separate steps.'))
p.save();workflow('freeze_occupations.hwf','Freeze product occupation decisions',[
    ('RELEASE_ID','','Exact unsealed PREPARING release with assembled claims and a reviewed editorial pin.')],
    [('Freeze reviewed occupations','freeze_occupations.hpl')],False)

for name,arguments in [('occupation_input',[('ENTITY_ID','','Exact posting identity in the selected release.')]),('occupations',[])]:
    params=[('RELEASE_ID','','Exact release; blank selects only an active published release.')]+arguments+[
        ('PREVIEW','N','Y explicitly reads a draft. This never performs inference.')]
    fields=[(k.lower(),'${'+k+'}','String') for k,_,_ in params]
    args=['?::text']+['?::text' for _ in arguments]+["CASE ?::text WHEN 'Y' THEN true WHEN 'N' THEN false ELSE NULL END"]
    p=Pipe('read_'+name,'Read product-role evidence and selections as JSON.',{k:v for k,v,_ in params})
    p.chain(variables('Read choices',fields),db('Read JSON',
        'SELECT ontology.query_'+name+'_v1('+','.join(args)+')::text AS result_json',[(k,t) for k,_,t in fields]),
        node('Dummy','Preview JSON here'))
    p.save();workflow('read_'+name+'.hwf','Read product '+name,params,[('Read JSON','read_'+name+'.hpl')],False)
