from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from dotenv import load_dotenv

from autoresearch.config import ConfigParser, SystemConfig
from autoresearch.knowledge.raw_memory import RawMemoryStore
from autoresearch.llm.client import run_llm_json_completion
from autoresearch.research.adaptive_capabilities import (
    AdaptiveResearchCapabilityEnvironment,
)
from autoresearch.research.adaptive_loop_benchmark import AdaptiveLoopBenchmarkArm
from autoresearch.research.adaptive_loop_benchmark_arm_adapters import (
    audit_benchmark_arm_realization,
    build_benchmark_arm_adapter,
    build_benchmark_arm_runtime_plan,
)
from autoresearch.research.adaptive_loop_benchmark_context import (
    AdaptiveLoopBenchmarkPublicContextAdapter,
)
from autoresearch.research.adaptive_loop_benchmark_execution_protocol import (
    write_adaptive_loop_benchmark_execution_protocol,
)
from autoresearch.research.adaptive_loop_benchmark_live_runner import (
    build_formal_gateway_trust_policy,
    run_formal_benchmark_cell,
)
from autoresearch.research.adaptive_loop_benchmark_receipts import (
    write_adaptive_loop_benchmark_receipt_bridge_once,
)
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveLoopPolicy,
    AdaptiveLoopRunStatus,
    AdaptiveResearchLoopSnapshot,
    AdaptiveResearchSeed,
    ExternalResearchFeedback,
    ModelResearchActionDraft,
    ResearchOperator,
    TemporaryAgentBatchOutcome,
    TemporaryResearchTask,
    create_adaptive_research_seed,
    run_adaptive_research_loop,
)
from autoresearch.research.adaptive_transport_gateway import (
    TransportGatewayReplayLedger,
)
from autoresearch.research.adaptive_transport_gateway_worker import (
    adaptive_transport_gateway_worker_trust_manifest,
)


class _EphemeralSignedLiveGateway:
    """Real HTTPS worker with a test-owned key; never confirmation evidence."""

    test_only = True

    def __init__(
        self,
        *,
        api_key: str,
        private_key_pem: str,
        origin: str,
        model_name: str,
        nonce_ledger_root: Path,
        timeout_seconds: int,
    ) -> None:
        self._environment = _minimal_worker_environment(
            api_key=api_key,
            private_key_pem=private_key_pem,
            origin=origin,
            model_name=model_name,
            nonce_ledger_root=nonce_ledger_root,
            timeout_seconds=timeout_seconds,
        )

    def __call__(self, canonical_worker_request: bytes) -> bytes:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "autoresearch.research.adaptive_transport_gateway_worker",
            ],
            cwd=Path(__file__).resolve().parents[2],
            env=self._environment,
            input=canonical_worker_request,
            capture_output=True,
            check=False,
            timeout=330,
        )
        if completed.returncode != 0:
            raise RuntimeError("test-only signed live gateway failed closed")
        return completed.stdout


class _DreamingOnlyLiveEnvironment:
    """Expose only local Dreaming; public stimuli come from the frozen adapter."""

    def __init__(self, delegate: AdaptiveResearchCapabilityEnvironment) -> None:
        self._delegate = delegate

    def supported_operators(self) -> frozenset[ResearchOperator]:
        return frozenset({ResearchOperator.CONSOLIDATE_DREAMING})

    def execute(
        self,
        *,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
        proposal: ModelResearchActionDraft,
    ) -> ExternalResearchFeedback:
        if proposal.operator is not ResearchOperator.CONSOLIDATE_DREAMING:
            raise AssertionError("live memory pilot may execute only local Dreaming")
        return self._delegate.execute(
            seed=seed,
            snapshot=snapshot,
            proposal=proposal,
        )


class _UnavailableLiveTemporaryDispatcher:
    """Expose the capability boundary without fabricating temporary-Agent output."""

    def dispatch(
        self,
        *,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
        proposal: ModelResearchActionDraft,
        tasks: Sequence[TemporaryResearchTask],
    ) -> TemporaryAgentBatchOutcome:
        del seed, snapshot, proposal, tasks
        raise RuntimeError("nonconfirmatory live pilot has no temporary-Agent gateway")


def test_real_qwen_completes_twelve_turn_a4_without_intermediate_human_prose() -> None:
    if os.getenv("RUN_LIVE_ADAPTIVE_BENCHMARK_SIGNED") != "1":
        pytest.skip(
            "set RUN_LIVE_ADAPTIVE_BENCHMARK_SIGNED=1 for the signed live pilot"
        )
    run_id = os.getenv("ADAPTIVE_BENCHMARK_LIVE_RUN_ID")
    if not run_id or run_id.strip() != run_id:
        pytest.fail("ADAPTIVE_BENCHMARK_LIVE_RUN_ID must name one fresh retained run")

    root = Path("runs/manual-live") / run_id
    if root.exists():
        pytest.fail(f"live benchmark run already exists: {root}")
    root.mkdir(parents=True)

    load_dotenv(Path(".env"), override=True)
    config = ConfigParser().parse_file("config.yaml", model_type=SystemConfig)
    assert isinstance(config, SystemConfig)
    llm = config.deployment.llm
    api_key = os.getenv(llm.api_key_env)
    if not api_key:
        pytest.fail(f"missing configured API key environment: {llm.api_key_env}")
    endpoint = llm.base_url.rstrip("/") + "/chat/completions"
    parsed = urlsplit(endpoint)
    if parsed.scheme != "https" or not parsed.hostname:
        pytest.fail("signed live benchmark requires one HTTPS provider endpoint")
    origin = f"{parsed.scheme}://{parsed.netloc}"

    private_key = Ed25519PrivateKey.generate()
    private_key_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    public_key = private_key.public_key()
    public_der = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_fingerprint = hashlib.sha256(public_der).hexdigest()

    protocol_root = root / "protocol"
    bundle = write_adaptive_loop_benchmark_execution_protocol(
        protocol_root,
        randomization_seed=27_132_026,
    )
    bridge = write_adaptive_loop_benchmark_receipt_bridge_once(protocol_root, bundle)
    scenario = bundle.protocol.public_scenarios[0]
    binding = next(
        item
        for item in bridge.cells
        if item.scenario_id == scenario.scenario_id
        and item.arm is AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN
    )
    blinded_cell = next(
        item
        for item in bundle.blinded_cells.cells
        if item.blinded_cell_id == binding.blinded_cell_id
    )
    raw_store = RawMemoryStore(root / "autoresearch-vault")
    seed = create_adaptive_research_seed(
        loop_id=f"{run_id}-loop",
        project_id=run_id.replace("-", "_"),
        objective_cn=scenario.objective_cn,
        scope_cn=scenario.scope_cn,
        raw_memory_store=raw_store,
    )
    policy = AdaptiveLoopPolicy(
        policy_id="adaptive-loop-benchmark-live-a4-pilot-v1",
        max_steps=12,
        max_model_calls=12,
        max_external_actions=12,
        max_temporary_agents=14,
        max_consecutive_stalls=20,
        thinking_budget=2_000,
    )
    manifest = adaptive_transport_gateway_worker_trust_manifest()
    gateway = _EphemeralSignedLiveGateway(
        api_key=api_key,
        private_key_pem=private_key_pem,
        origin=origin,
        model_name=llm.model_name,
        nonce_ledger_root=root / "gateway-request-nonces",
        timeout_seconds=min(llm.request_timeout_seconds, 300),
    )

    artifact = run_formal_benchmark_cell(
        receipt_root=protocol_root,
        output_dir=root / "cell",
        bridge=bridge,
        public_scenario=scenario,
        blinded_cell=blinded_cell,
        cell_binding=binding,
        arm_runtime_plan=build_benchmark_arm_runtime_plan(
            AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN
        ),
        seed=seed,
        policy=policy,
        gateway_trust_policy=build_formal_gateway_trust_policy(
            model_name=llm.model_name,
            request_url=endpoint,
            allowlisted_origins={origin},
            trusted_gateway_public_key_sha256=public_fingerprint,
            trusted_gateway_build_sha256=manifest.gateway_build_sha256,
            trusted_gateway_source_sha256=manifest.gateway_source_sha256,
        ),
        raw_memory_store=raw_store,
        gateway_transport=gateway,
        replay_ledger=TransportGatewayReplayLedger(root / "verifier-antireplay"),
    )

    assert artifact.test_only_non_confirmatory is True
    assert artifact.formal_eligible is False
    assert artifact.scientific_result_generated is False
    assert artifact.scoring_not_executed is True
    assert len(artifact.call_evidence) == 12
    assert len(artifact.final_snapshot.events) == 12
    assert all(
        event.interaction.model_name == llm.model_name
        and event.interaction.proposal.human_authored_scientific_prose_count == 0
        and event.orchestrator_scientific_prose_count == 0
        for event in artifact.final_snapshot.events
    )
    assert artifact.sovereign_recall_use_receipt is not None
    assert (
        artifact.sovereign_recall_use_receipt.actual_sovereign_recall_use_verified
        is True
    )
    assert artifact.terminal is not None
    assert artifact.terminal.actual_sovereign_recall_use_verified is True
    assert artifact.terminal.formal_eligible is False


def test_real_qwen_runs_nonconfirmatory_a4_behavior_loop_with_dreaming() -> None:
    if os.getenv("RUN_LIVE_ADAPTIVE_BENCHMARK") != "1":
        pytest.skip("set RUN_LIVE_ADAPTIVE_BENCHMARK=1 for the behavior-only pilot")
    run_id = os.getenv("ADAPTIVE_BENCHMARK_LIVE_RUN_ID")
    if not run_id or run_id.strip() != run_id:
        pytest.fail("ADAPTIVE_BENCHMARK_LIVE_RUN_ID must name one fresh retained run")

    root = Path("runs/manual-live") / run_id
    if root.exists():
        pytest.fail(f"live benchmark run already exists: {root}")
    root.mkdir(parents=True)
    bundle = write_adaptive_loop_benchmark_execution_protocol(
        root / "protocol",
        randomization_seed=27_132_026,
    )
    scenario = bundle.protocol.public_scenarios[0]
    binding = next(
        item
        for item in bundle.runner_assignments.assignments
        if item.scenario_id == scenario.scenario_id
        and item.arm is AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN
    )
    blinded_cell = next(
        item
        for item in bundle.blinded_cells.cells
        if item.blinded_cell_id == binding.blinded_cell_id
    )
    store = RawMemoryStore(root / "autoresearch-vault")
    seed = create_adaptive_research_seed(
        loop_id=f"{run_id}-loop",
        project_id=run_id.replace("-", "_"),
        objective_cn=scenario.objective_cn,
        scope_cn=scenario.scope_cn,
        raw_memory_store=store,
    )
    policy = AdaptiveLoopPolicy(
        policy_id="adaptive-loop-benchmark-live-a4-behavior-v1",
        max_steps=12,
        max_model_calls=12,
        max_external_actions=12,
        max_temporary_agents=14,
        max_consecutive_stalls=20,
        thinking_budget=2_000,
    )
    loop_root = root / "loop"
    context = AdaptiveLoopBenchmarkPublicContextAdapter(
        public_scenario=scenario,
        blinded_cell=blinded_cell,
        raw_memory_store=store,
    )
    environment = _DreamingOnlyLiveEnvironment(
        AdaptiveResearchCapabilityEnvironment(
            output_dir=loop_root,
            raw_memory_store=store,
        )
    )
    snapshot = run_adaptive_research_loop(
        seed=seed,
        policy=policy,
        raw_memory_store=store,
        output_dir=loop_root,
        environment=environment,
        operator_catalog_provider=build_benchmark_arm_adapter(
            AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN
        ),
        external_turn_context_provider=context,
        temporary_dispatcher=_UnavailableLiveTemporaryDispatcher(),
        completion=run_llm_json_completion,
    )
    config = ConfigParser().parse_file("config.yaml", model_type=SystemConfig)
    assert isinstance(config, SystemConfig)
    audit = audit_benchmark_arm_realization(
        plan=build_benchmark_arm_runtime_plan(
            AdaptiveLoopBenchmarkArm.ADAPTIVE_SOVEREIGN
        ),
        snapshot=snapshot,
        artifact_root=loop_root,
    )

    assert snapshot.status is AdaptiveLoopRunStatus.PAUSED_BUDGET
    assert len(snapshot.events) == 12
    assert snapshot.model_call_count == 12
    assert all(
        event.interaction.model_name == config.deployment.llm.model_name
        and event.interaction.proposal.human_authored_scientific_prose_count == 0
        and event.orchestrator_scientific_prose_count == 0
        for event in snapshot.events
    )
    assert audit.capability_matrix_realized is True
    assert audit.dreaming_operator_count >= 1
    assert audit.sovereign_selection_artifact_count >= 1
    assert snapshot.events[-1].interaction.proposal.memory_consumption_claims
    assert audit.actual_sovereign_recall_use_verified is False


def _minimal_worker_environment(
    *,
    api_key: str,
    private_key_pem: str,
    origin: str,
    model_name: str,
    nonce_ledger_root: Path,
    timeout_seconds: int,
) -> dict[str, str]:
    inherited_names = (
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    )
    environment = {
        name: value
        for name in inherited_names
        if (value := os.environ.get(name)) is not None
    }
    environment.update(
        {
            "PYTHONUTF8": "1",
            "AUTORESEARCH_GATEWAY_PROVIDER_API_KEY": api_key,
            "AUTORESEARCH_GATEWAY_PRIVATE_KEY_PEM": private_key_pem,
            "AUTORESEARCH_GATEWAY_ALLOWED_ORIGINS": origin,
            "AUTORESEARCH_GATEWAY_PROVIDER": "qwen",
            "AUTORESEARCH_GATEWAY_MODEL": model_name,
            "AUTORESEARCH_GATEWAY_REQUEST_NONCE_LEDGER": str(
                nonce_ledger_root.resolve()
            ),
            "AUTORESEARCH_GATEWAY_TIMEOUT_SECONDS": str(timeout_seconds),
        }
    )
    return environment
