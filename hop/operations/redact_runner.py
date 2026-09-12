"""Host log boundary only. ETL and graph operations are native Hop workflows."""
import os
import subprocess
import sys
from urllib.parse import quote, quote_plus

container, root, key_file, workflow, parameters, log_path = sys.argv[1:]
key_rows = subprocess.check_output(
    ["docker", "exec", container, "cat", key_file], text=True
).splitlines()
if len(key_rows) != 2 or key_rows[0] != "service_key" or not key_rows[1]:
    raise SystemExit("Invalid protected API-key CSV; expected exactly one key.")
key = key_rows[1]
forms = {key, quote(key, safe=""), quote_plus(key)}
command = [
    "docker", "exec", "-w", root, container, "bash", "hop-run.sh",
    "-j", "default", "-r", "reference-local", "-f", workflow,
    "-p", parameters, "-l", "Basic",
]
# Exclusive creation: scheduler logs, like raw snapshots, are never overwritten.
with open(log_path, "x", encoding="utf-8") as output:
    os.chmod(log_path, 0o600)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in process.stdout:
        for form in forms:
            line = line.replace(form, "<redacted>")
        output.write(line)
        output.flush()
    code = process.wait()
print(f"Hop exit: {code}")
raise SystemExit(code)
