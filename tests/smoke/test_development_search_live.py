import os
from pathlib import Path

import pytest

from autoresearch.research.development_search import (
    freeze_development_search,
    load_development_search_report,
    run_development_search,
)

RUN_ENV = "AUTORESEARCH_RUN_TASK2635_LIVE"
OUTPUT_ENV = "AUTORESEARCH_TASK2635_OUTPUT_DIR"
BASELINE_ENV = "AUTORESEARCH_TASK26342_BASELINE_DIR"
PANEL_ENV = "AUTORESEARCH_TASK26341_PANEL_PATH"
CONFIG_ENV = "AUTORESEARCH_TASK2635_CONFIG"
PREDECESSOR_ENV = "AUTORESEARCH_TASK2635_PREDECESSOR_DIR"


@pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to execute the full external development matrix",
)
def test_live_budget_matched_development_search() -> None:
    root = Path(__file__).resolve().parents[2]
    baseline_dir = Path(
        os.getenv(
            BASELINE_ENV,
            str(
                root
                / "runs/manual-live/"
                "task26342-clean-baseline-preregistration-v2"
            ),
        )
    ).resolve()
    panel_path = Path(
        os.getenv(
            PANEL_ENV,
            str(
                root
                / "runs/manual-live/task26341-open-objective-panel-v1/"
                "open-objective-task-panel.json"
            ),
        )
    ).resolve()
    output_dir = Path(
        os.getenv(
            OUTPUT_ENV,
            str(root / "runs/manual-live/task2635-development-search-v2"),
        )
    ).resolve()
    config_path = Path(
        os.getenv(
            CONFIG_ENV,
            str(root / "configs/campaign/ollama-qwen35-9b.yaml"),
        )
    ).resolve()
    predecessor_dir = Path(
        os.getenv(
            PREDECESSOR_ENV,
            str(root / "runs/manual-live/task2635-development-search-v1"),
        )
    ).resolve()
    os.environ.setdefault("AUTORESEARCH_LOCAL_OLLAMA_API_KEY", "ollama-local")

    freeze = freeze_development_search(
        baseline_dir,
        output_dir,
        panel_path=panel_path,
        config_path=config_path,
        env_path=root / ".env",
        predecessor_dir=predecessor_dir,
    )
    assert len(freeze.candidates) == 12
    assert len(freeze.policies) == 9
    assert len(freeze.assignments) == 189
    assert freeze.label_preparation_audit.confirmatory_resource_url_count == 0
    assert freeze.confirmatory_payloads_downloaded is False
    assert freeze.result_record_count == 0
    assert freeze.repair_lineage is not None
    assert freeze.repair_lineage.candidate_order_reused is True
    assert freeze.repair_lineage.scientific_design_changed is False
    assert freeze.repair_lineage.confirmatory_evidence_used is False

    first = run_development_search(baseline_dir, output_dir)
    first_loaded, _, first_manifest = load_development_search_report(output_dir)
    second = run_development_search(baseline_dir, output_dir)
    second_loaded, _, second_manifest = load_development_search_report(output_dir)

    assert first.report_hash == first_loaded.report_hash
    assert second.report_hash == first.report_hash
    assert second_loaded.report_hash == first.report_hash
    assert second_manifest.manifest_hash == first_manifest.manifest_hash
    assert first.assignment_count == 189
    assert first.candidate_stage_record_count == 189 * 12 * 4
    assert first.full_matrix_complete is True
    assert first.exact_resume_verified is True
    assert first.failure_cost_provenance_audit_passed is True
    assert first.numerical_outcomes_deterministic is True
    assert first.confirmatory_payloads_downloaded is False
    assert first.confirmatory_results_visible is False
