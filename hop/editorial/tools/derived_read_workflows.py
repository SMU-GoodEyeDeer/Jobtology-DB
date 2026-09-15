"""Loaded by build.py; prepared native SQL reads, without provider requests."""
for kind, version, extra, arguments in [
    ('summary', 'v3', [], []),
    ('entity', 'v3', [('ENTITY_ID', '', 'Exact entity selected in this release.')],
     [('entity_id', '${ENTITY_ID}', 'String')]),
    ('derived_claim', 'v1', [('CLAIM_ID', '', 'Exact derived claim_id returned by read_entity_v3 or read_derived_claims_v1.')],
     [('claim_id', '${CLAIM_ID}', 'String')]),
    ('derived_claims', 'v1', [
        ('ENTITY_ID', '', 'Optional posting identity; filters subjects, not target occupations.'),
        ('CLAIM_KIND', '', 'Optional NORMALIZED_REQUIREMENT or PRIMARY_OCCUPATION.'),
        ('PAGE_SIZE', '100', '1 to 100 rows.'),
        ('CURSOR', '', 'Cursor from the same release and filters; blank starts at the first row.')],
     [('entity_id', '${ENTITY_ID}', 'String'), ('claim_kind', '${CLAIM_KIND}', 'String'),
      ('page_size', '${PAGE_SIZE}', 'Integer'), ('cursor_value', '${CURSOR}', 'String')])]:
    params = [('RELEASE_ID', '', 'Exact release; blank selects only the active published release.')]+extra+[
        ('PREVIEW', 'N', 'Y explicitly reads a draft; failed and revoked releases remain unavailable.')]
    fields = [('release_id', '${RELEASE_ID}', 'String')]+arguments+[('preview', '${PREVIEW}', 'String')]
    placeholders = ['?::text']+[
        '?::integer' if typ == 'Integer' else "nullif(?::text,'')" for _, _, typ in arguments]+[
        "CASE ?::text WHEN 'Y' THEN true WHEN 'N' THEN false ELSE NULL END"]
    name = 'read_'+kind+'_'+version
    p = Pipe(name, 'Read frozen derived claims with exact review and evidence provenance.', {k:v for k,v,_ in params})
    p.chain(variables('Read choices', fields), db('Read versioned JSON',
        'SELECT ontology.query_'+kind+'_'+version+'('+','.join(placeholders)+')::text AS result_json',
        [(k,t) for k,_,t in fields]), node('Dummy', 'Preview JSON here'))
    p.save()
    workflow(name+'.hwf', 'Read ontology '+kind+' '+version, params, [('Read '+kind, name+'.hpl')], False)
