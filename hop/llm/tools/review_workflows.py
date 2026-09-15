"""Native JSON-file transport for explicit batch reviews, without acceptance defaults."""
from pathlib import Path
import ast,xml.etree.ElementTree as E
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'hop/llm'
source=(OUT/'tools/build.py').read_text()
for d in ast.parse(source).body:
 if isinstance(d,(ast.FunctionDef,ast.ClassDef)) and d.name in {'put','child','node','Pipe','save','variables','db','log','workflow'}:exec(compile(ast.get_source_segment(source,d),__file__,'exec'),globals())
p=Pipe('export_link_review','Capture validated production outputs and write a review packet; no decisions are made.')
fields=[('batch_id','${BATCH_ID}','String'),('posting_ids','${POSTING_IDS}','String'),('cap','${POSTING_LIMIT}','String'),('actor','${ACTOR}','String'),('review_filename','${REVIEW_FILE}','String')]
p.chain(variables('Review options',fields),db('Build review packet',"SELECT convert_to(jsonb_pretty(enrichment.prepare_link_review(?,?,?::integer,?)),'UTF8') AS review_bytes",[(k,t) for k,_,t in fields[:-1]]),node('BinaryFileOutput','Save review packet',binaryfield='review_bytes',filenamefield='review_filename',createparentfolder='Y',overwritefile='N',addresultfilenames='N'),log('Review file written',['batch_id','review_filename'],'Fill named reviewer, explicit decisions and notes. Null decisions remain pending.'));p.save()
workflow('export_link_review.hwf','Prepare a batch of independent NCS-link reviews',[
 ('BATCH_ID','','Terminal ENRICH batch; EVAL is forbidden.'),('POSTING_IDS','','Optional | separated posting IDs.'),('POSTING_LIMIT','20','Fail above cap; select a smaller review group or raise it explicitly.'),('ACTOR','','Operator preparing the file, not its semantic reviewer.'),('REVIEW_FILE','${PROJECT_HOME}/data/llm/link-review.json','New UTF-8 JSON file; existing files are not overwritten.')],[('Prepare source and candidate review','export_link_review.hpl')],False)
p=Pipe('import_link_review','Apply explicit reviewed decisions atomically; reject changed source/context or stale decisions.')
r=node('JsonInput','Read review packet',IsInFields='Y',IsAFile='Y',valueField='review_filename',removeSourceField='N',ignoreMissingPath='N',defaultPathLeafToNull='Y',doNotFailIfNoFile='N')
child(E.SubElement(r,'fields'),'field',dict(name='review_json',path='$',type='String',length=-1,precision=-1,trim_type='none',repeat='N'))
p.chain(variables('Review file',[('review_filename','${REVIEW_FILE}','String')]),r,db('Apply explicit decisions','SELECT enrichment.apply_link_review(?::jsonb)::text AS outcome',[('review_json','String')]),log('Review receipt',['outcome'],'No graph write occurred. Run publish_links.hwf after review.'));p.save()
workflow('import_link_review.hwf','Import a completed batch of independent reviews',[('REVIEW_FILE','${PROJECT_HOME}/data/llm/link-review-completed.json','Reviewed UTF-8 JSON. Blank decisions are skipped; notes and accurate reviewer identity are required.')],[('Validate context and save decisions','import_link_review.hpl')],False)
w=E.parse(OUT/'install_link_publication.hwf').getroot();put(w,'name','Install bulk independent review transport');w.find("actions/action[type='SQL']/sqlfilename").text='${PROJECT_HOME}/llm/sql/024_review_packets.sql';save(w,OUT/'install_link_review.hwf')
