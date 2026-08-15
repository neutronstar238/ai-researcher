"""The system authors its own research plan; deterministic graders teach it.

Why this exists
---------------
`P-20260804-086`: `build_official_research_plan` contains no model call. Its
`problem_statement`, `rationale`, `technical_details`, and `expected_results` are
hardcoded string literals, so the scientific FRAMING of every lineage was authored by
an agent rather than by the system. The measured numbers were the system's; the science
around them was not.

This module inverts that. The model authors every prose field. Deterministic graders
decide whether what it wrote is acceptable, and on failure the exact grader findings go
back to the model so it can repair its own plan. Nothing here composes a scientific
claim, suggests a hypothesis, or supplies a sentence the plan can reuse.

The teaching mechanism
---------------------
A grader that only says "no" teaches nothing. Each refusal returns the specific finding
that caused it, so the model converges on the standard rather than guessing at it. This
is the same loop the candidate implementations already use, applied to the plan.

What is deterministic on purpose, and why
-----------------------------------------
* `evidence_refs` are derived from artifacts that EXIST on disk. If the model supplied
  them it could cite a package that was never written, and a plan that cites
  non-existent evidence is worse than one with no citations.
* `project_id` and `candidate_id` are identifiers, not science.
* Every frozen constraint is passed in as context and never re-authored.

Domain-agnostic: this module names no benchmark, stratum, metric, or method family. It
passes whatever frozen evidence it is given and grades whatever comes back.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, model_serializer, model_validator

from autoresearch.competition.language_guard import non_chinese_prose_fields
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.model_authorship import (
    record_model_authorship_receipt,
)
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.competition.plan_execution_contract import (
    PlanExecutionContractError,
    extract_required_method_tokens,
)
from autoresearch.competition.research_plan_markdown import (
    render_plan_artifact_markdown,
)
from autoresearch.competition.system_authored_outcome import (
    audit_numeric_traceability,
    collect_evidence_numbers,
)
from autoresearch.competition.system_plan_component_atoms import SystemPlanComponentAtom
from autoresearch.competition.system_plan_ideation import ResearchDirectionCandidate
from autoresearch.competition.system_plan_opportunity_map import (
    ResearchOpportunityCell,
)
from autoresearch.competition.system_plan_prospective_atoms import (
    ComponentExperimentBindingV2,
    ProspectiveComponentAtom,
    ProspectiveInterventionIdentity,
    ProspectiveResourceRequest,
)
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion
from autoresearch.research.plans import ResearchPlan, ResearchPlanStatus, audit_research_plan

_PLAN_NAME = "system-authored-research-plan.json"
_MAX_AUTHORING_ATTEMPTS = 8

# A plan must admit that its own expectation may fail. Without this a "plan" is an
# announcement of a result, and the preregistration protects nothing.
# A brief that names a script which does not exist is not executable, however
# command-shaped it looks. `P-20260804-089`: an authored brief invoked
# `pytest test_candidate.py` with flags that exist nowhere in the repository, and the
# quality rubric passed it because it contained the word `pytest`.
#
# Only HOST-relative script paths are checked. A brief legitimately references paths
# inside the pinned container (`/harness/runner.py`), which do not exist on the host,
# so absolute and container paths are out of scope for this guard.
_HOST_SCRIPT_PATTERN = re.compile(
    r"(?<![\w./\\-])(?!/)([A-Za-z0-9_][A-Za-z0-9_./\\-]*\.py)\b"
)

# Absolute paths were originally exempt so a brief could reference the pinned
# container. `P-20260804-089` continued: the system then satisfied the guard by
# inventing CONTAINER paths instead (`/app/run_grammar_conditioned_search.py`), so the
# exemption became an escape hatch. An absolute path is now only accepted if the caller
# declared it as a real entry point.
_ABSOLUTE_SCRIPT_PATTERN = re.compile(r"(/[A-Za-z0-9_][A-Za-z0-9_./-]*\.py)\b")

# `P-20260808-095`: 这些标记原本只有英文，而计划的交付语言是中文。系统若用中文撰写，
# 可反驳性检查会永远判定"未声明反驳条件"并拒收，于是系统被迫用英文写作才能通过自己的
# grader——语言混杂正是这么来的，不是模型的选择。
#
# 这与 `P-20260807-092` 同一缺陷类：grader 检的是词汇而非实质。标记因此改为中英双语，
# 让同一份判断在两种语言下都成立。
_FALSIFIABILITY_MARKERS: tuple[str, ...] = (
    # 英文
    "negative",
    "null",
    "may fail",
    "does not",
    "would refute",
    "if the effect",
    "not yet observed",
    "fails to",
    # 中文：反驳、零结果、未达成
    "反驳",
    "推翻",
    "否定",
    "零结果",
    "负结果",
    "负值",
    "无改进",
    "未能",
    "不成立",
    "若未",
    "如果未",
    "低于",
    "尚未观测",
    "有效结果",
)

# A preregistration must be allowed to choose NEW design constants.  Those constants
# are decisions, not observations: forbidding them unless they already occurred in a
# prior result made it impossible to pre-fix folds, thresholds, grids, or stopping
# rules.  Only an explicitly prospective clause in a design field receives this
# exemption.  Numeric claims in the problem, rationale, and expected result remain
# bound to frozen evidence.
_PROSPECTIVE_DESIGN_MARKERS: tuple[str, ...] = (
    "预先",
    "预注册",
    "计划",
    "拟采用",
    "将采用",
    "将使用",
    "设定",
    "固定为",
    "配置为",
    "选择",
    "取值",
    "限制为",
    "划分为",
    "预算为",
    "上限",
    "下限",
    "网格",
    "preregister",
    "pre-register",
    "preset",
    "plan to",
    "will use",
    "set to",
    "fixed at",
    "choose",
    "budget",
)
_DESIGN_CLAUSE_SPLIT = re.compile(r"[。！？!?；;，,\n]+")

# 行内引用形如 [1]、[2]，编号对应传入 surveyed_literature 的 index。
_CITATION_PATTERN = re.compile(r"\[(\d{1,2})\]")
_INTERVENTION_IDENTITY_PATTERN = re.compile(
    r"required_intervention_identity\s*=\s*(\{[^{}\r\n]+\})"
)

# 必须携带行内引用的字段。一份对先前工作零定位的文档不是研究计划。
_FIELDS_REQUIRING_CITATION: tuple[str, ...] = (
    "problem_statement",
    "rationale",
    "methods",
)

def authored_plan_non_chinese_fields(plan: ResearchPlan) -> tuple[str, ...]:
    """Return every model-authored plan field that is not predominantly Chinese.

    Machine identifiers, commands, and standard method names may remain Latin, but
    the surrounding title and scientific prose must be Chinese.  Bibliographic titles,
    DOI/URL values, and derived evidence paths are intentionally excluded.
    """

    prose_failures = non_chinese_prose_fields(
        {
            "title": plan.title,
            "abstract": plan.abstract,
            "problem_statement": plan.problem_statement,
            "rationale": plan.rationale,
            "technical_details": plan.technical_details,
            "datasets.source": plan.datasets.get("source", ""),
            "datasets.target": plan.datasets.get("target", ""),
            "methods": plan.methods,
            "experiments": plan.experiments,
            "baselines": plan.baselines,
            "metrics": plan.metrics,
            "results": plan.results,
            "expected_results": plan.expected_results,
            "risks_and_alternatives": plan.risks_and_alternatives,
        }
    )
    # The runnable brief necessarily carries a Python command, paths, flags, and the
    # literal method-token contract.  It still needs Chinese explanatory prose, but a
    # lower ratio prevents those required machine tokens from being mistaken for an
    # English narrative.
    brief_failures = non_chinese_prose_fields(
        {"code_agent_brief": plan.code_agent_brief}, minimum_ratio=0.35
    )
    return prose_failures + brief_failures


def authored_plan_control_character_fields(plan: ResearchPlan) -> tuple[str, ...]:
    """Locate invisible control bytes introduced by malformed JSON/LaTeX escapes."""

    values: dict[str, str | Sequence[str]] = {
        "title": plan.title,
        "abstract": plan.abstract,
        "problem_statement": plan.problem_statement,
        "rationale": plan.rationale,
        "technical_details": plan.technical_details,
        "datasets.source": str(plan.datasets.get("source", "")),
        "datasets.target": str(plan.datasets.get("target", "")),
        "methods": plan.methods,
        "experiments": plan.experiments,
        "baselines": plan.baselines,
        "metrics": plan.metrics,
        "results": plan.results,
        "expected_results": plan.expected_results,
        "code_agent_brief": plan.code_agent_brief,
        "risks_and_alternatives": plan.risks_and_alternatives,
        "references": plan.references,
    }
    failures: list[str] = []
    for name, value in values.items():
        items = (value,) if isinstance(value, str) else tuple(value)
        for index, item in enumerate(items):
            invalid = [
                char
                for char in str(item)
                if unicodedata.category(char) == "Cc" and char not in "\n\r\t"
            ]
            if invalid:
                failures.append(name if isinstance(value, str) else f"{name}[{index}]")
    return tuple(failures)


class SystemAuthoredPlanError(RuntimeError):
    """Raised when an authored plan cannot be accepted by its own graders."""


def _is_cjk_ideograph(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x2EBEF
        or 0x2F800 <= codepoint <= 0x2FA1F
        or 0x30000 <= codepoint <= 0x323AF
    )


def _missing_required_chinese_prose(
    fields: Mapping[str, str | Sequence[str]],
) -> tuple[str, ...]:
    """Reject blank or non-Chinese prose without imposing stylistic length quotas."""

    failed: list[str] = []
    for name, value in fields.items():
        items = (value,) if isinstance(value, str) else tuple(value)
        for index, item in enumerate(items):
            text = str(item).strip()
            if not text or not any(_is_cjk_ideograph(char) for char in text):
                failed.append(name if isinstance(value, str) else f"{name}[{index}]")
    return tuple(failed)


class PlanScientificLineageBinding(StrictFrozenModel):
    """Historical opportunity-cell lineage, retained for v1 artifact loading only.

    This schema predates prospective component identities.  New formal plan lineages
    must use :class:`PlanScientificLineageBindingV2`; keeping this model separate lets
    old immutable artifacts round-trip without letting the broad opportunity cell
    silently become the treatment definition for a new experiment.
    """

    schema_version: Literal["plan-scientific-lineage-binding-v1"] = (
        "plan-scientific-lineage-binding-v1"
    )
    method_skill_selection_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    opportunity_map_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_opportunity_cell: ResearchOpportunityCell
    source_opportunity_cell_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    ideation_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_direction: ResearchDirectionCandidate
    selected_direction_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_binding(self) -> PlanScientificLineageBinding:
        expected_cell_hash = canonical_model_hash(
            self.source_opportunity_cell.model_dump(mode="json")
        )
        if self.source_opportunity_cell_hash != expected_cell_hash:
            raise SystemAuthoredPlanError("source opportunity cell hash mismatch")
        expected_direction_hash = canonical_model_hash(
            self.selected_direction.model_dump(mode="json")
        )
        if self.selected_direction_hash != expected_direction_hash:
            raise SystemAuthoredPlanError("selected research direction hash mismatch")
        if (
            self.selected_direction.opportunity_cell_id
            != self.source_opportunity_cell.cell_id
        ):
            raise SystemAuthoredPlanError(
                "selected direction does not bind its source opportunity cell"
            )
        if not set(self.selected_direction.target_systems).issubset(
            self.source_opportunity_cell.eligible_target_systems
        ):
            raise SystemAuthoredPlanError(
                "selected direction targets escape its source opportunity cell"
            )
        if not set(self.selected_direction.evidence_fact_ids).issubset(
            self.source_opportunity_cell.evidence_fact_ids
        ):
            raise SystemAuthoredPlanError(
                "selected direction facts escape its source opportunity cell"
            )
        if not set(self.source_opportunity_cell.literature_indices).issubset(
            self.selected_direction.nearest_work_indices
        ):
            raise SystemAuthoredPlanError(
                "selected direction dropped source opportunity prior work"
            )
        expected_binding_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"binding_hash"})
        )
        if self.binding_hash != expected_binding_hash:
            raise SystemAuthoredPlanError("plan scientific lineage binding hash mismatch")
        return self


class PlanScientificLineageBindingV2(StrictFrozenModel):
    """Exact opportunity→future atom→direction lineage for a formal new plan.

    The opportunity cell is only the problem-motivation link.  Experimental scope is
    derived exclusively from the independently reviewed prospective atom, its target
    aliases, its literature supports, and its observed control atom.
    """

    schema_version: Literal["plan-scientific-lineage-binding-v2"] = (
        "plan-scientific-lineage-binding-v2"
    )
    method_skill_selection_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    opportunity_map_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_opportunity_cell: ResearchOpportunityCell
    source_opportunity_cell_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    component_experiment_binding: ComponentExperimentBindingV2
    component_experiment_binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    ideation_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_direction: ResearchDirectionCandidate
    selected_direction_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_intervention_identity: ProspectiveInterventionIdentity
    binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    def selected_prospective_atom(self) -> ProspectiveComponentAtom:
        """Return the one atom named by the selected direction, or fail closed."""

        matches = tuple(
            atom
            for atom in self.component_experiment_binding.prospective_components.atoms
            if atom.atom_id == self.selected_direction.prospective_atom_id
        )
        if len(matches) != 1:
            raise SystemAuthoredPlanError(
                "selected direction must bind exactly one prospective component atom"
            )
        return matches[0]

    def selected_observed_baseline_atom(self) -> SystemPlanComponentAtom:
        """Return the exact observed control atom named by the future intervention."""

        atom = self.selected_prospective_atom()
        matches = tuple(
            observed
            for observed in self.component_experiment_binding.observed_components.atoms
            if observed.atom_id == atom.baseline_observed_atom_id
        )
        if len(matches) != 1:
            raise SystemAuthoredPlanError(
                "selected prospective atom must bind exactly one observed baseline"
            )
        return matches[0]

    def selected_plan_reference_indices(self) -> tuple[int, ...]:
        """Return selected-survey indices used by public plan citations.

        `ResearchDirectionCandidate.nearest_work_indices` intentionally uses the full
        retrieved-catalogue one-based domain.  Public plan citations use the compact
        selected-survey `reference_index` domain, so the two must never be conflated.
        """

        return tuple(
            support.reference_index
            for support in self.selected_prospective_atom().literature_supports
        )

    def selected_target_systems(self) -> tuple[str, ...]:
        """Resolve the selected atom's anonymous target keys without model inference."""

        aliases = {
            item.target_key: item.system_name
            for item in self.component_experiment_binding.prospective_components.target_aliases
        }
        atom = self.selected_prospective_atom()
        try:
            return tuple(aliases[key] for key in atom.target_keys)
        except KeyError as exc:
            raise SystemAuthoredPlanError(
                f"selected prospective atom references unknown target alias {exc.args[0]}"
            ) from exc

    @model_validator(mode="after")
    def _validate_binding(self) -> PlanScientificLineageBindingV2:
        expected_cell_hash = canonical_model_hash(
            self.source_opportunity_cell.model_dump(mode="json")
        )
        if self.source_opportunity_cell_hash != expected_cell_hash:
            raise SystemAuthoredPlanError("source opportunity cell hash mismatch")
        if (
            self.component_experiment_binding.binding_hash
            != self.component_experiment_binding_hash
        ):
            raise SystemAuthoredPlanError(
                "component experiment binding retained hash mismatch"
            )
        expected_direction_hash = canonical_model_hash(
            self.selected_direction.model_dump(mode="json")
        )
        if self.selected_direction_hash != expected_direction_hash:
            raise SystemAuthoredPlanError("selected research direction hash mismatch")
        if (
            self.selected_direction.opportunity_cell_id
            != self.source_opportunity_cell.cell_id
        ):
            raise SystemAuthoredPlanError(
                "selected direction does not bind its problem-motivation opportunity cell"
            )
        if (
            self.component_experiment_binding.observed_components.method_skill_selection_artifact_hash
            != self.method_skill_selection_artifact_hash
        ):
            raise SystemAuthoredPlanError(
                "component experiment binding uses a different method skill selection"
            )

        atom = self.selected_prospective_atom()
        atom_hash = canonical_model_hash(atom.model_dump(mode="json"))
        identities = tuple(
            identity
            for identity in self.component_experiment_binding.prospective_components.intervention_identities
            if identity.atom_id == atom.atom_id
        )
        if len(identities) != 1 or self.selected_intervention_identity != identities[0]:
            raise SystemAuthoredPlanError(
                "selected intervention identity is not the exact prospective binding projection"
            )
        if (
            self.selected_direction.prospective_atom_hash != atom_hash
            or self.selected_direction.prospective_intervention_hash
            != self.selected_intervention_identity.intervention_hash
            or self.selected_direction.prospective_origin_kind
            != self.selected_intervention_identity.origin_kind
        ):
            raise SystemAuthoredPlanError(
                "selected direction did not inherit the prospective atom identity exactly"
            )
        baseline = self.selected_observed_baseline_atom()
        if (
            atom.baseline_observed_atom_hash
            != canonical_model_hash(baseline.model_dump(mode="json"))
        ):
            raise SystemAuthoredPlanError(
                "selected prospective atom observed baseline hash mismatch"
            )
        if self.selected_direction.target_systems != self.selected_target_systems():
            raise SystemAuthoredPlanError(
                "selected direction targets are not the exact prospective alias projection"
            )
        if self.selected_direction.evidence_fact_ids != atom.supporting_fact_ids:
            raise SystemAuthoredPlanError(
                "selected direction facts are not the exact prospective atom facts"
            )
        expected_catalogue_indices = tuple(
            support.retrieval_index + 1 for support in atom.literature_supports
        )
        if self.selected_direction.nearest_work_indices != expected_catalogue_indices:
            raise SystemAuthoredPlanError(
                "selected direction literature is not the exact full-catalogue projection"
            )
        expected_binding_hash = canonical_model_hash(
            self.model_dump(mode="json", exclude={"binding_hash"})
        )
        if self.binding_hash != expected_binding_hash:
            raise SystemAuthoredPlanError("plan scientific lineage v2 binding hash mismatch")
        return self


class PlanScientificLineageAttestation(StrictFrozenModel):
    """Historical v1 model declaration, retained for artifact loading."""

    source_opportunity_cell_id: str = Field(pattern=r"^O0[1-7]$")
    selected_direction_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_direction_title: str = Field(min_length=1)
    target_systems: tuple[str, ...] = Field(min_length=1)
    evidence_fact_ids: tuple[str, ...] = Field(min_length=2)
    nearest_work_indices: tuple[int, ...] = Field(min_length=3)
    method_tokens: tuple[str, ...] = Field(min_length=2, max_length=8)
    core_mechanism: str = Field(min_length=1)
    falsifiable_hypothesis: str = Field(min_length=1)
    alternative_explanation: str = Field(min_length=1)
    decisive_test: str = Field(min_length=1)
    negative_control: str = Field(min_length=1)
    sensitivity_control: str = Field(min_length=1)
    orthogonal_diagnostic: str = Field(min_length=1)
    independent_analysis_unit: str = Field(min_length=1)
    result_blind_decision_rule: str = Field(min_length=1)
    continuity_explanation: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_attestation(self) -> PlanScientificLineageAttestation:
        for label, values in (
            ("target_systems", self.target_systems),
            ("evidence_fact_ids", self.evidence_fact_ids),
            ("nearest_work_indices", self.nearest_work_indices),
            ("method_tokens", tuple(token.casefold() for token in self.method_tokens)),
        ):
            if len(set(values)) != len(values):
                raise SystemAuthoredPlanError(f"{label} in lineage attestation repeats")
        prose = {
            "selected_direction_title": self.selected_direction_title,
            "core_mechanism": self.core_mechanism,
            "falsifiable_hypothesis": self.falsifiable_hypothesis,
            "alternative_explanation": self.alternative_explanation,
            "decisive_test": self.decisive_test,
            "negative_control": self.negative_control,
            "sensitivity_control": self.sensitivity_control,
            "orthogonal_diagnostic": self.orthogonal_diagnostic,
            "independent_analysis_unit": self.independent_analysis_unit,
            "result_blind_decision_rule": self.result_blind_decision_rule,
            "continuity_explanation": self.continuity_explanation,
        }
        non_chinese = _missing_required_chinese_prose(prose)
        non_chinese += non_chinese_prose_fields(prose)
        if non_chinese:
            raise SystemAuthoredPlanError(
                f"plan scientific lineage attestation is not Chinese: {list(non_chinese)}"
            )
        return self


class PlanScientificLineageAttestationV2(PlanScientificLineageAttestation):
    """Model-authored exact declaration of the future treatment/control contract."""

    schema_version: Literal["plan-scientific-lineage-attestation-v2"] = (
        "plan-scientific-lineage-attestation-v2"
    )
    nearest_work_indices: tuple[int, ...] = Field(min_length=2)
    component_experiment_binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_intervention_identity: ProspectiveInterventionIdentity
    change_mode: Literal["替换", "消融", "参数化"]
    control_level_zh: str = Field(min_length=1)
    intervention_level_zh: str = Field(min_length=1)
    single_factor_rationale_zh: str = Field(min_length=1)
    falsifiable_single_factor_contrast_zh: str = Field(min_length=1)
    frozen_dimensions: tuple[str, ...] = Field(min_length=1)
    resource_request: ProspectiveResourceRequest
    selected_plan_reference_indices: tuple[int, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def _validate_v2_attestation(self) -> PlanScientificLineageAttestationV2:
        for label, values in (
            ("frozen_dimensions", self.frozen_dimensions),
            ("selected_plan_reference_indices", self.selected_plan_reference_indices),
        ):
            if len(set(values)) != len(values):
                raise SystemAuthoredPlanError(f"{label} in lineage attestation repeats")
        prose = {
            "control_level_zh": self.control_level_zh,
            "intervention_level_zh": self.intervention_level_zh,
            "single_factor_rationale_zh": self.single_factor_rationale_zh,
            "falsifiable_single_factor_contrast_zh": (
                self.falsifiable_single_factor_contrast_zh
            ),
            "frozen_dimensions": self.frozen_dimensions,
        }
        non_chinese = _missing_required_chinese_prose(prose)
        non_chinese += non_chinese_prose_fields(
            prose,
            exempt_identifiers=(
                self.selected_intervention_identity.implementation_anchor,
                *self.selected_intervention_identity.public_hooks,
            ),
        )
        if non_chinese:
            raise SystemAuthoredPlanError(
                f"plan scientific lineage v2 attestation is not Chinese: "
                f"{list(non_chinese)}"
            )
        return self


def _build_plan_scientific_lineage_binding(
    frozen_context: Mapping[str, Any],
) -> PlanScientificLineageBinding | PlanScientificLineageBindingV2 | None:
    """Materialize the official prospective lineage without authoring science.

    A context with no formal prospective routing remains an isolated/legacy caller.
    The moment any prospective routing object is present, all objects are mandatory;
    there is no fallback to the historical opportunity-cell-only binding.
    """

    ideation_hash = frozen_context.get("system_plan_ideation_artifact_hash")
    raw_direction = frozen_context.get("system_selected_research_direction")
    formal_prospective_context = any(
        key in frozen_context
        for key in (
            "system_component_atom_catalog",
            "system_prospective_component_atoms",
            "system_component_experiment_binding",
        )
    ) or (
        isinstance(raw_direction, Mapping)
        and raw_direction.get("schema_version") == "research-direction-candidate-v2"
    )
    if ideation_hash is None:
        if formal_prospective_context:
            raise SystemAuthoredPlanError(
                "prospective plan context is missing its ideation artifact hash"
            )
        return None
    method_binding = frozen_context.get("system_selected_method_skills")
    opportunity_map = frozen_context.get("system_audited_research_opportunity_map")
    raw_direction_hash = frozen_context.get("system_selected_research_direction_hash")
    raw_combined = frozen_context.get("system_component_experiment_binding")
    raw_observed = frozen_context.get("system_component_atom_catalog")
    raw_prospective = frozen_context.get("system_prospective_component_atoms")
    if not isinstance(method_binding, Mapping):
        raise SystemAuthoredPlanError(
            "official plan lineage is missing its method skill selection binding"
        )
    if not isinstance(opportunity_map, Mapping):
        raise SystemAuthoredPlanError(
            "official plan lineage is missing its audited opportunity map binding"
        )
    if not isinstance(raw_direction, Mapping):
        raise SystemAuthoredPlanError(
            "official plan lineage is missing its selected research direction"
        )
    if not isinstance(raw_combined, Mapping):
        raise SystemAuthoredPlanError(
            "official plan lineage is missing its component experiment binding"
        )
    if not isinstance(raw_observed, Mapping):
        raise SystemAuthoredPlanError(
            "official plan lineage is missing its observed component binding"
        )
    if not isinstance(raw_prospective, Mapping):
        raise SystemAuthoredPlanError(
            "official plan lineage is missing its prospective component binding"
        )
    try:
        direction = ResearchDirectionCandidate.model_validate(raw_direction)
    except (ValidationError, ValueError, RuntimeError) as exc:
        raise SystemAuthoredPlanError(
            f"official selected direction is malformed: {exc}"
        ) from exc
    try:
        combined = ComponentExperimentBindingV2.model_validate(raw_combined)
    except (ValidationError, ValueError, RuntimeError) as exc:
        raise SystemAuthoredPlanError(
            f"official component experiment binding is malformed: {exc}"
        ) from exc
    if canonical_model_hash(dict(raw_observed)) != canonical_model_hash(
        combined.observed_components.model_dump(mode="json")
    ):
        raise SystemAuthoredPlanError(
            "official observed component binding is not the exact combined projection"
        )
    if canonical_model_hash(dict(raw_prospective)) != canonical_model_hash(
        combined.prospective_components.model_dump(mode="json")
    ):
        raise SystemAuthoredPlanError(
            "official prospective component binding is not the exact combined projection"
        )
    if (
        method_binding.get("selection_artifact_hash")
        != combined.observed_components.method_skill_selection_artifact_hash
    ):
        raise SystemAuthoredPlanError(
            "official component experiment binding uses a different method skill selection"
        )
    expected_direction_hash = canonical_model_hash(direction.model_dump(mode="json"))
    if raw_direction_hash != expected_direction_hash:
        raise SystemAuthoredPlanError(
            "official selected direction bytes do not match their retained hash"
        )
    raw_cells = opportunity_map.get("accepted_cells")
    if not isinstance(raw_cells, Sequence) or isinstance(raw_cells, str | bytes):
        raise SystemAuthoredPlanError(
            "official opportunity map has no materialized accepted cells"
        )
    try:
        cells = tuple(ResearchOpportunityCell.model_validate(item) for item in raw_cells)
    except (ValidationError, ValueError) as exc:
        raise SystemAuthoredPlanError(
            f"official accepted opportunity cell is malformed: {exc}"
        ) from exc
    matching_cells = tuple(
        item for item in cells if item.cell_id == direction.opportunity_cell_id
    )
    if len(matching_cells) != 1:
        raise SystemAuthoredPlanError(
            "official selected direction must bind exactly one accepted opportunity cell"
        )
    cell = matching_cells[0]
    payload: dict[str, Any] = {
        "schema_version": "plan-scientific-lineage-binding-v2",
        "method_skill_selection_artifact_hash": method_binding.get(
            "selection_artifact_hash"
        ),
        "opportunity_map_artifact_hash": opportunity_map.get("artifact_hash"),
        "source_opportunity_cell": cell.model_dump(mode="json"),
        "source_opportunity_cell_hash": canonical_model_hash(
            cell.model_dump(mode="json")
        ),
        "component_experiment_binding": combined.model_dump(mode="json"),
        "component_experiment_binding_hash": combined.binding_hash,
        "ideation_artifact_hash": ideation_hash,
        "selected_direction": direction.model_dump(mode="json"),
        "selected_direction_hash": expected_direction_hash,
    }
    matching_identities = tuple(
        identity
        for identity in combined.prospective_components.intervention_identities
        if identity.atom_id == direction.prospective_atom_id
    )
    if len(matching_identities) != 1:
        raise SystemAuthoredPlanError(
            "official selected direction must bind exactly one intervention identity"
        )
    payload["selected_intervention_identity"] = matching_identities[0].model_dump(
        mode="json"
    )
    payload["binding_hash"] = canonical_model_hash(payload)
    try:
        return PlanScientificLineageBindingV2.model_validate(payload)
    except (ValidationError, ValueError, RuntimeError) as exc:
        raise SystemAuthoredPlanError(
            f"official plan scientific lineage binding is invalid: {exc}"
        ) from exc


def _lineage_attestation_expected_fields(
    binding: PlanScientificLineageBinding | PlanScientificLineageBindingV2,
) -> dict[str, Any]:
    """Return exact upstream-owned attestation fields, excluding new explanation."""

    direction = binding.selected_direction
    expected: dict[str, Any] = {
        "source_opportunity_cell_id": direction.opportunity_cell_id,
        "selected_direction_hash": binding.selected_direction_hash,
        "selected_direction_title": direction.title,
        "target_systems": list(direction.target_systems),
        "evidence_fact_ids": list(direction.evidence_fact_ids),
        "nearest_work_indices": list(direction.nearest_work_indices),
        "method_tokens": list(direction.method_tokens),
        "core_mechanism": direction.core_mechanism,
        "falsifiable_hypothesis": direction.falsifiable_hypothesis,
        "alternative_explanation": direction.alternative_explanation,
        "decisive_test": direction.decisive_test,
        "negative_control": direction.negative_control,
        "sensitivity_control": direction.sensitivity_control,
        "orthogonal_diagnostic": direction.orthogonal_diagnostic,
        "independent_analysis_unit": direction.independent_analysis_unit,
        "result_blind_decision_rule": direction.result_blind_decision_rule,
    }
    if isinstance(binding, PlanScientificLineageBindingV2):
        atom = binding.selected_prospective_atom()
        expected.update(
            {
                "schema_version": "plan-scientific-lineage-attestation-v2",
                "component_experiment_binding_hash": (
                    binding.component_experiment_binding_hash
                ),
                "selected_intervention_identity": (
                    binding.selected_intervention_identity.model_dump(mode="json")
                ),
                "change_mode": atom.change_mode,
                "control_level_zh": atom.control_level_zh,
                "intervention_level_zh": atom.intervention_level_zh,
                "single_factor_rationale_zh": atom.single_factor_rationale_zh,
                "falsifiable_single_factor_contrast_zh": (
                    atom.falsifiable_single_factor_contrast_zh
                ),
                "frozen_dimensions": list(atom.frozen_dimensions),
                "resource_request": atom.resource_request.model_dump(mode="json"),
                "selected_plan_reference_indices": list(
                    binding.selected_plan_reference_indices()
                ),
            }
        )
    return expected


def _project_lineage_attestation(
    *,
    binding: PlanScientificLineageBinding | PlanScientificLineageBindingV2,
    continuity_explanation: str,
) -> PlanScientificLineageAttestation | PlanScientificLineageAttestationV2:
    """Attach one Qwen-authored explanation to the exact upstream identity bytes."""

    payload = _lineage_attestation_expected_fields(binding)
    payload["continuity_explanation"] = continuity_explanation
    model_type = (
        PlanScientificLineageAttestationV2
        if isinstance(binding, PlanScientificLineageBindingV2)
        else PlanScientificLineageAttestation
    )
    return model_type.model_validate(payload)


def _lineage_attestation_findings(
    *,
    binding: PlanScientificLineageBinding | PlanScientificLineageBindingV2,
    attestation: (
        PlanScientificLineageAttestation | PlanScientificLineageAttestationV2 | None
    ),
) -> tuple[str, ...]:
    """Compare a model declaration to exact upstream model-owned bytes."""

    if attestation is None:
        return ("缺少 scientific_lineage_attestation，无法证明计划延续入选方向",)
    if isinstance(binding, PlanScientificLineageBindingV2):
        if not isinstance(attestation, PlanScientificLineageAttestationV2):
            return ("正式前瞻谱系必须提供 scientific_lineage_attestation v2",)
        expected_v2 = _lineage_attestation_expected_fields(binding)
        actual_v2 = attestation.model_dump(mode="json")
        return tuple(
            f"scientific_lineage_attestation.{field_name} 未逐字继承正式前瞻谱系"
            for field_name, expected_value in expected_v2.items()
            if actual_v2.get(field_name) != expected_value
        )
    if isinstance(attestation, PlanScientificLineageAttestationV2):
        return ("历史 v1 谱系不得承载 prospective scientific attestation",)
    expected = _lineage_attestation_expected_fields(binding)
    actual = attestation.model_dump(mode="json")
    findings = [
        f"scientific_lineage_attestation.{field_name} 未逐字继承入选方向"
        for field_name, expected_value in expected.items()
        if actual.get(field_name) != expected_value
    ]
    return tuple(findings)


def _plan_scientific_lineage_findings(
    *,
    plan: ResearchPlan,
    binding: PlanScientificLineageBinding | PlanScientificLineageBindingV2,
) -> tuple[str, ...]:
    """Refuse plans that paste lineage prose in the wrong field or change identity."""

    if isinstance(binding, PlanScientificLineageBindingV2):
        return _plan_scientific_lineage_v2_findings(plan=plan, binding=binding)

    direction = binding.selected_direction
    experiments = "\n".join(plan.experiments)
    risks = "\n".join(plan.risks_and_alternatives)
    design_corpus = "\n".join(
        (
            plan.technical_details,
            plan.methods,
            experiments,
            "\n".join(plan.baselines),
            "\n".join(plan.metrics),
            risks,
            plan.code_agent_brief,
        )
    )
    requirements: tuple[tuple[str, str, str], ...] = (
        ("selected_direction_title", direction.title, plan.title),
        (
            "scientific_gap",
            direction.scientific_gap,
            "\n".join((plan.abstract, plan.problem_statement, plan.rationale)),
        ),
        (
            "challenged_assumption",
            direction.challenged_assumption,
            "\n".join((plan.problem_statement, plan.rationale)),
        ),
        (
            "core_mechanism",
            direction.core_mechanism,
            "\n".join((plan.abstract, plan.rationale, plan.technical_details, plan.methods)),
        ),
        (
            "falsifiable_hypothesis",
            direction.falsifiable_hypothesis,
            "\n".join((plan.abstract, plan.expected_results)),
        ),
        (
            "alternative_explanation",
            direction.alternative_explanation,
            "\n".join((experiments, risks)),
        ),
        ("decisive_test", direction.decisive_test, design_corpus),
        ("negative_control", direction.negative_control, design_corpus),
        ("sensitivity_control", direction.sensitivity_control, design_corpus),
        ("orthogonal_diagnostic", direction.orthogonal_diagnostic, design_corpus),
        (
            "independent_analysis_unit",
            direction.independent_analysis_unit,
            design_corpus,
        ),
        (
            "result_blind_decision_rule",
            direction.result_blind_decision_rule,
            design_corpus,
        ),
    )
    findings = [
        f"计划未逐字保留入选方向的 {field_name}，不得只粘贴 method token 后偷换课题"
        for field_name, required_text, corpus in requirements
        if required_text not in corpus
    ]
    target_corpus = "\n".join((str(plan.datasets.get("target", "")), experiments))
    missing_targets = [
        target for target in direction.target_systems if target not in target_corpus
    ]
    if missing_targets:
        findings.append(f"计划遗漏入选方向目标系统：{missing_targets}")
    citation_corpus = "\n".join(
        (plan.problem_statement, plan.rationale, plan.methods, experiments)
    )
    missing_citations = [
        index
        for index in direction.nearest_work_indices
        if f"[{index}]" not in citation_corpus
    ]
    if missing_citations:
        findings.append(f"计划遗漏入选方向近邻文献编号：{missing_citations}")
    return tuple(findings)


def _contains_identifier(text: str, identifier: str) -> bool:
    return bool(
        re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(identifier)}(?![A-Za-z0-9_])",
            text,
        )
    )


def _plan_scientific_lineage_v2_findings(
    *, plan: ResearchPlan, binding: PlanScientificLineageBindingV2
) -> tuple[str, ...]:
    """Apply field-local checks to the exact future intervention contract."""

    direction = binding.selected_direction
    atom = binding.selected_prospective_atom()
    experiments = "\n".join(plan.experiments)
    risks = "\n".join(plan.risks_and_alternatives)
    findings: list[str] = []

    direction_requirements: tuple[tuple[str, str, str], ...] = (
        ("selected_direction_title", direction.title, plan.title),
        (
            "scientific_gap",
            direction.scientific_gap,
            "\n".join((plan.problem_statement, plan.rationale)),
        ),
        (
            "challenged_assumption",
            direction.challenged_assumption,
            "\n".join((plan.problem_statement, plan.rationale)),
        ),
        (
            "core_mechanism",
            direction.core_mechanism,
            "\n".join((plan.abstract, plan.rationale)),
        ),
        (
            "falsifiable_hypothesis",
            direction.falsifiable_hypothesis,
            "\n".join((plan.abstract, plan.expected_results)),
        ),
        ("alternative_explanation", direction.alternative_explanation, risks),
        ("decisive_test", direction.decisive_test, experiments),
        ("negative_control", direction.negative_control, experiments),
        ("sensitivity_control", direction.sensitivity_control, experiments),
        ("orthogonal_diagnostic", direction.orthogonal_diagnostic, experiments),
        (
            "independent_analysis_unit",
            direction.independent_analysis_unit,
            experiments,
        ),
        (
            "result_blind_decision_rule",
            direction.result_blind_decision_rule,
            experiments,
        ),
    )
    findings.extend(
        f"计划未在规定字段逐字保留入选方向的 {field_name}"
        for field_name, required_text, field_text in direction_requirements
        if required_text not in field_text
    )

    if atom.control_level_zh not in plan.baselines:
        findings.append(
            "计划 baselines 未以独立条目逐字承载前瞻 atom 的 control_level_zh"
        )
    technical_requirements = (
        ("change_mode", atom.change_mode),
        ("intervention_level_zh", atom.intervention_level_zh),
        ("single_factor_rationale_zh", atom.single_factor_rationale_zh),
    )
    findings.extend(
        f"计划 technical_details 未逐字承载前瞻 atom 的 {field_name}"
        for field_name, required_text in technical_requirements
        if required_text not in plan.technical_details
    )
    method_requirements = (
        ("change_mode", atom.change_mode),
        ("intervention_level_zh", atom.intervention_level_zh),
        ("single_factor_rationale_zh", atom.single_factor_rationale_zh),
    )
    findings.extend(
        f"计划 methods 未逐字承载前瞻 atom 的 {field_name}"
        for field_name, required_text in method_requirements
        if required_text not in plan.methods
    )
    if atom.falsifiable_single_factor_contrast_zh not in experiments:
        findings.append(
            "计划 experiments 未逐字承载前瞻 atom 的 "
            "falsifiable_single_factor_contrast_zh"
        )
    missing_frozen = tuple(
        dimension for dimension in atom.frozen_dimensions if dimension not in experiments
    )
    if missing_frozen:
        findings.append(
            "计划 experiments 未逐项冻结前瞻 atom 的 frozen_dimensions："
            f"{list(missing_frozen)}"
        )

    target_corpus = "\n".join((str(plan.datasets.get("target", "")), experiments))
    missing_targets = tuple(
        target for target in direction.target_systems if target not in target_corpus
    )
    if missing_targets:
        findings.append(f"计划遗漏前瞻 atom 匿名映射后的目标系统：{list(missing_targets)}")
    citation_corpus = "\n".join(
        (plan.problem_statement, plan.rationale, plan.methods, experiments)
    )
    missing_plan_references = tuple(
        index
        for index in binding.selected_plan_reference_indices()
        if f"[{index}]" not in citation_corpus
    )
    if missing_plan_references:
        findings.append(
            "计划遗漏前瞻 atom 的入选文献引用编号："
            f"{list(missing_plan_references)}"
        )

    declarations = _INTERVENTION_IDENTITY_PATTERN.findall(plan.code_agent_brief)
    if len(declarations) != 1:
        findings.append(
            "code_agent_brief 必须且只能包含一个可解析的 "
            "required_intervention_identity"
        )
    else:
        try:
            declared_identity = ProspectiveInterventionIdentity.model_validate(
                json.loads(declarations[0])
            )
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            findings.append(
                "code_agent_brief 的 required_intervention_identity 无法严格解析："
                f"{exc}"
            )
        else:
            if declared_identity != binding.selected_intervention_identity:
                findings.append(
                    "code_agent_brief 的 required_intervention_identity 未逐字等于"
                    "正式前瞻干预身份"
                )
    identity = binding.selected_intervention_identity
    if not _contains_identifier(plan.code_agent_brief, identity.implementation_anchor):
        findings.append(
            "code_agent_brief 未携带正式前瞻干预的 implementation_anchor "
            f"{identity.implementation_anchor}"
        )
    missing_hooks = tuple(
        hook
        for hook in identity.public_hooks
        if not _contains_identifier(plan.code_agent_brief, hook)
    )
    if missing_hooks:
        findings.append(
            "code_agent_brief 未携带正式前瞻干预的全部 public_hooks："
            f"{list(missing_hooks)}"
        )

    for other_atom, other_identity in zip(
        binding.component_experiment_binding.prospective_components.atoms,
        binding.component_experiment_binding.prospective_components.intervention_identities,
        strict=True,
    ):
        if other_atom.atom_id == atom.atom_id:
            continue
        forbidden_identifiers = (
            other_atom.atom_id,
            other_identity.intervention_hash,
            other_identity.implementation_anchor,
        )
        for forbidden in forbidden_identifiers:
            if _contains_identifier(plan.code_agent_brief, forbidden):
                findings.append(
                    "code_agent_brief 混入其他前瞻 atom 身份或锚点：" + forbidden
                )
    return tuple(dict.fromkeys(findings))


class AuthoredPlanGuardReport(StrictFrozenModel):
    """Every deterministic finding about one authored plan."""

    schema_version: Literal["authored-plan-guard-report-v1"] = (
        "authored-plan-guard-report-v1"
    )
    quality_gate_passed: bool
    quality_gate_issues: tuple[str, ...]
    quality_gate_warnings: tuple[str, ...]
    quality_gate_score: float
    # Guards this module adds on top of the shared quality gate.
    all_cited_evidence_exists: bool
    missing_evidence_paths: tuple[str, ...]
    numbers_traceable: bool
    untraceable_numbers: tuple[str, ...]
    states_falsifiable_expectation: bool
    claims_no_unobserved_result: bool
    named_scripts_exist: bool
    missing_script_paths: tuple[str, ...]
    accepted: bool
    findings: tuple[str, ...]
    report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate(self) -> AuthoredPlanGuardReport:
        if self.accepted != (not self.findings):
            raise SystemAuthoredPlanError(
                "the guard verdict contradicts its own finding list"
            )
        if self.all_cited_evidence_exists != (not self.missing_evidence_paths):
            raise SystemAuthoredPlanError(
                "the evidence verdict contradicts its own missing list"
            )
        if self.numbers_traceable != (not self.untraceable_numbers):
            raise SystemAuthoredPlanError(
                "the traceability verdict contradicts its own untraceable list"
            )
        if self.named_scripts_exist != (not self.missing_script_paths):
            raise SystemAuthoredPlanError(
                "the script verdict contradicts its own missing list"
            )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"report_hash"})
        )
        if self.report_hash != expected:
            raise SystemAuthoredPlanError("authored plan guard report hash mismatch")
        return self


class SystemAuthoredPlanArtifact(StrictFrozenModel):
    """An authored plan plus the graders that accepted it."""

    schema_version: Literal[
        "system-authored-research-plan-v1", "system-authored-research-plan-v2"
    ] = (
        "system-authored-research-plan-v2"
    )
    lineage_id: str = Field(min_length=1)
    plan: dict[str, Any]
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    guard_report: AuthoredPlanGuardReport
    authoring_attempts: int = Field(ge=1)
    model_name: str = Field(min_length=1)
    reasoning_tokens: int = Field(ge=0)
    # Optional only so immutable pre-270.4 plan artifacts remain loadable. Every
    # newly authored plan binds the exact provider transaction that supplied all
    # scientific prose fields.
    authorship_receipt_relative_path: str | None = None
    authorship_receipt_hash: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    # Optional only for immutable pre-lineage-binding artifacts.  Every new plan
    # created from the official opportunity-map/ideation path must carry both.
    scientific_lineage_binding: (
        PlanScientificLineageBinding | PlanScientificLineageBindingV2 | None
    ) = None
    scientific_lineage_attestation: (
        PlanScientificLineageAttestation | PlanScientificLineageAttestationV2 | None
    ) = None
    authored_by_model: Literal[True] = True
    hand_written_prose_field_count: Literal[0] = 0
    execution_authorized: Literal[False] = False
    is_evidence: Literal[False] = False
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate(self) -> SystemAuthoredPlanArtifact:
        if (self.authorship_receipt_relative_path is None) != (
            self.authorship_receipt_hash is None
        ):
            raise SystemAuthoredPlanError(
                "plan authorship receipt path/hash presence mismatch"
            )
        if (self.scientific_lineage_binding is None) != (
            self.scientific_lineage_attestation is None
        ):
            raise SystemAuthoredPlanError(
                "plan scientific lineage binding/attestation presence mismatch"
            )
        if self.schema_version == "system-authored-research-plan-v1":
            if isinstance(
                self.scientific_lineage_binding, PlanScientificLineageBindingV2
            ) or isinstance(
                self.scientific_lineage_attestation,
                PlanScientificLineageAttestationV2,
            ):
                raise SystemAuthoredPlanError(
                    "historical plan artifact v1 cannot carry a prospective formal chain"
                )
            if (
                isinstance(
                    self.scientific_lineage_binding, PlanScientificLineageBinding
                )
                and self.scientific_lineage_binding.selected_direction.schema_version
                == "research-direction-candidate-v2"
            ):
                raise SystemAuthoredPlanError(
                    "historical plan artifact v1 cannot carry a prospective direction"
                )
        elif self.scientific_lineage_binding is not None:
            if not isinstance(
                self.scientific_lineage_binding, PlanScientificLineageBindingV2
            ) or not isinstance(
                self.scientific_lineage_attestation,
                PlanScientificLineageAttestationV2,
            ):
                raise SystemAuthoredPlanError(
                    "new plan artifact v2 requires the prospective v2 binding and "
                    "attestation together"
                )
        if self.scientific_lineage_binding is not None:
            lineage_findings = _lineage_attestation_findings(
                binding=self.scientific_lineage_binding,
                attestation=self.scientific_lineage_attestation,
            )
            try:
                persisted_plan = ResearchPlan.model_validate(self.plan)
            except ValidationError as exc:
                raise SystemAuthoredPlanError(
                    f"persisted research plan is malformed: {exc}"
                ) from exc
            lineage_findings = (
                *lineage_findings,
                *_plan_scientific_lineage_findings(
                    plan=persisted_plan,
                    binding=self.scientific_lineage_binding,
                ),
            )
            if lineage_findings:
                raise SystemAuthoredPlanError(
                    "persisted plan scientific lineage mismatch: "
                    + "; ".join(lineage_findings)
                )
        if not self.guard_report.accepted:
            raise SystemAuthoredPlanError(
                "a plan artifact cannot be constructed from a refused plan; the "
                "refusal must be raised rather than persisted as an accepted plan"
            )
        expected_plan_hash = canonical_model_hash(self.plan)
        if self.plan_hash != expected_plan_hash:
            raise SystemAuthoredPlanError("system authored plan payload hash mismatch")
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"artifact_hash", "output_path"})
        )
        if self.artifact_hash != expected:
            raise SystemAuthoredPlanError("system authored plan artifact hash mismatch")
        return self

    @model_serializer(mode="wrap")
    def _serialize_with_legacy_compatibility(self, handler: Any) -> dict[str, Any]:
        """Do not inject new null keys into immutable historical artifacts."""

        payload = dict(handler(self))
        if self.authorship_receipt_hash is None:
            payload.pop("authorship_receipt_relative_path", None)
            payload.pop("authorship_receipt_hash", None)
        if self.scientific_lineage_binding is None:
            payload.pop("scientific_lineage_binding", None)
            payload.pop("scientific_lineage_attestation", None)
        return payload


def plan_reachable_numbers(evidence_numbers: set[str]) -> set[str]:
    """Extend evidence numbers with arithmetic a PLAN may legitimately perform.

    `P-20260804-087`: a plan does budget arithmetic. Writing "6 systems by 3 seeds is
    18 cells" is correct reasoning, but 18 appears nowhere in the frozen evidence, so
    strict traceability refused a sound plan.

    This registers pairwise products and sums of the small integers already present in
    the evidence, plus small ordinals for enumerated steps. It is deliberately NOT
    applied to result interpretation, where every number is a measured value and must
    match exactly.
    """

    integers: set[int] = set()
    for token in evidence_numbers:
        try:
            value = float(token)
        except ValueError:
            continue
        if value.is_integer() and 0 <= abs(value) <= 10_000:
            integers.add(int(value))

    reachable = set(evidence_numbers)
    # Ordinals for enumerated steps and short lists.
    reachable.update(str(index) for index in range(1, 21))
    for left in integers:
        for right in integers:
            for derived in (left * right, left + right, left - right):
                if 0 <= abs(derived) <= 1_000_000:
                    reachable.add(str(derived))
    return reachable


def _numeric_claim_prose(plan: ResearchPlan) -> str:
    """Return clauses whose numbers must be inherited from frozen evidence.

    The plan may originate numerical *design choices* only in fields that describe
    implementation or experimental procedure, and only when the local clause marks
    the value prospectively.  This keeps measured/evidentiary numbers fail-closed
    while making an actual preregistration possible.
    """

    evidence_claims = [
        plan.title,
        plan.problem_statement,
        plan.rationale,
        plan.results,
        plan.expected_results,
    ]
    # The exact intervention declaration is a machine identity, not scientific prose.
    # Its SHA-256 fragments otherwise look like invented decimals/exponents to the
    # numeric-claim scanner.  Strip only declarations that strictly validate against
    # the closed identity schema; malformed or arbitrary JSON remains auditable text.
    def _replace_valid_identity(match: re.Match[str]) -> str:
        try:
            ProspectiveInterventionIdentity.model_validate(json.loads(match.group(1)))
        except (json.JSONDecodeError, ValidationError, ValueError):
            return match.group(0)
        return "required_intervention_identity=<validated-machine-identity>"

    sanitized_code_brief = _INTERVENTION_IDENTITY_PATTERN.sub(
        _replace_valid_identity, plan.code_agent_brief
    )
    prospective_design_fields = [
        plan.abstract or "",
        plan.technical_details,
        plan.methods,
        sanitized_code_brief,
        *plan.experiments,
        *plan.baselines,
        *plan.metrics,
        *plan.risks_and_alternatives,
        str(plan.datasets.get("source", "")),
        str(plan.datasets.get("target", "")),
    ]
    for block in prospective_design_fields:
        for clause in _DESIGN_CLAUSE_SPLIT.split(str(block)):
            lowered = clause.lower()
            if any(marker in lowered for marker in _PROSPECTIVE_DESIGN_MARKERS):
                continue
            evidence_claims.append(clause)
    return "\n".join(evidence_claims)


def _existing_evidence_refs(paths: Sequence[Path | str]) -> tuple[list[str], list[str]]:
    """Split candidate references into those that exist and those that do not."""

    present: list[str] = []
    missing: list[str] = []
    for item in paths:
        path = Path(item)
        if path.exists():
            present.append(path.as_posix())
        else:
            missing.append(path.as_posix())
    return present, missing


def guard_authored_plan(
    *,
    plan: ResearchPlan,
    evidence_numbers: set[str],
    cited_evidence: Sequence[Path | str],
    repo_root: Path = Path("."),
    container_entry_points: Sequence[str] = (),
    required_direction_tokens: Sequence[str] = (),
    literature_count: int = 0,
    require_chinese: bool = False,
) -> AuthoredPlanGuardReport:
    """Grade an authored plan deterministically. Every finding is actionable.

    Reuses the shared `audit_research_plan` rubric rather than inventing a second
    standard, then adds the three checks that rubric cannot make: that cited evidence
    exists on disk, that every number traces to the frozen evidence, and that the
    expectation is stated falsifiably.
    """

    audit = audit_research_plan(plan)
    findings: list[str] = [f"quality gate: {item}" for item in audit.issues]

    present, missing = _existing_evidence_refs(cited_evidence)
    if missing:
        findings.append(
            "these cited evidence paths do not exist on disk, so they cannot be "
            f"cited: {missing}"
        )

    # `P-20260808-095`：交付语言是中文，但从未有任何检查强制它，于是产出中英混杂。
    if require_chinese:
        too_english = authored_plan_non_chinese_fields(plan)
        if too_english:
            findings.append(
                "以下系统撰写字段必须用简体中文，当前中文占比过低："
                f"{list(too_english)}。技术标识符（字段名、门禁名、系统名、路径、命令）"
                "保持英文原样，其余散文必须中文。"
            )

    control_character_fields = authored_plan_control_character_fields(plan)
    if control_character_fields:
        findings.append(
            "这些系统撰写字段含不可见控制字符，通常来自在 JSON 字符串中直接写入 "
            f"LaTeX 反斜杠转义：{list(control_character_fields)}。请改用普通 Unicode "
            "数学符号或文字说明；不可见字节会破坏中文交付与可复现渲染。"
        )

    # `P-20260808-095`：参考文献曾是装饰——列了 7 条，正文一次都没引用。
    # 根因是我把顺序做反了（先写计划再检索），现在文献先行，于是可以强制引用。
    if literature_count:
        uncited: list[str] = []
        out_of_range: set[str] = set()
        for field in _FIELDS_REQUIRING_CITATION:
            value = str(getattr(plan, field, "") or "")
            hits = _CITATION_PATTERN.findall(value)
            if not hits:
                uncited.append(field)
            for hit in hits:
                if not (1 <= int(hit) <= literature_count):
                    out_of_range.add(hit)
        if uncited:
            findings.append(
                f"以下字段缺少对已调研文献的行内引用：{uncited}。"
                f"请用 [1]..[{literature_count}] 形式引用 surveyed_literature 中的条目；"
                "一份对先前工作零定位的文档不是研究计划。"
            )
        if out_of_range:
            findings.append(
                f"这些引用编号超出已调研文献范围：{sorted(out_of_range)}。"
                f"可用编号只有 1..{literature_count}，超范围的编号等同于虚构引用。"
            )

    prose = "\n".join(
        [
            plan.title,
            plan.problem_statement,
            plan.rationale,
            plan.technical_details,
            plan.methods,
            plan.expected_results,
            plan.code_agent_brief,
            *plan.experiments,
            *plan.risks_and_alternatives,
            str(plan.datasets.get("source", "")),
            str(plan.datasets.get("target", "")),
        ]
    )
    traceability = audit_numeric_traceability(
        prose=_numeric_claim_prose(plan),
        allowed_numbers=plan_reachable_numbers(evidence_numbers),
    )
    if not traceability.passed:
        findings.append(
            "these EVIDENCE-CLAIM numbers appear in the plan but not in the frozen "
            "evidence, so they were invented rather than derived. New prospective "
            "design constants are allowed only when explicitly described as "
            "pre-registered choices in a method or experiment clause: "
            f"{list(traceability.untraceable_numbers)}"
        )

    expected_lower = plan.expected_results.lower()
    falsifiable = any(marker in expected_lower for marker in _FALSIFIABILITY_MARKERS)
    if not falsifiable:
        findings.append(
            "expected_results must state what outcome would REFUTE the expectation, "
            "and must acknowledge that a negative or null result is a valid outcome; "
            "a plan that only describes success is an announcement, not a plan"
        )

    # A plan is written before observation, so it must not assert an achieved result.
    # Only PAST-TENSE assertions of an achieved result. `P-20260804-087`: an earlier
    # pattern flagged "outperforms", which is how a legitimate expectation is phrased
    # ("is expected to outperform"), so correct plans were refused.
    # `P-20260808-095`: 中文分支同样必要。原正则只认英文，所以一份中文计划写下
    # "实验结果表明本方法优于基线" 也能过关——检查会漏掉它本该拦住的越界宣称。
    # 中文无词边界，故不用 `\b`。刻意只匹配"已然"语气：
    # "预期优于基线" 是合法的预期表述，不能拦。
    achieved_pattern = re.compile(
        r"\b(?:we (?:achieved|obtained|observed|showed|demonstrated)|"
        r"(?:the )?results? (?:showed|demonstrated|confirmed)|"
        r"(?:has|have|had) outperformed|outperformed the)\b"
        r"|(?:实验|结果|测量|数据)(?:表明|显示|证实|证明)"
        r"|(?:我们|本方法|该方法)(?:已|已经)(?:达到|取得|获得|实现|观测到|验证)"
        r"|(?:已|已经)(?:优于|超过|超越)(?:基线|baseline)"
    )

    def is_conditional_result(match: re.Match[str]) -> bool:
        """Do not mistake a refutation condition for a claimed observation."""

        prefix = prose.lower()[max(0, match.start() - 32) : match.start()]
        english_conditional = re.search(
            r"\b(?:if|when)\b[^.!?;；。]{0,28}$", prefix
        )
        chinese_prefix = prefix[-16:]
        chinese_conditional = any(
            marker in chinese_prefix for marker in ("若", "如果", "倘若", "一旦")
        )
        return english_conditional is not None or chinese_conditional

    achieved = next(
        (
            match
            for match in achieved_pattern.finditer(prose.lower())
            if not is_conditional_result(match)
        ),
        None,
    )
    claims_no_result = achieved is None
    if achieved:
        findings.append(
            "the plan asserts an achieved result before any measurement exists: "
            f"{achieved.group(0)!r}; state expectations, not outcomes"
        )

    # A brief naming a script that does not exist cannot be run, so the plan is not
    # executable however command-shaped its prose is.
    brief_text = plan.code_agent_brief + " " + " ".join(plan.experiments)
    named_scripts = sorted(set(_HOST_SCRIPT_PATTERN.findall(brief_text)))
    absent_scripts = [
        name
        for name in named_scripts
        if not (repo_root / name).exists() and not Path(name).exists()
    ]
    # An absolute path must be one the caller declared as real, or it is invented.
    allowed_absolute = set(container_entry_points or ())
    absent_scripts.extend(
        sorted(
            name
            for name in set(_ABSOLUTE_SCRIPT_PATTERN.findall(brief_text))
            if name not in allowed_absolute
        )
    )
    briefs_runnable = not absent_scripts
    if absent_scripts:
        findings.append(
            "the plan names these host scripts, none of which exist, so the brief "
            f"cannot be executed as written: {absent_scripts}. Reference an entry "
            "point that exists, or describe the command in terms of the pinned "
            "container path."
        )

    # A runnable command alone does not prove which scientific method will be coded.
    # Require model-authored, source-checkable method tokens before accepting the plan.
    try:
        authored_method_tokens = extract_required_method_tokens(plan.code_agent_brief)
    except PlanExecutionContractError as exc:
        findings.append(str(exc))
        authored_method_tokens = ()
    missing_direction_tokens = sorted(
        set(required_direction_tokens) - set(authored_method_tokens)
    )
    if missing_direction_tokens:
        findings.append(
            "the full plan abandoned method identifiers from the independently "
            "selected system-authored direction: "
            f"{missing_direction_tokens}. Preserve the selected direction rather "
            "than reverting to a rejected method family."
        )

    payload: dict[str, Any] = {
        "schema_version": "authored-plan-guard-report-v1",
        "quality_gate_passed": audit.passed,
        "quality_gate_issues": tuple(audit.issues),
        "quality_gate_warnings": tuple(audit.warnings),
        "quality_gate_score": float(audit.score),
        "all_cited_evidence_exists": not missing,
        "missing_evidence_paths": tuple(missing),
        "numbers_traceable": traceability.passed,
        "untraceable_numbers": traceability.untraceable_numbers,
        "states_falsifiable_expectation": falsifiable,
        "claims_no_unobserved_result": claims_no_result,
        "named_scripts_exist": briefs_runnable,
        "missing_script_paths": tuple(absent_scripts),
        "accepted": not findings,
        "findings": tuple(dict.fromkeys(findings)),
    }
    payload["report_hash"] = canonical_model_hash(payload)
    return AuthoredPlanGuardReport.model_validate(payload)


_AUTHORED_FIELDS: tuple[str, ...] = (
    "title",
    # 榜题《生成结果规范》要求摘要含背景、方法、预期结果三部分。
    "abstract",
    "problem_statement",
    "rationale",
    "technical_details",
    "methods",
    "experiments",
    # 榜题点名要求实验设计包含 Baselines 与 Metrics，所以拆成独立字段，
    # 而不是指望它们埋在 experiments 的散文里。
    "baselines",
    "metrics",
    "expected_results",
    "code_agent_brief",
    "risks_and_alternatives",
    "dataset_source",
    "dataset_target",
    "references",
)

_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": list(_AUTHORED_FIELDS),
    "properties": {
        "title": {"type": "string"},
        "abstract": {"type": "string"},
        "problem_statement": {"type": "string"},
        "rationale": {"type": "string"},
        "technical_details": {"type": "string"},
        "methods": {"type": "string"},
        "experiments": {"type": "array", "items": {"type": "string"}, "minItems": 3},
        "baselines": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "metrics": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "expected_results": {"type": "string"},
        "code_agent_brief": {"type": "string"},
        "risks_and_alternatives": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
        },
        "dataset_source": {"type": "string"},
        "dataset_target": {"type": "string"},
        "references": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "scientific_lineage_attestation": (
            PlanScientificLineageAttestation.model_json_schema()
        ),
    },
}


class _AuthoredPlanResponse(StrictFrozenModel):
    """Strict shape of model-owned prose before it can become a ResearchPlan.

    In particular, a string is never coerced to a list of characters.  Every
    malformed response is retained in its model receipt and returned to the model as
    a repair finding.
    """

    title: str
    abstract: str
    problem_statement: str
    rationale: str
    technical_details: str
    dataset_source: str
    dataset_target: str
    methods: str
    experiments: tuple[str, ...]
    baselines: tuple[str, ...]
    metrics: tuple[str, ...]
    # Required dynamically when a real preliminary experiment is present.  The
    # default preserves strict loading of historical pre-measurement responses.
    results: str = ""
    expected_results: str
    code_agent_brief: str
    risks_and_alternatives: tuple[str, ...]
    references: tuple[str, ...]
    scientific_lineage_attestation: (
        PlanScientificLineageAttestation | PlanScientificLineageAttestationV2 | None
    ) = None


def _authored_plan_response_schema(
    *,
    has_lineage_binding: bool,
) -> dict[str, Any]:
    """Expose prose and scientific choices, never replayable machine identities."""

    plan_schema: dict[str, Any] = json.loads(json.dumps(_PLAN_SCHEMA))
    plan_schema["properties"].pop("results", None)
    plan_schema["required"] = [
        field_name
        for field_name in plan_schema["required"]
        if field_name != "results"
    ]
    if has_lineage_binding:
        plan_schema["required"].append("scientific_lineage_attestation")
        plan_schema["properties"]["scientific_lineage_attestation"] = {
            "type": "object",
            "additionalProperties": False,
            "required": ["continuity_explanation"],
            "properties": {
                "continuity_explanation": {"type": "string", "minLength": 1}
            },
        }
    else:
        plan_schema["properties"].pop("scientific_lineage_attestation", None)
    return plan_schema


def _project_authored_plan_payload(
    payload: Any,
    *,
    scientific_lineage_binding: (
        PlanScientificLineageBinding | PlanScientificLineageBindingV2 | None
    ),
    preliminary_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Project exact results and lineage identity around Qwen-authored plan prose."""

    if not isinstance(payload, Mapping):
        raise SystemAuthoredPlanError("研究计划响应必须为 JSON 对象")
    projected = dict(payload)
    preliminary_results = (
        preliminary_context.get("plan_results_zh")
        if isinstance(preliminary_context, Mapping)
        else None
    )
    projected["results"] = (
        preliminary_results
        if isinstance(preliminary_results, str) and preliminary_results.strip()
        else ""
    )

    raw_attestation = payload.get("scientific_lineage_attestation")
    if scientific_lineage_binding is None:
        if raw_attestation is not None:
            raise SystemAuthoredPlanError(
                "没有正式谱系时 Qwen 不得自行声明 scientific_lineage_attestation"
            )
        projected.pop("scientific_lineage_attestation", None)
        return projected
    if not isinstance(raw_attestation, Mapping):
        raise SystemAuthoredPlanError(
            "正式谱系计划必须由 Qwen 返回 continuity_explanation 对象"
        )
    continuity_explanation = raw_attestation.get("continuity_explanation")
    if not isinstance(continuity_explanation, str) or not continuity_explanation.strip():
        raise SystemAuthoredPlanError("continuity_explanation 必须为非空中文解释")
    attestation = _project_lineage_attestation(
        binding=scientific_lineage_binding,
        continuity_explanation=continuity_explanation,
    )
    projected["scientific_lineage_attestation"] = attestation.model_dump(mode="json")

    if isinstance(scientific_lineage_binding, PlanScientificLineageBindingV2):
        raw_brief = projected.get("code_agent_brief")
        if not isinstance(raw_brief, str):
            raise SystemAuthoredPlanError("code_agent_brief 必须为字符串")
        scientific_brief = _INTERVENTION_IDENTITY_PATTERN.sub("", raw_brief).strip()
        if "required_intervention_identity" in scientific_brief:
            raise SystemAuthoredPlanError(
                "code_agent_brief 含无法规范投影的 intervention identity 声明"
            )
        identity_json = json.dumps(
            scientific_lineage_binding.selected_intervention_identity.model_dump(
                mode="json"
            ),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        projected["code_agent_brief"] = (
            f"required_intervention_identity={identity_json}\n{scientific_brief}"
        )
    return projected


def _plan_authoring_feedback_trace(
    *,
    prior_findings: Sequence[str],
    previous_system_authored_plan: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    findings = tuple(str(item) for item in prior_findings)
    if not findings:
        return None
    if any(not item.strip() for item in findings):
        raise SystemAuthoredPlanError("计划编排器反馈不得包含空字符串")
    previous_hash = (
        canonical_model_hash(dict(previous_system_authored_plan))
        if previous_system_authored_plan is not None
        else None
    )
    binding = {
        "stage": "research_plan_authoring",
        "findings": list(findings),
        "previous_system_authored_plan_hash": previous_hash,
    }
    return {
        "schema_version": "system-authored-plan-feedback-trace-v1",
        **binding,
        "trace_hash": canonical_model_hash(binding),
    }


def _authoring_feedback_from_payload(
    payload: Mapping[str, Any],
) -> tuple[str, ...]:
    trace = payload.get("orchestrator_feedback_trace")
    previous = payload.get("previous_system_authored_plan")
    if trace is None:
        if previous is not None:
            raise SystemAuthoredPlanError(
                "存在待修系统计划时必须保存编排器反馈轨迹"
            )
        return ()
    if not isinstance(trace, Mapping):
        raise SystemAuthoredPlanError("计划编排器反馈轨迹必须为对象")
    findings = trace.get("findings")
    if not isinstance(findings, list) or not findings:
        raise SystemAuthoredPlanError("计划编排器反馈轨迹必须含非空有序列表")
    if any(not isinstance(item, str) or not item.strip() for item in findings):
        raise SystemAuthoredPlanError("计划编排器反馈轨迹含空值或非字符串")
    if previous is not None and not isinstance(previous, Mapping):
        raise SystemAuthoredPlanError("待修系统计划必须为对象")
    previous_hash = (
        canonical_model_hash(dict(previous))
        if isinstance(previous, Mapping)
        else None
    )
    binding = {
        "stage": "research_plan_authoring",
        "findings": list(findings),
        "previous_system_authored_plan_hash": previous_hash,
    }
    if (
        trace.get("schema_version")
        != "system-authored-plan-feedback-trace-v1"
        or trace.get("stage") != "research_plan_authoring"
        or trace.get("previous_system_authored_plan_hash") != previous_hash
        or trace.get("trace_hash") != canonical_model_hash(binding)
        or set(trace) != {
            "schema_version",
            "stage",
            "findings",
            "previous_system_authored_plan_hash",
            "trace_hash",
        }
    ):
        raise SystemAuthoredPlanError("计划编排器反馈轨迹与待修输出不一致")
    return tuple(findings)


def _authoring_messages(
    *,
    frozen_context: Mapping[str, Any],
    prior_findings: Sequence[str],
    previous_system_authored_plan: Mapping[str, Any] | None = None,
    container_entry_points: Sequence[str] = (),
    literature: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, str]]:
    """Give the system its constraints, its evidence, and the surveyed literature.

    Supply no science. `literature` is passed so the plan can CITE prior work:
    `P-20260808-095` recorded that surveying after authoring left the reference list
    decorative, because the plan had never seen the papers it was supposed to build on.
    """

    selected_direction = frozen_context.get("system_selected_research_direction")
    selected_method_skills = frozen_context.get("system_selected_method_skills")
    audited_opportunity_map = frozen_context.get(
        "system_audited_research_opportunity_map"
    )
    scientific_lineage_binding = frozen_context.get(
        "system_plan_scientific_lineage_binding"
    )
    preexperiment_context = frozen_context.get("system_preliminary_experiment")
    has_preexperiment = (
        isinstance(preexperiment_context, Mapping)
        and preexperiment_context.get("schema_version")
        == "system-plan-preexperiment-plan-context-v1"
        and isinstance(preexperiment_context.get("plan_results_zh"), str)
        and bool(str(preexperiment_context.get("plan_results_zh")).strip())
    )
    formal_v2 = (
        isinstance(scientific_lineage_binding, Mapping)
        and scientific_lineage_binding.get("schema_version")
        == "plan-scientific-lineage-binding-v2"
    )
    if isinstance(selected_direction, Mapping):
        if formal_v2:
            opportunity_context = (
                "Its opportunity cell is ONLY a problem-motivation link. Do not use "
                "the cell's broad targets, facts, literature, or component prose as "
                "the treatment boundary. The exact experimental boundary is the "
                "selected prospective atom and intervention identity in the v2 "
                "scientific lineage binding. "
            )
        else:
            opportunity_context = (
                "It is also bound to one cell in YOUR independently audited research "
                "opportunity map. Preserve the cell's operational construct, target "
                "systems, alternative explanation, and discriminating logic; "
                if isinstance(audited_opportunity_map, Mapping)
                else ""
            )
        direction_context = (
            "A separate system-authored divergent tournament in the context selected "
            "one research direction. It is YOUR configured model's hash-bound output, "
            "not human-authored science and not observed evidence. Expand that exact "
            "direction into the full plan. "
            + opportunity_context
            + "Preserve all direction method_tokens in required_method_tokens. Do not "
            "invent a different problem or revert to a rejected method family. "
        )
    else:
        direction_context = "Nothing scientific is supplied to you. "
    plan_schema = _authored_plan_response_schema(
        has_lineage_binding=isinstance(scientific_lineage_binding, Mapping)
    )
    if isinstance(scientific_lineage_binding, Mapping):
        if formal_v2:
            lineage_contract = (
                "The context includes a v2 `system_plan_scientific_lineage_binding`, "
                "an immutable chain of YOUR upstream model outputs. Return only a new "
                "Chinese continuity_explanation inside scientific_lineage_attestation; "
                "the orchestrator will project every hash, ID, array, intervention "
                "identity, and atom contract field exactly from that binding. The two literature "
                "number domains differ: nearest_work_indices are one-based positions "
                "in the full retrieved catalogue, while selected_plan_reference_indices "
                "are the atom support reference_index values and are the [n] citations "
                "that belong in this public plan. The opportunity cell supplies only "
                "motivation and may not broaden those exact values.\n"
                "FIELD-LOCAL CONTRACT: baselines must contain control_level_zh as one "
                "exact item; technical_details AND methods must each contain change_mode, "
                "intervention_level_zh, and single_factor_rationale_zh verbatim; "
                "experiments must contain the falsifiable_single_factor_contrast_zh and "
                "every frozen_dimensions item. Do not write any "
                "`required_intervention_identity` declaration yourself; the orchestrator "
                "will prepend exactly one canonical declaration to code_agent_brief, "
                "thereby naming the exact implementation_anchor and every public_hook. "
                "Pasting this content into "
                "risks_and_alternatives or another field cannot satisfy any check. "
                "Include every resolved target system and every selected-plan citation. "
            )
        else:
            lineage_contract = (
                "The context includes `system_plan_scientific_lineage_binding`, which is "
                "an immutable chain of YOUR upstream model outputs. Return only a new "
                "Chinese continuity_explanation inside scientific_lineage_attestation; "
                "the orchestrator will project all exact selected-direction fields. "
                "In the public plan prose, preserve the selected direction title, "
                "scientific_gap, challenged_assumption, core_mechanism, "
                "falsifiable_hypothesis, alternative_explanation, decisive_test, all "
                "three controls/diagnostics, independent_analysis_unit, and "
                "result_blind_decision_rule verbatim at least once in their appropriate "
                "fields. Include every selected target system and every selected "
                "nearest-work citation [n]. A deterministic byte-level guard refuses a "
                "plan that merely copies method_tokens and changes the science. "
            )
    else:
        lineage_contract = (
            "Do not return scientific_lineage_attestation because no official "
            "map-to-direction lineage is present. "
        )
    instruction = (
        "You are the autonomous research system. Author your OWN research plan for the "
        "next lineage. You decide the problem framing, the mechanism you believe is "
        "responsible, what you will test, and what result would refute you.\n\n"
        + direction_context
        + lineage_contract
        + "The context below also carries frozen constraints you may not change, and "
        "evidence retained from your own prior lineages. Do not restate the constraints "
        "as if they were your reasoning.\n\n"
        # `P-20260808-095`: 交付文档是中文的《科学假设与研究计划》，此前提示词全英文，
        # 导致中文标题配英文正文。语言要求放在最前，因为它约束下面每一条的写法。
        "LANGUAGE: write every prose field in CHINESE (简体中文). This plan is delivered "
        "as a Chinese document and is read by Chinese reviewers. Keep these in their "
        "original form and do NOT translate them, because they are literal identifiers "
        "that a reader must be able to search for in the code and artifacts: field "
        "names (overall_median_log_effect), system names "
        "(reaction_diffusion_cylinder), metric names (NMSE), gate names "
        "(pde_stratum_non_negative), file paths, and commands. Write natural technical "
        "Chinese around them; do not transliterate them into Chinese characters.\n\n"
        # 质量要求。此前产出是 "Risk: ... Alternative: ..." 这类标签拼接，读起来像填表
        # 而非科学写作，所以在这里明确要求成文。
        "WRITING QUALITY: write connected technical prose, not label-prefixed "
        "fragments. Do NOT open items with bare labels like 'Risk:' / 'Alternative:' / "
        "'Phase 1:'; state the risk and its mitigation as complete sentences that "
        "explain the causal reason. Each field must read as if written by a researcher "
        "who understands the mechanism, not as a form filled in. Avoid restating a "
        "number without saying what it implies. Do not pad with the frozen constraints "
        "you were given. Never place a LaTeX backslash command such as \\beta inside "
        "a JSON string: JSON interprets escapes such as \\b as invisible control bytes. "
        "Use ordinary Unicode symbols (for example β) or Chinese words instead.\n\n"
        "Hard requirements, each enforced by a deterministic grader that will return "
        "its exact findings to you if you fail:\n"
        "1. Every number stated as prior evidence, an observation, an effect, or an "
        "expected-result threshold must already appear in the supplied evidence. An "
        "invented evidence number is refused. You MAY originate a new prospective "
        "design constant in abstract, technical_details, methods, experiments, "
        "baselines, metrics, code_agent_brief, risks, or dataset fields only when the "
        "same clause explicitly says it is a pre-registered choice (for example "
        "「预先固定」「计划采用」「设定为」). Never present such a choice as observed or "
        "evidence-derived.\n"
        "2. expected_results must state what outcome would REFUTE your expectation, "
        "and must acknowledge that a negative or null result is a valid outcome. "
        "Writing in Chinese, use explicit wording such as 「若…则假设被反驳」、"
        "「零结果同样是有效结果」、「低于该阈值即推翻本假设」, because the grader looks "
        "for that commitment and a plan that only describes success is an "
        "announcement, not a plan.\n"
        + (
            "3. A real bounded preliminary experiment exists in "
            "`system_preliminary_experiment`. Do not return a `results` field; the "
            "orchestrator will reuse its `plan_results_zh` byte for byte. It is your "
            "own prior Qwen-authored interpretation of raw sandbox results. Do not "
            "paraphrase those results elsewhere or claim the proposed intervention "
            "was measured.\n"
            if has_preexperiment
            else "3. Do not assert any achieved result. No measurement exists yet, "
            "and do not return a `results` field.\n"
        )
        + "4. Name at least one baseline or control, and concrete evaluation metrics. "
        "Put these in the dedicated `baselines` and `metrics` arrays, not only inside "
        "the experiments prose, because they are graded as separate fields. Every "
        "baseline and metric item must be a complete Chinese technical description "
        "around any literal English identifier; a bare identifier such as NMSE is "
        "not a Chinese prose item.\n"
        "4a. `abstract` must be a self-contained abstract covering THREE parts in "
        "order: the background/problem, the method you propose, and the expected "
        "result. It is read on its own, so do not open with 'as stated above' or refer "
        "to sections the reader has not seen.\n"
        "5. code_agent_brief must be COMMAND-ORIENTED and RUNNABLE: it has to contain "
        "an actual command line, and the grader looks for one of the literal words "
        "'python', 'command', 'script', or 'pytest'. It must NOT invent a script name. "
        "EVERY `.py` path you write is checked, host-relative and absolute alike. The "
        "ONLY entry points that exist are listed below; inventing a plausible-looking "
        "path is refused whether it starts with a slash or not: "
        + (json.dumps(list(container_entry_points)) if container_entry_points else "[]")
        + "\n"
        "5a. End code_agent_brief with 2-8 distinctive SINGLE-TERM ASCII method "
        "identifiers in the literal form required_method_tokens=[spectral, stlsq]. "
        "Each token must contain letters/digits only: NO underscores, hyphens, spaces, "
        "or multiword names. Choose tokens that identify YOUR proposed scientific "
        "mechanism, not generic interface words such as model, method, fit, runner, "
        "or candidate. Candidate source is "
        "later checked by AST: every token must occur in a callable actually reached "
        "from fit_equations or predict_derivative; comments, prose, variable names, "
        "and unused helpers cannot pass.\n"
        "6. Use no placeholder text and no reference to any contest or organizer.\n"
        "6a. dataset_source and dataset_target must each be a complete natural Chinese "
        "sentence explaining the role of the exact path or system identifiers. A bare "
        "path or comma-separated identifier list is refused as non-Chinese prose.\n"
        "6b. Because this is a preregistration, never use 「实验显示」 or 「结果显示」 "
        "as an unqualified past observation about this new lineage. They are allowed "
        "inside an explicit refutation condition such as 「若实验结果显示…则假设被反驳」. "
        "Every claim about this new plan must remain an expectation.\n"
        "7. WRITE THE TITLE AND EVERY PROSE FIELD IN CHINESE (简体中文). This document is read by "
        "Chinese reviewers. Keep these in their original form because they are literal "
        "identifiers a reader must be able to match against code and data, and "
        "translating them makes them unfindable: field and gate names, metric names, "
        "system names, file paths, commands, and original bibliography titles. All "
        "authored prose surrounding those literal identifiers must be Chinese.\n"
        "8. WRITE FOR AN EXTERNAL SCIENTIFIC READER, not for an internal issue "
        "tracker. Do NOT build sentences around internal bookkeeping identifiers such "
        "as lineage ids, ledger counters, or budget field names. A reader outside this "
        "system has never seen them and cannot verify them. State the SCIENTIFIC "
        "problem, mechanism, and evidence. When a number matters, say what it measures "
        "and why it matters, not merely which internal gate it belongs to.\n"
        "9. CITE THE SUPPLIED LITERATURE INLINE using bracket numerals that match the "
        "`index` of each paper in `surveyed_literature` below, for example 「稀疏回归"
        "方法[1]」. At minimum, `problem_statement`, `rationale`, and `methods` must "
        "each carry at least one citation, because a plan that positions itself "
        "against no prior work is not a research plan. Cite ONLY the supplied indices: "
        "there is no other literature available to you, and an index that is not in "
        "the list will be treated as fabricated.\n\n"
        "Think first, then answer. Your reasoning is process provenance only and is "
        "never scientific evidence.\n"
        + (
            "The provider response MUST include non-empty reasoning_content that "
            "follows the separately supplied, system-selected "
            "SKILL.md stages; a missing audit trail is refused.\n"
            if isinstance(selected_method_skills, Mapping)
            else ""
        )
        + "Return exactly one json object satisfying this schema, with no prose outside "
        "it; local strict validation will reject every extra, missing, or invalid "
        "field: " + json.dumps(plan_schema, ensure_ascii=False, sort_keys=True)
    )
    if prior_findings:
        scientific_refusal = any(
            "mandatory adversarial scientific review:" in item
            for item in prior_findings
        )
        if scientific_refusal:
            instruction += (
                "\n\nYour previous attempt was REFUSED by the mandatory adversarial "
                "SCIENTIFIC review, not merely by a format checker. Read your previous "
                "plan in the user payload and repair every exact finding below. If a "
                "finding rejects novelty, the central mechanism, or the ability of the "
                "design to identify that mechanism, DISCARD that framing and originate "
                "a materially different hypothesis and method from the retained "
                "evidence and literature. Do not preserve or rename a rejected "
                "component combination. No human is supplying the replacement science; "
                "you must create it yourself. Exact findings: "
                + json.dumps(list(prior_findings), ensure_ascii=False)
            )
        else:
            instruction += (
                "\n\nYour previous attempt was REFUSED by the graders (deterministic "
                "checks) with these exact findings. Read your previous plan in the "
                "user payload, repair each named defect, and keep the rest of your "
                "plan when it is unaffected scientific content: "
                + json.dumps(list(prior_findings), ensure_ascii=False)
            )
    user_payload: dict[str, Any] = dict(frozen_context)
    user_payload.pop("system_selected_method_skills", None)
    if prior_findings and previous_system_authored_plan is not None:
        # The only scientific prose added here is the model's own exact previous
        # response.  Without it, findings such as "fix experiment two" refer to text
        # the next stateless provider call cannot see, so the loop cannot truly revise.
        user_payload["previous_system_authored_plan"] = dict(
            previous_system_authored_plan
        )
    feedback_trace = _plan_authoring_feedback_trace(
        prior_findings=prior_findings,
        previous_system_authored_plan=previous_system_authored_plan,
    )
    if feedback_trace is not None:
        user_payload["orchestrator_feedback_trace"] = feedback_trace
    if literature:
        # 文献以 index 呈现，与提示词里要求的行内引用编号一致，也与最终 LaTeX 参考
        # 文献表的顺序一致，这样正文的 [n] 能被读者对上号。
        user_payload["surveyed_literature"] = [
            {
                "index": position,
                "title": item.get("title"),
                "authors": list(item.get("authors") or [])[:6],
                "venue": item.get("venue"),
                "publication_date": item.get("publication_date"),
                "doi": item.get("doi"),
                "relevance_noted_by_you": item.get("relevance_to_plan"),
            }
            for position, item in enumerate(literature, 1)
        ]
    messages = [{"role": "system", "content": instruction}]
    if isinstance(selected_method_skills, Mapping):
        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "context_kind": "system_selected_project_method_skills",
                        **dict(selected_method_skills),
                        "use_boundary": (
                            "技能只约束推理方法，不是事实、文献、假设、计划或实验结果。"
                        ),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )
    messages.append(
        {
            "role": "user",
            "content": json.dumps(user_payload, ensure_ascii=False, sort_keys=True),
        }
    )
    return messages


def _rebuild_exact_authoring_messages(
    *,
    retained_messages: Sequence[Mapping[str, str]],
    frozen_context: Mapping[str, Any],
    container_entry_points: Sequence[str] = (),
    literature: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, str]]:
    """Rebuild a retained plan prompt and reject any extra or changed instruction."""

    normalized = [dict(message) for message in retained_messages]
    selected_skills = frozen_context.get("system_selected_method_skills")
    expected_roles = (
        ["system", "user", "user"]
        if isinstance(selected_skills, Mapping)
        else ["system", "user"]
    )
    if [message.get("role") for message in normalized] != expected_roles:
        raise SystemAuthoredPlanError(
            "计划模型回执消息数量、顺序或角色不符合唯一规范"
        )
    if any(set(message) != {"role", "content"} for message in normalized):
        raise SystemAuthoredPlanError("计划模型回执消息含未授权字段")
    try:
        payload = json.loads(normalized[-1]["content"])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise SystemAuthoredPlanError("计划模型任务消息不是规范 JSON 对象") from exc
    if not isinstance(payload, dict):
        raise SystemAuthoredPlanError("计划模型任务消息必须为 JSON 对象")
    raw_previous = payload.get("previous_system_authored_plan")
    if raw_previous is not None and not isinstance(raw_previous, Mapping):
        raise SystemAuthoredPlanError("待修系统计划必须为对象")
    previous = dict(raw_previous) if isinstance(raw_previous, Mapping) else None
    findings = _authoring_feedback_from_payload(payload)
    expected = _authoring_messages(
        frozen_context=frozen_context,
        prior_findings=findings,
        previous_system_authored_plan=previous,
        container_entry_points=container_entry_points,
        literature=literature,
    )
    if normalized != expected:
        raise SystemAuthoredPlanError(
            "retained plan 回执并非编排器根据冻结输入生成的完整精确消息"
        )
    return expected


def author_research_plan(
    *,
    lineage_id: str,
    project_id: str,
    candidate_id: str,
    frozen_context: Mapping[str, Any],
    evidence_paths: Sequence[Path | str],
    output_dir: Path | str,
    completion: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    max_attempts: int = _MAX_AUTHORING_ATTEMPTS,
    container_entry_points: Sequence[str] = (),
    literature: Sequence[Mapping[str, Any]] = (),
    require_chinese: bool = True,
    scientific_review: Callable[[ResearchPlan, int], Sequence[str]] | None = None,
) -> SystemAuthoredPlanArtifact:
    """Have the system author its own plan, and let the graders teach it.

    Raises `SystemAuthoredPlanError` if the system cannot satisfy its own graders
    within `max_attempts`. A plan that cannot pass is not quietly downgraded.
    """

    scientific_lineage_binding = _build_plan_scientific_lineage_binding(frozen_context)
    authoring_context: dict[str, Any] = dict(frozen_context)
    if scientific_lineage_binding is not None:
        authoring_context["system_plan_scientific_lineage_binding"] = (
            scientific_lineage_binding.model_dump(mode="json")
        )

    # A direction is system-authored prospective science, not an observation.  Its
    # numerical design choices therefore cannot become an evidence-number allowlist.
    # The plan must preserve its method tokens, but any numerical claim still has to
    # be labelled as a newly pre-registered choice or trace to retained evidence.
    numeric_context = dict(authoring_context)
    selected_direction = numeric_context.pop(
        "system_selected_research_direction", None
    )
    numeric_context.pop("system_selected_research_direction_hash", None)
    numeric_context.pop("system_selected_method_skills", None)
    numeric_context.pop("system_audited_research_opportunity_map", None)
    numeric_context.pop("system_component_atom_catalog", None)
    numeric_context.pop("system_prospective_component_atoms", None)
    numeric_context.pop("system_component_experiment_binding", None)
    numeric_context.pop("system_plan_ideation_artifact_hash", None)
    numeric_context.pop("system_plan_scientific_lineage_binding", None)
    required_direction_tokens: tuple[str, ...] = ()
    if isinstance(selected_direction, Mapping):
        raw_tokens = selected_direction.get("method_tokens")
        if isinstance(raw_tokens, Sequence) and not isinstance(
            raw_tokens, str | bytes
        ):
            required_direction_tokens = tuple(str(token) for token in raw_tokens)
    evidence_numbers = collect_evidence_numbers(numeric_context)
    present, missing_inputs = _existing_evidence_refs(evidence_paths)
    if missing_inputs:
        raise SystemAuthoredPlanError(
            f"cannot author a plan against evidence that does not exist: "
            f"{missing_inputs}"
        )
    if not present:
        raise SystemAuthoredPlanError(
            "a plan must cite at least one retained artifact; authoring against no "
            "evidence would produce an unfalsifiable plan"
        )

    findings: list[str] = []
    last_report: AuthoredPlanGuardReport | None = None
    previous_system_authored_plan: dict[str, Any] | None = None
    output_root = Path(output_dir).resolve()
    for attempt in range(1, max_attempts + 1):
        messages = _authoring_messages(
            frozen_context=authoring_context,
            prior_findings=findings,
            previous_system_authored_plan=previous_system_authored_plan,
            container_entry_points=container_entry_points,
            literature=literature,
        )
        try:
            result = completion(
                messages=messages,
                config_path=config_path,
                env_path=env_path,
                timeout_seconds=300,
                max_tokens=8_000,
                temperature=0.3,
                thinking_mode="enabled",
                thinking_budget=4_000,
                response_schema=None,
                response_schema_name="authored_research_plan",
            )
        except (OSError, RuntimeError, ValueError) as exc:
            findings = [
                "your previous provider response could not become a research plan "
                "because the model call or JSON parse failed: "
                f"{type(exc).__name__}: {exc}. Return one complete strict JSON object; "
                "do not change unaffected scientific content."
            ]
            continue
        authorship_receipt = record_model_authorship_receipt(
            artifact_kind="research_plan",
            interaction_id=f"system-authored-plan-attempt-{attempt:02d}",
            attempt=attempt,
            messages=messages,
            completion=result,
            output_dir=output_root,
        )
        if (
            isinstance(
                authoring_context.get("system_selected_method_skills"), Mapping
            )
            and not str(result.reasoning_text or "").strip()
        ):
            findings = [
                "Qwen did not return non-empty reasoning_content; "
                "the system-selected methodology chain is not auditable."
            ]
            continue
        raw_authored = result.parsed_json
        if isinstance(raw_authored, Mapping):
            # Feed the provider's exact prior scientific prose—not an orchestrator
            # rewrite—into the next repair turn.
            previous_system_authored_plan = dict(raw_authored)
        preliminary_context = authoring_context.get("system_preliminary_experiment")
        try:
            authored = _project_authored_plan_payload(
                raw_authored,
                scientific_lineage_binding=scientific_lineage_binding,
                preliminary_context=(
                    preliminary_context
                    if isinstance(preliminary_context, Mapping)
                    else None
                ),
            )
        except (SystemAuthoredPlanError, ValueError) as exc:
            findings = [f"研究计划机械身份投影失败：{exc}"]
            continue
        try:
            authored_response = _AuthoredPlanResponse.model_validate(authored)
        except ValidationError as exc:
            shape_errors = [
                {
                    "field": ".".join(str(part) for part in item["loc"]),
                    "message": item["msg"],
                    "type": item["type"],
                }
                for item in exc.errors(include_input=False)
            ]
            findings = [
                "your json object violates the required field shapes; return arrays "
                "as JSON arrays and strings as single strings: "
                + json.dumps(shape_errors, ensure_ascii=False, sort_keys=True)
            ]
            continue
        if scientific_lineage_binding is None:
            if authored_response.scientific_lineage_attestation is not None:
                findings = [
                    "没有正式机会图→方向谱系时不得自行声称 "
                    "scientific_lineage_attestation"
                ]
                continue
        else:
            attestation_findings = _lineage_attestation_findings(
                binding=scientific_lineage_binding,
                attestation=authored_response.scientific_lineage_attestation,
            )
            if attestation_findings:
                findings = list(attestation_findings)
                continue

        plan = ResearchPlan.model_validate(
            {
                "project_id": project_id,
                "candidate_id": candidate_id,
                "title": authored["title"],
                "abstract": authored["abstract"],
                "problem_statement": authored["problem_statement"],
                "rationale": authored["rationale"],
                "technical_details": authored["technical_details"],
                "datasets": {
                    "source": authored["dataset_source"],
                    "target": authored["dataset_target"],
                },
                "methods": authored["methods"],
                "experiments": list(authored["experiments"]),
                "baselines": list(authored["baselines"]),
                "metrics": list(authored["metrics"]),
                "results": authored_response.results,
                "expected_results": authored["expected_results"],
                "code_agent_brief": authored["code_agent_brief"],
                "risks_and_alternatives": list(authored["risks_and_alternatives"]),
                "references": list(authored["references"]),
                # Derived, never authored: a model cannot cite what does not exist.
                "evidence_refs": present,
                # 检索所得的真实文献随计划一起留存，顺序与正文 [n] 编号一致，
                # 这样 LaTeX 参考文献表能与行内引用对上号。
                "literature_references": list(literature),
                "status": ResearchPlanStatus.DRAFT,
            }
        )
        if scientific_lineage_binding is not None:
            lineage_findings = _plan_scientific_lineage_findings(
                plan=plan,
                binding=scientific_lineage_binding,
            )
            if lineage_findings:
                findings = list(lineage_findings)
                continue
        report = guard_authored_plan(
            plan=plan,
            evidence_numbers=evidence_numbers,
            cited_evidence=present,
            container_entry_points=container_entry_points,
            required_direction_tokens=required_direction_tokens,
            literature_count=len(literature),
            require_chinese=require_chinese,
        )
        last_report = report
        if not report.accepted:
            findings = list(report.findings)
            continue

        audit = audit_research_plan(plan)
        graded = plan.model_copy(
            update={
                "quality_gate": audit.to_dict(),
                "status": ResearchPlanStatus.READY_FOR_APPROVAL,
                "validation_status": audit.verdict,
            }
        )
        if scientific_review is not None:
            try:
                review_findings = tuple(scientific_review(graded, attempt))
            except (OSError, RuntimeError, ValueError) as exc:
                findings = [
                    "the mandatory adversarial scientific review failed closed: "
                    f"{exc}. Keep the valid plan shape and repair only what the "
                    "review response requires."
                ]
                continue
            if review_findings:
                findings = [
                    "mandatory adversarial scientific review: " + str(item)
                    for item in review_findings
                ]
                continue
        usage = result.usage if isinstance(result.usage, dict) else {}
        details = usage.get("completion_tokens_details")
        reasoning_tokens = (
            int(details.get("reasoning_tokens") or 0) if isinstance(details, dict) else 0
        )
        plan_payload = graded.model_dump(mode="json")
        output_path = output_root / _PLAN_NAME
        payload: dict[str, Any] = {
            # v1 is load-only compatibility. Every artifact authored by current code
            # uses v2, even isolated calls that have no formal prospective lineage.
            "schema_version": "system-authored-research-plan-v2",
            "lineage_id": lineage_id,
            "plan": plan_payload,
            "plan_hash": canonical_model_hash(plan_payload),
            "guard_report": report.model_dump(mode="json"),
            "authoring_attempts": attempt,
            "model_name": result.model_name,
            "reasoning_tokens": reasoning_tokens,
            "authorship_receipt_relative_path": Path(
                authorship_receipt.output_path
            ).resolve().relative_to(output_root).as_posix(),
            "authorship_receipt_hash": authorship_receipt.receipt_hash,
            **(
                {
                    "scientific_lineage_binding": (
                        scientific_lineage_binding.model_dump(mode="json")
                    ),
                    "scientific_lineage_attestation": (
                        authored_response.scientific_lineage_attestation.model_dump(
                            mode="json"
                        )
                    ),
                }
                if scientific_lineage_binding is not None
                and authored_response.scientific_lineage_attestation is not None
                else {}
            ),
            "authored_by_model": True,
            "hand_written_prose_field_count": 0,
            "execution_authorized": False,
            "is_evidence": False,
        }
        payload["artifact_hash"] = canonical_model_hash(payload)
        payload["output_path"] = output_path.as_posix()
        artifact = SystemAuthoredPlanArtifact.model_validate(payload)
        write_json_model(output_path, artifact)
        # 同时落盘一份给人读的 Markdown。JSON 仍是唯一权威（plan_hash 绑定它的规范字节），
        # Markdown 由 JSON 单向派生，且头部写明两个哈希，任何引文都能回溯。
        # 渲染失败不能让一份已经通过全部 grader 的计划丢失，所以这里不向外抛。
        try:
            markdown_path = output_path.with_suffix(".md")
            markdown_path.write_text(
                render_plan_artifact_markdown(artifact.model_dump(mode="json")),
                encoding="utf-8",
            )
        except (OSError, ValueError):
            pass
        # 再落一份《科学假设与研究计划》LaTeX。参考文献用非严格模式：文献调研是独立
        # 步骤，尚未接入时缺口会被显著写进文档，而不是静默放过或由渲染器编造条目。
        try:
            from autoresearch.competition.research_plan_latex import (
                render_research_plan_latex,
            )

            output_path.with_suffix(".tex").write_text(
                render_research_plan_latex(
                    plan=plan_payload,
                    references=plan_payload.get("literature_references") or (),
                    plan_hash=payload["plan_hash"],
                    artifact_hash=payload["artifact_hash"],
                    lineage_id=lineage_id,
                    model_name=result.model_name,
                    strict_references=False,
                ),
                encoding="utf-8",
            )
        except (OSError, ValueError, RuntimeError):
            pass
        return artifact

    # `last_report` may be accepted by the deterministic guard while the mandatory
    # scientific review still refuses the plan.  In that case its findings are
    # intentionally empty, so prefer the most recent loop-level failure detail.
    # Otherwise the CLI would misleadingly print `final findings: []` after a
    # scientifically rejected final attempt.
    detail = findings or (list(last_report.findings) if last_report else [])
    raise SystemAuthoredPlanError(
        f"the system could not author a plan its own graders accept in {max_attempts} "
        f"attempts; final findings: {detail}"
    )
