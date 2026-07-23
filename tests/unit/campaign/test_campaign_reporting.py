from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from autoresearch.campaign import (
    AutonomousResearchCampaign,
    CampaignExporter,
    CampaignIntegrityError,
    CampaignOutcome,
    CampaignResult,
    load_campaign_manifest,
    load_round_manifest,
)
from autoresearch.campaign.cli import _development_campaign_spec, _parse_deadline
from autoresearch.campaign.development import DevelopmentFixtureCampaignAdapter
from autoresearch.campaign.reporting import _resolve_path as resolve_report_path
from autoresearch.campaign.service import _resolve_artifact_path
from autoresearch.cli.main import app

runner = CliRunner()


def test_date_only_deadline_uses_fixed_shanghai_offset() -> None:
    deadline = _parse_deadline("2026-08-15")
    offset = deadline.utcoffset()

    assert deadline.isoformat() == "2026-08-15T23:59:59+08:00"
    assert offset is not None
    assert offset.total_seconds() == 8 * 60 * 60


def test_managed_artifacts_cannot_escape_campaign_directory(tmp_path: Path) -> None:
    campaign_dir = tmp_path / "campaign"
    campaign_dir.mkdir()

    with pytest.raises(
        CampaignIntegrityError,
        match="escapes the campaign directory",
    ):
        _resolve_artifact_path(campaign_dir, "../outside.json")
    with pytest.raises(ValueError, match="escapes the campaign directory"):
        resolve_report_path(campaign_dir, "../outside.json")


def _run_development_campaign(tmp_path: Path) -> tuple[Path, CampaignResult]:
    output_root = tmp_path / "runs"
    spec = _development_campaign_spec(
        campaign_id="task260-reporting",
        project_id="task260-reporting",
        deadline=datetime(2099, 8, 15, tzinfo=timezone.utc),
        adapter_id=DevelopmentFixtureCampaignAdapter.adapter_id,
    )
    service = AutonomousResearchCampaign(
        adapter=DevelopmentFixtureCampaignAdapter(
            output_root / spec.campaign_id / "adapter-evidence"
        ),
        output_root=output_root,
        vault_root=tmp_path / "vault",
    )
    result = service.run(spec)
    return Path(result.campaign_dir), result


def test_round_reports_and_complete_local_export_are_visible(tmp_path: Path) -> None:
    unrelated_index = tmp_path / "vault" / "exploration" / "index.md"
    unrelated_index.parent.mkdir(parents=True)
    unrelated_index.write_text("# Unrelated knowledge\n", encoding="utf-8")
    project_index = tmp_path / "vault" / "projects" / "task260-reporting" / "index.md"
    project_index.parent.mkdir(parents=True)
    project_index.write_text(
        "# Existing project\n\nKeep this project context.\n",
        encoding="utf-8",
    )
    campaign_dir, result = _run_development_campaign(tmp_path)

    assert unrelated_index.read_text(encoding="utf-8") == "# Unrelated knowledge\n"
    project_index_text = project_index.read_text(encoding="utf-8")
    assert "Keep this project context." in project_index_text
    assert project_index_text.count(
        "<!-- AUTORESEARCH-CAMPAIGN:task260-reporting:START -->"
    ) == 1
    assert "[[task260-reporting-round-001]]" in project_index_text
    assert "[[task260-reporting-round-002]]" in project_index_text
    assert result.outcome is CampaignOutcome.STOPPED
    assert result.completed_round_count == 2
    assert result.experimental_round_count == 2
    manifest = load_campaign_manifest(campaign_dir / "campaign-manifest.json")
    required = {
        "hypothesis_report",
        "experiment_manifest",
        "metrics",
        "validation_report",
        "failure_analysis",
        "research_report",
        "loop_report",
        "metrics_table",
        "metrics_figure",
        "manuscript",
        "paper_build_status",
        "round_summary",
        "evidence_map",
    }
    rounds = [
        load_round_manifest(campaign_dir / path)
        for path in manifest.round_manifest_paths
    ]
    for round_manifest in rounds:
        assert required <= round_manifest.artifact_paths.keys()
        for name in required:
            assert (campaign_dir / round_manifest.artifact_paths[name]).is_file()
        evidence_map = json.loads(
            (campaign_dir / round_manifest.artifact_paths["evidence_map"]).read_text(
                encoding="utf-8"
            )
        )
        assert evidence_map["missing_adapter_evidence"] == []
        research_report = (
            campaign_dir / round_manifest.artifact_paths["research_report"]
        ).read_text(encoding="utf-8")
        assert "## Evidence boundary" in research_report
        assert "does not claim acceptance" in research_report

    export = CampaignExporter().export(campaign_dir, tmp_path / "outputs")
    deliverables = Path(export.deliverables_dir)
    assert Path(export.index_path).is_file()
    assert Path(export.manifest_path).is_file()
    assert (deliverables / "EXPORT-BLOCKED.md").is_file()
    assert (deliverables / "campaign-report.md").is_file()
    assert (deliverables / "environment-lock.json").is_file()
    assert (deliverables / "reproduce.ps1").is_file()
    assert "poetry run airesearcher campaign status" in (
        deliverables / "reproduce.ps1"
    ).read_text(encoding="utf-8")
    assert "Get-FileHash -Algorithm SHA256" in (
        deliverables / "reproduce.ps1"
    ).read_text(encoding="utf-8")
    assert list((deliverables / "campaign" / "rounds").rglob("research-report.md"))
    assert list((deliverables / "campaign" / "rounds").rglob("*unseen-metrics.json"))
    index = Path(export.index_path).read_text(encoding="utf-8")
    assert "Research report" in index
    assert "Evidence map" in index
    assert "External submission authorized: `false`" in index
    export_manifest = json.loads(Path(export.manifest_path).read_text(encoding="utf-8"))
    assert export_manifest["external_submission_authorized"] is False
    assert len(export_manifest["files"]) == export.file_count - 1


def test_export_rejects_tampered_round_report(tmp_path: Path) -> None:
    campaign_dir, _ = _run_development_campaign(tmp_path)
    manifest = load_campaign_manifest(campaign_dir / "campaign-manifest.json")
    first = load_round_manifest(campaign_dir / manifest.round_manifest_paths[0])
    report_path = campaign_dir / first.artifact_paths["research_report"]
    report_path.write_text("tampered report\n", encoding="utf-8")

    with pytest.raises(CampaignIntegrityError, match="research_report file hash mismatch"):
        CampaignExporter().export(campaign_dir, tmp_path / "outputs")


def test_campaign_cli_start_status_resume_and_export(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    vault_root = tmp_path / "vault"
    campaign_id = "task260-cli"
    start = runner.invoke(
        app,
        [
            "campaign",
            "start",
            "--campaign-id",
            campaign_id,
            "--deadline",
            "2099-08-15",
            "--output-dir",
            str(output_root),
            "--vault",
            str(vault_root),
        ],
    )
    assert start.exit_code == 0, start.output
    assert "outcome=stopped" in start.output
    assert "experimental_round_count=2" in start.output
    assert "[BOUNDARY] development fixture only" in start.output

    campaign_dir = output_root / campaign_id
    status = runner.invoke(app, ["campaign", "status", str(campaign_dir)])
    assert status.exit_code == 0, status.output
    assert "outcome=stopped" in status.output
    resume = runner.invoke(
        app,
        ["campaign", "resume", str(campaign_dir), "--vault", str(vault_root)],
    )
    assert resume.exit_code == 0, resume.output
    assert "completed_round_count=2" in resume.output

    export_root = tmp_path / "outputs"
    export = runner.invoke(
        app,
        [
            "campaign",
            "export",
            str(campaign_dir),
            "--output-dir",
            str(export_root),
        ],
    )
    assert export.exit_code == 0, export.output
    assert "[BLOCKED] external_submission_authorized=false" in export.output
    assert (
        export_root / campaign_id / "deliverables" / "index.md"
    ).is_file()
