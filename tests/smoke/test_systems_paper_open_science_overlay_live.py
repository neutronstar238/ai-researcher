from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.research.systems_paper_currency_audit import (
    ParentSystemsPaperEvidence,
)
from autoresearch.research.systems_paper_open_science_overlay import (
    EXTERNAL_PROFILE_IDS,
    PROFILE_VALIDATION_FILENAME,
    SOURCE_REGISTRY_FILENAME,
    ProfileValidationReport,
    StandardSourceRegistry,
    execute_systems_paper_open_science_overlay,
    load_systems_paper_open_science_overlay,
)

LIVE_ENV = "AUTORESEARCH_TASK26373_LIVE"
OUTPUT_ENV = "AUTORESEARCH_TASK26373_OUTPUT"
VALIDATOR_ENV = "AUTORESEARCH_ROCRATE_VALIDATOR"

pytestmark = pytest.mark.skipif(
    os.getenv(LIVE_ENV) != "1",
    reason=f"set {LIVE_ENV}=1 to build the real Task 263.7.3 overlay",
)


def _validator_default() -> Path:
    executable = "rocrate-validator.exe" if os.name == "nt" else "rocrate-validator"
    return (
        Path(tempfile.gettempdir()) / "autoresearch-roc-validator-0.11.3" / "Scripts" / executable
    )


def test_real_task260_open_science_overlay_live() -> None:
    root = Path(__file__).resolve().parents[2]
    parent_dir = root / "runs/manual-live/task260-final-paper-v2"
    audit_dir = root / "runs/manual-live/task26370-systems-paper-currency-audit-v1"
    reanalysis_dir = root / "runs/manual-live/task26371-independent-task-reanalysis-v1"
    rewrite_dir = root / "runs/manual-live/task26372-current-field-manuscript-v1"
    output = Path(
        os.getenv(
            OUTPUT_ENV,
            str(root / "runs/manual-live/task26373-open-science-overlay-v1"),
        )
    ).resolve()
    validator = Path(os.getenv(VALIDATOR_ENV, str(_validator_default()))).resolve()
    if not validator.is_file():
        pytest.fail(f"isolated rocrate-validator executable is missing: {validator}")
    parent_before = ParentSystemsPaperEvidence.from_package(parent_dir)

    report, manifest = execute_systems_paper_open_science_overlay(
        parent_package_dir=parent_dir,
        audit_dir=audit_dir,
        reanalysis_dir=reanalysis_dir,
        rewrite_dir=rewrite_dir,
        output_dir=output,
        built_at=datetime(2026, 7, 31, 22, 30, tzinfo=timezone.utc),
        validator_executable=validator,
    )
    loaded_report, loaded_manifest = load_systems_paper_open_science_overlay(output)
    parent_after = ParentSystemsPaperEvidence.from_package(parent_dir)
    registry = StandardSourceRegistry.model_validate_json(
        (output / SOURCE_REGISTRY_FILENAME).read_text(encoding="utf-8")
    )
    profiles = ProfileValidationReport.model_validate_json(
        (output / PROFILE_VALIDATION_FILENAME).read_text(encoding="utf-8")
    )

    assert loaded_report == report
    assert loaded_manifest == manifest
    assert parent_after == parent_before
    assert report.parent_file_count == 3272
    assert report.external_profile_validation_complete is True
    assert profiles.external_validation_performed is True
    assert profiles.validator_version == "0.11.3"
    assert profiles.external_ro_crate_1_3_profile_available is False
    assert profiles.internal_ro_crate_1_3_contract_passed is True
    assert sorted(profiles.externally_validated_profiles) == sorted(EXTERNAL_PROFILE_IDS)
    assert len(profiles.results) == 8
    assert all(item.status == "passed" for item in profiles.results)
    persisted_profile_text = "\n".join(
        (output / item.report_relative_path).read_text(encoding="utf-8")
        for item in profiles.results
    )
    assert str(Path.home()) not in persisted_profile_text
    assert str(output) not in persisted_profile_text
    assert registry.source_count == 6
    assert all(item.status_code == 200 for item in registry.sources)
    assert all(item.required_markers == item.matched_markers for item in registry.sources)
    assert report.metadata_interoperability_only is True
    assert report.scientific_confirmation_added is False
    assert report.independent_confirmation_complete is False
    assert report.publication_ready is False
    assert report.public_view_created is False
    assert report.public_release_authorized is False
    assert report.external_submission_authorized is False
    assert not (output / "open-science/public").exists()
