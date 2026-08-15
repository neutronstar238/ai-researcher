from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from typer.testing import CliRunner

from autoresearch.cli.main import app


def test_adaptive_explore_cli_starts_one_seed_without_scientific_fields(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    observed: dict[str, Any] = {}

    def fake_run(**kwargs: Any) -> SimpleNamespace:
        observed.update(kwargs)
        event = SimpleNamespace(
            interaction=SimpleNamespace(
                proposal=SimpleNamespace(operator=SimpleNamespace(value="reframe_question"))
            )
        )
        return SimpleNamespace(
            status=SimpleNamespace(value="paused_budget"),
            events=[event],
            model_call_count=2,
        )

    monkeypatch.setattr(
        "autoresearch.cli.main.run_conceptual_adaptive_exploration",
        fake_run,
    )
    output_dir = tmp_path / "loop"
    result = CliRunner().invoke(
        app,
        [
            "adaptive-explore",
            "--loop-id",
            "cli_adaptive_loop",
            "--project-id",
            "cli_adaptive_project",
            "--objective",
            "自主寻找可证伪且可复核的新研究问题。",
            "--scope",
            "只做开放探索，不执行实验或发表。",
            "--output-dir",
            str(output_dir),
            "--vault",
            str(tmp_path / "vault"),
            "--skill-root",
            str(tmp_path / "skills"),
            "--max-steps",
            "3",
        ],
    )

    assert result.exit_code == 0, result.output
    assert observed["loop_id"] == "cli_adaptive_loop"
    assert observed["objective_cn"] == "自主寻找可证伪且可复核的新研究问题。"
    assert observed["scope_cn"] == "只做开放探索，不执行实验或发表。"
    assert observed["max_steps"] == 3
    assert "supplied_hypothesis" not in observed
    assert "supplied_method" not in observed
    assert "formal_execution_authorized: false" in result.output
    assert "publication_authorized: false" in result.output


def test_adaptive_explore_cli_reports_fail_closed_runtime_error(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    def fail(**_: Any) -> None:
        raise ValueError("目标目录不是新的空目录")

    monkeypatch.setattr(
        "autoresearch.cli.main.run_conceptual_adaptive_exploration",
        fail,
    )
    result = CliRunner().invoke(
        app,
        [
            "adaptive-explore",
            "--loop-id",
            "cli_adaptive_loop",
            "--project-id",
            "cli_adaptive_project",
            "--objective",
            "自主寻找新的研究问题。",
            "--scope",
            "只做开放探索。",
            "--output-dir",
            str(tmp_path / "occupied"),
        ],
    )

    assert result.exit_code == 1
    assert "目标目录不是新的空目录" in result.output


def test_adaptive_research_cli_exposes_real_inputs_but_no_execution_authority(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    observed: dict[str, Any] = {}

    def fake_run(**kwargs: Any) -> SimpleNamespace:
        observed.update(kwargs)
        event = SimpleNamespace(
            interaction=SimpleNamespace(
                proposal=SimpleNamespace(
                    operator=SimpleNamespace(value="retrieve_evidence")
                )
            )
        )
        return SimpleNamespace(
            status=SimpleNamespace(value="paused_budget"),
            events=[event],
            model_call_count=2,
            temporary_agent_count=0,
            external_action_count=1,
        )

    monkeypatch.setattr(
        "autoresearch.cli.main.run_capability_adaptive_exploration",
        fake_run,
    )
    result = CliRunner().invoke(
        app,
        [
            "adaptive-research",
            "--loop-id",
            "cli_capability_loop",
            "--project-id",
            "cli_capability_project",
            "--objective",
            "自主寻找长期记忆状态更新的可证伪问题。",
            "--scope",
            "允许检索、派生整理和临时评审，不执行正式实验。",
            "--output-dir",
            str(tmp_path / "loop"),
            "--vault",
            str(tmp_path / "vault"),
            "--skill-root",
            str(tmp_path / "skills"),
            "--max-steps",
            "5",
            "--max-external-actions",
            "3",
            "--max-temporary-agents",
            "6",
        ],
    )

    assert result.exit_code == 0, result.output
    assert observed["objective_cn"] == "自主寻找长期记忆状态更新的可证伪问题。"
    assert observed["scope_cn"] == "允许检索、派生整理和临时评审，不执行正式实验。"
    assert observed["max_steps"] == 5
    assert observed["max_external_actions"] == 3
    assert observed["max_temporary_agents"] == 6
    assert "supplied_hypothesis" not in observed
    assert "supplied_method" not in observed
    assert "live_literature_retrieval: true" in result.output
    assert "independent_promotion_verifier: true" in result.output
    assert "generic_sandbox_execution: false" in result.output
    assert "formal_execution_authorized: false" in result.output
