# ruff: noqa: E501
"""Bounded NDJSON Java source for the native Hop importer; no runtime Python ETL."""

NDJSON_JAVA = r'''
boolean ndjsonMode = false;
boolean ndjsonTerminalFailure = false;
long ndjsonLineNumber = 1;
long ndjsonByteOffset = 0;
int ndjsonCommittedBatches = 0;
int ndjsonInterruptAfterBatches = 0;

void ndjsonRequire(boolean condition, String code) throws Exception {
  if (!condition) { ndjsonTerminalFailure = true; require(false, code); }
}

class NdjsonFile {
  java.nio.file.Path path;
  String relative;
  String sha;
  String scrapedAt;
  long size;
}

String inputFormat(String input, String resume) throws Exception {
  String requested = getVariable("INPUT_FORMAT", "AUTO");
  requested = requested == null ? "AUTO" : requested.trim().toUpperCase(java.util.Locale.ROOT);
  require("AUTO".equals(requested) || "JSON_ARRAY".equals(requested) || "NDJSON".equals(requested), "INPUT_FORMAT_INVALID");
  if (resume != null && !resume.trim().isEmpty()) {
    require(!"JSON_ARRAY".equals(requested), "NDJSON_RESUME_FORMAT_REQUIRED");
    return "NDJSON";
  }
  if (!"AUTO".equals(requested)) return requested;
  String name = input == null ? "" : input.toLowerCase(java.util.Locale.ROOT);
  return name.endsWith(".ndjson") || name.endsWith(".jsonl") ? "NDJSON" : "JSON_ARRAY";
}

long importFileLimit(String format) throws Exception {
  String configured = getVariable("MAX_FILE_BYTES", "");
  long limit = configured == null || configured.trim().isEmpty()
    ? ("NDJSON".equals(format) ? 1073741824L : 16777216L) : Long.parseLong(configured.trim());
  require(limit > 0 && limit <= ("NDJSON".equals(format) ? 17179869184L : 67108864L), "FILE_BOUND_INVALID");
  return limit;
}

void noPathLinks(java.nio.file.Path path) throws Exception {
  java.nio.file.Path absolute = path.toAbsolutePath().normalize();
  java.nio.file.Path component = absolute.getRoot();
  for (java.nio.file.Path part : absolute) {
    component = component.resolve(part);
    ndjsonRequire(!java.nio.file.Files.isSymbolicLink(component), "LOCAL_SYMLINK_FORBIDDEN");
  }
}

NdjsonFile hashNdjsonFile(java.nio.file.Path path, long limit) throws Exception {
  noPathLinks(path);
  ndjsonRequire(java.nio.file.Files.isRegularFile(path, java.nio.file.LinkOption.NOFOLLOW_LINKS), "LOCAL_FILE_REQUIRED");
  long expected = java.nio.file.Files.size(path);
  ndjsonRequire(expected > 0 && expected <= limit, "LOCAL_FILE_SIZE");
  java.security.MessageDigest hash = java.security.MessageDigest.getInstance("SHA-256");
  long count = 0;
  java.io.InputStream stream = java.nio.file.Files.newInputStream(path, java.nio.file.LinkOption.NOFOLLOW_LINKS);
  try {
    byte[] buffer = new byte[65536];
    int read;
    while ((read = stream.read(buffer)) != -1) {
      count += read;
      ndjsonRequire(count <= limit, "LOCAL_FILE_SIZE");
      hash.update(buffer, 0, read);
    }
  } finally { stream.close(); }
  ndjsonRequire(count == expected, "LOCAL_FILE_MUTATED");
  NdjsonFile result = new NdjsonFile();
  result.path = path; result.size = count;
  StringBuilder text = new StringBuilder();
  byte[] bytes = hash.digest();
  for (int i=0; i<bytes.length; i++) {
    int value = bytes[i] & 255;
    if (value < 16) text.append('0');
    text.append(Integer.toHexString(value));
  }
  result.sha = text.toString();
  return result;
}

NdjsonFile archiveNdjson(String input, String raw, long limit) throws Exception {
  failureCode = "NDJSON_ARCHIVE_FAILED";
  java.nio.file.Path source = java.nio.file.Paths.get(input).toAbsolutePath().normalize();
  noPathLinks(source);
  ndjsonRequire(java.nio.file.Files.isRegularFile(source, java.nio.file.LinkOption.NOFOLLOW_LINKS), "LOCAL_FILE_REQUIRED");
  java.nio.file.attribute.BasicFileAttributes before = java.nio.file.Files.readAttributes(source,
    java.nio.file.attribute.BasicFileAttributes.class, java.nio.file.LinkOption.NOFOLLOW_LINKS);
  ndjsonRequire(before.size() > 0 && before.size() <= limit, "LOCAL_FILE_SIZE");
  java.nio.file.Path root = java.nio.file.Paths.get(raw).toAbsolutePath().normalize();
  directory(root.resolve("jobkorea"));
  java.nio.file.Path temporary = java.nio.file.Files.createTempFile(root.resolve("jobkorea"), ".ndjson-", ".tmp",
    java.nio.file.attribute.PosixFilePermissions.asFileAttribute(java.nio.file.attribute.PosixFilePermissions.fromString("rw-------")));
  java.security.MessageDigest hash = java.security.MessageDigest.getInstance("SHA-256");
  long count = 0;
  try {
    java.io.InputStream stream = java.nio.file.Files.newInputStream(source, java.nio.file.LinkOption.NOFOLLOW_LINKS);
    java.nio.channels.FileChannel target = java.nio.channels.FileChannel.open(temporary, java.nio.file.StandardOpenOption.WRITE);
    try {
      byte[] buffer = new byte[65536];
      int read;
      while ((read = stream.read(buffer)) != -1) {
        count += read;
        ndjsonRequire(count <= limit, "LOCAL_FILE_SIZE");
        hash.update(buffer,0,read);
        java.nio.ByteBuffer bytes = java.nio.ByteBuffer.wrap(buffer,0,read);
        while (bytes.hasRemaining()) target.write(bytes);
      }
      target.force(true);
    } finally { try { stream.close(); } finally { target.close(); } }
    java.nio.file.attribute.BasicFileAttributes after = java.nio.file.Files.readAttributes(source,
      java.nio.file.attribute.BasicFileAttributes.class, java.nio.file.LinkOption.NOFOLLOW_LINKS);
    ndjsonRequire(count == before.size() && before.size() == after.size()
      && before.lastModifiedTime().equals(after.lastModifiedTime())
      && java.util.Objects.equals(before.fileKey(), after.fileKey()), "LOCAL_FILE_MUTATED");
    StringBuilder text = new StringBuilder();
    byte[] bytes = hash.digest();
    for (int i=0; i<bytes.length; i++) {
      int value=bytes[i]&255; if(value<16) text.append('0'); text.append(Integer.toHexString(value));
    }
    String sha = text.toString();
    String relative = "jobkorea/"+sha+"/source.ndjson";
    java.nio.file.Path archived = root.resolve(relative).normalize();
    ndjsonRequire(archived.startsWith(root), "ARCHIVE_ESCAPE_FORBIDDEN");
    directory(archived.getParent());
    java.nio.file.Files.setPosixFilePermissions(temporary,java.nio.file.attribute.PosixFilePermissions.fromString("r--------"));
    // An atomic no-replace link publishes only a completed, flushed evidence file.
    try { java.nio.file.Files.createLink(archived, temporary); }
    catch(java.nio.file.FileAlreadyExistsException exists) { }
    NdjsonFile result = hashNdjsonFile(archived,limit);
    ndjsonRequire(result.size==count && result.sha.equals(sha), "ARCHIVE_HASH_MISMATCH");
    result.relative = relative;
    return result;
  } finally { java.nio.file.Files.deleteIfExists(temporary); }
}

NdjsonFile resumeNdjson(java.sql.Connection jdbc, String resume, String raw, long limit) throws Exception {
  failureCode = "NDJSON_RESUME_BINDING_FAILED";
  java.sql.PreparedStatement query = jdbc.prepareStatement("SELECT i.file_sha256,i.byte_length,i.raw_path,i.scraped_at::text AS scraped_at FROM ingestion.jobkorea_import i JOIN ingestion.run r USING(run_id) WHERE i.run_id=? AND i.parser_version='hop-jobkorea-ndjson-v1' AND i.file_format='NDJSON' AND r.source_id='jobkorea' AND r.mode='REPLAY' AND r.parser_version=i.parser_version AND r.policy_revision=i.policy_revision AND i.run_id='jobkorea-ndjson-'||encode(sha256(convert_to(i.parser_version||':'||i.policy_revision||':'||i.file_sha256,'UTF8')),'hex')");
  String sha; String relative; String scrapedAt; long size;
  try {
    query.setString(1,resume);
    java.sql.ResultSet result=query.executeQuery();
    try {
      ndjsonRequire(result.next(),"NDJSON_RESUME_RUN_REQUIRED");
      sha=result.getString("file_sha256"); relative=result.getString("raw_path"); size=result.getLong("byte_length");scrapedAt=result.getString("scraped_at");
      ndjsonRequire(!result.next(),"NDJSON_RESUME_RUN_CONFLICT");
    } finally {result.close();}
  } finally {query.close();}
  ndjsonRequire(sha!=null && sha.matches("[0-9a-f]{64}") && ("jobkorea/"+sha+"/source.ndjson").equals(relative),"NDJSON_RESUME_PATH_INVALID");
  java.nio.file.Path root=java.nio.file.Paths.get(raw).toAbsolutePath().normalize();
  java.nio.file.Path path=root.resolve(relative).normalize();
  ndjsonRequire(path.startsWith(root),"ARCHIVE_ESCAPE_FORBIDDEN");
  NdjsonFile file=hashNdjsonFile(path,limit);
  ndjsonRequire(size==file.size && sha.equals(file.sha),"ARCHIVE_HASH_MISMATCH");
  file.relative=relative;
  file.scrapedAt=scrapedAt;
  return file;
}

byte[] readNdjsonLine(java.io.InputStream stream, int lineLimit) throws Exception {
  failureCode="NDJSON_READ_FAILED";
  java.io.ByteArrayOutputStream line=new java.io.ByteArrayOutputStream(2048);
  int value;
  while((value=stream.read())!=-1) {
    ndjsonRequire(line.size()<lineLimit,"NDJSON_LINE_BOUND_EXCEEDED");
    line.write(value);
    if(value==10) return line.toByteArray();
  }
  if(line.size()==0) return null;
  // Validate the terminal content first to distinguish truncation from framing.
  validateNdjsonLine(line.toByteArray(),false);
  ndjsonRequire(false,"NDJSON_FINAL_NEWLINE_REQUIRED");
  return null;
}

void validateNdjsonLine(byte[] bytes, boolean newline) throws Exception {
  failureCode="NDJSON_UTF8_INVALID";
  String body;
  try {
    body=java.nio.charset.StandardCharsets.UTF_8.newDecoder()
      .onMalformedInput(java.nio.charset.CodingErrorAction.REPORT)
      .onUnmappableCharacter(java.nio.charset.CodingErrorAction.REPORT)
      .decode(java.nio.ByteBuffer.wrap(bytes)).toString();
  } catch(java.nio.charset.CharacterCodingException failure) {ndjsonTerminalFailure=true;throw failure;}
  ndjsonRequire(!body.startsWith("\uFEFF"),"NDJSON_BOM_FORBIDDEN");
  if(newline) {
    ndjsonRequire(body.endsWith("\n"),"NDJSON_FINAL_NEWLINE_REQUIRED");
    body=body.substring(0,body.length()-1);
    if(body.endsWith("\r")) body=body.substring(0,body.length()-1);
  }
  ndjsonRequire(!body.trim().isEmpty(),"NDJSON_BLANK_LINE_FORBIDDEN");
  failureCode="NDJSON_JSON_INVALID";
  com.fasterxml.jackson.core.JsonFactory factory=new com.fasterxml.jackson.core.JsonFactory();
  factory.enable(com.fasterxml.jackson.core.JsonParser.Feature.STRICT_DUPLICATE_DETECTION);
  com.fasterxml.jackson.core.JsonParser parser=factory.createParser(body);
  try {
    ndjsonRequire(parser.nextToken()==com.fasterxml.jackson.core.JsonToken.START_OBJECT,"NDJSON_OBJECT_REQUIRED");
    parser.skipChildren();
    ndjsonRequire(parser.nextToken()==null,"NDJSON_TRAILING_CONTENT");
  } catch(com.fasterxml.jackson.core.JsonProcessingException failure) {ndjsonTerminalFailure=true;throw failure;}
  finally {parser.close();}
}

long[] appendNdjson(java.sql.Connection jdbc, long startByte, long startLine, java.io.ByteArrayOutputStream batch, int rows) throws Exception {
  failureCode="NDJSON_BATCH_DATABASE_FAILED";
  byte[] bytes=batch.toByteArray();
  String text=java.nio.charset.StandardCharsets.UTF_8.newDecoder()
    .onMalformedInput(java.nio.charset.CodingErrorAction.REPORT)
    .onUnmappableCharacter(java.nio.charset.CodingErrorAction.REPORT)
    .decode(java.nio.ByteBuffer.wrap(bytes)).toString();
  java.sql.PreparedStatement append=jdbc.prepareStatement("SELECT * FROM ingestion.append_jobkorea_ndjson_batch(?,?,?,?,?)");
  long nextByte; long nextLine;
  try {
    append.setString(1,runId);append.setLong(2,startByte);append.setLong(3,startLine);append.setString(4,text);append.setString(5,digest(bytes));
    java.sql.ResultSet result=append.executeQuery();
    try {
      ndjsonRequire(result.next(),"NDJSON_BATCH_EMPTY");
      nextByte=result.getLong("next_byte_offset");nextLine=result.getLong("next_line_number");
      ndjsonRequire(nextByte==startByte+bytes.length && nextLine==startLine+rows,"NDJSON_CHECKPOINT_MISMATCH");
      ndjsonRequire("LOADING".equals(result.getString("state")),"NDJSON_BATCH_STATE_INVALID");
    } finally {result.close();}
  } finally {append.close();}
  ndjsonCommittedBatches++;
  if(ndjsonInterruptAfterBatches>0 && ndjsonCommittedBatches==ndjsonInterruptAfterBatches) {
    // Test-only genuine process interruption: autocommit checkpoint survives;
    // no catch/failure marker runs and the source remains LOADING.
    java.lang.Runtime.getRuntime().halt(86);
  }
  return new long[]{nextByte,nextLine};
}

Object[] importNdjson(java.sql.Connection jdbc, Object[] row, String input, String raw, String resume, long limit, String mode) throws Exception {
  int lineLimit=Integer.parseInt(getVariable("MAX_LINE_BYTES","1048576"));
  int batchRows=Integer.parseInt(getVariable("BATCH_ROWS","500"));
  int batchBytes=Integer.parseInt(getVariable("BATCH_BYTES","4194304"));
  ndjsonRequire(lineLimit>0 && lineLimit<=16777216,"NDJSON_LINE_BOUND_INVALID");
  ndjsonRequire(batchRows>0 && batchRows<=5000,"NDJSON_BATCH_ROWS_INVALID");
  ndjsonRequire(batchBytes>0 && batchBytes<=33554432 && lineLimit<=batchBytes,"NDJSON_BATCH_BYTES_INVALID");
  String hook=System.getenv("JOBKOREA_NDJSON_INTERRUPT_AFTER_BATCHES");
  if(hook!=null && !hook.isEmpty()) {
    ndjsonRequire("DRY_RUN".equals(mode),"NDJSON_TEST_HOOK_ISOLATION_REQUIRED");
    // The caller has already verified env token AND the isolated database marker.
    ndjsonInterruptAfterBatches=Integer.parseInt(hook);
    ndjsonRequire(ndjsonInterruptAfterBatches>0 && ndjsonInterruptAfterBatches<=1000000,"NDJSON_TEST_HOOK_INVALID");
  }
  jdbc.setAutoCommit(true);
  NdjsonFile file=resume==null || resume.trim().isEmpty() ? archiveNdjson(input,raw,limit) : resumeNdjson(jdbc,resume.trim(),raw,limit);
  failureCode="NDJSON_BEGIN_DATABASE_FAILED";
  java.sql.PreparedStatement begin=jdbc.prepareStatement("SELECT * FROM ingestion.begin_jobkorea_ndjson_import(?,?,?,?::timestamptz,?::timestamptz)");
  String state;
  try {
    begin.setString(1,file.sha);begin.setLong(2,file.size);begin.setString(3,file.relative);begin.setString(4,java.time.Instant.now().toString());begin.setString(5,file.scrapedAt);
    java.sql.ResultSet result=begin.executeQuery();
    try {
      ndjsonRequire(result.next(),"NDJSON_BEGIN_EMPTY");runId=result.getString("run_id");state=result.getString("state");
      ndjsonByteOffset=result.getLong("next_byte_offset");ndjsonLineNumber=result.getLong("next_line_number");
      ndjsonRequire(resume==null || resume.trim().isEmpty() || resume.trim().equals(runId),"NDJSON_RESUME_ID_MISMATCH");
    } finally {result.close();}
  } finally {begin.close();}
  ndjsonRequire(ndjsonByteOffset>=0 && ndjsonByteOffset<=file.size && ndjsonLineNumber>=1,"NDJSON_CHECKPOINT_INVALID");
  ndjsonRequire("LOADING".equals(state) || "READY".equals(state) || "REVIEW_REQUIRED".equals(state),"NDJSON_RUN_NOT_RESUMABLE");
  if("LOADING".equals(state)) {
    java.nio.channels.FileChannel channel=java.nio.channels.FileChannel.open(file.path,java.nio.file.StandardOpenOption.READ);
    java.io.InputStream stream=null;
    try {
      if(ndjsonByteOffset>0) {
        java.nio.ByteBuffer last=java.nio.ByteBuffer.allocate(1);
        ndjsonRequire(channel.read(last,ndjsonByteOffset-1)==1 && last.get(0)==10,"NDJSON_CHECKPOINT_BOUNDARY_INVALID");
      }
      // Hash the bytes actually consumed by this parse, including the skipped
      // prefix on resume. Prefix reads are bounded and never reparse old rows.
      channel.position(0);
      java.security.MessageDigest parsedHash=java.security.MessageDigest.getInstance("SHA-256");
      java.security.DigestInputStream digested=new java.security.DigestInputStream(java.nio.channels.Channels.newInputStream(channel),parsedHash);
      byte[] prefix=new byte[65536];long prefixLeft=ndjsonByteOffset;
      while(prefixLeft>0) {
        int read=digested.read(prefix,0,(int)Math.min((long)prefix.length,prefixLeft));
        ndjsonRequire(read>0,"NDJSON_CHECKPOINT_BOUNDARY_INVALID");prefixLeft-=read;
      }
      stream=new java.io.BufferedInputStream(digested,65536);
      java.io.ByteArrayOutputStream batch=new java.io.ByteArrayOutputStream(Math.min(batchBytes,65536));
      long startByte=ndjsonByteOffset;long startLine=ndjsonLineNumber;int rows=0;
      byte[] line;
      while((line=readNdjsonLine(stream,lineLimit))!=null) {
        validateNdjsonLine(line,true);
        if(rows>0 && (rows==batchRows || batch.size()>batchBytes-line.length)) {
          long[] next=appendNdjson(jdbc,startByte,startLine,batch,rows);
          startByte=next[0];startLine=next[1];batch.reset();rows=0;
        }
        batch.write(line,0,line.length);rows++;
        ndjsonByteOffset+=line.length;ndjsonLineNumber++;
        if(rows==batchRows || batch.size()==batchBytes) {
          long[] next=appendNdjson(jdbc,startByte,startLine,batch,rows);
          startByte=next[0];startLine=next[1];batch.reset();rows=0;
        }
      }
      if(rows>0) appendNdjson(jdbc,startByte,startLine,batch,rows);
      StringBuilder parsedHex=new StringBuilder();
      byte[] parsedDigest=parsedHash.digest();
      for(int i=0;i<parsedDigest.length;i++) {
        int value=parsedDigest[i]&255;if(value<16)parsedHex.append('0');parsedHex.append(Integer.toHexString(value));
      }
      ndjsonRequire(ndjsonByteOffset==file.size && file.sha.equals(parsedHex.toString()),"NDJSON_PARSED_HASH_MISMATCH");
    } finally {if(stream!=null) stream.close(); else channel.close();}
  }
  failureCode="NDJSON_ARCHIVE_VERIFY_FAILED";
  NdjsonFile verified=hashNdjsonFile(file.path,limit);
  ndjsonRequire(verified.size==file.size && verified.sha.equals(file.sha),"ARCHIVE_HASH_MISMATCH");
  failureCode="NDJSON_SEAL_DATABASE_FAILED";
  java.sql.PreparedStatement finish=jdbc.prepareStatement("SELECT * FROM ingestion.seal_jobkorea_ndjson_import(?,?,?)");
  long records;long issues;
  try {
    finish.setString(1,runId);finish.setString(2,verified.sha);finish.setLong(3,verified.size);
    java.sql.ResultSet result=finish.executeQuery();
    try {ndjsonRequire(result.next(),"NDJSON_SEAL_EMPTY");state=result.getString("state");records=result.getLong("record_count");issues=result.getLong("issue_count");}
    finally {result.close();}
  } finally {finish.close();}
  ndjsonRequire("READY".equals(state) && issues==0,"IMPORT_REVIEW_REQUIRED");
  Object[] output=createOutputRow(row,data.outputRowMeta.size());
  get(Fields.Out,"run_id").setValue(output,runId);get(Fields.Out,"state").setValue(output,state);
  get(Fields.Out,"record_count").setValue(output,Long.valueOf(records));get(Fields.Out,"raw_sha256").setValue(output,file.sha);
  return output;
}

void markNdjsonFailure(Exception failure) {
  if(failure instanceof java.sql.SQLException) {
    String state=((java.sql.SQLException)failure).getSQLState();
    // Explicit data/binding exceptions are terminal. Operational errors,
    // including serialization, lock, resource and unknown states, leave the
    // last committed LOADING checkpoint available for a safe retry.
    if(state!=null && state.startsWith("22")) {
      ndjsonTerminalFailure=true;
      // The SQL contract exposes only a constant code and strict physical
      // locator in PostgreSQL DETAIL. Never copy an arbitrary JDBC message.
      try {
        java.lang.reflect.Method serverMethod=failure.getClass().getMethod("getServerErrorMessage",new Class[0]);
        Object server=serverMethod.invoke(failure,new Object[0]);
        if(server!=null) {
          String detail=(String)server.getClass().getMethod("getDetail",new Class[0]).invoke(server,new Object[0]);
          if(detail!=null) {
            java.util.regex.Matcher match=java.util.regex.Pattern.compile("^line:([1-9][0-9]*)@byte:([0-9]+)$").matcher(detail);
            if(match.matches()) {ndjsonLineNumber=Long.parseLong(match.group(1));ndjsonByteOffset=Long.parseLong(match.group(2));}
          }
          String code=(String)server.getClass().getMethod("getMessage",new Class[0]).invoke(server,new Object[0]);
          if(code!=null && code.matches("LOCAL_NDJSON_(LINE_TOO_LARGE|BLANK_LINE|BOM_FORBIDDEN|JSON_INVALID|DUPLICATE_KEYS|IDENTITY_INVALID|DUPLICATE_IDENTITY)|NDJSON_FINAL_NEWLINE_REQUIRED")) failureCode=code;
        }
      } catch(Exception ignored) { }
    }
  }
  if(!ndjsonTerminalFailure || db==null || runId==null) return;
  try {
    java.sql.PreparedStatement mark=db.getConnection().prepareStatement("SELECT ingestion.mark_failed_jobkorea_ndjson_import(?,?,?,?)");
    try {mark.setString(1,runId);mark.setLong(2,ndjsonLineNumber);mark.setLong(3,ndjsonByteOffset);mark.setString(4,failureCode);mark.execute();}
    finally {mark.close();}
  } catch(Exception ignored) { }
}
'''


def extend_java(java):
    """Add one explicit NDJSON branch while preserving legacy array operations."""
    replacements = {
        '    require(input != null && input.startsWith("/") && raw != null && raw.startsWith("/"), "ABSOLUTE_LOCAL_PATH_REQUIRED");\n    long limit = Long.parseLong(getVariable("MAX_FILE_BYTES", "16777216"));\n    require(limit > 0 && limit <= 67108864, "FILE_BOUND_INVALID");':
        '    String resume = getVariable("RESUME_RUN_ID", "");\n    String format = inputFormat(input, resume);\n    ndjsonMode = "NDJSON".equals(format);\n    require((input != null && input.startsWith("/") || ndjsonMode && resume != null && !resume.trim().isEmpty()) && raw != null && raw.startsWith("/"), "ABSOLUTE_LOCAL_PATH_REQUIRED");\n    long limit = importFileLimit(format);',
        '    java.nio.file.Path source = java.nio.file.Paths.get(input);':
        '    if (ndjsonMode) {\n      putRow(data.outputRowMeta, importNdjson(jdbc, row, input, raw, resume, limit, mode));\n      return true;\n    }\n    java.nio.file.Path source = java.nio.file.Paths.get(input);',
        '    if (db != null && runId != null) {':
        '    if (ndjsonMode) markNdjsonFailure(failure);\n    if (!ndjsonMode && db != null && runId != null) {',
        '    throw new HopException("JobKorea local import failed: " + failureCode + " (" + failure.getClass().getSimpleName() + ")");':
        '    throw new HopException("JobKorea local import failed: " + failureCode + (ndjsonMode ? " at line " + ndjsonLineNumber + " byte " + ndjsonByteOffset : "") + " (" + failure.getClass().getSimpleName() + ")");',
    }
    for old, new in replacements.items():
        assert java.count(old) == 1, old
        java = java.replace(old, new)
    return NDJSON_JAVA + java
