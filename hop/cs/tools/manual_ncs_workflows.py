"""Generate native Hop JSON export/import for explicit reviewer NCS candidates.

No ETL, provider call or database action is run by this generator.
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
                'Manual NCS review workflow failed. Inspect the PostgreSQL or Hop log.')
        exec(compile(code,__file__,'exec'),globals())


def json_file_input(transform_name,filename_field,output_field):
    reader=node('JsonInput',transform_name,IsInFields='Y',IsAFile='Y',
                valueField=filename_field,removeSourceField='N',
                ignoreMissingPath='N',defaultPathLeafToNull='Y',
                doNotFailIfNoFile='N')
    child(E.SubElement(reader,'fields'),'field',dict(
        name=output_field,path='$',type='String',length=-1,precision=-1,
        trim_type='none',repeat='N'))
    return reader


export_params=[
 ('SELECTION_FILE','${PROJECT_HOME}/data/cs/manual-ncs-selection.json',
  'UTF-8 JSON object with a selections array of exact posting_identity, role_id, zero-based duty_index and competency_code choices.'),
 ('ACTOR','','Operator preparing the source-bound review packet.'),
 ('REVIEW_FILE','${PROJECT_HOME}/data/cs/manual-ncs-review.json',
  'New UTF-8 JSON packet; an existing file is never overwritten.')]
p=Pipe('export_manual_ncs_review',
       'Freeze current accepted role/duty and complete NCS catalog definitions.')
p.chain(variables('Selection file and output',[
    ('selection_filename','${SELECTION_FILE}','String'),
    ('actor','${ACTOR}','String'),
    ('review_filename','${REVIEW_FILE}','String')]),
    json_file_input('Read exact role/duty/NCS selections','selection_filename','selection_json'),
    db('Validate and prepare manual NCS review',
       "SELECT convert_to(jsonb_pretty(cs.prepare_manual_ncs_link_review_v1(?::jsonb->'selections',?)),'UTF8') AS review_bytes",
       [('selection_json','String'),('actor','String')]),
    node('BinaryFileOutput','Save manual NCS packet',binaryfield='review_bytes',
         filenamefield='review_filename',createparentfolder='Y',overwritefile='N',
         addresultfilenames='N'),
    log('Manual NCS packet written',['review_filename'],
        'Review each full NCS definition against its explicit position-bound duty; fill named decisions.'))
p.save()
workflow('export_manual_ncs_review.hwf','Export current role-specific manual NCS review packet',
         export_params,[('Freeze exact source and NCS context','export_manual_ncs_review.hpl')],False)

p=Pipe('import_manual_ncs_review',
       'Atomically validate and append only explicit reviewer candidate decisions.')
p.chain(variables('Completed review file',[('review_filename','${REVIEW_FILE}','String')]),
    json_file_input('Read completed manual NCS review','review_filename','review_json'),
    db('Validate and record manual NCS choices',
       'SELECT cs.apply_manual_ncs_link_review_v1(?::jsonb)::text AS receipt',
       [('review_json','String')]),
    log('Manual NCS review receipt',['receipt'],
        'Decisions were saved in PostgreSQL; run llm/publish_links.hwf separately to update Neo4j.'))
p.save()
workflow('import_manual_ncs_review.hwf','Import completed role-specific manual NCS review packet',
         [('REVIEW_FILE','${PROJECT_HOME}/data/cs/manual-ncs-review-completed.json',
           'Completed JSON packet with reviewer, reviewer_kind, and explicit cases.')],
         [('Validate and record decisions','import_manual_ncs_review.hpl')],False)

w=E.Element('workflow')
put(w,'name','Install manual NCS candidate review transport')
put(w,'description','Install source and NCS bound manual reviewer candidate packet SQL')
put(w,'workflow_version','1');put(w,'workflow_status','0')
E.SubElement(w,'parameters');actions=E.SubElement(w,'actions');hops=E.SubElement(w,'hops')
child(actions,'action',dict(name='Start',type='SPECIAL',start='Y',repeat='N',
    xloc=80,yloc=80,draw='Y',parallel='N'))
child(actions,'action',dict(name='Install manual NCS review SQL',type='SQL',
    connection='jobtology-postgres',sqlfromfile='Y',
    sqlfilename='${PROJECT_HOME}/cs/sql/005_manual_ncs_links.sql',
    sqlfilename_encoding='UTF-8',useVariableSubstitution='N',
    sendOneStatement='Y',xloc=320,yloc=80,draw='Y',parallel='N'))
child(actions,'action',dict(name='Success',type='SUCCESS',xloc=560,yloc=80,
    draw='Y',parallel='N'))
child(actions,'action',dict(name='Abort',type='ABORT',
    message='Manual NCS review SQL installation failed.',xloc=560,yloc=240,
    draw='Y',parallel='N'))
for source,target,success in [('Start','Install manual NCS review SQL',True),
                              ('Install manual NCS review SQL','Success',True),
                              ('Install manual NCS review SQL','Abort',False)]:
    child(hops,'hop',{'from':source,'to':target,'enabled':'Y',
                     'evaluation':'Y' if success else 'N',
                     'unconditional':'Y' if source=='Start' else 'N'})
E.SubElement(w,'notepads');E.SubElement(w,'attributes')
save(w,OUT/'install_manual_ncs_review.hwf')
