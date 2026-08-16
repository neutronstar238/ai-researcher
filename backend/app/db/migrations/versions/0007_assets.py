"""assets table

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("bucket", sa.String(length=80), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("original_name", sa.Text(), nullable=True),
        sa.Column("mime_type", sa.String(length=160), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="ready", nullable=False),
        sa.Column("scan_status", sa.String(length=24), server_default="not_scanned", nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_assets_created_by_users"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_assets_project_id_projects"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], name=op.f("fk_assets_team_id_teams"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assets")),
        sa.UniqueConstraint("bucket", "object_key", name="uq_assets_bucket_key"),
    )


def downgrade() -> None:
    op.drop_table("assets")
