from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoresearch.competition.contest_direction_memory import (
    ContestDirectionMemoryBridge,
    ContestDirectionMemoryError,
    MemoryRecallReceipt,
    StageMemoryReceipt,
)
from autoresearch.knowledge.raw_memory import RawMemorySourceKind, RawMemoryStore

_NOW = datetime(2026, 8, 12, 4, 0, tzinfo=timezone.utc)
_PROJECT_ID = "direction-loop-memory-test"


def _bridge(tmp_path: Path) -> ContestDirectionMemoryBridge:
    return ContestDirectionMemoryBridge(
        output_root=tmp_path / "run",
        vault_root=tmp_path / "vault",
        project_id=_PROJECT_ID,
        clock=lambda: _NOW,
    )


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_completed_stage_captures_exact_model_io_and_builds_obsidian_dreaming(
    tmp_path: Path,
) -> None:
    bridge = _bridge(tmp_path)
    run_root = tmp_path / "run"
    request = _write(
        run_root / "hypothesis-stage" / "interactions" / "interaction.json",
        '{"messages":[{"role":"user","content":"提出可证伪假设"}]}',
    )
    response = _write(
        run_root / "hypothesis-stage" / "responses" / "response.txt",
        "模型原始响应：候选假设甲。",
    )
    artifact = _write(
        run_root / "hypothesis-stage" / "direction-hypothesis-brainstorm.json",
        '{"schema_version":"brainstorm-v1","status":"complete"}',
    )
    original = {path: path.read_bytes() for path in (request, response, artifact)}

    result = bridge.capture_completed_stage(
        stage="hypothesis",
        artifact_paths=[run_root / "hypothesis-stage"],
    )

    assert result.receipt.status == "complete"
    assert result.receipt_path is not None
    assert (
        StageMemoryReceipt.model_validate_json(result.receipt_path.read_bytes()) == result.receipt
    )
    assert len(result.receipt.artifacts) == 3
    by_path = {item.artifact_relative_path: item for item in result.receipt.artifacts}
    assert (
        by_path["hypothesis-stage/interactions/interaction.json"].source_kind
        is RawMemorySourceKind.MODEL_TRANSCRIPT
    )
    assert (
        by_path["hypothesis-stage/responses/response.txt"].source_kind
        is RawMemorySourceKind.MODEL_TRANSCRIPT
    )
    assert (
        by_path["hypothesis-stage/direction-hypothesis-brainstorm.json"].source_kind
        is RawMemorySourceKind.TOOL_OUTPUT
    )

    store = RawMemoryStore(tmp_path / "vault")
    for item in result.receipt.artifacts:
        capture = store.load_record(
            item.raw_binding.record_relative_path,
            project_id=_PROJECT_ID,
        )
        source = run_root / item.artifact_relative_path
        assert capture.blob_path.read_bytes() == original[source]
        assert source.read_bytes() == original[source]

    assert result.receipt.dreaming_projection_id is not None
    dreaming = store.load_dreaming_projection(
        result.receipt.dreaming_projection_id,
        project_id=_PROJECT_ID,
    )
    markdown = dreaming.markdown_path.read_text(encoding="utf-8")
    assert "可重建的 Dreaming 派生视图" in markdown
    assert "不得替代、压缩或删除原始记录" in markdown
    assert len(dreaming.projection.content.source_bindings) == 3


def test_optional_recall_is_explicit_hash_bound_and_never_claims_evidence(
    tmp_path: Path,
) -> None:
    bridge = _bridge(tmp_path)
    run_root = tmp_path / "run"
    literature = _write(
        run_root / "literature" / "direction-literature.json",
        '{"artifact_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}',
    )
    hypothesis = _write(
        run_root / "hypothesis-stage" / "direction-hypothesis-brainstorm.json",
        '{"artifact_hash":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}',
    )
    literature_memory = bridge.capture_completed_stage(
        stage="literature",
        artifact_paths=[literature],
    )
    hypothesis_memory = bridge.capture_completed_stage(
        stage="hypothesis",
        artifact_paths=[hypothesis],
    )

    recalled = bridge.recall_optional_context(
        consumer_stage="postpilot",
        source_stages=["literature", "hypothesis"],
        requested=True,
    )

    assert recalled.receipt.status == "available"
    assert recalled.receipt.model_consumption_proven is False
    assert recalled.receipt.derived_context_is_evidence is False
    assert recalled.receipt_path is not None
    assert (
        MemoryRecallReceipt.model_validate_json(recalled.receipt_path.read_bytes())
        == recalled.receipt
    )
    assert [item.source_stage for item in recalled.receipt.selected] == [
        "literature",
        "hypothesis",
    ]
    assert [item.stage_receipt_hash for item in recalled.receipt.selected] == [
        literature_memory.receipt.receipt_hash,
        hypothesis_memory.receipt.receipt_hash,
    ]
    assert recalled.context is not None
    assert recalled.context["context_kind"] == ("optional_rebuildable_dreaming_navigation")
    assert recalled.context["derived_context_is_evidence"] is False
    assert recalled.context["model_consumption_proven_by_this_receipt"] is False

    not_requested = bridge.recall_optional_context(
        consumer_stage="scientific-review",
        source_stages=["literature", "hypothesis"],
        requested=False,
    )
    assert not_requested.receipt.status == "not_requested"
    assert not_requested.context is None


def test_dreaming_navigation_does_not_copy_scientific_claims_into_context(
    tmp_path: Path,
) -> None:
    bridge = _bridge(tmp_path)
    fabricated = "未经验证的巨大效应p等于零且已经证明"
    artifact = _write(
        tmp_path / "run" / "preexperiment" / "metrics.json",
        f'{{"fabricated_claim":"{fabricated}"}}',
    )
    bridge.capture_completed_stage(stage="pilot", artifact_paths=[artifact])

    recalled = bridge.recall_optional_context(
        consumer_stage="plan",
        source_stages=["pilot"],
        requested=True,
    )

    assert recalled.context is not None
    rendered = str(recalled.context)
    assert fabricated not in rendered
    assert "不是文献、实验结果或科学证据" in rendered
    selected = recalled.receipt.selected[0]
    assert selected.raw_bindings
    assert all(item.payload_sha256 for item in selected.raw_bindings)


def test_memory_startup_failure_degrades_without_blocking_or_mutating_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _write(
        tmp_path / "run" / "plan" / "research-plan.json",
        '{"title":"仍应交付"}',
    )
    original = artifact.read_bytes()

    def fail_store(_root: Path) -> RawMemoryStore:
        raise OSError("simulated private-memory failure")

    monkeypatch.setattr(
        "autoresearch.competition.contest_direction_memory.RawMemoryStore",
        fail_store,
    )
    bridge = ContestDirectionMemoryBridge(
        output_root=tmp_path / "run",
        vault_root=tmp_path / "vault",
        project_id=_PROJECT_ID,
        clock=lambda: _NOW,
    )

    result = bridge.capture_completed_stage(
        stage="plan",
        artifact_paths=[artifact],
    )
    recall = bridge.recall_optional_context(
        consumer_stage="review",
        source_stages=["plan"],
        requested=True,
    )

    assert result.receipt.status == "unavailable"
    assert result.receipt.delivery_blocked_by_memory is False
    assert result.receipt.errors == ("raw-memory startup failed (OSError)",)
    assert result.receipt_path is not None
    assert recall.receipt.status == "unavailable"
    assert recall.context is None
    assert artifact.read_bytes() == original


def test_resume_reuses_verified_receipt_and_rejects_changed_source_from_recall(
    tmp_path: Path,
) -> None:
    bridge = _bridge(tmp_path)
    artifact = _write(
        tmp_path / "run" / "postpilot-stage" / "postpilot-objective-review.json",
        '{"decision":"retain"}',
    )
    first = bridge.capture_completed_stage(
        stage="postpilot",
        artifact_paths=[artifact],
    )
    record_files_before = tuple((tmp_path / "vault").rglob("rawmem_*.json"))

    resumed = _bridge(tmp_path).capture_completed_stage(
        stage="postpilot",
        artifact_paths=[artifact],
    )

    assert resumed.receipt == first.receipt
    assert tuple((tmp_path / "vault").rglob("rawmem_*.json")) == record_files_before

    artifact.write_text('{"decision":"terminate"}', encoding="utf-8")
    with pytest.raises(ContestDirectionMemoryError, match="changed after capture"):
        bridge.load_stage_receipt("postpilot")
    recall = bridge.recall_optional_context(
        consumer_stage="plan",
        source_stages=["postpilot"],
        requested=True,
    )
    assert recall.receipt.status == "unavailable"
    assert recall.context is None
    assert recall.receipt.delivery_blocked_by_memory is False
