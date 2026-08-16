"""lifecycle stages, transitions, actions and topic candidates

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lifecycle_stages",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stage_key", sa.String(length=32), nullable=False),
        sa.Column("ordinal", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("progress", sa.Numeric(5, 2), server_default="0", nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("gate_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("evidence_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("progress >= 0 AND progress <= 100", name=op.f("ck_lifecycle_stages_progress")),
        sa.CheckConstraint(
            "status IN ('pending','ready','running','waiting_approval','blocked','completed','failed','cancelled')",
            name=op.f("ck_lifecycle_stages_status"),
        ),
        sa.ForeignKeyConstraint(["cycle_id"], ["research_cycles.id"], name=op.f("fk_lifecycle_stages_cycle_id_research_cycles"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lifecycle_stages")),
        sa.UniqueConstraint("cycle_id", "ordinal", name="uq_lifecycle_stages_cycle_ordinal"),
        sa.UniqueConstraint("cycle_id", "stage_key", name="uq_lifecycle_stages_cycle_key"),
    )

    op.create_table(
        "stage_transition_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("stage_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=False),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("gate_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["stage_id"], ["lifecycle_stages.id"], name=op.f("fk_stage_transition_events_stage_id_lifecycle_stages"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stage_transition_events")),
    )

    op.create_table(
        "research_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stage_key", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="open", nullable=False),
        sa.Column("priority", sa.SmallInteger(), server_default="3", nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assignee_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_type", sa.String(length=20), nullable=True),
        sa.Column("source_agent_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("completed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion_note", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('open','in_progress','completed','cancelled')", name=op.f("ck_research_actions_status")),
        sa.ForeignKeyConstraint(["cycle_id"], ["research_cycles.id"], name=op.f("fk_research_actions_cycle_id_research_cycles"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_research_actions_project_id_projects"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_actions")),
    )

    op.create_table(
        "topic_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cycle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("research_question", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("novelty_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("evidence_strength", sa.Numeric(5, 2), nullable=True),
        sa.Column("risk_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="proposed", nullable=False),
        sa.Column("similar_work_summary", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["cycle_id"], ["research_cycles.id"], name=op.f("fk_topic_candidates_cycle_id_research_cycles"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_topic_candidates_project_id_projects"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_topic_candidates")),
    )


def downgrade() -> None:
    op.drop_table("topic_candidates")
    op.drop_table("research_actions")
    op.drop_table("stage_transition_events")
    op.drop_table("lifecycle_stages")
