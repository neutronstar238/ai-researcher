"""The formal plan must preserve the exact prospective science selected upstream."""

from __future__ import annotations

from autoresearch.competition.system_authored_plan import (
    PlanScientificLineageAttestationV2,
    PlanScientificLineageBindingV2,
    _build_plan_scientific_lineage_binding,
    _lineage_attestation_findings,
    _plan_scientific_lineage_findings,
)
from tests.unit.competition.test_system_authored_plan import (
    _v2_attestation,
    _v2_context,
    _v2_plan,
)


def _binding() -> PlanScientificLineageBindingV2:
    binding = _build_plan_scientific_lineage_binding(_v2_context())
    assert isinstance(binding, PlanScientificLineageBindingV2)
    return binding


def test_v2_binding_and_attestation_preserve_exact_upstream_model_bytes() -> None:
    binding = _binding()
    direction = binding.selected_direction
    atom = binding.selected_prospective_atom()

    assert binding.source_opportunity_cell.cell_id == direction.opportunity_cell_id
    assert binding.selected_intervention_identity.atom_id == atom.atom_id
    assert binding.selected_intervention_identity.intervention_hash == (
        direction.prospective_intervention_hash
    )
    assert _lineage_attestation_findings(
        binding=binding,
        attestation=_v2_attestation(binding),
    ) == ()
    assert _plan_scientific_lineage_findings(
        plan=_v2_plan(binding),
        binding=binding,
    ) == ()


def test_token_only_plan_cannot_replace_the_selected_prospective_mechanism() -> None:
    binding = _binding()
    plan = _v2_plan(binding).model_copy(
        update={
            "abstract": "本摘要改写为另一个课题，但仍保留原方法标识符。",
            "rationale": "本理由改写为另一个课题，并只保留方法 token。",
        }
    )

    findings = _plan_scientific_lineage_findings(plan=plan, binding=binding)

    assert any("core_mechanism" in finding for finding in findings)


def test_v2_attestation_cannot_rewrite_the_selected_mechanism() -> None:
    binding = _binding()
    attestation = _v2_attestation(binding)
    assert isinstance(attestation, PlanScientificLineageAttestationV2)
    altered = attestation.model_copy(
        update={
            "core_mechanism": (
                "另一机制必须在冻结数据与独立分析单位上接受反事实检验，"
                "并明确保留零结果和替代解释。"
            )
        }
    )

    findings = _lineage_attestation_findings(binding=binding, attestation=altered)

    assert any("core_mechanism" in finding for finding in findings)
