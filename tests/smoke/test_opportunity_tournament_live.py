"""Opt-in live opportunity tournament for Task 263.3."""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.research import (
    BaselineReproductionPlan,
    MetricDirection,
    NearestWorkDelta,
    OpportunityTournamentEntry,
    OpportunityTournamentReport,
    PowerSensitivityAudit,
    PrimaryMetricSpec,
    ProspectivePowerPlan,
    PublicationEndpoint,
    ResearchBudget,
    ResearchDataSplit,
    ResearchOpportunity,
    ResearchQuestionCertificate,
    ResearchSource,
    ResourceKind,
    SourceMaturity,
    TrackFeasibilityAudit,
    blocked_baseline_smoke,
    environment_fingerprint,
    probe_web_resource,
    run_baseline_command_smoke,
    write_opportunity_tournament,
)

LIVE_ENV = "AUTORESEARCH_OPPORTUNITY_TOURNAMENT_LIVE"
OUTPUT_ENV = "AUTORESEARCH_OPPORTUNITY_TOURNAMENT_OUTPUT"

pytestmark = pytest.mark.skipif(
    os.getenv(LIVE_ENV) != "1",
    reason=(
        f"set {LIVE_ENV}=1 to probe the frozen papers, repositories, datasets, "
        "licenses, and local baseline surfaces"
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


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _available_compute() -> str:
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return f"{platform.platform()}; NVIDIA telemetry unavailable"
    rendered = completed.stdout.strip() or completed.stderr.strip()
    return f"{platform.platform()}; {rendered[:700]}"


def _probe_sources(
    *,
    definitions: list[SourceDefinition],
    checked_at: datetime,
    session: requests.Session,
) -> tuple[list[ResearchSource], list[NearestWorkDelta], list]:
    probes = [
        probe_web_resource(
            resource_id=definition.source_id,
            kind=ResourceKind.LITERATURE,
            url=definition.url,
            checked_at=checked_at,
            session=session,
        )
        for definition in definitions
    ]
    assert all(probe.reachable for probe in probes), [
        (probe.resource_id, probe.error) for probe in probes if not probe.reachable
    ]
    by_id = {probe.resource_id: probe for probe in probes}
    sources = [
        ResearchSource(
            source_id=definition.source_id,
            title=definition.title,
            year=definition.year,
            locator=definition.locator,
            source_url=definition.url,
            maturity=definition.maturity,
            source_fingerprint=by_id[definition.source_id].sample_sha256,
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
    return sources, nearest_work, probes


def _probe_resources(
    *,
    track_id: str,
    repository_url: str,
    dataset_url: str,
    license_url: str,
    checked_at: datetime,
    session: requests.Session,
) -> list:
    probes = [
        probe_web_resource(
            resource_id=f"{track_id}.repository",
            kind=ResourceKind.REPOSITORY,
            url=repository_url,
            checked_at=checked_at,
            session=session,
        ),
        probe_web_resource(
            resource_id=f"{track_id}.dataset",
            kind=ResourceKind.DATASET,
            url=dataset_url,
            checked_at=checked_at,
            session=session,
        ),
        probe_web_resource(
            resource_id=f"{track_id}.license",
            kind=ResourceKind.LICENSE,
            url=license_url,
            checked_at=checked_at,
            session=session,
        ),
    ]
    assert all(probe.reachable for probe in probes), [
        (probe.resource_id, probe.error) for probe in probes if not probe.reachable
    ]
    return probes


def _build_entry(
    *,
    track_id: str,
    sources: list[ResearchSource],
    nearest_work: list[NearestWorkDelta],
    source_probes: list,
    resource_probes: list,
    baseline_smoke: object,
    power: PowerSensitivityAudit,
    feasibility: TrackFeasibilityAudit,
    question: str,
    mechanism_model: str,
    nearest_work_tension: str,
    main_claim: str,
    falsifier: str,
    failure_update: str,
    minimal_decisive_test: str,
    metric_id: str,
    metric_name: str,
    metric_unit: str,
    metric_direction: MetricDirection,
    metric_threshold: float,
    evaluator_description: str,
    null_id: str,
    ablation_ids: list[str],
    development_unit_ids: list[str],
    confirmatory_unit_ids: list[str],
    confirmatory_access_policy: str,
    budget: ResearchBudget,
    publication_endpoint: PublicationEndpoint,
    endpoint_rationale: str,
) -> OpportunityTournamentEntry:
    # Kept local to this opt-in smoke so the production contract stays
    # provider- and domain-neutral.
    from autoresearch.research import BaselineExecutionSmoke

    assert isinstance(baseline_smoke, BaselineExecutionSmoke)
    certificate = ResearchQuestionCertificate.create(
        certificate_id=f"{track_id}.certificate",
        literature_cutoff=date(2026, 7, 29),
        question=question,
        primitives=[
            "A scientific unit is one independent task or physical regime.",
            "Seed repeats estimate within-unit variance and are not independent units.",
            "Every arm uses the same objective evaluator and hard budget.",
        ],
        assumptions=[
            "Development and one-use confirmatory units remain disjoint.",
            "No result has been observed while this endpoint is frozen.",
        ],
        mechanism_model=mechanism_model,
        nearest_work_tension=nearest_work_tension,
        main_claim=main_claim,
        falsifier=falsifier,
        failure_update=failure_update,
        minimal_decisive_test=minimal_decisive_test,
        primary_metric=PrimaryMetricSpec(
            metric_id=metric_id,
            name=metric_name,
            direction=metric_direction,
            unit=metric_unit,
            meaningful_effect_threshold=metric_threshold,
            evaluator_description=evaluator_description,
        ),
        strong_baseline_ids=[baseline_smoke.baseline_id],
        null_or_control_ids=[null_id],
        required_ablation_ids=ablation_ids,
        source_ids=[source.source_id for source in sources],
        power_plan=ProspectivePowerPlan(
            analysis_unit=power.analysis_unit,
            confirmatory_independent_unit_count=power.independent_unit_count,
            within_unit_repeat_count=3,
            target_power=power.target_power,
            alpha=power.alpha,
            minimum_detectable_effect=power.minimum_detectable_effect,
            uncertainty_method=(
                "paired independent-unit interval plus complete unit-level effects"
            ),
            bootstrap_resamples=20_000,
            heterogeneity_plan=(
                "Report every independent unit, domain strata, and a "
                "failure-aware aggregate without treating seeds as units."
            ),
            analysis_artifact_hash=power.audit_hash,
        ),
        data_split=ResearchDataSplit(
            development_unit_ids=development_unit_ids,
            confirmatory_unit_ids=confirmatory_unit_ids,
            confirmatory_access_policy=confirmatory_access_policy,
        ),
        budget=budget,
        publication_endpoint=publication_endpoint,
        endpoint_rationale=endpoint_rationale,
    )
    baseline_plan = BaselineReproductionPlan.create(
        baseline_id=baseline_smoke.baseline_id,
        source_ids=[source.source_id for source in sources[:2]],
        expected_metric_id=metric_id,
        reproduction_tolerance=0.01,
        exact_command_hash=baseline_smoke.command_hash,
        environment_hash=baseline_smoke.environment_hash,
    )
    opportunity = ResearchOpportunity.create(
        opportunity_id=track_id,
        certificate=certificate,
        sources=sources,
        nearest_work=nearest_work,
        objective_evaluator_hash=canonical_sha256(
            {
                "metric_id": metric_id,
                "description": evaluator_description,
                "threshold": metric_threshold,
                "version": 1,
            }
        ),
        baseline_plan=baseline_plan,
        baseline_smoke_passed=baseline_smoke.passed,
        baseline_reproduction=None,
        data_available=feasibility.data_access_verified,
        license_clear=feasibility.license_clear,
        compute_feasible=feasibility.compute_feasible,
        source_snapshot_complete=True,
    )
    return OpportunityTournamentEntry.create(
        track_id=track_id,
        opportunity=opportunity,
        source_probes=source_probes,
        resource_probes=resource_probes,
        baseline_smoke=baseline_smoke,
        power_audit=power,
        feasibility_audit=feasibility,
    )


def test_task2633_live_opportunity_tournament() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    output_root = Path(
        os.getenv(
            OUTPUT_ENV,
            str(
                repository_root
                / "runs"
                / "manual-live"
                / "task263-opportunity-tournament-v1"
            ),
        )
    ).resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise AssertionError("opportunity tournament output must be absent or empty")

    checked_at = datetime.now(timezone.utc)
    session = _session()
    lock_hash = _file_sha256(repository_root / "poetry.lock")
    environment_hash = environment_fingerprint(
        lockfile_hash=lock_hash,
        python_version=sys.version.split()[0],
        platform=platform.platform(),
    )
    available_compute = _available_compute()

    search_definitions = [
        SourceDefinition(
            source_id="search-policy.ai-scientist",
            title="Towards end-to-end automation of AI research",
            year=2026,
            locator="Nature s41586-026-10265-5",
            url="https://www.nature.com/articles/s41586-026-10265-5",
            maturity=SourceMaturity.PEER_REVIEWED,
            shared_scope="End-to-end idea, code, experiment, and paper automation.",
            claimed_delta=(
                "Causally isolates portfolio, memory, certificate, and "
                "multi-fidelity policies under equal budget."
            ),
            overlap_risk=(
                "Both systems perform iterative code-and-experiment research."
            ),
            decisive_comparison=(
                "Run frozen policy arms on identical independent tasks and cost."
            ),
        ),
        SourceDefinition(
            source_id="search-policy.robin",
            title="A multi-agent system for automating scientific discovery",
            year=2026,
            locator="Nature s41586-026-10652-y",
            url="https://www.nature.com/articles/s41586-026-10652-y",
            maturity=SourceMaturity.PEER_REVIEWED,
            shared_scope="Multi-agent literature, hypothesis, and analysis loops.",
            claimed_delta=(
                "Measures search-policy causality rather than reporting only "
                "integrated system discoveries."
            ),
            overlap_risk="Agent specialization and iterative hypothesis updates overlap.",
            decisive_comparison=(
                "Use objective task outcomes, full trajectories, and fixed ablations."
            ),
        ),
        SourceDefinition(
            source_id="search-policy.scienceagentbench",
            title=(
                "ScienceAgentBench: Toward Rigorous Assessment of Language "
                "Agents for Data-Driven Scientific Discovery"
            ),
            year=2025,
            locator="arXiv:2410.05080; ICLR 2025",
            url="https://arxiv.org/abs/2410.05080",
            maturity=SourceMaturity.PEER_REVIEWED,
            shared_scope="Independent executable tasks for scientific agents.",
            claimed_delta=(
                "Treats task IDs as scientific units and compares complete "
                "research policies rather than model prompting variants."
            ),
            overlap_risk="Evaluator and task-family composition can dominate results.",
            decisive_comparison=(
                "Freeze non-visual deterministic tasks and report every task outcome."
            ),
        ),
        SourceDefinition(
            source_id="search-policy.researchgym",
            title=(
                "ResearchGym: Evaluating Language Model Agents on Real-World "
                "AI Research"
            ),
            year=2026,
            locator="arXiv:2602.15112",
            url="https://arxiv.org/abs/2602.15112",
            maturity=SourceMaturity.PREPRINT,
            shared_scope="Execution-grounded end-to-end research-agent evaluation.",
            claimed_delta=(
                "Tests whether a portfolio policy repairs documented impatience, "
                "premature commitment, and weak resource allocation."
            ),
            overlap_risk="Both studies may use repository-grounded research tasks.",
            decisive_comparison=(
                "Use budget-matched arms and independent task-level uncertainty."
            ),
        ),
    ]
    search_sources, search_nearest, search_source_probes = _probe_sources(
        definitions=search_definitions,
        checked_at=checked_at,
        session=session,
    )
    search_resources = _probe_resources(
        track_id="track.search-policy-causality",
        repository_url=(
            "https://api.github.com/repos/OSU-NLP-Group/ScienceAgentBench"
        ),
        dataset_url=(
            "https://huggingface.co/api/datasets/osunlp/ScienceAgentBench"
        ),
        license_url=(
            "https://raw.githubusercontent.com/OSU-NLP-Group/"
            "ScienceAgentBench/main/LICENSE"
        ),
        checked_at=checked_at,
        session=session,
    )
    search_command = [
        "poetry",
        "run",
        "python",
        "-c",
        (
            "from pathlib import Path; "
            "from autoresearch.campaign.systems import systems_benchmark_status; "
            "s=systems_benchmark_status("
            "Path('runs/manual-live/task260-autonomous-systems-v1')); "
            "assert s.completed and s.cell_count == 210 and "
            "s.contribution_gate_passed is True and "
            "s.external_submission_authorized is False; "
            "print(s.model_dump_json())"
        ),
    ]
    search_baseline_root = (
        repository_root / "runs" / "manual-live" / "task260-autonomous-systems-v1"
    )
    search_smoke = run_baseline_command_smoke(
        track_id="track.search-policy-causality",
        baseline_id="autoresearch-linear-self-loop-v1",
        command=search_command,
        cwd=repository_root,
        environment_hash=environment_hash,
        checked_at=checked_at,
        artifact_hashes=[
            _file_sha256(search_baseline_root / "benchmark-result.json"),
            _file_sha256(search_baseline_root / "contribution-gate.json"),
            _file_sha256(search_baseline_root / "matrix-manifest.json"),
            _file_sha256(repository_root / "LICENSE"),
        ],
        timeout_seconds=180,
    )
    assert search_smoke.passed is True
    search_power = PowerSensitivityAudit.create(
        track_id="track.search-policy-causality",
        analysis_unit="independent verified ScienceAgentBench task",
        independent_unit_count=12,
        alpha=0.05,
        target_power=0.80,
        minimum_detectable_effect=0.25,
        assumed_unit_sd=0.30,
        sensitivity_effects=[0.15, 0.20, 0.25, 0.30],
    )
    search_feasibility = TrackFeasibilityAudit.create(
        track_id="track.search-policy-causality",
        repository_probe_ids=["track.search-policy-causality.repository"],
        dataset_probe_ids=["track.search-policy-causality.dataset"],
        license_probe_ids=["track.search-policy-causality.license"],
        code_license_id="AutoResearch Apache-2.0; ScienceAgentBench MIT",
        data_license_id=(
            "ScienceAgentBench verified metadata CC-BY-4.0; excluded special-license IDs"
        ),
        code_license_verified=True,
        data_license_verified=True,
        data_access_verified=True,
        required_compute=(
            "CPU, sandboxed task runners, and the configured provider-neutral "
            "local model endpoint; no cloud GPU required for baseline audit"
        ),
        available_compute=available_compute,
        compute_feasible=True,
        estimated_baseline_cost_usd=20.0,
        estimated_baseline_walltime_minutes=180,
    )
    search_entry = _build_entry(
        track_id="track.search-policy-causality",
        sources=search_sources,
        nearest_work=search_nearest,
        source_probes=search_source_probes,
        resource_probes=search_resources,
        baseline_smoke=search_smoke,
        power=search_power,
        feasibility=search_feasibility,
        question=(
            "At equal model-token, trial, and wall-time budgets, does a "
            "certificate-gated diverse multi-fidelity portfolio with optional "
            "cross-branch memory improve independently confirmed scientific task "
            "success over a linear self-loop?"
        ),
        mechanism_model=(
            "Diversity reduces premature commitment, multi-fidelity allocation "
            "limits waste, and evidence-only cross-branch memory transfers useful "
            "failures without turning reviewer preference into an objective."
        ),
        nearest_work_tension=(
            "Recent autonomous-science systems demonstrate integrated loops, while "
            "independent benchmarks expose low reliability; none of the frozen "
            "nearest works supplies this budget-matched component-level causal study."
        ),
        main_claim=(
            "The portfolio-plus-memory policy increases independently confirmed "
            "task success by at least 0.25 over a budget-matched linear self-loop."
        ),
        falsifier=(
            "The untouched paired task interval fails to clear 0.25, any arm exceeds "
            "budget, or any execution/evidence/replay hard gate fails."
        ),
        failure_update=(
            "Reject the claimed policy advantage on this task distribution, retain "
            "the complete branch/failure matrix, and do not retune on the panel."
        ),
        minimal_decisive_test=(
            "Reproduce the strongest linear baseline, then compare one-shot, linear "
            "self-loop, portfolio, and portfolio-plus-memory on disjoint verified tasks."
        ),
        metric_id="confirmed-task-success-difference",
        metric_name="Paired independently confirmed task-success difference",
        metric_unit="proportion",
        metric_direction=MetricDirection.MAXIMIZE,
        metric_threshold=0.25,
        evaluator_description=(
            "Deterministic conjunction of task execution, objective output checks, "
            "evidence coverage, exact replay, and no-fallback budget compliance."
        ),
        null_id="budget-matched-rule-only-search",
        ablation_ids=[
            "without-certificate",
            "without-cross-branch-memory",
            "without-diversity",
            "without-multi-fidelity",
        ],
        development_unit_ids=[
            "scienceagentbench-verified-dev-001",
            "scienceagentbench-verified-dev-002",
            "scienceagentbench-verified-dev-004",
            "scienceagentbench-verified-dev-005",
        ],
        confirmatory_unit_ids=[
            f"scienceagentbench-verified-confirm-{index:03d}"
            for index in range(61, 73)
        ],
        confirmatory_access_policy=(
            "Only verified metadata and IDs are frozen now. The independent runner "
            "receives the full data/evaluators once in Task 263.6; development "
            "agents cannot read that directory or its outcomes."
        ),
        budget=ResearchBudget(
            max_cost_usd=500.0,
            max_walltime_minutes=7_200,
            max_model_tokens=4_000_000,
            max_trials=800,
        ),
        publication_endpoint=PublicationEndpoint.SYSTEM_CONTRIBUTION,
        endpoint_rationale=(
            "The single claim is the causal contribution of a research search policy."
        ),
    )

    neural_definitions = [
        SourceDefinition(
            source_id="neural-operator.ai-sc",
            title=(
                "An Agentic AI Scientific Community for Automated Neural "
                "Operator Discovery"
            ),
            year=2026,
            locator="arXiv:2607.12122",
            url="https://arxiv.org/abs/2607.12122",
            maturity=SourceMaturity.PREPRINT,
            shared_scope="Agentic population search over neural-operator architectures.",
            claimed_delta=(
                "Independent reproduction plus matched ablations on new PDE regimes "
                "and an evaluator isolated from LLM review."
            ),
            overlap_risk="The track directly targets the released system's main claims.",
            decisive_comparison=(
                "Reproduce FNO/DeepONet and LLM-versus-rule coordination at equal budget."
            ),
        ),
        SourceDefinition(
            source_id="neural-operator.fno",
            title="Fourier Neural Operator for Parametric Partial Differential Equations",
            year=2021,
            locator="ICLR 2021 c8P9NQVtmnO",
            url="https://openreview.net/forum?id=c8P9NQVtmnO",
            maturity=SourceMaturity.PEER_REVIEWED,
            shared_scope="Strong operator-learning baseline for PDE solution maps.",
            claimed_delta="Tests automated architecture discovery rather than a fixed FNO.",
            overlap_risk="FNO can remain the strongest problem-specific answer.",
            decisive_comparison=(
                "Use faithful FNO training budgets and regime-level paired errors."
            ),
        ),
        SourceDefinition(
            source_id="neural-operator.deeponet",
            title=(
                "Learning nonlinear operators via DeepONet based on the "
                "universal approximation theorem of operators"
            ),
            year=2021,
            locator="Nature Machine Intelligence s42256-021-00302-5",
            url="https://www.nature.com/articles/s42256-021-00302-5",
            maturity=SourceMaturity.PEER_REVIEWED,
            shared_scope="Strong branch-trunk neural-operator baseline.",
            claimed_delta=(
                "Tests whether agentic hybridization adds value beyond a faithfully "
                "trained problem-dependent DeepONet."
            ),
            overlap_risk="Undertraining DeepONet would create a false discovery.",
            decisive_comparison=(
                "Reproduce the baseline tolerance before any architecture search."
            ),
        ),
        SourceDefinition(
            source_id="neural-operator.pdebench",
            title=(
                "PDEBench: An Extensive Benchmark for Scientific Machine Learning"
            ),
            year=2022,
            locator="NeurIPS 2022 Datasets and Benchmarks",
            url=(
                "https://proceedings.neurips.cc/paper_files/paper/2022/hash/"
                "0a9747136d411fb83f0cf81820d44afb-"
                "Abstract-Datasets_and_Benchmarks.html"
            ),
            maturity=SourceMaturity.PEER_REVIEWED,
            shared_scope="Multi-regime PDE benchmark and normalized errors.",
            claimed_delta="Uses regimes not optimized during the released agentic campaign.",
            overlap_risk="Benchmark shifts may confound architecture and solver effects.",
            decisive_comparison=(
                "Freeze PDE regimes, discretization, data generation, and error metrics."
            ),
        ),
    ]
    neural_sources, neural_nearest, neural_source_probes = _probe_sources(
        definitions=neural_definitions,
        checked_at=checked_at,
        session=session,
    )
    neural_resources = _probe_resources(
        track_id="track.neural-operator-replication",
        repository_url=(
            "https://raw.githubusercontent.com/luislootx/AI-SC/main/"
            "nod/code/validate_baselines_v3.py"
        ),
        dataset_url=(
            "https://raw.githubusercontent.com/luislootx/AI-SC/main/"
            "nod/results/exp4v3/AGGREGATE.json"
        ),
        license_url=(
            "https://raw.githubusercontent.com/luislootx/AI-SC/main/LICENSE"
        ),
        checked_at=checked_at,
        session=session,
    )
    neural_by_id = {probe.resource_id: probe for probe in neural_resources}
    neural_command = [
        "poetry",
        "run",
        "python",
        "-c",
        (
            "import torch; assert torch.cuda.is_available(); "
            "p=torch.cuda.get_device_properties(0); "
            "assert p.total_memory >= 16 * 1024**3; "
            "print(torch.__version__, p.name, p.total_memory)"
        ),
    ]
    neural_smoke = run_baseline_command_smoke(
        track_id="track.neural-operator-replication",
        baseline_id="ai-sc-faithful-fno-deeponet-suite",
        command=neural_command,
        cwd=repository_root,
        environment_hash=environment_hash,
        checked_at=checked_at,
        artifact_hashes=[
            neural_by_id["track.neural-operator-replication.repository"].sample_sha256,
            neural_by_id["track.neural-operator-replication.dataset"].sample_sha256,
            neural_by_id["track.neural-operator-replication.license"].sample_sha256,
        ],
        timeout_seconds=60,
    )
    neural_power = PowerSensitivityAudit.create(
        track_id="track.neural-operator-replication",
        analysis_unit="independent PDE or operator regime",
        independent_unit_count=12,
        alpha=0.05,
        target_power=0.80,
        minimum_detectable_effect=0.01,
        assumed_unit_sd=0.012,
        sensitivity_effects=[0.006, 0.008, 0.01, 0.012],
    )
    neural_feasibility = TrackFeasibilityAudit.create(
        track_id="track.neural-operator-replication",
        repository_probe_ids=["track.neural-operator-replication.repository"],
        dataset_probe_ids=["track.neural-operator-replication.dataset"],
        license_probe_ids=["track.neural-operator-replication.license"],
        code_license_id="AI-SC MIT",
        data_license_id="AI-SC MIT release bundle",
        code_license_verified=True,
        data_license_verified=True,
        data_access_verified=True,
        required_compute=(
            "Released full campaign: one RTX 4080-class GPU for about two days; "
            "clean FNO/DeepONet reproduction before search"
        ),
        available_compute=available_compute,
        compute_feasible=False,
        estimated_baseline_cost_usd=500.0,
        estimated_baseline_walltime_minutes=2_880,
    )
    neural_entry = _build_entry(
        track_id="track.neural-operator-replication",
        sources=neural_sources,
        nearest_work=neural_nearest,
        source_probes=neural_source_probes,
        resource_probes=neural_resources,
        baseline_smoke=neural_smoke,
        power=neural_power,
        feasibility=neural_feasibility,
        question=(
            "Does LLM-mediated population coordination discover neural operators "
            "with lower normalized relative L2 error than a rule coordinator and "
            "faithful FNO/DeepONet baselines at identical training budget?"
        ),
        mechanism_model=(
            "Planner hybridization and fitness-anchored peer review may preserve "
            "useful architectural diversity that a rule coordinator collapses."
        ),
        nearest_work_tension=(
            "The released 2026 preprint reports problem-dependent discoveries, but "
            "the central coordination effect lacks independent clean-room replication."
        ),
        main_claim=(
            "LLM coordination reduces mean regime-level normalized relative L2 "
            "error by at least 0.01 versus the strongest matched control."
        ),
        falsifier=(
            "Faithful baselines cannot be reproduced, the independent regime-level "
            "interval misses 0.01, or compute/budget parity fails."
        ),
        failure_update=(
            "Classify the result as a replication or baseline diagnosis and do not "
            "launch architecture novelty search on an unreliable baseline."
        ),
        minimal_decisive_test=(
            "Reproduce FNO and DeepONet, then run LLM and rule coordinators at equal "
            "training budgets on disjoint PDE regimes."
        ),
        metric_id="regime-normalized-relative-l2-difference",
        metric_name="Paired normalized relative L2 error reduction",
        metric_unit="normalized relative L2",
        metric_direction=MetricDirection.MAXIMIZE,
        metric_threshold=0.01,
        evaluator_description=(
            "Deterministic prediction-versus-solution relative L2 calculation with "
            "fixed discretization, parameter budget, epochs, and data generator."
        ),
        null_id="matched-rule-coordinator",
        ablation_ids=[
            "planner-only",
            "reviewer-only",
            "without-diversity-pressure",
        ],
        development_unit_ids=[
            "pdebench-dev-burgers-1d",
            "pdebench-dev-darcy-2d",
            "pdebench-dev-navier-stokes-2d",
        ],
        confirmatory_unit_ids=[
            f"operator-regime-confirm-{index:02d}" for index in range(1, 13)
        ],
        confirmatory_access_policy=(
            "The independent runner alone materializes the twelve frozen regimes "
            "after baseline reproduction; development sees only regime schemas."
        ),
        budget=ResearchBudget(
            max_cost_usd=2_000.0,
            max_walltime_minutes=20_000,
            max_model_tokens=3_000_000,
            max_trials=500,
        ),
        publication_endpoint=PublicationEndpoint.POSITIVE_METHOD,
        endpoint_rationale=(
            "The frozen claim is a positive method effect of LLM coordination."
        ),
    )

    falsification_definitions = [
        SourceDefinition(
            source_id="sequential-falsification.popper",
            title=(
                "Automated Hypothesis Validation with Agentic Sequential "
                "Falsifications"
            ),
            year=2025,
            locator="PMLR 267:25372-25437",
            url="https://proceedings.mlr.press/v267/huang25n.html",
            maturity=SourceMaturity.PEER_REVIEWED,
            shared_scope="Agent-designed falsification with sequential error control.",
            claimed_delta=(
                "Tests a low-cost, provider-neutral evidence harness with frozen "
                "objective DiscoveryBench units."
            ),
            overlap_risk="The proposed lane closely follows POPPER's central method.",
            decisive_comparison=(
                "Require licensed code or an independently specified reimplementation "
                "before any baseline execution."
            ),
        ),
        SourceDefinition(
            source_id="sequential-falsification.discoverybench",
            title="DiscoveryBench: Towards Data-Driven Discovery with Large Language Models",
            year=2025,
            locator="ICLR 2025 vyflgpwfJW",
            url="https://arxiv.org/abs/2407.01725",
            maturity=SourceMaturity.PEER_REVIEWED,
            shared_scope="Objective data-driven hypothesis discovery tasks.",
            claimed_delta=(
                "Evaluates sequential falsification rather than a one-pass discovery agent."
            ),
            overlap_risk="Benchmark rubric design may dominate hypothesis validity.",
            decisive_comparison=(
                "Freeze task-level truth, evaluator, and error-control outcomes."
            ),
        ),
        SourceDefinition(
            source_id="sequential-falsification.safe-testing",
            title="Safe Testing",
            year=2024,
            locator="JRSS-B 86(5):1091-1128; arXiv:1906.07801",
            url="https://arxiv.org/abs/1906.07801",
            maturity=SourceMaturity.PEER_REVIEWED,
            shared_scope="E-value testing under optional continuation.",
            claimed_delta=(
                "Binds anytime-valid error control to agent-generated executable tests."
            ),
            overlap_risk="Invalid conditional tests can destroy nominal error control.",
            decisive_comparison=(
                "Recompute e-process validity and Type-I error in deterministic code."
            ),
        ),
    ]
    falsification_sources, falsification_nearest, falsification_source_probes = (
        _probe_sources(
            definitions=falsification_definitions,
            checked_at=checked_at,
            session=session,
        )
    )
    falsification_resources = _probe_resources(
        track_id="track.sequential-falsification",
        repository_url="https://api.github.com/repos/snap-stanford/POPPER",
        dataset_url=(
            "https://huggingface.co/api/datasets/allenai/discoverybench"
        ),
        license_url="https://api.github.com/repos/snap-stanford/POPPER",
        checked_at=checked_at,
        session=session,
    )
    falsification_by_id = {
        probe.resource_id: probe for probe in falsification_resources
    }
    falsification_command = [
        "python",
        "-m",
        "popper",
        "--help",
    ]
    falsification_smoke = blocked_baseline_smoke(
        track_id="track.sequential-falsification",
        baseline_id="popper-discoverybench-evalue-baseline",
        command=falsification_command,
        environment_hash=environment_hash,
        checked_at=checked_at,
        artifact_hashes=[
            falsification_by_id[
                "track.sequential-falsification.repository"
            ].sample_sha256,
            falsification_by_id[
                "track.sequential-falsification.dataset"
            ].sample_sha256,
            canonical_sha256(
                {
                    "github_repository": "snap-stanford/POPPER",
                    "license_spdx_id": None,
                    "checked_at": checked_at.isoformat(),
                }
            ),
        ],
        reason=(
            "GitHub repository metadata and tree expose no software license; "
            "external code execution is denied until rights are clarified or a "
            "clean-room specification is approved."
        ),
    )
    falsification_power = PowerSensitivityAudit.create(
        track_id="track.sequential-falsification",
        analysis_unit="independent DiscoveryBench dataset-hypothesis task",
        independent_unit_count=12,
        alpha=0.05,
        target_power=0.80,
        minimum_detectable_effect=0.20,
        assumed_unit_sd=0.24,
        sensitivity_effects=[0.12, 0.16, 0.20, 0.24],
    )
    falsification_feasibility = TrackFeasibilityAudit.create(
        track_id="track.sequential-falsification",
        repository_probe_ids=["track.sequential-falsification.repository"],
        dataset_probe_ids=["track.sequential-falsification.dataset"],
        license_probe_ids=["track.sequential-falsification.license"],
        code_license_id="POPPER NOASSERTION",
        data_license_id="DiscoveryBench ODC-By",
        code_license_verified=False,
        data_license_verified=True,
        data_access_verified=True,
        required_compute=(
            "CPU tabular analysis and a bounded provider-neutral model endpoint"
        ),
        available_compute=available_compute,
        compute_feasible=True,
        estimated_baseline_cost_usd=50.0,
        estimated_baseline_walltime_minutes=360,
    )
    falsification_entry = _build_entry(
        track_id="track.sequential-falsification",
        sources=falsification_sources,
        nearest_work=falsification_nearest,
        source_probes=falsification_source_probes,
        resource_probes=falsification_resources,
        baseline_smoke=falsification_smoke,
        power=falsification_power,
        feasibility=falsification_feasibility,
        question=(
            "Does anytime-valid sequential agentic falsification improve correctly "
            "validated hypothesis decisions over a fixed-budget one-pass analysis "
            "on independent data-discovery tasks?"
        ),
        mechanism_model=(
            "Adaptive falsification can spend tests on vulnerable implications while "
            "an e-process preserves Type-I error under optional continuation."
        ),
        nearest_work_tension=(
            "POPPER reports strong results but its public repository has no detected "
            "reuse license; a publishable lane also needs independent objective tasks."
        ),
        main_claim=(
            "Sequential falsification improves correct validated-hypothesis decisions "
            "by at least 0.20 while retaining the frozen Type-I error bound."
        ),
        falsifier=(
            "The license gate remains unresolved, empirical Type-I error exceeds "
            "alpha, or the independent paired effect misses 0.20."
        ),
        failure_update=(
            "Do not execute unlicensed code; retain the lane as a methods blueprint "
            "or draft a separately reviewed clean-room implementation."
        ),
        minimal_decisive_test=(
            "Reproduce a licensed or clean-room sequential baseline, then compare it "
            "with one-pass analysis on disjoint objective DiscoveryBench tasks."
        ),
        metric_id="correct-validation-decision-difference",
        metric_name="Paired correct validated-hypothesis decision difference",
        metric_unit="proportion",
        metric_direction=MetricDirection.MAXIMIZE,
        metric_threshold=0.20,
        evaluator_description=(
            "Deterministic task truth comparison plus simulated-null Type-I error "
            "and e-process validity checks; no LLM reviewer is an endpoint."
        ),
        null_id="fixed-budget-one-pass-analysis",
        ablation_ids=[
            "without-evalue-aggregation",
            "without-relevance-filter",
            "without-sequential-allocation",
        ],
        development_unit_ids=[
            f"discoverybench-dev-{index:03d}" for index in range(1, 5)
        ],
        confirmatory_unit_ids=[
            f"discoverybench-confirm-{index:03d}" for index in range(61, 73)
        ],
        confirmatory_access_policy=(
            "Only the independent runner may materialize confirmatory datasets and "
            "truth labels once; development receives schemas only."
        ),
        budget=ResearchBudget(
            max_cost_usd=300.0,
            max_walltime_minutes=3_000,
            max_model_tokens=1_500_000,
            max_trials=400,
        ),
        publication_endpoint=PublicationEndpoint.POSITIVE_METHOD,
        endpoint_rationale=(
            "The frozen claim is a positive method effect with error control."
        ),
    )

    report = OpportunityTournamentReport.create(
        tournament_id="task263-opportunity-tournament-v1",
        created_at=checked_at,
        entries=[search_entry, neural_entry, falsification_entry],
    )
    assert report.eligible_track_ids == ["track.search-policy-causality"]
    assert report.selected_track_id == "track.search-policy-causality"
    assert report.novelty_search_started is False
    assert neural_entry.assessment.admitted is False
    assert "opportunity.compute_feasible" in neural_entry.assessment.blockers
    assert "opportunity.baseline_smoke_passed" in neural_entry.assessment.blockers
    assert falsification_entry.assessment.admitted is False
    assert "opportunity.license_clear" in falsification_entry.assessment.blockers
    assert (
        "opportunity.baseline_smoke_passed"
        in falsification_entry.assessment.blockers
    )

    manifest = write_opportunity_tournament(output_root, report)
    assert manifest.report_hash == report.report_hash
    assert set(manifest.files) == {
        "opportunity-tournament.json",
        "opportunity-tournament.md",
    }
