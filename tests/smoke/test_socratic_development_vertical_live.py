"""Opt-in official-source inventory gate for Task 263.6.5."""

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
    InventoryProjection,
    LiveResourceProbe,
    NearestWorkDelta,
    ResearchSource,
    ResourceKind,
    SocraticInventoryStatus,
    SourceMaturity,
    build_inventory_projection,
    build_inventory_replay_payload,
    build_socratic_development_inventory,
    fetch_discoverybench_inventory_material,
    load_socratic_development_inventory,
    probe_web_resource,
    run_inventory_replay,
    write_socratic_development_inventory,
)

LIVE_ENV = "AUTORESEARCH_SOCRATIC_DEVELOPMENT_INVENTORY_LIVE"
OUTPUT_ENV = "AUTORESEARCH_SOCRATIC_DEVELOPMENT_INVENTORY_OUTPUT"
INTERPRETER_A_ENV = "AUTORESEARCH_WORKLOAD_INTERPRETER_A"
INTERPRETER_B_ENV = "AUTORESEARCH_WORKLOAD_INTERPRETER_B"

pytestmark = pytest.mark.skipif(
    os.getenv(LIVE_ENV) != "1",
    reason=(
        f"set {LIVE_ENV}=1 to audit the official DiscoveryBench revision, "
        "answer-key keys, licenses, literature, and two clean interpreters"
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
        total=4,
        connect=4,
        read=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update(
        {"User-Agent": "AutoResearch/1.0 task-263.6.5 inventory-gate"}
    )
    return session


def _source_definitions() -> list[SourceDefinition]:
    return [
        SourceDefinition(
            source_id="ahois",
            title=(
                "Socratic agents for autonomous scientific discovery in "
                "high-dimensional physical systems"
            ),
            year=2026,
            locator="arxiv:2606.26722",
            url="https://arxiv.org/html/2606.26722",
            maturity=SourceMaturity.PREPRINT,
            shared_scope=(
                "causal questioning, constraint checking, counterexamples, "
                "and falsification criteria"
            ),
            claimed_delta=(
                "tests these components on independently grouped objective "
                "fault decisions under equal budgets"
            ),
            overlap_risk=(
                "AHOIS already reports a four-part Socratic critic and ablations"
            ),
            decisive_comparison=(
                "source-group paired objective fault detection without a "
                "physics-platform-specific evaluator"
            ),
        ),
        SourceDefinition(
            source_id="astabench",
            title=(
                "AstaBench: Rigorous Benchmarking of AI Agents with a "
                "Scientific Research Suite"
            ),
            year=2025,
            locator="arxiv:2510.21652",
            url="https://arxiv.org/abs/2510.21652",
            maturity=SourceMaturity.PREPRINT,
            shared_scope="controlled scientific-agent harnesses and strong baselines",
            claimed_delta=(
                "uses equal model, tool, call, token, CPU, and failure budgets"
            ),
            overlap_risk=(
                "AstaBench already standardizes agent interfaces and tool access"
            ),
            decisive_comparison=(
                "mechanism-level critic ablation with independent source groups"
            ),
        ),
        SourceDefinition(
            source_id="autosdt",
            title="AutoSDT: Scaling Data-Driven Discovery Tasks Toward Open Co-Scientists",
            year=2025,
            locator="arxiv:2506.08140",
            url="https://arxiv.org/html/2506.08140",
            maturity=SourceMaturity.PREPRINT,
            shared_scope=(
                "large-scale open executable data-driven discovery tasks"
            ),
            claimed_delta=(
                "would use per-source licenses and objective fault decisions, "
                "not training-data scale as a scientific effect"
            ),
            overlap_risk=(
                "AutoSDT already supplies 5,404 tasks and a per-task license manifest"
            ),
            decisive_comparison=(
                "audit independent repositories and executable labels before "
                "selecting a replacement panel"
            ),
        ),
        SourceDefinition(
            source_id="discoverybench",
            title=(
                "DiscoveryBench: Towards Data-Driven Discovery with "
                "Large Language Models"
            ),
            year=2024,
            locator="arxiv:2407.01725",
            url="https://arxiv.org/html/2407.01725",
            maturity=SourceMaturity.PREPRINT,
            shared_scope="real and synthetic data-driven hypothesis discovery",
            claimed_delta=(
                "requires deterministic valid-versus-fault labels instead of HMS"
            ),
            overlap_risk=(
                "DiscoveryBench already defines context, variable, and relation facets"
            ),
            decisive_comparison=(
                "pre-frozen fault labels and adequate independent reserve units"
            ),
        ),
        SourceDefinition(
            source_id="popper",
            title="Automated Hypothesis Validation with Agentic Sequential Falsifications",
            year=2025,
            locator="PMLR:267:25372-25437",
            url="https://proceedings.mlr.press/v267/huang25n.html",
            maturity=SourceMaturity.PEER_REVIEWED,
            shared_scope="agentic falsification with Type-I error control",
            claimed_delta=(
                "isolates critic components under a fixed binary fault endpoint"
            ),
            overlap_risk=(
                "POPPER already supplies sequential falsification and error control"
            ),
            decisive_comparison=(
                "same-model paired component ablations on licensed source groups"
            ),
        ),
        SourceDefinition(
            source_id="scienceagentbench",
            title=(
                "ScienceAgentBench: Toward Rigorous Assessment of Language "
                "Agents for Data-Driven Scientific Discovery"
            ),
            year=2025,
            locator="arxiv:2410.05080",
            url="https://arxiv.org/abs/2410.05080",
            maturity=SourceMaturity.PEER_REVIEWED,
            shared_scope="executable scientific coding tasks and cost evaluation",
            claimed_delta=(
                "targets invalid scientific premises rather than code success alone"
            ),
            overlap_risk=(
                "ScienceAgentBench already has 102 tasks from 44 publications"
            ),
            decisive_comparison=(
                "at least 84 independent reserve sources with deterministic faults"
            ),
        ),
        SourceDefinition(
            source_id="sciagentarena",
            title="Benchmarking AI Agents for Addressing Scientific Challenges Across Scales",
            year=2026,
            locator="arxiv:2606.12736",
            url="https://arxiv.org/abs/2606.12736",
            maturity=SourceMaturity.PREPRINT,
            shared_scope="stepwise validity evaluation of scientific agents",
            claimed_delta=(
                "would test a specific four-component critic causal mechanism"
            ),
            overlap_risk=(
                "SciAgentArena directly covers validity and invalid-premise failures"
            ),
            decisive_comparison=(
                "licensed objective paired ablation with enough independent units"
            ),
        ),
    ]


def _source_material(
    *,
    checked_at: datetime,
    session: requests.Session,
) -> tuple[
    list[ResearchSource],
    list[NearestWorkDelta],
    list[LiveResourceProbe],
]:
    definitions = _source_definitions()
    probes = [
        probe_web_resource(
            resource_id=item.source_id,
            kind=ResourceKind.LITERATURE,
            url=item.url,
            checked_at=checked_at,
            session=session,
            timeout_seconds=60,
            max_sample_bytes=65_536,
        )
        for item in definitions
    ]
    if not all(item.reachable for item in probes):
        failures = [item.resource_id for item in probes if not item.reachable]
        raise AssertionError(f"primary source probes failed: {failures}")
    by_id = {item.resource_id: item for item in probes}
    sources = [
        ResearchSource(
            source_id=item.source_id,
            title=item.title,
            year=item.year,
            locator=item.locator,
            source_url=item.url,
            maturity=item.maturity,
            source_fingerprint=by_id[item.source_id].sample_sha256,
        )
        for item in definitions
    ]
    nearest = [
        NearestWorkDelta(
            source_id=item.source_id,
            shared_scope=item.shared_scope,
            claimed_delta=item.claimed_delta,
            overlap_risk=item.overlap_risk,
            decisive_comparison=item.decisive_comparison,
        )
        for item in definitions
    ]
    return sources, nearest, probes


def test_task26365_live_socratic_inventory_stop_gate() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    output_root = Path(
        os.getenv(
            OUTPUT_ENV,
            str(
                repository_root
                / "runs"
                / "manual-live"
                / "task26365-socratic-inventory-v1"
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

    runner = (
        repository_root
        / "src"
        / "autoresearch"
        / "research"
        / "assets"
        / "frozen_discoverybench_inventory_probe_v1.py"
    )
    checked_at = datetime.now(timezone.utc)
    session = _session()
    metadata, tree, answer_keys, database_license, harness_license = (
        fetch_discoverybench_inventory_material(session=session)
    )
    folders, local_projection = build_inventory_projection(
        tree_entries=tree,
        answer_keys=answer_keys,
        database_license=database_license,
    )
    assert len(folders) == 189
    replay_payload = build_inventory_replay_payload(
        tree_entries=tree,
        answer_keys=answer_keys,
    )
    replay = run_inventory_replay(
        replay_payload=replay_payload,
        input_path=output_root / "inventory-replay-input.json",
        runner_path=runner,
        interpreters={"clean-a": interpreter_a, "clean-b": interpreter_b},
        expected_projection=InventoryProjection.model_validate(
            local_projection.model_dump(mode="json")
        ),
        observed_at=checked_at,
    )
    sources, nearest, probes = _source_material(
        checked_at=checked_at,
        session=session,
    )
    report = build_socratic_development_inventory(
        study_id="task26365-socratic-inventory-v1",
        created_at=checked_at,
        literature_cutoff=checked_at.date(),
        research_questions=[
            (
                "After provenance and license clustering, can DiscoveryBench "
                "retain 30 development and 84 untouched reserve source groups?"
            ),
            (
                "Can four scientific fault classes be generated and scored "
                "deterministically without an LLM judge or post-result labels?"
            ),
            (
                "Under equal model, tool, token, call, CPU, wall-clock, and "
                "failure budgets, does the full critic improve source-group "
                "fault detection over no-critic and rule controls?"
            ),
        ],
        sources=sources,
        nearest_work=nearest,
        source_probes=probes,
        dataset_metadata=metadata,
        tree_entries=tree,
        answer_keys=answer_keys,
        database_license=database_license,
        harness_license=harness_license,
        replay_certificate=replay,
    )
    manifest = write_socratic_development_inventory(
        report,
        output_root,
        runner_path=runner,
    )
    loaded, loaded_manifest = load_socratic_development_inventory(output_root)

    assert loaded == report
    assert loaded_manifest == manifest
    assert report.snapshot.tree_entry_count == 987
    assert report.snapshot.directory_count == 198
    assert report.snapshot.file_count == 789
    assert report.projection.provisional_folder_count == 189
    assert report.projection.train_folder_count == 104
    assert report.projection.test_folder_count == 85
    assert report.projection.conservative_source_group_count == 107
    assert report.projection.maximum_reserve_after_development == 41
    assert report.projection.optimistic_reserve_upper_bound == 81
    assert report.projection.test_answer_key_lineage_complete is True
    assert {item.row_count for item in report.answer_keys} == {200, 239}
    assert report.replay_certificate.exact_cross_interpreter_projection is True
    assert report.decision.status is SocraticInventoryStatus.STOPPED_AT_INVENTORY
    assert report.decision.evaluator_construction_authorized is False
    assert report.decision.provider_configuration_collected is False
    assert report.decision.research_question_certificate_issued is False
    assert report.decision.confirmatory_panel_created_or_read is False
    assert report.decision.public_release_authorized is False
    assert report.decision.external_submission_authorized is False
