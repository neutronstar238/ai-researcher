import json
from pathlib import Path

import pytest

from autoresearch.evidence import EvidenceGraph
from autoresearch.reports import PaperDraftVersioningError, store_paper_draft_version


def test_store_paper_draft_version_preserves_previous_versions(tmp_path: Path) -> None:
    source_tex = tmp_path / "main.tex"
    source_tex.write_text("Version one\n", encoding="utf-8")
    evidence_graph = EvidenceGraph(schema_version=7)

    first = store_paper_draft_version(
        project_id="project-001",
        title="Demo Draft",
        source_tex_path=source_tex,
        evidence_graph=evidence_graph,
        output_dir=tmp_path / "paper",
        evidence_map_path="evidence/evidence-graph.json",
    )
    source_tex.write_text("Version two\n", encoding="utf-8")
    second = store_paper_draft_version(
        project_id="project-001",
        title="Demo Draft",
        source_tex_path=source_tex,
        evidence_graph=evidence_graph,
        output_dir=tmp_path / "paper",
        evidence_map_path="evidence/evidence-graph.json",
    )

    first_manifest = json.loads(Path(first.manifest_path).read_text(encoding="utf-8"))
    latest = json.loads((tmp_path / "paper" / "latest.json").read_text(encoding="utf-8"))
    assert first.version == 1
    assert second.version == 2
    assert Path(first.tex_path).read_text(encoding="utf-8") == "Version one\n"
    assert Path(second.tex_path).read_text(encoding="utf-8") == "Version two\n"
    assert first_manifest["source_evidence_graph_version"] == 7
    assert first_manifest["draft"]["metadata"]["source_evidence_graph_version"] == 7
    assert latest["version"] == 2
    assert latest["tex_path"] == second.tex_path


def test_store_paper_draft_version_rejects_missing_source(tmp_path: Path) -> None:
    with pytest.raises(PaperDraftVersioningError, match="missing"):
        store_paper_draft_version(
            project_id="project-001",
            title="Demo Draft",
            source_tex_path=tmp_path / "missing.tex",
            evidence_graph=EvidenceGraph(),
            output_dir=tmp_path / "paper",
        )
