"""Offline schema inspection. No credentials, filesystem writes or database calls."""

import json

import typer
from pydantic import BaseModel

from jobtology_db.contracts.bundle import CanonicalBundle
from jobtology_db.contracts.canonical import (
    EntityIdentity,
    EntityRevision,
    ExamSession,
    JobPosting,
    NCSClass,
    NCSCompetencyUnit,
    Occupation,
    Organization,
)
from jobtology_db.contracts.documents import EvidenceSpan, SourceDocument
from jobtology_db.contracts.person import PersonProjection
from jobtology_db.contracts.requirements import ExtractionOutput, RequirementClaim
from jobtology_db.storage.ontology_schema import neo4j_constraints

schema_app = typer.Typer(help="Inspect versioned canonical contracts offline", no_args_is_help=True)
CONTRACTS: dict[str, type[BaseModel]] = {
    "exam-session": ExamSession,
    "bundle": CanonicalBundle,
    "identity": EntityIdentity,
    "revision": EntityRevision,
    "occupation": Occupation,
    "ncs-class": NCSClass,
    "ncs-unit": NCSCompetencyUnit,
    "job-posting": JobPosting,
    "organization": Organization,
    "person": PersonProjection,
    "source-document": SourceDocument,
    "evidence": EvidenceSpan,
    "extraction-output": ExtractionOutput,
    "requirement-claim": RequirementClaim,
}


@schema_app.command("list")
def list_contracts() -> None:
    for name in CONTRACTS:
        typer.echo(name)


@schema_app.command("show")
def show_contract(name: str) -> None:
    model = CONTRACTS.get(name)
    if model is None:
        raise typer.BadParameter("Unknown contract; use `schema list`")
    typer.echo(json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2))


@schema_app.command("neo4j-ddl")
def show_neo4j_ddl(include_person: bool = typer.Option(False, "--include-person")) -> None:
    for statement in neo4j_constraints(include_person=include_person):
        typer.echo(statement + ";")
