"""Independent v5 binding reconstruction, selected review hashes and role edges."""
from decimal import Decimal
import runpy
from pathlib import Path

def verify(graph,release,manifest,mapping,native_properties,native_hash,JT,RDF,schema):
    nodes={str(graph.value(n,JT.nativeNodeId)):n for n in graph.subjects(JT.nativeNodeId,None)}
    cache={}
    def props(node):
        if type(node) is str:node=nodes[node]
        if node not in cache:cache[node]=native_properties(graph,node,mapping)
        return cache[node]
    def members(kind):return {str(graph.value(n,JT.nativeNodeId)):props(n) for n in graph.subjects(RDF.type,JT[kind])}
    groups={k:members(k) for k in ['OccupationFreeze','OccupationReviewSelection','OccupationProposal','OccupationReview',
        'OccupationBinding','OccupationBindingValue','PrimaryOccupationClaim','OccupationContract']}
    m=manifest.get('occupation_membership')
    if m is None:
        assert not any(groups.values()),'Occupation nodes without frozen membership'
        assert 'occupation_membership_hash' not in manifest and 'occupation_contract_hash' not in manifest
        return
    assert native_hash(m)==manifest['occupation_membership_hash'],'Occupation membership hash mismatch'
    assert m['format']=='hop-product-occupation-membership-v1' and m['release_id']==release
    edges={}
    for edge in graph.subjects(RDF.type,JT.Relation):
        subject=str(graph.value(edge,JT.nativeSubjectId));predicate=str(graph.value(edge,JT.nativePredicate));obj=str(graph.value(edge,JT.nativeObjectId))
        edges.setdefault((subject,predicate),[]).append((obj,props(edge)))
    def targets(subject,predicate):return {v for v,_ in edges.get((subject,predicate),[])}
    def only(subject,predicate):
        values=edges.get((subject,predicate),[]);assert len(values)==1,('Occupation relation cardinality',subject,predicate)
        return values[0][0]
    freeze_id='occupation-freeze/'+release;freeze=groups['OccupationFreeze']
    assert set(freeze)=={freeze_id},'Occupation freeze cardinality'
    assert {k:v for k,v in freeze[freeze_id].items() if k not in ('name','manifest_hash')}==m['freeze']
    assert freeze[freeze_id]['manifest_hash']==manifest['occupation_membership_hash']
    contract='occupation-contract/hop-product-occupation-proposal-v1'
    assert set(groups['OccupationContract'])=={contract}
    assert props(contract)['schema_hash']==native_hash(schema)==manifest['occupation_contract_hash']
    assert only(freeze_id,'USES_CONTRACT')==contract
    seen_values=set();bindings={}
    for root,b in groups['OccupationBinding'].items():
        bid=b['binding_id'];assert root=='occupation-binding/'+bid
        active=set()
        def decode(node,pointer):
            assert node in groups['OccupationBindingValue'] and node not in active,'Binding cycle or untyped value'
            active.add(node);assert node not in seen_values,'Binding value has multiple parents'
            seen_values.add(node);p=props(node)
            assert p['binding_id']==bid and p['pointer']==pointer,'Binding pointer mismatch'
            assert node=='occupation-value/'+native_hash([bid,pointer]),'Binding value identity mismatch'
            children=edges.get((node,'BINDING_MEMBER'),[]);kind=p['value_kind']
            if kind=='object':
                result={};assert p['member_count']==len(children) and 'value' not in p
                for child,edge in children:
                    assert set(edge)=={'member_key'},'Object member edge fields'
                    key=edge['member_key'];assert isinstance(key,str) and key not in result,'Duplicate object member'
                    result[key]=decode(child,pointer+'/'+key.replace('~','~0').replace('/','~1'))
            elif kind=='array':
                assert p['member_count']==len(children) and 'value' not in p
                assert all(set(e)=={'member_index'} and type(e['member_index']) is int for _,e in children)
                children.sort(key=lambda x:x[1]['member_index'])
                assert [e['member_index'] for _,e in children]==list(range(len(children))),'Array indices not contiguous'
                result=[decode(c,pointer+'/'+str(i)) for i,(c,_) in enumerate(children)]
            else:
                assert not children and 'member_count' not in p,'Scalar binding has children'
                if kind=='null':assert 'value' not in p;result=None
                else:
                    result=p['value']
                    assert (kind=='string' and type(result) is str) or (kind=='boolean' and type(result) is bool) or (
                        kind=='number' and type(result) in (int,float,Decimal)),'Binding scalar type mismatch'
            active.remove(node);return result
        value=decode(only(root,'HAS_BINDING_VALUE'),'')
        assert native_hash(value)==b['binding_hash'],'Binding content hash mismatch'
        assert bid==native_hash(['occupation-binding-v1',b['binding_kind'],value]),'Binding identity mismatch'
        bindings[root]=(b['binding_kind'],value)
    assert seen_values==set(groups['OccupationBindingValue']),'Orphan occupation binding values'
    validator=runpy.run_path(str(Path(__file__).with_name('validate_editorial.py')))['validate_source']
    proposal_fields='proposal_id proposal_no posting_entity_id posting_revision_id parent_id created_in_release source_binding_hash catalogue_snapshot_id occupation_id occupation_revision_id disposition created_at'.split()
    proposals={};used_bindings=set()
    for node,p in groups['OccupationProposal'].items():
        doc={k[len('proposal.'):]:v for k,v in p.items() if k.startswith('proposal.')}
        for key in p['proposal_null_fields']:assert key not in doc;doc[key]=None
        assert set(doc)==set(schema['required'])==set(schema['properties']),'Occupation proposal field set'
        for key,value in doc.items():
            spec=schema['properties'][key]
            if value is None:
                assert isinstance(spec['type'],list) and 'null' in spec['type'],'Unexpected null proposal field'
                if 'enum' in spec:assert None in spec['enum']
            else:validator(value,spec|{'type':'string'} if isinstance(spec['type'],list) else spec)
        source_id=only(node,'USES_SOURCE_BINDING');catalogue_id=only(node,'USES_CATALOGUE_BINDING')
        used_bindings.update([source_id,catalogue_id]);source_kind,source=bindings[source_id];cat_kind,catalogue=bindings[catalogue_id]
        assert source_kind=='SOURCE' and cat_kind=='CATALOGUE','Occupation binding role mismatch'
        assert source_id=='occupation-binding/'+p['source_binding_id'] and catalogue_id=='occupation-binding/'+p['catalogue_binding_id']
        assert native_hash(catalogue)==p['catalogue_binding_hash']
        row={k:p.get(k) for k in proposal_fields};row.update(document=doc,source_binding=source,catalogue_binding=catalogue)
        assert set(p['record_null_fields'])=={k for k,v in row.items() if v is None},'Proposal null field set'
        pid=native_hash(dict(document={k:v for k,v in doc.items() if k!='release_id'},source_binding=source,catalogue_binding=catalogue))
        assert pid==row['proposal_id'] and node=='occupation-proposal/'+pid,'Occupation proposal identity mismatch'
        for key in ['posting_entity_id','parent_id','source_binding_hash','catalogue_snapshot_id','occupation_id','disposition']:
            assert row[key]==doc[key],'Occupation proposal row/document mismatch'
        assert row['created_in_release']==doc['release_id'] and row['posting_revision_id']==source['posting_revision_id']
        assert row['posting_entity_id']==source['posting_entity_id'] and row['source_binding_hash']==native_hash(source)
        assert row['catalogue_snapshot_id']==catalogue['snapshot_id']
        assert only(node,'USES_CONTRACT')==contract and row['proposal_no']<=m['freeze']['proposal_cutoff']
        for key,expected in [('considered_duty_ids',[x['claim_id'] for x in source['duties']]),('considered_position_ids',[x['position_id'] for x in source['positions']])]:
            assert doc[key]==sorted(set(expected)),'Occupation considered input mismatch'
        evidence={x['evidence_id'] for x in source['evidence']}
        assert doc['evidence_ids']==sorted(set(doc['evidence_ids'])) and set(doc['evidence_ids'])<=evidence,'Occupation evidence outside binding'
        if doc['disposition']!='UNRESOLVED':
            assert source['extraction_outcome']=='ACCEPTED' and source['duties_status']=='explicit' and source['duties']
            assert set(doc['evidence_ids'])&{e['evidence_id'] for d in source['duties'] for e in d['evidence']},'Missing duty evidence'
        if doc['disposition']=='MATCH':
            target=[x for x in catalogue['definitions'] if x['entity_id']==doc['occupation_id']]
            assert len(target)==1 and target[0]['revision_id']==row['occupation_revision_id']
            assert target[0]['payload']['scheme_id']=='urn:jobtology:conceptScheme:product-occupations'
        else:assert row['occupation_id'] is None and row['occupation_revision_id'] is None
        assert (doc['disposition']=='UNRESOLVED')==(doc['unresolved_reason'] is not None)
        assert (doc['method']=='MANUAL' and doc['actor_kind']=='human' and doc['model_id'] is None and doc['prompt_version'] is None) or (
            doc['method']=='MODEL_INFERRED' and doc['actor_kind']=='assistant' and doc['model_id'] and doc['prompt_version']),'Occupation method provenance mismatch'
        proposals[pid]=row
    assert used_bindings==set(bindings),'Unused occupation bindings'
    reviews={}
    for node,p in groups['OccupationReview'].items():
        row={k:v for k,v in p.items() if k!='name'};reviews[row['decision_id']]=row
        assert node=='occupation-review/'+str(row['decision_id']) and row['decision_id']<=m['freeze']['decision_cutoff']
        assert only(node,'REVIEWS_PROPOSAL')=='occupation-proposal/'+row['proposal_id']
        assert row['reviewer'].strip()!=proposals[row['proposal_id']]['document']['actor'].strip(),'Occupation author self-review'
    selected=[];expected_claims={};seen_proposals=set();seen_reviews=set()
    posting_nodes=members('JobPostingRevision')
    def source_matches(source,posting):
        current=props('selection/'+release+'/'+posting['entity_id'])
        for key,expected in [('posting_payload_hash',posting['payload_hash']),('title',posting['name']),
            ('source_hash',current.get('source_hash')),('extraction_revision_id',current.get('extraction_revision_id')),
            ('extraction_decision_id',current.get('decision_id')),('extraction_outcome',current['outcome']),('duties_status',current.get('duties_status'))]:
            if source[key]!=expected:return False
        if {'claim/'+d['claim_id'] for d in source['duties']}!=targets('revision/'+posting['revision_id'],'HAS_DUTY'):return False
        if {'position/'+p['position_id'] for p in source['positions']}!=targets('revision/'+posting['revision_id'],'HAS_POSITION'):return False
        return True
    for node,p in groups['OccupationReviewSelection'].items():
        row={k:p.get(k) for k in ['release_id','entity_id','posting_revision_id','proposal_id','decision_id','outcome']};selected.append(row)
        assert row['release_id']==release and node=='occupation-selection/'+release+'/'+row['entity_id']
        subject=only(node,'HAS_SUBJECT');assert subject=='revision/'+row['posting_revision_id'] and subject in posting_nodes
        posting=props(subject);assert posting['entity_id']==row['entity_id']
        current=props('selection/'+release+'/'+row['entity_id'])
        proposal=proposals.get(row['proposal_id']);review=reviews.get(row['decision_id'])
        assert targets(node,'SELECTS_PROPOSAL')==({'occupation-proposal/'+row['proposal_id']} if proposal else set())
        assert targets(node,'REVIEWED_BY')==({'occupation-review/'+str(row['decision_id'])} if review else set())
        if proposal:seen_proposals.add(row['proposal_id']);assert proposal['posting_revision_id']==row['posting_revision_id']
        if review:seen_reviews.add(row['decision_id']);assert review['proposal_id']==row['proposal_id']
        if current['outcome']!='ACCEPTED':outcome='EXTRACTION_NOT_ACCEPTED'
        elif proposal is None:outcome='NOT_PROPOSED'
        elif not source_matches(proposal['source_binding'],posting):outcome='SOURCE_CHANGED'
        elif proposal['catalogue_binding']!=m['catalogue_binding']:outcome='CATALOGUE_CHANGED'
        elif review is None:outcome='PENDING'
        elif review['decision']=='REJECT':outcome='REJECTED'
        else:outcome='MATCHED' if proposal['disposition']=='MATCH' else proposal['disposition']
        assert row['outcome']==outcome,'Occupation selected outcome mismatch'
        if outcome=='MATCHED':
            claim=native_hash(['primary-product-occupation-v1',row['proposal_id'],row['decision_id']]);expected_claims[claim]=(row,proposal,review)
    assert len(selected)==m['selection_count']==m['posting_count']==len(posting_nodes),'Occupation posting coverage mismatch'
    assert len({s['entity_id'] for s in selected})==len(selected)
    assert targets(freeze_id,'HAS_OCCUPATION_SELECTION')==set(groups['OccupationReviewSelection'])
    assert seen_proposals==set(proposals) and seen_reviews==set(reviews),'Unselected occupation proposal/review'
    assert native_hash(sorted(selected,key=lambda s:s['entity_id']))==m['selection_hash'],'Occupation selection hash mismatch'
    assert native_hash(sorted(proposals.values(),key=lambda p:p['proposal_id']))==m['proposal_hash'],'Occupation proposal set hash mismatch'
    assert native_hash(sorted(reviews.values(),key=lambda d:d['decision_id']))==m['decision_hash'],'Occupation review set hash mismatch'
    editorial=manifest['editorial_membership']
    current_catalogue=dict(snapshot_id=editorial['snapshot_id'],source_contract='hop-product-occupations-v1',
        definitions=[{k:i[k] for k in ['entity_id','revision_id','payload_hash','payload']} for i in editorial['items']])
    assert m['catalogue_binding']==current_catalogue,'Occupation catalogue differs from pinned editorial source'
    actual={};shortcuts=[]
    for node,p in groups['PrimaryOccupationClaim'].items():
        claim=p['claim_id'];assert claim in expected_claims and node=='primary-occupation/'+claim
        row,proposal,review=expected_claims[claim];doc=proposal['document'];actual[claim]=True
        for key in ['proposal_id','decision_id','posting_revision_id']:assert p[key]==row[key]
        for key in ['occupation_id','occupation_revision_id']:assert p[key]==proposal[key]
        for key in ['reviewer','reviewer_kind','notes','reviewed_at']:assert p[key]==review[key]
        assert p['review_status']==('HUMAN_ACCEPTED' if review['reviewer_kind']=='human' else 'ASSISTANT_REVIEWED')
        assert p['confidence_state']=='UNASSESSED' and 'confidence' not in p
        assert p['method']==doc['method'] and p['resolver_version']==doc['resolver_version']
        assert p['assertion_kind']==('MODEL_INFERRED' if doc['method']=='MODEL_INFERRED' else 'NORMALIZED')
        subject='revision/'+row['posting_revision_id'];target='entity/'+proposal['occupation_id'];target_revision='revision/'+proposal['occupation_revision_id']
        assert only(node,'HAS_SUBJECT')==subject and only(node,'TARGETS')==target and only(node,'SELECTS_REVISION')==target_revision
        assert props(target_revision)['entity_id']==proposal['occupation_id']
        assert props(target_revision)['scheme_id']=='urn:jobtology:conceptScheme:product-occupations'
        assert only(node,'DERIVED_FROM')=='occupation-proposal/'+row['proposal_id']
        assert only(node,'REVIEWED_BY')=='occupation-review/'+str(row['decision_id'])
        assert targets(node,'EVIDENCED_BY')=={'evidence/'+e for e in doc['evidence_ids']}
        for duty in proposal['source_binding']['duties']:
            current=props('claim/'+duty['claim_id'])
            for key in ['claim_id','posting_revision_id','kind','ordinal','text','applicability']:assert current[key]==duty[key],'Bound duty differs from selected duty'
            assert duty['content_hash']==native_hash(duty['payload'])
            assert duty['claim_id']==native_hash([duty['posting_revision_id'],'duties',duty['ordinal'],duty['payload']])
            assert targets('claim/'+duty['claim_id'],'APPLIES_TO')=={'position/'+x for x in duty['position_ids']}
            assert sorted(edges.get(('claim/'+duty['claim_id'],'EVIDENCED_BY'),[]),key=lambda x:x[1]['part_index'])==[
                ('evidence/'+x['evidence_id'],{'part_index':x['part_index']}) for x in duty['evidence']]
        for ev in proposal['source_binding']['evidence']:
            current=props('evidence/'+ev['evidence_id']);artifact=props('artifact/'+ev['artifact_id'])
            for key in ['evidence_id','artifact_id','start_offset','end_offset','excerpt','excerpt_sha256','offset_unit','locator_version']:
                assert current[key]==ev[key],'Bound occupation evidence differs from current span'
            assert artifact['text_sha256']==ev['artifact_text_hash'] and artifact['input_sha256']==ev['artifact_input_hash']
        shortcuts.append((subject,target,dict(source_assertion_ids=[claim],methodology_version='product-occupation-graph-v1')))
    assert set(actual)==set(expected_claims),'Primary occupation claim membership mismatch'
    actual_edges=[(s,o,p) for (s,pred),vals in edges.items() if pred=='FOR_OCCUPATION' for o,p in vals]
    assert sorted(actual_edges)==sorted(shortcuts),'Primary occupation shortcut or assertion support mismatch'
