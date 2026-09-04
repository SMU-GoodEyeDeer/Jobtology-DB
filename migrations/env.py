from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from jobtology_db.settings import Settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The fetch ledger currently uses SQL text rather than declarative models. Revisions are
# therefore explicit; there is no application metadata to autogenerate against yet.
target_metadata = None


def database_url() -> str:
    value = Settings().database_url()
    if value:
        return value

    configured = config.get_main_option("sqlalchemy.url").strip()
    if configured:
        return configured

    raise RuntimeError("Set JOBTOLOGY_PIPELINE_DATABASE_URL before running pipeline migrations")


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(database_url(), poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
