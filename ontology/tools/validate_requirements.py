"""Independent v3 condition keys, target bindings and frozen atom readback."""
import hashlib
import json

def verify(graph,release,manifest,mapping,native_properties,native_hash,JT,RDF):
    def props(node):return native_properties(graph,node,mapping)
    def node_id(node):return str(graph.value(node,JT.nativeNodeId))
    def only(node,predicate):
        values=list(graph.objects(node,predicate));assert len(values)==1,('Typed relation cardinality',node,predicate)
        return values[0]
    condition_cache={}
    for kind in [JT.TypedCondition,JT.UnresolvedCondition]:
        for node in graph.subjects(RDF.type,kind):
            p=props(node);fields=p['condition_fields'];nulls=p['null_fields']
            assert fields==sorted(set(fields)) and nulls==sorted(set(nulls)) and set(nulls)<=set(fields),'Condition field set mismatch'
            assert all(k not in p for k in nulls),'Null condition field also has a value'
            c={k:None if k in nulls else p[k] for k in fields}
            assert set(p)==(set(fields)-set(nulls))|{'condition_id','condition_fields','null_fields','name'},'Unexpected condition property'
            assert p['condition_id']==native_hash(['typed-condition-v1',c]),'Typed condition identity mismatch'
            assert node_id(node)=='typed-condition/'+p['condition_id']
            for k in ['accepted_major_groups','capability_ids','administrative_codes']:
                if k in c:assert c[k]==sorted(set(c[k])),'Condition set is not canonical'
            for k in ['minimum_proficiency','minimum_months','maximum_months','minimum_count']:
                if c.get(k) is not None:assert type(c[k]) is int and 0<=c[k]<=2147483647,'Condition integer outside JCS schema'
            if c['kind']=='EXPERIENCE' and c['minimum_months'] is not None and c['maximum_months'] is not None:
                assert c['minimum_months']<=c['maximum_months'],'Experience bound order'
            if c['kind']=='UNRESOLVED':key=None;assert kind==JT.UnresolvedCondition
            else:
                payload={k:v for k,v in c.items() if k!='target_kind'}
                key=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
                assert kind==JT.TypedCondition
            condition_cache[node]=(c,key)
    proposals={}
    for node in graph.subjects(RDF.type,JT.RequirementNormalization):
        p=props(node);c,key=condition_cache[only(node,JT.hasProposedCondition)]
        assert p.get('requirement_key')==key,'Canonical requirement key mismatch'
        assert p['key_algorithm']=='sha256-jcs-requirement-v1','Unknown requirement key algorithm'
        expected=('claim/'+p['source_claim_id']) if p['source_node_index']==-1 else ('condition/'+p['source_claim_id']+'/'+str(p['source_node_index']))
        assert node_id(only(node,JT.forSourceAtom))==expected,'Normalization source atom mismatch'
        bindings=[]
        for target in graph.objects(node,JT.usesTargetBinding):
            b=props(target)
            binding={k:b[k] for k in ['role','entity_id','revision_id','payload_hash']}
            assert b['normalization_id']==p['normalization_id'],'Binding belongs to another normalization'
            assert node_id(target)=='requirement-binding/'+native_hash([p['normalization_id'],binding]),'Binding identity mismatch'
            bindings.append(binding)
        bindings.sort(key=lambda b:(b['role'],b['entity_id']))
        assert native_hash(bindings)==p['target_bindings_hash'],'Target binding set mismatch'
        proposals[node]=(p,c,key)
    atoms=[];selected_claim_ids=set()
    for node in graph.subjects(RDF.type,JT.RequirementReviewSelection):
        p=props(node);assert p['release_id']==release,'Requirement selection from another release'
        assert node_id(node)=='requirement-selection/'+release+'/'+p['source_claim_id']+'/'+str(p['source_node_index'])
        selected=list(graph.objects(node,JT.selectsNormalization))
        if p.get('normalization_id') is None:assert not selected and p['outcome']=='NOT_PROPOSED'
        else:
            assert len(selected)==1 and props(selected[0])['normalization_id']==p['normalization_id']
            assert only(node,JT.forSourceAtom)==only(selected[0],JT.forSourceAtom),'Selection points to another source atom'
        claim_id=native_hash(['typed-requirement-claim-v1',p['normalization_id'],p['decision_id']]) if p['outcome']=='REVIEWED' else None
        assert p.get('typed_claim_id')==claim_id,'Typed claim decision identity mismatch'
        if claim_id:selected_claim_ids.add(claim_id)
        atoms.append([p['source_claim_id'],p['source_node_index'],p.get('normalization_id'),p.get('decision_id'),p['outcome'],claim_id])
    actual_claim_ids=set()
    for node in graph.subjects(RDF.type,JT.RequirementClaim):
        p=props(node);actual_claim_ids.add(p['claim_id'])
        proposal,c,key=proposals[only(node,JT.derivedFrom)];decision=props(only(node,JT.reviewedBy))
        assert node_id(node)=='typed-requirement/'+p['claim_id'] and decision['typed_claim_id']==p['claim_id']
        assert p['normalization_id']==proposal['normalization_id'] and p['decision_id']==decision['decision_id']
        assert decision['outcome']=='REVIEWED' and decision['decision']=='ACCEPT','Non-reviewed proposal became a requirement claim'
        for k in ['reviewer','reviewer_kind','notes','reviewed_at']:assert p[k]==decision[k],'Claim review differs from selected decision'
        assert p['review_status']==('HUMAN_ACCEPTED' if decision['reviewer_kind']=='human' else 'ASSISTANT_REVIEWED'),'Reviewer kind misrepresented'
        assert 'confidence' not in p and p['confidence_state']=='UNASSESSED','Uncalibrated confidence was assigned'
        assert p['requirement_key']==key and p['requirement_kind']==c['kind'],'Typed requirement condition/key mismatch'
        assert p['necessity']==proposal['necessity'] and p['polarity']==proposal['polarity']
        assert node_id(only(node,JT.forSourceGroup))=='claim/'+proposal['source_claim_id']
        assert node_id(only(node,JT.hasSubject))=='revision/'+p['posting_revision_id']
        assert set(graph.subjects(JT.hasRequirement,node))=={only(node,JT.hasSubject)},'Posting requirement link differs from subject'
        expected_scope='POSTING_FILTER' if c['kind'] in ('LOCATION','ELIGIBILITY','AVAILABILITY') else 'CAPABILITY'
        assert p['requirement_scope']==expected_scope,'Posting filter counted as capability'
        targets=list(graph.objects(node,JT.targets));conditions=list(graph.objects(node,JT.normalizedCondition))
        if c['kind'] in ('SKILL','LANGUAGE','CREDENTIAL'):
            assert len(targets)==1 and node_id(targets[0])=='entity/'+c['target_id'] and not conditions
        else:assert not targets and len(conditions)==1 and condition_cache[conditions[0]][0]==c
        expected_atom=only(only(node,JT.derivedFrom),JT.forSourceAtom)
        assert only(node,JT.forSourceAtom)==expected_atom,'Typed claim changed source atom'
        assert set(graph.objects(node,JT.evidencedBy))==set(graph.objects(expected_atom,JT.evidencedBy)),'Typed claim lost or changed atom evidence'
        assert set(graph.objects(node,JT.appliesTo))==set(graph.objects(only(node,JT.forSourceGroup),JT.appliesTo)),'Typed claim changed position scope'
        assert set(graph.objects(node,JT.usesTargetBinding))==set(graph.objects(only(node,JT.derivedFrom),JT.usesTargetBinding)),'Claim target bindings differ from proposal'
        for target in graph.objects(node,JT.usesTargetBinding):
            b=props(target);revision=only(target,JT.selectsRevision);r=props(revision)
            assert node_id(revision)=='revision/'+b['revision_id'] and r['entity_id']==b['entity_id'] and r['payload_hash']==b['payload_hash'],'Typed target revision mismatch'
            if b['role']=='target':
                required='qualification' if c['kind']=='CREDENTIAL' else ('skill' if c['target_kind']=='Skill' else 'ncsCompetency')
                assert r['kind']==required,'Typed target kind mismatch'
                if c['kind']=='LANGUAGE':assert b['target_subkind']=='LANGUAGE','Language target is not a language skill'
    assert actual_claim_ids==selected_claim_ids,'Typed reviewed claim membership mismatch'
    projection=manifest.get('requirement_projection');membership=manifest.get('requirement_membership')
    if projection is None:assert not atoms and not proposals and not actual_claim_ids and membership is None
    else:
        assert projection['contract']=='typed-requirement-graph-v1' and membership is not None
        assert len(atoms)==projection['atoms']==membership['manifest']['atom_count'],'Requirement atom coverage mismatch'
        assert native_hash(sorted(atoms,key=lambda a:(a[0],a[1])))==projection['atom_hash'],'Requirement frozen atom hash mismatch'
        assert len(actual_claim_ids)==projection['reviewed_claims']
