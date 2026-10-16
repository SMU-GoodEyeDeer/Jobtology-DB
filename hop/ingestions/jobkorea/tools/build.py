# ruff: noqa: E501
"""Generate the offline native Hop JobKorea local-file adapter (development only)."""

import json
import xml.etree.ElementTree as E
from copy import deepcopy
from pathlib import Path

from build_ndjson import extend_java

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / "hop/ingestions/jobkorea"


def put(node, tag, value):
    target = node.find(tag)
    if target is None:
        target = E.SubElement(node, tag)
    target.text = str(value)


def save(node, path):
    E.indent(node, space="  ")
    E.ElementTree(node).write(path, encoding="UTF-8", xml_declaration=True)


JAVA = r"""
String failureCode = "LOCAL_INPUT_INVALID";
String runId = null;
org.apache.hop.core.database.Database db = null;

void require(boolean condition, String code) throws Exception {
  if (!condition) { failureCode = code; throw new Exception(code); }
}

byte[] boundedRead(java.nio.file.Path file, long limit) throws Exception {
  require(java.nio.file.Files.isRegularFile(file, java.nio.file.LinkOption.NOFOLLOW_LINKS), "LOCAL_FILE_REQUIRED");
  require(!java.nio.file.Files.isSymbolicLink(file), "LOCAL_SYMLINK_FORBIDDEN");
  require(java.nio.file.Files.size(file) > 0 && java.nio.file.Files.size(file) <= limit, "LOCAL_FILE_SIZE");
  java.io.InputStream stream = java.nio.file.Files.newInputStream(file, java.nio.file.LinkOption.NOFOLLOW_LINKS);
  try {
    java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
    byte[] buffer = new byte[8192];
    int count;
    while ((count = stream.read(buffer)) != -1) {
      require((long) out.size() + count <= limit, "LOCAL_FILE_SIZE");
      out.write(buffer, 0, count);
    }
    return out.toByteArray();
  } finally { stream.close(); }
}

String digest(byte[] bytes) throws Exception {
  byte[] hash = java.security.MessageDigest.getInstance("SHA-256").digest(bytes);
  StringBuilder text = new StringBuilder();
  for (int i = 0; i < hash.length; i++) {
    int value = hash[i] & 255;
    if (value < 16) text.append('0');
    text.append(Integer.toHexString(value));
  }
  return text.toString();
}

void directory(java.nio.file.Path path) throws Exception {
  java.nio.file.Path absolute = path.toAbsolutePath().normalize();
  java.nio.file.Path current = absolute.getRoot();
  for (java.nio.file.Path component : absolute) {
    current = current.resolve(component);
    require(!java.nio.file.Files.isSymbolicLink(current), "ARCHIVE_SYMLINK_FORBIDDEN");
    if (!java.nio.file.Files.exists(current, java.nio.file.LinkOption.NOFOLLOW_LINKS)) {
      try { java.nio.file.Files.createDirectory(current, java.nio.file.attribute.PosixFilePermissions.asFileAttribute(java.nio.file.attribute.PosixFilePermissions.fromString("rwx------"))); }
      catch (java.nio.file.FileAlreadyExistsException exists) { }
    }
    require(java.nio.file.Files.isDirectory(current, java.nio.file.LinkOption.NOFOLLOW_LINKS), "ARCHIVE_DIRECTORY_REQUIRED");
  }
}

public boolean processRow() throws HopException {
  Object[] row = getRow();
  if (row == null) { setOutputDone(); return false; }
  try {
    String mode = get(Fields.In, "mode").getString(row);
    require("IMPORT".equals(mode) || "DRY_RUN".equals(mode), "IMPORT_MODE_INVALID");
    require(!"DRY_RUN".equals(mode) || "true".equals(System.getenv("JOBKOREA_ISOLATED_CONTEXT")), "DRY_RUN_ISOLATION_REQUIRED");
    String input = get(Fields.In, "input_file").getString(row);
    String raw = get(Fields.In, "raw_root").getString(row);
    require(input != null && input.startsWith("/") && raw != null && raw.startsWith("/"), "ABSOLUTE_LOCAL_PATH_REQUIRED");
    long limit = Long.parseLong(getVariable("MAX_FILE_BYTES", "16777216"));
    require(limit > 0 && limit <= 67108864, "FILE_BOUND_INVALID");
    failureCode = "LOCAL_DATABASE_FAILED";
    org.apache.hop.core.database.DatabaseMeta connection = (org.apache.hop.core.database.DatabaseMeta)
      getPipelineMeta().getMetadataProvider().getSerializer(org.apache.hop.core.database.DatabaseMeta.class).load("jobtology-postgres");
    db = new org.apache.hop.core.database.Database(getParent(), getParent(), connection);
    db.connect();
    java.sql.Connection jdbc = db.getConnection();
    if ("DRY_RUN".equals(mode)) {
      String token = System.getenv("JOBKOREA_ISOLATED_TOKEN");
      require(token != null && token.matches("[0-9a-f]{12}"), "DRY_RUN_DATABASE_ISOLATION_REQUIRED");
      java.sql.PreparedStatement guard = jdbc.prepareStatement("SELECT current_database() = ? AND current_setting('jobtology.isolated_fixture',true)=?");
      try {
        guard.setString(1, "jobkorea_dryrun_"+token); guard.setString(2, token);
        java.sql.ResultSet result = guard.executeQuery();
        try { require(result.next() && result.getBoolean(1), "DRY_RUN_DATABASE_ISOLATION_REQUIRED"); }
        finally { result.close(); }
      } finally { guard.close(); }
    }
    if ("DRY_RUN".equals(mode)) {
      String token = System.getenv("JOBKOREA_ISOLATED_TOKEN");
      failureCode = "DRY_RUN_NEO4J_ISOLATION_REQUIRED";
      Class neoClass = getPipelineMeta().getMetadataProvider().getMetadataClassForKey("neo4j-connection");
      Object neo = getPipelineMeta().getMetadataProvider().getSerializer(neoClass).load(getVariable("NEO4J_CONNECTION", "jobtology-neo4j"));
      java.lang.reflect.Method endpoints = neoClass.getMethod("getURIs", new Class[] {org.apache.hop.core.variables.IVariables.class});
      java.util.List uris = (java.util.List) endpoints.invoke(neo, new Object[] {getParent()});
      require(uris.size() == 1, "DRY_RUN_NEO4J_ISOLATION_REQUIRED");
      java.net.URI endpoint = (java.net.URI) uris.get(0);
      require(("bolt://jobtology-jobkorea-test-"+token+"-neo:7687").equals(endpoint.toString()), "DRY_RUN_NEO4J_ISOLATION_REQUIRED");
    }
    java.nio.file.Path source = java.nio.file.Paths.get(input);
    byte[] bytes = boundedRead(source, limit);
    String sha = digest(bytes);
    failureCode = "LOCAL_UTF8_INVALID";
    String body = java.nio.charset.StandardCharsets.UTF_8.newDecoder()
      .onMalformedInput(java.nio.charset.CodingErrorAction.REPORT)
      .onUnmappableCharacter(java.nio.charset.CodingErrorAction.REPORT)
      .decode(java.nio.ByteBuffer.wrap(bytes)).toString();
    failureCode = "LOCAL_JSON_INVALID";
    com.fasterxml.jackson.core.JsonFactory factory = new com.fasterxml.jackson.core.JsonFactory();
    factory.enable(com.fasterxml.jackson.core.JsonParser.Feature.STRICT_DUPLICATE_DETECTION);
    com.fasterxml.jackson.core.JsonParser parser = factory.createParser(body);
    try {
      require(parser.nextToken() == com.fasterxml.jackson.core.JsonToken.START_ARRAY, "LOCAL_JSON_ARRAY_REQUIRED");
      while (parser.nextToken() != com.fasterxml.jackson.core.JsonToken.END_ARRAY) {
        require(parser.currentToken() != null, "LOCAL_JSON_INVALID");
        parser.skipChildren();
      }
      require(parser.nextToken() == null, "LOCAL_JSON_TRAILING_CONTENT");
    } finally { parser.close(); }
    failureCode = "LOCAL_ARCHIVE_FAILED";
    String relative = "jobkorea/" + sha + "/source.json";
    java.nio.file.Path root = java.nio.file.Paths.get(raw).toAbsolutePath().normalize();
    java.nio.file.Path archived = root.resolve(relative).normalize();
    require(archived.startsWith(root), "ARCHIVE_ESCAPE_FORBIDDEN");
    directory(archived.getParent());
    if (!java.nio.file.Files.exists(archived, java.nio.file.LinkOption.NOFOLLOW_LINKS)) {
      java.nio.file.Path temporary = java.nio.file.Files.createTempFile(archived.getParent(), ".source-", ".tmp",
        java.nio.file.attribute.PosixFilePermissions.asFileAttribute(java.nio.file.attribute.PosixFilePermissions.fromString("rw-------")));
      try {
        java.nio.file.Files.write(temporary, bytes);
        java.nio.file.Files.setPosixFilePermissions(temporary, java.nio.file.attribute.PosixFilePermissions.fromString("r--------"));
        // CREATE_NEW-style atomic hard link never replaces an existing evidence file.
        try { java.nio.file.Files.createLink(archived, temporary); }
        catch (java.nio.file.FileAlreadyExistsException exists) { }
      } finally { java.nio.file.Files.deleteIfExists(temporary); }
    }
    byte[] check = boundedRead(archived, limit);
    require(check.length == bytes.length && sha.equals(digest(check)), "ARCHIVE_HASH_MISMATCH");
    failureCode = "IMPORT_BEGIN_FAILED";
    java.sql.PreparedStatement begin = jdbc.prepareStatement("SELECT * FROM ingestion.begin_jobkorea_import(?,?,?,?::timestamptz,NULL::timestamptz)");
    try {
      begin.setString(1, sha); begin.setLong(2, bytes.length); begin.setString(3, relative);
      begin.setString(4, java.time.Instant.now().toString());
      java.sql.ResultSet result = begin.executeQuery();
      try { require(result.next(), "IMPORT_BEGIN_EMPTY"); runId = result.getString("run_id"); }
      finally { result.close(); }
    } finally { begin.close(); }
    failureCode = "IMPORT_LOAD_FAILED";
    java.sql.PreparedStatement load = jdbc.prepareStatement("SELECT * FROM ingestion.load_jobkorea_document(?,?)");
    try {
      load.setString(1, runId); load.setString(2, body);
      java.sql.ResultSet result = load.executeQuery();
      try { require(result.next(), "IMPORT_LOAD_EMPTY"); require(result.getString("error_code") == null, "IMPORT_LOAD_REJECTED"); }
      finally { result.close(); }
    } finally { load.close(); }
    check = boundedRead(archived, limit);
    require(check.length == bytes.length && sha.equals(digest(check)), "ARCHIVE_HASH_MISMATCH");
    failureCode = "IMPORT_VERIFY_FAILED";
    java.sql.PreparedStatement verify = jdbc.prepareStatement("SELECT ingestion.verify_jobkorea_file(?,?,?)");
    try { verify.setString(1, runId); verify.setString(2, digest(check)); verify.setLong(3, check.length); verify.execute(); }
    finally { verify.close(); }
    failureCode = "IMPORT_FINALIZE_FAILED";
    java.sql.PreparedStatement finish = jdbc.prepareStatement("SELECT * FROM ingestion.finalize_jobkorea_import(?)");
    String state;
    long records;
    long issues;
    try {
      finish.setString(1, runId);
      java.sql.ResultSet result = finish.executeQuery();
      try { require(result.next(), "IMPORT_FINALIZE_EMPTY"); state = result.getString("state"); records = result.getLong("record_count"); issues = result.getLong("issue_count"); }
      finally { result.close(); }
    } finally { finish.close(); }
    require("READY".equals(state) && issues == 0, "IMPORT_REVIEW_REQUIRED");
    Object[] output = createOutputRow(row, data.outputRowMeta.size());
    get(Fields.Out, "run_id").setValue(output, runId);
    get(Fields.Out, "state").setValue(output, state);
    get(Fields.Out, "record_count").setValue(output, Long.valueOf(records));
    get(Fields.Out, "raw_sha256").setValue(output, sha);
    putRow(data.outputRowMeta, output);
    return true;
  } catch (Exception failure) {
    if (db != null && runId != null) {
      try {
        java.sql.PreparedStatement mark = db.getConnection().prepareStatement("SELECT ingestion.mark_failed_jobkorea_import(?,?)");
        try { mark.setString(1, runId); mark.setString(2, failureCode); mark.execute(); }
        finally { mark.close(); }
      } catch (Exception ignored) { }
    }
    // Never expose JDBC exception messages, source bytes, row values or signed URLs.
    throw new HopException("JobKorea local import failed: " + failureCode + " (" + failure.getClass().getSimpleName() + ")");
  } finally { if (db != null) { db.close(); db = null; } }
}
"""


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sql").mkdir(exist_ok=True)
    (OUT / "sql/005_shared_checks.sql").write_bytes(
        (ROOT / "docs/hop-migration/checks.sql").read_bytes()
    )
    p = E.parse(ROOT / "hop/ingestions/job_alio/start_run.hpl").getroot()
    for n in p.findall("transform"):
        p.remove(n)
    put(p.find("info"), "name", "import_local")
    put(
        p.find("info"),
        "description",
        "Local JSON-array or streaming NDJSON archival and prepared SQL import. URLs are inert evidence.",
    )
    parameters = p.find("info/parameters")
    parameters.clear()
    for name, default in [
        ("INPUT_FILE", ""),
        ("RAW_ROOT", ""),
        ("MODE", "DRY_RUN"),
        ("INPUT_FORMAT", "AUTO"),
        ("MAX_FILE_BYTES", ""),
        ("MAX_LINE_BYTES", "1048576"),
        ("BATCH_ROWS", "500"),
        ("BATCH_BYTES", "4194304"),
        ("RESUME_RUN_ID", ""),
        ("NEO4J_CONNECTION", "jobtology-neo4j"),
    ]:
        parameter = E.SubElement(parameters, "parameter")
        put(parameter, "name", name)
        put(parameter, "default_value", default)
    context = deepcopy(
        E.parse(ROOT / "hop/ingestions/job_alio/start_run.hpl").find(
            "transform[name='Run options']"
        )
    )
    put(context, "name", "Local input options")
    context.find("fields").clear()
    for name, variable in [
        ("input_file", "INPUT_FILE"),
        ("raw_root", "RAW_ROOT"),
        ("mode", "MODE"),
    ]:
        f = E.SubElement(context.find("fields"), "field")
        for key, value in [
            ("name", name),
            ("variable", "${" + variable + "}"),
            ("type", "String"),
            ("length", -1),
            ("precision", -1),
            ("trim_type", "none"),
        ]:
            put(f, key, value)
    p.append(context)
    java = E.SubElement(p, "transform")
    for key, value in [
        ("name", "Archive and import local JSON"),
        ("type", "UserDefinedJavaClass"),
        ("clear_result_fields", "N"),
        ("java_target_version", 17),
    ]:
        put(java, key, value)
    definition = E.SubElement(E.SubElement(java, "definitions"), "definition")
    for key, value in [
        ("class_type", "TRANSFORM_CLASS"),
        ("class_name", "JobKoreaLocalImport"),
        ("class_source", extend_java(JAVA)),
    ]:
        put(definition, key, value)
    fields = E.SubElement(java, "fields")
    for name, kind in [
        ("run_id", "String"),
        ("state", "String"),
        ("record_count", "Integer"),
        ("raw_sha256", "String"),
    ]:
        field = E.SubElement(fields, "field")
        for key, value in [
            ("field_name", name),
            ("field_type", kind),
            ("field_length", -1),
            ("field_precision", -1),
        ]:
            put(field, key, value)
    put(java, "copies", 1)
    put(java, "distribute", "Y")
    gui = E.SubElement(java, "GUI")
    put(gui, "xloc", 340)
    put(gui, "yloc", 100)
    p.append(
        deepcopy(
            E.parse(ROOT / "hop/ingestions/job_alio/start_run.hpl").find(
                "transform[name='Remember run ID']"
            )
        )
    )
    remember = p.findall("transform")[-1]
    put(remember.find("fields/field"), "variable_name", "JOBKOREA_RUN_ID")
    order = p.find("order")
    order.clear()
    for start, end in [
        ("Local input options", "Archive and import local JSON"),
        ("Archive and import local JSON", "Remember run ID"),
    ]:
        h = E.SubElement(order, "hop")
        for key, value in [("from", start), ("to", end), ("enabled", "Y")]:
            put(h, key, value)
    save(p, OUT / "import_local.hpl")
    w = E.parse(ROOT / "hop/graph/load_snapshot.hwf").getroot()
    put(w, "name", "Import supplied JobKorea local export and verify source graph")
    put(
        w,
        "description",
        "Local files only. No source requests or paid enrichment. Default DRY_RUN requires isolated context.",
    )
    params = w.find("parameters")
    params.clear()
    for name, default, description in [
        ("INPUT_FILE", "", "Absolute supplied local JSON-array or NDJSON path; optional for archive-only resume."),
        ("RAW_ROOT", "", "Absolute private evidence directory."),
        (
            "MODE",
            "DRY_RUN",
            "DRY_RUN requires JOBKOREA_ISOLATED_CONTEXT=true; IMPORT writes explicitly configured staging DB.",
        ),
        ("INPUT_FORMAT", "AUTO", "AUTO by .ndjson/.jsonl extension, JSON_ARRAY or NDJSON."),
        ("MAX_FILE_BYTES", "", "Blank: JSON array 16 MiB or NDJSON 1 GiB; hard limits 64 MiB and 16 GiB."),
        ("MAX_LINE_BYTES", "1048576", "NDJSON physical line bytes including newline, maximum 16 MiB."),
        ("BATCH_ROWS", "500", "NDJSON committed batch rows, maximum 5000."),
        ("BATCH_BYTES", "4194304", "NDJSON committed batch bytes, maximum 32 MiB; must cover MAX_LINE_BYTES."),
        ("RESUME_RUN_ID", "", "Exact NDJSON run to resume from its verified private archive and durable checkpoint."),
        ("NEO4J_CONNECTION", "jobtology-neo4j", "Native private Neo4j connection."),
    ]:
        param = E.SubElement(params, "parameter")
        for key, value in [
            ("name", name),
            ("default_value", default),
            ("description", description),
        ]:
            put(param, key, value)
    actions = w.find("actions")
    samples = {n.findtext("type"): deepcopy(n) for n in actions.findall("action")}
    actions.clear()
    for label in ("Start",):
        action = deepcopy(samples["SPECIAL"])
        put(action, "name", label)
        actions.append(action)
    steps = [
        (
            "Import immutable local evidence",
            "PIPELINE",
            "${PROJECT_HOME}/ingestions/jobkorea/import_local.hpl",
            "jobkorea-local",
        ),
        (
            "Load and verify source graph",
            "WORKFLOW",
            "${PROJECT_HOME}/graph/load_snapshot.hwf",
            "graph-local",
        ),
        (
            "Save verified graph checkpoint",
            "PIPELINE",
            "${PROJECT_HOME}/operations/record_graph_export.hpl",
            "jobkorea-local",
        ),
    ]
    for index, (label, kind, filename, config) in enumerate(steps):
        action = deepcopy(samples["PIPELINE"])
        for key, value in [
            ("name", label),
            ("type", kind),
            ("filename", filename),
            ("run_configuration", config),
            ("xloc", 100 + index * 260),
            ("yloc", 230),
        ]:
            put(action, key, value)
        if index:
            parameter = E.SubElement(action.find("parameters"), "parameter")
            for key, value in [("name", "RUN_ID"), ("value", "${JOBKOREA_RUN_ID}")]:
                put(parameter, key, value)
        actions.append(action)
    for kind, label in [("SUCCESS", "Success"), ("ABORT", "Abort")]:
        action = deepcopy(samples[kind])
        put(action, "name", label)
        put(action, "xloc", 900 if kind == "SUCCESS" else 360)
        put(action, "yloc", 230 if kind == "SUCCESS" else 460)
        if kind == "ABORT":
            put(
                action,
                "message",
                "JobKorea import or graph verification failed. Inspect the import state, source projection and checkpoint before retrying the same file.",
            )
        actions.append(action)
    hops = w.find("hops")
    hops.clear()
    labels = ["Start"] + [s[0] for s in steps] + ["Success"]
    for index, label in enumerate(labels[:-1]):
        for target, evaluation in [(labels[index + 1], "Y")] + (
            [] if index == 0 else [("Abort", "N")]
        ):
            hop = E.SubElement(hops, "hop")
            for key, value in [
                ("from", label),
                ("to", target),
                ("evaluation", evaluation),
                ("enabled", "Y"),
                ("unconditional", "Y" if index == 0 else "N"),
            ]:
                put(hop, key, value)
    save(w, OUT / "full.hwf")
    build_installer()
    for kind in ("pipeline", "workflow"):
        path = ROOT / f"hop/metadata/{kind}-run-configuration"
        metadata = json.loads((path / "job-alio-local.json").read_text())
        metadata["name"] = "jobkorea-local"
        metadata["description"] = (
            "Local-only JobKorea native execution; Basic logging and no execution-data capture."
        )
        (path / "jobkorea-local.json").write_text(json.dumps(metadata, indent=2) + "\n")


def build_installer():
    installer = E.parse(ROOT / "hop/ontology/install.hwf").getroot()
    put(installer, "name", "Install JobKorea local-file source adapter")
    put(
        installer,
        "description",
        "Requires shared ingestion checks, operations, LLM and retention. CS integration is conditional. SQL001-008 and shared graph evidence contracts install sequentially; no source requests.",
    )
    installer.find("parameters").clear()
    actions = installer.find("actions")
    sql_action = deepcopy(next(a for a in actions if a.findtext("type") == "SQL"))
    for action in list(actions):
        if action.findtext("type") not in ("SPECIAL", "SUCCESS", "ABORT"):
            actions.remove(action)
    for action in actions:
        kind = action.findtext("type")
        put(action, "xloc", 80 if kind == "SPECIAL" else 1700 if kind == "SUCCESS" else 860)
        put(action, "yloc", 300 if kind == "ABORT" else 100)
        if kind == "ABORT":
            put(
                action,
                "message",
                "JobKorea adapter installation failed. Inspect the failed SQL action before replaying the installer.",
            )
    steps = ["Start"]
    for name in (
        "001_schema",
        "002_operations",
        "003_checks",
        "004_integration",
        "005_shared_checks",
        "006_ndjson",
        "007_dataset_provenance",
        "008_ready_statistics",
    ):
        action = deepcopy(sql_action)
        label = "JobKorea " + name
        put(action, "name", label)
        put(action, "sqlfilename", "${PROJECT_HOME}/ingestions/jobkorea/sql/" + name + ".sql")
        put(action, "xloc", 260 + 240 * (len(steps) - 1))
        put(action, "yloc", 100)
        actions.append(action)
        steps.append(label)
    action = E.Element("action")
    for key, value in {
        "name": "Install shared graph evidence contracts", "type": "WORKFLOW",
        "filename": "${PROJECT_HOME}/graph/install.hwf", "run_configuration": "jobkorea-local",
        "wait_until_finished": "Y",
        "xloc": 260 + 240 * (len(steps) - 1), "yloc": 100, "draw": "Y", "parallel": "N",
    }.items():
        put(action, key, value)
    actions.append(action)
    steps.append("Install shared graph evidence contracts")
    steps.append("Success")
    hops = installer.find("hops")
    hops.clear()
    for index, label in enumerate(steps[:-1]):
        for target, evaluation in [(steps[index + 1], "Y")] + (
            [] if index == 0 else [("Abort", "N")]
        ):
            hop = E.SubElement(hops, "hop")
            for key, value in [
                ("from", label),
                ("to", target),
                ("evaluation", evaluation),
                ("enabled", "Y"),
                ("unconditional", "Y" if index == 0 else "N"),
            ]:
                put(hop, key, value)
    save(installer, OUT / "install.hwf")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer-only", action="store_true")
    args = parser.parse_args()
    if args.installer_only:
        build_installer()
    else:
        build()
        from build_linking import build_linking

        build_linking()
