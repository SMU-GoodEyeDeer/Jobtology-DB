"""Neo4j constraint DDL. Applying it is an explicit deployment step, not a fetch side effect."""

from typing import get_args

from jobtology_db.contracts.canonical import EntityKind


def neo4j_constraints(*, include_person: bool = False) -> tuple[str, ...]:
    # CorpusEntity enforces cross-label ID uniqueness, not just uniqueness within one type.
    labels = ("CorpusEntity", *get_args(EntityKind))
    statements = [
        f"CREATE CONSTRAINT jt_{label.lower()}_id IF NOT EXISTS "
        f"FOR (n:{label}) REQUIRE n.jt_id IS UNIQUE"
        for label in labels
    ]
    for label, key in (
        ("EntityRevision", "revision_id"),
        ("EvidenceSpan", "evidence_id"),
        ("Assertion", "claim_id"),
        ("SourceDocument", "document_id"),
    ):
        statements.append(
            f"CREATE CONSTRAINT jt_{label.lower()}_id IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.{key} IS UNIQUE"
        )
    if include_person:
        statements.append(
            "CREATE CONSTRAINT jt_person_id IF NOT EXISTS "
            "FOR (n:Person) REQUIRE n.person_id IS UNIQUE"
        )
    return tuple(statements)
