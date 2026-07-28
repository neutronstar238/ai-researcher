from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.evidence import build_campaign_round_provenance
from autoresearch.reports import (
    ArtifactAccess,
    ArtifactTransform,
    Contributor,
    JsonAssertion,
    ResearchObjectArtifact,
    ResearchObjectMetadata,
    ResearchObjectView,
    export_open_science_research_object,
    run_clean_directory_reproduction,
    validate_open_science_view,
)
from autoresearch.schemas import file_hash

LIVE_ENV = "AUTORESEARCH_OPEN_SCIENCE_REAL"
CAMPAIGN_ENV = "AUTORESEARCH_OPEN_SCIENCE_CAMPAIGN"
OUTPUT_ENV = "AUTORESEARCH_OPEN_SCIENCE_OUTPUT"
DEFAULT_CAMPAIGN = "runs/manual-live/task260-autonomous-ccfb-v1"
ROUND_ID = "round-001"

pytestmark = pytest.mark.skipif(
    os.getenv(LIVE_ENV) != "1",
    reason=f"set {LIVE_ENV}=1 to export the validated task260 campaign round",
)


def _git_commit(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.stdout.strip()


def _artifact(
    round_dir: Path,
    filename: str,
    *,
    role: str,
    entity_id: str | None,
) -> ResearchObjectArtifact:
    source = round_dir / filename
    return ResearchObjectArtifact(
        source_path=source,
        crate_path=f"artifacts/{filename}",
        role=role,
        media_type="application/json",
        license_id="LicenseRef-Internal-Research",
        access=ArtifactAccess.REVIEW,
        provenance_entity_id=entity_id,
        expected_sha256=file_hash(source),
        transform=ArtifactTransform.SANITIZE_JSON,
        description=f"Validated {ROUND_ID} {role.replace('_', ' ')} artifact.",
    )


def test_real_campaign_round_exports_a_reviewable_research_object(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    campaign_dir = Path(os.getenv(CAMPAIGN_ENV, DEFAULT_CAMPAIGN)).resolve()
    if not campaign_dir.is_dir():
        pytest.fail(f"configured real campaign directory does not exist: {campaign_dir}")
    round_dir = campaign_dir / "rounds" / ROUND_ID
    if not round_dir.is_dir():
        pytest.fail(f"configured real campaign round does not exist: {round_dir}")
    output_root = Path(os.getenv(OUTPUT_ENV, str(tmp_path))).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    projection = build_campaign_round_provenance(campaign_dir, ROUND_ID)
    commit_sha = _git_commit(repo_root)
    artifacts = (
        _artifact(
            round_dir,
            "frozen_protocol.json",
            role="workflow_input",
            entity_id=(
                "entity.task260-autonomous-ccfb-v1.round-001.frozen-protocol"
            ),
        ),
        _artifact(
            round_dir,
            "preregistration.json",
            role="preregistration",
            entity_id=(
                "entity.task260-autonomous-ccfb-v1.round-001.preregistration"
            ),
        ),
        _artifact(
            round_dir,
            "unseen_evaluation.json",
            role="unseen_evaluation",
            entity_id=(
                "entity.task260-autonomous-ccfb-v1.round-001.unseen-evaluation"
            ),
        ),
        _artifact(
            round_dir,
            "contribution_gate.json",
            role="validation_gate",
            entity_id=(
                "entity.task260-autonomous-ccfb-v1.round-001.contribution-gate"
            ),
        ),
        _artifact(
            round_dir,
            "round_decision.json",
            role="decision",
            entity_id=(
                "entity.task260-autonomous-ccfb-v1.round-001.round-decision"
            ),
        ),
        _artifact(
            round_dir,
            "validation-report.json",
            role="validation_report",
            entity_id=None,
        ),
        _artifact(
            round_dir,
            "experiment-manifest.json",
            role="experiment_manifest",
            entity_id=None,
        ),
    )
    assertions = (
        JsonAssertion(
            "artifacts/contribution_gate.json",
            "/passed",
            False,
            "The deterministic contribution gate remains failed.",
        ),
        JsonAssertion(
            "artifacts/contribution_gate.json",
            "/checks/bootstrap_ci_lower_above_zero",
            False,
            "The preregistered confidence-bound gate remains failed.",
        ),
        JsonAssertion(
            "artifacts/contribution_gate.json",
            "/checks/three_ablations_complete",
            False,
            "The preregistered ablation-completeness gate remains failed.",
        ),
        JsonAssertion(
            "artifacts/unseen_evaluation.json",
            "/outcome",
            "negative_result",
            "Unseen evaluation remains a negative result.",
        ),
        JsonAssertion(
            "artifacts/round_decision.json",
            "/decision",
            "next_round",
            "The frozen decision remains next_round.",
        ),
        JsonAssertion(
            "artifacts/validation-report.json",
            "/passed",
            False,
            "Validation remains failed rather than being reinterpreted.",
        ),
    )
    metadata = ResearchObjectMetadata(
        identifier=(
            "urn:autoresearch:campaign:task260-autonomous-ccfb-v1:round-001"
        ),
        title="AutoResearch task260 campaign round-001 research object",
        description=(
            "A review/reproduction package for the validated negative-result "
            "campaign round. Metadata validation is not a scientific rerun."
        ),
        version="1.0.0",
        publisher="AutoResearch Team",
        published_at=datetime(2026, 7, 23, 15, 7, tzinfo=timezone.utc),
        license_id="Apache-2.0",
        repository_url=(
            "https://github.com/neutronstar238/ai-researcher-loop"
        ),
        commit_sha=commit_sha,
        swhid=f"swh:1:rev:{commit_sha}",
        contributors=(
            Contributor(
                family_names="AutoResearch Team",
                roles=("Software", "Methodology", "Validation"),
                affiliation="AutoResearch Team",
            ),
        ),
        keywords=(
            "open science",
            "negative results",
            "scientific machine learning",
        ),
    )

    exported = export_open_science_research_object(
        export_dir=output_root / "research-object",
        bundle=projection.bundle,
        metadata=metadata,
        artifacts=artifacts,
        reproduction_assertions=assertions,
        created_at=datetime(2026, 7, 29, 0, 0, tzinfo=timezone.utc),
    )
    internal_validation = validate_open_science_view(
        exported.internal.crate_dir,
        view=ResearchObjectView.INTERNAL,
    )
    review_validation = validate_open_science_view(
        exported.review.crate_dir,
        view=ResearchObjectView.REVIEW,
    )
    reproduction = run_clean_directory_reproduction(
        exported.review.crate_dir,
        clean_dir=output_root / "clean-review-reproduction",
    )

    assert projection.bundle.bundle_hash == (
        "a2e54556b3f6e242deeaff3d7c87400ae23e701ef034983fb6964a3c2df4c782"
    )
    assert internal_validation.status == "passed"
    assert review_validation.status == "passed"
    assert all(review_validation.checks.values())
    assert exported.public is None
    assert "explicit human publication approval is missing" in (
        exported.public_blocked_reasons
    )
    assert not (Path(exported.export_dir) / "public").exists()
    assert reproduction.status == "passed"
    assert reproduction.assertion_count == len(assertions)
    assert reproduction.scientific_experiment_reexecuted is False
    review_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in Path(exported.review.crate_dir).rglob("*")
        if path.is_file()
    )
    assert "E:/AIResearch" not in review_text
    assert "E:\\\\AIResearch" not in review_text
    assert not (
        Path(exported.review.crate_dir) / "internal/provenance-bundle.json"
    ).exists()

    (output_root / "smoke-summary.json").write_text(
        json.dumps(
            {
                "export": exported.to_dict(),
                "internal_validation": internal_validation.to_dict(),
                "review_validation": review_validation.to_dict(),
                "clean_reproduction": reproduction.to_dict(),
                "source_artifact_hashes": {
                    Path(artifact.source_path).name: artifact.expected_sha256
                    for artifact in artifacts
                },
                "source_bundle_hash": projection.bundle.bundle_hash,
                "public_view_created": False,
                "publication_performed": False,
                "metadata_interoperability_only": True,
                "scientific_experiment_reexecuted": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
