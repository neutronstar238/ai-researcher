"""Markdown knowledge entries with YAML frontmatter."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from pydantic import BaseModel, ConfigDict, Field

WIKI_LINK_PATTERN = re.compile(r"\[\[([^\]|\n]+)(?:\|([^\]\n]+))?\]\]")


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


def extract_wiki_links(markdown_body: str) -> list[str]:
    """Return Obsidian wiki-link targets from Markdown body text."""

    return sorted({match.group(1).strip() for match in WIKI_LINK_PATTERN.finditer(markdown_body)})


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
    links: list[str] = Field(default_factory=list)
    backlinks: list[str] = Field(default_factory=list)
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
        entry.links = extract_wiki_links(entry.body)
        path.write_text(entry.to_markdown(), encoding="utf-8")
        self.rebuild_indexes()
        return path

    def read_entry(self, relative_path: Path | str) -> KnowledgeEntry:
        path = self.root / relative_path
        return KnowledgeEntry.from_markdown(path.read_text(encoding="utf-8"))

    def find_by_keyword(self, keyword: str) -> list[KnowledgeEntry]:
        normalized_keyword = keyword.casefold()
        entries = self._read_all_entries()
        return [
            entry
            for _, entry in entries.items()
            if normalized_keyword in {item.casefold() for item in entry.keywords}
        ]

    def rebuild_indexes(self) -> None:
        entries = self._read_all_entries()
        path_by_key: dict[str, Path] = {}
        for path, entry in entries.items():
            relative_path = path.relative_to(self.root).as_posix()
            path_by_key[entry.entry_id] = path
            path_by_key[relative_path] = path
            if relative_path.endswith(".md"):
                path_by_key[relative_path.removesuffix(".md")] = path

        backlinks: dict[Path, set[str]] = {path: set() for path in entries}
        for path, entry in entries.items():
            entry.links = extract_wiki_links(entry.body)
            for target in entry.links:
                target_path = path_by_key.get(target)
                if target_path is not None and target_path != path:
                    backlinks[target_path].add(entry.entry_id)

        for path, entry in entries.items():
            entry.backlinks = sorted(backlinks[path])
            path.write_text(entry.to_markdown(), encoding="utf-8")

        self._write_topic_index(entries)

    def _read_all_entries(self) -> dict[Path, KnowledgeEntry]:
        entries: dict[Path, KnowledgeEntry] = {}
        if not self.root.exists():
            return entries

        for path in sorted(self.root.rglob("*.md")):
            try:
                entries[path] = KnowledgeEntry.from_markdown(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
        return entries

    def _write_topic_index(self, entries: dict[Path, KnowledgeEntry]) -> None:
        topics: dict[str, list[KnowledgeEntry]] = {}
        for entry in entries.values():
            for keyword in entry.keywords:
                topics.setdefault(keyword.casefold(), []).append(entry)

        index_path = self.root / "exploration" / "index.md"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# Topic Index", ""]
        for keyword in sorted(topics):
            lines.extend([f"## {keyword}", ""])
            for entry in sorted(topics[keyword], key=lambda item: item.title.casefold()):
                lines.append(f"- [[{entry.entry_id}|{entry.title}]]")
            lines.append("")

        index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
