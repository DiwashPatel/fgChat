from logging.config import fileConfig

from alembic import context
from flask import current_app

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

migration = current_app.extensions["migrate"]
database = migration.db
config.set_main_option(
    "sqlalchemy.url",
    str(database.engine.url).replace("%", "%%"),
)
target_metadata = database.metadata


def process_revision_directives(migration_context, revision, directives):
    if not getattr(config.cmd_opts, "autogenerate", False):
        return
    script = directives[0]
    if script.upgrade_ops.is_empty():
        directives[:] = []


def run_migrations_offline():
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    configure_args = dict(migration.configure_args)
    configure_args.setdefault("process_revision_directives", process_revision_directives)
    with database.engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, **configure_args)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
