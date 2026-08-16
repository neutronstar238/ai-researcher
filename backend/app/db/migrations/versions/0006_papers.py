"""papers and project papers

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "papers",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("doi", postgresql.CITEXT(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("publication_year", sa.SmallInteger(), nullable=True),
        sa.Column("venue", sa.Text(), nullable=True),
        sa.Column("publication_date", sa.Date(), nullable=True),
        sa.Column("external_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("citation_count", sa.Integer(), nullable=True),
        sa.Column("metadata_source", sa.String(length=40), nullable=True),
        sa.Column("raw_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_papers")),
        sa.UniqueConstraint("doi", name=op.f("uq_papers_doi")),
    )

    op.create_table(
        "project_papers",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="saved", nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("added_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["added_by"], ["users.id"], name=op.f("fk_project_papers_added_by_users"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], name=op.f("fk_project_papers_paper_id_papers"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_project_papers_project_id_projects"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_papers")),
        sa.UniqueConstraint("project_id", "paper_id", name="uq_project_papers_project_paper"),
    )


def downgrade() -> None:
    op.drop_table("project_papers")
    op.drop_table("papers")
