"""Public-only v3 benchmark stimuli for the adaptive sovereign loop.

The adapter deliberately accepts only the public scenario and blinded cell
contracts.  It captures exactly one current-turn payload in sovereign raw
memory before constructing the controller-visible external context.  It does
not score cells, select a runtime assignment, call a model, or produce results.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from autoresearch.kernel.contracts import canonical_sha256
from autoresearch.knowledge.raw_memory import (
    RawMemorySourceKind,
    RawMemoryStore,
)
from autoresearch.research.adaptive_loop_benchmark_execution_protocol import (
    AdaptiveLoopBenchmarkBlindedCell,
    AdaptiveLoopBenchmarkPublicScenario,
    AdaptiveLoopBenchmarkPublicStimulus,
)
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveExternalTurnContext,
    AdaptiveLoopRunStatus,
    AdaptiveResearchBranch,
    AdaptiveResearchLoopSnapshot,
    AdaptiveResearchSeed,
)

_TURN_COUNT = 12
_CONTEXT_BINDING_SCHEMA_VERSION = "adaptive-loop-benchmark-public-context-binding-v1"
_CONTEXT_ID_PREFIX = "adaptive-benchmark-context-"
_CAPTURE_LOCK = threading.Lock()
_PRIVATE_FIELD_PREFIXES = ("oracle", "required_", "forbidden_", "arm_")
_PRIVATE_FIELD_NAMES = frozenset(
    {
        "arm",
        "expected_terminal_state",
        "hidden_oracle",
        "machine_oracle",
        "ordered_arms",
    }
)
_PRIVATE_VALUE_MARKERS = (
    "oracle",
    "required_",
    "forbidden_",
    "expected_terminal",
    "ordered_arms",
    "arm_assignment",
    "fixed_pipeline",
    "linear_model_loop",
    "adaptive_derived_memory",
    "adaptive_sovereign_memory",
)


class AdaptiveLoopBenchmarkContextError(RuntimeError):
    """Raised before a mixed, repeated, changed, or private stimulus can escape."""


class AdaptiveLoopBenchmarkPublicContextAdapter:
    """Expose one frozen public stimulus per loop turn, never private scoring data."""

    def __init__(
        self,
        *,
        public_scenario: AdaptiveLoopBenchmarkPublicScenario,
        blinded_cell: AdaptiveLoopBenchmarkBlindedCell,
        raw_memory_store: RawMemoryStore,
    ) -> None:
        if not isinstance(public_scenario, AdaptiveLoopBenchmarkPublicScenario):
            raise TypeError("public_scenario must be a v3 public scenario")
        if not isinstance(blinded_cell, AdaptiveLoopBenchmarkBlindedCell):
            raise TypeError("blinded_cell must be a blinded public cell")
        if not isinstance(raw_memory_store, RawMemoryStore):
            raise TypeError("raw_memory_store must be a RawMemoryStore")
        try:
            scenario = AdaptiveLoopBenchmarkPublicScenario.model_validate(
                public_scenario.model_dump(mode="json")
            )
            cell = AdaptiveLoopBenchmarkBlindedCell.model_validate(
                blinded_cell.model_dump(mode="json")
            )
        except ValueError as exc:
            raise AdaptiveLoopBenchmarkContextError(
                f"public benchmark input failed canonical validation: {exc}"
            ) from exc
        _validate_scenario_cell_pair(scenario, cell)
        _assert_public_only(
            [item.model_dump(mode="json") for item in scenario.stimuli],
            path="public_stimuli",
        )
        self._public_scenario = scenario
        self._blinded_cell = cell
        self._raw_memory_store = raw_memory_store
        self._scenario_fingerprint = canonical_sha256(scenario)
        self._cell_fingerprint = canonical_sha256(cell)
        self._bound_seed_fingerprint: str | None = None
        self._issued_snapshot_hashes: set[str] = set()

    def contexts_for_turn(
        self,
        *,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
        branch: AdaptiveResearchBranch,
    ) -> tuple[AdaptiveExternalTurnContext]:
        """Capture and return exactly one public context for the current turn."""

        validated_seed, validated_snapshot, validated_branch = _validate_loop_inputs(
            seed=seed,
            snapshot=snapshot,
            branch=branch,
            public_scenario=self._public_scenario,
            raw_memory_store=self._raw_memory_store,
        )
        self._recheck_frozen_inputs()
        seed_fingerprint = canonical_sha256(validated_seed)
        if (
            self._bound_seed_fingerprint is not None
            and seed_fingerprint != self._bound_seed_fingerprint
        ):
            raise AdaptiveLoopBenchmarkContextError(
                "benchmark adapter cannot cross a loop seed boundary"
            )
        if validated_snapshot.snapshot_hash in self._issued_snapshot_hashes:
            raise AdaptiveLoopBenchmarkContextError(
                "current benchmark turn was already emitted by this adapter"
            )

        turn_index = validated_snapshot.next_step_index
        if turn_index > _TURN_COUNT:
            raise AdaptiveLoopBenchmarkContextError(
                "public benchmark has exactly twelve ordered turns"
            )
        self._verify_prior_turns(validated_seed, validated_snapshot)
        stimulus = self._public_scenario.stimuli[turn_index - 1]
        _recheck_stimulus(stimulus, expected_turn=turn_index)
        _assert_public_only(stimulus.model_dump(mode="json"), path="current_stimulus")

        identity_hash = _context_identity_hash(
            seed=validated_seed,
            cell=self._blinded_cell,
            scenario=self._public_scenario,
            stimulus=stimulus,
        )
        context_id = f"{_CONTEXT_ID_PREFIX}{identity_hash}"
        source_ref = _source_ref(
            loop_id=validated_seed.loop_id,
            turn_index=turn_index,
            context_id=context_id,
        )
        with _CAPTURE_LOCK:
            _require_unused_source_ref(
                self._raw_memory_store,
                project_id=validated_seed.project_id,
                source_ref=source_ref,
            )
            capture = self._raw_memory_store.capture_text(
                stimulus.payload_cn,
                project_id=validated_seed.project_id,
                source_kind=RawMemorySourceKind.TOOL_OUTPUT,
                source_label=f"自适应循环基准第{turn_index}轮公开刺激",
                source_ref=source_ref,
                original_name=f"benchmark-public-turn-{turn_index:02d}-{identity_hash[:16]}.txt",
                source_authorized=True,
                sensitive_content_reviewed=True,
            )
        self._raw_memory_store.verify_capture(capture)
        context = AdaptiveExternalTurnContext.create(
            context_id=context_id,
            loop_id=validated_seed.loop_id,
            project_id=validated_seed.project_id,
            step_index=turn_index,
            source_ref=source_ref,
            content_cn=stimulus.payload_cn,
            content_sha256=hashlib.sha256(stimulus.payload_cn.encode("utf-8")).hexdigest(),
            raw_binding=capture.binding(self._raw_memory_store.vault_root),
        )
        _verify_context(
            context,
            seed=validated_seed,
            cell=self._blinded_cell,
            scenario=self._public_scenario,
            stimulus=stimulus,
            raw_memory_store=self._raw_memory_store,
        )
        _assert_public_only(context.model_dump(mode="json"), path="external_context")
        self._bound_seed_fingerprint = seed_fingerprint
        self._issued_snapshot_hashes.add(validated_snapshot.snapshot_hash)
        del validated_branch  # validated above; branch identity never enters the stimulus.
        return (context,)

    def _recheck_frozen_inputs(self) -> None:
        try:
            scenario = AdaptiveLoopBenchmarkPublicScenario.model_validate(
                self._public_scenario.model_dump(mode="json")
            )
            cell = AdaptiveLoopBenchmarkBlindedCell.model_validate(
                self._blinded_cell.model_dump(mode="json")
            )
        except ValueError as exc:
            raise AdaptiveLoopBenchmarkContextError(
                f"frozen public benchmark input changed: {exc}"
            ) from exc
        if canonical_sha256(scenario) != self._scenario_fingerprint:
            raise AdaptiveLoopBenchmarkContextError("frozen public scenario changed")
        if canonical_sha256(cell) != self._cell_fingerprint:
            raise AdaptiveLoopBenchmarkContextError("frozen blinded cell changed")
        _validate_scenario_cell_pair(scenario, cell)

    def _verify_prior_turns(
        self,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
    ) -> None:
        for expected_turn, event in enumerate(snapshot.events, start=1):
            contexts = event.interaction.external_turn_contexts
            if len(contexts) != 1:
                raise AdaptiveLoopBenchmarkContextError(
                    "every preceding benchmark turn must retain exactly one public context"
                )
            stimulus = self._public_scenario.stimuli[expected_turn - 1]
            _verify_context(
                contexts[0],
                seed=seed,
                cell=self._blinded_cell,
                scenario=self._public_scenario,
                stimulus=stimulus,
                raw_memory_store=self._raw_memory_store,
            )
            projections = _external_context_message_projections(event.interaction.messages)
            if len(projections) != 1 or not _projection_matches_context(
                projections[0], contexts[0]
            ):
                raise AdaptiveLoopBenchmarkContextError(
                    "preceding benchmark context was not injected exactly once"
                )


def _validate_scenario_cell_pair(
    scenario: AdaptiveLoopBenchmarkPublicScenario,
    cell: AdaptiveLoopBenchmarkBlindedCell,
) -> None:
    expected_scenario_hash = canonical_sha256(
        scenario.model_dump(mode="json", exclude={"public_scenario_hash"})
    )
    if scenario.public_scenario_hash != expected_scenario_hash:
        raise AdaptiveLoopBenchmarkContextError("public scenario hash changed")
    if (
        cell.scenario_id != scenario.scenario_id
        or cell.challenge_kind is not scenario.challenge_kind
        or cell.public_scenario_hash != scenario.public_scenario_hash
    ):
        raise AdaptiveLoopBenchmarkContextError(
            "blinded cell and public scenario do not form one frozen pair"
        )
    if len(scenario.stimuli) != _TURN_COUNT or [
        item.turn_index for item in scenario.stimuli
    ] != list(range(1, _TURN_COUNT + 1)):
        raise AdaptiveLoopBenchmarkContextError(
            "public scenario must contain ordered turns one through twelve"
        )
    for expected_turn, stimulus in enumerate(scenario.stimuli, start=1):
        _recheck_stimulus(stimulus, expected_turn=expected_turn)


def _validate_loop_inputs(
    *,
    seed: AdaptiveResearchSeed,
    snapshot: AdaptiveResearchLoopSnapshot,
    branch: AdaptiveResearchBranch,
    public_scenario: AdaptiveLoopBenchmarkPublicScenario,
    raw_memory_store: RawMemoryStore,
) -> tuple[AdaptiveResearchSeed, AdaptiveResearchLoopSnapshot, AdaptiveResearchBranch]:
    if not isinstance(seed, AdaptiveResearchSeed):
        raise TypeError("seed must be an AdaptiveResearchSeed")
    if not isinstance(snapshot, AdaptiveResearchLoopSnapshot):
        raise TypeError("snapshot must be an AdaptiveResearchLoopSnapshot")
    if not isinstance(branch, AdaptiveResearchBranch):
        raise TypeError("branch must be an AdaptiveResearchBranch")
    try:
        checked_seed = AdaptiveResearchSeed.model_validate(seed.model_dump(mode="json"))
        checked_snapshot = AdaptiveResearchLoopSnapshot.model_validate(
            snapshot.model_dump(mode="json")
        )
        checked_branch = AdaptiveResearchBranch.model_validate(branch.model_dump(mode="json"))
    except ValueError as exc:
        raise AdaptiveLoopBenchmarkContextError(
            f"adaptive loop input failed canonical validation: {exc}"
        ) from exc
    if checked_snapshot.seed != checked_seed:
        raise AdaptiveLoopBenchmarkContextError("snapshot belongs to another loop seed")
    if checked_snapshot.status is not AdaptiveLoopRunStatus.RUNNING:
        raise AdaptiveLoopBenchmarkContextError("benchmark context requires a running snapshot")
    if checked_branch not in checked_snapshot.branches:
        raise AdaptiveLoopBenchmarkContextError("selected branch is absent from the snapshot")
    if (
        checked_seed.objective_cn != public_scenario.objective_cn
        or checked_seed.scope_cn != public_scenario.scope_cn
    ):
        raise AdaptiveLoopBenchmarkContextError(
            "loop seed objective and scope do not match the public scenario"
        )
    try:
        capture = raw_memory_store.load_record(
            checked_seed.raw_seed_binding.record_relative_path,
            project_id=checked_seed.project_id,
        )
    except Exception as exc:
        raise AdaptiveLoopBenchmarkContextError(
            f"loop seed raw-memory binding could not be verified: {exc}"
        ) from exc
    if capture.binding(raw_memory_store.vault_root) != checked_seed.raw_seed_binding:
        raise AdaptiveLoopBenchmarkContextError("loop seed raw-memory binding changed")
    return checked_seed, checked_snapshot, checked_branch


def _recheck_stimulus(
    stimulus: AdaptiveLoopBenchmarkPublicStimulus,
    *,
    expected_turn: int,
) -> None:
    expected_hash = canonical_sha256(stimulus.model_dump(mode="json", exclude={"stimulus_hash"}))
    if stimulus.turn_index != expected_turn or stimulus.stimulus_hash != expected_hash:
        raise AdaptiveLoopBenchmarkContextError("public stimulus order or hash changed")


def _context_identity_hash(
    *,
    seed: AdaptiveResearchSeed,
    cell: AdaptiveLoopBenchmarkBlindedCell,
    scenario: AdaptiveLoopBenchmarkPublicScenario,
    stimulus: AdaptiveLoopBenchmarkPublicStimulus,
) -> str:
    identity = {
        "schema_version": _CONTEXT_BINDING_SCHEMA_VERSION,
        "blinded_cell_id": cell.blinded_cell_id,
        "scenario_id": scenario.scenario_id,
        "public_scenario_hash": scenario.public_scenario_hash,
        "stimulus_id": stimulus.stimulus_id,
        "turn_index": stimulus.turn_index,
        "stimulus_hash": stimulus.stimulus_hash,
        "loop_id": seed.loop_id,
        "project_id": seed.project_id,
    }
    _assert_public_only(identity, path="context_identity")
    return canonical_sha256(identity)


def _source_ref(*, loop_id: str, turn_index: int, context_id: str) -> str:
    return f"adaptive-loop:{loop_id}:step:{turn_index}:" f"external-context:{context_id}"


def _verify_context(
    context: AdaptiveExternalTurnContext,
    *,
    seed: AdaptiveResearchSeed,
    cell: AdaptiveLoopBenchmarkBlindedCell,
    scenario: AdaptiveLoopBenchmarkPublicScenario,
    stimulus: AdaptiveLoopBenchmarkPublicStimulus,
    raw_memory_store: RawMemoryStore,
) -> None:
    _recheck_stimulus(stimulus, expected_turn=stimulus.turn_index)
    identity_hash = _context_identity_hash(
        seed=seed,
        cell=cell,
        scenario=scenario,
        stimulus=stimulus,
    )
    context_id = f"{_CONTEXT_ID_PREFIX}{identity_hash}"
    expected_ref = _source_ref(
        loop_id=seed.loop_id,
        turn_index=stimulus.turn_index,
        context_id=context_id,
    )
    expected_content_hash = hashlib.sha256(stimulus.payload_cn.encode("utf-8")).hexdigest()
    if (
        context.context_id != context_id
        or context.loop_id != seed.loop_id
        or context.project_id != seed.project_id
        or context.step_index != stimulus.turn_index
        or context.source_ref != expected_ref
        or context.content_cn != stimulus.payload_cn
        or context.content_sha256 != expected_content_hash
    ):
        raise AdaptiveLoopBenchmarkContextError(
            "external context is not bound to this cell, scenario, step, and stimulus"
        )
    expected_context_hash = canonical_sha256(
        context.model_dump(mode="json", exclude={"context_hash"})
    )
    if context.context_hash != expected_context_hash:
        raise AdaptiveLoopBenchmarkContextError("external context hash changed")
    try:
        capture = raw_memory_store.load_record(
            context.raw_binding.record_relative_path,
            project_id=seed.project_id,
        )
    except Exception as exc:
        raise AdaptiveLoopBenchmarkContextError(
            f"external context raw memory could not be verified: {exc}"
        ) from exc
    if capture.binding(raw_memory_store.vault_root) != context.raw_binding:
        raise AdaptiveLoopBenchmarkContextError("external context raw binding changed")
    if (
        capture.record.envelope.source_kind is not RawMemorySourceKind.TOOL_OUTPUT
        or capture.record.envelope.source_ref != expected_ref
        or capture.blob_path.read_bytes() != stimulus.payload_cn.encode("utf-8")
    ):
        raise AdaptiveLoopBenchmarkContextError(
            "external context raw provenance or exact bytes changed"
        )


def _require_unused_source_ref(
    store: RawMemoryStore,
    *,
    project_id: str,
    source_ref: str,
) -> None:
    record_root = store.private_root / "projects" / project_id / "records"
    if not record_root.exists():
        return
    for record_path in record_root.glob("*/*/*.json"):
        try:
            capture = store.load_record(
                record_path.resolve().relative_to(store.vault_root),
                project_id=project_id,
            )
        except Exception as exc:
            raise AdaptiveLoopBenchmarkContextError(
                f"raw-memory capture index could not be verified: {exc}"
            ) from exc
        if capture.record.envelope.source_ref == source_ref:
            raise AdaptiveLoopBenchmarkContextError(
                "current benchmark turn already has a raw-memory capture"
            )


def _external_context_message_projections(
    messages: Sequence[Mapping[Literal["role", "content"], str]],
) -> list[dict[str, Any]]:
    projections: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") != "user":
            continue
        try:
            payload = json.loads(message.get("content", ""))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("context_kind") == (
            "adaptive_external_turn_context"
        ):
            _assert_public_only(payload, path="retained_context_message")
            projections.append(payload)
    return projections


def _projection_matches_context(
    projection: Mapping[str, Any],
    context: AdaptiveExternalTurnContext,
) -> bool:
    return all(
        (
            projection.get("context_id") == context.context_id,
            projection.get("loop_id") == context.loop_id,
            projection.get("project_id") == context.project_id,
            projection.get("step_index") == context.step_index,
            projection.get("source_ref") == context.source_ref,
            projection.get("content_cn") == context.content_cn,
            projection.get("content_sha256") == context.content_sha256,
            projection.get("raw_binding") == context.raw_binding.model_dump(mode="json"),
            projection.get("context_hash") == context.context_hash,
        )
    )


def _assert_public_only(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).casefold()
            if normalized == "contains_required_operator":
                if item is not False:
                    raise AdaptiveLoopBenchmarkContextError(
                        f"{path}.{key} must remain the inherited false safety declaration"
                    )
            elif (
                normalized in _PRIVATE_FIELD_NAMES
                or normalized.startswith(_PRIVATE_FIELD_PREFIXES)
                or normalized.endswith("_oracle")
                or normalized.endswith("_arm")
            ):
                raise AdaptiveLoopBenchmarkContextError(
                    f"{path} contains a private benchmark field"
                )
            _assert_public_only(item, path=f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, item in enumerate(value):
            _assert_public_only(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str):
        folded = value.casefold()
        if any(marker in folded for marker in _PRIVATE_VALUE_MARKERS):
            raise AdaptiveLoopBenchmarkContextError(f"{path} contains a private benchmark value")


__all__ = [
    "AdaptiveLoopBenchmarkContextError",
    "AdaptiveLoopBenchmarkPublicContextAdapter",
]
