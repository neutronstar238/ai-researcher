"""experiment run datasets binding

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "experiment_run_datasets",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mount_path", sa.Text(), nullable=False),
        sa.Column("access_mode", sa.String(length=12), server_default="read_only", nullable=False),
        sa.ForeignKeyConstraint(["dataset_version_id"], ["dataset_versions.id"], name=op.f("fk_experiment_run_datasets_dataset_version_id_dataset_versions"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["experiment_runs.id"], name=op.f("fk_experiment_run_datasets_run_id_experiment_runs"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "dataset_version_id", name=op.f("pk_experiment_run_datasets")),
        sa.UniqueConstraint("run_id", "mount_path", name="uq_run_datasets_mount"),
    )


def downgrade() -> None:
    op.drop_table("experiment_run_datasets")
