"""citations table

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "citations",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("citation_key", sa.String(length=80), nullable=False),
        sa.Column("style_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("anchors", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"], name=op.f("fk_citations_document_version_id_document_versions"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], name=op.f("fk_citations_paper_id_papers"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_citations")),
        sa.UniqueConstraint("document_version_id", "citation_key", name="uq_citations_version_key"),
    )


def downgrade() -> None:
    op.drop_table("citations")
