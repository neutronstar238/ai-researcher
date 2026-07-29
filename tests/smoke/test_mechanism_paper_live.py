"""Opt-in live source, PDF, and audit smoke for task 261.2.4."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from autoresearch.campaign.mechanism_paper import (
    MechanismCitationAudit,
    MechanismClaimEntailmentReport,
    MechanismFigureTableAudit,
    MechanismPaperAudit,
    MechanismPaperReproductionReport,
    MechanismPaperStatus,
    build_task2612_child_paper,
    load_task2612_child_paper,
)

LIVE_ENV = "AUTORESEARCH_MECHANISM_PAPER_LIVE"
FOUNDATION_ENV = "AUTORESEARCH_MECHANISM_PAPER_FOUNDATION"
CONFIRMATORY_ENV = "AUTORESEARCH_MECHANISM_PAPER_CONFIRMATORY"
OUTPUT_ENV = "AUTORESEARCH_MECHANISM_PAPER_OUTPUT"
REPRODUCTION_ENV = "AUTORESEARCH_MECHANISM_PAPER_REPRODUCTION"

pytestmark = pytest.mark.skipif(
    os.getenv(LIVE_ENV) != "1",
    reason=(
        f"set {LIVE_ENV}=1 to check all frozen literature sources and build "
        "the task 261.2.4 paper twice"
    ),
)


def test_negative_child_paper_builds_and_reproduces_with_live_sources() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    foundation = Path(
        os.getenv(
            FOUNDATION_ENV,
            str(
                repository_root
                / "runs"
                / "manual-live"
                / "task2612-mechanism-foundation-live-v3"
            ),
        )
    ).resolve()
    confirmatory = Path(
        os.getenv(
            CONFIRMATORY_ENV,
            str(
                repository_root
                / "runs"
                / "manual-live"
                / "task2612-mechanism-confirmatory-live-v1"
            ),
        )
    ).resolve()
    output = Path(
        os.getenv(
            OUTPUT_ENV,
            str(
                repository_root
                / "runs"
                / "manual-live"
                / "task2612-mechanism-paper-live-v1"
            ),
        )
    ).resolve()
    reproduction = Path(
        os.getenv(
            REPRODUCTION_ENV,
            str(
                repository_root
                / "runs"
                / "manual-live"
                / "task2612-mechanism-paper-reproduction-live-v1"
            ),
        )
    ).resolve()

    if (output / "paper-manifest.json").is_file():
        result = load_task2612_child_paper(output)
    else:
        for directory in (output, reproduction):
            if directory.exists() and any(directory.iterdir()):
                raise AssertionError(
                    f"mechanism paper smoke directory must be absent or empty: "
                    f"{directory}"
                )
        result = build_task2612_child_paper(
            foundation_dir=foundation,
            confirmatory_dir=confirmatory,
            output_dir=output,
            reproduction_dir=reproduction,
            compile_pdf=True,
            live_source_check=True,
        )

    entailment = MechanismClaimEntailmentReport.model_validate_json(
        (output / "manuscript" / "evidence" / "entailment-audit.json").read_text(
            encoding="utf-8"
        )
    )
    citation = MechanismCitationAudit.model_validate_json(
        (output / "manuscript" / "audit" / "citation-audit.json").read_text(
            encoding="utf-8"
        )
    )
    display = MechanismFigureTableAudit.model_validate_json(
        (output / "manuscript" / "audit" / "figure-table-audit.json").read_text(
            encoding="utf-8"
        )
    )
    paper_reproduction = MechanismPaperReproductionReport.model_validate_json(
        (output / "reproduction" / "paper-reproduction.json").read_text(
            encoding="utf-8"
        )
    )
    final_audit = MechanismPaperAudit.model_validate_json(
        (output / "audit" / "paper-audit.json").read_text(encoding="utf-8")
    )
    reachability = json.loads(
        (output / "frozen" / "source-reachability.json").read_text(
            encoding="utf-8"
        )
    )
    paper_build = json.loads(
        (output / "manuscript" / "build" / "paper-build.json").read_text(
            encoding="utf-8"
        )
    )

    assert result.status is MechanismPaperStatus.NEGATIVE_RESULT_PAPER_BUILT
    assert result.paper_quality_passed is True
    assert result.claim_coverage_complete is True
    assert result.submission_readiness_granted is False
    assert result.external_submission_authorized is False
    assert result.pdf_path is not None
    assert (output / result.pdf_path).is_file()
    assert reachability["mode"] == "live"
    assert reachability["all_reachable"] is True
    assert len(reachability["observations"]) == 14
    assert all(
        observation["status_code"] == 200
        and observation["content_bytes"] >= 1_000
        for observation in reachability["observations"]
    )
    assert entailment.passed is True
    assert entailment.registered_claim_count == 51
    assert citation.passed is True
    assert citation.source_count == 14
    assert citation.live_source_check_performed is True
    assert display.passed is True
    assert display.figure_count == 5
    assert display.table_count == 1
    assert paper_reproduction.passed is True
    assert paper_reproduction.source_file_count == 24
    assert paper_reproduction.primary_page_count == 13
    assert paper_reproduction.reproduced_page_count == 13
    assert paper_build["status"] == "compiled"
    assert paper_build["paper_quality"]["passed"] is True
    assert paper_build["paper_quality"]["overfull_hbox_count"] == 0
    assert paper_build["paper_quality"]["word_count"] >= 2_500
    assert final_audit.faithful_negative_result_reported is True
    assert final_audit.failed_gates == [
        "authorship_review",
        "explicit_human_approval",
        "license_review",
        "scientific_submission_gate",
    ]
    assert final_audit.submission_readiness_granted is False
    assert final_audit.external_submission_authorized is False
    assert load_task2612_child_paper(output) == result
