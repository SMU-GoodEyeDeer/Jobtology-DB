#!/usr/bin/env python3
"""Run exact operator deletion Cypher in a unique, disposable Neo4j fixture.

Docker never pulls, publishes ports, mounts volumes or reaches production.
Optional --ssh executes the isolated fixture on a host with the image cached.
"""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import inspect
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "operations"))
import cutover_jobkorea_graph as cutover

FIXTURE = r"""
import csv
import io
import json
import subprocess
import time
import uuid

name='jobtology-jk-cutover-test-'+uuid.uuid4().hex[:12]
def command(args, data=None, check=True):
    return subprocess.run(args,input=data,text=True,capture_output=True,check=check,timeout=60)
def query(cypher, check=True):
    return command(['docker','exec','-i','-e','JAVA_OPTS=-Xms32m -Xmx128m -XX:ActiveProcessorCount=1',name,'cypher-shell','-a','bolt://localhost:7687',
                    '--format','plain'],cypher+';\n',check)
def rows(cypher):
    return list(csv.DictReader(io.StringIO(query(cypher).stdout),skipinitialspace=True))
try:
    command(['docker','run','--detach','--pull=never','--name',name,'--network','none',
             '--hostname','localhost','--cpus','1','--memory','2g','--env','NEO4J_AUTH=none',
             '--env','NEO4J_server_default__listen__address=127.0.0.1',
             '--env','NEO4J_server_default__advertised__address=localhost',
             '--env','NEO4J_server_jvm_additional=-XX:ActiveProcessorCount=1',
             '--env','NEO4J_server_memory_heap_initial__size=256m',
             '--env','NEO4J_server_memory_heap_max__size=512m',
             '--env','NEO4J_server_memory_pagecache_size=128m','neo4j:2026.06.0'])
    for attempt in range(90):
        if command(['docker','inspect',name,'--format','{{.State.Running}}']).stdout.strip()!='true':
            raise RuntimeError(command(['docker','logs',name]).stdout)
        if query('RETURN 1 AS ready',False).returncode==0:
            break
        time.sleep(1)
    else:
        raise RuntimeError('Disposable Neo4j did not become ready')
    query("CREATE (old:entity:jobPosting {id:'"+PREFIX+"old',kind:'JobPosting'}), "
          "(kept:entity:jobPosting {id:'"+PREFIX+"kept',kind:'JobPosting'}), "
          "(nara:entity:jobPosting {id:'source:posting:nara_job:other',kind:'JobPosting'}), "
          "(ncs:entity:occupation {id:'ncs:occupation:shared',name:'보존'}), "
          "(onet:entity:occupation:onetCatalogObject {id:'onet:occupation:shared',name:'Preserved'}), "
          "(old)-[:INFERRED_NCS_OCCUPATION {candidate_id:'old'}]->(ncs), "
          "(kept)-[:INFERRED_NCS_OCCUPATION {candidate_id:'old-kept'}]->(ncs), "
          "(old)-[:INFERRED_ONET_OCCUPATION {id:'old-onet'}]->(onet), "
          "(nara)-[:INFERRED_ONET_OCCUPATION {id:'nara-onet'}]->(onet)")
    ids=rows("MATCH(n:jobPosting) RETURN n.id AS id,elementId(n) AS eid")
    old=next(row['eid'] for row in ids if row['id']==PREFIX+'old')
    edges=rows("MATCH(a)-[r]->() WHERE a.id STARTS WITH '"+PREFIX+"' RETURN elementId(r) AS eid")
    assert rows(delete_query('REL',[row['eid'] for row in edges]))==[{'signature':'3'}]
    assert rows(delete_query('NODE',[old]))==[{'signature':'1'}]
    assert rows("MATCH(n) RETURN count(n) AS total")==[{'total':'4'}]
    assert rows("MATCH()-[r]->() RETURN count(r) AS total")==[{'total':'1'}]
    assert rows("MATCH(n:occupation) RETURN n.id AS id,n.name AS name ORDER BY id")==[
        {'id':'ncs:occupation:shared','name':'보존'},
        {'id':'onet:occupation:shared','name':'Preserved'}]
    query("CREATE (old:entity:jobPosting {id:'"+PREFIX+"attached',kind:'JobPosting'}), "
          "(user:User {id:'test-user'}),(user)-[:USER_SAVED]->(old)")
    attached=rows("MATCH(n {id:'"+PREFIX+"attached'}) RETURN elementId(n) AS eid")[0]['eid']
    assert query(delete_query('NODE',[attached]),False).returncode!=0
    assert rows("MATCH(:User)-[r:USER_SAVED]->() RETURN count(r) AS total")==[{'total':'1'}]
    print(json.dumps({'status':'VERIFIED','fixture':name,'removed_old_nodes':1,
                      'removed_old_ncs_onet_edges':3,'preserved_catalogue_nodes':2,
                      'preserved_other_source_edges':1,'unknown_attachment_delete':'REJECTED',
                      'source_requests':0,'paid_calls':0}))
finally:
    command(['docker','rm','--force','--volumes',name],check=False)
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh")
    args = parser.parse_args()
    program = (
        "import json\nPREFIX="
        + repr(cutover.PREFIX)
        + "\nASSOCIATIONS="
        + repr(cutover.ASSOCIATIONS)
        + "\nBATCH_SIZE="
        + repr(cutover.BATCH_SIZE)
        + "\n"
        + inspect.getsource(cutover.delete_query)
        + "\n"
        + FIXTURE
    )
    command = (
        ["ssh", "-o", "BatchMode=yes", args.ssh, "python3", "-"]
        if args.ssh
        else [sys.executable, "-"]
    )
    subprocess.run(command, input=program, text=True, check=True, timeout=240)


if __name__ == "__main__":
    main()
