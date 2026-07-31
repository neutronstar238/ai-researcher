from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.reports.open_science import (
    ArtifactAccess,
    ResearchObjectView,
    validate_open_science_view,
)
from autoresearch.research.systems_paper_currency_audit import SourceResponse
from autoresearch.research.systems_paper_open_science_overlay import (
    MANIFEST_FILENAME,
    PROFILE_VALIDATION_FILENAME,
    SOURCE_REGISTRY_FILENAME,
    SystemsPaperOpenScienceIntegrityError,
    build_systems_paper_open_science_artifacts,
    build_systems_paper_open_science_provenance,
    execute_systems_paper_open_science_overlay,
    fetch_standard_source_registry,
    load_systems_paper_open_science_overlay,
    run_systems_paper_provenance_queries,
    standard_source_definitions,
)

ROOT = Path(__file__).resolve().parents[3]
PARENT = ROOT / "runs/manual-live/task260-final-paper-v2"
AUDIT = ROOT / "runs/manual-live/task26370-systems-paper-currency-audit-v1"
REANALYSIS = ROOT / "runs/manual-live/task26371-independent-task-reanalysis-v1"
REWRITE = ROOT / "runs/manual-live/task26372-current-field-manuscript-v1"
BUILT_AT = datetime(2026, 7, 31, 22, 0, tzinfo=timezone.utc)


def _mock_fetch(url: str) -> SourceResponse:
    definitions = {item.url: item for item in standard_source_definitions()}
    definition = definitions[url]
    body = (
        f"<html><title>{definition.title}</title><body>"
        f"{' '.join(definition.required_markers)}</body></html>"
    ).encode()
    return SourceResponse(
        status_code=200,
        media_type="text/html",
        body=body,
        final_url=url,
    )


def test_standard_source_registry_is_authoritative_hashed_and_internal_raw(
    tmp_path: Path,
) -> None:
    registry = fetch_standard_source_registry(
        output_dir=tmp_path,
        retrieved_at=BUILT_AT,
        fetcher=_mock_fetch,
    )

    assert registry.source_count == 6
    assert registry.authoritative_only is True
    assert registry.raw_snapshots_internal_only is True
    assert all(item.review_exposes_raw_body is False for item in registry.sources)
    assert all((tmp_path / item.raw_relative_path).is_file() for item in registry.sources)
    assert (tmp_path / SOURCE_REGISTRY_FILENAME).is_file()

    def missing_markers(url: str) -> SourceResponse:
        return SourceResponse(200, "text/html", b"unrelated page", url)

    with pytest.raises(SystemsPaperOpenScienceIntegrityError, match="markers missing"):
        fetch_standard_source_registry(
            output_dir=tmp_path / "bad",
            retrieved_at=BUILT_AT,
            fetcher=missing_markers,
        )


def test_provenance_queries_retain_counterevidence_limits_and_negative_lineage() -> None:
    first = build_systems_paper_open_science_provenance(
        parent_dir=PARENT,
        audit_dir=AUDIT,
        reanalysis_dir=REANALYSIS,
        rewrite_dir=REWRITE,
        built_at=BUILT_AT,
    )
    second = build_systems_paper_open_science_provenance(
        parent_dir=PARENT,
        audit_dir=AUDIT,
        reanalysis_dir=REANALYSIS,
        rewrite_dir=REWRITE,
        built_at=BUILT_AT,
    )
    query = run_systems_paper_provenance_queries(first)
    traces = {item.claim_id: item for item in query.claim_traces}

    assert first.bundle_hash == second.bundle_hash
    assert traces["claim.controlled-state-machine-demonstration"].limiting_evidence_ids == [
        "evidence.external-validity-limit"
    ]
    assert traces["claim.thirty-seed-cells-independent"].counterevidence_ids == [
        "counterevidence.task-unit-correction"
    ]
    assert query.negative_result_entity_ids == [
        "entity.failure.route-a-round-1",
        "entity.failure.route-a-round-2",
    ]
    assert query.publication_decision == (
        "blocked_pending_independent_confirmation_and_human_review"
    )
    assert query.passed is True


def test_artifact_policy_keeps_complete_parent_internal_and_no_public_artifact(
    tmp_path: Path,
) -> None:
    fetch_standard_source_registry(
        output_dir=tmp_path,
        retrieved_at=BUILT_AT,
        fetcher=_mock_fetch,
    )
    artifacts, assertions, parent_file_count = build_systems_paper_open_science_artifacts(
        parent_dir=PARENT,
        audit_dir=AUDIT,
        reanalysis_dir=REANALYSIS,
        rewrite_dir=REWRITE,
        staging_dir=tmp_path,
    )
    parent_payload = [
        item for item in artifacts if item.crate_path.startswith("payload/task260-final-paper-v2/")
    ]
    assert parent_file_count == 3272
    assert len(parent_payload) == parent_file_count
    assert all(item.access is ArtifactAccess.INTERNAL for item in parent_payload)
    assert not any(item.crate_path.startswith("standards/raw/") for item in artifacts)
    assert len(list((tmp_path / "standards/raw").glob("*.html"))) == 6
    assert all(item.access is not ArtifactAccess.PUBLIC for item in artifacts)
    assert len(assertions) == 7


def test_full_overlay_roundtrip_reconstruction_privacy_and_tamper_gate(
    tmp_path: Path,
) -> None:
    output = tmp_path / "task26373-open-science-overlay-v1"
    report, manifest = execute_systems_paper_open_science_overlay(
        parent_package_dir=PARENT,
        audit_dir=AUDIT,
        reanalysis_dir=REANALYSIS,
        rewrite_dir=REWRITE,
        output_dir=output,
        built_at=BUILT_AT,
        fetcher=_mock_fetch,
    )

    assert report.parent_file_count == 3272
    assert report.internal_view_complete is True
    assert report.review_view_sanitized is True
    assert report.external_profile_validation_complete is False
    assert report.metadata_interoperability_only is True
    assert report.scientific_confirmation_added is False
    assert report.publication_ready is False
    assert report.public_view_created is False
    assert report.public_release_authorized is False
    assert report.external_submission_authorized is False
    assert manifest.file_count > report.parent_file_count
    assert (output / MANIFEST_FILENAME).is_file()
    assert (output / PROFILE_VALIDATION_FILENAME).is_file()
    assert not (output / "open-science/public").exists()

    internal = output / "open-science/internal-complete"
    review = output / "open-science/review-reproduction"
    assert validate_open_science_view(internal, view=ResearchObjectView.INTERNAL).status == "passed"
    assert validate_open_science_view(review, view=ResearchObjectView.REVIEW).status == "passed"
    assert (internal / "payload/task260-final-paper-v2/paper-package.json").read_bytes() == (
        PARENT / "paper-package.json"
    ).read_bytes()
    review_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in review.rglob("*")
        if path.is_file()
    )
    assert "E:/AIResearch" not in review_text
    assert "E:\\\\AIResearch" not in review_text
    assert not (review / "internal/provenance-bundle.json").exists()

    loaded_report, loaded_manifest = load_systems_paper_open_science_overlay(output)
    assert loaded_report == report
    assert loaded_manifest == manifest

    first = output / manifest.files[0].relative_path
    first.write_bytes(first.read_bytes() + b"tamper")
    with pytest.raises(SystemsPaperOpenScienceIntegrityError, match="file hash changed"):
        load_systems_paper_open_science_overlay(output)
