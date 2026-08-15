from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from autoresearch.research.adaptive_loop_benchmark import (
    build_adaptive_loop_benchmark_protocol,
)
from autoresearch.research.adaptive_loop_benchmark_design import (
    AdaptiveLoopBenchmarkDesignAudit,
    audit_adaptive_loop_benchmark_design,
    write_adaptive_loop_benchmark_design_audit,
)


def test_design_audit_rejects_seed_pseudoreplication_and_v1_superiority() -> None:
    audit = audit_adaptive_loop_benchmark_design(
        build_adaptive_loop_benchmark_protocol()
    )

    assert audit.total_run_cell_count == 60
    assert audit.paired_run_block_count == 15
    assert audit.within_template_model_repeat_count == 3
    assert audit.independent_challenge_instance_count == 5
    assert audit.analysis_unit == "independent_challenge_instance"
    assert audit.primary_contrast == (
        "adaptive_sovereign_minus_adaptive_derived_only"
    )
    assert audit.confirmatory_primary_endpoint == (
        "objectively_confirmed_terminal_success"
    )
    assert audit.per_challenge_inference_possible is False
    assert audit.pilot_execution_allowed_after_v2_freeze is True
    assert audit.confirmatory_superiority_claim_allowed is False
    assert audit.innovation_verified is False
    assert audit.publication_authorized is False
    assert all(item.current_exact_power == 0.0 for item in audit.power_scenarios)
    assert [
        item.required_independent_scenario_count for item in audit.power_scenarios
    ] == [31, 45, 60]
    assert audit.recommended_confirmatory_independent_scenario_count == 60
    assert audit.recommended_confirmatory_cell_count == 240
    assert audit.confirmatory_cell_count_with_three_model_repeats == 720


def test_design_audit_rejects_hash_and_exact_power_tamper() -> None:
    audit = audit_adaptive_loop_benchmark_design(
        build_adaptive_loop_benchmark_protocol()
    )
    payload = audit.model_dump(mode="json")
    payload["power_scenarios"][1]["current_exact_power"] = 0.5
    with pytest.raises(ValidationError, match="exact power mismatch"):
        AdaptiveLoopBenchmarkDesignAudit.model_validate(payload)

    payload = audit.model_dump(mode="json")
    payload["findings_cn"][0] += "篡改"
    with pytest.raises(ValidationError, match="design audit hash mismatch"):
        AdaptiveLoopBenchmarkDesignAudit.model_validate(payload)


def test_design_audit_writes_canonical_result_blind_artifacts(tmp_path: Path) -> None:
    protocol = build_adaptive_loop_benchmark_protocol()
    audit = write_adaptive_loop_benchmark_design_audit(protocol, tmp_path)

    raw = (tmp_path / "adaptive-loop-benchmark-design-audit-v2.json").read_bytes()
    assert AdaptiveLoopBenchmarkDesignAudit.model_validate_json(raw) == audit
    decoded = json.loads(raw)
    assert "results" not in decoded
    assert decoded["confirmatory_superiority_claim_allowed"] is False
    markdown = (
        tmp_path / "adaptive-loop-benchmark-design-audit-v2.md"
    ).read_text(encoding="utf-8")
    assert "独立挑战实例：5" in markdown
    assert "v1只允许工程pilot" in markdown
    assert "单次模型运行cell：240" in markdown
