"""documents, versions and claims

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("document_type", sa.String(length=32), server_default="manuscript", nullable=False),
        sa.Column("status", sa.String(length=24), server_default="draft", nullable=False),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_documents_created_by_users"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["cycle_id"], ["research_cycles.id"], name=op.f("fk_documents_cycle_id_research_cycles"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_documents_project_id_projects"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )

    op.create_table(
        "document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=False),
        sa.Column("structure", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("source_agent_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_document_versions_created_by_users"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name=op.f("fk_document_versions_document_id_documents"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_versions")),
        sa.UniqueConstraint("document_id", "version_no", name="uq_document_versions_no"),
    )

    op.create_table(
        "document_claims",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("anchor", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("support_status", sa.String(length=24), server_default="supports", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"], name=op.f("fk_document_claims_document_version_id_document_versions"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_node_id"], ["evidence_nodes.id"], name=op.f("fk_document_claims_evidence_node_id_evidence_nodes"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_claims")),
    )


def downgrade() -> None:
    op.drop_table("document_claims")
    op.drop_table("document_versions")
    op.drop_table("documents")
