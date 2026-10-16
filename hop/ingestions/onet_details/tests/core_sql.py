"""Isolated actual PostgreSQL import/projection checks using the frozen full bundle."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location(
    "onet_core", ROOT / "hop/ingestions/onet/tests/core_sql.py"
)
assert spec and spec.loader
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bundle-dir", type=Path, required=True)
    args = p.parse_args()
    f = core.Fixture()
    try:
        f.boot()
        for path in sorted((ROOT / "hop/ingestions/onet_details/sql").glob("*.sql")):
            f.sql(path.read_text())
        raw = (args.bundle_dir / "base_catalogue.json").read_text()
        f.sql("SELECT classification.import_onet_catalog(" + core.quote(raw) + "::jsonb);")
        payload = json.loads((args.bundle_dir / "details.json").read_text())

        def statement(value):
            return (
                "SELECT onet_detail.import_onet_catalog("
                + core.quote(json.dumps(value))
                + "::jsonb,"
                + core.quote(raw)
                + ");"
            )

        bad = copy.deepcopy(payload)
        bad["release_id"] = "invalid-detail-endpoint"
        bad["edges"][0]["target_id"] = "urn:jobtology:onet-detail:element:absent"
        f.error(statement(bad), "ONET_DETAILS_INVALID_ENDPOINT")
        f.expect(
            f.sql("SELECT count(*) FROM onet_detail.catalog_release;") == "0",
            "atomic-failed-import",
        )
        bad = copy.deepcopy(payload)
        bad["release_id"] = "invalid-detail-kind"
        edge = next(e for e in bad["edges"] if e["type"] == "ONET_DETAIL_PARENT")
        edge["source_id"] = "urn:jobtology:onet:occupation:15-1252.00"
        f.error(statement(bad), "ONET_DETAILS_ENDPOINT_KIND_MISMATCH")
        f.sql(statement(payload))
        f.sql(statement(payload))
        f.expect(
            f.sql("SELECT count(*) FROM onet_detail.catalog_release;") == "1",
            "immutable-release-replay",
        )
        for entity in ("nodes", "edges"):
            count = f.sql(
                "SELECT count(*) FROM onet_detail.graph_"
                + entity
                + "("
                + core.quote(payload["release_id"])
                + ");"
            )
            f.expect(int(count) == len(payload[entity]), "complete-" + entity + "-projection")
        f.error("UPDATE onet_detail.node SET type='SOFTWARE';", "IMMUTABLE")
        bad = copy.deepcopy(payload)
        bad["nodes"][0]["properties"]["name"] = "changed"
        f.error(statement(bad), "ONET_DETAILS_RELEASE_REPLAY_CHANGED")
        print(json.dumps(dict(status="PASSED_ONET_DETAILS_CORE_SQL", checks=f.checks)))
    finally:
        f.command(["docker", "rm", "-fv", f.container])


if __name__ == "__main__":
    main()
