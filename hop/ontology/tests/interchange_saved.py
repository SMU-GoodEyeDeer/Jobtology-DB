"""Full native export of the retained, saved-source ontology fixture.

Clone ontologyrealtest into a new temporary database; never reset or alter the
original. No downloads, attachment parsing, inference, review or graph writes.
This checks every exported native object at corpus scale using a streaming
decoder. Full-scale RDFLib/SHACL memory/performance is a separate check.
"""
import hashlib
import json
import subprocess
import uuid
from decimal import Decimal
from pathlib import Path
import run
import interchange


def main():
    suffix=uuid.uuid4().hex[:10]
    database='interchange_saved_'+suffix
    hop='jobtology-interchange-saved-'+suffix
    network='jobtology-interchange-saved-net-'+suffix
    source='ontologyrealtest';release='real-reviewed-projection-fixture'
    def sql(text,db=database):
        return run.cmd(['docker','exec','-i',run.PG,'psql','-X','-qAt','-v','ON_ERROR_STOP=1','-U','postgres','-d',db],input=text)
    assert sql("SELECT count(*) FROM pg_stat_activity WHERE datname='ontologyrealtest'",'postgres')=='0','Saved fixture has active users'
    assert sql("SELECT to_regclass('ontology.graph_node') IS NOT NULL",source)=='t'
    created=False
    try:
        sql('CREATE DATABASE '+database+' TEMPLATE '+source,'postgres');created=True
        for name in ['005_queries.sql','006_interchange_contract.sql','007_interchange.sql']:
            sql((run.ROOT/'hop/ontology/sql'/name).read_text())
        manifest=json.loads(sql('SELECT manifest FROM ontology.corpus_release WHERE release_id='+run.q(release)))
        assert manifest['nodes']>100000 and manifest['edges']>500000
        before=sql('SELECT ontology.hash(jsonb_agg(r ORDER BY release_id)) FROM ontology.corpus_release r')
        import native
        native.HOP=hop;native.NET=network
        native.stage(database)
        print('Full export native fixture:',native.WORK,flush=True)
        native.run('export_jsonld.hwf',dict(RELEASE_ID=release,PREVIEW='Y'),'full-native-jsonld')
        output=native.WORK/'exports'
        run.cmd(['docker','cp',hop+':'+native.REMOTE+'/project/data/ontology-exports',str(output)])
        paths=list(output.glob('*.jsonld'));assert len(paths)==1
        assert str(uuid.UUID(paths[0].stem))==paths[0].stem
        nodes=dict(json.loads(sql('SELECT jsonb_agg(jsonb_build_array(node_id,content_hash)) FROM ontology.graph_node WHERE release_id='+run.q(release))))
        edges=dict(json.loads(sql('SELECT jsonb_agg(jsonb_build_array(edge_id,content_hash)) FROM ontology.graph_edge WHERE release_id='+run.q(release))))
        original_counts=(len(nodes),len(edges));last=None;root=None;digest=hashlib.sha256();line_count=0
        mapping=interchange.MAPPING
        def value(v):
            if isinstance(v,dict):
                if '@list' in v:return [value(x) for x in v['@list']]
                if v.get('@type')=='xsd:integer':return int(v['@value'])
                if v.get('@type')=='xsd:decimal':return Decimal(v['@value'])
                if v.get('@type')=='@json':return v['@value']
                raise AssertionError(v)
            return v
        def properties(row):
            keys=row['nativePropertyKey']['@list']
            return {k:value(row[mapping['properties'].get(k,'jtf:'+k.encode().hex())]) for k in keys}
        with paths[0].open('rb') as file:
            for index,raw in enumerate(file):
                digest.update(raw);line_count+=1
                line=raw.decode().rstrip('\n')
                if index==0:
                    header=json.loads(line+']}')
                    assert header['@context']==json.loads((run.ROOT/'ontology/context.jsonld').read_text())['@context']
                    continue
                if line.endswith(']}'):
                    root=json.loads(line[:-2],parse_float=Decimal);assert file.read()==b'';break
                assert line.endswith(',');row=json.loads(line[:-1],parse_float=Decimal)
                if 'nativeNodeId' in row:
                    node=row['nativeNodeId'];labels=row['nativeLabelOrder']['@list'];props=properties(row)
                    assert row['nativeContentHash']==nodes.pop(node)
                    assert row['nativeContentHash']==interchange.validator.native_hash([node,labels,props])
                    assert row['@id']=='urn:jobtology:node:'+hashlib.sha256(node.encode()).hexdigest()
                elif 'nativeEdgeId' in row:
                    assert last is None
                    edge=row['nativeEdgeId'];props=properties(row)
                    values=[row['nativeSubjectId'],row['nativePredicate'],row['nativeObjectId'],props]
                    assert row['nativeContentHash']==edges.pop(edge)
                    assert row['nativeContentHash']==interchange.validator.native_hash(values)
                    assert edge==interchange.validator.native_hash([release,*values]);last=row
                else:
                    assert last is not None
                    assert row['@id']==last['rdf:subject']['@id']
                    assert row[mapping['predicates'][last['nativePredicate']]]==last['rdf:object']
                    assert row['hasRelation']=={'@id':last['@id']}
                    if last['nativePredicate'] in mapping['schema_relation_aliases']:
                        assert row[mapping['schema_relation_aliases'][last['nativePredicate']]]==last['rdf:object']
                    last=None
                if index%200000==0:print('Verified export lines:',index,flush=True)
        assert not nodes and not edges and last is None and root is not None
        assert root['selectedReleaseId']==release and root['nativeGraphManifest']['@value']==manifest
        assert (manifest['nodes'],manifest['edges'])==original_counts
        assert root['nativeGraphManifestHash']==interchange.validator.native_hash(manifest)
        assert root['exportContractHash']==sql("SELECT content_hash FROM ontology.interchange_contract WHERE version='hop-ontology-interchange-v1'")
        assert line_count==2+manifest['nodes']+2*manifest['edges']
        assert before==sql('SELECT ontology.hash(jsonb_agg(r ORDER BY release_id)) FROM ontology.corpus_release r')
        result=dict(release_id=release,nodes=manifest['nodes'],edges=manifest['edges'],bytes=paths[0].stat().st_size,
            sha256=digest.hexdigest(),lines=line_count,native_hop_heap_mb=1024,
            native_export_and_all_object_readback=True,full_scale_shacl=False,
            original_database_untouched=True,model_calls=0)
        (native.WORK/'full-export-verification.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result),flush=True)
        print('SAVED-SOURCE FULL NATIVE INTERCHANGE CHECKS PASSED',native.WORK,flush=True)
    finally:
        subprocess.run(['docker','rm','-fv',hop],capture_output=True)
        subprocess.run(['docker','network','disconnect',network,run.PG],capture_output=True)
        subprocess.run(['docker','network','rm',network],capture_output=True)
        if created:sql('DROP DATABASE '+database,'postgres')


if __name__=='__main__':main()
