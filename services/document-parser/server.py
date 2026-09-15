"""Private, read-only parser adapter for Hop. It never follows document URLs."""
from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import sys
import tempfile
import zipfile

MAX_BYTES = 64 * 1024 * 1024
MAX_OUTPUT = 64 * 1024 * 1024
ROOT = Path(os.environ.get("DOCUMENT_ROOT", "/documents")).resolve()
TIMEOUT = int(os.environ.get("PARSE_TIMEOUT_SECONDS", "180"))


def validate(request, root=ROOT):
    if not isinstance(request, dict) or set(request) != {"path", "raw_hash", "extension"}:
        raise ValueError("INVALID_REQUEST")
    if not all(isinstance(v, str) for v in request.values()):
        raise ValueError("INVALID_REQUEST")
    path = Path(request["path"]).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("PATH_OUTSIDE_DOCUMENT_ROOT")
    ext = request["extension"]
    if ext not in {"pdf", "hwp", "hwpx", "doc", "docx", "zip"} or path.suffix.lower() != "." + ext:
        raise ValueError("UNSUPPORTED_FORMAT")
    if not re.fullmatch(r"[0-9a-f]{64}", request["raw_hash"]):
        raise ValueError("INVALID_SOURCE_HASH")
    if not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError("DOCUMENT_SIZE_LIMIT")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != request["raw_hash"]:
        raise ValueError("SOURCE_HASH_MISMATCH")
    if ext in {"hwpx", "docx", "zip"}:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > 20000 or sum(i.file_size for i in members) > 256 * 1024 * 1024:
                raise ValueError("ARCHIVE_SIZE_LIMIT")
            if any(i.flag_bits & 1 for i in members):
                raise ValueError("ENCRYPTED_DOCUMENT")
            if ext == "zip" and any(PurePosixPath(i.filename).is_absolute()
                    or ".." in PurePosixPath(i.filename).parts or "\\" in i.filename
                    or (i.external_attr >> 16) & 0o170000 == 0o120000 for i in members):
                raise ValueError("UNSAFE_ARCHIVE_MEMBER")
    return path


def parse(request, root=ROOT):
    path = validate(request, root)
    with tempfile.TemporaryDirectory(prefix="docir-") as directory:
        output = Path(directory) / "result.json"
        with (Path(directory) / "worker.log").open("wb") as log:
            process = subprocess.Popen([sys.executable, str(Path(__file__).with_name("worker.py"))],
                stdin=subprocess.PIPE, stdout=log, stderr=log, start_new_session=True)
            try:
                process.communicate(json.dumps(request | {"path": str(path), "result_path": str(output)}).encode(), timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                return {"state": "PARSE_ERROR", "issue": "PARSER_TIMEOUT"}
        if process.returncode or not output.is_file():
            return {"state": "PARSE_ERROR", "issue": "PARSER_FAILED"}
        if output.stat().st_size > MAX_OUTPUT:
            return {"state": "PARSE_ERROR", "issue": "PARSER_OUTPUT_LIMIT"}
        # Input is mounted read-only; verify again to catch external replacement.
        validate(request, root)
        return json.loads(output.read_text(encoding="utf-8"))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Do not log source paths or document contents.

    def respond(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.respond(200 if self.path == "/health" else 404,
                     {"service": "document-parser", "revision": os.environ.get("PARSER_REVISION", "development")})

    def do_POST(self):
        if self.path != "/parse":
            self.respond(404, {"issue": "NOT_FOUND"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 16384:
                raise ValueError("INVALID_REQUEST_SIZE")
            result = parse(json.loads(self.rfile.read(size)))
            self.respond(200, result)
        except (ValueError, OSError, zipfile.BadZipFile) as error:
            code = str(error) if isinstance(error, ValueError) and re.fullmatch(r"[A-Z_]+", str(error)) else "INVALID_DOCUMENT"
            self.respond(422, {"state": "PARSE_ERROR", "issue": code})


if __name__ == "__main__":
    HTTPServer((os.environ.get("BIND_ADDRESS", "0.0.0.0"), int(os.environ.get("PORT", "8080"))), Handler).serve_forever()
