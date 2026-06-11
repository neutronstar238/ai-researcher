"""Markdown knowledge entries with YAML frontmatter."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from pydantic import BaseModel, ConfigDict, Field


class KnowledgeEntryType(str, Enum):
    PAPER_NOTE = "paper_note"
    DATASET_CARD = "dataset_card"
    METHOD_CARD = "method_card"
    EXPERIMENT_RECORD = "experiment_record"
    FAILURE_CASE = "failure_case"
    SKILL_CARD = "skill_card"
    STRATEGY_CARD = "strategy_card"
    EVIDENCE_NOTE = "evidence_note"
    PROJECT_PROGRESS = "project_progress"
    ISSUE_NOTE = "issue_note"
    REVIEW_NOTE = "review_note"


class KnowledgeZone(str, Enum):
    EXPLORATION = "exploration"
    PROJECT = "project"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class KnowledgeEntry(BaseModel):
    """Obsidian-readable Markdown knowledge entry."""

    model_config = ConfigDict(extra="forbid")

    entry_id: str = Field(default_factory=lambda: f"entry_{uuid4().hex}")
    entry_type: KnowledgeEntryType
    zone: KnowledgeZone
    title: str = Field(min_length=1)
    project_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    related_task_ids: list[str] = Field(default_factory=list)
    related_run_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    body: str = ""

    def frontmatter(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"body"})

    def to_markdown(self) -> str:
        frontmatter = yaml.safe_dump(
            self.frontmatter(),
            allow_unicode=True,
            sort_keys=True,
        )
        body = self.body.rstrip()
        return f"---\n{frontmatter}---\n\n{body}\n"

    @classmethod
    def from_markdown(cls, text: str) -> KnowledgeEntry:
        if not text.startswith("---\n"):
            msg = "Knowledge entry Markdown must start with YAML frontmatter."
            raise ValueError(msg)

        try:
            _, frontmatter_text, body = text.split("---\n", 2)
        except ValueError as exc:
            msg = "Knowledge entry Markdown must contain closing frontmatter delimiter."
            raise ValueError(msg) from exc

        frontmatter = yaml.safe_load(frontmatter_text) or {}
        if not isinstance(frontmatter, dict):
            msg = "Knowledge entry frontmatter must be a YAML mapping."
            raise ValueError(msg)

        if body.startswith("\n"):
            body = body[1:]

        payload = {**frontmatter, "body": body.rstrip("\n")}
        return cls.model_validate(payload)


class MarkdownKnowledgeStore:
    """Read and write knowledge entries as plain Markdown files."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def write_entry(self, relative_path: Path | str, entry: KnowledgeEntry) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(entry.to_markdown(), encoding="utf-8")
        return path

    def read_entry(self, relative_path: Path | str) -> KnowledgeEntry:
        path = self.root / relative_path
        return KnowledgeEntry.from_markdown(path.read_text(encoding="utf-8"))
