"""experiment metrics, artifacts and datasets

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "experiment_metrics",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("step", sa.BigInteger(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["experiment_runs.id"], name=op.f("fk_experiment_metrics_run_id_experiment_runs"), ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "name", "step", name="uq_experiment_metrics_run_name_step"),
    )

    op.create_table(
        "experiment_artifacts",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], name=op.f("fk_experiment_artifacts_asset_id_assets"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["experiment_runs.id"], name=op.f("fk_experiment_artifacts_run_id_experiment_runs"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "asset_id", name=op.f("pk_experiment_artifacts")),
    )

    op.create_table(
        "datasets",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("license", sa.Text(), nullable=True),
        sa.Column("sensitivity", sa.String(length=24), server_default="internal", nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_datasets_created_by_users"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_datasets_project_id_projects"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_datasets")),
        sa.UniqueConstraint("project_id", "name", name="uq_datasets_project_name"),
    )

    op.create_table(
        "dataset_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("schema_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("statistics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("row_count", sa.BigInteger(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="ready", nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_dataset_versions_created_by_users"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], name=op.f("fk_dataset_versions_dataset_id_datasets"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dataset_versions")),
        sa.UniqueConstraint("dataset_id", "manifest_sha256", name="uq_dataset_versions_manifest"),
        sa.UniqueConstraint("dataset_id", "version_no", name="uq_dataset_versions_no"),
    )


def downgrade() -> None:
    op.drop_table("dataset_versions")
    op.drop_table("datasets")
    op.drop_table("experiment_artifacts")
    op.drop_table("experiment_metrics")
