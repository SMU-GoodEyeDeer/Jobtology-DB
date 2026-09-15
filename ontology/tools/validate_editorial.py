"""Independently reconstruct editorial definitions from exported exact source bytes."""
import hashlib
import json
import re

def validate_source(value,schema):
    """Only the small, closed JSON Schema subset in the local v1 catalogue contract."""
    allowed={'type','properties','required','additionalProperties','items','minItems','maxItems','minLength','maxLength','enum','minimum','maximum'}
    assert set(schema)<=allowed,'Unknown editorial source schema keyword'
    kind=schema['type']
    assert {'object':type(value) is dict,'array':type(value) is list,'string':type(value) is str,
            'integer':type(value) is int}.get(kind,False),'Editorial source field type'
    if 'enum' in schema:assert value in schema['enum'],'Editorial source enum'
    if kind=='object':
        assert set(value)==set(schema['required'])==set(schema['properties']),'Editorial source field set'
        assert schema['additionalProperties'] is False
        for key,child in value.items():validate_source(child,schema['properties'][key])
    elif kind=='array':
        assert schema.get('minItems',0)<=len(value)<=schema.get('maxItems',2147483647),'Editorial source array length'
        for child in value:validate_source(child,schema['items'])
    elif kind=='string':
        assert schema.get('minLength',0)<=len(value)<=schema.get('maxLength',2147483647) and value.strip(),'Editorial source text'
    elif kind=='integer':assert schema['minimum']<=value<=schema['maximum'],'Editorial source integer range'

def verify(graph,release,manifest,mapping,native_properties,native_hash,JT,RDF,schema):
    def props(node):return native_properties(graph,node,mapping)
    def node_id(node):return str(graph.value(node,JT.nativeNodeId))
    def unique(kind):
        values=list(graph.subjects(RDF.type,kind));assert len(values)==1,('Editorial node cardinality',kind)
        return values[0]
    def targets(node,predicate):return {node_id(x) for x in graph.objects(node,predicate)}
    def duplicate_keys(pairs):
        result=dict(pairs);assert len(result)==len(pairs),'Editorial source duplicate JSON key'
        return result
    classes=[JT.EditorialSourceSnapshot,JT.EditorialSourceRecord,JT.EditorialReview,JT.EditorialReleaseSelection,JT.EditorialContract]
    member=manifest.get('editorial_membership')
    if member is None:
        assert not any(list(graph.subjects(RDF.type,k)) for k in classes),'Editorial nodes without frozen membership'
        assert 'editorial_membership_hash' not in manifest and 'editorial_contract_hash' not in manifest
        return
    assert native_hash(member)==manifest['editorial_membership_hash'],'Editorial membership hash mismatch'
    assert member['format']=='hop-editorial-membership-v1' and member['source_id']=='INTERNAL_EDITORIAL'
    source_node=unique(JT.EditorialSourceSnapshot);source=props(source_node)
    raw=source['source_text'].encode('utf-8');sha=hashlib.sha256(raw).hexdigest()
    blob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    assert sha==member['snapshot_id']==source['snapshot_id']==source['sha256'],'Editorial source SHA-256 mismatch'
    assert blob==member['git_blob_sha1']==source['git_blob_sha1'],'Editorial Git blob mismatch'
    assert len(raw)==member['byte_length']==source['byte_length'],'Editorial byte length mismatch'
    assert source['encoding']=='UTF-8' and source['source_id']=='INTERNAL_EDITORIAL'
    document=json.loads(raw,object_pairs_hook=duplicate_keys);validate_source(document,schema)
    assert {v['code'] for v in document['occupations']}=={'AI_ENGINEER','BACKEND_DEVELOPER','FRONTEND_DEVELOPER','DATA_ANALYST'}
    for key in ['catalogue_id','catalogue_version']:
        assert document[key]==source[key]==member[key],'Editorial catalogue identity mismatch'
    for key in ['schema_version','actor','actor_kind']:assert source[key]==document[key]
    snapshot_id='snapshot/INTERNAL_EDITORIAL/'+sha
    assert node_id(source_node)==snapshot_id
    assert targets(source_node,JT.fromSource)=={'source/INTERNAL_EDITORIAL'}
    contract_node=unique(JT.EditorialContract);contract=props(contract_node)
    assert contract['schema_version']==document['schema_version']
    assert contract['schema_hash']==native_hash(schema)==manifest['editorial_contract_hash'],'Editorial source contract mismatch'
    assert targets(source_node,JT.usesContract)=={'editorial-contract/'+document['schema_version']}
    assert node_id(contract_node)=='editorial-contract/'+document['schema_version']
    selection_node=unique(JT.EditorialReleaseSelection);selection=props(selection_node)
    assert node_id(selection_node)=='editorial-selection/'+release
    assert selection['release_id']==release and selection['snapshot_id']==sha
    assert selection['manifest_hash']==manifest['editorial_membership_hash']
    assert targets(selection_node,JT.selectsSnapshot)=={snapshot_id}
    review_node=unique(JT.EditorialReview);review=props(review_node);selected_review=member['review']
    assert {k:v for k,v in review.items() if k not in ('name','attestation_kind','repository_verification')}==selected_review,'Editorial frozen review mismatch'
    assert selected_review['snapshot_id']==sha and selected_review['review_id']==selection['review_id']
    assert selected_review['decision']=='ACCEPT' and selected_review['reviewer_kind']=='human'
    assert selected_review['reviewer'].strip()!=document['actor'].strip(),'Editorial author self-review'
    assert re.fullmatch(r'([0-9a-f]{40}|[0-9a-f]{64})',selected_review['git_commit']) and selected_review['merge_evidence'].strip()
    assert review['attestation_kind']=='OPERATOR_REPORTED' and review['repository_verification']=='NOT_AUTOMATICALLY_VERIFIED'
    review_id='editorial-review/'+selected_review['review_id']
    assert node_id(review_node)==review_id and targets(selection_node,JT.reviewedBy)=={review_id}
    assert targets(review_node,JT.forSnapshot)=={snapshot_id}
    scheme_id='urn:jobtology:conceptScheme:product-occupations'
    common=dict(source_id='INTERNAL_EDITORIAL',source_snapshot_id=sha,catalogue_version=document['catalogue_version'])
    expected=[dict(entity_id=scheme_id,kind='conceptScheme',code='product-occupations',scheme_id=None,
        name=document['scheme']['name'],payload=document['scheme']|dict(scheme_code='product-occupations',kind='TAXONOMY')|common,
        source_pointer='/scheme')]
    for index,entry in enumerate(document['occupations']):
        expected.append(dict(entity_id='urn:jobtology:occupation:product:'+entry['code'],kind='occupation',code='product:'+entry['code'],
            scheme_id=scheme_id,name=entry['name'],payload=entry|dict(occupation_code=entry['code'],scheme_id=scheme_id)|common,
            source_pointer='/occupations/'+str(index)))
    for item in expected:
        item['snapshot_id']=sha
        item['payload_hash']=native_hash(item['payload'])
        item['revision_id']=native_hash([item['entity_id'],'hop-editorial-revision-v1',sha,item['payload']])
    assert sorted(expected,key=lambda i:i['entity_id'])==member['items'],'Editorial definitions differ from original source'
    lookup={node_id(n):n for n in graph.subjects(JT.nativeNodeId,None)}
    records={props(n)['entity_id']:n for n in graph.subjects(RDF.type,JT.EditorialSourceRecord)}
    assert len(records)==5 and set(records)=={i['entity_id'] for i in expected},'Editorial record membership mismatch'
    assert targets(selection_node,JT.selectsRevision)=={'revision/'+i['revision_id'] for i in expected}
    for item in expected:
        identity_id='entity/'+item['entity_id'];revision_id='revision/'+item['revision_id']
        identity=lookup[identity_id];revision=lookup[revision_id];record=records[item['entity_id']]
        expected_identity={k:item[k] for k in ['entity_id','kind','code','scheme_id'] if item[k] is not None}
        assert props(identity)==expected_identity,'Editorial stable identity mismatch'
        expected_revision=item['payload']|{k:item[k] for k in ['entity_id','kind','revision_id','payload_hash']}|dict(schema_version='hop-editorial-revision-v1')
        assert props(revision)==expected_revision,'Editorial definition revision mismatch'
        record_id='editorial-record/'+native_hash([sha,item['entity_id'],item['source_pointer'],item['payload_hash']])
        assert node_id(record)==record_id
        record_props=props(record)
        assert record_props==dict(source_id='INTERNAL_EDITORIAL',source_record_id=item['entity_id'],entity_id=item['entity_id'],
            snapshot_id=sha,locator=item['source_pointer'],raw_sha256=sha,normalized_hash=item['payload_hash'],
            revision_id=item['revision_id'],name=item['name']+' — 편집 원문'),'Editorial source pointer mismatch'
        assert targets(identity,JT.hasRevision)=={revision_id}
        assert targets(revision,JT.derivedFrom)=={record_id}
        assert targets(record,JT.inSnapshot)=={snapshot_id}
        assert targets(revision,JT.inScheme)==({'entity/'+scheme_id} if item['scheme_id'] else set())
