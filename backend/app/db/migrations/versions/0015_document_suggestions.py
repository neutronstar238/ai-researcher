"""document suggestions table

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_suggestions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("base_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_section_key", sa.String(length=120), nullable=True),
        sa.Column("patch", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("rendered_preview", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("agent_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["base_version_id"], ["document_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_suggestions")),
    )
    op.create_index(
        "ix_document_suggestions_document_status",
        "document_suggestions",
        ["document_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_document_suggestions_document_status", table_name="document_suggestions")
    op.drop_table("document_suggestions")
