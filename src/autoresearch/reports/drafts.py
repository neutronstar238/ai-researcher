"""Version paper draft artifacts without overwriting previous drafts."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autoresearch.evidence import EvidenceGraph
from autoresearch.schemas import PaperDraft


class PaperDraftVersioningError(RuntimeError):
    """Raised when a paper draft version cannot be stored."""


@dataclass(frozen=True)
class PaperDraftVersion:
    """Stored paper draft version with manifest provenance."""

    draft: PaperDraft
    version: int
    version_dir: str
    tex_path: str
    manifest_path: str
    source_evidence_graph_version: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "draft": self.draft.model_dump(mode="json"),
            "version": self.version,
            "version_dir": self.version_dir,
            "tex_path": self.tex_path,
            "manifest_path": self.manifest_path,
            "source_evidence_graph_version": self.source_evidence_graph_version,
        }


def store_paper_draft_version(
    *,
    project_id: str,
    title: str,
    source_tex_path: Path | str,
    evidence_graph: EvidenceGraph,
    output_dir: Path | str,
    evidence_map_path: Path | str = "evidence-graph.json",
) -> PaperDraftVersion:
    """Copy a LaTeX draft into the next immutable version directory."""

    if not project_id:
        msg = "project_id is required"
        raise PaperDraftVersioningError(msg)
    if not title:
        msg = "title is required"
        raise PaperDraftVersioningError(msg)
    source_path = Path(source_tex_path).resolve()
    if not source_path.exists():
        msg = f"source LaTeX draft is missing: {source_path.as_posix()}"
        raise PaperDraftVersioningError(msg)

    root = Path(output_dir).resolve()
    versions_dir = root / "versions"
    versions_dir.mkdir(parents=True, exist_ok=True)
    version = _next_version(versions_dir)
    version_dir = versions_dir / f"v{version:04d}"
    version_dir.mkdir()
    version_tex_path = version_dir / source_path.name
    shutil.copy2(source_path, version_tex_path)

    evidence_map = Path(evidence_map_path).as_posix()
    draft = PaperDraft(
        project_id=project_id,
        title=title,
        draft_path=version_tex_path.as_posix(),
        evidence_map_path=evidence_map,
        version=version,
        metadata={
            "source_evidence_graph_version": evidence_graph.schema_version,
            "version_dir": version_dir.as_posix(),
        },
    )
    manifest_path = version_dir / "manifest.json"
    stored = PaperDraftVersion(
        draft=draft,
        version=version,
        version_dir=version_dir.as_posix(),
        tex_path=version_tex_path.as_posix(),
        manifest_path=manifest_path.as_posix(),
        source_evidence_graph_version=evidence_graph.schema_version,
    )
    manifest = {
        **stored.to_dict(),
        "stored_at": datetime.now(timezone.utc).isoformat(),
        "source_tex_path": source_path.as_posix(),
        "evidence_map_path": evidence_map,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (root / "latest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return stored


def _next_version(versions_dir: Path) -> int:
    versions = []
    for path in versions_dir.iterdir():
        if path.is_dir() and path.name.startswith("v"):
            try:
                versions.append(int(path.name[1:]))
            except ValueError:
                continue
    return max(versions, default=0) + 1
