"""Opt-in live mechanism tournament and workload qualification for Task 263.6.4."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.research import (
    ExactPairedPowerScenario,
    LiveResourceProbe,
    MechanismTrackKind,
    MechanismTrackPlan,
    NearestWorkDelta,
    ResearchSource,
    ResourceKind,
    ResultBlindnessAudit,
    SourceMaturity,
    TrackProspectivePowerPlan,
    TrackResourceAudit,
    WorkloadQualifiedOpportunityEntry,
    WorkloadQualifiedOpportunityReport,
    probe_web_resource,
    run_workload_qualification,
    write_workload_qualified_opportunity,
)

LIVE_ENV = "AUTORESEARCH_WORKLOAD_QUALIFIED_OPPORTUNITY_LIVE"
OUTPUT_ENV = "AUTORESEARCH_WORKLOAD_QUALIFIED_OPPORTUNITY_OUTPUT"
INTERPRETER_A_ENV = "AUTORESEARCH_WORKLOAD_INTERPRETER_A"
INTERPRETER_B_ENV = "AUTORESEARCH_WORKLOAD_INTERPRETER_B"

pytestmark = pytest.mark.skipif(
    os.getenv(LIVE_ENV) != "1",
    reason=(
        f"set {LIVE_ENV}=1 to probe primary papers, open resources, "
        "DiscoveryBench source groups, and two clean interpreters"
    ),
)


@dataclass(frozen=True)
class SourceDefinition:
    source_id: str
    title: str
    year: int
    locator: str
    url: str
    maturity: SourceMaturity
    shared_scope: str
    claimed_delta: str
    overlap_risk: str
    decisive_comparison: str


@dataclass(frozen=True)
class ResourceDefinition:
    resource_id: str
    kind: ResourceKind
    url: str


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        connect=4,
        read=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def _source_probe(
    definition: SourceDefinition,
    *,
    checked_at: datetime,
    session: requests.Session,
) -> LiveResourceProbe:
    return probe_web_resource(
        resource_id=definition.source_id,
        kind=ResourceKind.LITERATURE,
        url=definition.url,
        checked_at=checked_at,
        session=session,
        timeout_seconds=60,
        max_sample_bytes=65_536,
    )


def _resource_probe(
    definition: ResourceDefinition,
    *,
    checked_at: datetime,
    session: requests.Session,
) -> LiveResourceProbe:
    return probe_web_resource(
        resource_id=definition.resource_id,
        kind=definition.kind,
        url=definition.url,
        checked_at=checked_at,
        session=session,
        timeout_seconds=60,
        max_sample_bytes=65_536,
    )


def _power_plan(
    track_id: MechanismTrackKind,
    *,
    accessible_independent_unit_count: int,
) -> TrackProspectivePowerPlan:
    probabilities = {
        0.15: (0.25, 0.10),
        0.20: (0.30, 0.10),
        0.25: (0.35, 0.10),
    }
    scenarios = [
        ExactPairedPowerScenario.create(
            independent_unit_count=max(1, accessible_independent_unit_count),
            alpha=0.05,
            target_power=0.8,
            minimum_effect=effect,
            favorable_probability=favorable,
            unfavorable_probability=unfavorable,
        )
        for effect, (favorable, unfavorable) in probabilities.items()
    ]
    return TrackProspectivePowerPlan.create(
        track_id=track_id,
        endpoint=(
            "paired objective correctness per independent source group under "
            "the frozen strong-baseline comparison"
        ),
        accessible_independent_unit_count=accessible_independent_unit_count,
        scenarios=scenarios,
    )


def _source_material(
    definitions: list[SourceDefinition],
    probes: list[LiveResourceProbe],
) -> tuple[list[ResearchSource], list[NearestWorkDelta]]:
    probe_by_id = {probe.resource_id: probe for probe in probes}
    sources = [
        ResearchSource(
            source_id=definition.source_id,
            title=definition.title,
            year=definition.year,
            locator=definition.locator,
            source_url=definition.url,
            maturity=definition.maturity,
            source_fingerprint=probe_by_id[definition.source_id].sample_sha256,
        )
        for definition in definitions
    ]
    nearest_work = [
        NearestWorkDelta(
            source_id=definition.source_id,
            shared_scope=definition.shared_scope,
            claimed_delta=definition.claimed_delta,
            overlap_risk=definition.overlap_risk,
            decisive_comparison=definition.decisive_comparison,
        )
        for definition in definitions
    ]
    return sources, nearest_work


def _discoverybench_inventory(
    session: requests.Session,
) -> tuple[list[str], str, str]:
    tree_url = (
        "https://huggingface.co/api/datasets/allenai/discoverybench/"
        "tree/main?recursive=true&expand=false&limit=1000"
    )
    response = session.get(tree_url, timeout=60)
    response.raise_for_status()
    items = response.json()
    if not isinstance(items, list) or len(items) != 987:
        raise AssertionError("DiscoveryBench live tree changed; re-audit the inventory")
    source_groups = sorted(
        item["path"]
        for item in items
        if item.get("type") == "directory"
        and len(str(item.get("path", "")).split("/")) == 4
        and str(item["path"]).startswith("discoverybench/")
    )
    if len(source_groups) != 189:
        raise AssertionError(
            "DiscoveryBench no longer exposes the frozen 189 source-group folders"
        )
    metadata_url = "https://huggingface.co/api/datasets/allenai/discoverybench"
    metadata_response = session.get(metadata_url, timeout=60)
    metadata_response.raise_for_status()
    metadata = metadata_response.json()
    if metadata.get("cardData", {}).get("license") != "odc-by":
        raise AssertionError("DiscoveryBench ODC-By metadata changed")
    return source_groups, canonical_sha256(source_groups), tree_url


def _build_track_entry(
    *,
    track_id: MechanismTrackKind,
    source_definitions: list[SourceDefinition],
    resource_definitions: list[ResourceDefinition],
    resource_audit_values: dict[str, object],
    checked_at: datetime,
    session: requests.Session,
    runner_path: Path,
    interpreters: dict[str, Path],
) -> WorkloadQualifiedOpportunityEntry:
    source_probes = [
        _source_probe(definition, checked_at=checked_at, session=session)
        for definition in source_definitions
    ]
    if not all(probe.reachable for probe in source_probes):
        failures = [
            probe.resource_id for probe in source_probes if not probe.reachable
        ]
        raise AssertionError(f"primary source probes failed: {failures}")
    resource_probes = [
        _resource_probe(definition, checked_at=checked_at, session=session)
        for definition in resource_definitions
    ]
    sources, nearest_work = _source_material(source_definitions, source_probes)
    resource_audit = TrackResourceAudit.create(
        track_id=track_id,
        **resource_audit_values,
    )
    power_plan = _power_plan(
        track_id,
        accessible_independent_unit_count=(
            resource_audit.accessible_independent_unit_count
        ),
    )
    workload = run_workload_qualification(
        track_id=track_id,
        stratum_id="representative-development-v1",
        runner_path=runner_path,
        interpreters=interpreters,
        input_seed=26_364,
        algorithmic_work_units=20_000,
        algorithmic_cpu_seconds_budget=5.0,
        concurrency_levels=(1, 2),
        qualification_repeat_count=3,
        calibration_deadline_seconds=30.0,
        minimum_timeout_slack_ratio=8.0,
        minimum_qualification_deadline_seconds=2.0,
    )
    if not workload.qualified:
        raise AssertionError(
            f"representative workload did not qualify: {track_id.value} "
            f"{workload.blockers}"
        )
    result_blindness = ResultBlindnessAudit.create(
        forbidden_lineage_hashes=[
            "6b7f124fab513e8032ff777b2a92926cf5e57836d409ad133700c49946cea22b",
            "7069ae95433cf7f83c86d35993dd3bd88020e919102d01594574c1860b3c8031",
            "f756ab01b1e7291875470e75d63e5fe668bf199a50659c041799e038578f9dd0",
        ],
        accessed_input_hashes=[
            *(probe.probe_hash for probe in source_probes),
            *(probe.probe_hash for probe in resource_probes),
            workload.specification.spec_hash,
        ],
    )
    plan = MechanismTrackPlan.create(
        track_id=track_id,
        literature_cutoff=checked_at.date(),
        sources=sources,
        nearest_work=nearest_work,
        source_probes=source_probes,
        resource_probes=resource_probes,
        resource_audit=resource_audit,
        power_plan=power_plan,
        workload_certificate=workload,
        result_blindness_audit=result_blindness,
        **_scientific_plan_values(track_id),
    )
    return WorkloadQualifiedOpportunityEntry.create(plan)


def _scientific_plan_values(track_id: MechanismTrackKind) -> dict[str, object]:
    common = {
        "primary_endpoint": (
            "paired objective correctness per independent source group, scored "
            "by a deterministic answer-key evaluator"
        ),
        "smallest_effect_of_interest": 0.20,
        "result_blind_publication_endpoint": (
            "positive mechanism effect, system/reproducibility contribution, "
            "or diagnostic negative boundary"
        ),
    }
    if track_id is MechanismTrackKind.STRUCTURED_WORLD_MODEL:
        return {
            **common,
            "main_claim": (
                "A provenance-bound evidence graph improves objective scientific "
                "decision correctness by at least 0.20 over the strongest open baseline."
            ),
            "mechanism": (
                "A structured world model binds claims, evidence, code, and "
                "counterevidence before each research action."
            ),
            "strong_baseline_comparison": (
                "same-budget flat notebook/tool agent without persistent graph coherence"
            ),
            "falsification_rule": (
                "reject if an open strong baseline, deterministic evaluator, "
                "licensed dataset, 84 units, or the paired SESOI cannot be recovered"
            ),
            "failure_case_update": (
                "record that structured traces improve inspectability but have "
                "no demonstrated objective scientific effect in an open testbed"
            ),
            "required_ablations": [
                "remove evidence-edge validation while retaining graph storage",
                "replace the graph with the same facts in flat context",
                "shuffle provenance links without changing token budget",
            ],
        }
    if track_id is MechanismTrackKind.SOCRATIC_FALSIFICATION:
        return {
            **common,
            "main_claim": (
                "A frozen causal/constraint/counterexample/falsification critic "
                "improves exact discovery decisions by at least 0.20 over a "
                "same-budget Asta/DiscoveryBench baseline."
            ),
            "mechanism": (
                "Before acceptance, a deterministic protocol asks causal, "
                "constraint, counterexample, and explicit falsifier questions."
            ),
            "strong_baseline_comparison": (
                "same-model same-tool Asta-style ReAct baseline with equal call "
                "and wall-clock budgets but no Socratic critic"
            ),
            "falsification_rule": (
                "reject if the paired exact endpoint misses 0.20, null Type-I "
                "control fails, or any single critic ablation explains the effect"
            ),
            "failure_case_update": (
                "publish or log the critic boundary and error taxonomy even when "
                "the prospective effect is absent"
            ),
            "required_ablations": [
                "causal questions only",
                "constraint checks only",
                "counterexample search only",
                "explicit falsifier criteria only",
                "full critic with equalized inference budget",
            ],
        }
    return {
        **common,
        "main_claim": (
            "Execution or laboratory feedback improves objective research "
            "decisions by at least 0.20 while preserving explicit human duties."
        ),
        "mechanism": (
            "The agent proposes bounded actions, observes an external "
            "environment, and routes safety/scientific responsibility to humans."
        ),
        "strong_baseline_comparison": (
            "same-budget proposal agent without external feedback, plus the "
            "published execution-grounded baseline"
        ),
        "falsification_rule": (
            "reject if fewer than 84 independent open environments exist, "
            "licenses are unclear, compute is unavailable, or human duties blur"
        ),
        "failure_case_update": (
            "record the boundary between reproducible environment feedback and "
            "non-delegable laboratory or publication responsibility"
        ),
        "required_ablations": [
            "remove environment feedback while retaining action budget",
            "replace feedback with a static simulator trace",
            "remove the explicit human approval checkpoint",
        ],
    }


def test_task26364_live_workload_qualified_opportunity() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    output_root = Path(
        os.getenv(
            OUTPUT_ENV,
            str(
                repository_root
                / "runs"
                / "manual-live"
                / "task26364-workload-qualified-opportunity-v1"
            ),
        )
    ).resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise AssertionError("live output directory must be absent or empty")

    interpreter_a = Path(
        os.getenv(
            INTERPRETER_A_ENV,
            str(
                repository_root
                / "runs"
                / "manual-live"
                / "task26342-clean-baseline-preregistration-v2"
                / "clean-venv-a"
                / "Scripts"
                / "python.exe"
            ),
        )
    ).resolve()
    interpreter_b = Path(
        os.getenv(
            INTERPRETER_B_ENV,
            str(
                repository_root
                / "runs"
                / "manual-live"
                / "task26342-clean-baseline-preregistration-v2"
                / "clean-venv-b"
                / "Scripts"
                / "python.exe"
            ),
        )
    ).resolve()
    if not interpreter_a.is_file() or not interpreter_b.is_file():
        raise AssertionError("both frozen clean interpreter installations are required")
    interpreters = {"clean-a": interpreter_a, "clean-b": interpreter_b}
    runner_path = (
        repository_root
        / "src"
        / "autoresearch"
        / "research"
        / "assets"
        / "frozen_mechanism_workload_probe_v1.py"
    )
    checked_at = datetime.now(timezone.utc)
    session = _session()
    source_groups, discovery_inventory_hash, discovery_tree_url = (
        _discoverybench_inventory(session)
    )
    assert len(source_groups) == 189

    structured_sources = [
        SourceDefinition(
            source_id="world.kosmos",
            title="Kosmos: An AI Scientist for Autonomous Discovery",
            year=2025,
            locator="arXiv:2511.02824",
            url="https://arxiv.org/html/2511.02824",
            maturity=SourceMaturity.PREPRINT,
            shared_scope="Long-horizon automated discovery with a structured world model.",
            claimed_delta="Tests objective incremental effect rather than statement accuracy alone.",
            overlap_risk="A structured world model is already the central Kosmos mechanism.",
            decisive_comparison="Open same-budget graph versus flat-context paired benchmark.",
        ),
        SourceDefinition(
            source_id="world.graph-of-trace",
            title="Graph of Trace: Making Scientific Agents Inspectable",
            year=2026,
            locator="arXiv:2606.15116",
            url="https://arxiv.org/html/2606.15116",
            maturity=SourceMaturity.PREPRINT,
            shared_scope="Graph representation of scientific-agent trajectories.",
            claimed_delta="Moves from expert usability to objective scientific correctness.",
            overlap_risk="Graph structure and trace inspection substantially overlap.",
            decisive_comparison="Blind exact endpoint, not expert trace preference.",
        ),
        SourceDefinition(
            source_id="world.code-harness",
            title="Code as an Agent Harness",
            year=2026,
            locator="arXiv:2605.18747",
            url="https://arxiv.org/html/2605.18747",
            maturity=SourceMaturity.PREPRINT,
            shared_scope="Code unifies reasoning, action, state, and verification.",
            claimed_delta="Requires regression-free workload qualification and objective effect.",
            overlap_risk="Code-backed state already behaves as a structured world model.",
            decisive_comparison="Same code tools with and without evidence-graph constraints.",
        ),
    ]
    structured_resources = [
        ResourceDefinition(
            "kosmos-figures-repository",
            ResourceKind.REPOSITORY,
            "https://api.github.com/repos/EdisonScientific/kosmos-figures",
        ),
        ResourceDefinition(
            "kosmos-figures-data",
            ResourceKind.DATASET,
            "https://api.github.com/repos/EdisonScientific/kosmos-figures/contents",
        ),
        ResourceDefinition(
            "kosmos-license-evidence",
            ResourceKind.LICENSE,
            "https://api.github.com/repos/EdisonScientific/kosmos-figures/license",
        ),
    ]
    structured_resource_audit = {
        "strong_baseline_id": "kosmos-structured-world-model",
        "strong_baseline_description": (
            "the reported Kosmos world-model system under its approximately "
            "200-rollout, 12-hour discovery regime"
        ),
        "strong_baseline_spec_sha256": canonical_sha256(
            {"source": "arXiv:2511.02824", "role": "strong baseline"}
        ),
        "strong_baseline_reference_available": False,
        "objective_evaluator_id": "world-model-objective-decision-evaluator",
        "objective_evaluator_description": (
            "paired exact correctness on independently keyed scientific decisions"
        ),
        "objective_evaluator_sha256": canonical_sha256(
            {"endpoint": "paired exact correctness", "version": 1}
        ),
        "objective_evaluator_specification_available": False,
        "dataset_id": "kosmos-public-figure-subset",
        "dataset_inventory_sha256": canonical_sha256(
            {"available": "figure scripts only", "system_data": "incomplete"}
        ),
        "data_access_verified": False,
        "accessible_independent_unit_count": 0,
        "independence_grouping_basis": (
            "no open objective task inventory is available for scientific grouping"
        ),
        "reference_code_license": "no verified official system-code license",
        "dataset_license": "incomplete; some source data deferred",
        "reference_code_license_verified": False,
        "dataset_license_verified": False,
        "estimated_development_cost_usd": 1_000.0,
        "estimated_development_walltime_hours": 240.0,
        "required_compute": "unreleased system plus long-horizon model rollouts",
        "available_compute": "local CPU qualification only",
        "compute_feasible": False,
        "human_responsibility_boundary": (
            "humans remain responsible for source legality, scientific validity, "
            "interpretation, and publication"
        ),
        "excluded_resource_reasons": [
            "Kosmos figure scripts do not reproduce the autonomous system",
            "statement-accuracy review is not an incremental mechanism endpoint",
            "some underlying datasets are unavailable pending future publication",
        ],
        "repository_probe_ids": ["kosmos-figures-repository"],
        "dataset_probe_ids": ["kosmos-figures-data"],
        "license_probe_ids": ["kosmos-license-evidence"],
    }

    socratic_sources = [
        SourceDefinition(
            source_id="socratic.ahois",
            title="Socratic Agents Enable Autonomous Hypothesis Discovery in Physics",
            year=2026,
            locator="arXiv:2606.26722",
            url="https://arxiv.org/html/2606.26722",
            maturity=SourceMaturity.PREPRINT,
            shared_scope="Causal questions, constraints, counterexamples, and falsifiers.",
            claimed_delta="Tests the critic causally across many independent source groups.",
            overlap_risk="The proposed critic primitives directly overlap AHOIS.",
            decisive_comparison="Same-model same-budget component ablation with exact scoring.",
        ),
        SourceDefinition(
            source_id="socratic.popper",
            title="POPPER: Automated Hypothesis Testing with Agentic Sequential Falsifications",
            year=2025,
            locator="PMLR 267:19923-19949",
            url="https://proceedings.mlr.press/v267/huang25n.html",
            maturity=SourceMaturity.PEER_REVIEWED,
            shared_scope="Sequential falsification with explicit Type-I error control.",
            claimed_delta="Adds a four-part critic and open clean-room evaluation boundary.",
            overlap_risk="Falsification and statistical control are prior art.",
            decisive_comparison="POPPER-style sequential test versus the frozen full critic.",
        ),
        SourceDefinition(
            source_id="socratic.discoverybench",
            title="DiscoveryBench: Towards Data-Driven Discovery with Large Language Models",
            year=2024,
            locator="arXiv:2407.01725",
            url="https://arxiv.org/abs/2407.01725",
            maturity=SourceMaturity.PREPRINT,
            shared_scope="Open data-driven discovery tasks and structured answer keys.",
            claimed_delta="Uses independent source groups and an exact paired primary endpoint.",
            overlap_risk="DiscoveryBench already benchmarks multi-step discovery.",
            decisive_comparison="Clean-room baseline versus critic on identical source groups.",
        ),
        SourceDefinition(
            source_id="socratic.astabench",
            title="AstaBench: Rigorous Benchmarking of AI Agents with a Scientific Research Suite",
            year=2026,
            locator="ICLR 2026, OpenReview M7TNf5J26u",
            url="https://arxiv.org/abs/2510.21652",
            maturity=SourceMaturity.PEER_REVIEWED,
            shared_scope="Standardized scientific-agent tools, environments, cost, and scoring.",
            claimed_delta="Restricts the gate to objective DiscoveryBench-style endpoints.",
            overlap_risk="AstaBench already supplies strong agents and a reusable harness.",
            decisive_comparison="Equalized Asta-style baseline with deterministic scoring only.",
        ),
        SourceDefinition(
            source_id="socratic.sciagentarena",
            title="Benchmarking AI Agents for Addressing Scientific Challenges Across Scales",
            year=2026,
            locator="arXiv:2606.12736",
            url="https://arxiv.org/abs/2606.12736",
            maturity=SourceMaturity.PREPRINT,
            shared_scope=(
                "Approximately 200 stepwise-verified scientific tasks, including "
                "validity checks and deliberately invalid premises."
            ),
            claimed_delta=(
                "Causally isolates a four-part critic rather than reporting "
                "cross-agent benchmark rankings and failure taxonomy."
            ),
            overlap_risk=(
                "Its validity category, premise checking, and structured refusal "
                "substantially narrow the available novelty claim."
            ),
            decisive_comparison=(
                "After license clearance, equal-budget baseline and component "
                "ablations on objective invalid-task decisions."
            ),
        ),
    ]
    socratic_resources = [
        ResourceDefinition(
            "asta-bench-repository",
            ResourceKind.REPOSITORY,
            "https://api.github.com/repos/allenai/asta-bench",
        ),
        ResourceDefinition(
            "discoverybench-source-tree",
            ResourceKind.DATASET,
            discovery_tree_url,
        ),
        ResourceDefinition(
            "asta-bench-license",
            ResourceKind.LICENSE,
            "https://api.github.com/repos/allenai/asta-bench/license",
        ),
        ResourceDefinition(
            "discoverybench-license-metadata",
            ResourceKind.LICENSE,
            "https://huggingface.co/api/datasets/allenai/discoverybench",
        ),
    ]
    socratic_resource_audit = {
        "strong_baseline_id": "asta-react-discoverybench-clean-room",
        "strong_baseline_description": (
            "same-model same-tool Asta-style ReAct baseline, reconstructed "
            "without importing unlicensed POPPER or database-licensed code"
        ),
        "strong_baseline_spec_sha256": canonical_sha256(
            {
                "harness": "AstaBench Apache-2.0",
                "data": "DiscoveryBench ODC-By-1.0",
                "comparison": "same model, tools, calls, and wall-clock budget",
            }
        ),
        "strong_baseline_reference_available": True,
        "objective_evaluator_id": "discoverybench-exact-decision-evaluator",
        "objective_evaluator_description": (
            "clean-room binary fault-injection decision labels derived before "
            "execution from gold hypotheses; no free-form answer or model judge "
            "may enter the primary gate"
        ),
        "objective_evaluator_sha256": canonical_sha256(
            {
                "source_answer_keys": [
                    "answer_key/answer_key_real.csv",
                    "answer_key/answer_key_synth.csv",
                ],
                "planned_endpoint": "frozen valid-versus-fault-injected decision",
                "unit": "depth-four source-group folder",
                "version": 1,
            }
        ),
        "objective_evaluator_specification_available": True,
        "dataset_id": "allenai-discoverybench-source-groups",
        "dataset_inventory_sha256": discovery_inventory_hash,
        "data_access_verified": True,
        "accessible_independent_unit_count": len(source_groups),
        "independence_grouping_basis": (
            "189 depth-four dataset folders are provisional source groups; "
            "provenance deduplication is mandatory before any scientific freeze"
        ),
        "reference_code_license": (
            "AstaBench Apache-2.0; POPPER has no verified repository license "
            "and is excluded from code reuse"
        ),
        "dataset_license": "DiscoveryBench ODC-By-1.0 database license",
        "reference_code_license_verified": True,
        "dataset_license_verified": True,
        "estimated_development_cost_usd": 50.0,
        "estimated_development_walltime_hours": 40.0,
        "required_compute": "two local CPU interpreters plus bounded model calls later",
        "available_compute": "two clean local CPU interpreters",
        "compute_feasible": True,
        "human_responsibility_boundary": (
            "humans approve source use, freeze the scientific question, inspect "
            "failures, interpret evidence, and authorize any release"
        ),
        "excluded_resource_reasons": [
            "POPPER repository code excluded because no license file is verified",
            "AstaBench gated aggregate dataset excluded from the primary open panel",
            "LLM-judged Asta tasks excluded from the primary endpoint",
            "SciAgentArena data are gated and its public repository has no verified license",
        ],
        "repository_probe_ids": ["asta-bench-repository"],
        "dataset_probe_ids": ["discoverybench-source-tree"],
        "license_probe_ids": [
            "asta-bench-license",
            "discoverybench-license-metadata",
        ],
    }

    external_sources = [
        SourceDefinition(
            source_id="external.robin",
            title="An AI Scientist for Autonomous Experimentation and Discovery",
            year=2026,
            locator="Nature s41586-026-10652-y",
            url="https://www.nature.com/articles/s41586-026-10652-y",
            maturity=SourceMaturity.PEER_REVIEWED,
            shared_scope="Semi-autonomous laboratory-in-the-loop discovery.",
            claimed_delta="Requires explicit human duties and independent open environments.",
            overlap_risk="Laboratory feedback is the central prior mechanism.",
            decisive_comparison="Same proposal policy with and without real feedback.",
        ),
        SourceDefinition(
            source_id="external.execution-grounded",
            title="Execution-Grounded Automated AI Research",
            year=2026,
            locator="arXiv:2601.14525",
            url="https://arxiv.org/html/2601.14525",
            maturity=SourceMaturity.PREPRINT,
            shared_scope="Execution feedback evolves research solutions.",
            claimed_delta="Requires generalization across at least 84 independent environments.",
            overlap_risk="Execution feedback and evolutionary search are existing mechanisms.",
            decisive_comparison="Held-out environments under equal compute and no outcome reuse.",
        ),
        SourceDefinition(
            source_id="external.eurekagent",
            title="EurekAgent: Environment Engineering for AI Agents",
            year=2026,
            locator="arXiv:2606.13662",
            url="https://arxiv.org/html/2606.13662",
            maturity=SourceMaturity.PREPRINT,
            shared_scope="Permissions, artifacts, budgets, graders, and human checkpoints.",
            claimed_delta="Tests scientific effect rather than environment solvability alone.",
            overlap_risk="Environment engineering and hidden graders are prior art.",
            decisive_comparison="Scientific endpoint with unchanged environment/grader budget.",
        ),
    ]
    external_resources = [
        ResourceDefinition(
            "execution-grounded-repository",
            ResourceKind.REPOSITORY,
            "https://api.github.com/repos/NoviScl/Automated-AI-Researcher",
        ),
        ResourceDefinition(
            "execution-grounded-environments",
            ResourceKind.DATASET,
            "https://api.github.com/repos/NoviScl/Automated-AI-Researcher/contents",
        ),
        ResourceDefinition(
            "execution-grounded-license",
            ResourceKind.LICENSE,
            "https://api.github.com/repos/NoviScl/Automated-AI-Researcher/license",
        ),
    ]
    external_resource_audit = {
        "strong_baseline_id": "execution-grounded-automated-ai-researcher",
        "strong_baseline_description": (
            "published execution-grounded post-training and nanoGPT environments"
        ),
        "strong_baseline_spec_sha256": canonical_sha256(
            {"source": "arXiv:2601.14525", "environments": 2}
        ),
        "strong_baseline_reference_available": True,
        "objective_evaluator_id": "external-environment-objective-score",
        "objective_evaluator_description": (
            "deterministic environment score with human responsibility ledger"
        ),
        "objective_evaluator_sha256": canonical_sha256(
            {"endpoint": "environment objective score", "version": 1}
        ),
        "objective_evaluator_specification_available": True,
        "dataset_id": "execution-grounded-two-environments",
        "dataset_inventory_sha256": canonical_sha256(
            ["post-training", "nanoGPT"]
        ),
        "data_access_verified": True,
        "accessible_independent_unit_count": 2,
        "independence_grouping_basis": (
            "the paper reports two distinct execution environments"
        ),
        "reference_code_license": "no repository license file verified",
        "dataset_license": "no separate environment-data license verified",
        "reference_code_license_verified": False,
        "dataset_license_verified": False,
        "estimated_development_cost_usd": 2_000.0,
        "estimated_development_walltime_hours": 240.0,
        "required_compute": "reported nanoGPT route uses eight H100 GPUs",
        "available_compute": "local CPU qualification only",
        "compute_feasible": False,
        "human_responsibility_boundary": (
            "humans execute wet-lab protocols, approve unsafe or costly actions, "
            "interpret results, and own publication decisions"
        ),
        "excluded_resource_reasons": [
            "two execution environments cannot support the prospective paired power",
            "reported nanoGPT compute exceeds the available envelope",
            "repository and environment license scopes are not verified",
            "Robin laboratory actions remain human-executed and cannot be delegated",
        ],
        "repository_probe_ids": ["execution-grounded-repository"],
        "dataset_probe_ids": ["execution-grounded-environments"],
        "license_probe_ids": ["execution-grounded-license"],
    }

    entries = [
        _build_track_entry(
            track_id=MechanismTrackKind.STRUCTURED_WORLD_MODEL,
            source_definitions=structured_sources,
            resource_definitions=structured_resources,
            resource_audit_values=structured_resource_audit,
            checked_at=checked_at,
            session=session,
            runner_path=runner_path,
            interpreters=interpreters,
        ),
        _build_track_entry(
            track_id=MechanismTrackKind.SOCRATIC_FALSIFICATION,
            source_definitions=socratic_sources,
            resource_definitions=socratic_resources,
            resource_audit_values=socratic_resource_audit,
            checked_at=checked_at,
            session=session,
            runner_path=runner_path,
            interpreters=interpreters,
        ),
        _build_track_entry(
            track_id=MechanismTrackKind.EXTERNAL_FEEDBACK,
            source_definitions=external_sources,
            resource_definitions=external_resources,
            resource_audit_values=external_resource_audit,
            checked_at=checked_at,
            session=session,
            runner_path=runner_path,
            interpreters=interpreters,
        ),
    ]
    report = WorkloadQualifiedOpportunityReport.create(
        tournament_id="task26364-workload-qualified-opportunity-v1",
        created_at=datetime.now(timezone.utc),
        entries=entries,
    )
    assert report.selected_track_id is MechanismTrackKind.SOCRATIC_FALSIFICATION
    assert report.eligible_track_ids == [
        MechanismTrackKind.SOCRATIC_FALSIFICATION
    ]
    assert report.research_question_certificate_issued is False
    assert report.confirmatory_panel_created is False
    assert report.novelty_search_started is False
    assert report.external_submission_authorized is False
    manifest = write_workload_qualified_opportunity(output_root, report)
    assert manifest.report_hash == report.report_hash
    assert (output_root / "workload-qualified-opportunity.json").is_file()
    assert (output_root / "workload-qualified-opportunity.md").is_file()
    assert (output_root / "workload-qualified-opportunity-schemas.json").is_file()
