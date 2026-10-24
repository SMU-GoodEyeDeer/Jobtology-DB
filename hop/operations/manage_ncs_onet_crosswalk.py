#!/usr/bin/env python3
"""Review local, version-pinned catalogue crosswalks. Never calls a model/source URL."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

DSN_ENV = "JOBTOLOGY_ADMIN_POSTGRES_DSN"


def parser() -> argparse.ArgumentParser:
    app = argparse.ArgumentParser(description=__doc__)
    commands = app.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="Read proposals/reviews for an exact graph node")
    listing.add_argument("--node-id", required=True)
    listing.add_argument("--limit", type=int, default=20)
    listing.add_argument("--offset", type=int, default=0)
    proposal = commands.add_parser("propose", help="Freeze an evidenced comparison; no approval")
    proposal.add_argument("--source-id", required=True, help="NCS graph node ID")
    proposal.add_argument("--target-id", required=True, help="O*NET graph node ID")
    proposal.add_argument("--relation", choices=("RELATED", "PARTIAL", "EXACT"), required=True)
    proposal.add_argument("--evidence-file", type=Path, required=True)
    proposal.add_argument("--version", default="crosswalk-v1")
    review = commands.add_parser("review", help="Append a real individual review decision")
    review.add_argument("--mapping-id", required=True)
    review.add_argument("--decision", choices=("APPROVED", "REJECTED"), required=True)
    review.add_argument("--reviewer-kind", choices=("ASSISTANT", "HUMAN"), required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--note-file", type=Path, required=True)
    review.add_argument(
        "--expected-review-id",
        type=int,
        required=True,
        help="0 for a first review; otherwise the current review_id",
    )
    return app


def run(args: argparse.Namespace, dsn: str) -> Any:
    import psycopg
    from psycopg.types.json import Jsonb

    # Input contents and DSNs are not interpolated into SQL or exception output.
    params: tuple[Any, ...]
    if args.command == "list":
        query = "SELECT catalog.ncs_onet_crosswalk_v1(%s,%s,%s)"
        params = (args.node_id, args.limit, args.offset)
    elif args.command == "propose":
        if args.evidence_file.stat().st_size > 16000:
            raise ValueError("Evidence file exceeds 16 KB")
        evidence = json.loads(args.evidence_file.read_text())
        query = "SELECT catalog.propose_ncs_onet_mapping(%s,%s,%s,%s,%s)"
        params = (args.source_id, args.target_id, args.relation, Jsonb(evidence), args.version)
    else:
        if args.note_file.stat().st_size > 12000:
            raise ValueError("Review note exceeds 12 KB")
        query = "SELECT catalog.review_ncs_onet_mapping(%s,%s,%s,%s,%s,%s)"
        params = (
            args.mapping_id,
            args.decision,
            args.reviewer_kind,
            args.reviewer,
            args.note_file.read_text(),
            args.expected_review_id,
        )
    with psycopg.connect(dsn, connect_timeout=10) as connection, connection.transaction():
        connection.execute("SET LOCAL statement_timeout='30s'")
        if args.command == "list":
            connection.execute("SET TRANSACTION READ ONLY")
        row = connection.execute(query, params).fetchone()
        if row is None:
            raise RuntimeError("Crosswalk command returned no result")
        return row[0]


def main() -> None:
    app = parser()
    args = app.parse_args()
    dsn = os.environ.get(DSN_ENV)
    if not dsn:
        app.error(f"Set {DSN_ENV} to an admin connection; credentials are never printed")
    try:
        result = run(args, dsn)
    except Exception as exc:
        # Preserve bounded application error codes, never provider/connection text.
        message = str(getattr(getattr(exc, "diag", None), "message_primary", ""))
        prefixes = ("CROSSWALK_", "INVALID_CROSSWALK_", "STALE_CROSSWALK_")
        safe_code = message if message.startswith(prefixes) else "CROSSWALK_COMMAND_FAILED"
        app.exit(1, f"{safe_code}\n")
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
