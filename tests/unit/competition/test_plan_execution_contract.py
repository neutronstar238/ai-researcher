"""Task 270.2: approved scientific prose must constrain the code that executes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.official_development_search import (
    OfficialCandidateRecord,
    OfficialCellSpec,
    OfficialDevelopmentIdentity,
    OfficialDevelopmentSearchError,
    _generation_brief,
    execute_official_stage,
    generate_official_candidates,
)
from autoresearch.competition.official_lineage import (
    OfficialLineageConfig,
    run_generate_stage,
)
from autoresearch.competition.plan_execution_contract import (
    PlanExecutionContractError,
    audit_candidate_plan_alignment,
    compile_plan_execution_contract,
    extract_required_method_tokens,
    load_plan_execution_contract,
    require_candidate_plan_alignment,
    write_plan_execution_contract,
)
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.research.plan_confirmation import (
    ResearchPlanConfirmationError,
    record_plan_decision,
)
from autoresearch.schemas import ResearchPlan, ResearchPlanStatus


def _plan(**overrides: Any) -> ResearchPlan:
    payload: dict[str, Any] = {
        "project_id": "task-270-2",
        "candidate_id": "candidate-plan-bound",
        "title": "Integral Bayesian constrained sparse discovery",
        "abstract": "A plan whose method is executable and falsifiable.",
        "problem_statement": "Point derivatives amplify measurement noise.",
        "rationale": "Integral evidence should reduce derivative noise.",
        "technical_details": (
            "Use an integral Bayesian sampler followed by constrained LARS."
        ),
        "datasets": {"source": "frozen panel", "target": "held-out derivatives"},
        "methods": "Integral Bayesian sampling with a constrained LARS solver.",
        "experiments": ["pilot", "ablation", "full panel"],
        "baselines": ["pinned PDE-FIND"],
        "metrics": ["derivative NMSE", "paired log effect"],
        "expected_results": "A null is valid and refutes the mechanism.",
        "code_agent_brief": (
            "Run python /harness/runner.py --config integral_bayesian.yaml. "
            "required_method_tokens=[integral, bayesian]"
        ),
        "risks_and_alternatives": ["thin PDE stratum", "sampler may time out"],
        "references": ["retained prior package"],
        "evidence_refs": ["runs/prior/package.json"],
        "status": ResearchPlanStatus.READY_FOR_APPROVAL,
    }
    payload.update(overrides)
    return ResearchPlan.model_validate(payload)


_ALIGNED_SOURCE = """\
def _integral_bayesian_sampler(payload):
    return payload

def fit_equations(payload):
    return _integral_bayesian_sampler(payload)

def predict_derivative(payload):
    return payload
"""


_UNRELATED_SOURCE = """\
# integral bayesian -- prose cannot satisfy the audit
def _integral_bayesian_sampler(payload):
    return payload

def _spectral_stridge(payload):
    return payload

def fit_equations(payload):
    integral_bayesian = payload
    return _spectral_stridge(payload)

def predict_derivative(payload):
    return payload
"""


def test_contract_carries_the_exact_approved_science_and_is_round_trippable(
    tmp_path: Path,
) -> None:
    plan = _plan()
    contract = compile_plan_execution_contract(plan)

    assert contract.scientific_plan["methods"] == plan.methods
    assert contract.scientific_plan["experiments"] == plan.experiments
    assert contract.scientific_plan["baselines"] == plan.baselines
    assert contract.scientific_plan["metrics"] == plan.metrics
    assert contract.required_method_tokens == ("integral", "bayesian")

    write_plan_execution_contract(contract=contract, output_dir=tmp_path)
    assert load_plan_execution_contract(tmp_path) == contract


def test_retained_config_name_is_an_unambiguous_legacy_contract() -> None:
    tokens = extract_required_method_tokens(
        "python /harness/runner.py --config "
        "integral_bayesian_constrained_lars.yaml --budget 252"
    )

    assert tokens == ("integral", "bayesian", "constrained", "lars")


def test_a_generic_brief_is_not_an_executable_scientific_contract() -> None:
    with pytest.raises(PlanExecutionContractError, match="2-8 distinctive"):
        compile_plan_execution_contract(
            _plan(code_agent_brief="Run python /harness/runner.py --spec x")
        )


def test_only_reachable_callables_can_prove_method_alignment() -> None:
    contract = compile_plan_execution_contract(_plan())

    aligned = audit_candidate_plan_alignment(
        candidate_id="aligned", source_text=_ALIGNED_SOURCE, contract=contract
    )
    unrelated = audit_candidate_plan_alignment(
        candidate_id="unrelated", source_text=_UNRELATED_SOURCE, contract=contract
    )

    assert aligned.passed is True
    assert aligned.reachable_identifier_evidence["integral"] == (
        "_integral_bayesian_sampler",
    )
    assert unrelated.passed is False
    assert unrelated.missing_method_tokens == ("integral", "bayesian")


def test_generation_brief_contains_plan_content_not_only_its_hash() -> None:
    contract = compile_plan_execution_contract(_plan())
    brief = _generation_brief(
        {
            "systems": [{"system_name": "s1", "data_type": "ode"}],
            "conditions": ["clean"],
        },
        {
            "maximum_seconds_per_cell": 20,
            "maximum_memory_mb_per_cell": 1024,
            "maximum_cpu_cores_per_cell": 2,
        },
        plan_execution_contract=contract,
    )

    embedded = brief["approved_research_plan_execution_contract"]
    assert embedded["scientific_plan"]["methods"] == _plan().methods
    assert embedded["scientific_plan"]["experiments"] == _plan().experiments
    assert embedded["required_method_tokens"] == ["integral", "bayesian"]
    assert "actually reached" in str(brief["plan_alignment_requirement"])


def test_generation_persists_alignment_and_rejects_an_unrelated_method(
    tmp_path: Path,
) -> None:
    sent_messages: list[list[dict[str, str]]] = []

    def completion(**kwargs: Any) -> LLMJsonCompletionResult:
        sent_messages.append([dict(item) for item in kwargs["messages"]])
        payload = _source_response(_ALIGNED_SOURCE)
        return _completion_result(payload)

    aligned = generate_official_candidates(
        identity=_identity(tmp_path),
        panel=_panel(),
        budget=_budget(),
        output_dir=tmp_path / "aligned",
        completion=completion,
        research_plan=_plan(),
    )[0]

    assert aligned.plan_alignment is not None
    assert aligned.plan_alignment.passed is True
    assert aligned.approved_plan_hash == aligned.plan_alignment.approved_plan_hash
    assert (tmp_path / "aligned" / "plan-execution-contract.json").is_file()
    assert _plan().methods in sent_messages[0][-1]["content"]

    def unrelated_completion(**_kwargs: Any) -> LLMJsonCompletionResult:
        return _completion_result(_source_response(_UNRELATED_SOURCE))

    unrelated = generate_official_candidates(
        identity=_identity(tmp_path),
        panel=_panel(),
        budget=_budget(),
        output_dir=tmp_path / "unrelated",
        completion=unrelated_completion,
        research_plan=_plan(),
    )[0]

    assert unrelated.plan_alignment is not None
    assert unrelated.plan_alignment.passed is False
    assert unrelated.static_review_approved is False
    assert any("PLAN_METHOD_NOT_IMPLEMENTED" in item for item in unrelated.static_review_findings)


def test_execution_refuses_a_legacy_hash_only_candidate_before_runner_start(
    tmp_path: Path,
) -> None:
    plan = _plan()
    decision = record_plan_decision(
        plan=plan,
        decision="approve",
        decided_by="operator",
        notes="scope approved",
        output_dir=tmp_path,
    )
    contract = compile_plan_execution_contract(plan)
    write_plan_execution_contract(contract=contract, output_dir=tmp_path)
    legacy = _candidate_record(source_sha256="2" * 64)

    with pytest.raises(PlanExecutionContractError, match="missing plan-alignment audit"):
        execute_official_stage(
            identity=_identity(tmp_path),
            specs=[_spec()],
            candidates=[legacy],
            output_dir=tmp_path,
            research_plan=plan,
            plan_decision=decision,
        )

    assert not (tmp_path / "cells").exists()


def test_generate_stage_requires_approval_before_freezing_or_calling_a_model(
    tmp_path: Path,
) -> None:
    config = OfficialLineageConfig(
        lineage_id="task-270-2",
        work_dir=tmp_path,
        frozen_plan_path=tmp_path / "missing-frozen.json",
        autonomous_plan_path=tmp_path / "missing-autonomous.json",
        data_root=tmp_path / "missing-data",
    )
    config.plan_dir.mkdir(parents=True)
    (config.plan_dir / "research-plan.json").write_text(
        _plan().model_dump_json(), encoding="utf-8"
    )

    with pytest.raises(ResearchPlanConfirmationError, match="recorded human decision"):
        run_generate_stage(config)

    assert not (tmp_path / "official-development-identity.json").exists()
    assert not (tmp_path / "plan-execution-contract.json").exists()


def test_alignment_audit_cannot_be_reused_for_other_source_bytes() -> None:
    contract = compile_plan_execution_contract(_plan())
    audit = audit_candidate_plan_alignment(
        candidate_id="c1", source_text=_ALIGNED_SOURCE, contract=contract
    )
    record = _candidate_record(
        source_sha256=audit.source_sha256,
        approved_plan_hash=contract.approved_plan_hash,
        plan_contract_hash=contract.contract_hash,
        plan_alignment=audit,
    )
    require_candidate_plan_alignment(candidates=[record], contract=contract)

    payload = json.loads(record.model_dump_json())
    payload["source_sha256"] = "f" * 64
    with pytest.raises(OfficialDevelopmentSearchError, match="different source bytes"):
        OfficialCandidateRecord.model_validate(payload)


def test_legacy_candidate_serialization_stays_byte_shape_compatible() -> None:
    legacy = _candidate_record()
    dumped = legacy.model_dump(mode="json")

    assert "approved_plan_hash" not in dumped
    assert "plan_contract_hash" not in dumped
    assert "plan_alignment" not in dumped


def _candidate_record(**overrides: Any) -> OfficialCandidateRecord:
    payload: dict[str, Any] = {
        "candidate_id": "c1",
        "generation": 1,
        "interaction_id": "generate-c1",
        "source_relative_path": "candidates/c1/candidate.py",
        "source_sha256": "a" * 64,
        "static_review_approved": True,
        "implementation_summary": "model-authored implementation",
    }
    payload.update(overrides)
    return OfficialCandidateRecord.model_validate(payload)


def _identity(tmp_path: Path) -> OfficialDevelopmentIdentity:
    payload: dict[str, Any] = {
        "schema_version": "official-development-identity-v1",
        "plan_hash": "a" * 64,
        "development_panel_hash": "b" * 64,
        "sealed_confirmation_panel_hash": "c" * 64,
        "runner_sha256": "d" * 64,
        "runtime_environment_hash": "e" * 64,
        "image_id": "sha256:" + "f" * 64,
        "data_root": tmp_path.as_posix(),
        "initial_candidate_count": 1,
        "pilot_system_count": 1,
        "full_system_count": 1,
        "conditions": ["clean"],
        "seeds": [101],
        "maximum_official_cells_total": 1,
        "numeric_payload_opened_during_freeze": False,
        "confirmation_identity_read_count": 0,
        "created_at": datetime(2026, 8, 8, tzinfo=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    payload["identity_hash"] = canonical_model_hash(payload)
    return OfficialDevelopmentIdentity.model_validate(payload)


def _spec() -> OfficialCellSpec:
    payload: dict[str, Any] = {
        "attempt_id": "pilot-c1-s1-clean-101",
        "method_kind": "candidate",
        "candidate_id": "c1",
        "stage": "pilot",
        "system_name": "s1",
        "data_type": "ode",
        "condition": "clean",
        "seed": 101,
        "data_relative_path": "s1.npz",
        "data_sha256": "1" * 64,
        "candidate_source_sha256": "2" * 64,
    }
    payload["spec_hash"] = canonical_model_hash(payload)
    return OfficialCellSpec.model_validate(payload)


def _panel() -> dict[str, Any]:
    return {
        "systems": [{"system_name": "s1", "data_type": "ode"}],
        "conditions": ["clean"],
        "seeds": [101],
    }


def _budget() -> dict[str, Any]:
    return {
        "maximum_seconds_per_cell": 20,
        "maximum_memory_mb_per_cell": 1024,
        "maximum_cpu_cores_per_cell": 2,
    }


def _source_response(source: str) -> dict[str, Any]:
    return {
        "response_type": "scientific_contract_source",
        "observation": "Noisy trajectories need a stable estimator.",
        "problem": "Point derivatives amplify measurement noise.",
        "hypothesis": "Integral Bayesian evidence reduces that amplification.",
        "intervention": "Implement the approved integral Bayesian mechanism.",
        "expected_effect": "Lower held-out derivative error under noise.",
        "implementation_summary": "Approved plan method implemented in reachable code.",
        "source_lines": source.splitlines(),
    }


def _completion_result(payload: dict[str, Any]) -> LLMJsonCompletionResult:
    return LLMJsonCompletionResult(
        provider="stub",
        base_url="https://example.invalid/v1",
        model_name="qwen3.7-max",
        endpoint="https://example.invalid/v1/chat/completions",
        response_text=json.dumps(payload),
        parsed_json=payload,
        usage={"prompt_tokens": 10, "completion_tokens": 20},
        temperature=0.2,
    )
