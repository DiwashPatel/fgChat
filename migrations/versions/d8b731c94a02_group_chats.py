"""Allow named groups and track each group member's reading position.

Revision ID: d8b731c94a02
Revises: c4a6b92d10ef
"""

import sqlalchemy as sa
from alembic import op

revision = "d8b731c94a02"
down_revision = "c4a6b92d10ef"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("name", sa.String(80), nullable=True))
        batch.alter_column("user_a_id", existing_type=sa.Integer(), nullable=True)
        batch.alter_column("user_b_id", existing_type=sa.Integer(), nullable=True)
    op.add_column(
        "conversation_members",
        sa.Column("last_read_message_id", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    # The old schema cannot represent groups; don't silently delete their history.
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM conversations WHERE name IS NOT NULL")):
        raise RuntimeError("Cannot downgrade while group conversations exist.")
    with op.batch_alter_table("conversation_members") as batch:
        batch.drop_column("last_read_message_id")
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("name")
        batch.alter_column("user_a_id", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("user_b_id", existing_type=sa.Integer(), nullable=False)
