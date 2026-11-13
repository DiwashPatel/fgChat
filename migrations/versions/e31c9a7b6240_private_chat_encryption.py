"""Store public identity keys and opaque encrypted private messages.

Revision ID: e31c9a7b6240
Revises: d8b731c94a02
"""

import sqlalchemy as sa
from alembic import op

revision = "e31c9a7b6240"
down_revision = "d8b731c94a02"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("e2ee_public_key", sa.Text(), nullable=True))
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("encryption", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("client_message_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("encryption_iv", sa.String(16), nullable=True))
        batch.create_unique_constraint(
            "uq_message_sender_client_id", ["sender_id", "client_message_id"]
        )
        batch.create_unique_constraint(
            "uq_message_conversation_iv", ["conversation_id", "encryption_iv"]
        )


def downgrade():
    # Dropping ciphertext or enrolled identities would irreversibly lose access.
    bind = op.get_bind()
    if bind.scalar(
        sa.text("SELECT COUNT(*) FROM users WHERE e2ee_public_key IS NOT NULL")
    ) or bind.scalar(sa.text("SELECT COUNT(*) FROM messages WHERE client_message_id IS NOT NULL")):
        raise RuntimeError("Cannot downgrade while encryption keys or encrypted messages exist.")
    with op.batch_alter_table("messages") as batch:
        batch.drop_constraint("uq_message_conversation_iv", type_="unique")
        batch.drop_constraint("uq_message_sender_client_id", type_="unique")
        batch.drop_column("encryption_iv")
        batch.drop_column("client_message_id")
        batch.drop_column("encryption")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("e2ee_public_key")
    if bind.dialect.name == "sqlite":
        # SQLite batch recreation cannot reflect expression indexes. Restore the
        # account uniqueness protections instead of silently dropping them.
        op.create_index(
            "uq_users_username_lower", "users", [sa.text("lower(username)")], unique=True
        )
        op.create_index(
            "uq_users_email_lower",
            "users",
            [sa.text("lower(email)")],
            unique=True,
            sqlite_where=sa.text("email IS NOT NULL"),
        )
