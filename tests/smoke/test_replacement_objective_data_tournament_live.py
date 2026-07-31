"""Opt-in exact-source admission tournament for Task 263.6.6."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from autoresearch.research import (
    LiveResourceProbe,
    NearestWorkDelta,
    ResearchSource,
    ResourceKind,
    SourceMaturity,
    probe_web_resource,
)
from autoresearch.research.replacement_objective_data_tournament import (
    REPLACEMENT_REPLAY_INPUT_FILENAME,
    ReplacementCandidateId,
    ReplacementTournamentStatus,
    build_official_candidate_audits,
    build_replacement_replay_payload,
    build_replacement_tournament_report,
    fetch_replacement_candidate_materials,
    load_replacement_tournament,
    project_replacement_tournament,
    run_replacement_tournament_replay,
    write_replacement_tournament,
)

LIVE_ENV = "AUTORESEARCH_REPLACEMENT_OBJECTIVE_DATA_LIVE"
OUTPUT_ENV = "AUTORESEARCH_REPLACEMENT_OBJECTIVE_DATA_OUTPUT"
INTERPRETER_A_ENV = "AUTORESEARCH_REPLACEMENT_INTERPRETER_A"
INTERPRETER_B_ENV = "AUTORESEARCH_REPLACEMENT_INTERPRETER_B"

pytestmark = pytest.mark.skipif(
    os.getenv(LIVE_ENV) != "1",
    reason=(
        f"set {LIVE_ENV}=1 to fetch exact candidate artifacts, probe primary "
        "papers, and replay the admission decision in two clean interpreters"
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


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=5,
        connect=5,
        read=4,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def _source_material(
    *,
    definitions: list[SourceDefinition],
    checked_at: datetime,
    session: requests.Session,
) -> tuple[
    list[ResearchSource],
    list[NearestWorkDelta],
    list[LiveResourceProbe],
]:
    probes = [
        probe_web_resource(
            resource_id=definition.source_id,
            kind=ResourceKind.LITERATURE,
            url=definition.url,
            checked_at=checked_at,
            session=session,
            timeout_seconds=60,
            max_sample_bytes=65_536,
        )
        for definition in definitions
    ]
    failures = [
        (probe.resource_id, probe.status_code, probe.error)
        for probe in probes
        if not probe.reachable
    ]
    if failures:
        raise AssertionError(f"primary-source probe failed: {failures}")
    probe_by_id = {probe.resource_id: probe for probe in probes}
    sources = [
        ResearchSource(
            source_id=definition.source_id,
            title=definition.title,
            year=definition.year,
            locator=definition.locator,
            source_url=definition.url,
            maturity=definition.maturity,
            source_fingerprint=probe_by_id[
                definition.source_id
            ].sample_sha256,
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


def _source_definitions() -> list[SourceDefinition]:
    return [
        SourceDefinition(
            source_id="autosdt-paper",
            title="AutoSDT: Scaling Data-Driven Discovery Tasks Toward Open Co-Scientists",
            year=2025,
            locator="arXiv:2506.08140",
            url="https://arxiv.org/abs/2506.08140",
            maturity=SourceMaturity.PREPRINT,
            shared_scope="scientific coding task acquisition at repository scale",
            claimed_delta="audit repository groups and source rights before reuse",
            overlap_risk="headline task counts can be mistaken for independent units",
            decisive_comparison="released tasks versus licensed repository groups",
        ),
        SourceDefinition(
            source_id="scienceagentbench-paper",
            title="ScienceAgentBench: Toward Rigorous Assessment of Language Agents for Data-Driven Scientific Discovery",
            year=2025,
            locator="ICLR 2025 OpenReview 6z4YKr0GK6",
            url="https://openreview.net/forum?id=6z4YKr0GK6",
            maturity=SourceMaturity.PEER_REVIEWED,
            shared_scope="publication-derived scientific program synthesis",
            claimed_delta="separate deterministic and LLM-judged primary endpoints",
            overlap_risk="attempts and visualization judges can obscure the unit",
            decisive_comparison="publication groups and exact scorer coverage",
        ),
        SourceDefinition(
            source_id="core-bench-paper",
            title="CORE-Bench: Fostering the Credibility of Published Research Through a Computational Reproducibility Agent Benchmark",
            year=2025,
            locator="TMLR OpenReview BsMMc4MEGS",
            url="https://openreview.net/forum?id=BsMMc4MEGS",
            maturity=SourceMaturity.PEER_REVIEWED,
            shared_scope="agentic computational reproducibility of papers",
            claimed_delta="collapse three difficulties to one paper-level unit",
            overlap_risk="difficulty variants can create pseudoreplication",
            decisive_comparison="paper groups, capsule rights, and local workload",
        ),
        SourceDefinition(
            source_id="qrdata-paper",
            title="Are LLMs Capable of Data-based Statistical and Causal Reasoning?",
            year=2024,
            locator="Findings of ACL 2024, paper 548",
            url="https://aclanthology.org/2024.findings-acl.548/",
            maturity=SourceMaturity.PEER_REVIEWED,
            shared_scope="statistical and causal reasoning over real data sheets",
            claimed_delta="cluster questions by shared data-file set and source rights",
            overlap_risk="questions sharing a sheet are not independent studies",
            decisive_comparison="question count versus licensed sealed sheet groups",
        ),
        SourceDefinition(
            source_id="popper-paper",
            title="Automated Hypothesis Validation with Agentic Sequential Falsifications",
            year=2025,
            locator="PMLR 267:25372-25437",
            url="https://proceedings.mlr.press/v267/huang25n.html",
            maturity=SourceMaturity.PEER_REVIEWED,
            shared_scope="sequential falsification with statistical error control",
            claimed_delta="admit data before constructing the falsification critic",
            overlap_risk="strong method novelty is unusable without a valid panel",
            decisive_comparison="data admission first, equal-budget critic second",
        ),
        SourceDefinition(
            source_id="astabench-paper",
            title="AstaBench: Rigorous Benchmarking of AI Agents with a Scientific Research Suite",
            year=2026,
            locator="ICLR 2026; arXiv:2510.21652v2",
            url="https://arxiv.org/abs/2510.21652v2",
            maturity=SourceMaturity.PEER_REVIEWED,
            shared_scope="controlled tools, harnesses, and scientific-agent baselines",
            claimed_delta="add source-license and reserve-seal admission gates",
            overlap_risk="harness rigor alone does not make units publishable",
            decisive_comparison="controlled evaluation plus independent data lineage",
        ),
        SourceDefinition(
            source_id="ai-scientist-v2-paper",
            title="The AI Scientist-v2: Workshop-Level Automated Scientific Discovery via Agentic Tree Search",
            year=2025,
            locator="arXiv:2504.08066",
            url="https://arxiv.org/abs/2504.08066",
            maturity=SourceMaturity.PREPRINT,
            shared_scope="agentic experiment-manager tree search and paper production",
            claimed_delta="freeze objective evidence before search and writing",
            overlap_risk="paper acceptance is not a powered scientific endpoint",
            decisive_comparison="artifact generation versus result-blind validation",
        ),
        SourceDefinition(
            source_id="kosmos-paper",
            title="Kosmos: An AI Scientist for Autonomous Discovery",
            year=2025,
            locator="arXiv:2511.02824",
            url="https://arxiv.org/abs/2511.02824",
            maturity=SourceMaturity.PREPRINT,
            shared_scope="long-horizon literature, analysis, and hypothesis loops",
            claimed_delta="bind each loop to admissible source and endpoint contracts",
            overlap_risk="long traces can remain scientifically underidentified",
            decisive_comparison="traceable evidence depth versus causal validity",
        ),
        SourceDefinition(
            source_id="autoresearchbench-paper",
            title="AutoResearchBench: Benchmarking AI Agents on Complex Scientific Literature Discovery",
            year=2026,
            locator="arXiv:2604.25256",
            url="https://arxiv.org/abs/2604.25256",
            maturity=SourceMaturity.PREPRINT,
            shared_scope="objective evaluation of autonomous literature discovery",
            claimed_delta="require frozen retrieval and source-group reserve lineage",
            overlap_risk="mutable web services weaken exact replay and sealing",
            decisive_comparison="public tasks versus frozen independent topic groups",
        ),
        SourceDefinition(
            source_id="socratic-agent-paper",
            title="Socratic agents for autonomous scientific discovery in high-dimensional physical systems",
            year=2026,
            locator="arXiv:2606.26722",
            url="https://arxiv.org/abs/2606.26722",
            maturity=SourceMaturity.PREPRINT,
            shared_scope="causal, constraint, counterexample, and falsification dialogue",
            claimed_delta="evaluate the critic only after objective-panel admission",
            overlap_risk="mechanism appeal can outrun evaluable independent evidence",
            decisive_comparison="same-budget ablation on a sealed admitted panel",
        ),
        SourceDefinition(
            source_id="fair4rs-paper",
            title="Introducing the FAIR Principles for research software",
            year=2022,
            locator="Scientific Data 9, 622",
            url="https://www.nature.com/articles/s41597-022-01710-x",
            maturity=SourceMaturity.PEER_REVIEWED,
            shared_scope="findable, accessible, interoperable, reusable software",
            claimed_delta="make per-source executable and rights evidence machine-checkable",
            overlap_risk="repository availability can be mistaken for legal reuse",
            decisive_comparison="artifact reachability versus scope-specific rights",
        ),
    ]


def test_task26366_live_replacement_objective_data_tournament() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    output_root = Path(
        os.getenv(
            OUTPUT_ENV,
            str(
                repository_root
                / "runs"
                / "manual-live"
                / "task26366-replacement-objective-data-tournament-v1"
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
        raise AssertionError("two clean interpreter installations are required")
    runner_path = (
        repository_root
        / "src"
        / "autoresearch"
        / "research"
        / "assets"
        / "frozen_replacement_objective_data_probe_v1.py"
    )
    checked_at = datetime.now(timezone.utc)
    session = _session()

    materials = fetch_replacement_candidate_materials(
        session=session,
        timeout_seconds=300,
    )
    audits = build_official_candidate_audits(materials)
    replay_payload = build_replacement_replay_payload(audits)
    projection = project_replacement_tournament(replay_payload)
    certificate = run_replacement_tournament_replay(
        replay_payload=replay_payload,
        input_path=output_root / REPLACEMENT_REPLAY_INPUT_FILENAME,
        runner_path=runner_path,
        interpreters={
            "clean-venv-a": interpreter_a,
            "clean-venv-b": interpreter_b,
        },
        expected_projection=projection,
        observed_at=checked_at,
    )
    sources, nearest_work, source_probes = _source_material(
        definitions=_source_definitions(),
        checked_at=checked_at,
        session=session,
    )
    report = build_replacement_tournament_report(
        study_id="task26366-replacement-objective-data-tournament-v1",
        created_at=checked_at,
        literature_cutoff=checked_at.date(),
        research_questions=[
            (
                "Which candidate retains at least 30 development and 84 "
                "completely sealed reserve groups after exact license and "
                "source-lineage admission?"
            ),
            (
                "What is the independent scientific unit and deterministic "
                "primary endpoint for each candidate?"
            ),
            (
                "Can an official strong baseline be reproduced within a "
                "bounded local compute envelope before any candidate model call?"
            ),
        ],
        intended_reader="AutoResearch project owner and technical research lead",
        review_angle=(
            "Published benchmark task scale versus independently licensed, "
            "executable, and sealed scientific units"
        ),
        sources=sources,
        nearest_work=nearest_work,
        source_probes=source_probes,
        candidate_audits=audits,
        replay_certificate=certificate,
    )
    manifest = write_replacement_tournament(
        report,
        output_root,
        runner_path=runner_path,
    )
    loaded_report, loaded_manifest = load_replacement_tournament(output_root)

    audit_by_id = {item.candidate_id: item for item in audits}
    projection_by_id = {
        item.candidate_id: item for item in projection.candidate_projections
    }
    assert set(audit_by_id) == set(ReplacementCandidateId)
    assert (
        audit_by_id[ReplacementCandidateId.AUTOSDT_5K].lineage.task_count
        == 5_148
    )
    assert len(
        audit_by_id[
            ReplacementCandidateId.AUTOSDT_5K
        ].lineage.source_group_ids
    ) == 1_317
    assert (
        projection_by_id["autosdt-5k"].lineaged_capacity_group_count == 1_002
    )
    assert (
        audit_by_id[
            ReplacementCandidateId.SCIENCE_AGENT_BENCH
        ].lineage.task_count
        == 102
    )
    assert (
        projection_by_id[
            "scienceagentbench"
        ].independent_group_upper_bound
        == 44
    )
    assert (
        audit_by_id[ReplacementCandidateId.CORE_BENCH].lineage.task_count
        == 270
    )
    assert projection_by_id["core-bench"].independent_group_upper_bound == 90
    assert projection_by_id["core-bench"].sealed_reserve_group_capacity == 45
    assert (
        audit_by_id[ReplacementCandidateId.QRDATA].lineage.task_count == 411
    )
    assert projection_by_id["qrdata"].independent_group_upper_bound == 190
    assert projection_by_id["qrdata"].sealed_reserve_group_capacity == 0
    assert all(not item.eligible for item in projection.candidate_projections)
    assert (
        projection.decision.status
        is ReplacementTournamentStatus.ALL_CANDIDATES_REJECTED
    )
    assert projection.decision.selected_candidate_id is None
    assert projection.decision.research_question_issued is False
    assert projection.decision.confirmation_panel_created_or_read is False
    assert projection.decision.publication_claim_authorized is False
    assert projection.decision.submission_authorized is False
    assert certificate.exact is True
    assert len(
        {
            runtime.environment_hash
            for runtime in certificate.interpreter_runtimes
        }
    ) == 2
    assert loaded_report == report
    assert loaded_manifest == manifest
    assert loaded_report.candidate_model_calls_run is False
    assert loaded_report.outcome_values_projected is False
