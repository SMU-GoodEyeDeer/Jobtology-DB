"""Build public catalogue contracts and native Hop artifacts; never an ETL step."""
from pathlib import Path
import ast
import json
import runpy
import xml.etree.ElementTree as E

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'hop/editorial'
for folder in ('sql', 'schemas', 'catalogues'):
    (OUT / folder).mkdir(parents=True, exist_ok=True)

def obj(props):
    return dict(type='object', properties=props, required=list(props), additionalProperties=False)

def string(*values, maximum=4000):
    result = dict(type='string', minLength=1, maxLength=maximum)
    if values:
        result['enum'] = list(values)
    return result

codes = ['AI_ENGINEER', 'BACKEND_DEVELOPER', 'FRONTEND_DEVELOPER', 'DATA_ANALYST']
schema = obj(dict(
    schema_version=string('hop-product-occupations-v1'),
    source_id=string('INTERNAL_EDITORIAL'),
    catalogue_id=string('product-occupations'),
    catalogue_version=dict(type='integer', minimum=1, maximum=2147483647),
    actor=string(maximum=200), actor_kind=string('human', 'assistant'),
    scheme=obj(dict(code=string('product-occupations'), name=string(maximum=200), description=string())),
    occupations=dict(type='array', minItems=4, maxItems=4, items=obj(dict(
        code=string(*codes), name=string(maximum=200), description=string(),
        aliases=dict(type='array', maxItems=30, items=string(maximum=200)),
        boundary_notes=dict(type='array', minItems=1, maxItems=20, items=string()))))))
(OUT / 'schemas/product-occupations-v1.schema.json').write_text(json.dumps(schema, ensure_ascii=False, indent=2) + '\n')
compact = json.dumps(schema, ensure_ascii=False, separators=(',', ':'))
(OUT / 'sql/001_contract.sql').write_text('''-- This module depends on the installed native ontology and LLM schema validator.
BEGIN;
CREATE SCHEMA IF NOT EXISTS editorial;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE IF NOT EXISTS editorial.contract(version text PRIMARY KEY, schema jsonb NOT NULL, content_hash text NOT NULL);
INSERT INTO editorial.contract SELECT 'hop-product-occupations-v1',s,ontology.hash(s)
FROM (SELECT $contract$''' + compact + '''$contract$::jsonb s) v ON CONFLICT DO NOTHING;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM editorial.contract WHERE version='hop-product-occupations-v1'
  AND schema=$contract$''' + compact + '''$contract$::jsonb AND content_hash=ontology.hash(schema))
 THEN RAISE EXCEPTION 'EDITORIAL_CONTRACT_CHANGED'; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='editorial_contract_immutable' AND tgrelid='editorial.contract'::regclass) THEN
  CREATE TRIGGER editorial_contract_immutable BEFORE UPDATE OR DELETE ON editorial.contract
  FOR EACH ROW EXECUTE FUNCTION ontology.immutable();
 END IF;
END $$;
COMMIT;
''')
runpy.run_path(str(OUT/'tools/graph_build.py'))
runpy.run_path(str(OUT/'tools/occupations_build.py'))
runpy.run_path(str(OUT/'tools/occupation_graph_build.py'))
runpy.run_path(str(ROOT/'ontology/tools/build_editorial.py'), run_name='__main__')
runpy.run_path(str(ROOT/'ontology/tools/build_occupations.py'), run_name='__main__')

# Reuse only XML construction definitions, without running another generator.
source = (ROOT / 'hop/llm/tools/build.py').read_text()
wanted = {'put', 'child', 'node', 'Pipe', 'save', 'variables', 'db', 'execute', 'log', 'workflow'}
for definition in ast.parse(source).body:
    if isinstance(definition, (ast.FunctionDef, ast.ClassDef)) and definition.name in wanted:
        code = ast.get_source_segment(source, definition).replace("'llm-local'", "'ontology-local'").replace('/llm/', '/editorial/').replace(
            'LLM workflow failed. Inspect enrichment.batch_report and enrichment.attempt.',
            'Editorial workflow failed. Inspect this execution log; no failed import is partially committed.')
        exec(compile(code, str(__file__), 'exec'), globals())

p = Pipe('import_catalogue', 'Read exact file bytes and append a validated editorial source snapshot.')
reader = node('LoadFileInput', 'Read exact catalogue bytes', IsInFields='Y', DynamicFilenameField='catalogue_file',
              IsIgnoreEmptyFile='N', IsIgnoreMissingPath='N', encoding='UTF-8', addresultfile='N', limit=0)
child(E.SubElement(reader, 'fields'), 'field', dict(name='catalogue_bytes', element_type='content', type='Binary',
      length=-1, precision=-1, trim_type='none', repeat='N'))
fields = [('catalogue_file', '${CATALOGUE_FILE}', 'String'), ('expected_sha256', '${EXPECTED_SHA256}', 'String'),
          ('expected_git_blob', '${EXPECTED_GIT_BLOB}', 'String')]
p.chain(variables('Catalogue choices', fields), reader,
        db('Capture verified source', 'SELECT editorial.capture_v1(?::bytea,?::text,?::text) AS snapshot_id',
           [('catalogue_bytes', 'Binary'), ('expected_sha256', 'String'), ('expected_git_blob', 'String')]),
        log('Catalogue imported', ['snapshot_id'], 'Source captured. Import does not assert review, Git merge, classification or publication.'))
p.save()
workflow('import_catalogue.hwf', 'Import versioned product occupations', [
    ('CATALOGUE_FILE', '${PROJECT_HOME}/editorial/catalogues/product-occupations.v1.yaml', 'One UTF-8 JSON-subset YAML file; exact bytes are retained.'),
    ('EXPECTED_SHA256', '', 'Required lowercase SHA-256 from the reviewed file or staged checksum manifest.'),
    ('EXPECTED_GIT_BLOB', '', 'Required SHA-1 Git blob ID for those exact bytes; does not assert a commit or merge.')],
    [('Capture catalogue file', 'import_catalogue.hpl')], False)

params = [('REVIEW_ID', '', 'Caller-generated UUID; repeat it only for an identical decision.'),
          ('SNAPSHOT_ID', '', 'Exact imported file SHA-256.'), ('DECISION', 'REJECT', 'ACCEPT or REJECT.'),
          ('REVIEWER', '', 'Independent reviewer identity.'), ('REVIEWER_KIND', 'human', 'Actual reviewer kind: human or assistant.'),
          ('NOTES', '', 'Review rationale. Assistant ACCEPT cannot make a catalogue publication eligible.'),
          ('GIT_COMMIT', '', 'For human ACCEPT: actual main-branch commit containing this blob.'),
          ('MERGE_EVIDENCE', '', 'For human ACCEPT: review/merge reference checked by the operator; retained as an attestation.')]
p = Pipe('review_catalogue', 'Append an independent decision and explicit Git provenance attestation.')
p.chain(variables('Review choices', [(k.lower(), '${' + k + '}', 'String') for k, _, _ in params]),
        db('Record catalogue review', 'SELECT editorial.review_v1(?::uuid,?,?,?,?,?,?,?) AS recorded_review_id',
           [(k.lower(), 'String') for k, _, _ in params]),
        log('Review saved', ['recorded_review_id'], 'Review history is append-only. Existing release selections are unchanged.'))
p.save()
workflow('review_catalogue.hwf', 'Review editorial catalogue', params, [('Record independent decision', 'review_catalogue.hpl')], False)

p = Pipe('pin_catalogue', 'Freeze the current reviewed editorial revision in an unsealed ontology draft.')
p.chain(variables('Release and catalogue', [('release_id', '${RELEASE_ID}', 'String'), ('snapshot_id', '${SNAPSHOT_ID}', 'String')]),
        execute('Pin reviewed source', 'SELECT editorial.pin_v1(?,?)', ['release_id', 'snapshot_id']),
        log('Source pinned', ['release_id', 'snapshot_id'], 'Editorial membership frozen. Assemble remaining reviewed claims before loading this draft graph.'))
p.save()
workflow('pin_catalogue.hwf', 'Pin reviewed product occupations', [
    ('RELEASE_ID', '', 'Exact assembled, unsealed PREPARING release, before requirement normalization freeze.'),
    ('SNAPSHOT_ID', '', 'Exact latest imported catalogue version with a current independent human ACCEPT and Git attestation.')],
    [('Pin catalogue membership', 'pin_catalogue.hpl')], False)

p = Pipe('inspect_catalogues', 'Inspect imported catalogues, review outcomes and stable occupation IDs.')
p.chain(node('TableInput', 'Read editorial status', connection='jobtology-postgres',
             sql='SELECT * FROM editorial.catalogue_status ORDER BY catalogue_version DESC', limit=0, execute_each_row='N', variables_active='N'),
        node('Dummy', 'Preview catalogue status'))
p.save()
workflow('inspect_catalogues.hwf', 'Inspect editorial source status', [], [('Inspect catalogues', 'inspect_catalogues.hpl')], False)

# Reuse the exact native streaming export pipeline, with a new contract selector.
export=E.parse(ROOT/'hop/ontology/export_jsonld_v3.hpl').getroot()
put(export.find('info'),'name','export_jsonld_v4')
for transform in export.findall('transform'):
    if transform.findtext('type')=='TableInput':
        put(transform,'sql',transform.findtext('sql').replace('ontology.export_jsonld_v3','ontology.export_jsonld_v4'))
save(export,OUT/'export_jsonld_v4.hpl')
workflow('export_jsonld_v4.hwf','Export ontology with reviewed editorial source',[
    ('RELEASE_ID','','Exact sealed release; blank selects only an active published release.'),
    ('PREVIEW','N','Y explicitly exports a sealed draft. This does not assert publication readiness.')],
    [('Allocate export filename','../ontology/export_prepare.hpl'),('Write JSON-LD v4','export_jsonld_v4.hpl')],False)

export=E.parse(OUT/'export_jsonld_v4.hpl').getroot();put(export.find('info'),'name','export_jsonld_v5')
for transform in export.findall('transform'):
    if transform.findtext('type')=='TableInput':
        put(transform,'sql',transform.findtext('sql').replace('ontology.export_jsonld_v4','ontology.export_jsonld_v5'))
save(export,OUT/'export_jsonld_v5.hpl')
workflow('export_jsonld_v5.hwf','Export ontology with reviewed product occupations',[
    ('RELEASE_ID','','Exact sealed release; blank selects only an active published release.'),
    ('PREVIEW','N','Y explicitly exports a sealed draft; publication requirements remain enforced separately.')],
    [('Allocate export filename','../ontology/export_prepare.hpl'),('Write JSON-LD v5','export_jsonld_v5.hpl')],False)

# Versioned database reads include catalogue provenance without changing v1.
for kind,extra,arguments in [
    ('summary',[],[]),
    ('entity',[('ENTITY_ID','','Exact identity selected by this release.')],[('entity_id','${ENTITY_ID}','String')]),
    ('entities',[('ENTITY_KIND','','Optional public entity kind.'),('SCHEME_ID','','Optional exact scheme identity; filters members only.'),
                 ('PAGE_SIZE','100','1 to 100 rows.'),('CURSOR','','Returned v2 cursor from this release and filters.')],
                 [('entity_kind','${ENTITY_KIND}','String'),('scheme_id','${SCHEME_ID}','String'),
                  ('page_size','${PAGE_SIZE}','Integer'),('cursor_value','${CURSOR}','String')]),
    ('source_record',[('SUPPORT_ID','','Exact support_id returned by the v2 entity reader.')],[('support_id','${SUPPORT_ID}','String')])]:
    params=[('RELEASE_ID','','Exact release; blank selects only the active published release.')]+extra+[
        ('PREVIEW','N','Y explicitly reads a draft; failed and revoked releases remain unavailable.')]
    fields=[('release_id','${RELEASE_ID}','String')]+arguments+[('preview','${PREVIEW}','String')]
    placeholders=['?::text']+[('?::integer' if typ=='Integer' else "nullif(?::text,'')") for _,_,typ in arguments]+[
        "CASE ?::text WHEN 'Y' THEN true WHEN 'N' THEN false ELSE NULL END"]
    p=Pipe('read_'+kind+'_v2','Read frozen source facts and editorial review provenance.',{k:v for k,v,_ in params})
    p.chain(variables('Read choices',fields),db('Read versioned JSON',
        'SELECT ontology.query_'+kind+'_v2('+','.join(placeholders)+')::text AS result_json',[(k,t) for k,_,t in fields]),
        node('Dummy','Preview JSON here'))
    p.save()
    workflow('read_'+kind+'_v2.hwf','Read ontology '+kind+' v2',params,[('Read '+kind,'read_'+kind+'_v2.hpl')],False)

# The native occupation workflows are generated with these same XML helpers.
exec(compile((OUT/'tools/occupation_workflows.py').read_text(),str(OUT/'tools/occupation_workflows.py'),'exec'),globals())
exec(compile((OUT/'tools/derived_read_workflows.py').read_text(),str(OUT/'tools/derived_read_workflows.py'),'exec'),globals())

# A separate installer preserves the already-tested ontology v3 deployment package.
w = E.Element('workflow'); put(w, 'name', 'Install editorial source ledger')
actions = E.SubElement(w, 'actions'); hops = E.SubElement(w, 'hops')
child(actions, 'action', dict(name='Start', type='SPECIAL', start='Y', repeat='N', xloc=80, yloc=80, draw='Y'))
previous = 'Start'
for i, file in enumerate(sorted((OUT / 'sql').glob('*.sql')), 1):
    name = file.stem
    child(actions, 'action', dict(name=name, type='SQL', connection='jobtology-postgres',
          sql='', sqlfromfile='Y', sqlfilename='${PROJECT_HOME}/editorial/sql/' + file.name,
          sqlfilename_encoding='UTF-8', useVariableSubstitution='N', sendOneStatement='Y', xloc=80+240*(i%5), yloc=80+160*(i//5), draw='Y'))
    child(hops, 'hop', {'from': previous, 'to': name, 'enabled': 'Y', 'evaluation': 'Y', 'unconditional': 'Y' if previous == 'Start' else 'N'})
    child(hops, 'hop', {'from': name, 'to': 'Abort', 'enabled': 'Y', 'evaluation': 'N', 'unconditional': 'N'})
    previous = name
child(actions, 'action', dict(name='Success', type='SUCCESS', xloc=80, yloc=80+160*((i+5)//5), draw='Y'))
child(actions, 'action', dict(name='Abort', type='ABORT', message='Editorial installation failed; inspect SQL action log.', xloc=1040, yloc=80+160*((i+5)//5), draw='Y'))
child(hops, 'hop', {'from': previous, 'to': 'Success', 'enabled': 'Y', 'evaluation': 'Y', 'unconditional': 'N'})
save(w, OUT / 'install.hwf')

import hashlib
manifest = []
for path in sorted((OUT / 'catalogues').glob('*.yaml')):
    raw = path.read_bytes()
    manifest.append(dict(file=path.name, byte_length=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                         git_blob_sha1=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()))
(OUT / 'catalogues/checksums.json').write_text(json.dumps(manifest, indent=2)+'\n')
