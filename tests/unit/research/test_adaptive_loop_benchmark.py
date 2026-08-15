from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from autoresearch.research.adaptive_loop_benchmark import (
    AdaptiveLoopBenchmarkProtocol,
    build_adaptive_loop_benchmark_protocol,
    write_adaptive_loop_benchmark_protocol,
)


def test_protocol_freezes_complete_result_blind_four_arm_matrix() -> None:
    protocol = build_adaptive_loop_benchmark_protocol()

    assert len(protocol.arms) == 4
    assert len(protocol.challenges) == 5
    assert len(protocol.random_seeds) == 3
    assert len(protocol.arms) * len(protocol.challenges) * len(
        protocol.random_seeds
    ) == 60
    assert protocol.no_result_observed_when_frozen
    assert protocol.same_total_budget_across_arms
    assert protocol.scientific_superiority_established is False
    assert protocol.innovation_verified is False


def test_protocol_rejects_result_aware_endpoint_or_hash_tamper() -> None:
    protocol = build_adaptive_loop_benchmark_protocol()
    payload = protocol.model_dump(mode="json")
    payload["metrics"][0]["primary"] = False
    with pytest.raises(ValidationError, match="primary endpoints changed"):
        AdaptiveLoopBenchmarkProtocol.model_validate(payload)

    payload = protocol.model_dump(mode="json")
    payload["maximum_main_model_requests_per_cell"] += 1
    with pytest.raises(ValidationError, match="protocol hash mismatch"):
        AdaptiveLoopBenchmarkProtocol.model_validate(payload)


def test_protocol_writes_canonical_json_and_chinese_markdown(tmp_path: Path) -> None:
    protocol = write_adaptive_loop_benchmark_protocol(tmp_path)

    raw = (tmp_path / "adaptive-loop-benchmark-protocol.json").read_bytes()
    assert AdaptiveLoopBenchmarkProtocol.model_validate_json(raw) == protocol
    decoded = json.loads(raw)
    assert "results" not in decoded
    markdown = (tmp_path / "adaptive-loop-benchmark-protocol.md").read_text(
        encoding="utf-8"
    )
    assert "完整单元数：60" in markdown
    assert "尚未建立科学优越性" in markdown
