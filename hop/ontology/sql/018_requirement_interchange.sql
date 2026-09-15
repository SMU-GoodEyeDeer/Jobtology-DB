-- Generated v3 serializer; shared native value helpers retain v1 behavior.
BEGIN;
CREATE OR REPLACE FUNCTION ontology.interchange_check_v3(choice text,preview boolean DEFAULT false)
RETURNS text LANGUAGE plpgsql STABLE AS $$
DECLARE id text; r ontology.corpus_release%ROWTYPE; mapping jsonb;
BEGIN
 id:=ontology.read_release_v1(choice,preview);
 SELECT * INTO r FROM ontology.corpus_release WHERE release_id=id;
 IF r.manifest IS NULL OR r.manifest_hash IS NULL THEN RAISE EXCEPTION 'SEAL_ONTOLOGY_GRAPH_FIRST'; END IF;
 IF r.manifest_hash IS DISTINCT FROM ontology.hash(r.manifest) OR r.manifest IS DISTINCT FROM ontology.graph_inventory_manifest(id)
 THEN RAISE EXCEPTION 'SEALED_GRAPH_INVENTORY_CHANGED'; END IF;
 SELECT artifacts->'mappings/hop-v3.json' INTO mapping FROM ontology.interchange_contract WHERE version='hop-ontology-interchange-v3';
 IF mapping IS NULL THEN RAISE EXCEPTION 'INTERCHANGE_CONTRACT_MISSING'; END IF;
 IF EXISTS(SELECT 1 FROM ontology.graph_node n CROSS JOIN LATERAL unnest(n.labels) label
   WHERE n.release_id=id AND NOT (mapping->'node_labels' ? label))
 THEN RAISE EXCEPTION 'INTERCHANGE_UNMAPPED_NODE_LABEL'; END IF;
 IF EXISTS(SELECT 1 FROM ontology.graph_edge e WHERE e.release_id=id AND NOT (mapping->'predicates' ? e.predicate))
 THEN RAISE EXCEPTION 'INTERCHANGE_UNMAPPED_PREDICATE'; END IF;
 IF EXISTS(SELECT 1 FROM ontology.graph_node n WHERE n.release_id=id AND
   n.content_hash IS DISTINCT FROM ontology.hash(jsonb_build_array(n.node_id,n.labels,n.properties))) OR
   EXISTS(SELECT 1 FROM ontology.graph_edge e WHERE e.release_id=id AND
    (e.content_hash IS DISTINCT FROM ontology.hash(jsonb_build_array(e.subject_id,e.predicate,e.object_id,e.properties)) OR
     e.edge_id IS DISTINCT FROM ontology.hash(jsonb_build_array(id,e.subject_id,e.predicate,e.object_id,e.properties))))
 THEN RAISE EXCEPTION 'INTERCHANGE_NATIVE_CONTENT_HASH_MISMATCH'; END IF;
 PERFORM ontology.verify_observation_membership_v1(id);
 PERFORM ontology.verify_requirements_v1(id);
 RETURN id;
END $$;

-- One JSON line per object, not one corpus-sized JSON/JVM field. PostgreSQL's
-- tuplestore can spill to disk; Table Input consumes rows from its ResultSet.
-- Call in one SELECT: all metadata, objects and relations share its MVCC snapshot.
CREATE OR REPLACE FUNCTION ontology.export_jsonld_v3(choice text DEFAULT NULL,preview boolean DEFAULT false)
RETURNS TABLE(line_no bigint,line text) LANGUAGE plpgsql STABLE AS $$
DECLARE id text; r ontology.corpus_release%ROWTYPE; contract ontology.interchange_contract%ROWTYPE;
 mapping jsonb; item record; result jsonb; types jsonb; native_kind text; alias record; value text; seq bigint:=0;
BEGIN
 id:=ontology.interchange_check_v3(choice,preview);
 SELECT * INTO r FROM ontology.corpus_release WHERE release_id=id;
 SELECT * INTO contract FROM ontology.interchange_contract WHERE version='hop-ontology-interchange-v3';
 mapping:=contract.artifacts->'mappings/hop-v3.json';
 line_no:=seq; line:='{"@context":'||(contract.artifacts->'context.jsonld'->'@context')::text||
  ',"@id":'||to_json('urn:jobtology:release:'||encode(sha256(convert_to(id,'UTF8')),'hex'))::text||',"@graph":[';
 RETURN NEXT;
 FOR item IN SELECT * FROM ontology.graph_node n WHERE n.release_id=id ORDER BY n.node_id COLLATE "C" LOOP
  SELECT jsonb_agg('jt:'||(mapping->'node_labels'->>label) ORDER BY ord) INTO types
   FROM unnest(item.labels) WITH ORDINALITY x(label,ord);
  native_kind:=CASE WHEN item.properties->>'kind' IN (SELECT jsonb_object_keys(mapping->'schema_types'))
    THEN item.properties->>'kind' ELSE NULL END;
  IF native_kind IS NOT NULL THEN types:=types||jsonb_build_array(mapping->'schema_types'->>native_kind); END IF;
  result:=jsonb_build_object('@id',ontology.interchange_node_iri_v1(item.node_id),'@type',types,
   'nativeNodeId',item.node_id,'nativeLabel',to_jsonb(item.labels),
   'nativeLabelOrder',jsonb_build_object('@list',to_jsonb(item.labels)),'nativeContentHash',item.content_hash)
   ||ontology.interchange_properties_v1(item.properties,mapping);
  FOR alias IN SELECT * FROM jsonb_each_text(mapping->'schema_literal_aliases') LOOP
   value:=item.properties->>alias.key;
   IF value IS NULL OR jsonb_typeof(item.properties->alias.key)<>'string' OR value='' THEN CONTINUE; END IF;
   IF alias.key='source_url' THEN
    IF value ~ '^https?://[^[:space:]]+$' THEN result:=result||jsonb_build_object(alias.value,jsonb_build_object('@id',value)); END IF;
   ELSIF alias.key IN ('date_posted','closing_date') THEN
    IF value ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN
     PERFORM value::date;
     result:=result||jsonb_build_object(alias.value,jsonb_build_object('@value',value,'@type','xsd:date'));
    ELSIF value ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T.*(Z|[+-][0-9]{2}:[0-9]{2})$' THEN
     PERFORM value::timestamptz;
     result:=result||jsonb_build_object(alias.value,jsonb_build_object('@value',value,'@type','xsd:dateTime'));
    END IF;
   ELSE result:=result||jsonb_build_object(alias.value,value);
   END IF;
  END LOOP;
  FOR alias IN SELECT * FROM jsonb_each_text(mapping->'datetime_aliases') LOOP
   value:=item.properties->>alias.key;
   IF value IS NOT NULL THEN
    PERFORM value::timestamptz;
    result:=result||jsonb_build_object(alias.value,jsonb_build_object('@value',value,'@type','xsd:dateTime'));
   END IF;
  END LOOP;
  FOR alias IN SELECT * FROM jsonb_each_text(mapping->'date_aliases') LOOP
   value:=item.properties->>alias.key;
   IF value IS NOT NULL THEN
    PERFORM value::date;
    result:=result||jsonb_build_object(alias.value,jsonb_build_object('@value',value,'@type','xsd:date'));
   END IF;
  END LOOP;
  seq:=seq+1;line_no:=seq;line:=result::text||',';RETURN NEXT;
 END LOOP;
 FOR item IN SELECT * FROM ontology.graph_edge e WHERE e.release_id=id ORDER BY e.edge_id COLLATE "C" LOOP
  result:=jsonb_build_object('@id','urn:jobtology:edge:'||item.edge_id,'@type',jsonb_build_array('jt:Relation','rdf:Statement'),
   'nativeEdgeId',item.edge_id,'nativePredicate',item.predicate,'nativeSubjectId',item.subject_id,'nativeObjectId',item.object_id,
   'nativeContentHash',item.content_hash,
   'rdf:subject',jsonb_build_object('@id',ontology.interchange_node_iri_v1(item.subject_id)),
   'rdf:predicate',jsonb_build_object('@id','jt:'||(mapping->'predicates'->>item.predicate)),
   'rdf:object',jsonb_build_object('@id',ontology.interchange_node_iri_v1(item.object_id)))
   ||ontology.interchange_properties_v1(item.properties,mapping);
  seq:=seq+1;line_no:=seq;line:=result::text||',';RETURN NEXT;
  result:=jsonb_build_object('@id',ontology.interchange_node_iri_v1(item.subject_id),
   mapping->'predicates'->>item.predicate,jsonb_build_object('@id',ontology.interchange_node_iri_v1(item.object_id)),
   'hasRelation',jsonb_build_object('@id','urn:jobtology:edge:'||item.edge_id));
  IF mapping->'schema_relation_aliases' ? item.predicate THEN
   result:=result||jsonb_build_object(mapping->'schema_relation_aliases'->>item.predicate,
    jsonb_build_object('@id',ontology.interchange_node_iri_v1(item.object_id)));
  END IF;
  seq:=seq+1;line_no:=seq;line:=result::text||',';RETURN NEXT;
 END LOOP;
 -- The virtual release root is not an inventory node. Its hash is the sealed
 -- native manifest hash, exactly as on the existing Neo4j corpusRelease root.
 result:=jsonb_build_object('@id',ontology.interchange_node_iri_v1('release/'||id),'@type','jt:CorpusRelease',
  'nativeNodeId','release/'||id,'nativeLabel',jsonb_build_array('corpusRelease'),'nativeContentHash',r.manifest_hash,
  'selectedReleaseId',id,'nativeGraphManifestHash',r.manifest_hash,
  'nativeGraphManifest',jsonb_build_object('@value',r.manifest,'@type','@json'),
  'exportContractVersion',contract.version,'exportContractHash',contract.content_hash,
  'exportReadMode',CASE WHEN preview THEN 'PREVIEW' ELSE 'PUBLISHED' END,'releaseState',r.state,
  'dataAsOf',jsonb_build_object('@value',r.manifest->>'data_as_of','@type','xsd:dateTime'),
  'pipelineVersion',r.pipeline_version,'methodologyVersion',r.methodology_version);
 seq:=seq+1;line_no:=seq;line:=result::text||']}';RETURN NEXT;
END $$;
COMMIT;
