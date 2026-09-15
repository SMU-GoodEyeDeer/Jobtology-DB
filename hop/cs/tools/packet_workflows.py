"""Generate native Hop JSON-file transport for explicit CS position reviews.

This module is standalone for development. cs/tools/build.py may execute it
after creating the install workflow; it does not run any ETL or model request.
"""
from pathlib import Path
import ast
import xml.etree.ElementTree as E

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'hop/cs'
helper_source=(ROOT/'hop/llm/tools/build.py').read_text()
for definition in ast.parse(helper_source).body:
    if isinstance(definition,(ast.FunctionDef,ast.ClassDef)) and definition.name in {
        'put','child','node','Pipe','save','variables','db','log','workflow'
    }:
        code=ast.get_source_segment(helper_source,definition)
        if definition.name=='workflow':
            code=code.replace('/llm/','/cs/').replace(
                'LLM workflow failed. Inspect enrichment.batch_report and enrichment.attempt.',
                'CS scope review workflow failed. Inspect the PostgreSQL or Hop log.')
        exec(compile(code,__file__,'exec'),globals())

params=[
 ('SOURCE_ID','','Optional source ID. Blank selects all current sources.'),
 ('SCOPE_STATUS','NEEDS_REVIEW','Current scope status to export. Blank selects all.'),
 ('POSTING_IDENTITIES','','Optional | separated source-qualified posting identities from read_scope.hwf.'),
 ('POSITION_LIMIT','1000','Hard cap, 1–1000. Reduce the selection if exceeded.'),
 ('ACTOR','','Operator preparing this file, distinct from its reviewer.'),
 ('REVIEW_FILE','${PROJECT_HOME}/data/cs/scope-review.json',
  'New UTF-8 JSON file. An existing file is never overwritten.')]
fields=[('source_filter','${SOURCE_ID}','String'),
        ('status_filter','${SCOPE_STATUS}','String'),
        ('posting_identities','${POSTING_IDENTITIES}','String'),
        ('cap','${POSITION_LIMIT}','String'),
        ('actor','${ACTOR}','String'),
        ('review_filename','${REVIEW_FILE}','String')]
p=Pipe('export_scope_review',
       'Write current source-bound role contexts and blank explicit review decisions.')
p.chain(variables('Review selection',fields),
 db('Build frozen role packet',
    "SELECT convert_to(jsonb_pretty(cs.prepare_scope_review_v1(?,?,?,?::integer,?)),'UTF8') AS review_bytes",
    [('source_filter','String'),('status_filter','String'),
     ('posting_identities','String'),('cap','String'),('actor','String')]),
 node('BinaryFileOutput','Save scope packet',binaryfield='review_bytes',
      filenamefield='review_filename',createparentfolder='Y',overwritefile='N',
      addresultfilenames='N'),
 log('Scope packet written',['review_filename'],
     'Name the reviewer and fill explicit decisions, families and source-grounded notes.'))
p.save()
workflow('export_scope_review.hwf','Export current position-scope review packet',
         params,[('Export role and source contexts','export_scope_review.hpl')],False)

p=Pipe('import_scope_review',
       'Validate every frozen role/source context and save explicit decisions atomically.')
reader=node('JsonInput','Read reviewed scope packet',IsInFields='Y',
            IsAFile='Y',valueField='review_filename',removeSourceField='N',
            ignoreMissingPath='N',defaultPathLeafToNull='Y',doNotFailIfNoFile='N')
child(E.SubElement(reader,'fields'),'field',dict(
    name='review_json',path='$',type='String',length=-1,precision=-1,
    trim_type='none',repeat='N'))
p.chain(variables('Review file',[('review_filename','${REVIEW_FILE}','String')]),
        reader,
        db('Apply named scope decisions',
           'SELECT cs.apply_scope_review_v1(?::jsonb)::text AS receipt',
           [('review_json','String')]),
        log('Scope review receipt',['receipt'],
            'Position decisions were saved. Assess scope before publishing NCS links.'))
p.save()
workflow('import_scope_review.hwf','Import completed position-scope review packet',
         [('REVIEW_FILE','${PROJECT_HOME}/data/cs/scope-review-completed.json',
           'Named JSON review packet with at least one explicit decision and notes.')],
         [('Validate context and save decisions','import_scope_review.hpl')],False)

# The regular cs/install.hwf installs all SQL in sequence. This small install
# workflow is useful when 001–003 are already live and only the packet
# transport needs deployment.
w=E.Element('workflow')
put(w,'name','Install position-scope review transport')
put(w,'description','Install immutable review receipts and JSON packet functions')
put(w,'workflow_version','1');put(w,'workflow_status','0')
E.SubElement(w,'parameters')
actions=E.SubElement(w,'actions');hops=E.SubElement(w,'hops')
child(actions,'action',dict(name='Start',type='SPECIAL',start='Y',repeat='N',
    xloc=80,yloc=80,draw='Y',parallel='N'))
child(actions,'action',dict(name='Install scope review SQL',type='SQL',
    connection='jobtology-postgres',sqlfromfile='Y',
    sqlfilename='${PROJECT_HOME}/cs/sql/004_scope_packets.sql',
    sqlfilename_encoding='UTF-8',useVariableSubstitution='N',
    sendOneStatement='Y',xloc=320,yloc=80,draw='Y',parallel='N'))
child(actions,'action',dict(name='Success',type='SUCCESS',xloc=560,yloc=80,
    draw='Y',parallel='N'))
child(actions,'action',dict(name='Abort',type='ABORT',
    message='CS scope review SQL installation failed.',xloc=560,yloc=240,
    draw='Y',parallel='N'))
for source,target,success in [('Start','Install scope review SQL',True),
                              ('Install scope review SQL','Success',True),
                              ('Install scope review SQL','Abort',False)]:
    child(hops,'hop',{'from':source,'to':target,'enabled':'Y',
                     'evaluation':'Y' if success else 'N',
                     'unconditional':'Y' if source=='Start' else 'N'})
E.SubElement(w,'notepads');E.SubElement(w,'attributes')
save(w,OUT/'install_scope_review.hwf')
