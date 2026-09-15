"""Executed by build.py with native Hop XML helpers; development only."""
p=Pipe('import_requirement','Append a typed interpretation of an exact reviewed requirement atom.')
reader=node('JsonInput','Read normalization JSON',IsInFields='Y',IsAFile='Y',valueField='normalization_filename',
 removeSourceField='N',ignoreMissingPath='N',defaultPathLeafToNull='Y',doNotFailIfNoFile='N')
child(E.SubElement(reader,'fields'),'field',dict(name='normalization_json',path='$',type='String',length=-1,precision=-1,trim_type='none',repeat='N'))
p.chain(variables('Normalization file',[('normalization_filename','${NORMALIZATION_FILE}','String')]),reader,
 db('Append normalization','SELECT ontology.capture_requirement_v1(?::jsonb) AS normalization_id',[('normalization_json','String')]),
 log('Normalization saved',['normalization_id'],'Pending independent review. Source expressions and evidence remain unchanged.'))
p.save()
workflow('import_requirement.hwf','Import typed requirement normalization',[
 ('NORMALIZATION_FILE','${PROJECT_HOME}/data/ontology/requirement.json','UTF-8 JSON object matching schemas/requirement-normalization-v1.schema.json.')],
 [('Append source-grounded normalization','import_requirement.hpl')],False)

p=Pipe('review_requirement','Record a separate review of a typed requirement interpretation.')
fields=('NORMALIZATION_ID','DECISION','REVIEWER','REVIEWER_KIND','NOTES')
p.chain(variables('Review choices',[(k.lower(),'${'+k+'}','String') for k in fields]),
 db('Append independent decision','SELECT ontology.decide_requirement_v1(?,?,?,?,?) AS decision_id',[(k.lower(),'String') for k in fields]),
 log('Decision recorded',['normalization_id','decision_id'],'Semantic review does not assign confidence or activate a release.'))
p.save()
workflow('review_requirement.hwf','Review typed requirement interpretation',[
 ('NORMALIZATION_ID','','Exact normalization hash.'),('DECISION','REJECT','ACCEPT or REJECT.'),
 ('REVIEWER','','Reviewer identity distinct from the proposal actor.'),('REVIEWER_KIND','human','human or assistant; record the actual reviewer kind.'),
 ('NOTES','','Evidence-based review rationale.')],[('Record independent review','review_requirement.hpl')],False)

p=Pipe('freeze_requirements','Freeze the complete set of typed atom outcomes for an assembled draft.')
p.chain(variables('Release',[('release_id','${RELEASE_ID}','String')]),
 execute('Freeze typed requirements','SELECT ontology.freeze_requirements_v1(?)',['release_id']),
 log('Typed requirements frozen',['release_id'],'A later proposal or review requires a new release. Inspect remaining semantic issues.'))
p.save()
workflow('freeze_requirements.hwf','Freeze typed requirements',[
 ('RELEASE_ID','','Exact unsealed PREPARING release after assemble_reviewed.')],[('Freeze and verify membership','freeze_requirements.hpl')],False)

p=Pipe('inspect_requirements','Inspect current proposals; these are live review work, not frozen published selections.',{'RELEASE_ID':''})
p.chain(variables('Release',[('release_id','${RELEASE_ID}','String')]),
 db('Source atoms and current proposals',"""SELECT a.*,ontology.requirement_source_v1(a.source_claim_id,a.node_index)::text AS source_binding,
 n.normalization_id,n.parent_id,n.condition::text AS condition,n.requirement_key,n.document->>'actor' AS actor,
 d.decision_id,d.decision,d.reviewer,d.reviewer_kind,d.notes,
 s.outcome AS frozen_outcome,s.normalization_id AS frozen_normalization_id
 FROM ontology.requirement_atom a
 LEFT JOIN LATERAL (SELECT * FROM ontology.requirement_normalization p WHERE p.source_claim_id=a.source_claim_id AND p.node_index=a.node_index ORDER BY normalization_no DESC LIMIT 1) n ON true
 LEFT JOIN LATERAL (SELECT * FROM ontology.requirement_decision r WHERE r.normalization_id=n.normalization_id ORDER BY decision_id DESC LIMIT 1) d ON true
 LEFT JOIN ontology.requirement_selection s ON s.release_id=a.release_id AND s.source_claim_id=a.source_claim_id AND s.node_index=a.node_index
 WHERE a.release_id=? ORDER BY a.entity_id,a.source_claim_id,a.node_index""",[('release_id','String')]),node('Dummy','Preview source and typed conditions'))
p.save()
params=[('RELEASE_ID','','Exact release ID; blank uses only the active published release.'),('PREVIEW','N','Y explicitly reads draft membership; N requires a published release.')]
p=Pipe('read_requirements','Read frozen typed requirement outcomes and remaining issues.',{k:v for k,v,_ in params})
p.chain(variables('Read choices',[('release_id','${RELEASE_ID}','String'),('preview','${PREVIEW}','String')]),
 db('Read frozen requirements',"SELECT ontology.query_requirements_v1(?::text,CASE ?::text WHEN 'Y' THEN true WHEN 'N' THEN false ELSE NULL END)::text AS result_json",[('release_id','String'),('preview','String')]),
 node('Dummy','Preview frozen requirements'))
p.save()
workflow('read_requirements.hwf','Read frozen typed requirements',params,[('Read release requirements','read_requirements.hpl')],False)
