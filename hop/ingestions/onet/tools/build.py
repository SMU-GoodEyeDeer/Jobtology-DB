"""Generate the local-only, separately owned O*NET native Hop adapter."""
# SQL/Cypher literals are mirrored in generated native artifacts.
# ruff: noqa: E501

import json
import xml.etree.ElementTree as E
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / "hop/ingestions/onet"
OWNER = "jobtology-onet-catalog-v1"
NAMESPACE = "urn:jobtology:onet:"
BATCH_SIZE = 500


def put(node, key, value):
    child = node.find(key)
    if child is None:
        child = E.SubElement(node, key)
    child.text = str(value)


def child(node, tag, values):
    result = E.SubElement(node, tag)
    for key, value in values.items():
        put(result, key, value)
    return result


def save(node, name):
    E.indent(node, space="  ")
    E.ElementTree(node).write(OUT / name, encoding="UTF-8", xml_declaration=True)


def transform(kind, name, **values):
    return child(E.Element("root"), "transform", {"type": kind, "name": name, **values})


class Pipeline:
    def __init__(self, name, description):
        self.name = name
        self.root = E.Element("pipeline")
        info = child(self.root, "info", {"name": name, "description": description,
                                        "pipeline_type": "Normal", "size_rowset": 1000})
        E.SubElement(info, "parameters")
        E.SubElement(self.root, "notepads")
        self.order = E.SubElement(self.root, "order")
        self.last = None
        self.names = []

    def add(self, node, chain=True):
        name = node.findtext("name")
        if self.last and chain:
            self.hop(self.last, name)
        child(node, "GUI", {"xloc": 80 + len(self.names) * 230, "yloc": 100})
        child(node, "partitioning", {"method": "none", "schema_name": ""})
        put(node, "copies", 1)
        put(node, "distribute", "Y")
        self.root.append(node)
        self.names.append(name)
        if chain:
            self.last = name
        return node

    def hop(self, start, end):
        child(self.order, "hop", {"from": start, "to": end, "enabled": "Y"})

    def save(self):
        E.SubElement(self.root, "transform_error_handling")
        E.SubElement(self.root, "attributes")
        save(self.root, self.name + ".hpl")


def variables(fields):
    node = transform("GetVariable", "Exact catalogue options")
    target = E.SubElement(node, "fields")
    for field, variable in fields:
        child(target, "field", {"name": field, "variable": "${" + variable + "}",
                                "type": "String", "length": -1, "precision": -1,
                                "trim_type": "none"})
    return node


def database(name, sql, fields):
    node = transform("DBJoin", name, connection="jobtology-postgres", sql=sql,
                     cache="N", cache_size=0, rowlimit=0, outer_join="N", replace_vars="N")
    parameters = E.SubElement(node, "parameter")
    for field, kind in fields:
        child(parameters, "field", {"name": field, "type": kind})
    return node


def execute(name, sql, fields):
    node = transform("ExecSql", name, connection="jobtology-postgres", sql=sql,
                     execute_each_row="Y", single_statement="Y", set_params="Y",
                     replace_variables="N", quoteString="N")
    arguments = E.SubElement(node, "arguments")
    for field in fields:
        child(arguments, "argument", {"name": field})
    return node


def cypher(name, query, fields=(), readonly=False, batched=False, returns=(("verified", "Boolean"),)):
    node = transform("Neo4jCypherOutput", name, connection="${NEO4J_CONNECTION}",
                     cypher=query, batch_size=BATCH_SIZE if batched else 1,
                     read_only="Y" if readonly else "N", retry="N", nr_retries_on_error=0,
                     cypher_from_field="N", unwind="Y" if batched else "N", returning_graph="N")
    if batched:
        put(node, "unwind_map", "rows")
    target = E.SubElement(node, "mappings")
    for field, kind in fields:
        child(target, "mapping", {"parameter": field, "field": field, "type": kind})
    target = E.SubElement(node, "returns")
    for field, kind in returns:
        child(target, "return", {"name": field, "type": kind, "source_type": kind})
    return node


def remember(field, variable):
    node = transform("SetVariable", "Remember exact catalogue token", use_formatting="Y")
    child(E.SubElement(node, "fields"), "field", {"field_name": field, "variable_name": variable,
                                                 "variable_type": "PARENT_WORKFLOW", "default_value": ""})
    return node


def require_result(p, field="verified", name="Require exact graph result"):
    done, failed = name + " accepted", name + " rejected"
    node = transform("FilterRows", name, send_true_to=done, send_false_to=failed)
    condition = child(E.SubElement(node, "compare"), "condition",
                      {"negated": "N", "operator": "-", "leftvalue": field, "function": "="})
    child(condition, "value", {"name": "constant", "type": "Boolean", "text": "Y",
                               "length": -1, "precision": -1, "isnull": "N"})
    p.add(node)
    p.add(transform("Dummy", done))
    p.add(transform("Abort", failed, message="O*NET catalogue graph differs from its exact owned PostgreSQL inventory.",
                    always_log_rows="N", abort_option="ABORT_WITH_ERROR", row_threshold=0), chain=False)
    p.hop(name, failed)


# Hop's Cypher transform maps primitive fields, not JSON maps. Render complete
# scalar property maps into an escaped tuple stream and decode without APOC.
# Escape percent first, decode it last so literal %7C and %25 round-trip.
def property_sql(column):
    value = "value#>>'{}'"

    def encode(text):
        return f"replace(replace(coalesce({text},''),'%','%25'),'|','%7C')"
    dtype = ("CASE jsonb_typeof(value) WHEN 'string' THEN 'string' WHEN 'boolean' THEN 'boolean' "
             "WHEN 'number' THEN CASE WHEN value::text ~ '^-?[0-9]+$' THEN 'integer' ELSE 'number' END "
             "ELSE 'invalid' END")
    return f"(SELECT string_agg({encode('key')}||'|'||({dtype})||'|'||{encode(value)},'|' ORDER BY key COLLATE \"C\") FROM jsonb_each({column}))"


def rendered_rows(entity, retired=False):
    function = "graph_load_" + ("retired_" if retired else "") + entity
    labels = ("array_to_string(labels,'|') AS expected_labels,array_to_string(previous_labels,'|') AS baseline_labels"
              if entity == "nodes" else "''::text AS expected_labels,''::text AS baseline_labels")
    return f"""SELECT context.database_id,expected.*,{labels},
{property_sql('properties')} AS property_data,
{property_sql('previous_properties')} AS baseline_data,
(SELECT count(*) FROM jsonb_object_keys(properties))::bigint AS property_count,
(SELECT count(*) FROM jsonb_object_keys(previous_properties))::bigint AS baseline_count
FROM classification.graph_load_context(?) context
CROSS JOIN LATERAL classification.{function}(context.load_id) expected
ORDER BY {"node_id" if entity == "nodes" else "edge_id"} COLLATE "C"
"""


PREFIX = """CALL db.info() YIELD id AS actual_database_id
UNWIND $rows AS row
WITH row,actual_database_id WHERE actual_database_id=row.database_id
"""
# The namespace gate has already rejected every foreign reserved-ID object.
# Keep global relationship-ID collision semantics while scanning the graph only
# once per native batch, before UNWIND expands the planned rows. Do not narrow
# by expected endpoints or type: that would hide colliding IDs elsewhere.
EDGE_PREFLIGHT_PREFIX = f"""CALL db.info() YIELD id AS actual_database_id
CALL () {{
 OPTIONAL MATCH (a)-[object]->(b)
 WHERE object.id STARTS WITH '{NAMESPACE}' OR object.managed_by='{OWNER}'
 RETURN collect({{object:object,start_id:a.id,end_id:b.id,edge_type:type(object)}}) AS candidates
}}
UNWIND $rows AS row
WITH row,candidates,actual_database_id WHERE actual_database_id=row.database_id
"""
DECODE = """WITH row,split(coalesce(row.property_data,''),'|') AS fields,split(coalesce(row.baseline_data,''),'|') AS old_fields
WHERE row.property_count>0 AND size(fields)=row.property_count*3
AND (row.baseline_count=0 OR size(old_fields)=row.baseline_count*3)
WITH row,[i IN range(0,size(fields)-1,3) | {
 key:replace(replace(fields[i],'%7C','|'),'%25','%'),type:fields[i+1],
 text:replace(replace(fields[i+2],'%7C','|'),'%25','%')}] AS expected_properties,
CASE WHEN row.baseline_count=0 THEN [] ELSE [i IN range(0,size(old_fields)-1,3) | {
 key:replace(replace(old_fields[i],'%7C','|'),'%25','%'),type:old_fields[i+1],
 text:replace(replace(old_fields[i+2],'%7C','|'),'%25','%')}] END AS previous_properties
WITH row,[p IN expected_properties | {key:p.key,valid:p.type IN ['string','integer','number','boolean'],
 value:CASE p.type WHEN 'string' THEN p.text WHEN 'integer' THEN toInteger(p.text)
 WHEN 'number' THEN toFloat(p.text) WHEN 'boolean' THEN toBoolean(p.text) END}] AS expected_properties,
[p IN previous_properties | {key:p.key,valid:p.type IN ['string','integer','number','boolean'],
 value:CASE p.type WHEN 'string' THEN p.text WHEN 'integer' THEN toInteger(p.text)
 WHEN 'number' THEN toFloat(p.text) WHEN 'boolean' THEN toBoolean(p.text) END}] AS previous_properties
WHERE all(p IN expected_properties WHERE p.valid AND p.value IS NOT NULL)
AND all(p IN previous_properties WHERE p.valid AND p.value IS NOT NULL)
"""
TYPED_EQUAL = "all(p IN expected_properties WHERE object[p.key]=p.value AND valueType(object[p.key])=valueType(p.value))"
OLD_TYPED_EQUAL = "all(p IN previous_properties WHERE object[p.key]=p.value AND valueType(object[p.key])=valueType(p.value))"
EXPECTED = "object.content_hash=row.content_hash AND size(keys(object))=row.property_count AND " + TYPED_EQUAL
BASELINE = "row.baseline_count>0 AND object.content_hash=row.previous_content_hash AND size(keys(object))=row.baseline_count AND " + OLD_TYPED_EQUAL
NODE_LABELS = "size(labels(object))=size(split(row.expected_labels,'|')) AND all(label IN split(row.expected_labels,'|') WHERE label IN labels(object))"
OLD_NODE_LABELS = "size(labels(object))=size(split(row.baseline_labels,'|')) AND all(label IN split(row.baseline_labels,'|') WHERE label IN labels(object))"
NODE_FIELDS = [(name, "String") for name in ("database_id", "node_id", "expected_labels", "baseline_labels", "property_data", "baseline_data", "content_hash", "previous_content_hash")] + [("property_count", "Integer"), ("baseline_count", "Integer")]
EDGE_FIELDS = [(name, "String") for name in ("database_id", "edge_id", "start_id", "end_id", "edge_type", "expected_labels", "baseline_labels", "property_data", "baseline_data", "content_hash", "previous_content_hash")] + [("property_count", "Integer"), ("baseline_count", "Integer")]

LOCAL_JAVA = r"""
void require(boolean condition, String code) throws Exception {
  if (!condition) throw new Exception(code);
}

void localPath(java.nio.file.Path path) throws Exception {
  java.nio.file.Path absolute = path.toAbsolutePath().normalize();
  java.nio.file.Path current = absolute.getRoot();
  for (java.nio.file.Path part : absolute) {
    current = current.resolve(part);
    require(!java.nio.file.Files.isSymbolicLink(current), "LOCAL_SYMLINK_FORBIDDEN");
  }
  require(java.nio.file.Files.isRegularFile(absolute,java.nio.file.LinkOption.NOFOLLOW_LINKS), "LOCAL_FILE_REQUIRED");
}

byte[] boundedRead(java.nio.file.Path path, long bound) throws Exception {
  localPath(path);
  require(java.nio.file.Files.size(path)>0 && java.nio.file.Files.size(path)<=bound, "LOCAL_FILE_BOUND");
  java.io.InputStream input = java.nio.file.Files.newInputStream(path,java.nio.file.LinkOption.NOFOLLOW_LINKS);
  try {
    java.io.ByteArrayOutputStream output = new java.io.ByteArrayOutputStream();
    byte[] buffer = new byte[8192]; int count;
    while ((count=input.read(buffer))!=-1) {
      require((long)output.size()+count<=bound,"LOCAL_FILE_BOUND");
      output.write(buffer,0,count);
    }
    return output.toByteArray();
  } finally { input.close(); }
}

String digest(byte[] bytes) throws Exception {
  byte[] hash=java.security.MessageDigest.getInstance("SHA-256").digest(bytes);
  StringBuilder value=new StringBuilder();
  for (int i=0;i<hash.length;i++) {
    int part=hash[i]&255; if (part<16) value.append('0'); value.append(Integer.toHexString(part));
  }
  return value.toString();
}

com.fasterxml.jackson.databind.JsonNode json(byte[] bytes) throws Exception {
  String body=java.nio.charset.StandardCharsets.UTF_8.newDecoder()
    .onMalformedInput(java.nio.charset.CodingErrorAction.REPORT)
    .onUnmappableCharacter(java.nio.charset.CodingErrorAction.REPORT)
    .decode(java.nio.ByteBuffer.wrap(bytes)).toString();
  com.fasterxml.jackson.core.JsonFactory factory=new com.fasterxml.jackson.core.JsonFactory();
  factory.enable(com.fasterxml.jackson.core.JsonParser.Feature.STRICT_DUPLICATE_DETECTION);
  com.fasterxml.jackson.databind.ObjectMapper mapper=new com.fasterxml.jackson.databind.ObjectMapper(factory);
  mapper.enable(com.fasterxml.jackson.databind.DeserializationFeature.FAIL_ON_TRAILING_TOKENS);
  return mapper.readTree(body);
}

public boolean processRow() throws HopException {
  Object[] row=getRow();
  if (row==null) { setOutputDone(); return false; }
  String stage="LOCAL_INPUT_FAILED";
  org.apache.hop.core.database.Database db=null;
  try {
    String input=get(Fields.In,"input_file").getString(row);
    String root=get(Fields.In,"evidence_root").getString(row);
    String expected=get(Fields.In,"expected_sha256").getString(row);
    String release=get(Fields.In,"release_id").getString(row);
    require(input!=null && input.startsWith("/") && root!=null && root.startsWith("/"),"ABSOLUTE_LOCAL_PATH_REQUIRED");
    require(expected!=null && expected.matches("[0-9a-f]{64}"),"EXPECTED_INPUT_HASH_REQUIRED");
    long bound=Long.parseLong(getVariable("MAX_FILE_BYTES","16777216"));
    require(bound>0 && bound<=67108864,"INPUT_BOUND_INVALID");
    java.nio.file.Path evidence=java.nio.file.Paths.get(root).toAbsolutePath().normalize();
    java.nio.file.Path path=java.nio.file.Paths.get(input).toAbsolutePath().normalize();
    require(path.startsWith(evidence),"INPUT_OUTSIDE_EVIDENCE_ROOT");
    byte[] bytes=boundedRead(path,bound);
    require(expected.equals(digest(bytes)),"INPUT_HASH_MISMATCH");
    com.fasterxml.jackson.databind.JsonNode payload=json(bytes);
    require(payload.isObject() && release!=null && release.equals(payload.path("release_id").asText()),"RELEASE_PIN_MISMATCH");
    require(payload.path("sources").isArray() && payload.path("sources").size()==3,"SOURCE_INVENTORY_REQUIRED");
    stage="LOCAL_EVIDENCE_FAILED";
    java.util.HashSet paths=new java.util.HashSet();
    for (com.fasterxml.jackson.databind.JsonNode source : payload.path("sources")) {
      String relative=source.path("archive_path").asText();
      require(relative.matches("sources/[A-Za-z0-9_.-]+") && paths.add(relative),"SOURCE_PATH_INVALID");
      java.nio.file.Path archived=evidence.resolve(relative).normalize();
      require(archived.startsWith(evidence),"SOURCE_ARCHIVE_ESCAPE");
      byte[] sourceBytes=boundedRead(archived,16777216);
      require(source.path("byte_length").isIntegralNumber() && source.path("byte_length").asLong()==sourceBytes.length
        && source.path("sha256").asText().equals(digest(sourceBytes)),"SOURCE_ARCHIVE_HASH_MISMATCH");
      String fileId=source.path("file_id").asText();
      require(fileId.matches("[a-z_]+"),"SOURCE_ID_INVALID");
      com.fasterxml.jackson.databind.JsonNode receipt=json(boundedRead(evidence.resolve("sources/"+fileId+".receipt.json"),1048576));
      require(receipt.path("url").asText().equals(source.path("source_uri").asText())
        && receipt.path("sha256").asText().equals(source.path("sha256").asText())
        && receipt.path("byte_count").asLong()==sourceBytes.length
        && receipt.path("retrieved_at").asText().equals(source.path("downloaded_at").asText()),"DOWNLOAD_RECEIPT_MISMATCH");
    }
    require(expected.equals(digest(boundedRead(path,bound))),"INPUT_CHANGED_BEFORE_IMPORT");
    stage="DATABASE_IMPORT_FAILED";
    org.apache.hop.core.database.DatabaseMeta connection=(org.apache.hop.core.database.DatabaseMeta)
      getPipelineMeta().getMetadataProvider().getSerializer(org.apache.hop.core.database.DatabaseMeta.class).load("jobtology-postgres");
    db=new org.apache.hop.core.database.Database(getParent(),getParent(),connection);
    db.connect();
    java.sql.PreparedStatement statement=db.getConnection().prepareStatement("SELECT classification.import_onet_catalog(?::jsonb)");
    String imported;
    try {
      statement.setString(1,new String(bytes,java.nio.charset.StandardCharsets.UTF_8));
      java.sql.ResultSet result=statement.executeQuery();
      try { require(result.next(),"IMPORT_RESULT_REQUIRED"); imported=result.getString(1); require(release.equals(imported),"IMPORT_RESULT_MISMATCH"); }
      finally { result.close(); }
    } finally { statement.close(); }
    Object[] output=createOutputRow(row,data.outputRowMeta.size());
    get(Fields.Out,"catalog_release_id").setValue(output,imported);
    get(Fields.Out,"catalogue_sha256").setValue(output,expected);
    get(Fields.Out,"term_count").setValue(output,Long.valueOf(payload.path("terms").size()));
    putRow(data.outputRowMeta,output); return true;
  } catch (Exception failure) {
    throw new HopException("O*NET local catalogue import failed: "+stage+" ("+failure.getClass().getSimpleName()+")");
  } finally { if (db!=null) db.close(); }
}
"""


def build_import():
    p = Pipeline("import_local", "Verify bounded frozen local source bytes before the atomic O*NET catalogue import.")
    p.add(variables([("input_file", "INPUT_FILE"), ("evidence_root", "EVIDENCE_ROOT"),
                     ("expected_sha256", "EXPECTED_INPUT_SHA256"), ("release_id", "RELEASE_ID")]))
    node = transform("UserDefinedJavaClass", "Verify local evidence and import catalogue", clear_result_fields="N", java_target_version=17)
    child(E.SubElement(node, "definitions"), "definition", {"class_type": "TRANSFORM_CLASS", "class_name": "OnetLocalCatalogueImport", "class_source": LOCAL_JAVA})
    target = E.SubElement(node, "fields")
    for field, kind in (("catalog_release_id", "String"), ("catalogue_sha256", "String"), ("term_count", "Integer")):
        child(target, "field", {"field_name": field, "field_type": kind, "field_length": -1, "field_precision": -1})
    p.add(node)
    p.save()


def token():
    return variables([("load_id", "ONET_LOAD_ID")])


def row_pipeline(name, description, entity, query, readonly, prefix=PREFIX, decode=DECODE):
    p = Pipeline(name, description)
    p.add(token())
    if not readonly or name.startswith("graph_preflight"):
        p.add(database("Require own running writer", "SELECT classification.assert_running_graph_load(?) AS checked_token", [("load_id", "String")]))
    p.add(database("Read immutable planned inventory", rendered_rows(entity), [("load_id", "String")]))
    p.add(cypher("Check exact catalogue rows" if readonly else "Write owned catalogue rows", prefix + decode + query,
                 NODE_FIELDS if entity == "nodes" else EDGE_FIELDS, readonly, True))
    require_result(p)
    p.save()


def scope_pipeline(name, readonly=True):
    p = Pipeline(name, "Check the entire deliberately owned O*NET namespace before graph mutation." if name == "graph_preflight_scope" else "Verify complete current and retired O*NET graph scope.")
    p.add(token())
    if name in ("graph_preflight_scope", "graph_finish"):
        p.add(database("Require own running writer", "SELECT classification.assert_running_graph_load(?) AS checked_token", [("load_id", "String")]))
    p.add(database("Read complete planned scope", """SELECT context.*,
(SELECT string_agg(node_id,'|' ORDER BY node_id COLLATE "C") FROM classification.graph_load_nodes(context.load_id)) AS node_ids,
(SELECT string_agg(edge_id,'|' ORDER BY edge_id COLLATE "C") FROM classification.graph_load_edges(context.load_id)) AS edge_ids
FROM classification.graph_load_context(?) context""", [("load_id", "String")]))
    guard = f"""CALL db.info() YIELD id AS actual_database_id
OPTIONAL MATCH (n) WHERE n.id STARTS WITH '{NAMESPACE}' OR n.managed_by='{OWNER}'
WITH actual_database_id,collect(n) AS nodes
OPTIONAL MATCH ()-[r]->() WHERE r.id STARTS WITH '{NAMESPACE}' OR r.managed_by='{OWNER}'
WITH actual_database_id,nodes,collect(r) AS edges
RETURN actual_database_id=$database_id AND all(n IN nodes WHERE coalesce(n.id IN split($node_ids,'|') AND n.managed_by='{OWNER}' AND n.scheme_id='ONET'
AND 'entity' IN labels(n) AND 'onetCatalogObject' IN labels(n),false))
AND all(r IN edges WHERE coalesce(r.id IN split($edge_ids,'|') AND r.managed_by='{OWNER}' AND r.scheme_id='ONET'
AND type(r) IN ['IN_SCHEME','BROADER'] AND startNode(r).managed_by='{OWNER}' AND endNode(r).managed_by='{OWNER}',false))"""
    if name != "graph_preflight_scope":
        guard += "\nAND size(nodes)=$expected_nodes AND size(edges)=$expected_edges\nAND size([n IN nodes WHERE n.current=true])=$current_nodes AND size([r IN edges WHERE r.current=true])=$current_edges"
    guard += " AS verified"
    fields = [(field, "String") for field in ("database_id", "node_ids", "edge_ids")]
    if name != "graph_preflight_scope":
        fields += [(field, "Integer") for field in ("expected_nodes", "expected_edges", "current_nodes", "current_edges")]
    p.add(cypher("Check entire owned namespace", guard, fields, readonly))
    require_result(p)
    if name == "graph_finish":
        p.add(execute("Record actually verified graph", "SELECT classification.finish_graph_load(?,?,?,?)", ["load_id", "expected_nodes", "expected_edges", "verified"]))
    p.save()


def build_graph():
    p = Pipeline("graph_start", "Acquire the shared writer and freeze exact current and retired O*NET inventory in PostgreSQL.")
    p.add(variables([("release_id", "RELEASE_ID")]))
    p.add(cypher("Read destination identity", "CALL db.info() YIELD id RETURN id AS database_id", readonly=True, returns=(("database_id", "String"),)))
    p.add(database("Create unique graph token", "SELECT gen_random_uuid()::text AS load_id", []))
    p.add(remember("load_id", "ONET_LOAD_ID"))
    p.add(execute("Freeze planned catalogue writer", "SELECT classification.begin_graph_load(?,?,?)", ["release_id", "database_id", "load_id"]))
    p.save()
    scope_pipeline("graph_preflight_scope")
    node_preflight = f"""CALL (row,expected_properties,previous_properties) {{
OPTIONAL MATCH (object:entity {{id:row.node_id}})
RETURN count(object)<=1 AND all(ok IN collect(CASE WHEN object IS NULL THEN true ELSE coalesce(
 object.managed_by='{OWNER}' AND object.scheme_id='ONET' AND
 (({EXPECTED} AND {NODE_LABELS}) OR ({BASELINE} AND {OLD_NODE_LABELS})),false) END) WHERE ok) AS row_matches
}}
RETURN count(*)=size($rows) AND all(ok IN collect(row_matches) WHERE ok) AS verified"""
    row_pipeline("graph_preflight_nodes", "Reject every reserved node collision before the first graph write.", "nodes", node_preflight, True)
    edge_preflight = f"""CALL (row,candidates,expected_properties,previous_properties) {{
WITH row,expected_properties,previous_properties,
 [candidate IN candidates WHERE candidate.object.id=row.edge_id] AS matches
UNWIND CASE WHEN size(matches)=0 THEN [null] ELSE matches END AS candidate
WITH row,expected_properties,previous_properties,candidate.object AS object,
 candidate.start_id AS actual_start_id,candidate.end_id AS actual_end_id,candidate.edge_type AS actual_edge_type
RETURN count(object)<=1 AND all(ok IN collect(CASE WHEN object IS NULL THEN true ELSE coalesce(
 object.managed_by='{OWNER}' AND object.scheme_id='ONET' AND actual_edge_type=row.edge_type
 AND actual_start_id=row.start_id AND actual_end_id=row.end_id AND (({EXPECTED}) OR ({BASELINE})),false) END) WHERE ok) AS row_matches
}}
RETURN count(*)=size($rows) AND all(ok IN collect(row_matches) WHERE ok) AS verified"""
    row_pipeline("graph_preflight_edges", "Reject every reserved relationship collision before the first graph write.", "edges", edge_preflight, True,
                 EDGE_PREFLIGHT_PREFIX, DECODE.replace("WITH row,", "WITH row,candidates,"))
    p = Pipeline("graph_constraint", "Inspect entity identity uniqueness and create only a missing compatible constraint.")
    p.add(token())
    p.add(database("Require own running writer", "SELECT classification.assert_running_graph_load(?) AS checked_token", [("load_id", "String")]))
    p.add(cypher("Inspect entity identity constraint", """SHOW CONSTRAINTS YIELD name,entityType,type,labelsOrTypes,properties
RETURN count(CASE WHEN entityType='NODE' AND type IN ['UNIQUENESS','NODE_KEY','NODE_PROPERTY_UNIQUENESS'] AND labelsOrTypes=['entity'] AND properties=['id'] THEN 1 END)>0 AS correct,
count(CASE WHEN name='jobtology_onet_entity_id' THEN 1 END)=0 AS name_available""", readonly=True, returns=(("correct", "Boolean"), ("name_available", "Boolean"))))
    check = transform("FilterRows", "Identity constraint exists", send_true_to="Constraint accepted", send_false_to="Require free constraint name")
    condition = child(E.SubElement(check, "compare"), "condition", {"negated": "N", "operator": "-", "leftvalue": "correct", "function": "="})
    child(condition, "value", {"name": "constant", "type": "Boolean", "text": "Y", "length": -1, "precision": -1, "isnull": "N"})
    p.add(check)
    p.add(transform("Dummy", "Constraint accepted"))
    p.last = "Identity constraint exists"
    require_result(p, "name_available", "Require free constraint name")
    p.add(cypher("Create missing identity uniqueness", "CREATE CONSTRAINT jobtology_onet_entity_id FOR (n:entity) REQUIRE n.id IS UNIQUE", returns=()))
    p.save()
    node_write = f"""MERGE (object:entity {{id:row.node_id}})
ON CREATE SET object.managed_by='{OWNER}',object.content_hash=row.content_hash
WITH row,expected_properties,previous_properties,object
WHERE object.managed_by='{OWNER}' AND
 ((size(keys(object))=3 AND object.content_hash=row.content_hash AND labels(object)=['entity'])
 OR ({EXPECTED} AND {NODE_LABELS}) OR ({BASELINE} AND {OLD_NODE_LABELS}))
FOREACH (key IN [key IN keys(object) WHERE NOT key IN [p IN expected_properties | p.key]] | SET object[key]=null)
FOREACH (property IN expected_properties | SET object[property.key]=property.value)
SET object:$(split(row.expected_labels,'|'))
RETURN count(object)=size($rows) AND count(DISTINCT row.node_id)=size($rows) AS verified"""
    row_pipeline("graph_nodes", "Update only previously verified O*NET identities; soft-retired terms stay available as historical endpoints.", "nodes", node_write, False)
    edge_write = f"""MATCH (a:entity {{id:row.start_id}})
WITH row,expected_properties,previous_properties,a MATCH (b:entity {{id:row.end_id}})
WHERE a.managed_by='{OWNER}' AND b.managed_by='{OWNER}' AND a.scheme_id='ONET' AND b.scheme_id='ONET'
MERGE (a)-[object:$(row.edge_type) {{id:row.edge_id}}]->(b)
ON CREATE SET object.managed_by='{OWNER}',object.content_hash=row.content_hash
WITH row,expected_properties,previous_properties,object
WHERE object.managed_by='{OWNER}' AND ((size(keys(object))=3 AND object.content_hash=row.content_hash)
 OR ({EXPECTED}) OR ({BASELINE}))
FOREACH (key IN [key IN keys(object) WHERE NOT key IN [p IN expected_properties | p.key]] | SET object[key]=null)
FOREACH (property IN expected_properties | SET object[property.key]=property.value)
RETURN count(object)=size($rows) AND count(DISTINCT row.edge_id)=size($rows) AS verified"""
    row_pipeline("graph_edges", "Write direct owned IN_SCHEME and BROADER relationships without graph import-history nodes.", "edges", edge_write, False)
    node_verify = f"""OPTIONAL MATCH (object:entity {{id:row.node_id}})
RETURN count(object)=size($rows) AND count(DISTINCT row.node_id)=size($rows)
AND all(ok IN collect(coalesce(({EXPECTED}) AND ({NODE_LABELS}),false)) WHERE ok) AS verified"""
    row_pipeline("graph_verify_nodes", "Independently verify every expected scalar value, Neo4j value type and exact node label set.", "nodes", node_verify, True)
    edge_verify = f"""OPTIONAL MATCH (a:entity {{id:row.start_id}})-[object:$(row.edge_type) {{id:row.edge_id}}]->(b:entity {{id:row.end_id}})
RETURN count(object)=size($rows) AND count(DISTINCT row.edge_id)=size($rows)
AND all(ok IN collect(coalesce(({EXPECTED}),false)) WHERE ok) AS verified"""
    row_pipeline("graph_verify_edges", "Independently verify all relationship endpoints, types and complete typed properties.", "edges", edge_verify, True)
    scope_pipeline("graph_finish")
    scope_pipeline("graph_verify_scope")
    p = Pipeline("graph_activate", "Select only the exact independently verified O*NET release for catalogue reads.")
    p.add(token())
    p.add(database("Require verified current graph target", "SELECT classification.assert_verified_graph_load(?) AS checked_token", [("load_id", "String")]))
    p.add(database("Read verified load context", "SELECT * FROM classification.graph_load_context(?)", [("load_id", "String")]))
    p.add(execute("Activate verified catalogue", "SELECT classification.activate_catalog(?,?,?)", ["release_id", "database_id", "load_id"]))
    p.save()
    p = Pipeline("graph_require_verified", "Reject missing, invalid or superseded graph-load tokens before the read-only native verifier.")
    p.add(token())
    p.add(database("Require verified current graph target", "SELECT classification.assert_verified_graph_load(?) AS checked_token", [("load_id", "String")]))
    p.save()
    p = Pipeline("graph_fail", "Mark only this O*NET graph attempt failed and release its own shared writer.")
    p.add(token())
    p.add(execute("Fail only own catalogue writer", "SELECT classification.fail_graph_load(?)", ["load_id"]))
    p.save()


PARAMETERS = [("RELEASE_ID", "", "Exact immutable O*NET catalogue release; no latest-source or NCS fallback."),
              ("NEO4J_CONNECTION", "jobtology-neo4j", "Existing protected native Neo4j connection.")]
IMPORT_PARAMETERS = [("INPUT_FILE", "", "Absolute immutable prepared catalogue JSON under EVIDENCE_ROOT."),
                     ("EVIDENCE_ROOT", "", "Absolute private bundle containing raw sources and acquisition receipts."),
                     ("EXPECTED_INPUT_SHA256", "", "Exact SHA256 from the frozen catalogue descriptor."),
                     ("MAX_FILE_BYTES", "16777216", "Bounded prepared JSON, maximum 64MiB; no truncation.")]


def workflow(name, description, steps, parameters, failure_after_start=False):
    root = E.parse(ROOT / "hop/ontology/load_release.hwf").getroot()
    put(root, "name", name)
    put(root, "description", description)
    target = root.find("parameters")
    target.clear()
    for field, default, help_text in parameters:
        child(target, "parameter", {"name": field, "default_value": default, "description": help_text})
    actions = root.find("actions")
    templates = {node.findtext("type"): deepcopy(node) for node in actions}
    actions.clear()
    start = deepcopy(templates["SPECIAL"])
    put(start, "name", "Start")
    actions.append(start)
    for ordinal, (label, file) in enumerate(steps):
        action = deepcopy(templates["PIPELINE"])
        for key, value in {"name": label, "filename": "${PROJECT_HOME}/ingestions/onet/" + file,
                           "run_configuration": "onet-local", "xloc": 100 + ordinal % 4 * 250,
                           "yloc": 200 + ordinal // 4 * 150}.items():
            put(action, key, value)
        action.find("parameters").clear()
        put(action.find("parameters"), "pass_all_parameters", "Y")
        actions.append(action)
    for kind, label in (("SUCCESS", "Success"), ("ABORT", "Abort")):
        action = deepcopy(templates[kind])
        put(action, "name", label)
        if kind == "ABORT":
            put(action, "message", "O*NET catalogue import or graph verification failed. Replay the exact frozen bundle after inspecting its own failed attempt.")
        actions.append(action)
    if failure_after_start:
        action = deepcopy(templates["PIPELINE"])
        put(action, "name", "Fail own graph attempt")
        put(action, "filename", "${PROJECT_HOME}/ingestions/onet/graph_fail.hpl")
        put(action, "run_configuration", "onet-local")
        action.find("parameters").clear()
        put(action.find("parameters"), "pass_all_parameters", "Y")
        actions.append(action)
    hops = root.find("hops")
    hops.clear()
    chain = ["Start", *(label for label, _ in steps), "Success"]
    for ordinal, label in enumerate(chain[:-1]):
        child(hops, "hop", {"from": label, "to": chain[ordinal + 1], "enabled": "Y",
                            "evaluation": "Y", "unconditional": "Y" if ordinal == 0 else "N"})
        if ordinal:
            target = "Fail own graph attempt" if failure_after_start and ordinal > (2 if steps[0][1] == "import_local.hpl" else 1) else "Abort"
            child(hops, "hop", {"from": label, "to": target, "enabled": "Y", "evaluation": "N", "unconditional": "N"})
    if failure_after_start:
        for evaluation in ("Y", "N"):
            child(hops, "hop", {"from": "Fail own graph attempt", "to": "Abort", "enabled": "Y", "evaluation": evaluation, "unconditional": "N"})
    save(root, name + ".hwf")


def build_workflows():
    steps = [("Acquire exact catalogue writer", "graph_start.hpl"),
             ("Preflight entire O*NET namespace", "graph_preflight_scope.hpl"),
             ("Preflight all catalogue nodes", "graph_preflight_nodes.hpl"),
             ("Preflight all catalogue relationships", "graph_preflight_edges.hpl"),
             ("Require entity identity uniqueness", "graph_constraint.hpl"),
             ("Write owned catalogue nodes", "graph_nodes.hpl"),
             ("Write direct catalogue hierarchy", "graph_edges.hpl"),
             ("Verify every typed node", "graph_verify_nodes.hpl"),
             ("Verify every typed relationship", "graph_verify_edges.hpl"),
             ("Checkpoint actual complete graph", "graph_finish.hpl"),
             ("Select verified catalogue", "graph_activate.hpl")]
    workflow("load_catalog", "Import frozen official local O*NET catalogue evidence, load and verify its owned graph, then select it. No posting matching or model calls.",
             [("Import exact local catalogue", "import_local.hpl"), *steps], IMPORT_PARAMETERS + PARAMETERS, True)
    workflow("replay_catalog", "Replay the exact READY O*NET release; full collision, typed graph and inventory checks precede selection.", steps, PARAMETERS, True)
    workflow("verify_catalog", "Read-only exact current and retired O*NET graph verification for an explicit preserved graph-load token.",
             [("Require exact verified target", "graph_require_verified.hpl"),
              ("Verify every typed node", "graph_verify_nodes.hpl"), ("Verify every typed relationship", "graph_verify_edges.hpl"),
              ("Verify complete owned scope", "graph_verify_scope.hpl")],
             [("ONET_LOAD_ID", "", "Exact graph-load token retained in PostgreSQL."), *PARAMETERS])
    root = E.parse(ROOT / "hop/ontology/install.hwf").getroot()
    put(root, "name", "Install the independent O*NET catalogue schema and graph contracts")
    put(root, "description", "Add only the independent classification ledger and owned graph interfaces. Existing ontology, posting and model contracts are untouched.")
    root.find("parameters").clear()
    actions = root.find("actions")
    templates = {node.findtext("type"): deepcopy(node) for node in actions}
    actions.clear()
    for kind, label in (("SPECIAL", "Start"), ("SUCCESS", "Success"), ("ABORT", "Abort")):
        action = deepcopy(templates[kind])
        put(action, "name", label)
        actions.append(action)
    steps = []
    for file in sorted((OUT / "sql").glob("*.sql")):
        label = "Install O*NET " + file.stem
        action = deepcopy(templates["SQL"])
        put(action, "name", label)
        put(action, "sqlfilename", "${PROJECT_HOME}/ingestions/onet/sql/" + file.name)
        actions.append(action)
        steps.append(label)
    hops = root.find("hops")
    hops.clear()
    names = ["Start", *steps, "Success"]
    for ordinal, label in enumerate(names[:-1]):
        child(hops, "hop", {"from": label, "to": names[ordinal + 1], "enabled": "Y", "evaluation": "Y", "unconditional": "Y" if ordinal == 0 else "N"})
        if ordinal:
            child(hops, "hop", {"from": label, "to": "Abort", "enabled": "Y", "evaluation": "N", "unconditional": "N"})
    save(root, "install.hwf")


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    build_import()
    build_graph()
    build_workflows()
    for kind in ("pipeline", "workflow"):
        path = ROOT / f"hop/metadata/{kind}-run-configuration"
        metadata = json.loads((path / "jobkorea-local.json").read_text())
        metadata["name"] = "onet-local"
        metadata["description"] = "Local frozen O*NET catalogue only; Basic logging and no execution-data capture."
        (path / "onet-local.json").write_text(json.dumps(metadata, indent=2) + "\n")


if __name__ == "__main__":
    build()
