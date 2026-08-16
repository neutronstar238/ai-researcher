"""Task 270.2: approved scientific prose must constrain the code that executes."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
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
    PairedControlTreatmentContract,
    PlanExecutionContractError,
    ProspectiveCandidatePlanAlignmentAudit,
    ProspectiveExecutionArmBinding,
    ProspectivePairedExecutionBinding,
    ProspectivePlanExecutionContract,
    audit_candidate_plan_alignment,
    audit_prospective_candidate_plan_alignment,
    build_prospective_candidate_execution_declaration,
    compile_plan_execution_contract,
    compile_system_authored_plan_execution_contract,
    derive_prospective_paired_execution_binding,
    extract_required_method_tokens,
    load_plan_execution_contract,
    load_prospective_plan_execution_contract,
    require_candidate_plan_alignment,
    require_prospective_candidate_plan_alignment,
    write_plan_execution_contract,
)
from autoresearch.competition.system_authored_plan import (
    PlanScientificLineageBindingV2,
    _build_plan_scientific_lineage_binding,
    author_research_plan,
)
from autoresearch.competition.system_plan_ideation import ResearchDirectionCandidate
from autoresearch.competition.system_plan_prospective_atoms import (
    ComponentExperimentBindingV2,
)
from autoresearch.llm.client import LLMJsonCompletionResult
from autoresearch.research.plan_confirmation import (
    ResearchPlanConfirmationError,
    record_plan_decision,
)
from autoresearch.schemas import ResearchPlan, ResearchPlanStatus
from tests.unit.competition import test_system_authored_plan as plan_v2_support


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


def _formal_plan_artifact(tmp_path: Path) -> Any:
    frozen_context = plan_v2_support._v2_context()
    binding = _build_plan_scientific_lineage_binding(frozen_context)
    assert isinstance(binding, PlanScientificLineageBindingV2)
    plan = plan_v2_support._v2_plan(binding)
    attestation = plan_v2_support._v2_attestation(binding)
    response = {
        "title": plan.title,
        "abstract": plan.abstract,
        "problem_statement": plan.problem_statement,
        "rationale": plan.rationale,
        "technical_details": plan.technical_details,
        "dataset_source": str(plan.datasets["source"]),
        "dataset_target": str(plan.datasets["target"]),
        "methods": plan.methods,
        "experiments": list(plan.experiments),
        "baselines": list(plan.baselines),
        "metrics": list(plan.metrics),
        "expected_results": plan.expected_results,
        # The model is instructed not to author the ``required_intervention_identity``
        # declaration itself; the orchestrator prepends exactly one canonical copy.
        # Strip the fixture's inline identity so the response replays like a
        # well-behaved model and the authorship receipt binds the scientific brief.
        "code_agent_brief": re.sub(
            r"required_intervention_identity\s*=\s*\{[^{}\r\n]+\}",
            "",
            plan.code_agent_brief,
        ).strip(),
        "risks_and_alternatives": list(plan.risks_and_alternatives),
        "references": list(plan.references),
        "scientific_lineage_attestation": attestation.model_dump(mode="json"),
    }
    evidence = tmp_path / "formal-prior-package.json"
    evidence.write_text("{}", encoding="utf-8")

    def formal_completion(**_kwargs: Any) -> LLMJsonCompletionResult:
        return LLMJsonCompletionResult(
            provider="qwen-dashscope",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_name="qwen3.7-max",
            endpoint=(
                "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
            ),
            response_text=json.dumps(response, ensure_ascii=False),
            parsed_json=response,
            usage={
                "prompt_tokens": 900,
                "completion_tokens": 1_100,
                "completion_tokens_details": {"reasoning_tokens": 2_100},
            },
            temperature=0.3,
            reasoning_text=(
                "本次推理逐项核对前瞻干预身份、观察基线、公开接口、目标系统、"
                "事实闭包、文献编号、单因子对照和冻结维度，并检查任何零结果均能"
                "反驳预注册机制。"
                * 3
            ),
            reasoning_transport="dashscope_enable_thinking",
        )

    return author_research_plan(
        lineage_id="formal-prospective-lineage",
        project_id="formal-prospective-project",
        candidate_id="formal-prospective-candidate",
        frozen_context=frozen_context,
        evidence_paths=[evidence],
        output_dir=tmp_path,
        completion=formal_completion,
        container_entry_points=("/harness/runner.py",),
        literature=tuple({"title": f"真实入选文献 {index}"} for index in range(1, 4)),
        require_chinese=False,
        max_attempts=1,
    )


def _formal_contract(tmp_path: Path) -> ProspectivePlanExecutionContract:
    return compile_system_authored_plan_execution_contract(
        _formal_plan_artifact(tmp_path)
    )


def _prospective_source(
    contract: ProspectivePlanExecutionContract,
    *,
    omit_hook: str | None = None,
    call_forbidden_anchor: bool = False,
    anchor_reads_declaration: bool = True,
    consume_runtime_configuration: bool = True,
    same_arm_helper: bool = False,
    bypass_hook: str | None = None,
    declaration_alias: bool = False,
    dead_selector: bool = False,
    anchor_bypass_return: bool = False,
) -> str:
    declaration = build_prospective_candidate_execution_declaration(contract)
    anchor = contract.implementation_anchor
    control_helper = f"{anchor}__control"
    treatment_helper = control_helper if same_arm_helper else f"{anchor}__treatment"
    identity_guards = (
        "    if payload['prospective_execution_binding']"
        "['plan_execution_contract_hash'] != "
        "PROSPECTIVE_EXECUTION_DECLARATION['plan_execution_contract_hash']:\n"
        "        raise ValueError('plan contract mismatch')\n"
        "    if payload['prospective_execution_binding']"
        "['selected_intervention_hash'] != "
        "PROSPECTIVE_EXECUTION_DECLARATION['selected_intervention_identity']"
        "['intervention_hash']:\n"
        "        raise ValueError('intervention mismatch')\n"
        "    if payload['prospective_execution_binding']['pair_contract_hash'] != "
        "PROSPECTIVE_EXECUTION_DECLARATION['paired_control_treatment']['pair_hash']:\n"
        "        raise ValueError('pair mismatch')\n"
        if anchor_reads_declaration
        else ""
    )
    runtime_value = (
        "payload['prospective_execution_binding']['configuration']["
        "PROSPECTIVE_EXECUTION_DECLARATION['paired_control_treatment']"
        "['intervention_key']]"
    )
    control_value = (
        "PROSPECTIVE_EXECUTION_DECLARATION['paired_control_treatment']"
        "['control_configuration'][PROSPECTIVE_EXECUTION_DECLARATION"
        "['paired_control_treatment']['intervention_key']]"
    )
    treatment_value = (
        "PROSPECTIVE_EXECUTION_DECLARATION['paired_control_treatment']"
        "['treatment_configuration'][PROSPECTIVE_EXECUTION_DECLARATION"
        "['paired_control_treatment']['intervention_key']]"
    )
    if consume_runtime_configuration:
        selector = (
            f"    if {runtime_value} == {control_value}:\n"
            f"        return {control_helper}(payload)\n"
            f"    if {runtime_value} == {treatment_value}:\n"
            f"        return {treatment_helper}(payload)\n"
            "    raise ValueError('unknown prospective arm')\n"
        )
    else:
        selector = f"    return {control_helper}(payload)\n"
    if dead_selector:
        selector = (
            "    if False:\n"
            + "".join(f"    {line}\n" for line in selector.splitlines())
            + f"    return {control_helper}(payload)\n"
        )
    elif not anchor_reads_declaration:
        selector = "    return payload\n"
    elif anchor_bypass_return:
        selector = (
            "    if payload.get('bypass'):\n"
            "        return payload\n"
            f"{selector}"
        )
    forbidden = ""
    forbidden_call = ""
    if call_forbidden_anchor:
        forbidden_name = contract.forbidden_implementation_anchors[0]
        forbidden = f"def {forbidden_name}(payload):\n    return payload\n\n"
        forbidden_call = f"    payload = {forbidden_name}(payload)\n"
    hooks = ""
    for hook in contract.public_hooks:
        if hook == omit_hook:
            continue
        if hook == bypass_hook:
            hooks += (
                f"def {hook}(payload):\n"
                "    if payload:\n"
                "        return payload\n"
                f"    return {anchor}(payload)\n\n"
            )
            continue
        hooks += (
            f"def {hook}(payload):\n"
            f"{forbidden_call}"
            f"    return {anchor}(payload)\n\n"
        )
    alias = (
        "DECL_ALIAS = PROSPECTIVE_EXECUTION_DECLARATION\n"
        "DECL_ALIAS['paired_control_treatment']['control_configuration'] = {}\n\n"
        if declaration_alias
        else ""
    )
    return (
        "PROSPECTIVE_EXECUTION_DECLARATION = "
        f"{declaration.model_dump(mode='python')!r}\n\n"
        f"{alias}"
        f"{forbidden}"
        f"def {control_helper}(payload):\n"
        "    return payload\n\n"
        + (
            ""
            if treatment_helper == control_helper
            else f"def {treatment_helper}(payload):\n    return payload\n\n"
        )
        + f"def {anchor}(payload):\n"
        f"{identity_guards}"
        f"{selector}\n"
        f"{hooks}"
    )


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


def test_formal_v2_contract_carries_exact_atom_baseline_scope_and_pair(
    tmp_path: Path,
) -> None:
    artifact = _formal_plan_artifact(tmp_path)
    contract = compile_system_authored_plan_execution_contract(artifact)
    assert compile_system_authored_plan_execution_contract(
        artifact.model_dump(mode="json")
    ) == contract
    atom = contract.selected_prospective_atom
    pair = contract.paired_control_treatment

    assert contract.schema_version == "plan-execution-contract-v2"
    assert contract.selected_intervention_identity.intervention_hash == (
        contract.selected_prospective_atom_hash
    )
    assert contract.baseline_observed_atom.atom_id == atom.baseline_observed_atom_id
    assert contract.baseline_observed_atom_hash == atom.baseline_observed_atom_hash
    assert contract.implementation_anchor == atom.implementation_anchor
    assert contract.public_hooks == atom.public_hooks
    assert contract.target_keys == atom.target_keys
    assert contract.target_systems == (
        "system_alpha",
        "system_beta",
        "system_gamma",
    )
    assert contract.supporting_fact_ids == atom.supporting_fact_ids
    assert contract.resource_request == atom.resource_request
    assert contract.selected_plan_reference_indices == (2, 3)
    assert pair.changed_keys == (atom.implementation_anchor,)
    mechanically_changed = tuple(
        key
        for key in pair.control_configuration
        if pair.control_configuration[key] != pair.treatment_configuration[key]
    )
    assert mechanically_changed == (atom.implementation_anchor,)

    write_plan_execution_contract(contract=contract, output_dir=tmp_path)
    assert load_prospective_plan_execution_contract(tmp_path) == contract
    with pytest.raises(PlanExecutionContractError, match="legacy v1 consumer"):
        load_plan_execution_contract(tmp_path)


def test_formal_prospective_plan_cannot_downgrade_to_token_contract(
    tmp_path: Path,
) -> None:
    artifact = _formal_plan_artifact(tmp_path)
    plan = ResearchPlan.model_validate(artifact.plan)

    with pytest.raises(PlanExecutionContractError, match="cannot downgrade"):
        compile_plan_execution_contract(plan)


def test_formal_pair_binding_derives_exact_arms_and_explicit_doubled_budget(
    tmp_path: Path,
) -> None:
    contract = _formal_contract(tmp_path)

    binding = derive_prospective_paired_execution_binding(contract)

    assert isinstance(binding, ProspectivePairedExecutionBinding)
    assert isinstance(binding.control_arm, ProspectiveExecutionArmBinding)
    assert binding.control_arm.arm_role == "control"
    assert binding.treatment_arm.arm_role == "treatment"
    assert binding.control_arm.configuration == (
        contract.paired_control_treatment.control_configuration
    )
    assert binding.treatment_arm.configuration == (
        contract.paired_control_treatment.treatment_configuration
    )
    changed = tuple(
        key
        for key in binding.control_arm.configuration
        if binding.control_arm.configuration[key]
        != binding.treatment_arm.configuration[key]
    )
    assert changed == (contract.implementation_anchor,)
    assert binding.arm_count == 2
    assert binding.total_seconds_budget == 2 * contract.resource_request.seconds_per_cell
    assert binding.total_memory_mb_allocation == (
        2 * contract.resource_request.memory_mb_per_cell
    )
    assert binding.total_cpu_core_allocation == (
        2 * contract.resource_request.cpu_cores_per_cell
    )
    assert binding.total_public_fit_call_budget == (
        2 * contract.resource_request.public_fit_calls_per_cell
    )
    assert binding.execution_authorized is False
    assert binding.is_scientific_evidence is False


def test_rehashed_formal_pair_binding_cannot_change_a_second_arm_key(
    tmp_path: Path,
) -> None:
    binding = derive_prospective_paired_execution_binding(_formal_contract(tmp_path))
    payload = binding.model_dump(mode="json")
    frozen_key = next(
        key
        for key in payload["treatment_arm"]["configuration"]
        if key.startswith("frozen::")
    )
    treatment = payload["treatment_arm"]
    treatment["configuration"][frozen_key] = "偷偷改变"
    treatment["configuration_hash"] = canonical_model_hash(
        treatment["configuration"]
    )
    treatment["arm_binding_hash"] = canonical_model_hash(
        {key: value for key, value in treatment.items() if key != "arm_binding_hash"}
    )
    payload["binding_hash"] = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "binding_hash"}
    )

    with pytest.raises(ValueError, match="paired control/treatment contract"):
        ProspectivePairedExecutionBinding.model_validate(payload)


def test_rehashed_pair_cannot_change_a_second_frozen_dimension(
    tmp_path: Path,
) -> None:
    pair = _formal_contract(tmp_path).paired_control_treatment
    payload = pair.model_dump(mode="json")
    frozen_key = next(
        key for key in payload["treatment_configuration"] if key.startswith("frozen::")
    )
    payload["treatment_configuration"][frozen_key] = "偷偷改变"
    payload["pair_hash"] = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "pair_hash"}
    )

    with pytest.raises(ValueError, match="changed_keys contradict"):
        PairedControlTreatmentContract.model_validate(payload)


def test_exact_formal_declaration_and_every_public_hook_are_required(
    tmp_path: Path,
) -> None:
    contract = _formal_contract(tmp_path)
    source = _prospective_source(contract)

    audit = audit_prospective_candidate_plan_alignment(
        candidate_id="prospective-aligned",
        source_text=source,
        contract=contract,
    )

    assert audit.passed is True
    assert audit.declaration_exact is True
    assert audit.anchor_reads_execution_declaration is True
    assert audit.schema_version == "candidate-plan-alignment-audit-v3"
    assert audit.declaration_read_only is True
    assert audit.runtime_configuration_consumed is True
    assert audit.arm_selector_dominates_scientific_returns is True
    assert audit.distinct_arm_helpers is True
    assert audit.control_helper == f"{contract.implementation_anchor}__control"
    assert audit.treatment_helper == f"{contract.implementation_anchor}__treatment"
    assert audit.hook_anchor_reachability == {
        "fit_equations": True,
        "predict_derivative": True,
    }
    assert audit.hook_anchor_dominance == {
        "fit_equations": True,
        "predict_derivative": True,
    }
    assert audit.mechanical_pair_diff_only_declared_intervention is True


def test_dead_code_declaration_reads_and_selector_are_not_execution_evidence(
    tmp_path: Path,
) -> None:
    contract = _formal_contract(tmp_path)

    audit = audit_prospective_candidate_plan_alignment(
        candidate_id="dead-selector",
        source_text=_prospective_source(contract, dead_selector=True),
        contract=contract,
    )

    assert audit.passed is False
    assert audit.runtime_configuration_consumed is False
    assert audit.arm_selector_dominates_scientific_returns is False
    assert any("reachable arm selector" in item for item in audit.findings)


def test_declaration_alias_and_alias_mutation_are_refused(
    tmp_path: Path,
) -> None:
    contract = _formal_contract(tmp_path)

    audit = audit_prospective_candidate_plan_alignment(
        candidate_id="declaration-alias",
        source_text=_prospective_source(contract, declaration_alias=True),
        contract=contract,
    )

    assert audit.passed is False
    assert audit.declaration_read_only is False
    assert any("alias" in item for item in audit.findings)


@pytest.mark.parametrize(
    "escaped_statement",
    [
        "DECL_BOX = [PROSPECTIVE_EXECUTION_DECLARATION]\n",
        (
            "def consume_declaration(value):\n"
            "    return value\n\n"
            "DECL_COPY = consume_declaration(PROSPECTIVE_EXECUTION_DECLARATION)\n"
        ),
        "del PROSPECTIVE_EXECUTION_DECLARATION['target_systems']\n",
    ],
)
def test_declaration_container_argument_and_delete_escape_are_refused(
    tmp_path: Path,
    escaped_statement: str,
) -> None:
    contract = _formal_contract(tmp_path)
    source = _prospective_source(contract).replace(
        "\n\ndef ", f"\n{escaped_statement}\ndef ", 1
    )

    audit = audit_prospective_candidate_plan_alignment(
        candidate_id="declaration-escape",
        source_text=source,
        contract=contract,
    )

    assert audit.passed is False
    assert audit.declaration_read_only is False


@pytest.mark.parametrize(
    ("source_kwargs", "expected_finding"),
    [
        ({"consume_runtime_configuration": False}, "runtime configuration"),
        ({"same_arm_helper": True}, "distinct control/treatment helpers"),
        ({"anchor_bypass_return": True}, "does not dominate every anchor return"),
        ({"bypass_hook": "fit_equations"}, "does not dominate every return"),
    ],
)
def test_formal_audit_rejects_runtime_arm_bypasses(
    tmp_path: Path,
    source_kwargs: dict[str, Any],
    expected_finding: str,
) -> None:
    contract = _formal_contract(tmp_path)

    audit = audit_prospective_candidate_plan_alignment(
        candidate_id="runtime-arm-bypass",
        source_text=_prospective_source(contract, **source_kwargs),
        contract=contract,
    )

    assert audit.passed is False
    assert any(expected_finding in item for item in audit.findings)


def test_v2_formal_audit_shape_cannot_be_grandfathered(
    tmp_path: Path,
) -> None:
    contract = _formal_contract(tmp_path)
    audit = audit_prospective_candidate_plan_alignment(
        candidate_id="formal-v3",
        source_text=_prospective_source(contract),
        contract=contract,
    )
    payload = audit.model_dump(mode="json")
    payload["schema_version"] = "candidate-plan-alignment-audit-v2"
    payload["audit_hash"] = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "audit_hash"}
    )

    with pytest.raises(ValueError, match="candidate-plan-alignment-audit-v3"):
        ProspectiveCandidatePlanAlignmentAudit.model_validate(payload)


@pytest.mark.parametrize("omit_hook", ["fit_equations", "predict_derivative"])
def test_one_reachable_hook_cannot_cover_for_a_missing_second_hook(
    tmp_path: Path,
    omit_hook: str,
) -> None:
    contract = _formal_contract(tmp_path)

    audit = audit_prospective_candidate_plan_alignment(
        candidate_id="missing-one-hook",
        source_text=_prospective_source(contract, omit_hook=omit_hook),
        contract=contract,
    )

    assert audit.passed is False
    assert audit.hook_anchor_reachability[omit_hook] is False
    assert any(omit_hook in item for item in audit.findings)


def test_callable_name_without_exact_identity_declaration_does_not_pass(
    tmp_path: Path,
) -> None:
    contract = _formal_contract(tmp_path)
    declaration = build_prospective_candidate_execution_declaration(contract)
    tampered = declaration.model_dump(mode="python")
    tampered["component_experiment_binding_hash"] = "f" * 64
    tampered["declaration_hash"] = canonical_model_hash(
        {key: value for key, value in tampered.items() if key != "declaration_hash"}
    )
    source = _prospective_source(contract).replace(
        repr(declaration.model_dump(mode="python")), repr(tampered), 1
    )

    audit = audit_prospective_candidate_plan_alignment(
        candidate_id="identity-tampered",
        source_text=source,
        contract=contract,
    )

    assert audit.passed is False
    assert audit.declaration_exact is False
    assert any("does not equal" in item for item in audit.findings)


def test_dead_declaration_and_non_selected_reachable_anchor_are_refused(
    tmp_path: Path,
) -> None:
    contract = _formal_contract(tmp_path)

    audit = audit_prospective_candidate_plan_alignment(
        candidate_id="confounded-anchor",
        source_text=_prospective_source(
            contract,
            call_forbidden_anchor=True,
            anchor_reads_declaration=False,
        ),
        contract=contract,
    )

    assert audit.passed is False
    assert audit.anchor_reads_execution_declaration is False
    assert audit.reachable_forbidden_implementation_anchors
    assert any("non-selected" in item for item in audit.findings)


def test_exact_declaration_cannot_be_mutated_after_initialization(
    tmp_path: Path,
) -> None:
    contract = _formal_contract(tmp_path)
    source = _prospective_source(contract).replace(
        "\n\ndef ",
        "\nPROSPECTIVE_EXECUTION_DECLARATION['target_systems'] = []\n\ndef ",
        1,
    )

    audit = audit_prospective_candidate_plan_alignment(
        candidate_id="mutated-declaration",
        source_text=source,
        contract=contract,
    )

    assert audit.passed is False
    assert audit.declaration_read_only is False
    assert any("mutated after" in item for item in audit.findings)


def test_rehashed_contract_cannot_select_an_atom_other_than_its_bound_direction(
    tmp_path: Path,
) -> None:
    contract = _formal_contract(tmp_path)
    payload = copy.deepcopy(contract.model_dump(mode="json"))
    lineage = payload["scientific_lineage_binding"]
    component = ComponentExperimentBindingV2.model_validate(
        lineage["component_experiment_binding"]
    )
    other_atom = component.prospective_components.atoms[1]
    other_identity = component.prospective_components.intervention_identities[1]
    direction = ResearchDirectionCandidate.model_validate(lineage["selected_direction"])
    aliases = {
        item.target_key: item.system_name
        for item in component.prospective_components.target_aliases
    }
    rebound_direction = direction.model_copy(
        update={
            "prospective_atom_id": other_atom.atom_id,
            "prospective_atom_hash": canonical_model_hash(other_atom),
            "prospective_intervention_hash": other_identity.intervention_hash,
            "prospective_origin_kind": other_identity.origin_kind,
            "target_systems": tuple(aliases[key] for key in other_atom.target_keys),
            "evidence_fact_ids": other_atom.supporting_fact_ids,
            "nearest_work_indices": tuple(
                item.retrieval_index + 1 for item in other_atom.literature_supports
            ),
        }
    )
    lineage["selected_direction"] = rebound_direction.model_dump(mode="json")
    lineage["selected_direction_hash"] = canonical_model_hash(rebound_direction)
    lineage["selected_intervention_identity"] = other_identity.model_dump(mode="json")
    lineage["binding_hash"] = canonical_model_hash(
        {key: value for key, value in lineage.items() if key != "binding_hash"}
    )
    payload["scientific_lineage_binding_hash"] = lineage["binding_hash"]
    payload["contract_hash"] = canonical_model_hash(
        {key: value for key, value in payload.items() if key != "contract_hash"}
    )

    with pytest.raises(ValueError, match="escaped its retained direction"):
        ProspectivePlanExecutionContract.model_validate(payload)


def test_v1_alignment_object_cannot_authorize_formal_candidate(
    tmp_path: Path,
) -> None:
    contract = _formal_contract(tmp_path)
    source = _prospective_source(contract)
    formal_audit = audit_prospective_candidate_plan_alignment(
        candidate_id="formal-candidate",
        source_text=source,
        contract=contract,
    )
    candidate = SimpleNamespace(
        candidate_id="formal-candidate",
        source_sha256=formal_audit.source_sha256,
        prospective_plan_alignment=formal_audit,
    )
    require_prospective_candidate_plan_alignment(
        candidates=[candidate], contract=contract
    )

    legacy_only = SimpleNamespace(
        candidate_id="legacy-only",
        source_sha256=formal_audit.source_sha256,
        plan_alignment=audit_candidate_plan_alignment(
            candidate_id="legacy-only",
            source_text=_ALIGNED_SOURCE,
            contract=compile_plan_execution_contract(_plan()),
        ),
    )
    with pytest.raises(PlanExecutionContractError, match="missing formal"):
        require_prospective_candidate_plan_alignment(
            candidates=[legacy_only], contract=contract
        )


def test_formal_audit_hash_binds_the_complete_source(tmp_path: Path) -> None:
    contract = _formal_contract(tmp_path)
    source = _prospective_source(contract)
    audit = audit_prospective_candidate_plan_alignment(
        candidate_id="formal-candidate",
        source_text=source,
        contract=contract,
    )

    assert isinstance(audit, ProspectiveCandidatePlanAlignmentAudit)
    assert audit.source_sha256 == hashlib.sha256(source.encode("utf-8")).hexdigest()
    changed = source + "\n# harmless source-byte change\n"
    changed_audit = audit_prospective_candidate_plan_alignment(
        candidate_id="formal-candidate",
        source_text=changed,
        contract=contract,
    )
    assert changed_audit.passed is True
    assert changed_audit.source_sha256 != audit.source_sha256
    assert changed_audit.audit_hash != audit.audit_hash

    contradictory = audit.model_dump(mode="json")
    contradictory["hook_anchor_reachability"]["fit_equations"] = False
    contradictory["audit_hash"] = canonical_model_hash(
        {key: value for key, value in contradictory.items() if key != "audit_hash"}
    )
    with pytest.raises(ValueError, match="verdict contradicts"):
        ProspectiveCandidatePlanAlignmentAudit.model_validate(contradictory)


def test_retained_config_name_is_an_unambiguous_legacy_contract() -> None:
    tokens = extract_required_method_tokens(
        "python /harness/runner.py --config "
        "integral_bayesian_constrained_lars.yaml --budget 252"
    )

    assert tokens == ("integral", "bayesian", "constrained", "lars")


def test_three_character_scientific_tokens_remain_source_verifiable() -> None:
    tokens = extract_required_method_tokens(
        "required_method_tokens=[sde, auc, spectral]"
    )

    assert tokens == ("sde", "auc", "spectral")


def test_two_character_scientific_tokens_remain_source_verifiable() -> None:
    contract = compile_plan_execution_contract(
        _plan(
            code_agent_brief=(
                "实现候选并运行 pytest。required_method_tokens=[ir, tv]"
            )
        )
    )
    source = """
def ir(values):
    return values

def tv(values):
    return values

def fit_equations(values):
    return tv(ir(values))

def predict_derivative(values):
    return tv(values)
"""

    audit = audit_candidate_plan_alignment(
        candidate_id="two-character-method",
        source_text=source,
        contract=contract,
    )

    assert contract.required_method_tokens == ("ir", "tv")
    assert audit.passed is True


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
    artifact = _formal_plan_artifact(tmp_path)
    config = OfficialLineageConfig(
        lineage_id="formal-prospective-lineage",
        work_dir=tmp_path,
        frozen_plan_path=tmp_path / "missing-frozen.json",
        autonomous_plan_path=tmp_path / "missing-autonomous.json",
        data_root=tmp_path / "missing-data",
    )
    config.plan_dir.mkdir(parents=True)
    (config.plan_dir / "research-plan.json").write_text(
        json.dumps(artifact.plan, ensure_ascii=False), encoding="utf-8"
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
