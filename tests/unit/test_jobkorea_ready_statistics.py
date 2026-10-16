"""Canonical seal preservation and source installer failure-chain contracts."""

import importlib.util
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def module(name: str, file: Path):
    spec = importlib.util.spec_from_file_location(name, file)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_generated_refresh_preserves_the_complete_canonical_seal(tmp_path: Path) -> None:
    relative = "hop/ingestions/jobkorea/sql/006_ndjson.sql"
    destination = tmp_path / relative
    destination.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / relative, destination)
    generator = module(
        "ready_statistics_generator",
        ROOT / "hop/ingestions/jobkorea/tools/build_ready_statistics.py",
    )
    generator.ROOT = tmp_path
    generated = generator.build()
    assert generated == (ROOT / "hop/ingestions/jobkorea/sql/008_ready_statistics.sql").read_text()
    assert generated == generator.build()
    canonical = destination.read_text()
    start = canonical.index("CREATE OR REPLACE FUNCTION ingestion.seal_jobkorea_ndjson_import(")
    end = canonical.index("\nEND $$;", start) + len("\nEND $$;")
    original = canonical[start:end]
    candidate_start = generated.index("CREATE OR REPLACE FUNCTION")
    candidate_end = generated.index("\nEND $$;", candidate_start) + len("\nEND $$;")
    assert generated[candidate_start:candidate_end].replace(generator.INSERTION, "") == original
    assert generated.count("ANALYZE ingestion.record") == 1
    assert generated.index("IF current_state='READY'") < generated.index("ANALYZE ingestion.record")
    assert "p.proconfig IS NULL" in generated and "NOT p.prosecdef" in generated
    assert "pg_get_function_result" in generated and "JOBKOREA_SEAL_CANONICAL_DRIFT" in generated
    # A new canonical admission rule survives generation and updates the guard.
    destination.write_text(canonical.replace("JOBKOREA_NDJSON_ROW_COUNT_LIMIT", "NEW_ROW_LIMIT"))
    changed = generator.build()
    assert "NEW_ROW_LIMIT" in changed and changed != generated


def test_installer_only_replay_preserves_other_workflows_and_aborts_on_each_sql_failure(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "hop/ingestions/jobkorea/tools"))
    build = module("jobkorea_installer_generator", ROOT / "hop/ingestions/jobkorea/tools/build.py")
    template = tmp_path / "hop/ontology/install.hwf"
    template.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "hop/ontology/install.hwf", template)
    output = tmp_path / "hop/ingestions/jobkorea"
    output.mkdir(parents=True)
    for name in ("full.hwf", "install_linking.hwf"):
        (output / name).write_bytes(b"preexisting unrelated workflow")
    build.ROOT, build.OUT = tmp_path, output
    build.build_installer()
    current = (output / "install.hwf").read_bytes()
    assert current == (ROOT / "hop/ingestions/jobkorea/install.hwf").read_bytes()
    build.build_installer()
    assert current == (output / "install.hwf").read_bytes()
    for name in ("full.hwf", "install_linking.hwf"):
        assert (output / name).read_bytes() == b"preexisting unrelated workflow"
    workflow = ET.fromstring(current)
    actions = [a for a in workflow.findall("actions/action") if a.findtext("type") == "SQL"]
    assert [a.findtext("sqlfilename") for a in actions] == [
        "${PROJECT_HOME}/ingestions/jobkorea/sql/" + name + ".sql"
        for name in (
            "001_schema",
            "002_operations",
            "003_checks",
            "004_integration",
            "005_shared_checks",
            "006_ndjson",
            "007_dataset_provenance",
            "008_ready_statistics",
        )
    ]
    next_names = [a.findtext("name") for a in actions[1:]] + [
        "Install shared graph evidence contracts"
    ]
    for action, successor in zip(actions, next_names, strict=True):
        name = action.findtext("name")
        assert (
            workflow.find(f"hops/hop[from='{name}'][to='{successor}'][evaluation='Y'][enabled='Y']")
            is not None
        )
        assert (
            workflow.find(f"hops/hop[from='{name}'][to='Abort'][evaluation='N'][enabled='Y']")
            is not None
        )
