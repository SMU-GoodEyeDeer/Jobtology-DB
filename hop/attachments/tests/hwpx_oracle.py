"""Independent archive/XML oracle; never used to transform production data."""
import hashlib,json,zipfile,xml.etree.ElementTree as E
from checks import sql,q
HP='{http://www.hancom.co.kr/hwpml/2011/paragraph}';OPF='{http://www.idpf.org/2007/opf/}'

def verify(row,original):
 sid=row['structure_id'];bodies=[];counts=dict(atoms=0,cells=0,blocks=0,tables=0)
 def rows(table,entry,order):
  return json.loads(sql(f"SELECT coalesce(jsonb_agg(to_jsonb(a)-'structure_id'-'entry_name' ORDER BY {order}),'[]') FROM attachment.{table} a WHERE structure_id={q(sid)} AND entry_name={q(entry)}"))
 entries=json.loads(sql(f"SELECT jsonb_agg(jsonb_build_object('name',entry_name,'hash',raw_hash,'bytes',byte_length) ORDER BY entry_name) FROM attachment.hwpx_entry WHERE structure_id={q(sid)}"))
 with zipfile.ZipFile(original) as z:
  manifest=E.fromstring(z.read('Contents/content.hpf'))
  items={i.attrib['id']:i.attrib['href'] for i in manifest.find(OPF+'manifest')}
  names=[items[i.attrib['idref']] for i in manifest.find(OPF+'spine')]
  assert {e['name'] for e in entries}=={'Contents/content.hpf',*names}
  for entry in entries:
   raw=z.read(entry['name']);assert len(raw)==entry['bytes'] and hashlib.sha256(raw).hexdigest()==entry['hash']
  for name in names:
   if name=='Contents/header.xml':continue
   tree=E.fromstring(z.read(name));parents={c:p for p in tree.iter() for c in p}
   indexes={kind:{e:i for i,e in enumerate((e for e in tree.iter() if e.tag==HP+kind),1)} for kind in ['p','tbl','tc']}
   def chain(e):
    result=[]
    while e in parents:e=parents[e];result.append(e)
    return result
   def nearest(nodes,kind):return next((indexes[kind][e] for e in nodes if e.tag==HP+kind),None)
   events=[]
   for t in (e for e in tree.iter() if e.tag==HP+'t'):
    owners=chain(t);role=next((kind.lower() for kind in ['header','footer','footNote','endNote'] if any(e.tag==HP+kind for e in owners)),'body');parts=[]
    if t.text is not None:parts.append(('text',t.text))
    for c in t:
     kind=c.tag[len(HP):] if c.tag.startswith(HP) else c.tag
     parts.append((kind,{'lineBreak':'\n','tab':'\t','fwSpace':'\u3000','nbSpace':'\u00a0'}.get(kind,'')))
     if c.tail is not None:parts.append(('text',c.tail))
    for kind,text in parts:events.append(dict(event_no=len(events)+1,paragraph_no=nearest(owners,'p'),table_no=nearest(owners,'tbl'),cell_no=nearest(owners,'tc'),context_role=role,kind=kind,content=text))
   assert rows('hwpx_atom',name,'event_no')==events,'XML text/control order or ancestry changed'
   tables=[]
   for t,i in indexes['tbl'].items():
    tables.append(dict(table_no=i,parent_table_no=nearest(chain(t),'tbl'),parent_cell_no=nearest(chain(t),'tc'),rows=int(t.get('rowCnt')),cols=int(t.get('colCnt'))))
   assert rows('hwpx_table',name,'table_no')==tables,'Nested table ownership changed'
   cells=[]
   for c,i in indexes['tc'].items():
    addr=c.find(HP+'cellAddr').attrib;span=c.find(HP+'cellSpan').attrib
    cells.append(dict(cell_no=i,table_no=nearest(chain(c),'tbl'),row_no=int(addr['rowAddr']),col_no=int(addr['colAddr']),row_span=int(span['rowSpan']),col_span=int(span['colSpan']),is_header=c.get('header','0')=='1'))
   assert rows('hwpx_cell',name,'cell_no')==cells,'Table geometry or ownership changed'
   blocks=[];previous=None
   for e in events:
    keys=['paragraph_no','table_no','cell_no','context_role'];owner=tuple(e[k] for k in keys)
    if owner!=previous:
     blocks.append(dict(block_no=len(blocks)+1,**{k:e[k] for k in keys},first_event=e['event_no'],last_event=e['event_no'],content=''));previous=owner
    blocks[-1]['content']+=e['content'];blocks[-1]['last_event']=e['event_no']
   for b in blocks:b['content_hash']=hashlib.sha256(b['content'].encode()).hexdigest()
   assert rows('hwpx_block',name,'block_no')==blocks,'Paragraph block order or event binding changed'
   bodies.extend(b['content'] for b in blocks if b['content'].strip(' \t\r\n\u3000\u00a0'))
   for k,v in [('atoms',events),('tables',tables),('cells',cells),('blocks',blocks)]:counts[k]+=len(v)
 body='\n'.join(bodies)
 assert row['body_text']==body and row['body_hash']==hashlib.sha256(body.encode()).hexdigest()
 return dict(counts=counts,entries=entries,body_chars=len(body))
