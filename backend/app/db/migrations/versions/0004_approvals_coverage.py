"""approvals, approval decisions and coverage snapshots

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approval_type", sa.String(length=80), nullable=False),
        sa.Column("subject_type", sa.String(length=80), nullable=True),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("risk_level", sa.String(length=20), server_default="medium", nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=True),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_to", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('pending','approved','rejected','cancelled','expired')", name=op.f("ck_approvals_status")),
        sa.CheckConstraint("risk_level IN ('low','medium','high')", name=op.f("ck_approvals_risk_level")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_approvals_project_id_projects"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], name=op.f("fk_approvals_requested_by_users"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approvals")),
    )

    op.create_table(
        "approval_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("approval_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("decided_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("decision IN ('approved','rejected')", name=op.f("ck_approval_decisions_decision")),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"], name=op.f("fk_approval_decisions_approval_id_approvals"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], name=op.f("fk_approval_decisions_decided_by_users"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_decisions")),
    )

    op.create_table(
        "cycle_coverage_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period_index", sa.SmallInteger(), nullable=False),
        sa.Column("label", sa.String(length=16), nullable=False),
        sa.Column("coverage", sa.Numeric(5, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_cycle_coverage_snapshots_project_id_projects"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cycle_coverage_snapshots")),
        sa.UniqueConstraint("project_id", "period_index", name="uq_coverage_project_period"),
    )


def downgrade() -> None:
    op.drop_table("cycle_coverage_snapshots")
    op.drop_table("approval_decisions")
    op.drop_table("approvals")
