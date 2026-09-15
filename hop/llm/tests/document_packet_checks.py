"""Independent decoding of model packets; no inference or acceptance decisions."""
import collections
import copy
import json


def assert_packet(source,packet,passages):
    assert packet['source_encoding']=='field-lines-and-tables-v1'
    decoded={field+':'+str(number):text for field,rows in packet['source_passages'].items() for number,text in rows}
    assert decoded=={p['id']:p['text'] for p in passages}
    assert sum(len(rows) for rows in packet['source_passages'].values())==len(decoded)
    for field,rows in packet['source_passages'].items():
        assert rows==sorted(rows,key=lambda r:r[0])
        assert all(source[field].split('\n')[n-1]==text for n,text in rows)
    if '_input' not in source:
        assert 'source_documents' not in packet
        return dict(fields=len(packet['source_passages']),tables=0,cells=0,blocks=0)
    assert packet['document_outcomes']==source['_input']['documents']
    assert set(packet['source_documents'])==set(source['_input']['fields'])
    counts=collections.Counter(fields=len(packet['source_passages']))
    for field,metadata in source['_input']['fields'].items():
        doc=packet['source_documents'][field]
        for key in ['file_id','name','role','parser_version']:assert doc[key]==metadata.get(key)
        lines=[p for p in passages if p['field']==field]
        def line_ids(block):
            return [int(p['id'].rsplit(':',1)[1]) for p in lines if p['start']-1<block['end'] and p['end']>block['start']]
        if metadata['parser_version']!='hwpx-xml-structure-v1':
            expected=[]
            for b in metadata['sections']:
                numbers=line_ids(b)
                expected.append(dict(kind=b.get('locator_kind'),locator=b.get('locator'),
                                     first_line=numbers[0] if numbers else None,last_line=numbers[-1] if numbers else None))
            assert doc['sections']==expected
            continue
        layout=doc['layout'];assert layout['encoding']=='hwpx-rows-v1'
        expected_blocks={(b['section_no'],b['block_no']):b for b in metadata['sections']}
        expected_tables={(t['section_no'],t['table_no']):t for t in metadata['tables']}
        expected_cells={(c['section_no'],c['cell_no']):c for c in metadata['cells']}
        got_blocks={};got_tables={};got_cells={}
        for section in layout['sections']:
            sec=section['section']
            def block(row,table=None,cell=None):
                key=(sec,row[0]);assert key not in got_blocks
                b=expected_blocks[key]
                assert section['entry']==b['entry_name']
                assert row[:4]==[b['block_no'],b['paragraph_no'],b['context_role'],line_ids(b)]
                assert [table,cell]==[b['table_no'],b['cell_no']]
                got_blocks[key]=row
            for row in section['body_blocks']:block(row,row[4],row[5])
            for table in section['tables']:
                key=(sec,table['table']);assert key not in got_tables
                expected=expected_tables[key];got_tables[key]=table
                assert section['entry']==expected['entry_name']
                assert table['parent']==[expected['parent_table_no'],expected['parent_cell_no']]
                assert table['dimensions']==[expected['rows'],expected['cols']]
                for row_no,cells in table['rows']:
                    assert cells==sorted(cells,key=lambda c:(c[1],c[0]))
                    for c in cells:
                        ckey=(sec,c[0]);assert ckey not in got_cells
                        e=expected_cells[ckey];got_cells[ckey]=c
                        assert e['table_no']==table['table'] and e['row_no']==row_no
                        assert c[:5]==[e['cell_no'],e['col_no'],e['row_span'],e['col_span'],e['is_header']]
                        for b in c[5]:block(b,table['table'],c[0])
                for key_name in ['preceding_body_blocks','following_body_blocks']:
                    for number in table[key_name]:
                        b=expected_blocks[(sec,number)]
                        assert b['cell_no'] is None
        assert set(got_blocks)==set(expected_blocks)
        assert set(got_tables)==set(expected_tables)
        assert set(got_cells)==set(expected_cells)
        counts.update(blocks=len(got_blocks),tables=len(got_tables),cells=len(got_cells))
    return dict(counts)


def check_packet_sql(sql,js):
    source=dict(title='😀 한 개발자',eligibility_text='첫째\r\n\n둘째 "문장"\n[4, "untrusted text"]')
    packet=json.loads(sql(f'SELECT enrichment.document_packet_v1({js(source)})'))
    passages=json.loads(sql(f'SELECT enrichment.source_passages_v2({js(source)})'))
    assert_packet(source,packet,passages)
    assert packet['source_passages']['eligibility_text'][1][0]==3
    assert packet['source_passages']['eligibility_text'][0][1]=='첫째\r'
    # Nested table caption owners need not be a cell of their nearest table.
    # Empty tables/sections and merged cells must survive model projection too.
    field='attachment_1_9';body='😀 제목\r\n\n자격\n10\n각주'
    source=dict(_input=dict(contract='attachment-input-v2',documents=[dict(outcome='PARSED',field=field)],fields={}),**{field:body})
    blocks=[]
    for no,text,table,cell,role in [(1,'😀 제목\r',None,None,'body'),(2,'자격',1,1,'body'),(3,'10',2,2,'body'),(4,'각주',2,1,'caption')]:
        start=body.index(text)
        blocks.append(dict(section_no=1,entry_name='Contents/section0.xml',block_no=no,paragraph_no=no,
                           table_no=table,cell_no=cell,context_role=role,start=start,end=start+len(text)))
    tables=[dict(section_no=1,entry_name='Contents/section0.xml',table_no=1,parent_table_no=None,parent_cell_no=None,rows=2,cols=2),
            dict(section_no=1,entry_name='Contents/section0.xml',table_no=2,parent_table_no=1,parent_cell_no=1,rows=1,cols=1),
            dict(section_no=2,entry_name='Contents/section1.xml',table_no=1,parent_table_no=None,parent_cell_no=None,rows=1,cols=1)]
    cells=[dict(section_no=1,entry_name='Contents/section0.xml',table_no=1,cell_no=1,row_no=0,col_no=0,row_span=2,col_span=2,is_header=True),
           dict(section_no=1,entry_name='Contents/section0.xml',table_no=2,cell_no=2,row_no=0,col_no=0,row_span=1,col_span=1,is_header=False),
           dict(section_no=2,entry_name='Contents/section1.xml',table_no=1,cell_no=1,row_no=0,col_no=0,row_span=1,col_span=1,is_header=False)]
    source['_input']['fields'][field]=dict(file_id='9',name='fixture.hwpx',role='A',parser_version='hwpx-xml-structure-v1',sections=blocks,tables=tables,cells=cells)
    packet=json.loads(sql(f'SELECT enrichment.document_packet_v1({js(source)})'))
    passages=json.loads(sql(f'SELECT enrichment.source_passages_v2({js(source)})'))
    assert assert_packet(source,packet,passages)==dict(fields=1,blocks=4,tables=3,cells=3)
    assert packet['source_documents'][field]['layout']['sections'][1]['tables'][0]['rows'][0][1][0][-1]==[]
    print('Grouped source decoding, Unicode/blank lines, merged/nested/empty cells and caption ownership passed',flush=True)
