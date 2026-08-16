"""experiments and experiment runs

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "experiments",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("entrypoint", sa.Text(), nullable=False),
        sa.Column("container_image", sa.Text(), nullable=True),
        sa.Column("container_digest", sa.Text(), nullable=True),
        sa.Column("default_parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("resource_spec", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="draft", nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_experiments_created_by_users"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["cycle_id"], ["research_cycles.id"], name=op.f("fk_experiments_cycle_id_research_cycles"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_experiments_project_id_projects"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_experiments")),
        sa.UniqueConstraint("cycle_id", "code", name="uq_experiments_cycle_code"),
    )

    op.create_table(
        "experiment_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("experiment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="queued", nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("code_sha256", sa.String(length=64), nullable=True),
        sa.Column("image_digest", sa.Text(), nullable=True),
        sa.Column("random_seed", sa.Integer(), nullable=True),
        sa.Column("resource_request", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("runner_job_id", sa.String(length=160), nullable=True),
        sa.Column("log_output", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued','preparing','running','uploading_artifacts','succeeded','failed','cancelled')",
            name=op.f("ck_experiment_runs_status"),
        ),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiments.id"], name=op.f("fk_experiment_runs_experiment_id_experiments"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], name=op.f("fk_experiment_runs_requested_by_users"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_experiment_runs")),
        sa.UniqueConstraint("experiment_id", "run_no", name="uq_experiment_runs_no"),
    )


def downgrade() -> None:
    op.drop_table("experiment_runs")
    op.drop_table("experiments")
