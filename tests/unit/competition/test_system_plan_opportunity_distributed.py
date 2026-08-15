from __future__ import annotations

import copy
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import pytest

from autoresearch.agents.temporary import (
    StageControllerBinding,
    StageDispatchCapability,
    issue_stage_controller,
)
from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.system_plan_opportunity_distributed import (
    DistributedOpportunityPipelineError,
    DistributedSystemPlanOpportunityMapArtifact,
    _author_task,
    _binding_payload,
    _compact_expected_output_schema,
    _reviewer_task,
    _skill_contexts,
    _worker_evidence_fact_view,
    run_distributed_system_plan_opportunity_map,
)
from autoresearch.competition.system_plan_opportunity_map import (
    ResearchFeasibilityEnvelope,
    ResearchOpportunityCell,
    ResearchOpportunityMapBinding,
    SystemPlanOpportunityMapError,
)
from autoresearch.competition.system_plan_opportunity_routing import (
    OpportunityWorkerBinding,
    SystemPlanOpportunityRoutingArtifact,
    run_system_plan_opportunity_routing,
)
from autoresearch.competition.temporary_qwen_pool import TemporaryQwenContentTask
from autoresearch.llm.client import LLMJsonCompletionResult
from tests.unit.competition import test_system_plan_opportunity_map as map_helpers
from tests.unit.competition import (
    test_system_plan_opportunity_routing as routing_helpers,
)

_NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
_TASK_PAYLOAD_ASSERTION_LIMIT = 30_000


def _serialized_task_payload_size(task: TemporaryQwenContentTask) -> int:
    payload = task.model_dump(mode="json")
    return len(
        json.dumps(
            {
                key: payload[key]
                for key in (
                    "task_instruction",
                    "input_refs",
                    "input_payload",
                    "expected_output_schema",
                    "chinese_output_fields",
                )
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def _large_worker_binding(
    binding: OpportunityWorkerBinding,
) -> OpportunityWorkerBinding:
    """Expand one real v4 fact shape to the upper end of observed live payloads."""

    payload = binding.model_dump(mode="json")
    profile = next(
        item for item in payload["evidence_facts"] if item["fact_kind"] == "data_profile"
    )
    profile["value"]["channels"] = [
        f"扩展状态通道{index:03d}-" + ("甲" * 58) for index in range(205)
    ]
    payload_without_hash = dict(payload)
    payload_without_hash.pop("binding_hash")
    payload["binding_hash"] = canonical_model_hash(payload_without_hash)
    return OpportunityWorkerBinding.model_validate(payload)


def _routing(tmp_path: Path) -> SystemPlanOpportunityRoutingArtifact:
    envelope_payload = routing_helpers._envelope().model_dump(mode="json")
    for fact in envelope_payload["evidence_facts"]:
        if fact["fact_kind"] == "data_profile":
            fact["value"]["mechanical_placeholder"] = "甲"
    envelope_payload.pop("envelope_hash")
    envelope_payload["envelope_hash"] = canonical_model_hash(envelope_payload)
    envelope = ResearchFeasibilityEnvelope.model_validate(envelope_payload)
    method_binding = routing_helpers._method_binding()
    component_binding = routing_helpers._component_binding(
        envelope,
        method_binding,
    )
    return run_system_plan_opportunity_routing(
        lineage_id="distributed-opportunity-lineage",
        feasibility_envelope=envelope,
        retrieved_catalog=routing_helpers._catalog(),
        selected_references=routing_helpers._selected_references(),
        component_atom_binding=component_binding,
        method_skill_selection=method_binding,
        output_dir=tmp_path / "routing",
        completion=routing_helpers._Stub(
            routing_helpers._portfolio_payload(envelope, component_binding)
        ),
        max_attempts=1,
        clock=_NOW,
    )


def _controller(
    routing: SystemPlanOpportunityRoutingArtifact,
) -> tuple[StageControllerBinding, StageDispatchCapability]:
    return issue_stage_controller(
        lineage_id=routing.lineage_id,
        stage="distributed-opportunity-map",
        stage_attempt=1,
        controller_agent_id="opportunity-stage-main-agent",
        stage_input_hash=routing.artifact_hash,
        max_parallel_agents=7,
        claimed_at=_NOW,
        lease_token="distributed-opportunity-stage-token",
    )


def _cell_payload(worker_binding: dict[str, Any]) -> dict[str, Any]:
    route = worker_binding["route"]
    index = int(str(route["cell_id"])[1:]) - 1
    cell = copy.deepcopy(map_helpers._map()["opportunities"][index])
    cell["evidence_fact_ids"] = list(route["evidence_fact_ids"])
    cell["literature_indices"] = list(route["literature_indices"])
    cell["eligible_target_systems"] = list(route["target_systems"])
    cell["method_application_trace"]["verified_fact_ids"] = list(route["evidence_fact_ids"])
    cell["method_application_trace"]["closest_prior_reference_indices"] = list(
        route["literature_indices"]
    )
    cell["method_application_trace"]["changed_component"] = route["single_component_assignment"]
    return cast(dict[str, Any], cell)


class _DistributedCompletion:
    def __init__(
        self,
        *,
        author_attack: str | None = None,
        reviewer_attack: bool = False,
        fail_author: str | None = None,
        reject_all: bool = False,
        require_overlap: bool = False,
    ) -> None:
        self.author_attack = author_attack
        self.reviewer_attack = reviewer_attack
        self.fail_author = fail_author
        self.reject_all = reject_all
        self.barriers = {
            "opportunity_memo": threading.Barrier(7),
            "adversarial_critique": threading.Barrier(7),
        }
        self.require_overlap = require_overlap
        self.lock = threading.Lock()
        self.first_cell_ready = threading.Event()
        self.calls: list[dict[str, Any]] = []
        self.cells_by_id: dict[str, dict[str, Any]] = {}

    def __call__(self, **kwargs: Any) -> LLMJsonCompletionResult:
        user = json.loads(kwargs["messages"][-1]["content"])
        task_kind = str(user["任务类型"])
        short_input = user["短任务输入"]
        binding = short_input["worker_binding"]
        cell_id = str(binding["route"]["cell_id"])
        if self.require_overlap:
            self.barriers[task_kind].wait(timeout=10)
        if task_kind == "opportunity_memo":
            payload = _cell_payload(binding)
            if self.author_attack == "wrong-target" and cell_id == "O01":
                payload["eligible_target_systems"] = ["unassigned-target"]
            elif self.author_attack == "target-omission" and cell_id == "O01":
                payload["eligible_target_systems"] = payload["eligible_target_systems"][:-1]
            elif self.author_attack == "swapped-component" and cell_id == "O01":
                payload["method_application_trace"]["changed_component"] = (
                    "擅自改成另一项未获主阶段派工授权的科研组件并改变其作用对象，"
                    "同时声称其余全部条件仍保持冻结。"
                )
            elif self.author_attack == "duplicate" and cell_id == "O02":
                if not self.first_cell_ready.wait(timeout=10):
                    raise AssertionError("O01 author output was not available")
                first = self.cells_by_id["O01"]
                payload["evidence_fact_ids"] = list(first["evidence_fact_ids"])
                payload["eligible_target_systems"] = list(first["eligible_target_systems"])
                payload["method_application_trace"]["verified_fact_ids"] = list(
                    first["evidence_fact_ids"]
                )
            with self.lock:
                self.cells_by_id[cell_id] = copy.deepcopy(payload)
                if cell_id == "O01":
                    self.first_cell_ready.set()
        else:
            passes = not self.reject_all
            payload = {
                "cell_id": cell_id,
                "supporting_fact_ids": list(binding["route"]["evidence_fact_ids"]),
                "supporting_literature_indices": list(binding["route"]["literature_indices"]),
                "evidence_grounded": passes,
                "prerequisite_matches_target": passes,
                "intervention_preserves_semantics": passes,
                "alternative_is_distinguishable": passes,
                "feasible_under_frozen_contract": passes,
                "gap_not_covered_by_catalog": passes,
                "generalizable_scientific_question": passes,
                "critical_findings": (
                    [] if passes else ["该机会未能通过独立证据和可区分性硬门禁。"]
                ),
            }
            if self.reviewer_attack and cell_id == "O01":
                payload["supporting_fact_ids"] = ["E999"]
        with self.lock:
            self.calls.append(copy.deepcopy(kwargs))
        reasoning = (
            ""
            if task_kind == "opportunity_memo" and cell_id == self.fail_author
            else "先核对派工绑定，再逐项检查事实、目标、文献、对照与权限边界。" * 12
        )
        return LLMJsonCompletionResult(
            provider="qwen-dashscope",
            base_url="https://dashscope.example/compatible-mode/v1",
            model_name="qwen3.7-max",
            endpoint="https://dashscope.example/v1/chat/completions",
            response_text=json.dumps(payload, ensure_ascii=False),
            parsed_json=payload,
            usage={"reasoning_tokens": 800},
            temperature=float(kwargs["temperature"]),
            reasoning_text=reasoning,
            reasoning_transport="dashscope_enable_thinking",
        )


def _run(
    tmp_path: Path,
    completion: _DistributedCompletion,
) -> tuple[
    DistributedSystemPlanOpportunityMapArtifact,
    StageDispatchCapability,
]:
    routing = _routing(tmp_path)
    controller, capability = _controller(routing)
    artifact = run_distributed_system_plan_opportunity_map(
        routing_artifact=routing,
        controller=controller,
        capability=capability,
        output_dir=tmp_path / "distributed",
        author_completion=completion,
        reviewer_completion=completion,
        max_workers=7,
        clock=_NOW,
    )
    return artifact, capability


def test_seven_authors_then_distinct_reviewers_overlap_and_bind_for_ideation(
    tmp_path: Path,
) -> None:
    completion = _DistributedCompletion(require_overlap=True)
    artifact, capability = _run(tmp_path, completion)

    assert isinstance(artifact.binding(), ResearchOpportunityMapBinding)
    assert len(artifact.accepted_cells) == 7
    assert not capability.active
    assert artifact.author_phase_manifest.capability_retained_for_next_phase
    assert not artifact.author_phase_manifest.research_stage_completion_claimed
    assert artifact.reviewer_phase_manifest.capability_finalized
    assert artifact.reviewer_phase_manifest.phase_sequence_completed
    assert artifact.execution_authorized is False
    assert artifact.is_scientific_evidence is False
    assert artifact.approval_granted is False
    assert artifact.independent_review_bypassed is False
    output_dir = tmp_path / "distributed"
    assert len(list(output_dir.glob("temporary-agents/batches/*/assignments/*.json"))) == 14
    assert len(list(output_dir.glob("temporary-agents/batches/*/archives/*.json"))) == 14
    assert len(list(output_dir.glob("interactions/*.json"))) == 14
    persisted = DistributedSystemPlanOpportunityMapArtifact.model_validate_json(
        (output_dir / "system-plan-opportunity-distributed.json").read_text(encoding="utf-8")
    )
    assert persisted.artifact_hash == artifact.artifact_hash
    for call in completion.calls:
        messages = call["messages"]
        short_input = json.loads(messages[-1]["content"])["短任务输入"]
        worker_binding = short_input["worker_binding"]
        assert len(worker_binding["literature_records"]) == 3
        assert "method_skill_selection" not in worker_binding
        assert "binding_hash" in worker_binding
        assert all("full_fact_sha256" not in fact for fact in worker_binding["evidence_facts"])
        assert len(messages) == 4
        assert call["thinking_mode"] == "enabled"
        assert call["thinking_budget"] == 4_000
    author_instruction = next(
        json.loads(call["messages"][-1]["content"])["任务指令"]
        for call in completion.calls
        if json.loads(call["messages"][-1]["content"])["任务类型"] == "opportunity_memo"
    )
    assert "verified_fact_ids" in author_instruction
    assert "不能只列实际引用的子集" in author_instruction
    assert "汉字必须多于拉丁字母" in author_instruction


def test_route_owned_target_omission_is_filled_without_rewriting_science(
    tmp_path: Path,
) -> None:
    completion = _DistributedCompletion(author_attack="target-omission")
    artifact, _ = _run(tmp_path, completion)

    first_route = artifact.worker_bindings[0].route
    first_cell = artifact.opportunity_map.opportunities[0]
    assert first_cell.eligible_target_systems == first_route.target_systems
    assert (
        first_cell.operational_construct
        == _cell_payload(artifact.worker_bindings[0].model_dump(mode="json"))[
            "operational_construct"
        ]
    )


def test_complete_v4_author_and_reviewer_tasks_keep_payload_headroom(
    tmp_path: Path,
) -> None:
    artifact, _ = _run(tmp_path, _DistributedCompletion())
    large_bindings = tuple(_large_worker_binding(binding) for binding in artifact.worker_bindings)
    author_tasks = tuple(
        _author_task(binding, _skill_contexts(binding)) for binding in large_bindings
    )
    reviewer_tasks = tuple(
        _reviewer_task(
            binding,
            cell,
            artifact.author_batch,
            _skill_contexts(binding),
        )
        for binding, cell in zip(
            large_bindings,
            artifact.opportunity_map.opportunities,
            strict=True,
        )
    )
    author_sizes = tuple(_serialized_task_payload_size(item) for item in author_tasks)
    reviewer_sizes = tuple(_serialized_task_payload_size(item) for item in reviewer_tasks)

    assert all(isinstance(item, TemporaryQwenContentTask) for item in author_tasks)
    assert all(isinstance(item, TemporaryQwenContentTask) for item in reviewer_tasks)
    reviewer_instruction = reviewer_tasks[0].task_instruction
    assert "七项硬门禁全部为 true 时必须返回空列表" in reviewer_instruction
    assert "不得把通过理由写入其中" in reviewer_instruction
    assert "任一硬门禁为 false 时必须" in reviewer_instruction
    assert max(author_sizes) <= _TASK_PAYLOAD_ASSERTION_LIMIT
    assert max(reviewer_sizes) <= _TASK_PAYLOAD_ASSERTION_LIMIT
    assert (
        min(
            len(
                json.dumps(
                    _binding_payload(binding),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            for binding in large_bindings
        )
        >= 26_000
    )
    author_schema = _compact_expected_output_schema(ResearchOpportunityCell)
    serialized_schema = json.dumps(author_schema, ensure_ascii=False)
    assert '"title"' not in serialized_schema
    assert '"description"' not in serialized_schema
    assert author_schema["additionalProperties"] is False
    assert author_schema["required"] == list(ResearchOpportunityCell.model_fields)


def test_worker_payload_projects_only_routed_matrix_rows_and_binds_full_fact(
    tmp_path: Path,
) -> None:
    routing = _routing(tmp_path)
    binding = routing.worker_binding("O01")
    payload = _binding_payload(binding)
    matrix = next(
        item
        for item in payload["evidence_facts"]
        if item["fact_kind"] == "cross_lineage_effect_matrix"
    )

    assert [item["system_name"] for item in matrix["value"]["comparable_system_rows"]] == list(
        binding.route.target_systems
    )
    assert "coverage_ledger" not in matrix["value"]
    assert "coverage_ledger_sha256" in matrix["value"]
    assert "candidate_records_sha256" in matrix["value"]
    assert all(
        "selected_candidate_summary" not in item for item in matrix["value"]["candidate_refs"]
    )
    assert len(matrix["full_fact_sha256"]) == 64
    assert len(payload["frozen_budget"]["full_budget_sha256"]) == 64


def test_large_matrix_projection_cannot_leak_unrouted_rows() -> None:
    candidates = [
        {
            "lineage_id": f"lineage-{index}",
            "package_hash": str(index) * 64,
            "selected_candidate_id": f"candidate-{index}",
            "selected_candidate_summary": "不应下发的完整候选摘要" * 30,
        }
        for index in range(1, 4)
    ]
    rows = [
        {
            "system_name": f"system-{system_index:02d}",
            "data_type": "ode",
            "observations": [
                {
                    "lineage_id": candidate["lineage_id"],
                    "paired_log_effect": float(system_index),
                }
                for candidate in candidates
            ],
        }
        for system_index in range(20)
    ]
    fact = {
        "fact_id": "E125",
        "fact_kind": "cross_lineage_effect_matrix",
        "scope": "retained_selected_candidates_cross_lineage_full_evaluation",
        "source_locator": "signed.matrix",
        "value": {
            "schema_version": "cross-lineage-system-effect-matrix-v1",
            "matrix_hash": "f" * 64,
            "candidates": candidates,
            "coverage_ledger": [observation for row in rows for observation in row["observations"]],
            "comparable_system_rows": rows,
            "comparability_rule": "same frozen identity",
            "candidate_differences_jointly_confounded": True,
            "component_attribution_authorized": False,
            "confirmatory_use_requires_model_authored_component_ablation": True,
        },
    }

    projection = _worker_evidence_fact_view(
        fact,
        target_systems=("system-02", "system-07", "system-19"),
    )
    serialized = json.dumps(projection, ensure_ascii=False, sort_keys=True)

    assert [row["system_name"] for row in projection["value"]["comparable_system_rows"]] == [
        "system-02",
        "system-07",
        "system-19",
    ]
    assert "system-18" not in serialized
    assert "不应下发的完整候选摘要" not in serialized
    assert len(serialized) < 4_000


def test_chinese_opportunity_prose_allows_bound_machine_identifiers(
    tmp_path: Path,
) -> None:
    routing = _routing(tmp_path)
    binding = _binding_payload(routing.worker_binding("O01"))
    payload = _cell_payload(binding)
    systems = "、".join(binding["route"]["target_systems"])
    payload["unresolved_contradiction"] = (
        f"在{systems}三个目标系统中，task2694 与 task2695 的配对对数效应方向"
        "不一致，但候选差异仍被联合混杂，不能直接归因于单一组件。"
    )
    payload["independent_analysis_unit"] = (
        f"以{systems}三个目标系统为独立分析单位，实验条件与随机种子只作为"
        "系统内重复，绝不冒充独立样本。"
    )
    payload["method_application_trace"]["evidence_scope_audit"] = (
        "仅核对完整观测配对、基线可用性和配对对数效应，task2694 的谱系标识"
        "只作来源绑定，不扩展为新的科学事实。"
    )
    payload["method_application_trace"]["frozen_components"][0] = (
        "导数估计方法保持 Savitzky-Golay 技术配置冻结，不把命名标识当作英文叙述。"
    )

    assert ResearchOpportunityCell.model_validate(payload).cell_id == "O01"

    payload["negative_control"] = (
        "This is an English-only narrative that must still fail the Chinese gate."
    )
    with pytest.raises(SystemPlanOpportunityMapError, match="不是中文"):
        ResearchOpportunityCell.model_validate(payload)


def test_author_component_identity_attack_revokes_before_review(tmp_path: Path) -> None:
    routing = _routing(tmp_path)
    controller, capability = _controller(routing)
    completion = _DistributedCompletion(author_attack="swapped-component")

    with pytest.raises(DistributedOpportunityPipelineError, match="failed closed"):
        run_distributed_system_plan_opportunity_map(
            routing_artifact=routing,
            controller=controller,
            capability=capability,
            output_dir=tmp_path / "distributed",
            author_completion=completion,
            reviewer_completion=completion,
            clock=_NOW,
        )

    assert not capability.active
    assert (
        len(list((tmp_path / "distributed").glob("temporary-agents/batches/*/archives/*.json")))
        == 7
    )
    assert not any(
        json.loads(call["messages"][-1]["content"])["任务类型"] == "adversarial_critique"
        for call in completion.calls
    )


@pytest.mark.parametrize("rendering", ["wrong-target", "duplicate"])
def test_route_owned_author_metadata_is_derived_by_orchestrator(
    tmp_path: Path, rendering: str
) -> None:
    completion = _DistributedCompletion(author_attack=rendering)
    artifact, _ = _run(tmp_path, completion)

    for binding, cell in zip(
        artifact.worker_bindings,
        artifact.opportunity_map.opportunities,
        strict=True,
    ):
        assert cell.evidence_fact_ids == binding.route.evidence_fact_ids
        assert cell.literature_indices == binding.route.literature_indices
        assert cell.eligible_target_systems == binding.route.target_systems
        assert (
            cell.method_application_trace.verified_fact_ids
            == binding.route.evidence_fact_ids
        )


def test_author_worker_failure_archives_all_and_revokes(tmp_path: Path) -> None:
    routing = _routing(tmp_path)
    controller, capability = _controller(routing)
    completion = _DistributedCompletion(fail_author="O03")

    with pytest.raises(DistributedOpportunityPipelineError) as caught:
        run_distributed_system_plan_opportunity_map(
            routing_artifact=routing,
            controller=controller,
            capability=capability,
            output_dir=tmp_path / "distributed",
            author_completion=completion,
            reviewer_completion=completion,
            clock=_NOW,
        )

    assert caught.value.phase == "opportunity-author"
    assert caught.value.batch_artifact is not None
    assert caught.value.batch_artifact.failed_count == 1
    assert not capability.active
    assert (
        len(list((tmp_path / "distributed").glob("temporary-agents/batches/*/archives/*.json")))
        == 7
    )


def test_route_owned_reviewer_metadata_is_derived_after_all_fourteen_archives(
    tmp_path: Path,
) -> None:
    completion = _DistributedCompletion(reviewer_attack=True)
    artifact, capability = _run(tmp_path, completion)

    assert not capability.active
    assert (
        len(list((tmp_path / "distributed").glob("temporary-agents/batches/*/archives/*.json")))
        == 14
    )
    for binding, assessment in zip(
        artifact.worker_bindings,
        artifact.review.assessments,
        strict=True,
    ):
        assert assessment.supporting_fact_ids == binding.route.evidence_fact_ids
        assert (
            assessment.supporting_literature_indices
            == binding.route.literature_indices
        )


def test_all_reviewer_rejections_persist_diagnostic_artifact_but_no_binding(
    tmp_path: Path,
) -> None:
    routing = _routing(tmp_path)
    controller, capability = _controller(routing)
    completion = _DistributedCompletion(reject_all=True)

    with pytest.raises(DistributedOpportunityPipelineError) as caught:
        run_distributed_system_plan_opportunity_map(
            routing_artifact=routing,
            controller=controller,
            capability=capability,
            output_dir=tmp_path / "distributed",
            author_completion=completion,
            reviewer_completion=completion,
            clock=_NOW,
        )

    artifact = caught.value.distributed_artifact
    assert artifact is not None
    assert artifact.review.map_ready is False
    assert artifact.accepted_cells == ()
    with pytest.raises(DistributedOpportunityPipelineError):
        artifact.binding()
    assert not capability.active
    assert (tmp_path / "distributed" / "system-plan-opportunity-distributed.json").is_file()
