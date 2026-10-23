"""Add conversation memberships and backfill existing direct chats.

Revision ID: c4a6b92d10ef
Revises: f2fe16aeb3f9
"""

import sqlalchemy as sa
from alembic import op

revision = "c4a6b92d10ef"
down_revision = "f2fe16aeb3f9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "conversation_members",
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("conversation_id", "user_id"),
    )
    op.create_index(
        "ix_conversation_members_user", "conversation_members", ["user_id", "conversation_id"]
    )
    op.execute(
        sa.text("""
        INSERT INTO conversation_members (conversation_id, user_id)
        SELECT id, user_a_id FROM conversations
        UNION ALL
        SELECT id, user_b_id FROM conversations
    """)
    )


def downgrade():
    op.drop_index("ix_conversation_members_user", table_name="conversation_members")
    op.drop_table("conversation_members")
