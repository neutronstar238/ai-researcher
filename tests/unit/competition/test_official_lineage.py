"""Task 269.1: the frozen gate and the signed package must be correct before any run.

The retired scratch driver `_lineage268.py` hand-wrote the frozen gate inside its
`adjudicate` stage, so the rule that decides whether a search-freeze receipt is
issued was never reviewed and never tested. It also never constructed an
`OfficialDevelopmentSearchPackage`, so the only adjudication record for the last real
lineage was a scratch text file.

These tests pin the adjudication rule itself:

* an absent aggregate is a FAILED check, never a pass
* an empty arm cannot satisfy a "must succeed" check vacuously
* a receipt is refused whenever any check fails, including budget non-conformance
* every threshold comes from the frozen plan's estimand, not from a literal
* the written package is the artifact whose hash is verified

The final test re-evaluates the retained conformant lineage through this module and
asserts the exact numbers that lineage recorded, which is what proves the gate moved
out of the scratch driver without changing arithmetic.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

import pytest

import autoresearch.competition.official_lineage as official_lineage_module
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.official_development_search import (
    _SPLIT_POLICY,
    OfficialCandidateRecord,
    OfficialCellResult,
    OfficialCellSpec,
    OfficialDevelopmentIdentity,
    OfficialDevelopmentSearchError,
    baseline_method_for,
    generate_official_candidates,
)
from autoresearch.competition.official_lineage import (
    LINEAGE_STAGES,
    LineageStageReport,
    OfficialLineageConfig,
    OfficialLineageError,
    _check_authoring_reservation,
    _reconcile_authoring_spend,
    _split_smoke_wave,
    _stage_shape,
    _verify_outcome_execution_artifacts,
    assert_finalists_can_execute,
    build_system_plan_evidence_context,
    evaluate_frozen_gate,
    freeze_lineage,
    frozen_gate_receipt,
    narrow_panel_by_policy,
    preregister_and_author_system_plan,
    rank_pilot_finalists,
    resume_plan_authoring_from_retained_reasoning,
    resume_plan_from_retained_routing,
    run_adjudicate_stage,
    run_lineage_stage,
    run_outcome_stage,
    select_pilot_systems,
    write_official_development_search_package,
)
from autoresearch.competition.official_spend_ledger import (
    OfficialSpendLedger,
    OfficialSpendLimitExceeded,
)
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.schemas import file_hash


def test_plan_authoring_resume_cannot_overwrite_original_receipts(
    tmp_path: Path,
) -> None:
    config = OfficialLineageConfig(
        lineage_id="resume-safety",
        work_dir=tmp_path,
        frozen_plan_path=tmp_path / "frozen.json",
        autonomous_plan_path=tmp_path / "autonomous.json",
        data_root=tmp_path / "data",
    )

    with pytest.raises(OfficialLineageError, match="fresh receipt directory"):
        resume_plan_authoring_from_retained_reasoning(
            config,
            output_dir=tmp_path,
        )


def _routing_resume_config(tmp_path: Path, *, lineage_id: str = "resume-routing") -> OfficialLineageConfig:
    return OfficialLineageConfig(
        lineage_id=lineage_id,
        work_dir=tmp_path / "lineage",
        frozen_plan_path=tmp_path / "frozen.json",
        autonomous_plan_path=tmp_path / "autonomous.json",
        data_root=tmp_path / "data",
    )


def test_routing_resume_refuses_a_missing_retained_reasoning_chain(
    tmp_path: Path,
) -> None:
    config = _routing_resume_config(tmp_path)
    config.work_dir.mkdir(parents=True)

    with pytest.raises(OfficialLineageError, match="retained.*missing"):
        resume_plan_from_retained_routing(
            config,
            output_dir=config.work_dir / "plan-resume-v1",
        )


def test_routing_resume_refuses_a_nonfresh_receipt_directory(tmp_path: Path) -> None:
    config = _routing_resume_config(tmp_path)
    config.work_dir.mkdir(parents=True)
    resume_root = config.work_dir / "plan-resume-v1"
    resume_root.mkdir()
    (resume_root / "unrelated.json").write_text("{}", encoding="utf-8")

    with pytest.raises(OfficialLineageError, match="not a fresh or valid partial"):
        resume_plan_from_retained_routing(config, output_dir=resume_root)


def test_routing_resume_refuses_to_overwrite_an_existing_official_plan(
    tmp_path: Path,
) -> None:
    config = _routing_resume_config(tmp_path)
    config.plan_dir.mkdir(parents=True)
    (config.plan_dir / "research-plan.json").write_text("{}", encoding="utf-8")

    with pytest.raises(OfficialLineageError, match="official research plan already exists"):
        resume_plan_from_retained_routing(
            config,
            output_dir=config.work_dir / "plan-resume-v1",
        )


def test_retained_ideation_receipt_must_contain_full_scientific_input(
    tmp_path: Path,
) -> None:
    from autoresearch.competition.model_authorship import (
        record_model_authorship_receipt,
    )

    parsed_payload = {"directions": [{"title": "系统生成方向"}]}
    full_input = {
        "research_opportunity_map_hash": "a" * 64,
        "component_experiment_binding": {"schema_version": "binding-v2"},
        "component_experiment_binding_hash": "b" * 64,
    }

    def completion() -> LLMJsonCompletionResult:
        response = json.dumps(parsed_payload, ensure_ascii=False, sort_keys=True)
        return LLMJsonCompletionResult(
            provider="openai_compatible",
            base_url="https://qwen.example.test/v1",
            model_name="qwen-test",
            endpoint="/chat/completions",
            response_text=response,
            parsed_json=parsed_payload,
            usage={},
            temperature=0.0,
            reasoning_text="逐项核对冻结输入、前瞻干预、文献映射和候选输出。" * 20,
            reasoning_transport="dashscope_enable_thinking",
        )

    valid_root = tmp_path / "valid"
    valid_messages = [
        {"role": "system", "content": "只按冻结输入生成结构化方向。"},
        {
            "role": "user",
            "content": json.dumps(full_input, ensure_ascii=False, sort_keys=True),
        },
    ]
    valid = record_model_authorship_receipt(
        artifact_kind="plan_ideation",
        interaction_id="system-plan-ideation-attempt-01",
        attempt=1,
        messages=valid_messages,
        completion=completion(),
        output_dir=valid_root,
    )
    loaded = official_lineage_module._load_exact_ideation_receipt(
        output_root=valid_root,
        relative_path=Path(valid.output_path).relative_to(valid_root).as_posix(),
        expected_hash=valid.receipt_hash,
        artifact_kind="plan_ideation",
        interaction_prefix="system-plan-ideation-attempt",
        outer_attempt=1,
        expected_model_name="qwen-test",
        expected_model_identity=(
            "openai_compatible",
            "https://qwen.example.test/v1",
            "qwen-test",
        ),
        expected_parsed_payload=parsed_payload,
        expected_input_fields=full_input,
        expected_method_skill_selection=None,
        label="ideation portfolio",
    )
    assert loaded == valid

    tampered_root = tmp_path / "tampered"
    tampered_messages = [
        valid_messages[0],
        {
            "role": "user",
            "content": json.dumps(
                {"research_opportunity_map_hash": "a" * 64},
                ensure_ascii=False,
                sort_keys=True,
            ),
        },
    ]
    tampered = record_model_authorship_receipt(
        artifact_kind="plan_ideation",
        interaction_id="system-plan-ideation-attempt-01",
        attempt=1,
        messages=tampered_messages,
        completion=completion(),
        output_dir=tampered_root,
    )
    with pytest.raises(OfficialLineageError, match="full hash-bound scientific input"):
        official_lineage_module._load_exact_ideation_receipt(
            output_root=tampered_root,
            relative_path=Path(tampered.output_path)
            .relative_to(tampered_root)
            .as_posix(),
            expected_hash=tampered.receipt_hash,
            artifact_kind="plan_ideation",
            interaction_prefix="system-plan-ideation-attempt",
            outer_attempt=1,
            expected_model_name="qwen-test",
            expected_model_identity=(
                "openai_compatible",
                "https://qwen.example.test/v1",
                "qwen-test",
            ),
            expected_parsed_payload=parsed_payload,
            expected_input_fields=full_input,
            expected_method_skill_selection=None,
            label="ideation portfolio",
        )


def _fake_retained_routing_chain(
    *, lineage_id: str = "resume-routing", bad_source_hash: bool = False
) -> dict[str, Any]:
    context = {"retained_signed_prior_results": [{"lineage_id": "prior-v1"}]}
    focus = {
        "domain": {"systems": [], "conditions": []},
        "exploratory_evidence_panels": [],
    }
    catalog = ({"retrieval_index": 0, "title": "paper"},)
    selected = ({"retrieval_index": 0, "title": "paper"},)
    method_binding = "method-binding"
    component_binding = "component-binding"
    envelope = "envelope"
    survey = SimpleNamespace(
        lineage_id=lineage_id,
        focus_sha256=canonical_model_hash(focus),
        retrieved_catalog=catalog,
        selected_references=selected,
    )
    task_signature = official_lineage_module._plan_method_task_signature(
        context=context,
        literature_focus=focus,
        retrieved_catalog=catalog,
    )
    method = SimpleNamespace(
        lineage_id="resume-routing",
        task_signature=task_signature,
        task_signature_hash=canonical_model_hash(task_signature),
        binding=lambda: method_binding,
    )
    component = SimpleNamespace(
        lineage_id="resume-routing",
        feasibility_envelope=envelope,
        method_skill_selection=method_binding,
        binding=lambda: component_binding,
    )
    prospective = SimpleNamespace(
        lineage_id="resume-routing",
        literature_survey=survey,
        feasibility_envelope=envelope,
        observed_component_binding=component_binding,
        method_skill_selection=method_binding,
        binding=lambda: "prospective-binding",
    )
    routing = SimpleNamespace(
        lineage_id="resume-routing",
        feasibility_envelope=envelope,
        component_atom_binding=component_binding,
        method_skill_selection=method_binding,
        source_catalog_hash=(
            "f" * 64
            if bad_source_hash
            else canonical_model_hash({"retrieved_catalog": list(catalog)})
        ),
        selected_references_hash=canonical_model_hash(
            {"selected_references": list(selected)}
        ),
        worker_bindings=lambda: (),
    )
    return {
        "lineage_id": "resume-routing",
        "context": context,
        "literature_focus": focus,
        "feasibility_envelope": envelope,
        "survey": survey,
        "method_skill_selection": method,
        "component_atoms": component,
        "prospective_atoms": prospective,
        "opportunity_routing": routing,
    }


@pytest.mark.parametrize(
    ("foreign_lineage", "bad_source_hash", "message"),
    (("other-lineage", False, "different lineage"), ("resume-routing", True, "hash chain")),
)
def test_routing_resume_rejects_cross_lineage_and_hash_mismatches(
    foreign_lineage: str, bad_source_hash: bool, message: str
) -> None:
    chain = _fake_retained_routing_chain(
        lineage_id=foreign_lineage, bad_source_hash=bad_source_hash
    )

    with pytest.raises(OfficialLineageError, match=message):
        official_lineage_module._validate_retained_plan_routing_chain(**chain)


def test_routing_resume_validates_existing_distributed_then_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _DumpModel:
        def __init__(self, **values: Any) -> None:
            self.__dict__.update(values)

        def model_dump(self, **_kwargs: Any) -> dict[str, Any]:
            return dict(self.__dict__)

        def __getattr__(self, name: str) -> Any:
            return self.__dict__[name]

    config = _routing_resume_config(tmp_path)
    config.work_dir.mkdir(parents=True)
    resume_root = config.work_dir / "plan-resume-v1"
    distributed_root = resume_root / "distributed"
    distributed_root.mkdir(parents=True)
    distributed_path = distributed_root / "system-plan-opportunity-distributed.json"
    original_distributed_bytes = b'{"retained":true}'
    distributed_path.write_bytes(original_distributed_bytes)

    method_binding = _DumpModel(selection_artifact_hash="b" * 64)
    component_binding = _DumpModel(binding_hash="c" * 64)
    survey = _DumpModel(
        survey_hash="a" * 64,
        selected_references=({}, {}, {}),
        retrieved_catalog=({}, {}, {}),
    )
    method = _DumpModel(artifact_hash="b" * 64, binding=lambda: method_binding)
    component = _DumpModel(artifact_hash="c" * 64, binding=lambda: component_binding)
    prospective_binding = _DumpModel(binding_hash="7" * 64)
    prospective = _DumpModel(
        artifact_hash="7" * 64,
        binding=lambda: prospective_binding,
    )
    routing = _DumpModel(artifact_hash="d" * 64)
    snapshot = official_lineage_module._RetainedPlanRoutingSnapshot(
        context={"public_development_panel": {}},
        evidence_paths=(),
        literature_focus={},
        survey=survey,
        method_skill_selection=method,
        component_atoms=component,
        prospective_atoms=prospective,
        opportunity_routing=routing,
        survey_path=config.work_dir / "plan-literature-survey.json",
        method_skill_selection_path=config.work_dir
        / "system-plan-method-skill-selection.json",
        component_atoms_path=config.work_dir / "system-plan-component-atoms.json",
        prospective_atoms_path=(
            config.work_dir / "system-plan-prospective-atoms.json"
        ),
        opportunity_routing_path=config.work_dir
        / "system-plan-opportunity-routing.json",
    )
    accepted_cell = _DumpModel(cell_id="O01")
    distributed = _DumpModel(
        artifact_hash="e" * 64,
        accepted_cells=(accepted_cell,),
        binding=lambda: "distributed-binding",
    )
    direction = _DumpModel(method_tokens=("token",))
    ideation = _DumpModel(
        artifact_hash="f" * 64,
        selected_direction=direction,
        selected_direction_hash="1" * 64,
    )
    preexperiment = _DumpModel(
        lineage_id=config.lineage_id,
        selected_direction_hash=ideation.selected_direction_hash,
        component_experiment_binding_hash="8" * 64,
        artifact_hash="2" * 64,
        output_path=(
            resume_root / "preexperiment" / "system-plan-preexperiment.json"
        ).resolve().as_posix(),
        limited_feasibility_supported=True,
        cell_evidence=(_DumpModel(),),
        plan_context=lambda: {
            "schema_version": "system-plan-preexperiment-plan-context-v1",
            "artifact_hash": "2" * 64,
            "plan_results_zh": "真实预实验已在有限范围运行成功；拟议处理效应仍未测量。",
        },
    )
    plan = _DumpModel(title="系统自产中文计划")
    plan_artifact = _DumpModel(
        plan={},
        plan_hash=canonical_model_hash(plan.model_dump()),
        artifact_hash="3" * 64,
        model_name="qwen-test",
        authorship_receipt_relative_path="interactions/plan.json",
        authorship_receipt_hash="4" * 64,
        output_path=(
            resume_root / "authoring" / "system-authored-research-plan.json"
        ).resolve().as_posix(),
    )
    review = _DumpModel(
        lineage_id=config.lineage_id,
        plan_hash=plan_artifact.plan_hash,
        literature_survey_hash=survey.survey_hash,
        review_hash="5" * 64,
        authorship_receipt_relative_path="interactions/review.json",
        authorship_receipt_hash="6" * 64,
        output_path=(
            resume_root / "authoring" / "system-plan-critical-review.json"
        ).resolve().as_posix(),
        assessment=_DumpModel(
            ready_for_human_scope_review=True,
            repair_findings=lambda: (),
        ),
    )
    distributed_loads: list[Path] = []
    ideation_calls: list[Path] = []

    monkeypatch.setattr(
        official_lineage_module,
        "_load_retained_plan_routing_snapshot",
        lambda _config: snapshot,
    )
    def fake_load_distributed(**kwargs: Any) -> Any:
        distributed_loads.append(kwargs["path"])
        return distributed

    monkeypatch.setattr(
        official_lineage_module,
        "_load_verified_distributed_artifact",
        fake_load_distributed,
    )
    monkeypatch.setattr(
        official_lineage_module,
        "_load_verified_ideation_artifact",
        lambda **_kwargs: ideation,
    )
    monkeypatch.setattr(
        official_lineage_module, "_require_model_receipt", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        official_lineage_module,
        "_same_retained_routing_snapshot",
        lambda _left, _right: True,
    )

    def fake_promote(**kwargs: Any) -> Any:
        canonical_path = config.work_dir / "system-authored-research-plan.json"
        canonical_path.write_text("{}", encoding="utf-8")
        values = kwargs["artifact"].model_dump()
        values["output_path"] = canonical_path.resolve().as_posix()
        return _DumpModel(**values)

    monkeypatch.setattr(
        official_lineage_module, "_promote_resumed_plan_artifact", fake_promote
    )

    import autoresearch.agents.temporary as temporary_module
    import autoresearch.competition.research_plan_latex as latex_module
    import autoresearch.competition.system_authored_plan as authored_module
    import autoresearch.competition.system_plan_ideation as ideation_module
    import autoresearch.competition.system_plan_opportunity_distributed as distributed_module
    import autoresearch.competition.system_plan_preexperiment as preexperiment_module
    import autoresearch.competition.system_plan_prospective_atoms as prospective_module
    import autoresearch.competition.system_plan_review as review_module
    import autoresearch.schemas as schemas_module

    monkeypatch.setattr(latex_module, "guard_references", lambda _refs: ())
    monkeypatch.setattr(
        temporary_module,
        "issue_stage_controller",
        lambda **_kwargs: pytest.fail("existing distributed stage must not issue a controller"),
    )
    monkeypatch.setattr(
        distributed_module,
        "run_distributed_system_plan_opportunity_map",
        lambda **_kwargs: pytest.fail("existing distributed stage must not rerun"),
    )
    monkeypatch.setattr(
        prospective_module,
        "build_component_experiment_binding",
        lambda _observed, _prospective: _DumpModel(
            binding_hash="8" * 64,
            prospective_components=prospective_binding,
        ),
    )

    def fake_ideation(**kwargs: Any) -> None:
        ideation_calls.append(Path(kwargs["output_dir"]))
        target = Path(kwargs["output_dir"]) / "system-plan-ideation.json"
        target.parent.mkdir(parents=True)
        target.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(ideation_module, "run_system_plan_ideation", fake_ideation)

    def fake_preexperiment(**kwargs: Any) -> Any:
        output = Path(kwargs["output_dir"])
        output.mkdir(parents=True)
        (output / "system-plan-preexperiment.json").write_text(
            "{}", encoding="utf-8"
        )
        return preexperiment

    monkeypatch.setattr(
        preexperiment_module,
        "run_system_plan_preexperiment",
        fake_preexperiment,
    )
    monkeypatch.setattr(
        preexperiment_module.SystemPlanPreexperimentArtifact,
        "model_validate_json",
        classmethod(lambda _cls, _payload: preexperiment),
    )

    def fake_author(**kwargs: Any) -> Any:
        output = Path(kwargs["output_dir"])
        output.mkdir(parents=True)
        (output / "system-authored-research-plan.json").write_text(
            "{}", encoding="utf-8"
        )
        (output / "system-plan-critical-review.json").write_text(
            "{}", encoding="utf-8"
        )
        return plan_artifact

    monkeypatch.setattr(authored_module, "author_research_plan", fake_author)
    monkeypatch.setattr(
        authored_module.SystemAuthoredPlanArtifact,
        "model_validate_json",
        classmethod(lambda _cls, _payload: plan_artifact),
    )
    monkeypatch.setattr(
        review_module.SystemPlanCriticalReview,
        "model_validate_json",
        classmethod(lambda _cls, _payload: review),
    )
    monkeypatch.setattr(
        schemas_module.ResearchPlan,
        "model_validate",
        classmethod(lambda _cls, _payload: plan),
    )
    monkeypatch.setattr(
        schemas_module.ResearchPlan,
        "model_validate_json",
        classmethod(lambda _cls, _payload: plan),
    )

    report = resume_plan_from_retained_routing(config, output_dir=resume_root)

    assert report.stage == "plan"
    assert distributed_loads == [distributed_path, distributed_path]
    assert ideation_calls == [resume_root / "ideation"]
    assert distributed_path.read_bytes() == original_distributed_bytes
    assert (config.work_dir / "system-authored-research-plan.json").is_file()
    assert (config.plan_dir / "research-plan.json").is_file()
    assert (resume_root / "plan-stage-resume-manifest.json").is_file()
    assert (resume_root / "preexperiment" / "system-plan-preexperiment.json").is_file()


# The frozen Task 266.1 estimand, verbatim. Nothing below invents a threshold.
_ESTIMAND: dict[str, Any] = {
    "minimum_overall_log_effect": 0.05129329438755058,
    "exploratory_lower_bound_minimum": 0.0,
    "ode_stratum_median_minimum": 0.0,
    "pde_stratum_median_minimum": 0.0,
}

_RETAINED = Path("runs/manual-live/task2663-conformant-v1")
_FROZEN_PLAN = Path(
    "runs/manual-live/task2661-scientific-contract-recovery-plan-v1/"
    "scientific-contract-recovery-plan.json"
)
_AUTONOMOUS_PLAN = Path(
    "runs/manual-live/task2651-autonomous-recovery-plan-v1/autonomous-research-plan.json"
)
_DATA_ROOT = Path(
    "runs/manual-live/task259-mdbench-official-v1/data/prepared/processed-9fe483c64ad6"
)
_PRIOR_SYSTEM_LINEAGE = Path(
    "runs/manual-live/task2696-stratified-gate-lineage-v1"
)


def _passing_summary() -> dict[str, Any]:
    """An aggregate that clears every frozen threshold."""

    return {
        "overall_median_log_effect": 0.9,
        "bootstrap_lower": 0.4,
        "bootstrap_upper": 1.4,
        "ode_stratum_median": 0.8,
        "pde_stratum_median": 0.7,
    }


def _cell(
    *,
    candidate_id: str = "c1",
    system: str = "s1",
    status: str = "succeeded",
    nmse: float | None = 0.1,
    validation: float | None = None,
    method_kind: str = "candidate",
    stage: str = "full",
    data_type: str = "ode",
    seed: int = 101,
) -> OfficialCellResult:
    return OfficialCellResult(
        attempt_id=f"{stage}-{candidate_id}-{system}-{seed}",
        method_kind=method_kind,  # type: ignore[arg-type]
        candidate_id=candidate_id,
        stage=stage,  # type: ignore[arg-type]
        system_name=system,
        data_type=data_type,  # type: ignore[arg-type]
        condition="snr_20",
        seed=seed,
        status=status,  # type: ignore[arg-type]
        derivative_nmse=nmse,
        validation_nmse=validation,
        result_hash="a" * 64,
    )


def _record(candidate_id: str, *, approved: bool = True) -> OfficialCandidateRecord:
    return OfficialCandidateRecord(
        candidate_id=candidate_id,
        generation=1,
        interaction_id=f"gen-{candidate_id}",
        source_relative_path=f"candidates/{candidate_id}/candidate.py",
        source_sha256="b" * 64,
        static_review_approved=approved,
        implementation_summary="a model-authored equation-discovery method",
    )


def _identity() -> OfficialDevelopmentIdentity:
    payload: dict[str, Any] = {
        "schema_version": "official-development-identity-v1",
        "plan_hash": "c" * 64,
        "development_panel_hash": "d" * 64,
        "sealed_confirmation_panel_hash": "e" * 64,
        "runner_sha256": "f" * 64,
        "runtime_environment_hash": "0" * 64,
        "image_id": "sha256:" + "1" * 64,
        "data_root": "/data/root",
        "initial_candidate_count": 8,
        "pilot_system_count": 6,
        "full_system_count": 14,
        "conditions": ["clean", "snr_20"],
        "seeds": [101, 211, 307],
        "maximum_official_cells_total": 464,
        "numeric_payload_opened_during_freeze": False,
        "confirmation_identity_read_count": 0,
        "created_at": datetime(2026, 8, 3, tzinfo=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    payload["identity_hash"] = canonical_model_hash(payload)
    return OfficialDevelopmentIdentity.model_validate(payload)


def _budget(**overrides: Any) -> dict[str, Any]:
    budget = {
        "pilot_ode_system_count": 3,
        "pilot_pde_system_count": 3,
        "pilot_seed_count": 1,
        "full_finalist_count": 3,
        "maximum_seconds_per_cell": 300,
        "maximum_parallel_cells": 4,
    }
    budget.update(overrides)
    return budget


def _panel(*, ode: int = 10, pde: int = 4) -> dict[str, Any]:
    systems = [{"system_name": f"ode-{i}", "data_type": "ode"} for i in range(ode)]
    systems += [{"system_name": f"pde-{i}", "data_type": "pde"} for i in range(pde)]
    return {"systems": systems, "seeds": [101, 211, 307], "conditions": ["clean", "snr_20"]}


def _authoring_test_config(tmp_path: Path) -> OfficialLineageConfig:
    return OfficialLineageConfig(
        lineage_id="authoring-ledger",
        work_dir=tmp_path,
        frozen_plan_path=tmp_path / "frozen.json",
        autonomous_plan_path=tmp_path / "autonomous.json",
        data_root=tmp_path / "data",
    )


def _authoring_test_ledger(*, maximum_interactions: int = 3) -> OfficialSpendLedger:
    return OfficialSpendLedger(
        lineage_id="authoring-ledger",
        plan_hash="c" * 64,
        maximum_total_candidate_count=4,
        maximum_official_candidate_cells=20,
        maximum_official_cells_total=30,
        maximum_model_interactions=maximum_interactions,
        maximum_generations=2,
    )


def _authoring_test_payload(*, conformant: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "response_type": "scientific_contract_source",
        "observation": "Noisy trajectories require a robust equation fit.",
        "problem": "A brittle sparse threshold can collapse under noise.",
        "hypothesis": "A fixed fallback preserves a non-empty prediction.",
        "intervention": "Use a bounded deterministic fallback after fitting.",
        "expected_effect": "The query path remains defined on held-out slices.",
        "implementation_summary": "Bounded model-authored fallback implementation.",
        "source_lines": [
            "import math",
            "",
            "",
            "def fit_equations(payload):",
            "    return {'equations': ['u_t = 0.0'], 'scaling': {}}",
            "",
            "",
            "def predict_derivative(payload):",
            "    return {'derivative': [0.0]}",
        ],
    }
    if not conformant:
        payload.pop("response_type")
    return payload


def _authoring_test_completion(payload: dict[str, Any]) -> LLMJsonCompletionResult:
    return LLMJsonCompletionResult(
        provider="qwen-dashscope",
        base_url="https://dashscope.example/compatible-mode/v1",
        model_name="qwen3.7-max",
        endpoint="https://dashscope.example/v1/chat/completions",
        response_text=json.dumps(payload),
        parsed_json=payload,
        usage={"prompt_tokens": 10, "completion_tokens": 20},
        temperature=0.2,
        reasoning_text="先保持科学方法，再核对结构契约。",
        reasoning_transport="dashscope_enable_thinking",
    )


def test_schema_repair_interactions_equal_ledger_and_provider_attempt_audit(
    tmp_path: Path,
) -> None:
    config = _authoring_test_config(tmp_path)
    identity = _identity().model_copy(update={"initial_candidate_count": 1})
    responses = [
        _authoring_test_payload(conformant=False),
        _authoring_test_payload(),
    ]
    calls: list[int] = []

    def completion(**_kwargs: Any) -> LLMJsonCompletionResult:
        calls.append(1)
        return _authoring_test_completion(responses[len(calls) - 1])

    records = generate_official_candidates(
        identity=identity,
        panel={"systems": [], "conditions": ["clean", "snr_20"]},
        budget={
            "maximum_seconds_per_cell": 10,
            "maximum_memory_mb_per_cell": 512,
            "maximum_cpu_cores_per_cell": 1,
        },
        output_dir=tmp_path,
        completion=completion,
    )
    specs: tuple[tuple[str, str, Literal[1, 2], str | None], ...] = (
        ("official-01", "official-generate-01", 1, None),
    )
    ledger, _evidence, audit = _reconcile_authoring_spend(
        config=config,
        ledger=_authoring_test_ledger(),
        stage="generate-gen1",
        specs=specs,
        records=records,
    )

    assert len(calls) == 2
    assert audit.logical_model_interaction_count == 2
    assert audit.canonical_model_interaction_count == 2
    assert audit.provider_request_attempt_count == 2
    assert audit.provider_request_attempt_count_is_lower_bound is False
    assert ledger.spent_model_interactions == 2
    assert ledger.spent_candidate_count == 1

    first = tmp_path / "interactions" / "official-generate-01.json"
    second = tmp_path / "interactions" / "official-generate-01-repair2.json"
    second.write_bytes(first.read_bytes())
    with pytest.raises(OfficialLineageError, match="canonical interaction contract mismatch"):
        _reconcile_authoring_spend(
            config=config,
            ledger=ledger,
            stage="generate-gen1",
            specs=specs,
            records=records,
        )


def test_provider_exception_persists_spend_and_resume_does_not_double_count(
    tmp_path: Path,
) -> None:
    config = _authoring_test_config(tmp_path)
    identity = _identity().model_copy(update={"initial_candidate_count": 1})
    specs: tuple[tuple[str, str, Literal[1, 2], str | None], ...] = (
        ("official-01", "official-generate-01", 1, None),
    )
    calls: list[int] = []

    def interrupted(**_kwargs: Any) -> LLMJsonCompletionResult:
        calls.append(1)
        raise RuntimeError("simulated provider interruption")

    with pytest.raises(RuntimeError, match="provider interruption"):
        generate_official_candidates(
            identity=identity,
            panel={"systems": [], "conditions": ["clean", "snr_20"]},
            budget={
                "maximum_seconds_per_cell": 10,
                "maximum_memory_mb_per_cell": 512,
                "maximum_cpu_cores_per_cell": 1,
            },
            output_dir=tmp_path,
            completion=interrupted,
        )
    ledger, evidence, audit = _reconcile_authoring_spend(
        config=config,
        ledger=_authoring_test_ledger(),
        stage="generate-gen1",
        specs=specs,
    )
    assert ledger.spent_candidate_count == 1
    assert ledger.spent_model_interactions == 1
    assert audit.incomplete_logical_interaction_ids == ("official-generate-01",)
    _check_authoring_reservation(
        ledger=ledger,
        stage="generate-gen1",
        specs=specs,
        evidence=evidence,
    )

    def resumed(**_kwargs: Any) -> LLMJsonCompletionResult:
        calls.append(1)
        return _authoring_test_completion(_authoring_test_payload())

    records = generate_official_candidates(
        identity=identity,
        panel={"systems": [], "conditions": ["clean", "snr_20"]},
        budget={
            "maximum_seconds_per_cell": 10,
            "maximum_memory_mb_per_cell": 512,
            "maximum_cpu_cores_per_cell": 1,
        },
        output_dir=tmp_path,
        completion=resumed,
    )
    ledger, _evidence, audit = _reconcile_authoring_spend(
        config=config,
        ledger=ledger,
        stage="generate-gen1",
        specs=specs,
        records=records,
    )
    entry_count = len(ledger.entries)
    ledger, _evidence, repeated = _reconcile_authoring_spend(
        config=config,
        ledger=ledger,
        stage="generate-gen1",
        specs=specs,
        records=records,
    )
    assert len(calls) == 2
    assert ledger.spent_candidate_count == 1
    assert ledger.spent_model_interactions == 1
    assert len(ledger.entries) == entry_count
    assert audit.canonical_model_interaction_count == 1
    assert repeated.logical_model_interaction_count == 1
    assert repeated.provider_request_attempt_count == 1


def test_insufficient_worst_case_budget_is_refused_before_model_registration(
    tmp_path: Path,
) -> None:
    config = _authoring_test_config(tmp_path)
    specs: tuple[tuple[str, str, Literal[1, 2], str | None], ...] = (
        ("official-01", "official-generate-01", 1, None),
    )
    ledger, evidence, _audit = _reconcile_authoring_spend(
        config=config,
        ledger=_authoring_test_ledger(maximum_interactions=2),
        stage="generate-gen1",
        specs=specs,
    )

    with pytest.raises(OfficialSpendLimitExceeded, match="maximum_model_interactions"):
        _check_authoring_reservation(
            ledger=ledger,
            stage="generate-gen1",
            specs=specs,
            evidence=evidence,
        )
    assert not (tmp_path / "candidates" / "official-01").exists()
    assert not list((tmp_path / "interactions").glob("*.logical-turn.json"))


# --------------------------------------------------------------------------
# The frozen gate
# --------------------------------------------------------------------------


def test_every_check_passes_on_a_conformant_adjudication() -> None:
    checks = evaluate_frozen_gate(
        estimand=_ESTIMAND,
        summary=_passing_summary(),
        candidate_cells=[_cell()],
        baseline_results=[_cell(method_kind="baseline", stage="baseline")],
        remaining_budget={"candidate_cells": 10, "total_cells": 20},
    )
    assert checks == {
        "all_candidate_cells_succeeded": True,
        "all_baseline_cells_succeeded": True,
        "overall_median_at_least_minimum": True,
        "bootstrap_lower_above_zero": True,
        "ode_stratum_non_negative": True,
        "pde_stratum_non_negative": True,
        "budget_conformant": True,
    }
    assert frozen_gate_receipt(checks) is True


def test_a_failed_candidate_cell_fails_its_check() -> None:
    checks = evaluate_frozen_gate(
        estimand=_ESTIMAND,
        summary=_passing_summary(),
        candidate_cells=[_cell(), _cell(system="s2", status="failed", nmse=None)],
        baseline_results=[_cell(method_kind="baseline", stage="baseline")],
        remaining_budget={"total_cells": 1},
    )
    assert checks["all_candidate_cells_succeeded"] is False
    assert frozen_gate_receipt(checks) is False


def test_a_failed_baseline_cell_fails_its_check() -> None:
    """The frozen estimand carries all_domain_baseline_cells_must_succeed = True."""

    checks = evaluate_frozen_gate(
        estimand=_ESTIMAND,
        summary=_passing_summary(),
        candidate_cells=[_cell()],
        baseline_results=[
            _cell(method_kind="baseline", stage="baseline"),
            _cell(method_kind="baseline", stage="baseline", system="s2", status="failed"),
        ],
        remaining_budget={"total_cells": 1},
    )
    assert checks["all_baseline_cells_succeeded"] is False
    assert frozen_gate_receipt(checks) is False


def test_an_empty_arm_cannot_satisfy_a_must_succeed_check() -> None:
    """`all()` over zero cells is vacuously true; an arm that ran nothing must fail."""

    checks = evaluate_frozen_gate(
        estimand=_ESTIMAND,
        summary=_passing_summary(),
        candidate_cells=[],
        baseline_results=[],
        remaining_budget={"total_cells": 1},
    )
    assert checks["all_candidate_cells_succeeded"] is False
    assert checks["all_baseline_cells_succeeded"] is False


def test_absent_aggregates_fail_rather_than_pass() -> None:
    """No estimate is not evidence the estimand was met."""

    checks = evaluate_frozen_gate(
        estimand=_ESTIMAND,
        summary={
            "overall_median_log_effect": None,
            "bootstrap_lower": None,
            "ode_stratum_median": None,
            "pde_stratum_median": None,
        },
        candidate_cells=[_cell()],
        baseline_results=[_cell(method_kind="baseline", stage="baseline")],
        remaining_budget={"total_cells": 1},
    )
    assert checks["overall_median_at_least_minimum"] is False
    assert checks["bootstrap_lower_above_zero"] is False
    assert checks["ode_stratum_non_negative"] is False
    assert checks["pde_stratum_non_negative"] is False


def test_thresholds_come_from_the_frozen_estimand() -> None:
    """An effect just under the frozen minimum fails; the frozen minimum itself passes."""

    minimum = float(_ESTIMAND["minimum_overall_log_effect"])
    summary = _passing_summary()
    summary["overall_median_log_effect"] = minimum
    at_minimum = evaluate_frozen_gate(
        estimand=_ESTIMAND,
        summary=summary,
        candidate_cells=[_cell()],
        baseline_results=[_cell(method_kind="baseline", stage="baseline")],
        remaining_budget={"total_cells": 1},
    )
    assert at_minimum["overall_median_at_least_minimum"] is True

    summary["overall_median_log_effect"] = minimum - 1e-12
    just_under = evaluate_frozen_gate(
        estimand=_ESTIMAND,
        summary=summary,
        candidate_cells=[_cell()],
        baseline_results=[_cell(method_kind="baseline", stage="baseline")],
        remaining_budget={"total_cells": 1},
    )
    assert just_under["overall_median_at_least_minimum"] is False


def test_a_lower_bound_exactly_at_the_minimum_does_not_pass() -> None:
    """The frozen check is a strict exceedance of the exploratory lower bound."""

    summary = _passing_summary()
    summary["bootstrap_lower"] = float(_ESTIMAND["exploratory_lower_bound_minimum"])
    checks = evaluate_frozen_gate(
        estimand=_ESTIMAND,
        summary=summary,
        candidate_cells=[_cell()],
        baseline_results=[_cell(method_kind="baseline", stage="baseline")],
        remaining_budget={"total_cells": 1},
    )
    assert checks["bootstrap_lower_above_zero"] is False


def test_budget_non_conformance_blocks_a_receipt() -> None:
    """An overrun search is not a protocol-conformant search (P-20260802-066)."""

    checks = evaluate_frozen_gate(
        estimand=_ESTIMAND,
        summary=_passing_summary(),
        candidate_cells=[_cell()],
        baseline_results=[_cell(method_kind="baseline", stage="baseline")],
        remaining_budget={"candidate_cells": 5, "total_cells": -1},
    )
    assert checks["budget_conformant"] is False
    assert frozen_gate_receipt(checks) is False


def test_an_empty_gate_cannot_decide_a_receipt() -> None:
    with pytest.raises(OfficialLineageError, match="empty gate"):
        frozen_gate_receipt({})


# --------------------------------------------------------------------------
# The signed package
# --------------------------------------------------------------------------


def _write_package(
    tmp_path: Path, *, gate_checks: dict[str, bool], selected: str | None = "c1"
) -> Any:
    return write_official_development_search_package(
        identity=_identity(),
        candidates=[_record("c1")],
        cell_results=[_cell()],
        stages_executed=["full"],
        selected_candidate_id=selected,
        selection_basis="median validation NMSE over executed cells",
        system_effects=[],
        summary=_passing_summary(),
        estimand=_ESTIMAND,
        gate_checks=gate_checks,
        output_dir=tmp_path,
    )


def test_a_conformant_package_is_written_and_hash_verified(tmp_path: Path) -> None:
    package = _write_package(tmp_path, gate_checks={"a": True, "b": True})
    written = tmp_path / "official-development-search-package.json"
    assert written.is_file()
    assert package.search_freeze_receipt_issued is True
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["package_hash"] == package.package_hash
    assert payload["minimum_overall_log_effect"] == _ESTIMAND["minimum_overall_log_effect"]
    # The hash must cover the content, so any edit to the persisted bytes is detected.
    payload["overall_median_log_effect"] = 99.0
    with pytest.raises(OfficialDevelopmentSearchError, match="hash mismatch"):
        type(package).model_validate(payload)


def test_a_receipt_is_refused_when_any_check_failed(tmp_path: Path) -> None:
    """The critical case: a failed check and a receipt can never coexist."""

    package = _write_package(tmp_path, gate_checks={"a": True, "b": False})
    assert package.search_freeze_receipt_issued is False


def test_a_receipt_requires_a_selected_candidate(tmp_path: Path) -> None:
    with pytest.raises(OfficialDevelopmentSearchError, match="selected candidate"):
        _write_package(tmp_path, gate_checks={"a": True}, selected=None)


def test_a_package_cannot_be_written_from_an_unevaluated_gate(tmp_path: Path) -> None:
    with pytest.raises(OfficialLineageError, match="empty gate"):
        _write_package(tmp_path, gate_checks={})


# --------------------------------------------------------------------------
# Stage shape read from the frozen plan
# --------------------------------------------------------------------------


def test_pilot_breadth_is_read_from_the_frozen_plan() -> None:
    systems = select_pilot_systems(panel=_panel(), budget=_budget())
    assert [item["data_type"] for item in systems] == ["ode"] * 3 + ["pde"] * 3


def test_a_panel_too_small_for_the_frozen_pilot_is_refused() -> None:
    with pytest.raises(OfficialLineageError, match="frozen pilot breadth"):
        select_pilot_systems(panel=_panel(ode=1, pde=4), budget=_budget())


def test_pilot_breadth_disagreeing_with_the_frozen_identity_is_refused() -> None:
    """The retired script ran 4 pilot systems while its identity declared 6."""

    with pytest.raises(OfficialLineageError, match="contradicts the preregistered"):
        _stage_shape(
            stage="pilot",
            panel=_panel(),
            budget=_budget(pilot_ode_system_count=2, pilot_pde_system_count=2),
            identity=_identity(),
        )


def test_pilot_uses_the_frozen_seed_count_and_full_uses_every_seed() -> None:
    _, pilot_seeds = _stage_shape(
        stage="pilot", panel=_panel(), budget=_budget(), identity=_identity()
    )
    full_systems, full_seeds = _stage_shape(
        stage="full", panel=_panel(), budget=_budget(), identity=_identity()
    )
    assert pilot_seeds == [101]
    assert full_seeds == [101, 211, 307]
    assert len(full_systems) == 14


# --------------------------------------------------------------------------
# Finalist ranking
# --------------------------------------------------------------------------


def test_finalists_are_the_best_median_validation_losses() -> None:
    candidates = [_record("c1"), _record("c2"), _record("c3"), _record("c4")]
    results = [
        _cell(candidate_id="c1", stage="pilot", validation=0.5),
        _cell(candidate_id="c2", stage="pilot", validation=0.1),
        _cell(candidate_id="c3", stage="pilot", validation=0.9),
        _cell(candidate_id="c4", stage="pilot", validation=0.3),
    ]
    chosen = rank_pilot_finalists(
        candidates=candidates, pilot_results=results, finalist_count=3
    )
    assert [item.candidate_id for item in chosen] == ["c2", "c4", "c1"]


def test_unapproved_and_unexecuted_candidates_cannot_be_finalists() -> None:
    candidates = [_record("c1", approved=False), _record("c2"), _record("c3")]
    results = [
        _cell(candidate_id="c1", stage="pilot", validation=0.01),
        _cell(candidate_id="c2", stage="pilot", validation=0.5),
        _cell(candidate_id="c3", stage="pilot", status="failed", nmse=None),
    ]
    chosen = rank_pilot_finalists(
        candidates=candidates, pilot_results=results, finalist_count=3
    )
    assert [item.candidate_id for item in chosen] == ["c2"]


def test_ties_break_deterministically_so_a_replay_selects_the_same_set() -> None:
    candidates = [_record("c2"), _record("c1")]
    results = [
        _cell(candidate_id="c1", stage="pilot", validation=0.4),
        _cell(candidate_id="c2", stage="pilot", validation=0.4),
    ]
    chosen = rank_pilot_finalists(
        candidates=candidates, pilot_results=results, finalist_count=1
    )
    assert [item.candidate_id for item in chosen] == ["c1"]


@pytest.mark.skipif(
    not (_PRIOR_SYSTEM_LINEAGE / "official-development-search-package.json").is_file(),
    reason="retained signed prior lineage is not present in this checkout",
)
def test_system_plan_context_contains_raw_evidence_but_no_authored_science(
    tmp_path: Path,
) -> None:
    config = OfficialLineageConfig(
        lineage_id="fresh-model-plan",
        work_dir=tmp_path,
        frozen_plan_path=_FROZEN_PLAN,
        autonomous_plan_path=_AUTONOMOUS_PLAN,
        data_root=_DATA_ROOT,
        prior_run_dirs=(_PRIOR_SYSTEM_LINEAGE,),
    )
    context, evidence_paths, focus = build_system_plan_evidence_context(config)

    assert set(context) == {
        "immutable_parent_protocol",
        "public_development_panel",
        "public_development_data_profiles",
        "sealed_confirmation_boundary",
        "current_lineage_preregistered_boundaries",
        "retained_signed_prior_results",
    }
    assert not {
        "title",
        "problem_statement",
        "rationale",
        "methods",
        "expected_results",
    }.intersection(context)
    prior = context["retained_signed_prior_results"][0]
    assert prior["package_hash"]
    assert prior["identity_binding"]["plan_hash"]
    assert prior["identity_binding"]["development_panel_hash"]
    assert prior["system_effects"]
    assert prior["gate_checks"]
    assert context["public_development_data_profiles"]
    assert all(
        item["profile_hash"]
        for item in context["public_development_data_profiles"]
    )
    assert all(path.is_file() for path in evidence_paths)
    assert set(focus) == {
        "domain",
        "public_data_profile_summaries",
        "observed_system_effects",
        "exploratory_evidence_panels",
        "observed_failures",
    }
    assert focus["public_data_profile_summaries"]
    assert focus["observed_system_effects"][0]["system_effects"]
    assert focus["exploratory_evidence_panels"]
    assert {
        item["fact_kind"] for item in focus["exploratory_evidence_panels"]
    } == {"profile_effect_association"}
    assert "problem_statement" not in focus


def test_preregister_plan_refuses_a_nonempty_lineage_before_docker_or_model(
    tmp_path: Path,
) -> None:
    (tmp_path / "preexisting.json").write_text("{}", encoding="utf-8")
    config = OfficialLineageConfig(
        lineage_id="not-fresh",
        work_dir=tmp_path,
        frozen_plan_path=Path("missing-plan.json"),
        autonomous_plan_path=Path("missing-autonomous.json"),
        data_root=Path("missing-data"),
    )
    with pytest.raises(OfficialLineageError, match="fresh lineage directory"):
        preregister_and_author_system_plan(
            config,
            baseline_parent_dir=Path("missing-parent"),
            authored_decision_package_path=Path("missing-decision.json"),
            zero_term_evidence_root=Path("missing-zero-term"),
            contradiction_package_path=Path("missing-contradiction.json"),
        )


def _chinese_outcome_interpretation() -> dict[str, Any]:
    return {
        "verdict": "claim_supported",
        "what_the_evidence_supports": (
            "在当前冻结开发面板内，观测到的总体配对对数效果中位数为 0.9，高于预先冻结的"
            "最低阈值 0.05129329438755058，而且候选单元、基线单元、两个分层以及预算门禁均"
            "通过。因此，这些已测证据支持本次入选实现相对固定基线的局部机制主张。"
        ),
        "what_the_evidence_does_not_support": (
            "这些开发数据不能证明该方法在封存确认面板、其他噪声分布、不同测量设备或未纳入"
            "的动力系统上仍然成立，也不能把一个入选实现推广成整个算法家族的普遍优势。任何"
            "超出本次冻结范围的结论都需要新的独立预注册与执行证据。"
        ),
        "strongest_counter_reading": (
            "最强反面解释是自助区间下界只有 0.4，有限开发系统可能夸大跨系统稳定性；因此即使"
            "当前门禁通过，仍不能把局部结果视为未经独立确认的普遍规律。"
        ),
        "limitations": (
            "结果只对应当前冻结的公开开发面板，尚未触碰封存确认数据。",
            "候选选择发生在开发阶段，不能替代另一执行者完成的独立科学复现。",
        ),
        "claims_frozen_gate_passed": True,
    }


class _OutcomeCompletion:
    def __init__(
        self,
        *,
        reasoning_tokens: int = 1_800,
        reasoning_text: str | None = "先核对冻结门禁，再逐项比较区间、分层和外推边界。",
    ) -> None:
        self.reasoning_tokens = reasoning_tokens
        self.reasoning_text = reasoning_text
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        self.calls.append(kwargs)
        payload = _chinese_outcome_interpretation()
        return LLMJsonCompletionResult(
            provider="qwen-dashscope",
            base_url="https://dashscope.example/compatible-mode/v1",
            model_name="qwen3.7-max",
            endpoint="https://dashscope.example/compatible-mode/v1/chat/completions",
            response_text=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            parsed_json=payload,
            usage={
                "completion_tokens_details": {
                    "reasoning_tokens": self.reasoning_tokens
                }
            },
            temperature=0.2,
            reasoning_text=self.reasoning_text,
            reasoning_transport=(
                "dashscope_enable_thinking"
                if self.reasoning_text is not None
                else "absent"
            ),
        )


def _write_outcome_model_config(tmp_path: Path) -> Path:
    path = tmp_path / "model-config.json"
    path.write_text(
        json.dumps(
            {
                "deployment": {
                    "llm": {
                        "provider": "qwen-dashscope",
                        "base_url": "https://dashscope.example/compatible-mode/v1",
                        "model_name": "qwen3.7-max",
                        "api_key_env": "DASHSCOPE_API_KEY",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def test_the_declared_stage_sequence_adds_outcome_after_adjudication() -> None:
    assert LINEAGE_STAGES == (
        "plan",
        "approve",
        "generate",
        "pilot",
        "revise",
        "baseline",
        "full",
        "adjudicate",
        "outcome",
    )


def test_lineage_stage_dispatches_outcome_with_model_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = OfficialLineageConfig(
        lineage_id="outcome-dispatch",
        work_dir=tmp_path,
        frozen_plan_path=tmp_path / "frozen.json",
        autonomous_plan_path=tmp_path / "autonomous.json",
        data_root=tmp_path / "data",
    )
    completion = _OutcomeCompletion()
    config_path = tmp_path / "qwen.json"
    env_path = tmp_path / ".env"
    observed: dict[str, Any] = {}

    def fake_outcome_stage(
        received: OfficialLineageConfig,
        *,
        completion: Any,
        config_path: Path | str,
        env_path: Path | str,
    ) -> LineageStageReport:
        observed.update(
            config=received,
            completion=completion,
            config_path=config_path,
            env_path=env_path,
        )
        return LineageStageReport(
            lineage_id=received.lineage_id,
            stage="outcome",
            lines=("outcome",),
            outcome_path=(tmp_path / "system-authored-outcome.json").as_posix(),
            outcome_hash="f" * 64,
            outcome_accepted=True,
        )

    monkeypatch.setattr(
        official_lineage_module, "run_outcome_stage", fake_outcome_stage
    )
    report = run_lineage_stage(
        config,
        stage="outcome",
        outcome_completion=completion,
        outcome_config_path=config_path,
        outcome_env_path=env_path,
    )

    assert report.stage == "outcome"
    assert observed == {
        "config": config,
        "completion": completion,
        "config_path": config_path,
        "env_path": env_path,
    }
    assert not (tmp_path / ".lineage-stage-lock").exists()


def test_outcome_stage_calls_the_model_and_accepts_only_bound_chinese_prose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen_plan = tmp_path / "frozen.json"
    frozen_plan.write_text(json.dumps({"estimand": _ESTIMAND}), encoding="utf-8")
    package = _write_package(tmp_path, gate_checks={"a": True, "b": True})
    config = OfficialLineageConfig(
        lineage_id="outcome-live-contract",
        work_dir=tmp_path,
        frozen_plan_path=frozen_plan,
        autonomous_plan_path=tmp_path / "autonomous.json",
        data_root=tmp_path / "data",
    )
    monkeypatch.setattr(
        official_lineage_module,
        "_load_verified_outcome_inputs",
        lambda _config, **_kwargs: (
            tmp_path / "official-development-search-package.json",
            package,
            "d" * 64,
        ),
    )
    completion = _OutcomeCompletion()
    report = run_outcome_stage(
        config,
        completion=completion,
        config_path=_write_outcome_model_config(tmp_path),
        env_path=tmp_path / ".env",
    )

    outcome_path = tmp_path / "system-authored-outcome.json"
    outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
    assert report.stage == "outcome"
    assert report.outcome_accepted is True
    assert report.outcome_path == outcome_path.resolve().as_posix()
    assert report.outcome_hash == outcome["outcome_hash"]
    assert outcome["accepted"] is True
    assert outcome["authored_by_model"] is True
    assert outcome["hand_written_prose_count"] == 0
    expected_interpretation = json.loads(
        json.dumps(
            {
                "schema_version": "authored-interpretation-v1",
                **_chinese_outcome_interpretation(),
            },
            ensure_ascii=False,
        )
    )
    assert outcome["interpretation"] == expected_interpretation
    assert completion.calls[0]["thinking_mode"] == "enabled"
    assert completion.calls[0]["thinking_budget"] == 4_000
    assert _chinese_outcome_interpretation()["what_the_evidence_supports"] not in "\n".join(
        report.lines
    )


def test_outcome_stage_refuses_missing_reasoning_even_when_prose_audits_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen_plan = tmp_path / "frozen.json"
    frozen_plan.write_text(json.dumps({"estimand": _ESTIMAND}), encoding="utf-8")
    package = _write_package(tmp_path, gate_checks={"a": True, "b": True})
    config = OfficialLineageConfig(
        lineage_id="outcome-no-reasoning",
        work_dir=tmp_path,
        frozen_plan_path=frozen_plan,
        autonomous_plan_path=tmp_path / "autonomous.json",
        data_root=tmp_path / "data",
    )
    monkeypatch.setattr(
        official_lineage_module,
        "_load_verified_outcome_inputs",
        lambda _config, **_kwargs: (
            tmp_path / "official-development-search-package.json",
            package,
            "d" * 64,
        ),
    )

    with pytest.raises(OfficialLineageError, match="reasoning provenance"):
        run_outcome_stage(
            config,
            completion=_OutcomeCompletion(reasoning_tokens=0, reasoning_text=None),
            config_path=_write_outcome_model_config(tmp_path),
            env_path=tmp_path / ".env",
        )


def test_outcome_stage_rechecks_inputs_after_the_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen_plan = tmp_path / "frozen.json"
    frozen_plan.write_text(json.dumps({"estimand": _ESTIMAND}), encoding="utf-8")
    package = _write_package(tmp_path, gate_checks={"a": True, "b": True})
    changed_package = package.model_copy(update={"selection_basis": "changed"})
    snapshots = iter(
        (
            (
                tmp_path / "official-development-search-package.json",
                package,
                "d" * 64,
            ),
            (
                tmp_path / "official-development-search-package.json",
                changed_package,
                "d" * 64,
            ),
        )
    )
    monkeypatch.setattr(
        official_lineage_module,
        "_load_verified_outcome_inputs",
        lambda _config, **_kwargs: next(snapshots),
    )
    config = OfficialLineageConfig(
        lineage_id="outcome-input-race",
        work_dir=tmp_path,
        frozen_plan_path=frozen_plan,
        autonomous_plan_path=tmp_path / "autonomous.json",
        data_root=tmp_path / "data",
    )
    completion = _OutcomeCompletion()

    with pytest.raises(OfficialLineageError, match="changed during outcome authoring"):
        run_outcome_stage(
            config,
            completion=completion,
            config_path=_write_outcome_model_config(tmp_path),
            env_path=tmp_path / ".env",
        )
    assert len(completion.calls) == 1


def test_outcome_stage_checks_official_inputs_before_calling_the_model(
    tmp_path: Path,
) -> None:
    completion = _OutcomeCompletion()
    config = OfficialLineageConfig(
        lineage_id="missing-official-evidence",
        work_dir=tmp_path,
        frozen_plan_path=tmp_path / "missing-frozen.json",
        autonomous_plan_path=tmp_path / "missing-autonomous.json",
        data_root=tmp_path / "missing-data",
    )

    with pytest.raises(OSError):
        run_outcome_stage(
            config,
            completion=completion,
            config_path=_write_outcome_model_config(tmp_path),
            env_path=tmp_path / ".env",
        )
    assert completion.calls == []


def test_raw_result_hash_tampering_is_refused_before_outcome_authoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from autoresearch.competition import plan_execution_contract

    data_root = tmp_path / "data"
    data_root.mkdir()
    data_path = data_root / "system-snr20.bin"
    data_path.write_bytes(b"official measured input")
    runner_path = tmp_path / "runner" / "runner.py"
    runner_path.parent.mkdir()
    runner_path.write_text("# frozen runner\n", encoding="utf-8")
    source_path = tmp_path / "candidates" / "c1" / "candidate.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("def fit_equations(x, y): return x\n", encoding="utf-8")

    identity_payload = _identity().model_dump(mode="json", exclude={"identity_hash"})
    identity_payload.update(
        {
            "plan_hash": "c" * 64,
            "runner_sha256": file_hash(runner_path),
            "data_root": data_root.resolve().as_posix(),
            "initial_candidate_count": 1,
            "pilot_system_count": 1,
            "full_system_count": 1,
            "conditions": ["snr_20"],
            "seeds": [101],
            "maximum_official_cells_total": 3,
        }
    )
    identity_payload["identity_hash"] = canonical_model_hash(identity_payload)
    identity = OfficialDevelopmentIdentity.model_validate(identity_payload)
    (tmp_path / "official-development-identity.json").write_text(
        identity.model_dump_json(), encoding="utf-8"
    )

    candidate = _record("c1").model_copy(
        update={
            "source_sha256": file_hash(source_path),
            "source_relative_path": "candidates/c1/candidate.py",
        }
    )
    registry = json.dumps(
        {"candidates": [candidate.model_dump(mode="json")]}, ensure_ascii=False
    )
    (tmp_path / "candidates" / "candidate-registry.json").write_text(
        registry, encoding="utf-8"
    )
    (tmp_path / "candidates" / "revised-registry.json").write_text(
        registry, encoding="utf-8"
    )

    spec_payload: dict[str, Any] = {
        "attempt_id": "pilot-c1-system-snr20-101",
        "method_kind": "candidate",
        "candidate_id": "c1",
        "stage": "pilot",
        "system_name": "system",
        "data_type": "ode",
        "condition": "snr_20",
        "seed": 101,
        "data_relative_path": data_path.name,
        "data_sha256": file_hash(data_path),
        "candidate_source_sha256": candidate.source_sha256,
    }
    spec_payload["spec_hash"] = canonical_model_hash(spec_payload)
    spec = OfficialCellSpec.model_validate(spec_payload)
    raw_spec: dict[str, Any] = {
        "attempt": {
            "attempt_id": spec.attempt_id,
            "system_name": spec.system_name,
            "condition": spec.condition,
            "data_type": spec.data_type,
            "seed": spec.seed,
        },
        "method_kind": spec.method_kind,
        "candidate_source_sha256": spec.candidate_source_sha256,
        "expected_data_sha256": spec.data_sha256,
        "expected_baseline_runner_sha256": "b" * 64,
        "baseline_method": baseline_method_for(spec.data_type),
        "split_policy": _SPLIT_POLICY,
        "maximum_fit_seconds": 270,
        "maximum_predict_seconds": 10,
    }
    raw_spec["spec_hash"] = canonical_model_hash(raw_spec)
    raw_result: dict[str, Any] = {
        "status": "succeeded",
        "derivative_nmse": 0.1,
        "validation_nmse": 0.2,
        "selected_term_count": 2,
        "equation_changed_on_shuffled_training": True,
        "maximum_equation_prediction_delta": 0.3,
        "wall_time_seconds": 1.0,
        "failure_reason": None,
        "spec_hash": raw_spec["spec_hash"],
    }
    raw_result["result_hash"] = canonical_model_hash(raw_result)
    result = OfficialCellResult(
        attempt_id=spec.attempt_id,
        method_kind=spec.method_kind,
        candidate_id=spec.candidate_id,
        stage=spec.stage,
        system_name=spec.system_name,
        data_type=spec.data_type,
        condition=spec.condition,
        seed=spec.seed,
        status="succeeded",
        derivative_nmse=0.1,
        validation_nmse=0.2,
        selected_term_count=2,
        equation_changed_on_shuffled_training=True,
        maximum_equation_prediction_delta=0.3,
        wall_time_seconds=1.0,
        result_hash=str(raw_result["result_hash"]),
    )
    cells_dir = tmp_path / "cells"
    cells_dir.mkdir()
    (cells_dir / "pilot-specs.json").write_text(
        json.dumps({"specs": [spec.model_dump(mode="json")]}), encoding="utf-8"
    )
    (cells_dir / "pilot-results.json").write_text(
        json.dumps(
            {
                "results": [result.model_dump(mode="json")],
                "approved_research_plan_hash": "a" * 64,
                "plan_execution_contract_hash": "d" * 64,
            }
        ),
        encoding="utf-8",
    )
    raw_dir = cells_dir / "pilot" / spec.attempt_id
    raw_dir.mkdir(parents=True)
    (raw_dir / "spec.json").write_text(json.dumps(raw_spec), encoding="utf-8")
    tampered_result = dict(raw_result)
    tampered_result["derivative_nmse"] = 99.0
    (raw_dir / "result.json").write_text(
        json.dumps(tampered_result), encoding="utf-8"
    )

    package = write_official_development_search_package(
        identity=identity,
        candidates=[candidate],
        cell_results=[result],
        stages_executed=["pilot", "baseline", "full"],
        selected_candidate_id="c1",
        selection_basis="frozen selection",
        system_effects=[],
        summary=_passing_summary(),
        estimand=_ESTIMAND,
        gate_checks={"a": True},
        output_dir=tmp_path,
    )
    config = OfficialLineageConfig(
        lineage_id="raw-result-tamper",
        work_dir=tmp_path,
        frozen_plan_path=tmp_path / "frozen.json",
        autonomous_plan_path=tmp_path / "autonomous.json",
        data_root=data_root,
    )
    ledger = OfficialSpendLedger(
        lineage_id=config.lineage_id,
        plan_hash=identity.plan_hash,
        maximum_total_candidate_count=1,
        maximum_official_candidate_cells=3,
        maximum_official_cells_total=3,
        maximum_model_interactions=3,
        maximum_generations=2,
    )
    contract = SimpleNamespace(
        approved_plan_hash="a" * 64,
        contract_hash="d" * 64,
    )
    monkeypatch.setattr(
        plan_execution_contract,
        "load_prospective_plan_execution_contract",
        lambda _root: contract,
    )
    monkeypatch.setattr(
        plan_execution_contract,
        "require_prospective_candidate_plan_alignment",
        lambda **_kwargs: None,
    )

    with pytest.raises(OfficialLineageError, match="raw execution result hash mismatch"):
        _verify_outcome_execution_artifacts(
            config=config,
            package=package,
            approved_plan_hash=contract.approved_plan_hash,
            contract_hash=contract.contract_hash,
            frozen={
                "estimand": _ESTIMAND,
                "search_budget": {"maximum_seconds_per_cell": 300},
            },
            ledger=ledger,
        )


# --------------------------------------------------------------------------
# Numerical equivalence with the retired scratch driver
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    not (_RETAINED / "cells" / "full-results.json").is_file(),
    reason="retained conformant lineage artifacts are not present in this checkout",
)
def test_adjudication_reproduces_the_retained_conformant_lineage(tmp_path: Path) -> None:
    """Re-evaluate the retained lineage and assert the numbers it recorded.

    This is the equivalence proof for moving the frozen gate out of `_lineage268.py`:
    the module must reproduce that lineage's adjudication exactly. The lineage is read
    read-only and the package is written to a temporary directory, so no retained
    artifact is mutated.
    """

    config = OfficialLineageConfig(
        lineage_id="task2663-conformant-v1",
        work_dir=_RETAINED,
        frozen_plan_path=_FROZEN_PLAN,
        autonomous_plan_path=_AUTONOMOUS_PLAN,
        data_root=_DATA_ROOT,
    )
    report = run_adjudicate_stage(config, package_output_dir=tmp_path)
    package = json.loads(
        (tmp_path / "official-development-search-package.json").read_text(encoding="utf-8")
    )

    assert package["selected_candidate_id"] == "official-03-r2"
    assert package["overall_median_log_effect"] == pytest.approx(-0.524076, abs=5e-7)
    assert package["bootstrap_lower"] == pytest.approx(-3.235713, abs=5e-7)
    assert package["bootstrap_upper"] == pytest.approx(1.804017, abs=5e-7)
    assert package["ode_stratum_median"] == pytest.approx(0.589509, abs=5e-7)
    assert package["pde_stratum_median"] == pytest.approx(-15.402305, abs=5e-7)
    assert package["search_freeze_receipt_issued"] is False
    assert report.search_freeze_receipt_issued is False

    selected = [
        item
        for item in package["cell_results"]
        if item["candidate_id"] == "official-03-r2" and item["stage"] == "full"
    ]
    assert len(selected) == 84
    assert sum(1 for item in selected if item["status"] == "succeeded") == 78

    # The two PDE systems whose baseline never produced a real loss stay excluded,
    # which is the correction `_verdict.txt` recorded only as prose.
    unpaired = [
        item["system_name"]
        for item in package["system_effects"]
        if not item["baseline_available"]
    ]
    assert sorted(unpaired) == ["heat_laser", "heat_soil_uniform_2d_p1"]

    # The retained lineage must not have been touched.
    assert not (_RETAINED / "official-development-search-package.json").exists()


# --------------------------------------------------------------------------
# Tasks 268.3 + 269.2: a new lineage must start with a provably clean ledger
# --------------------------------------------------------------------------


def _pinned_image_available() -> bool:
    """Report whether the pinned scientific image can be inspected.

    `freeze_lineage` fingerprints the pinned runtime, so it needs a running Docker
    daemon. The scientific dependencies live only in that image, so this test is
    skipped rather than failed when the daemon is absent.
    """

    try:
        completed = subprocess.run(
            ["docker", "image", "inspect", "autoresearch-mdbench:task260"],
            capture_output=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


@pytest.mark.skipif(
    not _pinned_image_available(),
    reason="pinned autoresearch-mdbench:task260 image is not inspectable here",
)
def test_freezing_a_lineage_that_already_spent_is_refused(tmp_path: Path) -> None:
    """A fresh lineage needs a fresh directory, or its spend is not clean.

    Freezing over an existing ledger would let a new lineage inherit the prior
    lineage's spend, which is how `P-20260802-066` overran the frozen budget.
    """

    from autoresearch.competition.official_spend_ledger import (
        OfficialSpendLedger,
        persist_ledger,
    )

    frozen_plan_hash = str(
        json.loads(_FROZEN_PLAN.read_text(encoding="utf-8"))["plan_hash"]
    )
    dirty = OfficialSpendLedger(
        lineage_id="task-dirty-v1",
        plan_hash=frozen_plan_hash,
        maximum_total_candidate_count=12,
        maximum_official_candidate_cells=380,
        maximum_official_cells_total=464,
        maximum_model_interactions=80,
        maximum_generations=2,
    ).record(stage="generate-gen1", candidate_count=8, model_interactions=8)
    persist_ledger(ledger=dirty, output_dir=tmp_path)

    config = OfficialLineageConfig(
        lineage_id="task-dirty-v1",
        work_dir=tmp_path,
        frozen_plan_path=_FROZEN_PLAN,
        autonomous_plan_path=_AUTONOMOUS_PLAN,
        data_root=_DATA_ROOT,
    )
    with pytest.raises(OfficialLineageError, match="not a new lineage"):
        freeze_lineage(config)


# --------------------------------------------------------------------------
# A preregistered exclusion must bind to the executed panel
# --------------------------------------------------------------------------


def test_a_policy_exclusion_removes_the_system_from_the_panel() -> None:
    """Without this the exclusion is decorative and the frozen gate stays unreachable.

    The gate checks `all_baseline_cells_succeeded`, so a system whose pinned baseline
    cannot produce a loss keeps that check false however clearly the policy declared
    it excluded. The declared panel change has to take effect somewhere, and this is
    where.
    """

    narrowed = narrow_panel_by_policy(
        panel=_panel(ode=10, pde=4),
        excluded_system_names=["pde-1", "pde-3"],
    )
    names = [item["system_name"] for item in narrowed["systems"]]
    assert "pde-1" not in names
    assert "pde-3" not in names
    assert len(names) == 12
    # Seeds and conditions are frozen and must survive the narrowing untouched.
    assert narrowed["seeds"] == [101, 211, 307]
    assert narrowed["conditions"] == ["clean", "snr_20"]


def test_narrowing_leaves_a_panel_without_exclusions_unchanged() -> None:
    panel = _panel()
    assert narrow_panel_by_policy(panel=panel, excluded_system_names=[])["systems"] == (
        panel["systems"]
    )


def test_excluding_a_system_absent_from_the_panel_is_refused() -> None:
    """A policy that names a system this lineage never had does not describe it."""

    with pytest.raises(OfficialLineageError, match="not in this panel"):
        narrow_panel_by_policy(
            panel=_panel(), excluded_system_names=["a-system-that-does-not-exist"]
        )


def test_a_policy_cannot_exclude_the_entire_panel() -> None:
    with pytest.raises(OfficialLineageError, match="excludes every system"):
        narrow_panel_by_policy(
            panel=_panel(ode=1, pde=0), excluded_system_names=["ode-0"]
        )


def test_baseline_and_full_stages_run_only_the_narrowed_panel() -> None:
    """The two stages that feed the gate and the effect must see 12, not 14."""

    narrowed = narrow_panel_by_policy(
        panel=_panel(), excluded_system_names=["pde-1", "pde-3"]
    )
    for stage in ("baseline", "full"):
        systems, seeds = _stage_shape(
            stage=stage,
            panel=narrowed,
            budget=_budget(),
            identity=_identity(),
        )
        assert len(systems) == 12
        assert seeds == [101, 211, 307]


def test_a_narrowed_panel_that_cannot_supply_the_frozen_pilot_breadth_is_refused() -> (
    None
):
    """The second frozen contradiction, surfaced rather than silently reshaped.

    The official panel carries exactly 4 PDE systems. The preregistered policy
    excludes 2 of them, leaving 2, while the frozen budget requires
    `pilot_pde_system_count=3` and the frozen identity declares
    `pilot_system_count=6`. Both are unsatisfiable on the narrowed panel, so
    honestly repairing the baseline-coverage contradiction exposes a SECOND
    independent one. This must fail closed: quietly running a 5-system pilot, or
    quietly drawing pilot systems from the un-narrowed panel, would rank finalists
    partly on systems the effect never measures.
    """

    narrowed = narrow_panel_by_policy(
        panel=_panel(ode=10, pde=4), excluded_system_names=["pde-1", "pde-3"]
    )
    with pytest.raises(OfficialLineageError, match="frozen pilot breadth"):
        _stage_shape(
            stage="pilot",
            panel=narrowed,
            budget=_budget(),
            identity=_identity(),
        )


# --------------------------------------------------------------------------
# A finalist must prove it can execute before it spends the full stage
# --------------------------------------------------------------------------


def _smoke_cell(candidate_id: str, *, status: str) -> OfficialCellResult:
    return _cell(
        candidate_id=candidate_id,
        system="ode-0",
        status=status,
        nmse=0.6 if status == "succeeded" else None,
        validation=0.5 if status == "succeeded" else None,
        stage="pilot",
    )


def test_a_finalist_that_executed_is_promoted() -> None:
    verdicts = assert_finalists_can_execute(
        results=[_smoke_cell("official-02-r2", status="succeeded")],
        finalist_ids=["official-02-r2"],
    )
    assert verdicts == {"official-02-r2": True}


def test_a_finalist_that_never_executed_is_flagged() -> None:
    """`P-20260804-080`: `official-05-r2` crashed all 72 of its full cells uniformly.

    Static review passed it because it checks structure, not types. Only execution
    evidence can catch an unconditional runtime crash.
    """

    verdicts = assert_finalists_can_execute(
        results=[
            _smoke_cell("official-02-r2", status="succeeded"),
            _smoke_cell("official-05-r2", status="failed"),
        ],
        finalist_ids=["official-02-r2", "official-05-r2"],
    )
    assert verdicts["official-02-r2"] is True
    # The refusal is REPORTED rather than hidden, so a reader sees the promotion gap.
    assert verdicts["official-05-r2"] is False


def test_a_finalist_with_no_cells_at_all_is_flagged() -> None:
    verdicts = assert_finalists_can_execute(
        results=[_smoke_cell("official-02-r2", status="succeeded")],
        finalist_ids=["official-02-r2", "official-09-r2"],
    )
    assert verdicts["official-09-r2"] is False


def test_promoting_when_no_finalist_can_run_is_refused() -> None:
    """The whole full stage must not be spent on code that cannot execute."""

    with pytest.raises(OfficialLineageError, match="cannot run"):
        assert_finalists_can_execute(
            results=[
                _smoke_cell("official-02-r2", status="failed"),
                _smoke_cell("official-05-r2", status="failed"),
            ],
            finalist_ids=["official-02-r2", "official-05-r2"],
        )


def _full_spec(
    candidate_id: str,
    system: str,
    condition: str,
    seed: int,
    *,
    data_type: str = "ode",
) -> Any:
    from autoresearch.competition.official_development_search import OfficialCellSpec

    payload: dict[str, Any] = {
        "attempt_id": f"full-{candidate_id}-{system}-{condition}-{seed}",
        "method_kind": "candidate",
        "candidate_id": candidate_id,
        "stage": "full",
        "system_name": system,
        "data_type": data_type,
        "condition": condition,
        "seed": seed,
        "data_relative_path": f"data/{system}-{condition}.npz",
        "data_sha256": "f" * 64,
        "candidate_source_sha256": "e" * 64,
    }
    payload["spec_hash"] = canonical_model_hash(payload)
    return OfficialCellSpec.model_validate(payload)


def _full_specs(
    candidate_ids: Sequence[str], systems: Sequence[str]
) -> tuple[Any, ...]:
    return tuple(
        _full_spec(candidate_id, system, condition, seed)
        for candidate_id in candidate_ids
        for system in systems
        for condition in ("clean", "snr_20")
        for seed in (101, 211, 307)
    )


def test_the_smoke_wave_takes_one_system_per_candidate() -> None:
    specs = _full_specs(["c1", "c2"], ["s1", "s2", "s3"])
    smoke, rest = _split_smoke_wave(specs)

    # All three systems here are ODE, so one system per candidate.
    assert len(smoke) == 12
    assert len(rest) == len(specs) - 12
    # Every candidate is represented, so no candidate skips the gate.
    assert {item.candidate_id for item in smoke} == {"c1", "c2"}
    for candidate_id in ("c1", "c2"):
        systems = {
            item.system_name for item in smoke if item.candidate_id == candidate_id
        }
        assert len(systems) == 1


def test_the_smoke_wave_covers_every_stratum() -> None:
    """`P-20260804-082`: a gate that cannot see a stratum cannot protect it.

    Taking only the first system covered an ODE system for all three candidates in
    `task2695-pde-repair-lineage-v1`, so a candidate whose PDE handling exceeds the
    wall-time budget passed its smoke wave and then failed all 12 of its PDE cells.
    """

    ode = _full_specs(["c1"], ["ode-a", "ode-b"])
    pde = tuple(
        _full_spec("c1", "pde-a", condition, seed, data_type="pde")
        for condition in ("clean", "snr_20")
        for seed in (101, 211, 307)
    )
    smoke, rest = _split_smoke_wave((*ode, *pde))

    covered = {item.data_type for item in smoke}
    assert covered == {"ode", "pde"}, "the smoke wave must reach both strata"
    # One ODE system plus one PDE system, at 2 conditions x 3 seeds each.
    assert len(smoke) == 12
    assert len(smoke) + len(rest) == len(ode) + len(pde)


def test_splitting_preserves_every_frozen_cell() -> None:
    """Freeze-before-execute must hold: no cell is added, dropped, or rewritten."""

    specs = _full_specs(["c1", "c2"], ["s1", "s2"])
    smoke, rest = _split_smoke_wave(specs)
    assert len(smoke) + len(rest) == len(specs)
    assert {item.spec_hash for item in (*smoke, *rest)} == {
        item.spec_hash for item in specs
    }


def test_a_single_system_stage_is_entirely_smoke() -> None:
    """A degenerate stage must not produce an empty second wave that then fails."""

    specs = _full_specs(["c1"], ["s1"])
    smoke, rest = _split_smoke_wave(specs)
    assert len(smoke) == len(specs)
    assert rest == ()
