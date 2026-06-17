"""Markdown knowledge entries with YAML frontmatter."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

WIKI_LINK_PATTERN = re.compile(r"\[\[([^\]|\n]+)(?:\|([^\]\n]+))?\]\]")
_TOPIC_INDEX_STOPWORDS = frozenset(
    {
        "a",
        "add",
        "adds",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "give",
        "gives",
        "in",
        "into",
        "is",
        "large",
        "need",
        "of",
        "on",
        "or",
        "second",
        "the",
        "to",
        "with",
    }
)
_FILE_ARTIFACT_PATTERN = re.compile(
    r"(?:^|[\s/\\])[\w.-]+\.(?:csv|json|jsonl|lock|md|pdf|txt|yaml|yml)\b"
)
_LONG_DIGIT_PATTERN = re.compile(r"\d{8,}")
_MAX_TOPIC_KEYWORD_LENGTH = 96
_WORD_PATTERN = re.compile(r"[a-z0-9]+")


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
    RESEARCH_CANDIDATE = "research_candidate"
    RESEARCH_PLAN = "research_plan"


class KnowledgeZone(str, Enum):
    EXPLORATION = "exploration"
    PROJECT = "project"


@dataclass(frozen=True)
class VersionSnapshot:
    """Markdown snapshot for a knowledge entry version."""

    version: int
    path: Path
    created_at: datetime
    content: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def extract_wiki_links(markdown_body: str) -> list[str]:
    """Return Obsidian wiki-link targets from Markdown body text."""

    return sorted({match.group(1).strip() for match in WIKI_LINK_PATTERN.finditer(markdown_body)})


def _topic_index_keyword(keyword: str) -> str | None:
    normalized = re.sub(r"\s+", " ", keyword.strip()).casefold()
    if not normalized:
        return None

    words = _WORD_PATTERN.findall(normalized)
    if _looks_like_file_artifact(normalized) or _looks_like_operational_slug(
        normalized, words
    ):
        return None
    normalized = re.sub(r"_+", " ", normalized)
    if len(normalized) > _MAX_TOPIC_KEYWORD_LENGTH:
        return None
    words = _WORD_PATTERN.findall(normalized)
    if words and all(word in _TOPIC_INDEX_STOPWORDS for word in words):
        return None
    return normalized


def _looks_like_file_artifact(value: str) -> bool:
    return bool(_FILE_ARTIFACT_PATTERN.search(value))


def _looks_like_operational_slug(value: str, words: list[str]) -> bool:
    if _LONG_DIGIT_PATTERN.search(value):
        return True
    if value.startswith(("autopilot_", "candidate_", "cycle_", "run_")) and any(
        any(character.isdigit() for character in word) for word in words
    ):
        return True
    if value.startswith(("autopilot_", "candidate_")):
        return True
    return value.count("_") >= 3 and any(word.startswith("task") for word in words)


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
        self.version_root = self.root / ".versions"
        self.backup_root = self.root / ".backups"

    def write_entry(self, relative_path: Path | str, entry: KnowledgeEntry) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            self._preserve_version(relative_path, path.read_text(encoding="utf-8"))
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

        links_by_path: dict[Path, list[str]] = {}
        backlinks: dict[Path, set[str]] = {path: set() for path in entries}
        for path, entry in entries.items():
            links_by_path[path] = extract_wiki_links(entry.body)
            for target in links_by_path[path]:
                target_path = path_by_key.get(target)
                if target_path is not None and target_path != path:
                    backlinks[target_path].add(entry.entry_id)

        for path, entry in entries.items():
            next_links = links_by_path[path]
            next_backlinks = sorted(backlinks[path])
            if entry.links != next_links or entry.backlinks != next_backlinks:
                entry.links = next_links
                entry.backlinks = next_backlinks
                path.write_text(entry.to_markdown(), encoding="utf-8")
            else:
                entry.links = next_links
                entry.backlinks = next_backlinks

        self._write_topic_index(entries)

    def _read_all_entries(self) -> dict[Path, KnowledgeEntry]:
        entries: dict[Path, KnowledgeEntry] = {}
        if not self.root.exists():
            return entries

        for path in sorted(self.root.rglob("*.md")):
            if self._is_internal_path(path):
                continue
            try:
                entries[path] = KnowledgeEntry.from_markdown(path.read_text(encoding="utf-8"))
            except (ValueError, ValidationError):
                continue
        return entries

    def _write_topic_index(self, entries: dict[Path, KnowledgeEntry]) -> None:
        topics: dict[str, list[KnowledgeEntry]] = {}
        for entry in entries.values():
            for keyword in entry.keywords:
                topic = _topic_index_keyword(keyword)
                if topic is not None:
                    topics.setdefault(topic, []).append(entry)

        index_path = self.root / "exploration" / "index.md"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# Topic Index", ""]
        for keyword in sorted(topics):
            lines.extend([f"## {keyword}", ""])
            for entry in sorted(topics[keyword], key=lambda item: item.title.casefold()):
                lines.append(f"- [[{entry.entry_id}|{entry.title}]]")
            lines.append("")

        index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def list_versions(self, relative_path: Path | str) -> list[VersionSnapshot]:
        snapshots = self._saved_versions(relative_path)
        current_path = self.root / relative_path
        if current_path.exists():
            snapshots.append(
                VersionSnapshot(
                    version=len(snapshots) + 1,
                    path=current_path,
                    created_at=datetime.fromtimestamp(current_path.stat().st_mtime, timezone.utc),
                    content=current_path.read_text(encoding="utf-8"),
                )
            )
        return snapshots

    def rollback(self, relative_path: Path | str, version: int) -> Path:
        snapshots = self.list_versions(relative_path)
        selected = next((snapshot for snapshot in snapshots if snapshot.version == version), None)
        if selected is None:
            msg = f"version {version} does not exist for {Path(relative_path).as_posix()}"
            raise ValueError(msg)

        target = self.root / relative_path
        if target.exists() and target != selected.path:
            self._preserve_version(relative_path, target.read_text(encoding="utf-8"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(selected.content, encoding="utf-8")
        self.rebuild_indexes()
        return target

    def backup_if_due(
        self, interval_hours: int, *, now: datetime | None = None
    ) -> Path | None:
        if not 1 <= interval_hours <= 26:
            msg = "backup interval must be between 1 and 26 hours"
            raise ValueError(msg)

        timestamp = now or _utc_now()
        latest = self._latest_backup_time()
        if latest is not None and (timestamp - latest).total_seconds() < interval_hours * 3600:
            return None

        backup_path = self.backup_root / timestamp.strftime("%Y%m%dT%H%M%SZ")
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            self.root,
            backup_path,
            ignore=shutil.ignore_patterns(".backups"),
            dirs_exist_ok=False,
        )
        return backup_path

    def _preserve_version(self, relative_path: Path | str, content: str) -> Path:
        version = len(self._saved_versions(relative_path)) + 1
        path = self._version_dir(relative_path) / f"v{version:04d}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        metadata = yaml.safe_dump(
            {
                "source_path": Path(relative_path).as_posix(),
                "version": version,
                "created_at": _utc_now().isoformat(),
            },
            sort_keys=True,
        )
        path.write_text(f"---\n{metadata}---\n\n{content}", encoding="utf-8")
        return path

    def _saved_versions(self, relative_path: Path | str) -> list[VersionSnapshot]:
        version_dir = self._version_dir(relative_path)
        snapshots: list[VersionSnapshot] = []
        if not version_dir.exists():
            return snapshots

        for path in sorted(version_dir.glob("v*.md")):
            metadata, content = self._read_version_file(path)
            snapshots.append(
                VersionSnapshot(
                    version=int(metadata["version"]),
                    path=path,
                    created_at=datetime.fromisoformat(str(metadata["created_at"])),
                    content=content,
                )
            )
        return snapshots

    def _version_dir(self, relative_path: Path | str) -> Path:
        source = Path(relative_path)
        return self.version_root.joinpath(*source.with_suffix("").parts)

    def _read_version_file(self, path: Path) -> tuple[dict[str, Any], str]:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            msg = f"version file missing frontmatter: {path}"
            raise ValueError(msg)
        _, metadata_text, content = text.split("---\n", 2)
        metadata = yaml.safe_load(metadata_text) or {}
        if not isinstance(metadata, dict):
            msg = f"version metadata must be a mapping: {path}"
            raise ValueError(msg)
        if content.startswith("\n"):
            content = content[1:]
        return metadata, content

    def _latest_backup_time(self) -> datetime | None:
        if not self.backup_root.exists():
            return None

        timestamps: list[datetime] = []
        for path in self.backup_root.iterdir():
            if path.is_dir():
                try:
                    timestamps.append(
                        datetime.strptime(path.name, "%Y%m%dT%H%M%SZ").replace(
                            tzinfo=timezone.utc
                        )
                    )
                except ValueError:
                    continue
        return max(timestamps) if timestamps else None

    def _is_internal_path(self, path: Path) -> bool:
        relative = path.relative_to(self.root)
        return any(part.startswith(".") or part == "_system" for part in relative.parts)
