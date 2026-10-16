"""Regenerated exact-run rules must track the canonical validation contracts."""

import importlib.util
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def generator(root: Path):
    path = ROOT / "hop/graph/tools/build_source_queries.py"
    spec = importlib.util.spec_from_file_location("source_query_generator", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = root
    module.OUTPUT = root / "hop/graph/sql/003_source_query_sharing.sql"
    return module


def test_generated_sql_is_current_and_deterministic(tmp_path: Path) -> None:
    for relative in (
        "docs/hop-migration/checks.sql",
        "docs/hop-migration/schema.sql",
        "hop/graph/sql/001_posting_ingestion_dates.sql",
        "hop/graph/sql/002_batchfree_source_graph.sql",
        "hop/ingestions/jobkorea/sql/003_checks.sql",
        "hop/ingestions/jobkorea/sql/006_ndjson.sql",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    build = generator(tmp_path)
    current = (ROOT / "hop/graph/sql/003_source_query_sharing.sql").read_text()
    assert build.build() == current
    assert build.build() == current
    # New shared and adapter rules cannot be omitted by an exact-run rewrite.
    shared = tmp_path / "docs/hop-migration/checks.sql"
    shared.write_text(shared.read_text().replace("'SMOKE_NOT_FULL'", "'NEW_SHARED_RULE'"))
    adapter = tmp_path / "hop/ingestions/jobkorea/sql/003_checks.sql"
    adapter.write_text(
        adapter.read_text().replace("'JOBKOREA_FILE_NOT_PROCESSED'", "'NEW_ADAPTER_RULE'")
    )
    changed = build.build()
    assert "NEW_SHARED_RULE" in changed and "NEW_ADAPTER_RULE" in changed
    assert "SMOKE_NOT_FULL" not in changed and "JOBKOREA_FILE_NOT_PROCESSED" not in changed


def test_dependency_inputs_remain_cross_run_and_definition_drift_uses_fresh_oracle() -> None:
    sql = (ROOT / "hop/graph/sql/003_source_query_sharing.sql").read_text()
    assert "FROM dependencies d JOIN ingestion.run u ON u.run_id = d.input_run_id" in sql
    assert "SOURCE_GRAPH_CANONICAL_VALIDATION_DRIFT" in sql
    assert "RETURN QUERY SELECT v.* FROM ingestion.validation_issue v WHERE v.run_id=jobs" in sql
    assert (
        "RETURN QUERY SELECT v.* FROM ingestion.local_file_validation_issue() v WHERE v.run_id=jobs"
        in sql
    )
    assert "__HOOK_HASH__" in sql and "__ND_HASH__" in sql and "__COLLISION_HASH__" in sql
    assert "CREATE TABLE" not in sql and "CREATE MATERIALIZED VIEW" not in sql
