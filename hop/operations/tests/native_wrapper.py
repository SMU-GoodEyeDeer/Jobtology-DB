"""Native offline scope/routing fixture; only a uniquely named, network-none Hop.

Source and graph actions use synthetic pipelines. This verifies real Hop
PARENT_WORKFLOW scope and checkpoint routing; it does not claim a provider or
database integration test. Requires an already-local Hop image; never pulls.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import xml.etree.ElementTree as E
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REMOTE = "/fixture"


def put(node, tag, value):
    child = node.find(tag)
    if child is None:
        child = E.SubElement(node, tag)
    child.text = str(value)


def save(root, path):
    E.indent(root, space="  ")
    E.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)


def command(args, **kwargs):
    result = subprocess.run(args, text=True, capture_output=True, check=False, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stdout[-4000:] + result.stderr[-4000:])
    return result


def pipeline(path, variable, label, remember=False):
    root = E.parse(ROOT / "hop/operations/record_graph_export.hpl").getroot()
    for node in root.findall("transform"):
        root.remove(node)
    put(root.find("info"), "name", path.stem)
    getter = deepcopy(E.parse(ROOT / "hop/operations/record_graph_export.hpl").find(
        "transform[name='Exported run']"
    ))
    put(getter.find("fields/field"), "variable", variable)
    root.append(getter)
    if remember:
        output = deepcopy(E.parse(ROOT / "hop/ingestions/nara_job/start_run.hpl").find(
            "transform[name='Remember run ID']"
        ))
    else:
        output = deepcopy(E.parse(ROOT / "hop/graph/verify_totals.hpl").find(
            "transform[name='Graph totals']"
        ))
        put(output, "name", label)
        put(output, "logmessage", label)
        fields = output.find("fields")
        for field in list(fields)[1:]:
            fields.remove(field)
    root.append(output)
    put(root.find("order/hop"), "to", output.findtext("name"))
    save(root, path)


def stage(work, run_id):
    project = work / "project"
    project.mkdir()
    metadata = project / "metadata"
    for kind in ("pipeline", "workflow"):
        destination = metadata / f"{kind}-run-configuration"
        destination.mkdir(parents=True)
        config = json.loads((ROOT / "hop/metadata" / destination.name
                             / "nara-job-local.json").read_text())
        config["name"] = "fixture-local"
        (destination / "fixture-local.json").write_text(json.dumps(config))
    (project / "project-config.json").write_text(json.dumps({
        "metadataBaseFolder": "${PROJECT_HOME}/metadata", "variables": [],
    }))
    config = work / "config"
    config.mkdir()
    (config / "hop-config.json").write_text(json.dumps({"projectsConfig": {
        "enabled": True, "projectMandatory": True, "defaultProject": "fixture",
        "projectConfigurations": [{"projectName": "fixture",
                                   "projectHome": REMOTE + "/project",
                                   "configFilename": "project-config.json", "readOnly": False}],
        "lifecycleEnvironments": [], "projectLifecycles": [],
    }}))
    pipeline(project / "start.hpl", run_id, "start", remember=True)
    pipeline(project / "noop.hpl", run_id, "SOURCE_FIXTURE")
    pipeline(project / "graph.hpl", "${RUN_ID}", "GRAPH_RUN_HANDOFF")
    pipeline(project / "checkpoint.hpl", "${RUN_ID}", "CHECKPOINT_RUN_HANDOFF")
    root = E.parse(ROOT / "hop/operations/refresh_nara_job.hwf").getroot()
    for action in root.findall("actions/action"):
        filename = action.findtext("filename", "")
        if not filename:
            continue
        put(action, "run_configuration", "fixture-local")
        if action.findtext("name") == "Create run and pin date window":
            put(action, "filename", "${PROJECT_HOME}/start.hpl")
        elif action.findtext("name") == "Load accepted snapshot to graph":
            put(action, "filename", "${PROJECT_HOME}/graph.hwf")
        elif action.findtext("name") == "Save graph checkpoint":
            put(action, "filename", "${PROJECT_HOME}/checkpoint.hpl")
        else:
            put(action, "filename", "${PROJECT_HOME}/noop.hpl")
    save(root, project / "refresh.hwf")
    graph = deepcopy(root)
    parameters = graph.find("parameters")
    parameters.clear()
    parameter = E.SubElement(parameters, "parameter")
    put(parameter, "name", "RUN_ID")
    put(parameter, "default_value", "")
    actions = graph.find("actions")
    for action in list(actions):
        if action.findtext("name") not in ("Start", "Success", "Abort", "Save graph checkpoint"):
            actions.remove(action)
    log = next(a for a in actions if a.findtext("name") == "Save graph checkpoint")
    put(log, "name", "Graph fixture")
    put(log, "filename", "${PROJECT_HOME}/graph.hpl")
    put(log.find("parameters/parameter"), "value", "${RUN_ID}")
    hops = graph.find("hops")
    hops.clear()
    for source, target, success in [("Start", "Graph fixture", "Y"),
                                    ("Graph fixture", "Success", "Y"),
                                    ("Graph fixture", "Abort", "N")]:
        hop = E.SubElement(hops, "hop")
        for tag, value in [("from", source), ("to", target), ("evaluation", success),
                           ("enabled", "Y"), ("unconditional", "Y" if source == "Start" else "N")]:
            put(hop, tag, value)
    save(graph, project / "graph.hwf")
    return root, graph


def main():
    image = os.environ.get("HOP_WRAPPER_TEST_IMAGE", "apache/hop:latest")
    command(["docker", "image", "inspect", image])
    container = "jobtology-nara-wrapper-test-" + uuid.uuid4().hex[:12]
    work = Path(tempfile.mkdtemp(prefix=container + "-"))
    run_id = str(uuid.uuid4())
    root, graph = stage(work, run_id)
    try:
        command(["docker", "run", "-d", "--pull", "never", "--network", "none",
                 "--name", container, "--user", "root", "-v", str(work) + ":" + REMOTE,
                 "--entrypoint", "/bin/sleep", image, "infinity"])

        def run(label, expected_success):
            result = subprocess.run([
                "docker", "exec", "-e", "HOP_CONFIG_FOLDER=" + REMOTE + "/config",
                "-e", "HOP_OPTIONS=-Xmx512m", "-w", "/opt/hop", container,
                "bash", "hop-run.sh", "-j", "fixture", "-r", "fixture-local",
                "-f", REMOTE + "/project/refresh.hwf", "-l", "Basic",
            ], text=True, capture_output=True, check=False)
            output = result.stdout + result.stderr
            (work / (label + ".log")).write_text(output)
            assert (result.returncode == 0) == expected_success, output[-6500:]
            print(label, "passed", flush=True)
            return output

        output = run("success", True)
        for label in ("GRAPH_RUN_HANDOFF", "CHECKPOINT_RUN_HANDOFF"):
            assert re.search(label + r".*?run_id\s*=\s*" + run_id, output, re.S), output[-6500:]
        failing = deepcopy(graph)
        action = failing.find("actions/action[name='Graph fixture']")
        put(action, "type", "ABORT")
        put(action, "message", "Synthetic graph failure")
        save(failing, work / "project/graph.hwf")
        output = run("graph-failure", False)
        assert "CHECKPOINT_RUN_HANDOFF" not in output
        save(graph, work / "project/graph.hwf")
        failing = deepcopy(root)
        action = failing.find("actions/action[name='Fetch first list page']")
        put(action, "type", "ABORT")
        put(action, "message", "Synthetic fetch failure")
        save(failing, work / "project/refresh.hwf")
        output = run("fetch-failure", False)
        assert "GRAPH_RUN_HANDOFF" not in output and "CHECKPOINT_RUN_HANDOFF" not in output
        print("Native wrapper fixture passed; logs:", work, flush=True)
    finally:
        subprocess.run(["docker", "rm", "-fv", container], capture_output=True, check=False)
        # Retain small logs, remove the synthetic project/config from the host.
        shutil.rmtree(work / "project")
        shutil.rmtree(work / "config")


if __name__ == "__main__":
    main()
