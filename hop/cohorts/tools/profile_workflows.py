"""Loaded by build.py with native XML helpers in scope."""
params=[('PROPOSAL_FILE','${PROJECT_HOME}/cohort-profile.json','Exact UTF-8 JSON from read_cohort_profile_input.')]
p=Pipe('import_cohort_profile','Import a source-bound country/experience/position-scope proposal.',{k:v for k,v,_ in params})
reader=node('LoadFileInput','Read exact profile bytes',IsInFields='Y',DynamicFilenameField='proposal_file',
    IsIgnoreEmptyFile='N',IsIgnoreMissingPath='N',encoding='UTF-8',addresultfile='N',limit=0)
child(E.SubElement(reader,'fields'),'field',dict(name='proposal_bytes',element_type='content',type='Binary',length=-1,precision=-1,trim_type='none',repeat='N'))
p.chain(variables('Profile file',[('proposal_file','${PROPOSAL_FILE}','String')]),reader,
    db('Capture cohort profile','SELECT ontology.import_cohort_profile_v1(?::bytea) AS proposal_id',[('proposal_bytes','Binary')]),
    log('Profile stored',['proposal_id'],'Independent review and release freezing remain separate. Source facts were not rewritten.'))
p.save();workflow('import_cohort_profile.hwf','Import cohort profile',params,[('Import profile','import_cohort_profile.hpl')],False)

params=[('REVIEW_ID','','New UUID; reuse only for an identical retry.'),('PROPOSAL_ID','','Exact latest proposal ID.'),
    ('DECISION','REJECT','ACCEPT or REJECT.'),('REVIEWER','','Actual independent reviewer.'),('REVIEWER_KIND','human','human or assistant.'),
    ('NOTES','','Evidence and position-scope review notes.')]
fields=[(k.lower(),'${'+k+'}','String') for k,_,_ in params]
p=Pipe('review_cohort_profile','Append an independent cohort profile decision.',{k:v for k,v,_ in params})
p.chain(variables('Review details',fields),db('Save independent review',
    'SELECT ontology.decide_cohort_profile_v1(?::uuid,?::text,?::text,?::text,?::text,?::text) AS decision_id',[(k,t) for k,_,t in fields]),
    log('Review saved',['decision_id'],'Historical release selections remain unchanged. No confidence score is inferred.'))
p.save();workflow('review_cohort_profile.hwf','Review cohort profile',params,[('Record decision','review_cohort_profile.hpl')],False)

params=[('RELEASE_ID','','Exact unsealed draft with frozen source reviews and requirement normalization.')]
p=Pipe('freeze_cohort_profiles','Freeze selected cohort-profile decisions for every posting.',{k:v for k,v,_ in params})
p.chain(variables('Release',[('release_id','${RELEASE_ID}','String')]),
    execute('Freeze cohort profiles','SELECT ontology.freeze_cohort_profiles_v1(?)',['release_id']),
    log('Profiles frozen',['release_id'],'Profile membership is frozen. Complete cohort and graph/publication integration remain separate.'))
p.save();workflow('freeze_cohort_profiles.hwf','Freeze cohort profiles',params,[('Freeze selected profiles','freeze_cohort_profiles.hpl')],False)

for name,extra,args in [
    ('cohort_profile_input',[('ENTITY_ID','','Exact posting identity selected by the release.')],[('entity_id','${ENTITY_ID}','String')]),
    ('cohort_profiles',[],[])]:
    params=[('RELEASE_ID','','Exact release; blank reads only the active published release.')]+extra+[
        ('PREVIEW','N','Y explicitly reads a draft; failed and revoked releases remain unavailable.')]
    fields=[('release_id','${RELEASE_ID}','String')]+args+[('preview','${PREVIEW}','String')]
    p=Pipe('read_'+name,'Read cohort profiles and exact selected source evidence.',{k:v for k,v,_ in params})
    p.chain(variables('Read choices',fields),db('Read profile JSON','SELECT ontology.query_'+name+'_v1('+','.join(
        ['?::text']+['?::text' for _ in args]+["CASE ?::text WHEN 'Y' THEN true WHEN 'N' THEN false ELSE NULL END"])+')::text AS result_json',[(k,t) for k,_,t in fields]),
        node('Dummy','Preview JSON here'))
    p.save();workflow('read_'+name+'.hwf','Read '+name,params,[('Read '+name,'read_'+name+'.hpl')],False)
