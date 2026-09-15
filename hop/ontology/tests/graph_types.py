"""Property boundary regressions in the disposable ontologytest database only."""
import json
from run import sql,js,q,ROOT,expect_error


def check():
    sql((ROOT/'hop/ontology/sql/004_graph_inventory.sql').read_text())
    release=sql('SELECT release_id FROM ontology.corpus_release ORDER BY created_at LIMIT 1')
    assert release
    def insert(value):
        return "BEGIN; INSERT INTO ontology.graph_node VALUES("+q(release)+",'property-boundary-fixture',ARRAY['fixture'],"+js(value)+",'fixture'); "
    good=dict(text='eligibility_text',empty='',zero=0,negative=-1,minimum=-9223372036854775808,
        maximum=9223372036854775807,decimal=1.25,numbers=[0,1.25],strings=['','한글'],empty_array=[],truth=[True,False])
    output=sql(insert(good)+"SELECT ontology.verify_graph_numbers("+q(release)+"); SELECT jsonb_agg(jsonb_build_array(key,ordinal,value_type,text_value) ORDER BY key,ordinal) FROM ontology.graph_property WHERE release_id="+q(release)+" AND owner_id='property-boundary-fixture'; ROLLBACK;")
    rows=json.loads(output.strip())
    assert ['zero',-1,'integer','0'] in rows and ['empty',-1,'string',''] in rows,rows
    assert ['empty_array',-1,'empty_array',None] in rows,rows
    assert ['numbers',0,'number','0'] in rows and ['numbers',1,'number','1.25'] in rows,rows
    for value,code in [
        (dict(number=9223372036854775808),'GRAPH_INTEGER_OUT_OF_RANGE'),
        (dict(number=-9223372036854775809),'GRAPH_INTEGER_OUT_OF_RANGE'),
        (dict(numbers=[9007199254740993,1.25]),'GRAPH_FLOAT_PRECISION_LOSS')]:
        expect_error(insert(value)+'SELECT ontology.verify_graph_numbers('+q(release)+'); ROLLBACK;',code)
    # Send this decimal as exact JSON; Python's float would round it beforehand.
    expect_error(insert({}).replace("'{}'::jsonb", "'{\"number\":1.0000000000000001}'::jsonb")+'SELECT ontology.verify_graph_numbers('+q(release)+'); ROLLBACK;','GRAPH_FLOAT_PRECISION_LOSS')
    # Literal dotted keys and nested maps must retain separate reversible names.
    flat=json.loads(sql("SELECT ontology.flat_properties("+js({'a.b':1,'a':{'b':2},'~':3})+")"))
    assert flat=={'a~2b':1,'a.b':2,'~0':3},flat
    expect_error("SELECT ontology.flat_properties('{\"mixed\":[1,\"1\"]}')",'HOMOGENEOUS_PRIMITIVES')
    expect_error("SELECT ontology.flat_properties('{\"objects\":[{\"x\":1}]}')",'HOMOGENEOUS_PRIMITIVES')
    assert sql("SELECT count(*) FROM ontology.graph_node WHERE node_id='property-boundary-fixture'")=='0'
    print('GRAPH PROPERTY BOUNDARY CHECKS PASSED',flush=True)


if __name__=='__main__':check()
