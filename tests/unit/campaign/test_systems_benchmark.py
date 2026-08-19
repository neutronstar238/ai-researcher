from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from autoresearch.campaign.systems import (
    SystemsMode,
    SystemsSourceEvidence,
    SystemsTaskFamily,
    freeze_systems_preregistration,
    run_systems_benchmark,
    systems_benchmark_status,
    task260_systems_blueprint_ids,
    write_systems_source_evidence,
)
from autoresearch.schemas import file_hash


def test_preregistration_freezes_exact_route_b_contract(tmp_path: Path) -> None:
    root, prereg = _fixture_preregistration(tmp_path)

    assert prereg.benchmark_id == root.name
    assert len(prereg.tasks) == 10
    assert tuple(task.task_id for task in prereg.tasks) == task260_systems_blueprint_ids()
    assert prereg.seeds == (211, 223, 227)
    assert prereg.main_modes == (
        SystemsMode.ONE_SHOT,
        SystemsMode.EXECUTE_ONCE,
        SystemsMode.FULL_LOOP,
    )
    assert len(prereg.ablation_modes) == 4
    assert prereg.route_a_completed_rounds == 2
    assert prereg.external_submission_authorized is False
    assert (root / "preregistration.md").is_file()


def test_complete_systems_matrix_passes_only_frozen_internal_gate(
    tmp_path: Path,
) -> None:
    root, _ = _fixture_preregistration(tmp_path)

    result = run_systems_benchmark(root, query_local_model=False)

    assert result.cell_count == 210
    assert result.main_cell_count == 90
    assert result.ablation_cell_count == 120
    metrics = result.mode_metrics
    assert metrics[SystemsMode.ONE_SHOT.value].task_success_rate == pytest.approx(0.2)
    assert metrics[SystemsMode.EXECUTE_ONCE.value].task_success_rate == pytest.approx(
        0.5
    )
    assert metrics[SystemsMode.FULL_LOOP.value].task_success_rate == pytest.approx(1.0)
    assert metrics[SystemsMode.NO_VAULT.value].task_success_rate == pytest.approx(0.7)
    assert metrics[
        SystemsMode.NO_FAILURE_FEEDBACK.value
    ].task_success_rate == pytest.approx(0.5)
    assert metrics[
        SystemsMode.NO_PREREGISTRATION.value
    ].task_success_rate == pytest.approx(0.0)
    assert metrics[
        SystemsMode.NO_EVIDENCE_GATE.value
    ].task_success_rate == pytest.approx(0.8)
    assert metrics[SystemsMode.FULL_LOOP.value].unsupported_claim_count == 0
    assert (
        metrics[SystemsMode.NO_EVIDENCE_GATE.value].unsupported_claim_count
        == 6
    )
    assert metrics[SystemsMode.FULL_LOOP.value].exact_reproduction_rate == 1.0
    assert result.bootstrap_ci95_lower > 0.0
    assert result.external_submission_authorized is False

    gate = json.loads(Path(result.contribution_gate_path).read_text(encoding="utf-8"))
    assert gate["passed"] is True
    assert gate["external_submission_authorized"] is False
    assert Path(result.report_path).is_file()
    assert Path(result.failure_report_path).is_file()
    assert Path(result.loop_report_path).is_file()
    assert Path(result.evidence_map_path).is_file()
    assert Path(result.manuscript_path).is_file()


def test_systems_run_is_idempotent_and_status_verifies_all_cells(
    tmp_path: Path,
) -> None:
    root, _ = _fixture_preregistration(tmp_path)
    first = run_systems_benchmark(root, query_local_model=False)
    result_path = root / "benchmark-result.json"
    first_mtime = result_path.stat().st_mtime_ns

    second = run_systems_benchmark(root, query_local_model=False)
    status = systems_benchmark_status(root)

    assert second.result_hash == first.result_hash
    assert result_path.stat().st_mtime_ns == first_mtime
    assert status.completed is True
    assert status.result_hash == first.result_hash
    assert status.contribution_gate_passed is True
    assert status.cell_count == 210


def test_source_tampering_blocks_systems_matrix(tmp_path: Path) -> None:
    root, prereg = _fixture_preregistration(tmp_path)
    source = Path(prereg.tasks[0].source_evidence_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    artifact = Path(payload["source_paths"][0])
    artifact.write_text("tampered", encoding="utf-8")

    with pytest.raises(ValueError, match="source artifact changed"):
        run_systems_benchmark(root, query_local_model=False)


def _fixture_preregistration(
    tmp_path: Path,
) -> tuple[Path, object]:
    root = tmp_path / "task260-systems-fixture"
    route_a = tmp_path / "route-a"
    route_a.mkdir()
    route_manifest = route_a / "campaign-manifest.json"
    route_manifest.write_text(
        json.dumps(
            {
                "campaign_id": "route-a",
                "completed_round_count": 2,
                "human_intervention_count": 0,
                "lineage_hash": "a" * 64,
                "outcome": "stopped",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    llm_config = tmp_path / "ollama.yaml"
    llm_config.write_text(
        "deployment:\n"
        "  llm:\n"
        "    provider: ollama-openai-compatible\n"
        "    base_url: http://127.0.0.1:11434/v1\n"
        "    model_name: qwen3.5:9b\n"
        "    api_key_env: AUTORESEARCH_LOCAL_OLLAMA_API_KEY\n",
        encoding="utf-8",
    )
    sources = []
    for index, task_id in enumerate(task260_systems_blueprint_ids()):
        family = (
            SystemsTaskFamily.UCI
            if index < 4
            else SystemsTaskFamily.MDBENCH
        )
        artifact = root / "source-evidence" / "raw" / f"{task_id}.txt"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(f"real-evidence-{task_id}", encoding="utf-8")
        source = SystemsSourceEvidence(
            task_id=task_id,
            family=family,
            dataset_or_system=task_id,
            source_kind="deterministic-test-source",
            source_paths=(artifact.resolve().as_posix(),),
            source_sha256={artifact.resolve().as_posix(): file_hash(artifact)},
            metrics={"effect": 0.1 if index % 2 == 0 else -0.1},
            validation_status="passed",
            truth_label="positive" if index % 2 == 0 else "negative",
            effect_value=0.1 if index % 2 == 0 else -0.1,
            created_at=datetime.now(timezone.utc),
        )
        record_path = (
            root
            / "source-evidence"
            / family.value
            / f"{task_id}.json"
        )
        sources.append(write_systems_source_evidence(record_path, source))
    prereg = freeze_systems_preregistration(
        root,
        benchmark_id=root.name,
        project_id="test-project",
        deadline=datetime.now(timezone.utc) + timedelta(days=30),
        route_a_campaign_path=route_a,
        route_a_manifest_sha256=file_hash(route_manifest),
        route_a_lineage_hash="a" * 64,
        route_a_completed_rounds=2,
        llm_config_path=llm_config,
        source_evidence=sources,
    )
    return root, prereg
