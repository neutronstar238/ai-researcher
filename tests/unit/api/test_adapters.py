from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from autoresearch.api.adapters import (
    ContestDirectionSkillEvolutionAdapter,
    Science125BatchAdapter,
)


def test_science125_adapter_forwards_only_pdf_selection_contract(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def runner(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"status": "dry_run", "question_count": 125, "provider_calls": 0}

    adapter = Science125BatchAdapter(
        skills_root=tmp_path / "skills", runner=runner, min_interval_seconds=1.5
    )
    result = adapter.submit_batch(
        question_pdf=tmp_path / "questions.pdf",
        output_root=tmp_path / "batch",
        start=1,
        limit=125,
        include_question_ids=(),
        resume=False,
        dry_run=True,
        config_path=tmp_path / "config.yaml",
        env_path=tmp_path / ".env",
        preexperiment_policy="plan_only_on_unsupported",
        dreaming_recall_enabled=True,
    )

    assert result["question_count"] == 125
    assert calls[0]["question_pdf"] == tmp_path / "questions.pdf"
    assert calls[0]["output_root"] == tmp_path / "batch" / "delivery"
    assert calls[0]["include_question_ids"] == ()
    assert calls[0]["dry_run"] is True
    assert calls[0]["min_interval_seconds"] == 1.5
    assert "questions" not in calls[0]


def test_skill_evolution_adapter_exposes_shadow_result_without_activation(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []
    artifact = SimpleNamespace(
        candidate_status="heldout_passed_shadow",
        candidate_skill_id="candidate-skill",
        parent_skill_id="parent-skill",
        promotion_eligible=True,
        production_enabled=False,
        active_skill_written=False,
        development_validation_passed=True,
        heldout_validation_passed=True,
        artifact_hash="a" * 64,
    )

    def runner(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            artifact=artifact,
            artifact_path=tmp_path / "evolution.json",
            report_path=tmp_path / "evolution.md",
            candidate_skill_dir=tmp_path / "shadow" / "candidate-skill",
            resumed_existing=False,
        )

    adapter = ContestDirectionSkillEvolutionAdapter(
        skills_root=tmp_path / "skills", runner=runner
    )
    result = adapter.evolve_run(
        run_id="run-test",
        delivery_root=tmp_path / "delivery",
        vault_root=tmp_path / "vault",
        config_path=tmp_path / "config.yaml",
        env_path=tmp_path / ".env",
    )

    assert result["status"] == "heldout_passed_shadow"
    assert result["promotion_eligible"] is True
    assert result["production_enabled"] is False
    assert result["active_skill_written"] is False
    assert result["promotion_authorized"] is False
    assert calls[0]["skills_root"] == (tmp_path / "skills").resolve()
    assert calls[0]["output_dir"] == tmp_path / "evolution" / "service"
