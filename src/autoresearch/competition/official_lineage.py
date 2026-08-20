"""Task 269.1: the reviewed, hash-bound driver for one preregistered official lineage.

Why this module exists
----------------------
The last real lineage, `runs/manual-live/task2663-conformant-v1`, was driven by an
untracked repo-root scratch script (`_lineage268.py`) that carried stage state across
eight separate invocations. That is a provenance hole rather than a convenience:

* the script was absent from the commit history, so the exact bytes that drove a
  formal preregistered lineage were unrecoverable;
* it could change silently between two stages of the same lineage;
* it was excluded from `ruff`, `mypy`, and the test suite;
* it hand-wrote the frozen gate evaluation inside its `adjudicate` stage, so the
  adjudication rule that decides whether a search-freeze receipt is issued lived
  in unreviewed code;
* nothing constructed an `OfficialDevelopmentSearchPackage`, so the lineage produced
  no signed package and its only adjudication record was a scratch text file.

This module owns the stage sequence, owns the frozen gate evaluation, and writes a
hash-verified `OfficialDevelopmentSearchPackage`. Every threshold is read from the
frozen plan; nothing numeric is hard-coded here.

Formal stage sequence
---------------------
``plan`` -> ``approve`` -> ``generate`` -> ``pilot`` -> ``revise`` -> ``baseline``
-> ``full`` -> ``adjudicate`` -> ``outcome``

The first eight stages preserve the retired driver's execution order.  ``outcome``
is the production, read-only bridge from signed adjudication evidence to the
configured model's own Chinese interpretation; it never executes an experiment,
records an approval, or authorizes publication.

Reading counts from the frozen plan instead of hard-coding them
--------------------------------------------------------------
The retired script hard-coded `timeout_seconds=300`, an initial candidate count of
8, a finalist count of 3, and a pilot subset of the first two ODE plus the first two
PDE systems. The frozen Task `266.1` plan already states all four, and
`freeze_official_identity` already derives `pilot_system_count` from
`pilot_ode_system_count + pilot_pde_system_count`. The script's hard-coded `[:2]`
subset therefore executed 4 pilot systems while the frozen identity it wrote
declared 6, so the executed breadth contradicted the lineage's own frozen identity
(`P-20260803-072`). This module reads all of them from the plan and refuses a pilot
whose breadth disagrees with the frozen identity.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections import Counter
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field, ValidationError

from autoresearch.competition.autonomous_engine import AutonomousModelInteraction
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.competition.official_development_search import (
    _AUTHORING_ATTEMPT_NAME,
    _GENERATION_CONFORMANCE_ATTEMPTS,
    _IDENTITY_NAME,
    _PACKAGE_NAME,
    _SPLIT_POLICY,
    OfficialCandidateAuthoringAttempt,
    OfficialCandidateRecord,
    OfficialCellResult,
    OfficialCellSpec,
    OfficialDevelopmentIdentity,
    OfficialDevelopmentSearchPackage,
    OfficialLogicalModelTurnRegistration,
    SystemEffect,
    aggregate_paired_effects,
    baseline_method_for,
    build_official_cell_specs,
    compute_system_effects,
    execute_official_stage,
    freeze_official_identity,
    generate_official_candidates,
    revise_official_candidates,
    select_official_candidate,
)
from autoresearch.competition.official_spend_ledger import (
    OfficialSpendLedger,
    load_or_create_ledger,
    persist_ledger,
)
from autoresearch.competition.preregistered_stage_breadth import (
    PreregisteredStageBreadth,
    load_stage_breadth,
)
from autoresearch.competition.public_data_profile import (
    public_data_profile_evidence_view,
)
from autoresearch.competition.scientific_contract_harness import (
    ScientificContractSourceResponse,
)
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion

# ---------------------------------------------------------------------------
# Lineage-level exclusive process lock
# ---------------------------------------------------------------------------

_LOCK_NAME = ".lineage-stage-lock"
# A Qwen-backed stage can legitimately run for substantially longer than five minutes.
# The owner therefore refreshes the lease while it is alive.  Age alone is never enough
# to reclaim a lock: the recorded process must also be proven dead.
_LOCK_STALE_SECONDS = 300.0
_LOCK_HEARTBEAT_SECONDS = 30.0


def _lineage_lock_process_is_alive(pid: int) -> bool:
    """Return whether *pid* is live, failing closed on permission errors."""

    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


@contextmanager
def exclusive_lineage_lock(
    work_dir: Path, *, stage: str
) -> Generator[None, None, None]:
    """Exclusive advisory lock scoped to one lineage directory.

    `P-20260807-090`: concurrent stage invocations on the same lineage corrupt the
    spend ledger and the candidate registry. The ledger is loaded fresh, checked, and
    persisted by each process, so last-writer-wins silently underreports spend. The
    candidate registry is overwritten by whichever generate process finishes last,
    creating a mismatch between the stored source_sha256 (from one process's memory)
    and the candidate.py bytes on disk (from another process's write).

    This lock uses O_EXCL atomic creation, which is supported on every OS the lineage
    runs on. A concurrent stage invocation sees the lock file already present. If the
    PID recorded in the file is still alive, the invocation is refused. If the PID is
    gone (crash / forceful kill), the lock is stale and is reclaimed so the lineage
    does not remain permanently bricked.

    The lock is advisory, not mandatory: a process that ignores this module can still
    corrupt the directory. Correctness depends on every stage entrypoint going through
    run_lineage_stage.
    """

    import json as _json

    lock_path = work_dir / _LOCK_NAME
    owner_token = uuid4().hex
    lock_payload = {
        "pid": os.getpid(),
        "stage": stage,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "owner_token": owner_token,
    }
    lock_content = _json.dumps(lock_payload, sort_keys=True).encode()

    def _try_create() -> bool:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, lock_content)
            os.close(fd)
            return True
        except FileExistsError:
            return False

    def _read_existing() -> dict[str, Any] | None:
        try:
            payload = _json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        return dict(payload) if isinstance(payload, Mapping) else None

    def _is_stale(existing: Mapping[str, Any] | None) -> bool:
        """Return True only for an old lease whose process is proven dead."""

        try:
            stat = lock_path.stat()
            age = datetime.now(timezone.utc).timestamp() - stat.st_mtime
        except OSError:
            return True  # file disappeared → stale
        if age <= _LOCK_STALE_SECONDS:
            return False
        if existing is None:
            return True
        try:
            holder_pid = int(existing["pid"])
        except (KeyError, TypeError, ValueError):
            return True
        return not _lineage_lock_process_is_alive(holder_pid)

    def _still_owned() -> bool:
        existing = _read_existing()
        return existing is not None and existing.get("owner_token") == owner_token

    heartbeat_stop = threading.Event()

    def _heartbeat() -> None:
        while not heartbeat_stop.wait(_LOCK_HEARTBEAT_SECONDS):
            if not _still_owned():
                return
            try:
                os.utime(lock_path, None)
            except OSError:
                return

    # First try: atomic create.
    if not _try_create():
        # Lock exists. Reclaim only the same inspected lease, and only after both
        # timeout and process-liveness checks prove abandonment.
        inspected = _read_existing()
        if _is_stale(inspected):
            current = _read_existing()
            if current != inspected:
                raise OfficialLineageError(
                    f"lineage lock changed during stale inspection for "
                    f"{work_dir.name}; refusing unsafe reclamation"
                )
            with suppress(FileNotFoundError):
                lock_path.unlink()
            if not _try_create():
                # Another process raced us to claim the stale lock.
                raise OfficialLineageError(
                    f"another process is already running a stage "
                    f"(generate/pilot/revise/...) for lineage {work_dir.name}; "
                    "concurrent stage execution corrupts the spend ledger and the "
                    "candidate registry (`P-20260807-090`). Wait for the running "
                    "stage to complete before starting the next one."
                )
        else:
            holder_stage = (
                inspected.get("stage", "unknown")
                if inspected is not None
                else "unknown"
            )
            raise OfficialLineageError(
                f"another process is already running stage '{holder_stage}' for "
                f"lineage {work_dir.name}; concurrent stage execution corrupts the "
                "spend ledger and the candidate registry (`P-20260807-090`). Wait "
                "for the running stage to complete before starting the next one."
            )
    heartbeat_thread = threading.Thread(
        target=_heartbeat,
        name=f"lineage-lock-heartbeat-{stage}",
        daemon=True,
    )
    heartbeat_thread.start()
    try:
        yield
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=max(_LOCK_HEARTBEAT_SECONDS * 2.0, 1.0))
        if _still_owned():
            with suppress(OSError):
                lock_path.unlink(missing_ok=True)


# Keep the private name for internal callers that predate the rename.
_lineage_lock = exclusive_lineage_lock


LineageStage = Literal[
    "plan",
    "approve",
    "generate",
    "pilot",
    "revise",
    "baseline",
    "full",
    "adjudicate",
    "outcome",
]

LINEAGE_STAGES: tuple[LineageStage, ...] = (
    "plan",
    "approve",
    "generate",
    "pilot",
    "revise",
    "baseline",
    "full",
    "adjudicate",
    "outcome",
)

_CANDIDATE_REGISTRY = "candidate-registry.json"
_REVISED_REGISTRY = "revised-registry.json"
_ZERO_TERM_MARKER = "returned 0 terms"
_SYSTEM_AUTHORED_PLAN_NAME = "system-authored-research-plan.json"
_OUTCOME_NAME = "system-authored-outcome.json"
_OUTCOME_EXECUTION_STAGES = ("pilot", "baseline", "full")
_PLAN_RESUME_DISTRIBUTED_DIR = "distributed"
_PLAN_RESUME_IDEATION_DIR = "ideation"
_PLAN_RESUME_PREEXPERIMENT_DIR = "preexperiment"
_PLAN_RESUME_AUTHORING_DIR = "authoring"
_PLAN_RESUME_MANIFEST_NAME = "plan-stage-resume-manifest.json"


class OfficialLineageError(RuntimeError):
    """Raised when a lineage stage cannot be driven under its frozen contract."""


class OfficialLineageConfig(StrictFrozenModel):
    """Everything one preregistered lineage is bound to. Frozen for the whole run."""

    lineage_id: str = Field(min_length=1)
    work_dir: Path
    frozen_plan_path: Path
    autonomous_plan_path: Path
    data_root: Path
    prior_run_dirs: tuple[Path, ...] = ()

    @property
    def plan_dir(self) -> Path:
        """Directory holding the generated plan and its recorded human decision."""

        return self.work_dir / "plan"

    @property
    def candidates_dir(self) -> Path:
        return self.work_dir / "candidates"

    @property
    def cells_dir(self) -> Path:
        return self.work_dir / "cells"


class LineageStageReport(StrictFrozenModel):
    """What one driven stage did. Returned so a caller never parses stdout."""

    lineage_id: str
    stage: LineageStage
    lines: tuple[str, ...]
    package_path: str | None = None
    search_freeze_receipt_issued: bool | None = None
    outcome_path: str | None = None
    outcome_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    outcome_accepted: bool | None = None


class OfficialAuthoringInteractionSpendAudit(StrictFrozenModel):
    """Canonical reconciliation between authoring turns and the frozen ledger."""

    schema_version: Literal["official-authoring-interaction-spend-audit-v1"] = (
        "official-authoring-interaction-spend-audit-v1"
    )
    stage: Literal["generate-gen1", "revise-gen2"]
    expected_candidate_ids: tuple[str, ...]
    attempted_candidate_ids: tuple[str, ...]
    registered_logical_interaction_ids: tuple[str, ...]
    registered_logical_interaction_hashes: tuple[str, ...]
    canonical_interaction_ids: tuple[str, ...]
    canonical_interaction_hashes: tuple[str, ...]
    incomplete_logical_interaction_ids: tuple[str, ...]
    logical_model_interaction_count: int = Field(ge=0)
    canonical_model_interaction_count: int = Field(ge=0)
    provider_request_attempt_count: int = Field(ge=0)
    provider_request_attempt_count_is_lower_bound: bool
    ledger_candidate_count_for_stage: int = Field(ge=0)
    ledger_model_interaction_count_for_stage: int = Field(ge=0)
    frozen_maximum_model_interactions: int = Field(ge=1)
    maximum_logical_attempts_per_candidate: Literal[3] = 3
    audit_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        stage: Literal["generate-gen1", "revise-gen2"],
        expected_candidate_ids: Sequence[str],
        attempted_candidate_ids: Sequence[str],
        registrations: Sequence[OfficialLogicalModelTurnRegistration],
        interactions: Sequence[AutonomousModelInteraction],
        incomplete_ids: Sequence[str],
        ledger_candidate_count: int,
        ledger_interaction_count: int,
        frozen_maximum_model_interactions: int,
    ) -> OfficialAuthoringInteractionSpendAudit:
        payload: dict[str, Any] = {
            "schema_version": "official-authoring-interaction-spend-audit-v1",
            "stage": stage,
            "expected_candidate_ids": tuple(expected_candidate_ids),
            "attempted_candidate_ids": tuple(attempted_candidate_ids),
            "registered_logical_interaction_ids": tuple(
                item.interaction_id for item in registrations
            ),
            "registered_logical_interaction_hashes": tuple(
                item.registration_hash for item in registrations
            ),
            "canonical_interaction_ids": tuple(
                item.interaction_id for item in interactions
            ),
            "canonical_interaction_hashes": tuple(
                item.interaction_hash for item in interactions
            ),
            "incomplete_logical_interaction_ids": tuple(incomplete_ids),
            "logical_model_interaction_count": len(registrations),
            "canonical_model_interaction_count": len(interactions),
            "provider_request_attempt_count": sum(
                item.provider_request_attempt_count for item in interactions
            ),
            "provider_request_attempt_count_is_lower_bound": bool(incomplete_ids),
            "ledger_candidate_count_for_stage": ledger_candidate_count,
            "ledger_model_interaction_count_for_stage": ledger_interaction_count,
            "frozen_maximum_model_interactions": frozen_maximum_model_interactions,
            "maximum_logical_attempts_per_candidate": 3,
        }
        payload["audit_hash"] = canonical_model_hash(payload)
        return cls.model_validate(payload)

    def model_post_init(self, __context: Any) -> None:
        if self.logical_model_interaction_count != len(
            self.registered_logical_interaction_ids
        ):
            raise ValueError("logical interaction audit count mismatch")
        if self.canonical_model_interaction_count != len(self.canonical_interaction_ids):
            raise ValueError("canonical interaction audit count mismatch")
        if self.ledger_model_interaction_count_for_stage != (
            self.logical_model_interaction_count
        ):
            raise ValueError("authoring ledger does not equal registered logical turns")
        if self.ledger_candidate_count_for_stage != len(self.attempted_candidate_ids):
            raise ValueError("authoring ledger does not equal attempted candidates")
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"audit_hash"})
        )
        if self.audit_hash != expected:
            raise ValueError("authoring interaction-spend audit hash mismatch")


@dataclass(frozen=True)
class _AuthoringEvidence:
    attempted_candidate_ids: tuple[str, ...]
    registrations: tuple[OfficialLogicalModelTurnRegistration, ...]
    interactions: tuple[AutonomousModelInteraction, ...]
    incomplete_interaction_ids: tuple[str, ...]
    terminal_candidate_ids: tuple[str, ...]


_AuthoringSpec = tuple[str, str, Literal[1, 2], str | None]


def _interaction_id_for_attempt(base_interaction_id: str, attempt: int) -> str:
    return (
        base_interaction_id
        if attempt == 1
        else f"{base_interaction_id}-repair{attempt}"
    )


def _collect_authoring_evidence(
    *,
    config: OfficialLineageConfig,
    stage: Literal["generate-gen1", "revise-gen2"],
    specs: Sequence[_AuthoringSpec],
    records: Sequence[OfficialCandidateRecord] | None = None,
) -> _AuthoringEvidence:
    """Parse exact expected artifacts; filenames alone never count as spend."""

    attempted: list[str] = []
    registrations: list[OfficialLogicalModelTurnRegistration] = []
    interactions: list[AutonomousModelInteraction] = []
    incomplete: list[str] = []
    terminal: list[str] = []
    interactions_by_id: dict[str, AutonomousModelInteraction] = {}
    expected_ids: set[str] = set()
    generation = 1 if stage == "generate-gen1" else 2
    for candidate_id, base_interaction_id, expected_generation, parent_hash in specs:
        if expected_generation != generation:
            raise OfficialLineageError("authoring stage/spec generation mismatch")
        marker_path = (
            config.candidates_dir / candidate_id / _AUTHORING_ATTEMPT_NAME
        )
        marker: OfficialCandidateAuthoringAttempt | None = None
        if marker_path.is_file():
            try:
                marker = OfficialCandidateAuthoringAttempt.model_validate_json(
                    marker_path.read_text(encoding="utf-8")
                )
            except (OSError, ValidationError) as exc:
                raise OfficialLineageError(
                    f"invalid candidate authoring marker for {candidate_id}: {exc}"
                ) from exc
            expected_marker = {
                "stage": stage,
                "generation": generation,
                "candidate_id": candidate_id,
                "base_interaction_id": base_interaction_id,
                "parent_source_sha256": parent_hash,
            }
            if any(
                getattr(marker, key) != value for key, value in expected_marker.items()
            ):
                raise OfficialLineageError(
                    f"candidate authoring marker drifted for {candidate_id}"
                )
            attempted.append(candidate_id)

        missing_registration_seen = False
        candidate_interactions: list[AutonomousModelInteraction] = []
        for attempt in range(1, _GENERATION_CONFORMANCE_ATTEMPTS + 1):
            interaction_id = _interaction_id_for_attempt(base_interaction_id, attempt)
            expected_ids.add(interaction_id)
            registration_path = (
                config.work_dir
                / "interactions"
                / f"{interaction_id}.logical-turn.json"
            )
            interaction_path = config.work_dir / "interactions" / f"{interaction_id}.json"
            if not registration_path.is_file():
                missing_registration_seen = True
                if interaction_path.is_file():
                    raise OfficialLineageError(
                        f"canonical interaction lacks pre-call registration: {interaction_id}"
                    )
                continue
            if marker is None:
                raise OfficialLineageError(
                    f"logical interaction lacks candidate marker: {interaction_id}"
                )
            if missing_registration_seen:
                raise OfficialLineageError(
                    f"logical interaction registration sequence has a gap: {interaction_id}"
                )
            try:
                registration = OfficialLogicalModelTurnRegistration.model_validate_json(
                    registration_path.read_text(encoding="utf-8")
                )
            except (OSError, ValidationError) as exc:
                raise OfficialLineageError(
                    f"invalid logical-turn registration {interaction_id}: {exc}"
                ) from exc
            expected_stage = (
                "scientific_contract_implementation"
                if stage == "generate-gen1" and attempt == 1
                else "scientific_contract_repair"
            )
            if (
                registration.interaction_id != interaction_id
                or registration.candidate_id != candidate_id
                or registration.stage != expected_stage
                or registration.logical_attempt_index != attempt
            ):
                raise OfficialLineageError(
                    f"logical-turn registration contract mismatch: {interaction_id}"
                )
            registrations.append(registration)
            if not interaction_path.is_file():
                incomplete.append(interaction_id)
                continue
            try:
                interaction = AutonomousModelInteraction.model_validate_json(
                    interaction_path.read_text(encoding="utf-8")
                )
            except (OSError, ValidationError) as exc:
                raise OfficialLineageError(
                    f"invalid canonical interaction {interaction_id}: {exc}"
                ) from exc
            if (
                interaction.interaction_id != interaction_id
                or interaction.candidate_id != candidate_id
                or interaction.stage != expected_stage
            ):
                raise OfficialLineageError(
                    f"canonical interaction contract mismatch: {interaction_id}"
                )
            interactions.append(interaction)
            candidate_interactions.append(interaction)
            interactions_by_id[interaction_id] = interaction

        source_path = config.candidates_dir / candidate_id / "candidate.py"
        if source_path.is_file():
            source_bytes = source_path.read_text(encoding="utf-8")
            matching = []
            for interaction in candidate_interactions:
                try:
                    response = ScientificContractSourceResponse.model_validate(
                        interaction.parsed_payload
                    )
                except ValidationError:
                    continue
                if response.source_text == source_bytes:
                    matching.append(interaction.interaction_id)
            if not matching or matching[-1] != candidate_interactions[-1].interaction_id:
                raise OfficialLineageError(
                    f"candidate source is not bound to its final canonical interaction: "
                    f"{candidate_id}"
                )
            terminal.append(candidate_id)

    interaction_root = config.work_dir / "interactions"
    if interaction_root.is_dir():
        bases = tuple(spec[1] for spec in specs)
        for path in interaction_root.glob("*.json"):
            for base in bases:
                match = re.fullmatch(rf"{re.escape(base)}(?:-repair([0-9]+))?\.json", path.name)
                if match and path.stem not in expected_ids:
                    raise OfficialLineageError(
                        f"unbounded authoring interaction artifact is forbidden: {path.name}"
                    )

    if records is not None:
        expected_candidates = tuple(spec[0] for spec in specs)
        if tuple(item.candidate_id for item in records) != expected_candidates:
            raise OfficialLineageError("authoring registry candidate order/identity mismatch")
        for record in records:
            accepted_interaction = interactions_by_id.get(record.interaction_id)
            if (
                accepted_interaction is None
                or accepted_interaction.interaction_hash != record.interaction_hash
            ):
                raise OfficialLineageError(
                    f"candidate registry does not bind a canonical interaction: "
                    f"{record.candidate_id}"
                )
            source_path = (config.work_dir / record.source_relative_path).resolve()
            try:
                source_path.relative_to(config.work_dir.resolve())
            except ValueError as exc:
                raise OfficialLineageError("candidate source path escapes lineage") from exc
            if not source_path.is_file():
                raise OfficialLineageError("candidate registry source is missing")
            source_text = source_path.read_text(encoding="utf-8")
            if hashlib.sha256(source_text.encode("utf-8")).hexdigest() != record.source_sha256:
                raise OfficialLineageError("candidate registry source hash mismatch")
            response = ScientificContractSourceResponse.model_validate(
                accepted_interaction.parsed_payload
            )
            if response.source_text != source_text:
                raise OfficialLineageError(
                    "accepted interaction payload differs from final candidate source"
                )

    return _AuthoringEvidence(
        attempted_candidate_ids=tuple(attempted),
        registrations=tuple(registrations),
        interactions=tuple(interactions),
        incomplete_interaction_ids=tuple(incomplete),
        terminal_candidate_ids=tuple(terminal),
    )


def _stage_ledger_counts(
    ledger: OfficialSpendLedger, *, stage: str
) -> tuple[int, int]:
    return (
        sum(item.candidate_count for item in ledger.entries if item.stage == stage),
        sum(item.model_interactions for item in ledger.entries if item.stage == stage),
    )


def _reconcile_authoring_spend(
    *,
    config: OfficialLineageConfig,
    ledger: OfficialSpendLedger,
    stage: Literal["generate-gen1", "revise-gen2"],
    specs: Sequence[_AuthoringSpec],
    records: Sequence[OfficialCandidateRecord] | None = None,
) -> tuple[OfficialSpendLedger, _AuthoringEvidence, OfficialAuthoringInteractionSpendAudit]:
    evidence = _collect_authoring_evidence(
        config=config, stage=stage, specs=specs, records=records
    )
    recorded_candidates, recorded_interactions = _stage_ledger_counts(
        ledger, stage=stage
    )
    actual_candidates = len(evidence.attempted_candidate_ids)
    actual_interactions = len(evidence.registrations)
    if recorded_candidates > actual_candidates or recorded_interactions > actual_interactions:
        raise OfficialLineageError(
            f"{stage} ledger claims spend without matching canonical registrations"
        )
    candidate_delta = actual_candidates - recorded_candidates
    interaction_delta = actual_interactions - recorded_interactions
    if candidate_delta or interaction_delta:
        ledger = ledger.record(
            stage=stage,
            candidate_count=candidate_delta,
            model_interactions=interaction_delta,
            new_generation=(recorded_candidates == 0 and candidate_delta > 0),
        )
        persist_ledger(ledger=ledger, output_dir=config.work_dir)
    recorded_candidates, recorded_interactions = _stage_ledger_counts(
        ledger, stage=stage
    )
    audit = OfficialAuthoringInteractionSpendAudit.create(
        stage=stage,
        expected_candidate_ids=tuple(spec[0] for spec in specs),
        attempted_candidate_ids=evidence.attempted_candidate_ids,
        registrations=evidence.registrations,
        interactions=evidence.interactions,
        incomplete_ids=evidence.incomplete_interaction_ids,
        ledger_candidate_count=recorded_candidates,
        ledger_interaction_count=recorded_interactions,
        frozen_maximum_model_interactions=ledger.maximum_model_interactions,
    )
    write_json_model(
        config.work_dir / "interactions" / f"{stage}-spend-audit.json", audit
    )
    return ledger, evidence, audit


def _check_authoring_reservation(
    *,
    ledger: OfficialSpendLedger,
    stage: Literal["generate-gen1", "revise-gen2"],
    specs: Sequence[_AuthoringSpec],
    evidence: _AuthoringEvidence,
) -> None:
    """Reserve the bounded worst case before the next provider call can occur."""

    attempted = set(evidence.attempted_candidate_ids)
    terminal = set(evidence.terminal_candidate_ids)
    registrations_by_candidate = Counter(
        item.candidate_id for item in evidence.registrations
    )
    candidate_reservation = sum(spec[0] not in attempted for spec in specs)
    interaction_reservation = sum(
        0
        if candidate_id in terminal
        else _GENERATION_CONFORMANCE_ATTEMPTS
        - registrations_by_candidate.get(candidate_id, 0)
        for candidate_id, _base, _generation, _parent in specs
    )
    recorded_candidates, _ = _stage_ledger_counts(ledger, stage=stage)
    ledger.check(
        candidate_count=candidate_reservation,
        model_interactions=interaction_reservation,
        new_generation=recorded_candidates == 0,
    )


# ---------------------------------------------------------------------------
# Frozen gate evaluation, moved out of the scratch driver
# ---------------------------------------------------------------------------


def evaluate_frozen_gate(
    *,
    estimand: dict[str, Any],
    summary: dict[str, Any],
    candidate_cells: Sequence[OfficialCellResult],
    baseline_results: Sequence[OfficialCellResult],
    remaining_budget: dict[str, int],
) -> dict[str, bool]:
    """Evaluate every frozen check for one adjudication.

    Numerically identical to the evaluation the retired scratch driver performed,
    with each threshold read from the frozen plan's estimand instead of a literal.
    A `None` aggregate is a FAILED check, never a pass, because an absent estimate
    is not evidence that the estimand was met.

    The two `must_succeed` checks are evaluated over a NON-EMPTY arm. An `all()`
    over zero cells is vacuously true, which would let an arm that produced no
    cells at all satisfy a success gate.
    """

    overall = summary.get("overall_median_log_effect")
    lower = summary.get("bootstrap_lower")
    ode = summary.get("ode_stratum_median")
    pde = summary.get("pde_stratum_median")
    return {
        "all_candidate_cells_succeeded": bool(candidate_cells)
        and all(item.status == "succeeded" for item in candidate_cells),
        "all_baseline_cells_succeeded": bool(baseline_results)
        and all(item.status == "succeeded" for item in baseline_results),
        "overall_median_at_least_minimum": overall is not None
        and float(overall) >= float(estimand["minimum_overall_log_effect"]),
        "bootstrap_lower_above_zero": lower is not None
        and float(lower) > float(estimand["exploratory_lower_bound_minimum"]),
        "ode_stratum_non_negative": ode is not None
        and float(ode) >= float(estimand["ode_stratum_median_minimum"]),
        "pde_stratum_non_negative": pde is not None
        and float(pde) >= float(estimand["pde_stratum_median_minimum"]),
        "budget_conformant": all(value >= 0 for value in remaining_budget.values()),
    }


def frozen_gate_receipt(gate_checks: dict[str, bool]) -> bool:
    """A search-freeze receipt is issued if and only if every frozen check passes."""

    if not gate_checks:
        raise OfficialLineageError(
            "a receipt cannot be decided from an empty gate; the frozen estimand "
            "requires every check to be evaluated"
        )
    return all(gate_checks.values())


def write_official_development_search_package(
    *,
    identity: OfficialDevelopmentIdentity,
    candidates: Sequence[OfficialCandidateRecord],
    cell_results: Sequence[OfficialCellResult],
    stages_executed: Sequence[str],
    selected_candidate_id: str | None,
    selection_basis: str,
    system_effects: Sequence[SystemEffect],
    summary: dict[str, Any],
    estimand: dict[str, Any],
    gate_checks: dict[str, bool],
    output_dir: Path | str,
) -> OfficialDevelopmentSearchPackage:
    """Construct, write, and re-verify the signed development-search package.

    The package model already refuses a receipt that coexists with a failed check.
    Nothing constructed it before this function, which is why the conformant lineage
    produced no signed adjudication record.
    """

    output_root = Path(output_dir).resolve()
    output_path = output_root / _PACKAGE_NAME
    payload: dict[str, Any] = {
        "schema_version": "official-development-search-package-v1",
        "identity": identity.model_dump(mode="json"),
        "candidates": [item.model_dump(mode="json") for item in candidates],
        "cell_results": [item.model_dump(mode="json") for item in cell_results],
        "stages_executed": list(stages_executed),
        "selected_candidate_id": selected_candidate_id,
        "selection_basis": selection_basis,
        "system_effects": [item.model_dump(mode="json") for item in system_effects],
        "overall_median_log_effect": summary.get("overall_median_log_effect"),
        "bootstrap_lower": summary.get("bootstrap_lower"),
        "bootstrap_upper": summary.get("bootstrap_upper"),
        "ode_stratum_median": summary.get("ode_stratum_median"),
        "pde_stratum_median": summary.get("pde_stratum_median"),
        "minimum_overall_log_effect": float(estimand["minimum_overall_log_effect"]),
        "gate_checks": dict(gate_checks),
        "search_freeze_receipt_issued": frozen_gate_receipt(gate_checks),
        "confirmation_identity_read_count": 0,
        "system_generated_manuscript_count": 0,
        "publication_ready": False,
    }
    payload["package_hash"] = canonical_model_hash(payload)
    payload["output_path"] = output_path.as_posix()
    package = OfficialDevelopmentSearchPackage.model_validate(payload)
    write_json_model(output_path, package)
    # Re-read the written bytes so the persisted artifact, not just the in-memory
    # object, is the thing whose hash was verified.
    reloaded = OfficialDevelopmentSearchPackage.model_validate_json(
        output_path.read_text(encoding="utf-8")
    )
    if reloaded.package_hash != package.package_hash:
        raise OfficialLineageError("written package hash does not match the constructed one")
    return reloaded


# ---------------------------------------------------------------------------
# Frozen-plan derived stage shape
# ---------------------------------------------------------------------------


def select_pilot_systems(
    *, panel: dict[str, Any], budget: dict[str, Any]
) -> list[dict[str, Any]]:
    """Take the pilot subset stated by the frozen plan, ODE first then PDE."""

    ode_count = int(budget["pilot_ode_system_count"])
    pde_count = int(budget["pilot_pde_system_count"])
    ode = [item for item in panel["systems"] if item["data_type"] == "ode"][:ode_count]
    pde = [item for item in panel["systems"] if item["data_type"] == "pde"][:pde_count]
    if len(ode) != ode_count or len(pde) != pde_count:
        raise OfficialLineageError(
            f"panel cannot supply the frozen pilot breadth: asked for {ode_count} ODE "
            f"and {pde_count} PDE systems, panel supplied {len(ode)} and {len(pde)}"
        )
    return [*ode, *pde]


def rank_pilot_finalists(
    *,
    candidates: Sequence[OfficialCandidateRecord],
    pilot_results: Sequence[OfficialCellResult],
    finalist_count: int,
) -> list[OfficialCandidateRecord]:
    """Rank approved candidates by median pilot validation NMSE, best first.

    Validation NMSE, never the held-out loss that forms the reported effect, so the
    revision choice cannot be contaminated by the outcome being measured.
    """

    ranked: list[tuple[float, str, OfficialCandidateRecord]] = []
    for record in candidates:
        if not record.static_review_approved:
            continue
        # Truthiness, not `is not None`, exactly as the retired script filtered. This
        # also drops an exact 0.0 validation loss; on the real noisy panel no cell has
        # ever produced one, and changing the filter would change which candidates a
        # replay of the retained lineage selects. Recorded as `P-20260803-073`.
        values = sorted(
            float(item.validation_nmse)
            for item in pilot_results
            if item.candidate_id == record.candidate_id
            and item.status == "succeeded"
            and item.validation_nmse
        )
        if not values:
            continue
        ranked.append((values[len(values) // 2], record.candidate_id, record))
    # candidate_id breaks ties deterministically, so a replay selects the same set.
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [record for _, _, record in ranked[:finalist_count]]


# ---------------------------------------------------------------------------
# Lineage-wide loading
# ---------------------------------------------------------------------------


def _load_frozen_plan(config: OfficialLineageConfig) -> dict[str, Any]:
    return dict(json.loads(config.frozen_plan_path.read_text(encoding="utf-8")))


def _freeze(
    config: OfficialLineageConfig,
) -> tuple[dict[str, Any], OfficialDevelopmentIdentity, dict[str, Any], OfficialSpendLedger]:
    """Freeze the result-blind identity and load the cross-stage spend ledger."""

    frozen = _load_frozen_plan(config)
    budget = frozen["search_budget"]
    identity, panel = freeze_official_identity(
        plan_path=config.frozen_plan_path,
        autonomous_plan_path=config.autonomous_plan_path,
        data_root=config.data_root,
        output_dir=config.work_dir,
        initial_candidate_count=int(budget["initial_candidate_count"]),
    )
    ledger = load_or_create_ledger(
        output_dir=config.work_dir,
        lineage_id=config.lineage_id,
        plan_hash=identity.plan_hash,
        budget=budget,
    )
    return frozen, identity, panel, ledger


def freeze_lineage(
    config: OfficialLineageConfig,
) -> tuple[OfficialDevelopmentIdentity, OfficialSpendLedger]:
    """Freeze this lineage's identity and persist its EMPTY spend ledger.

    Separated from the stage sequence so a lineage can be frozen and preregistered
    without generating a candidate or executing a cell. `freeze_official_identity`
    reads metadata only, so no numeric payload is opened here, and the ledger is
    written with zero spend so a new lineage provably starts clean.
    """

    _frozen, identity, _panel, ledger = _freeze(config)
    if ledger.entries:
        raise OfficialLineageError(
            f"lineage {config.lineage_id} already carries "
            f"{len(ledger.entries)} spend entries, so it is not a new lineage; a "
            "fresh lineage needs a fresh directory"
        )
    persist_ledger(ledger=ledger, output_dir=config.work_dir)
    return identity, ledger


def _load_frozen_read_only(
    config: OfficialLineageConfig,
) -> tuple[dict[str, Any], OfficialDevelopmentIdentity, OfficialSpendLedger]:
    """Load an already-frozen lineage WITHOUT rewriting any of its artifacts.

    Adjudication must never mutate a retained lineage, so it reads the identity that
    the freeze stage already wrote instead of re-freezing.
    """

    frozen = _load_frozen_plan(config)
    identity_path = config.work_dir / _IDENTITY_NAME
    if not identity_path.is_file():
        raise OfficialLineageError(
            f"no frozen identity at {identity_path}; this lineage was never frozen"
        )
    identity = OfficialDevelopmentIdentity.model_validate_json(
        identity_path.read_text(encoding="utf-8")
    )
    ledger = load_or_create_ledger(
        output_dir=config.work_dir,
        lineage_id=config.lineage_id,
        plan_hash=identity.plan_hash,
        budget=frozen["search_budget"],
    )
    return frozen, identity, ledger


def _load_registry(path: Path) -> list[OfficialCandidateRecord]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        OfficialCandidateRecord.model_validate(item) for item in payload["candidates"]
    ]


def _load_results(path: Path) -> list[OfficialCellResult]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [OfficialCellResult.model_validate(item) for item in payload["results"]]


def _load_plan_and_decision(config: OfficialLineageConfig) -> tuple[Any, Any]:
    from autoresearch.research.plan_confirmation import load_plan_decision
    from autoresearch.schemas import ResearchPlan

    plan = ResearchPlan.model_validate_json(
        (config.plan_dir / "research-plan.json").read_text(encoding="utf-8")
    )
    decision = load_plan_decision(project_id=plan.project_id, output_dir=config.plan_dir)
    return plan, decision


def _load_formal_system_plan_artifact(
    config: OfficialLineageConfig,
    *,
    config_path: Path | str = Path("config.yaml"),
    require_decision: bool = True,
) -> tuple[Any, Any, Any]:
    """Load the approved plan together with its exact Qwen-authored v2 lineage.

    Execution may not compile a detached ``ResearchPlan`` because that drops the
    prospective atom, observed baseline, and intervention identity.  This loader
    also replays the authorship receipt so a self-consistent hand-written artifact
    cannot become the source of an official execution contract.
    """

    from autoresearch.competition.model_authorship import (
        load_bound_authorship_receipt,
        plan_authored_fields,
    )
    from autoresearch.competition.system_authored_plan import (
        PlanScientificLineageAttestationV2,
        PlanScientificLineageBindingV2,
        SystemAuthoredPlanArtifact,
    )
    from autoresearch.llm.client import _parse_json_completion_content
    from autoresearch.schemas import ResearchPlan

    if require_decision:
        plan, decision = _load_plan_and_decision(config)
    else:
        plan = ResearchPlan.model_validate_json(
            (config.plan_dir / "research-plan.json").read_text(encoding="utf-8")
        )
        decision = None
    artifact_path = config.work_dir / _SYSTEM_AUTHORED_PLAN_NAME
    if not artifact_path.is_file():
        raise OfficialLineageError(
            "formal execution requires the retained system-authored plan artifact"
        )
    try:
        artifact = SystemAuthoredPlanArtifact.model_validate_json(
            artifact_path.read_text(encoding="utf-8")
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise OfficialLineageError(
            f"formal system-authored plan artifact is invalid: {exc}"
        ) from exc
    if (
        artifact.schema_version != "system-authored-research-plan-v2"
        or artifact.lineage_id != config.lineage_id
        or Path(artifact.output_path).resolve() != artifact_path.resolve()
        or artifact.plan != plan.model_dump(mode="json")
        or artifact.plan_hash
        != canonical_model_hash(plan.model_dump(mode="json"))
        or not isinstance(
            artifact.scientific_lineage_binding,
            PlanScientificLineageBindingV2,
        )
        or not isinstance(
            artifact.scientific_lineage_attestation,
            PlanScientificLineageAttestationV2,
        )
    ):
        raise OfficialLineageError(
            "official ResearchPlan is not the exact prospective system-authored v2 plan"
        )
    try:
        receipt = load_bound_authorship_receipt(
            lineage_dir=config.work_dir,
            relative_path=artifact.authorship_receipt_relative_path,
            expected_hash=artifact.authorship_receipt_hash,
            artifact_kind="research_plan",
            expected_model_name=artifact.model_name,
            expected_fields=plan_authored_fields(artifact.plan),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise OfficialLineageError(
            f"formal plan authorship receipt is invalid: {exc}"
        ) from exc
    receipt_path = _require_path_inside(
        config.work_dir,
        config.work_dir / str(artifact.authorship_receipt_relative_path),
        label="formal plan authorship",
    )
    if Path(receipt.output_path).resolve() != receipt_path:
        raise OfficialLineageError(
            "formal plan authorship receipt records a different canonical path"
        )
    attestation_payload = artifact.scientific_lineage_attestation.model_dump(
        mode="json"
    )
    if receipt.parsed_payload.get("scientific_lineage_attestation") != (
        attestation_payload
    ):
        raise OfficialLineageError(
            "formal plan attestation differs from the configured model response"
        )
    try:
        parsed_response, normalization, normalization_suffix = (
            _parse_json_completion_content(receipt.response_text)
        )
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise OfficialLineageError(
            f"formal plan raw model response cannot be replayed: {exc}"
        ) from exc
    if (
        parsed_response != receipt.parsed_payload
        or normalization != receipt.transport_normalization
        or normalization_suffix != receipt.normalization_suffix
    ):
        raise OfficialLineageError(
            "formal plan raw response differs from its accepted parsed payload"
        )
    configured_provider, configured_base_url, configured_model = (
        _configured_llm_identity(config_path)
    )
    if (
        receipt.provider != configured_provider
        or receipt.base_url.rstrip("/") != configured_base_url
        or receipt.model_name != configured_model
        or "qwen" not in receipt.model_name.casefold()
        or receipt.reasoning_transport == "absent"
        or len(str(receipt.reasoning_content or "").strip()) < 200
    ):
        raise OfficialLineageError(
            "formal plan authorship is not bound to the configured reasoning-enabled Qwen"
        )
    return artifact, plan, decision


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


def build_system_plan_evidence_context(
    config: OfficialLineageConfig,
) -> tuple[dict[str, Any], tuple[Path, ...], dict[str, Any]]:
    """Build a complete plan input from retained bytes, without authoring science.

    The function deliberately contains no hypothesis, mechanism, method, title,
    expected result, or problem statement.  It serializes the immutable protocol,
    public panel, preregistered child-lineage boundaries, and prior signed outcomes.
    The configured model must infer and author every scientific field itself.
    """

    from autoresearch.competition.official_baseline_policy import (
        BaselinePolicyError,
        load_baseline_policy,
    )
    from autoresearch.competition.public_data_profile import (
        profile_public_development_data,
    )

    frozen = json.loads(config.frozen_plan_path.read_text(encoding="utf-8"))
    autonomous = json.loads(config.autonomous_plan_path.read_text(encoding="utf-8"))
    panel = dict(autonomous["development_panel"])
    evidence_paths: list[Path] = [
        config.frozen_plan_path.resolve(),
        config.autonomous_plan_path.resolve(),
    ]
    current_boundaries: dict[str, Any] = {}

    identity_path = config.work_dir / _IDENTITY_NAME
    if identity_path.is_file():
        current_boundaries["frozen_identity"] = json.loads(
            identity_path.read_text(encoding="utf-8")
        )
        evidence_paths.append(identity_path.resolve())
    try:
        policy = load_baseline_policy(output_dir=config.work_dir)
    except BaselinePolicyError:
        policy = None
    if policy is not None:
        current_boundaries["preregistered_baseline_policy"] = policy.model_dump(
            mode="json"
        )
        evidence_paths.append(Path(policy.output_path).resolve())
    breadth = load_stage_breadth(output_dir=config.work_dir)
    if breadth is not None:
        current_boundaries["preregistered_stage_breadth"] = breadth.model_dump(
            mode="json"
        )
        evidence_paths.append(Path(breadth.output_path).resolve())

    retained: list[dict[str, Any]] = []
    observed_failures: list[str] = []
    for prior_dir in config.prior_run_dirs:
        prior_root = prior_dir.resolve()
        package_path = prior_root / _PACKAGE_NAME
        if not package_path.is_file():
            raise OfficialLineageError(
                f"prior lineage has no signed package: {package_path}"
            )
        package = OfficialDevelopmentSearchPackage.model_validate_json(
            package_path.read_text(encoding="utf-8")
        )
        status_counts = Counter(
            (item.stage, item.method_kind, item.status)
            for item in package.cell_results
        )
        failure_counts = Counter(
            str(item.failure_reason)
            for item in package.cell_results
            if item.failure_reason
        )
        observed_failures.extend(sorted(failure_counts))
        retained.append(
            {
                "lineage_id": prior_root.name,
                "package_hash": package.package_hash,
                "identity_binding": {
                    "plan_hash": package.identity.plan_hash,
                    "development_panel_hash": (
                        package.identity.development_panel_hash
                    ),
                    "runner_sha256": package.identity.runner_sha256,
                    "runtime_environment_hash": (
                        package.identity.runtime_environment_hash
                    ),
                    "conditions": list(package.identity.conditions),
                },
                "selected_candidate_id": package.selected_candidate_id,
                "selection_basis": package.selection_basis,
                "selected_candidate_summary": next(
                    (
                        item.implementation_summary
                        for item in package.candidates
                        if item.candidate_id == package.selected_candidate_id
                    ),
                    None,
                ),
                "aggregate_results": {
                    "overall_median_log_effect": package.overall_median_log_effect,
                    "bootstrap_lower": package.bootstrap_lower,
                    "bootstrap_upper": package.bootstrap_upper,
                    "ode_stratum_median": package.ode_stratum_median,
                    "pde_stratum_median": package.pde_stratum_median,
                    "minimum_overall_log_effect": package.minimum_overall_log_effect,
                },
                "system_effects": [
                    item.model_dump(mode="json") for item in package.system_effects
                ],
                "gate_checks": dict(package.gate_checks),
                "search_freeze_receipt_issued": (
                    package.search_freeze_receipt_issued
                ),
                "cell_status_counts": [
                    {
                        "stage": stage,
                        "method_kind": method_kind,
                        "status": status,
                        "count": count,
                    }
                    for (stage, method_kind, status), count in sorted(
                        status_counts.items()
                    )
                ],
                "failure_reason_counts": [
                    {"failure_reason": reason, "count": count}
                    for reason, count in sorted(failure_counts.items())
                ],
            }
        )
        evidence_paths.append(package_path.resolve())
    if not retained:
        raise OfficialLineageError(
            "a system-authored research plan requires at least one prior signed "
            "lineage as evidence; pass --prior-run-dir"
        )

    policy_payload = current_boundaries.get("preregistered_baseline_policy")
    eligible_literature_systems = [
        {
            "system_name": item["system_name"],
            "data_type": item["data_type"],
        }
        for item in (
            policy_payload.get("systems", [])
            if isinstance(policy_payload, Mapping)
            else panel["systems"]
        )
        if item.get("handling", "paired_against_pinned_baseline")
        == "paired_against_pinned_baseline"
    ]
    profiles, profile_paths = profile_public_development_data(
        data_root=config.data_root,
        systems=eligible_literature_systems,
        conditions=panel["conditions"],
    )
    evidence_paths.extend(profile_paths)
    profile_payload = [item.model_dump(mode="json") for item in profiles]
    context = {
        "immutable_parent_protocol": frozen,
        "public_development_panel": panel,
        "public_development_data_profiles": profile_payload,
        "sealed_confirmation_boundary": autonomous["confirmation_commitment"],
        "current_lineage_preregistered_boundaries": current_boundaries,
        "retained_signed_prior_results": retained,
    }
    from autoresearch.competition.system_plan_opportunity_map import (
        build_research_feasibility_envelope,
        exploratory_evidence_panel_literature_view,
    )

    literature_envelope = build_research_feasibility_envelope(context)
    exploratory_evidence_panels = [
        exploratory_evidence_panel_literature_view(item)
        for item in literature_envelope.evidence_facts
        if item.fact_kind
        in {"profile_effect_association", "cross_lineage_effect_matrix"}
    ]
    literature_profile_summaries = [
        public_data_profile_evidence_view(item) for item in profiles
    ]
    literature_focus = {
        # Raw public taxonomy, deterministic public-array profiles, and exact
        # retained failure strings only.  No human or orchestrator supplies a
        # scientific framing sentence here.
        "domain": {
            "systems": eligible_literature_systems,
            "conditions": list(panel["conditions"]),
        },
        "public_data_profile_summaries": literature_profile_summaries,
        "observed_system_effects": [
            {
                "lineage_id": item.get("lineage_id"),
                "package_hash": item.get("package_hash"),
                "system_effects": item.get("system_effects") or [],
            }
            for item in retained
        ],
        "exploratory_evidence_panels": exploratory_evidence_panels,
        "observed_failures": tuple(dict.fromkeys(observed_failures)),
    }
    return context, tuple(dict.fromkeys(evidence_paths)), literature_focus


def _plan_method_task_signature(
    *,
    context: Mapping[str, Any],
    literature_focus: Mapping[str, Any],
    retrieved_catalog: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Rebuild the exact task signature bound by method-skill selection."""

    domain = literature_focus["domain"]
    return {
        "stage": "research_opportunity_mapping",
        "eligible_public_systems": domain["systems"],
        "public_conditions": domain["conditions"],
        "retained_lineage_ids": [
            item.get("lineage_id")
            for item in context["retained_signed_prior_results"]
        ],
        "available_evidence_panel_kinds": sorted(
            {
                str(item.get("fact_kind"))
                for item in literature_focus["exploratory_evidence_panels"]
                if item.get("fact_kind")
            }
        ),
        "retrieved_literature_titles": [
            item.get("title") for item in retrieved_catalog
        ],
    }


def run_plan_stage(
    config: OfficialLineageConfig,
    *,
    completion: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
) -> LineageStageReport:
    """Let the configured model survey literature and author the Chinese plan."""

    from autoresearch.agents.temporary import issue_stage_controller
    from autoresearch.competition.plan_literature_survey import (
        PlanLiteratureSurveyArtifact,
        survey_literature_for_plan,
    )
    from autoresearch.competition.research_plan_latex import guard_references
    from autoresearch.competition.system_authored_plan import author_research_plan
    from autoresearch.competition.system_plan_component_atoms import (
        run_system_plan_component_atom_catalog,
    )
    from autoresearch.competition.system_plan_ideation import run_system_plan_ideation
    from autoresearch.competition.system_plan_methodology import (
        run_system_plan_method_skill_selection,
    )
    from autoresearch.competition.system_plan_opportunity_distributed import (
        run_distributed_system_plan_opportunity_map,
    )
    from autoresearch.competition.system_plan_opportunity_map import (
        build_research_feasibility_envelope,
    )
    from autoresearch.competition.system_plan_opportunity_routing import (
        run_system_plan_opportunity_routing,
    )
    from autoresearch.competition.system_plan_preexperiment import (
        run_system_plan_preexperiment,
    )
    from autoresearch.competition.system_plan_prospective_atoms import (
        build_component_experiment_binding,
        build_prospective_execution_interface_contract,
        run_system_plan_prospective_atoms,
    )
    from autoresearch.competition.system_plan_review import (
        SystemPlanCriticalReview,
        review_system_authored_plan,
    )
    from autoresearch.literature.clients import ArxivClient, OpenAlexClient
    from autoresearch.llm.task_context import AutonomousTaskContextSession
    from autoresearch.schemas import ResearchPlan

    context_session = (
        AutonomousTaskContextSession(
            project_id=config.lineage_id,
            conversation_id=f"{config.lineage_id}-plan",
            output_dir=config.work_dir / "task-context-memory",
            completion=completion,
        )
        if completion is run_llm_json_completion
        else None
    )

    @contextmanager
    def stage_task(
        task_id: str,
    ) -> Generator[Callable[..., LLMJsonCompletionResult], None, None]:
        if context_session is None:
            yield completion
            return
        with context_session.task(task_id) as scoped_completion:
            yield scoped_completion

    context, evidence_paths, literature_focus = build_system_plan_evidence_context(
        config
    )
    references = survey_literature_for_plan(
        focus=literature_focus,
        searchers={
            "arxiv": ArxivClient().search,
            "openalex": OpenAlexClient().search,
        },
        lineage_id=config.lineage_id,
        output_dir=config.work_dir,
        require_chinese_relevance=True,
        minimum_selected=3,
    )
    reference_findings = guard_references(references)
    if reference_findings:
        raise OfficialLineageError(
            f"retrieved literature failed verifiability checks: {reference_findings}"
        )
    survey_path = config.work_dir / "plan-literature-survey.json"
    survey_artifact = PlanLiteratureSurveyArtifact.model_validate_json(
        survey_path.read_text(encoding="utf-8")
    )
    with stage_task("method-skill-selection") as stage_completion:
        method_skill_selection = run_system_plan_method_skill_selection(
            lineage_id=config.lineage_id,
            task_signature=_plan_method_task_signature(
                context=context,
                literature_focus=literature_focus,
                retrieved_catalog=survey_artifact.retrieved_catalog,
            ),
            skill_root=Path(__file__).resolve().parents[3] / "skills",
            output_dir=config.work_dir,
            completion=stage_completion,
            config_path=config_path,
            env_path=env_path,
        )
    method_skill_selection_path = (
        config.work_dir / "system-plan-method-skill-selection.json"
    )
    feasibility_envelope = build_research_feasibility_envelope(context)
    with stage_task("observed-component-atoms") as stage_completion:
        component_atoms = run_system_plan_component_atom_catalog(
            lineage_id=config.lineage_id,
            feasibility_envelope=feasibility_envelope,
            method_skill_selection=method_skill_selection.binding(),
            output_dir=config.work_dir,
            author_completion=stage_completion,
            reviewer_completion=stage_completion,
            config_path=config_path,
            env_path=env_path,
        )
    component_atoms_path = config.work_dir / "system-plan-component-atoms.json"
    prospective_interface = build_prospective_execution_interface_contract(
        feasibility_envelope
    )
    with stage_task("prospective-component-atoms") as stage_completion:
        prospective_atoms = run_system_plan_prospective_atoms(
            lineage_id=config.lineage_id,
            literature_survey=survey_artifact,
            feasibility_envelope=feasibility_envelope,
            observed_component_binding=component_atoms.binding(),
            method_skill_selection=method_skill_selection.binding(),
            interface_contract=prospective_interface,
            output_dir=config.work_dir,
            author_completion=stage_completion,
            reviewer_completion=stage_completion,
            config_path=config_path,
            env_path=env_path,
        )
    prospective_atoms_path = (
        config.work_dir / "system-plan-prospective-atoms.json"
    )
    component_experiment_binding = build_component_experiment_binding(
        component_atoms.binding(), prospective_atoms.binding()
    )
    with stage_task("opportunity-routing") as stage_completion:
        opportunity_routing = run_system_plan_opportunity_routing(
            lineage_id=config.lineage_id,
            feasibility_envelope=feasibility_envelope,
            retrieved_catalog=survey_artifact.retrieved_catalog,
            selected_references=survey_artifact.selected_references,
            component_atom_binding=component_atoms.binding(),
            output_dir=config.work_dir,
            method_skill_selection=method_skill_selection.binding(),
            completion=stage_completion,
            config_path=config_path,
            env_path=env_path,
        )
    opportunity_routing_path = (
        config.work_dir / "system-plan-opportunity-routing.json"
    )
    stage_controller, dispatch_capability = issue_stage_controller(
        lineage_id=config.lineage_id,
        stage="research-plan-opportunity-map",
        stage_attempt=1,
        controller_agent_id="stage-main-qwen-opportunity-router",
        stage_input_hash=opportunity_routing.artifact_hash,
        max_parallel_agents=7,
    )
    with stage_task("distributed-opportunity-map") as stage_completion:
        opportunity_map = run_distributed_system_plan_opportunity_map(
            routing_artifact=opportunity_routing,
            controller=stage_controller,
            capability=dispatch_capability,
            output_dir=config.work_dir,
            author_completion=stage_completion,
            reviewer_completion=stage_completion,
            config_path=config_path,
            env_path=env_path,
        )
    opportunity_map_path = (
        config.work_dir / "system-plan-opportunity-distributed.json"
    )
    with stage_task("research-ideation") as stage_completion:
        ideation = run_system_plan_ideation(
            lineage_id=config.lineage_id,
            frozen_evidence_context=context,
            opportunity_map=opportunity_map.binding(),
            component_experiment_binding=component_experiment_binding,
            literature=references,
            retrieved_catalog=survey_artifact.retrieved_catalog,
            output_dir=config.work_dir,
            completion=stage_completion,
            review_completion=stage_completion,
            prosecution_completion=stage_completion,
            config_path=config_path,
            env_path=env_path,
        )
    ideation_path = config.work_dir / "system-plan-ideation.json"
    ideation = _load_verified_ideation_artifact(
        path=ideation_path,
        output_root=config.work_dir,
        distributed=opportunity_map,
        component_experiment_binding=component_experiment_binding,
        frozen_evidence_context=context,
        literature=references,
        retrieved_catalog=survey_artifact.retrieved_catalog,
        lineage_id=config.lineage_id,
        config_path=Path("config.yaml"),
    )
    # The contest's final plan must already contain a real preliminary result.  Run
    # the narrow, result-blind baseline feasibility probe only after Qwen has selected
    # its direction, but before Qwen authors the deliverable plan.  This does not test
    # the proposed treatment and therefore cannot leak into the later paired effect.
    preexperiment_root = config.work_dir / "preexperiment"
    with stage_task("real-preliminary-experiment") as stage_completion:
        preexperiment = run_system_plan_preexperiment(
            lineage_id=config.lineage_id,
            selected_direction=ideation.selected_direction,
            component_experiment_binding=component_experiment_binding,
            frozen_plan_path=config.frozen_plan_path,
            autonomous_plan_path=config.autonomous_plan_path,
            data_root=config.data_root,
            public_panel=context["public_development_panel"],
            output_dir=preexperiment_root,
            completion=stage_completion,
            config_path=config_path,
            env_path=env_path,
        )
    preexperiment_path = preexperiment_root / "system-plan-preexperiment.json"
    if not preexperiment.limited_feasibility_supported:
        raise OfficialLineageError(
            "真实预实验没有任何成功单元，尚不能生成声称已验证有限可行性的研究计划；"
            "原始失败已完整保留，下一自主谱系应据此换方向或修订实验边界"
        )
    # The only added scientific framing is the configured model's selected direction,
    # hash-bound above.  The orchestrator still contributes no hypothesis or method.
    authoring_context = {
        **context,
        "system_audited_research_opportunity_map": {
            "artifact_hash": opportunity_map.artifact_hash,
            "accepted_cells": [
                item.model_dump(mode="json")
                for item in opportunity_map.accepted_cells
            ],
        },
        "system_selected_method_skills": method_skill_selection.binding().model_dump(
            mode="json"
        ),
        "system_component_atom_catalog": component_atoms.binding().model_dump(
            mode="json"
        ),
        "system_prospective_component_atoms": prospective_atoms.binding().model_dump(
            mode="json"
        ),
        "system_component_experiment_binding": (
            component_experiment_binding.model_dump(mode="json")
        ),
        "system_selected_research_direction": ideation.selected_direction.model_dump(
            mode="json"
        ),
        "system_selected_research_direction_hash": (
            ideation.selected_direction_hash
        ),
        "system_plan_ideation_artifact_hash": ideation.artifact_hash,
        "system_preliminary_experiment": preexperiment.plan_context(),
    }

    with stage_task("research-plan-authoring") as stage_completion:

        def critical_review(candidate_plan: ResearchPlan, attempt: int) -> Sequence[str]:
            review = review_system_authored_plan(
                lineage_id=config.lineage_id,
                plan=candidate_plan,
                plan_hash=canonical_model_hash(candidate_plan.model_dump(mode="json")),
                literature_survey=survey_artifact.model_dump(mode="json"),
                frozen_evidence_context=authoring_context,
                authoring_attempt=attempt,
                output_dir=config.work_dir,
                completion=stage_completion,
                config_path=config_path,
                env_path=env_path,
            )
            return review.assessment.repair_findings()

        artifact = author_research_plan(
            lineage_id=config.lineage_id,
            project_id=config.lineage_id,
            candidate_id=f"candidate_{ideation.selected_direction_hash[:12]}",
            frozen_context=authoring_context,
            evidence_paths=(
                *evidence_paths,
                survey_path,
                method_skill_selection_path,
                component_atoms_path,
                prospective_atoms_path,
                opportunity_routing_path,
                opportunity_map_path,
                ideation_path,
                preexperiment_path,
            ),
            output_dir=config.work_dir,
            completion=stage_completion,
            config_path=config_path,
            env_path=env_path,
            container_entry_points=("/harness/runner.py",),
            literature=references,
            require_chinese=True,
            scientific_review=critical_review,
        )
    plan = ResearchPlan.model_validate(artifact.plan)
    critical_review_path = config.work_dir / "system-plan-critical-review.json"
    accepted_review = SystemPlanCriticalReview.model_validate_json(
        critical_review_path.read_text(encoding="utf-8")
    )
    if (
        accepted_review.plan_hash != artifact.plan_hash
        or not accepted_review.assessment.ready_for_human_scope_review
    ):
        raise OfficialLineageError(
            "accepted critical review does not bind the final system-authored plan"
        )
    config.plan_dir.mkdir(parents=True, exist_ok=True)
    write_json_model(config.plan_dir / "research-plan.json", plan)
    return LineageStageReport(
        lineage_id=config.lineage_id,
        stage="plan",
        lines=(
            "=== STAGE plan: system-authored Chinese preregistration",
            f"  model          : {artifact.model_name}",
            f"  author attempts: {artifact.authoring_attempts}",
            f"  plan hash      : {artifact.plan_hash}",
            f"  literature     : {len(references)} real retrieved references",
            f"  component atoms: {component_atoms.artifact_hash}",
            f"  prospective atoms: {prospective_atoms.artifact_hash}",
            f"  main-Qwen route: {opportunity_routing.artifact_hash}",
            f"  opportunity map: {opportunity_map.artifact_hash}",
            "  temporary agents: 7 authors + 7 independent reviewers archived",
            f"  ideation       : {ideation.artifact_hash}",
            f"  preexperiment : {preexperiment.artifact_hash}",
            f"  preliminary cells: {len(preexperiment.cell_evidence)} actual sandbox runs",
            "  preliminary scope: baseline feasibility only; treatment effect unmeasured",
            f"  critical review: {accepted_review.review_hash}",
            "  abstract direct-copy check: passed; publication novelty unverified",
            f"  quality score  : {artifact.guard_report.quality_gate_score}",
            f"  title           : {plan.title}",
            "  hand-written scientific prose fields: 0",
            "  execution BLOCKED until a human approves this exact plan hash",
        ),
    )


@dataclass(frozen=True)
class _RetainedPlanRoutingSnapshot:
    """Strictly revalidated immutable inputs for a routing-bound plan resume."""

    context: dict[str, Any]
    evidence_paths: tuple[Path, ...]
    literature_focus: dict[str, Any]
    survey: Any
    method_skill_selection: Any
    component_atoms: Any
    prospective_atoms: Any
    opportunity_routing: Any
    survey_path: Path
    method_skill_selection_path: Path
    component_atoms_path: Path
    prospective_atoms_path: Path
    opportunity_routing_path: Path


def _require_path_inside(root: Path, path: Path, *, label: str) -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise OfficialLineageError(f"{label} escapes its retained artifact root") from exc
    return resolved


def _require_artifact_output_path(
    *, artifact: Any, artifact_path: Path, label: str
) -> None:
    recorded = getattr(artifact, "output_path", None)
    if recorded is None or Path(str(recorded)).resolve() != artifact_path.resolve():
        raise OfficialLineageError(
            f"retained {label} output path is not its canonical lineage path"
        )


def _require_model_receipt(
    *,
    output_root: Path,
    relative_path: str,
    expected_hash: str,
    label: str,
) -> None:
    from autoresearch.competition.model_authorship import ModelAuthorshipReceipt

    receipt_path = _require_path_inside(
        output_root, output_root / relative_path, label=label
    )
    if not receipt_path.is_file():
        raise OfficialLineageError(f"retained {label} receipt is missing: {receipt_path}")
    receipt = ModelAuthorshipReceipt.model_validate_json(
        receipt_path.read_text(encoding="utf-8")
    )
    if (
        receipt.receipt_hash != expected_hash
        or Path(receipt.output_path).resolve() != receipt_path
    ):
        raise OfficialLineageError(
            f"retained {label} receipt hash or canonical path mismatch"
        )


def _validate_retained_plan_routing_chain(
    *,
    lineage_id: str,
    context: Mapping[str, Any],
    literature_focus: Mapping[str, Any],
    feasibility_envelope: Any,
    survey: Any,
    method_skill_selection: Any,
    component_atoms: Any,
    prospective_atoms: Any,
    opportunity_routing: Any,
) -> None:
    """Fail closed unless the retained artifacts form one exact hash chain."""

    artifacts = (
        survey,
        method_skill_selection,
        component_atoms,
        prospective_atoms,
        opportunity_routing,
    )
    if any(getattr(item, "lineage_id", None) != lineage_id for item in artifacts):
        raise OfficialLineageError(
            "retained plan reasoning belongs to a different lineage"
        )
    if survey.focus_sha256 != canonical_model_hash(dict(literature_focus)):
        raise OfficialLineageError(
            "retained literature survey is not bound to the rebuilt literature focus"
        )
    expected_task_signature = _plan_method_task_signature(
        context=context,
        literature_focus=literature_focus,
        retrieved_catalog=survey.retrieved_catalog,
    )
    if (
        method_skill_selection.task_signature != expected_task_signature
        or method_skill_selection.task_signature_hash
        != canonical_model_hash(expected_task_signature)
    ):
        raise OfficialLineageError(
            "retained method skill selection is not bound to this lineage task"
        )
    method_binding = method_skill_selection.binding()
    component_binding = component_atoms.binding()
    prospective_atoms.binding()
    if (
        component_atoms.feasibility_envelope != feasibility_envelope
        or component_atoms.method_skill_selection != method_binding
        or prospective_atoms.literature_survey != survey
        or prospective_atoms.feasibility_envelope != feasibility_envelope
        or prospective_atoms.observed_component_binding != component_binding
        or prospective_atoms.method_skill_selection != method_binding
        or opportunity_routing.feasibility_envelope != feasibility_envelope
        or opportunity_routing.component_atom_binding != component_binding
        or opportunity_routing.method_skill_selection != method_binding
        or opportunity_routing.source_catalog_hash
        != canonical_model_hash(
            {
                "retrieved_catalog": [
                    dict(item) for item in survey.retrieved_catalog
                ]
            }
        )
        or opportunity_routing.selected_references_hash
        != canonical_model_hash(
            {
                "selected_references": [
                    dict(item) for item in survey.selected_references
                ]
            }
        )
    ):
        raise OfficialLineageError(
            "retained routing hash chain does not bind the rebuilt evidence, "
            "survey, method skills, observed/prospective components, and routing"
        )
    # Materializing both bindings above reruns their own hash validators. The full
    # typed ComponentExperimentBindingV2 is then constructed by the caller before
    # any downstream model receives these retained inputs.
    # This materializes every routed worker input and reruns the routing model's
    # own deterministic evidence, literature, component, and ordering validators.
    opportunity_routing.worker_bindings()


def _load_retained_plan_routing_snapshot(
    config: OfficialLineageConfig,
) -> _RetainedPlanRoutingSnapshot:
    from autoresearch.competition.plan_literature_survey import (
        PlanLiteratureSurveyArtifact,
    )
    from autoresearch.competition.system_plan_component_atoms import (
        SystemPlanComponentAtomArtifact,
    )
    from autoresearch.competition.system_plan_methodology import (
        SystemPlanMethodSkillSelectionArtifact,
    )
    from autoresearch.competition.system_plan_opportunity_map import (
        build_research_feasibility_envelope,
    )
    from autoresearch.competition.system_plan_opportunity_routing import (
        SystemPlanOpportunityRoutingArtifact,
    )
    from autoresearch.competition.system_plan_prospective_atoms import (
        SystemPlanProspectiveAtomArtifact,
    )

    survey_path = config.work_dir / "plan-literature-survey.json"
    method_path = config.work_dir / "system-plan-method-skill-selection.json"
    component_path = config.work_dir / "system-plan-component-atoms.json"
    prospective_path = config.work_dir / "system-plan-prospective-atoms.json"
    routing_path = config.work_dir / "system-plan-opportunity-routing.json"
    required = (
        survey_path,
        method_path,
        component_path,
        prospective_path,
        routing_path,
    )
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        raise OfficialLineageError(
            f"retained plan reasoning is missing required artifacts: {missing}"
        )

    try:
        context, evidence_paths, literature_focus = (
            build_system_plan_evidence_context(config)
        )
        survey = PlanLiteratureSurveyArtifact.model_validate_json(
            survey_path.read_text(encoding="utf-8")
        )
        method = SystemPlanMethodSkillSelectionArtifact.model_validate_json(
            method_path.read_text(encoding="utf-8")
        )
        component = SystemPlanComponentAtomArtifact.model_validate_json(
            component_path.read_text(encoding="utf-8")
        )
        prospective = SystemPlanProspectiveAtomArtifact.model_validate_json(
            prospective_path.read_text(encoding="utf-8")
        )
        routing = SystemPlanOpportunityRoutingArtifact.model_validate_json(
            routing_path.read_text(encoding="utf-8")
        )
        envelope = build_research_feasibility_envelope(context)
    except (OSError, RuntimeError, ValueError) as exc:
        raise OfficialLineageError(
            f"retained plan reasoning could not be strictly revalidated: {exc}"
        ) from exc

    for artifact, path, label in (
        (survey, survey_path, "literature survey"),
        (method, method_path, "method skill selection"),
        (component, component_path, "component atoms"),
        (prospective, prospective_path, "prospective component atoms"),
        (routing, routing_path, "opportunity routing"),
    ):
        _require_artifact_output_path(
            artifact=artifact, artifact_path=path, label=label
        )
    _validate_retained_plan_routing_chain(
        lineage_id=config.lineage_id,
        context=context,
        literature_focus=literature_focus,
        feasibility_envelope=envelope,
        survey=survey,
        method_skill_selection=method,
        component_atoms=component,
        prospective_atoms=prospective,
        opportunity_routing=routing,
    )
    _require_model_receipt(
        output_root=config.work_dir,
        relative_path=survey.query_authorship_receipt_relative_path,
        expected_hash=survey.query_authorship_receipt_hash,
        label="literature query authorship",
    )
    _require_model_receipt(
        output_root=config.work_dir,
        relative_path=survey.selection_authorship_receipt_relative_path,
        expected_hash=survey.selection_authorship_receipt_hash,
        label="literature selection authorship",
    )
    _require_model_receipt(
        output_root=config.work_dir,
        relative_path=method.authorship_receipt_relative_path,
        expected_hash=method.authorship_receipt_hash,
        label="method skill authorship",
    )
    for round_item in component.rounds:
        _require_model_receipt(
            output_root=config.work_dir,
            relative_path=round_item.author_receipt_relative_path,
            expected_hash=round_item.author_receipt.receipt_hash,
            label=f"component author round {round_item.round_index}",
        )
        _require_model_receipt(
            output_root=config.work_dir,
            relative_path=round_item.reviewer_receipt_relative_path,
            expected_hash=round_item.reviewer_receipt.receipt_hash,
            label=f"component reviewer round {round_item.round_index}",
        )
    _require_model_receipt(
        output_root=config.work_dir,
        relative_path=routing.provider_receipt_relative_path,
        expected_hash=routing.provider_receipt.receipt_hash,
        label="opportunity routing authorship",
    )
    return _RetainedPlanRoutingSnapshot(
        context=context,
        evidence_paths=evidence_paths,
        literature_focus=literature_focus,
        survey=survey,
        method_skill_selection=method,
        component_atoms=component,
        prospective_atoms=prospective,
        opportunity_routing=routing,
        survey_path=survey_path,
        method_skill_selection_path=method_path,
        component_atoms_path=component_path,
        prospective_atoms_path=prospective_path,
        opportunity_routing_path=routing_path,
    )


def _validate_plan_resume_layout(
    *, config: OfficialLineageConfig, output_root: Path
) -> None:
    lineage_root = config.work_dir.resolve()
    if output_root == lineage_root:
        raise OfficialLineageError(
            "routing resume must use a fresh receipt directory inside the lineage"
        )
    _require_path_inside(lineage_root, output_root, label="plan resume directory")
    if not output_root.exists():
        return
    if not output_root.is_dir():
        raise OfficialLineageError("plan resume output path is not a directory")
    allowed = {
        _PLAN_RESUME_DISTRIBUTED_DIR,
        _PLAN_RESUME_IDEATION_DIR,
        _PLAN_RESUME_PREEXPERIMENT_DIR,
        _PLAN_RESUME_AUTHORING_DIR,
        _PLAN_RESUME_MANIFEST_NAME,
        "task-context-memory",
    }
    unexpected = sorted(item.name for item in output_root.iterdir() if item.name not in allowed)
    if unexpected:
        raise OfficialLineageError(
            "plan resume directory is not a fresh or valid partial receipt "
            f"directory; unexpected entries: {unexpected}"
        )
    for directory_name, artifact_name in (
        (
            _PLAN_RESUME_DISTRIBUTED_DIR,
            "system-plan-opportunity-distributed.json",
        ),
        (_PLAN_RESUME_IDEATION_DIR, "system-plan-ideation.json"),
        (
            _PLAN_RESUME_PREEXPERIMENT_DIR,
            "system-plan-preexperiment.json",
        ),
    ):
        stage_root = output_root / directory_name
        if stage_root.exists() and (
            not stage_root.is_dir() or not (stage_root / artifact_name).is_file()
        ):
            raise OfficialLineageError(
                "plan resume directory is not a fresh or valid partial receipt "
                f"directory; {directory_name} is incomplete"
            )
    authoring_root = output_root / _PLAN_RESUME_AUTHORING_DIR
    if authoring_root.exists() and any(authoring_root.iterdir()):
        raise OfficialLineageError(
            "resumed authoring receipts or a system-authored plan already exist; "
            "refusing to overwrite reasoning artifacts"
        )
    if (output_root / _PLAN_RESUME_MANIFEST_NAME).exists():
        raise OfficialLineageError(
            "a completed plan resume manifest already exists; refusing to overwrite it"
        )


def _load_relative_model(
    *, output_root: Path, relative_path: str, model_type: Any, label: str
) -> Any:
    path = _require_path_inside(
        output_root, output_root / relative_path, label=label
    )
    if not path.is_file():
        raise OfficialLineageError(f"retained {label} is missing: {path}")
    try:
        return model_type.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, RuntimeError, ValueError) as exc:
        raise OfficialLineageError(f"retained {label} is invalid: {exc}") from exc


def _verify_distributed_supporting_files(
    *, output_root: Path, artifact: Any
) -> None:
    from autoresearch.agents.temporary import (
        TemporaryAgentArchiveRecord,
        TemporaryAgentAssignment,
        TemporaryAgentBatchManifest,
        TemporaryAgentResultArtifact,
    )
    from autoresearch.competition.model_authorship import ModelAuthorshipReceipt
    from autoresearch.competition.temporary_qwen_pool import (
        TemporaryQwenBatchArtifact,
        TemporaryQwenPhaseManifest,
        TemporaryQwenTaskRecord,
    )

    for phase, embedded_batch, phase_label in (
        (artifact.author_phase_manifest, artifact.author_batch, "author"),
        (artifact.reviewer_phase_manifest, artifact.reviewer_batch, "reviewer"),
    ):
        loaded_phase = _load_relative_model(
            output_root=output_root,
            relative_path=phase.output_relative_path,
            model_type=TemporaryQwenPhaseManifest,
            label=f"distributed {phase_label} phase manifest",
        )
        if loaded_phase != phase:
            raise OfficialLineageError(
                f"retained distributed {phase_label} phase manifest differs from artifact"
            )
        loaded_batch = _load_relative_model(
            output_root=output_root,
            relative_path=embedded_batch.output_relative_path,
            model_type=TemporaryQwenBatchArtifact,
            label=f"distributed {phase_label} batch artifact",
        )
        if loaded_batch != embedded_batch:
            raise OfficialLineageError(
                f"retained distributed {phase_label} batch differs from artifact"
            )
        manifest = _load_relative_model(
            output_root=output_root,
            relative_path=embedded_batch.manifest_relative_path,
            model_type=TemporaryAgentBatchManifest,
            label=f"distributed {phase_label} batch manifest",
        )
        if (
            manifest.batch_hash != embedded_batch.manifest_hash
            or manifest.stable_merged_output_sha256
            != embedded_batch.manifest_stable_merged_output_sha256
        ):
            raise OfficialLineageError(
                f"retained distributed {phase_label} manifest hash mismatch"
            )
        manifest_entries = {item.dispatch_id: item for item in manifest.entries}
        stable_outputs = {
            item.dispatch_id: item for item in embedded_batch.stable_outputs
        }
        for record in embedded_batch.task_records:
            entry = manifest_entries.get(record.dispatch_id)
            stable_output = stable_outputs.get(record.dispatch_id)
            if (
                entry is None
                or stable_output is None
                or entry.temporary_agent_id != record.temporary_agent_id
                or entry.assignment_hash != record.assignment_hash
                or entry.result_hash != record.result_hash
                or entry.archive_hash != record.archive_hash
                or entry.output_payload_sha256
                != stable_output.output_payload_sha256
            ):
                raise OfficialLineageError(
                    f"temporary manifest/task binding mismatch: {record.dispatch_id}"
                )
            loaded_record = _load_relative_model(
                output_root=output_root,
                relative_path=record.record_relative_path,
                model_type=TemporaryQwenTaskRecord,
                label=f"temporary task record {record.dispatch_id}",
            )
            if loaded_record != record:
                raise OfficialLineageError(
                    f"temporary task record {record.dispatch_id} differs from batch"
                )
            assignment = _load_relative_model(
                output_root=output_root,
                relative_path=record.assignment_relative_path,
                model_type=TemporaryAgentAssignment,
                label=f"temporary assignment {record.dispatch_id}",
            )
            archive = _load_relative_model(
                output_root=output_root,
                relative_path=record.archive_relative_path,
                model_type=TemporaryAgentArchiveRecord,
                label=f"temporary archive {record.dispatch_id}",
            )
            if (
                assignment.assignment_hash != record.assignment_hash
                or assignment.dispatch_id != record.dispatch_id
                or assignment.temporary_agent_id != record.temporary_agent_id
                or archive.archive_hash != record.archive_hash
                or archive.dispatch_id != record.dispatch_id
                or archive.temporary_agent_id != record.temporary_agent_id
                or archive.assignment_hash != record.assignment_hash
                or archive.result_hash != record.result_hash
            ):
                raise OfficialLineageError(
                    f"temporary assignment/archive hash mismatch: {record.dispatch_id}"
                )
            if (
                record.result_relative_path is None
                or record.authorship_receipt_relative_path is None
                or record.result_hash is None
                or record.authorship_receipt_hash is None
            ):
                raise OfficialLineageError(
                    f"successful distributed task lacks retained output: {record.dispatch_id}"
                )
            result = _load_relative_model(
                output_root=output_root,
                relative_path=record.result_relative_path,
                model_type=TemporaryAgentResultArtifact,
                label=f"temporary result {record.dispatch_id}",
            )
            receipt = _load_relative_model(
                output_root=output_root,
                relative_path=record.authorship_receipt_relative_path,
                model_type=ModelAuthorshipReceipt,
                label=f"temporary model receipt {record.dispatch_id}",
            )
            if (
                result.result_hash != record.result_hash
                or result.dispatch_id != record.dispatch_id
                or result.temporary_agent_id != record.temporary_agent_id
                or result.assignment_hash != record.assignment_hash
                or result.authorship_receipt_hash != record.authorship_receipt_hash
                or result.authorship_receipt_relative_path
                != record.authorship_receipt_relative_path
                or receipt.receipt_hash != record.authorship_receipt_hash
                or Path(receipt.output_path).resolve()
                != (output_root / record.authorship_receipt_relative_path).resolve()
            ):
                raise OfficialLineageError(
                    f"temporary result/receipt hash mismatch: {record.dispatch_id}"
                )


def _load_verified_distributed_artifact(
    *,
    path: Path,
    output_root: Path,
    snapshot: _RetainedPlanRoutingSnapshot,
    lineage_id: str,
) -> Any:
    from autoresearch.competition.system_plan_opportunity_distributed import (
        DistributedSystemPlanOpportunityMapArtifact,
    )

    try:
        artifact = DistributedSystemPlanOpportunityMapArtifact.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise OfficialLineageError(
            f"retained distributed opportunity artifact is invalid: {exc}"
        ) from exc
    if (
        artifact.lineage_id != lineage_id
        or artifact.routing_artifact_hash
        != snapshot.opportunity_routing.artifact_hash
        or artifact.routing_context_hash
        != snapshot.opportunity_routing.compact_routing_context.context_hash
        or artifact.feasibility_envelope
        != snapshot.opportunity_routing.feasibility_envelope
        or artifact.method_skill_selection
        != snapshot.method_skill_selection.binding()
    ):
        raise OfficialLineageError(
            "retained distributed artifact has a cross-lineage or routing hash mismatch"
        )
    artifact.binding()
    _verify_distributed_supporting_files(output_root=output_root, artifact=artifact)
    return artifact


def _configured_llm_identity(config_path: Path | str) -> tuple[str, str, str]:
    """Read the provider endpoint and model that an official model call must use."""

    from autoresearch.config import ConfigParser, SystemConfig

    parsed = ConfigParser().parse_file(config_path, model_type=SystemConfig)
    if not isinstance(parsed, SystemConfig):
        raise OfficialLineageError("configured model file did not parse as SystemConfig")
    configured = parsed.deployment.llm
    return (
        configured.provider,
        configured.base_url.rstrip("/"),
        configured.model_name,
    )


def _load_exact_ideation_receipt(
    *,
    output_root: Path,
    relative_path: str,
    expected_hash: str,
    artifact_kind: str,
    interaction_prefix: str,
    outer_attempt: int,
    expected_model_name: str,
    expected_model_identity: tuple[str, str, str],
    expected_parsed_payload: Mapping[str, Any],
    expected_input_fields: Mapping[str, Any],
    expected_method_skill_selection: Any,
    label: str,
) -> Any:
    """Replay one retained ideation receipt instead of trusting its self-hash.

    A receipt is only provenance when the recorded model saw the exact scientific
    inputs and returned the exact accepted object.  Recomputing a SHA-256 after
    replacing both sides is not authorship evidence, so every semantic binding is
    compared here in addition to the receipt model's internal hashes.
    """

    from autoresearch.competition.model_authorship import ModelAuthorshipReceipt
    from autoresearch.competition.system_plan_ideation import (
        _method_skill_selection_from_receipt,
    )
    from autoresearch.llm.client import _parse_json_completion_content

    receipt_path = _require_path_inside(
        output_root,
        output_root / relative_path,
        label=label,
    )
    if not receipt_path.is_file():
        raise OfficialLineageError(f"retained {label} receipt is missing: {receipt_path}")
    try:
        receipt = ModelAuthorshipReceipt.model_validate_json(
            receipt_path.read_text(encoding="utf-8")
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise OfficialLineageError(f"retained {label} receipt is invalid: {exc}") from exc
    if (
        receipt.receipt_hash != expected_hash
        or Path(receipt.output_path).resolve() != receipt_path
    ):
        raise OfficialLineageError(
            f"retained {label} receipt hash or canonical path mismatch"
        )
    if receipt.artifact_kind != artifact_kind:
        raise OfficialLineageError(f"retained {label} receipt has the wrong artifact kind")
    match = re.fullmatch(
        rf"{re.escape(interaction_prefix)}-{outer_attempt:02d}"
        r"(?:-repair-(?P<repair>[0-9]{2}))?",
        receipt.interaction_id,
    )
    expected_inner_attempt = int(match.group("repair")) if match and match.group("repair") else 1
    if match is None or receipt.attempt != expected_inner_attempt:
        raise OfficialLineageError(
            f"retained {label} interaction id or repair attempt is inconsistent"
        )
    if receipt.model_name != expected_model_name:
        raise OfficialLineageError(
            f"retained {label} model name differs from the ideation artifact"
        )
    configured_provider, configured_base_url, configured_model = expected_model_identity
    if (
        receipt.provider != configured_provider
        or receipt.base_url.rstrip("/") != configured_base_url
        or receipt.model_name != configured_model
        or "qwen" not in receipt.model_name.casefold()
    ):
        raise OfficialLineageError(
            f"retained {label} model identity differs from the configured Qwen model"
        )
    if (
        receipt.reasoning_transport == "absent"
        or len(str(receipt.reasoning_content or "").strip()) < 200
    ):
        raise OfficialLineageError(
            f"retained {label} lacks the required auditable Qwen reasoning"
        )
    try:
        parsed_response, normalization, normalization_suffix = (
            _parse_json_completion_content(receipt.response_text)
        )
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise OfficialLineageError(
            f"retained {label} raw response cannot be replayed: {exc}"
        ) from exc
    if (
        parsed_response != receipt.parsed_payload
        or normalization != receipt.transport_normalization
        or normalization_suffix != receipt.normalization_suffix
        or receipt.parsed_payload != dict(expected_parsed_payload)
    ):
        raise OfficialLineageError(
            f"retained {label} response, parsed payload, or accepted object differs"
        )
    try:
        receipt_skill_selection = _method_skill_selection_from_receipt(receipt)
    except (RuntimeError, ValueError) as exc:
        raise OfficialLineageError(
            f"retained {label} method-skill message is invalid: {exc}"
        ) from exc
    if receipt_skill_selection != expected_method_skill_selection:
        raise OfficialLineageError(
            f"retained {label} did not receive the exact selected project skill"
        )

    matching_inputs: list[Mapping[str, Any]] = []
    for message in receipt.messages:
        if message.get("role") != "user":
            continue
        try:
            payload = json.loads(message.get("content", ""))
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(payload, Mapping):
            continue
        if all(payload.get(key) == value for key, value in expected_input_fields.items()):
            matching_inputs.append(payload)
    if len(matching_inputs) != 1:
        raise OfficialLineageError(
            f"retained {label} does not contain exactly one full hash-bound scientific input"
        )
    return receipt


def _load_verified_ideation_artifact(
    *,
    path: Path,
    output_root: Path,
    distributed: Any,
    component_experiment_binding: Any,
    frozen_evidence_context: Mapping[str, Any],
    literature: Sequence[Mapping[str, Any]],
    retrieved_catalog: Sequence[Mapping[str, Any]],
    lineage_id: str,
    config_path: Path | str = Path("config.yaml"),
) -> Any:
    from autoresearch.competition.system_plan_ideation import (
        SystemPlanIdeationArtifact,
        _catalog_payload_for_portfolio,
        _catalog_payload_for_review,
        _component_experiment_binding_findings,
        _literature_identity_map,
        _prospective_direction_allowlist,
        _prospective_direction_binding_findings,
        _selected_literature_payload,
    )

    try:
        artifact = SystemPlanIdeationArtifact.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise OfficialLineageError(
            f"retained plan ideation artifact is invalid: {exc}"
        ) from exc
    _require_artifact_output_path(
        artifact=artifact, artifact_path=path, label="plan ideation"
    )
    if (
        artifact.lineage_id != lineage_id
        or artifact.opportunity_map_hash != distributed.artifact_hash
        or artifact.component_experiment_binding != component_experiment_binding
        or artifact.component_experiment_binding_hash
        != component_experiment_binding.binding_hash
    ):
        raise OfficialLineageError(
            "retained ideation has a cross-lineage, distributed, or prospective "
            "component binding mismatch"
        )
    opportunity_binding = distributed.binding()
    try:
        literature_identity_map = _literature_identity_map(
            literature=literature,
            retrieved_catalog=retrieved_catalog,
        )
        component_findings = _component_experiment_binding_findings(
            component_experiment_binding=component_experiment_binding,
            opportunity_map=opportunity_binding,
            literature_identity_map=literature_identity_map,
            retrieved_catalog=retrieved_catalog,
        )
    except (RuntimeError, ValueError) as exc:
        raise OfficialLineageError(
            f"retained ideation source identities cannot be replayed: {exc}"
        ) from exc
    if component_findings:
        raise OfficialLineageError(
            "retained ideation component experiment no longer matches its survey, "
            "facts, or opportunity inputs: " + "；".join(component_findings)
        )
    selected_to_retrieved_reference = {
        int(item["selected_reference_index"]): int(
            item["retrieved_catalog_reference_index"]
        )
        for item in literature_identity_map
    }
    accepted_cell_ids = {item.cell_id for item in opportunity_binding.accepted_cells}
    bound_cell_ids = {
        item.opportunity_cell_id for item in artifact.portfolio.directions
    }
    direction_findings: list[str] = []
    if len(accepted_cell_ids) >= 5:
        if len(bound_cell_ids) != 5 or not bound_cell_ids.issubset(accepted_cell_ids):
            direction_findings.append(
                "存在至少五个合格机会时，五个方向必须绑定五个不同且已接受的机会格"
            )
    elif bound_cell_ids != accepted_cell_ids:
        direction_findings.append(
            "合格机会少于五个时，方向组合没有覆盖全部已接受机会格"
        )
    eligible_systems = {
        item.system_name
        for item in opportunity_binding.feasibility_envelope.eligible_systems
    }
    evidence_fact_ids = {
        item.fact_id for item in opportunity_binding.feasibility_envelope.evidence_facts
    }
    for index, direction in enumerate(artifact.portfolio.directions, 1):
        if direction.opportunity_cell_id not in accepted_cell_ids:
            direction_findings.append(
                f"方向{index}引用了未接受机会格 {direction.opportunity_cell_id}"
            )
        direction_findings.extend(
            f"方向{index}：{finding}"
            for finding in _prospective_direction_binding_findings(
                direction=direction,
                component_experiment_binding=component_experiment_binding,
                selected_to_retrieved_reference=selected_to_retrieved_reference,
                eligible_systems=eligible_systems,
                evidence_fact_ids=evidence_fact_ids,
            )
        )
    if direction_findings:
        raise OfficialLineageError(
            "retained ideation no longer exactly inherits its prospective atom: "
            + "；".join(direction_findings)
        )

    common_input_fields = {
        "research_opportunity_map_hash": distributed.artifact_hash,
        "component_experiment_binding": component_experiment_binding.model_dump(
            mode="json"
        ),
        "component_experiment_binding_hash": component_experiment_binding.binding_hash,
        "selected_to_retrieved_literature_identity_map": list(
            literature_identity_map
        ),
    }
    accepted_cells_payload = [
        item.model_dump(mode="json") for item in opportunity_binding.accepted_cells
    ]
    envelope_payload = opportunity_binding.feasibility_envelope.model_dump(mode="json")
    configured_identity = _configured_llm_identity(config_path)
    method_skill_selection = opportunity_binding.method_skill_selection
    _load_exact_ideation_receipt(
        output_root=output_root,
        relative_path=artifact.portfolio_authorship_receipt_relative_path,
        expected_hash=artifact.portfolio_authorship_receipt_hash,
        artifact_kind="plan_ideation",
        interaction_prefix="system-plan-ideation-attempt",
        outer_attempt=artifact.authoring_attempt,
        expected_model_name=artifact.portfolio_model_name,
        expected_model_identity=configured_identity,
        expected_parsed_payload=artifact.portfolio.model_dump(mode="json"),
        expected_input_fields={
            **common_input_fields,
            "frozen_evidence_context_hash": canonical_model_hash(
                dict(frozen_evidence_context)
            ),
            "independently_accepted_research_opportunities": accepted_cells_payload,
            "frozen_feasibility_envelope": envelope_payload,
            "selected_literature_for_plan_citations": _selected_literature_payload(
                literature,
                retrieved_catalog,
            ),
            "prospective_direction_allowlist": _prospective_direction_allowlist(
                component_experiment_binding=component_experiment_binding,
                selected_to_retrieved_reference=selected_to_retrieved_reference,
            ),
            "retrieved_prior_work_catalog": _catalog_payload_for_portfolio(
                retrieved_catalog
            ),
        },
        expected_method_skill_selection=method_skill_selection,
        label="ideation portfolio",
    )
    _load_exact_ideation_receipt(
        output_root=output_root,
        relative_path=artifact.review_authorship_receipt_relative_path,
        expected_hash=artifact.review_authorship_receipt_hash,
        artifact_kind="plan_ideation_review",
        interaction_prefix="system-plan-ideation-review-attempt",
        outer_attempt=artifact.authoring_attempt,
        expected_model_name=artifact.review_model_name,
        expected_model_identity=configured_identity,
        expected_parsed_payload=artifact.decision.model_dump(mode="json"),
        expected_input_fields={
            **common_input_fields,
            "portfolio": artifact.portfolio.model_dump(mode="json"),
            "accepted_research_opportunities": accepted_cells_payload,
            "frozen_feasibility_envelope": envelope_payload,
            "retrieved_catalog": _catalog_payload_for_review(retrieved_catalog),
        },
        expected_method_skill_selection=method_skill_selection,
        label="ideation review",
    )
    _load_exact_ideation_receipt(
        output_root=output_root,
        relative_path=artifact.prosecution_authorship_receipt_relative_path,
        expected_hash=artifact.prosecution_authorship_receipt_hash,
        artifact_kind="plan_ideation_prosecution",
        interaction_prefix="system-plan-ideation-prosecution-attempt",
        outer_attempt=artifact.authoring_attempt,
        expected_model_name=artifact.prosecution_model_name,
        expected_model_identity=configured_identity,
        expected_parsed_payload=artifact.prosecution.model_dump(mode="json"),
        expected_input_fields={
            **common_input_fields,
            "selected_direction_index": artifact.decision.selected_direction_index,
            "selected_direction": artifact.selected_direction.model_dump(mode="json"),
            "tournament_decision": artifact.decision.model_dump(mode="json"),
            "accepted_research_opportunities": accepted_cells_payload,
            "frozen_feasibility_envelope": envelope_payload,
            "retrieved_catalog": _catalog_payload_for_review(retrieved_catalog),
        },
        expected_method_skill_selection=method_skill_selection,
        label="ideation prosecution",
    )
    return artifact


def _write_once_json(path: Path, payload: Any) -> None:
    """Write canonical JSON exactly once; never replace prior provenance."""

    dumped = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
    rendered = json.dumps(dumped, ensure_ascii=False, indent=2, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
    except FileExistsError as exc:
        raise OfficialLineageError(
            f"immutable plan resume artifact already exists: {path}"
        ) from exc


def _promote_resumed_plan_artifact(
    *, config: OfficialLineageConfig, authoring_root: Path, artifact: Any
) -> Any:
    """Create the root canonical plan artifact while retaining nested receipts."""

    from autoresearch.competition.system_authored_plan import SystemAuthoredPlanArtifact

    if artifact.authorship_receipt_relative_path is None:
        raise OfficialLineageError("resumed plan cannot be promoted without a receipt")
    lineage_root = config.work_dir.resolve()
    receipt_path = _require_path_inside(
        authoring_root,
        authoring_root / artifact.authorship_receipt_relative_path,
        label="resumed plan authorship receipt",
    )
    root_relative_receipt = receipt_path.relative_to(lineage_root).as_posix()
    canonical_path = lineage_root / _SYSTEM_AUTHORED_PLAN_NAME
    payload = artifact.model_dump(
        mode="json", exclude={"artifact_hash", "output_path"}
    )
    payload["authorship_receipt_relative_path"] = root_relative_receipt
    payload["artifact_hash"] = canonical_model_hash(payload)
    payload["output_path"] = canonical_path.as_posix()
    canonical = SystemAuthoredPlanArtifact.model_validate(payload)
    _write_once_json(canonical_path, canonical)
    persisted = SystemAuthoredPlanArtifact.model_validate_json(
        canonical_path.read_text(encoding="utf-8")
    )
    if persisted != canonical:
        raise OfficialLineageError(
            "root canonical plan artifact differs from its hash-bound promotion"
        )
    _require_model_receipt(
        output_root=lineage_root,
        relative_path=root_relative_receipt,
        expected_hash=str(canonical.authorship_receipt_hash),
        label="root canonical plan authorship",
    )
    return persisted


def _same_retained_routing_snapshot(
    left: _RetainedPlanRoutingSnapshot, right: _RetainedPlanRoutingSnapshot
) -> bool:
    return (
        left.survey.survey_hash == right.survey.survey_hash
        and left.method_skill_selection.artifact_hash
        == right.method_skill_selection.artifact_hash
        and left.component_atoms.artifact_hash == right.component_atoms.artifact_hash
        and left.prospective_atoms.artifact_hash
        == right.prospective_atoms.artifact_hash
        and left.opportunity_routing.artifact_hash
        == right.opportunity_routing.artifact_hash
        and canonical_model_hash(left.context) == canonical_model_hash(right.context)
    )


def resume_plan_from_retained_routing(
    config: OfficialLineageConfig,
    *,
    output_dir: Path | str,
    completion: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
) -> LineageStageReport:
    """Continue from retained survey/method/observed/prospective/routing artifacts.

    The five prior reasoning artifacts are read-only inputs. New distributed,
    ideation, real preliminary execution, authoring, and review receipts live under
    one lineage-contained resume root. Valid completed distributed, ideation, or
    preliminary-experiment substages are reused after full schema/hash/file
    verification; an incomplete substage is never replayed in place.
    """

    from autoresearch.agents.temporary import issue_stage_controller
    from autoresearch.competition.official_development_search import OfficialCellResult
    from autoresearch.competition.research_plan_latex import guard_references
    from autoresearch.competition.system_authored_plan import (
        SystemAuthoredPlanArtifact,
        author_research_plan,
    )
    from autoresearch.competition.system_plan_ideation import run_system_plan_ideation
    from autoresearch.competition.system_plan_opportunity_distributed import (
        run_distributed_system_plan_opportunity_map,
    )
    from autoresearch.competition.system_plan_preexperiment import (
        SystemPlanPreexperimentArtifact,
        run_system_plan_preexperiment,
    )
    from autoresearch.competition.system_plan_prospective_atoms import (
        build_component_experiment_binding,
    )
    from autoresearch.competition.system_plan_review import (
        SystemPlanCriticalReview,
        review_system_authored_plan,
    )
    from autoresearch.llm.task_context import AutonomousTaskContextSession
    from autoresearch.schemas import ResearchPlan, file_hash

    output_root = Path(output_dir).resolve()
    context_session: AutonomousTaskContextSession | None = None

    @contextmanager
    def stage_task(
        task_id: str,
    ) -> Generator[Callable[..., LLMJsonCompletionResult], None, None]:
        if context_session is None:
            yield completion
            return
        with context_session.task(task_id) as scoped_completion:
            yield scoped_completion

    with exclusive_lineage_lock(config.work_dir, stage="plan-routing-resume"):
        official_plan_path = config.plan_dir / "research-plan.json"
        if official_plan_path.exists():
            raise OfficialLineageError(
                "an official research plan already exists; resume would overwrite it"
            )
        if (config.work_dir / _SYSTEM_AUTHORED_PLAN_NAME).exists():
            raise OfficialLineageError(
                "a system-authored plan already exists in the lineage; refusing overwrite"
            )
        _validate_plan_resume_layout(config=config, output_root=output_root)
        snapshot = _load_retained_plan_routing_snapshot(config)
        if completion is run_llm_json_completion:
            context_session = AutonomousTaskContextSession(
                project_id=config.lineage_id,
                conversation_id=f"{config.lineage_id}-plan-resume",
                output_dir=output_root / "task-context-memory",
                completion=completion,
            )
        component_experiment_binding = build_component_experiment_binding(
            snapshot.component_atoms.binding(),
            snapshot.prospective_atoms.binding(),
        )
        references = list(snapshot.survey.selected_references)
        reference_findings = guard_references(references)
        if reference_findings:
            raise OfficialLineageError(
                f"retained literature failed verifiability checks: {reference_findings}"
            )

        distributed_root_path = (
            config.work_dir / "system-plan-opportunity-distributed.json"
        )
        resumed_distributed_root = output_root / _PLAN_RESUME_DISTRIBUTED_DIR
        resumed_distributed_path = (
            resumed_distributed_root / "system-plan-opportunity-distributed.json"
        )
        distributed_locations = [
            (distributed_root_path, config.work_dir),
            (resumed_distributed_path, resumed_distributed_root),
        ]
        known_distributed_paths = {
            path.resolve() for path, _root in distributed_locations
        }
        for sibling_path in sorted(
            config.work_dir.glob(
                "plan-resume-*/distributed/system-plan-opportunity-distributed.json"
            )
        ):
            if sibling_path.resolve() in known_distributed_paths:
                continue
            distributed_locations.append((sibling_path, sibling_path.parent))
            known_distributed_paths.add(sibling_path.resolve())
        existing_distributed = [
            item for item in distributed_locations if item[0].is_file()
        ]
        if len(existing_distributed) > 1:
            raise OfficialLineageError(
                "multiple distributed opportunity artifacts exist; canonical source is ambiguous"
            )
        if existing_distributed:
            distributed_path, distributed_output_root = existing_distributed[0]
            distributed = _load_verified_distributed_artifact(
                path=distributed_path,
                output_root=distributed_output_root,
                snapshot=snapshot,
                lineage_id=config.lineage_id,
            )
            distributed_reused = True
        else:
            if resumed_distributed_root.exists() and any(
                resumed_distributed_root.iterdir()
            ):
                raise OfficialLineageError(
                    "distributed resume directory is not fresh; refusing to replay receipts"
                )
            controller, capability = issue_stage_controller(
                lineage_id=config.lineage_id,
                stage="research-plan-opportunity-map",
                stage_attempt=1,
                controller_agent_id="stage-main-qwen-opportunity-router-resume",
                stage_input_hash=snapshot.opportunity_routing.artifact_hash,
                max_parallel_agents=7,
            )
            with stage_task("distributed-opportunity-map") as stage_completion:
                run_distributed_system_plan_opportunity_map(
                    routing_artifact=snapshot.opportunity_routing,
                    controller=controller,
                    capability=capability,
                    output_dir=resumed_distributed_root,
                    author_completion=stage_completion,
                    reviewer_completion=stage_completion,
                    config_path=config_path,
                    env_path=env_path,
                )
            distributed = _load_verified_distributed_artifact(
                path=resumed_distributed_path,
                output_root=resumed_distributed_root,
                snapshot=snapshot,
                lineage_id=config.lineage_id,
            )
            distributed_path = resumed_distributed_path
            distributed_output_root = resumed_distributed_root
            distributed_reused = False

        ideation_root_path = config.work_dir / "system-plan-ideation.json"
        resumed_ideation_root = output_root / _PLAN_RESUME_IDEATION_DIR
        resumed_ideation_path = resumed_ideation_root / "system-plan-ideation.json"
        ideation_locations = [
            (ideation_root_path, config.work_dir),
            (resumed_ideation_path, resumed_ideation_root),
        ]
        known_ideation_paths = {path.resolve() for path, _root in ideation_locations}
        for sibling_path in sorted(
            config.work_dir.glob("plan-resume-*/ideation/system-plan-ideation.json")
        ):
            if sibling_path.resolve() in known_ideation_paths:
                continue
            ideation_locations.append((sibling_path, sibling_path.parent))
            known_ideation_paths.add(sibling_path.resolve())
        existing_ideation = [item for item in ideation_locations if item[0].is_file()]
        if len(existing_ideation) > 1:
            raise OfficialLineageError(
                "multiple ideation artifacts exist; canonical source is ambiguous"
            )
        if existing_ideation:
            ideation_path, ideation_output_root = existing_ideation[0]
            ideation = _load_verified_ideation_artifact(
                path=ideation_path,
                output_root=ideation_output_root,
                distributed=distributed,
                component_experiment_binding=component_experiment_binding,
                frozen_evidence_context=snapshot.context,
                literature=references,
                retrieved_catalog=snapshot.survey.retrieved_catalog,
                lineage_id=config.lineage_id,
                config_path=config_path,
            )
            ideation_reused = True
        else:
            if resumed_ideation_root.exists() and any(resumed_ideation_root.iterdir()):
                raise OfficialLineageError(
                    "ideation resume directory is not fresh; refusing to replay receipts"
                )
            with stage_task("research-ideation") as stage_completion:
                run_system_plan_ideation(
                    lineage_id=config.lineage_id,
                    frozen_evidence_context=snapshot.context,
                    opportunity_map=distributed.binding(),
                    component_experiment_binding=component_experiment_binding,
                    literature=references,
                    retrieved_catalog=snapshot.survey.retrieved_catalog,
                    output_dir=resumed_ideation_root,
                    completion=stage_completion,
                    review_completion=stage_completion,
                    prosecution_completion=stage_completion,
                    config_path=config_path,
                    env_path=env_path,
                )
            ideation = _load_verified_ideation_artifact(
                path=resumed_ideation_path,
                output_root=resumed_ideation_root,
                distributed=distributed,
                component_experiment_binding=component_experiment_binding,
                frozen_evidence_context=snapshot.context,
                literature=references,
                retrieved_catalog=snapshot.survey.retrieved_catalog,
                lineage_id=config.lineage_id,
                config_path=config_path,
            )
            ideation_path = resumed_ideation_path
            ideation_output_root = resumed_ideation_root
            ideation_reused = False

        preexperiment_root = output_root / _PLAN_RESUME_PREEXPERIMENT_DIR
        preexperiment_path = (
            preexperiment_root / "system-plan-preexperiment.json"
        )
        if preexperiment_path.is_file():
            preexperiment = SystemPlanPreexperimentArtifact.model_validate_json(
                preexperiment_path.read_text(encoding="utf-8")
            )
            _require_artifact_output_path(
                artifact=preexperiment,
                artifact_path=preexperiment_path,
                label="resumed real preliminary experiment",
            )
            if (
                preexperiment.lineage_id != config.lineage_id
                or preexperiment.selected_direction_hash
                != ideation.selected_direction_hash
                or preexperiment.component_experiment_binding_hash
                != component_experiment_binding.binding_hash
            ):
                raise OfficialLineageError(
                    "retained preliminary experiment is not bound to the selected "
                    "direction and prospective component experiment"
                )
            _require_model_receipt(
                output_root=preexperiment_root,
                relative_path=(
                    preexperiment.interpretation_receipt_relative_path
                ),
                expected_hash=preexperiment.interpretation_receipt_hash,
                label="resumed preliminary experiment interpretation",
            )
            for cell in preexperiment.cell_evidence:
                raw_result_path = _require_path_inside(
                    preexperiment_root,
                    preexperiment_root / cell.raw_result_relative_path,
                    label="resumed preliminary raw result",
                )
                if (
                    not raw_result_path.is_file()
                    or file_hash(raw_result_path) != cell.raw_result_file_sha256
                    or OfficialCellResult.model_validate_json(
                        raw_result_path.read_text(encoding="utf-8")
                    )
                    != cell.result
                ):
                    raise OfficialLineageError(
                        "retained preliminary raw result is missing or hash-invalid"
                    )
            preexperiment_reused = True
        else:
            if preexperiment_root.exists() and any(preexperiment_root.iterdir()):
                raise OfficialLineageError(
                    "preliminary experiment resume directory is incomplete; "
                    "refusing to overwrite raw execution evidence"
                )
            with stage_task("real-preliminary-experiment") as stage_completion:
                preexperiment = run_system_plan_preexperiment(
                    lineage_id=config.lineage_id,
                    selected_direction=ideation.selected_direction,
                    component_experiment_binding=component_experiment_binding,
                    frozen_plan_path=config.frozen_plan_path,
                    autonomous_plan_path=config.autonomous_plan_path,
                    data_root=config.data_root,
                    public_panel=snapshot.context["public_development_panel"],
                    output_dir=preexperiment_root,
                    completion=stage_completion,
                    config_path=config_path,
                    env_path=env_path,
                )
            preexperiment_reused = False
        if not preexperiment.limited_feasibility_supported:
            raise OfficialLineageError(
                "真实预实验没有任何成功单元，尚不能生成含可行性结果的研究计划"
            )

        authoring_root = output_root / _PLAN_RESUME_AUTHORING_DIR
        if authoring_root.exists() and any(authoring_root.iterdir()):
            raise OfficialLineageError(
                "authoring resume directory is not fresh; refusing to overwrite receipts"
            )
        authoring_context = {
            **snapshot.context,
            "system_audited_research_opportunity_map": {
                "artifact_hash": distributed.artifact_hash,
                "accepted_cells": [
                    item.model_dump(mode="json") for item in distributed.accepted_cells
                ],
            },
            "system_selected_method_skills": (
                snapshot.method_skill_selection.binding().model_dump(mode="json")
            ),
            "system_component_atom_catalog": (
                snapshot.component_atoms.binding().model_dump(mode="json")
            ),
            "system_prospective_component_atoms": (
                snapshot.prospective_atoms.binding().model_dump(mode="json")
            ),
            "system_component_experiment_binding": (
                component_experiment_binding.model_dump(mode="json")
            ),
            "system_selected_research_direction": (
                ideation.selected_direction.model_dump(mode="json")
            ),
            "system_selected_research_direction_hash": ideation.selected_direction_hash,
            "system_plan_ideation_artifact_hash": ideation.artifact_hash,
            "system_preliminary_experiment": preexperiment.plan_context(),
        }

        with stage_task("research-plan-authoring") as stage_completion:

            def critical_review(
                candidate_plan: ResearchPlan, attempt: int
            ) -> Sequence[str]:
                review = review_system_authored_plan(
                    lineage_id=config.lineage_id,
                    plan=candidate_plan,
                    plan_hash=canonical_model_hash(
                        candidate_plan.model_dump(mode="json")
                    ),
                    literature_survey=snapshot.survey.model_dump(mode="json"),
                    frozen_evidence_context=authoring_context,
                    authoring_attempt=attempt,
                    output_dir=authoring_root,
                    completion=stage_completion,
                    config_path=config_path,
                    env_path=env_path,
                )
                return review.assessment.repair_findings()

            plan_artifact = author_research_plan(
                lineage_id=config.lineage_id,
                project_id=config.lineage_id,
                candidate_id=f"candidate_{ideation.selected_direction_hash[:12]}",
                frozen_context=authoring_context,
                evidence_paths=(
                    *snapshot.evidence_paths,
                    snapshot.survey_path,
                    snapshot.method_skill_selection_path,
                    snapshot.component_atoms_path,
                    snapshot.prospective_atoms_path,
                    snapshot.opportunity_routing_path,
                    distributed_path,
                    ideation_path,
                    preexperiment_path,
                ),
                output_dir=authoring_root,
                completion=stage_completion,
                config_path=config_path,
                env_path=env_path,
                container_entry_points=("/harness/runner.py",),
                literature=references,
                require_chinese=True,
                scientific_review=critical_review,
            )
        plan_artifact_path = authoring_root / _SYSTEM_AUTHORED_PLAN_NAME
        persisted_plan_artifact = SystemAuthoredPlanArtifact.model_validate_json(
            plan_artifact_path.read_text(encoding="utf-8")
        )
        if persisted_plan_artifact != plan_artifact:
            raise OfficialLineageError(
                "persisted resumed plan artifact differs from the accepted model output"
            )
        plan_artifact = persisted_plan_artifact
        plan = ResearchPlan.model_validate(plan_artifact.plan)
        _require_artifact_output_path(
            artifact=plan_artifact,
            artifact_path=plan_artifact_path,
            label="system-authored resumed plan",
        )
        if plan_artifact.authorship_receipt_relative_path is None:
            raise OfficialLineageError("resumed system-authored plan lacks a model receipt")
        _require_model_receipt(
            output_root=authoring_root,
            relative_path=plan_artifact.authorship_receipt_relative_path,
            expected_hash=str(plan_artifact.authorship_receipt_hash),
            label="resumed plan authorship",
        )
        critical_review_path = authoring_root / "system-plan-critical-review.json"
        accepted_review = SystemPlanCriticalReview.model_validate_json(
            critical_review_path.read_text(encoding="utf-8")
        )
        _require_artifact_output_path(
            artifact=accepted_review,
            artifact_path=critical_review_path,
            label="resumed plan critical review",
        )
        _require_model_receipt(
            output_root=authoring_root,
            relative_path=accepted_review.authorship_receipt_relative_path,
            expected_hash=accepted_review.authorship_receipt_hash,
            label="resumed plan critical review",
        )
        if (
            accepted_review.lineage_id != config.lineage_id
            or accepted_review.plan_hash != plan_artifact.plan_hash
            or accepted_review.literature_survey_hash != snapshot.survey.survey_hash
            or not accepted_review.assessment.ready_for_human_scope_review
        ):
            raise OfficialLineageError(
                "accepted resumed review is not bound to the retained survey and final plan"
            )

        final_snapshot = _load_retained_plan_routing_snapshot(config)
        if not _same_retained_routing_snapshot(snapshot, final_snapshot):
            raise OfficialLineageError(
                "retained survey/method/observed/prospective/routing changed "
                "during plan resume"
            )
        final_distributed = _load_verified_distributed_artifact(
            path=distributed_path,
            output_root=distributed_output_root,
            snapshot=final_snapshot,
            lineage_id=config.lineage_id,
        )
        final_ideation = _load_verified_ideation_artifact(
            path=ideation_path,
            output_root=ideation_output_root,
            distributed=final_distributed,
            component_experiment_binding=component_experiment_binding,
            frozen_evidence_context=final_snapshot.context,
            literature=references,
            retrieved_catalog=final_snapshot.survey.retrieved_catalog,
            lineage_id=config.lineage_id,
            config_path=config_path,
        )
        if (
            final_distributed.artifact_hash != distributed.artifact_hash
            or final_ideation.artifact_hash != ideation.artifact_hash
        ):
            raise OfficialLineageError(
                "distributed or ideation artifact changed during plan resume"
            )
        final_preexperiment = SystemPlanPreexperimentArtifact.model_validate_json(
            preexperiment_path.read_text(encoding="utf-8")
        )
        if final_preexperiment != preexperiment:
            raise OfficialLineageError(
                "preliminary experiment artifact changed during plan resume"
            )

        canonical_plan_artifact = _promote_resumed_plan_artifact(
            config=config,
            authoring_root=authoring_root,
            artifact=plan_artifact,
        )
        _write_once_json(official_plan_path, plan)
        persisted_official_plan = ResearchPlan.model_validate_json(
            official_plan_path.read_text(encoding="utf-8")
        )
        if (
            persisted_official_plan != plan
            or canonical_model_hash(persisted_official_plan.model_dump(mode="json"))
            != plan_artifact.plan_hash
        ):
            raise OfficialLineageError(
                "persisted official plan is not the hash-bound resumed model plan"
            )
        manifest_payload: dict[str, Any] = {
            "schema_version": "plan-stage-routing-resume-manifest-v3",
            "lineage_id": config.lineage_id,
            "retained_survey_hash": snapshot.survey.survey_hash,
            "retained_method_skill_selection_hash": (
                snapshot.method_skill_selection.artifact_hash
            ),
            "retained_component_atom_hash": snapshot.component_atoms.artifact_hash,
            "retained_prospective_atom_hash": (
                snapshot.prospective_atoms.artifact_hash
            ),
            "retained_routing_hash": snapshot.opportunity_routing.artifact_hash,
            "distributed_artifact_hash": distributed.artifact_hash,
            "distributed_artifact_path": distributed_path.resolve().as_posix(),
            "distributed_reused": distributed_reused,
            "ideation_artifact_hash": ideation.artifact_hash,
            "ideation_artifact_path": ideation_path.resolve().as_posix(),
            "ideation_reused": ideation_reused,
            "preexperiment_artifact_hash": preexperiment.artifact_hash,
            "preexperiment_artifact_path": preexperiment_path.resolve().as_posix(),
            "preexperiment_reused": preexperiment_reused,
            "system_authored_plan_artifact_hash": (
                canonical_plan_artifact.artifact_hash
            ),
            "system_authored_plan_artifact_path": (
                Path(canonical_plan_artifact.output_path).resolve().as_posix()
            ),
            "plan_hash": plan_artifact.plan_hash,
            "official_plan_path": official_plan_path.resolve().as_posix(),
            "critical_review_hash": accepted_review.review_hash,
            "critical_review_path": critical_review_path.resolve().as_posix(),
            "authored_by_model": True,
            "hand_written_scientific_prose_count": 0,
            "execution_authorized": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        manifest_payload["manifest_hash"] = canonical_model_hash(manifest_payload)
        resume_manifest_path = output_root / _PLAN_RESUME_MANIFEST_NAME
        _write_once_json(resume_manifest_path, manifest_payload)
        persisted_manifest = json.loads(
            resume_manifest_path.read_text(encoding="utf-8")
        )
        persisted_manifest_hash = persisted_manifest.pop("manifest_hash", None)
        if (
            persisted_manifest_hash != manifest_payload["manifest_hash"]
            or canonical_model_hash(persisted_manifest) != persisted_manifest_hash
        ):
            raise OfficialLineageError("persisted plan resume manifest hash mismatch")
        return LineageStageReport(
            lineage_id=config.lineage_id,
            stage="plan",
            lines=(
                "=== STAGE plan: resumed after retained routing",
                f"  retained survey: {snapshot.survey.survey_hash}",
                f"  retained method: {snapshot.method_skill_selection.artifact_hash}",
                f"  retained atoms : {snapshot.component_atoms.artifact_hash}",
                f"  prospective atoms: {snapshot.prospective_atoms.artifact_hash}",
                f"  retained route : {snapshot.opportunity_routing.artifact_hash}",
                f"  opportunity map: {distributed.artifact_hash}",
                f"  distributed reused: {str(distributed_reused).lower()}",
                f"  ideation       : {ideation.artifact_hash}",
                f"  ideation reused: {str(ideation_reused).lower()}",
                f"  preexperiment : {preexperiment.artifact_hash}",
                f"  preliminary cells: {len(preexperiment.cell_evidence)} actual sandbox runs",
                f"  preexperiment reused: {str(preexperiment_reused).lower()}",
                "  preliminary scope: baseline feasibility only; treatment effect unmeasured",
                f"  plan hash      : {plan_artifact.plan_hash}",
                f"  critical review: {accepted_review.review_hash}",
                "  temporary agents: seven authors plus seven reviewers archived",
                "  hand-written scientific prose fields: 0",
                "  execution BLOCKED until a human approves this exact plan hash",
            ),
        )


def resume_plan_authoring_from_retained_reasoning(
    config: OfficialLineageConfig,
    *,
    output_dir: Path | str,
) -> LineageStageReport:
    """Compatibility wrapper for the single fail-closed plan-resume path.

    Older versions resumed directly from a retained ideation artifact. That route
    cannot prove that the direction inherits the reviewed prospective component and
    its unique intervention identity. Keep the public entry point for callers, but
    make it use the only current resume implementation, which replays the complete
    survey/method/observed/prospective/routing chain before any new model call.
    """

    return resume_plan_from_retained_routing(config, output_dir=output_dir)


def preregister_and_author_system_plan(
    config: OfficialLineageConfig,
    *,
    baseline_parent_dir: Path | str,
    authored_decision_package_path: Path | str,
    zero_term_evidence_root: Path | str,
    contradiction_package_path: Path | str,
) -> LineageStageReport:
    """Freeze a fresh child lineage, then autonomously author its Chinese plan."""

    from autoresearch.competition.official_baseline_policy import (
        assert_policy_precedes_numeric_payload,
        preregister_baseline_policy,
    )
    from autoresearch.competition.preregistered_stage_breadth import (
        preregister_stage_breadth,
    )

    config.work_dir.mkdir(parents=True, exist_ok=True)
    with exclusive_lineage_lock(config.work_dir, stage="preregister-plan"):
        unexpected = [
            item
            for item in config.work_dir.iterdir()
            if item.name != _LOCK_NAME
        ]
        if unexpected:
            raise OfficialLineageError(
                "preregister-plan requires a fresh lineage directory; found "
                + ", ".join(sorted(item.name for item in unexpected))
            )
        identity, ledger = freeze_lineage(config)
        parent = Path(baseline_parent_dir).resolve()
        policy = preregister_baseline_policy(
            lineage_id=config.lineage_id,
            parent_lineage_id=parent.name,
            frozen_plan_path=config.frozen_plan_path,
            authored_decision_package_path=authored_decision_package_path,
            parent_identity_path=parent / _IDENTITY_NAME,
            prior_baseline_results_path=parent / "cells" / "baseline-results.json",
            prior_full_results_path=parent / "cells" / "full-results.json",
            zero_term_evidence_root=zero_term_evidence_root,
            child_runner_sha256=identity.runner_sha256,
            output_dir=config.work_dir,
        )
        assert_policy_precedes_numeric_payload(
            output_dir=config.work_dir, lineage_dir=config.work_dir
        )
        panel = json.loads(
            config.autonomous_plan_path.read_text(encoding="utf-8")
        )["development_panel"]
        breadth = preregister_stage_breadth(
            lineage_id=config.lineage_id,
            frozen_plan_path=config.frozen_plan_path,
            baseline_policy_hash=policy.policy_hash,
            contradiction_package_path=contradiction_package_path,
            panel=panel,
            excluded_system_names=policy.excluded_system_names,
            output_dir=config.work_dir,
        )
        report = run_plan_stage(config)
    return report.model_copy(
        update={
            "lines": (
                "=== PREREGISTRATION: fresh zero-spend lineage frozen",
                f"  identity hash  : {identity.identity_hash}",
                f"  ledger entries : {len(ledger.entries)}",
                f"  policy hash    : {policy.policy_hash}",
                f"  breadth hash   : {breadth.breadth_hash}",
                *report.lines,
            )
        }
    )


def run_approve_stage(
    config: OfficialLineageConfig, *, decided_by: str, notes: str
) -> LineageStageReport:
    """Record the human decision against this exact plan hash, before any cell runs."""

    from autoresearch.research.plan_confirmation import (
        compute_plan_hash,
        record_plan_decision,
    )

    _artifact, plan, _ = _load_formal_system_plan_artifact(
        config,
        require_decision=False,
    )
    record = record_plan_decision(
        plan=plan,
        decision="approve",
        decided_by=decided_by,
        notes=notes,
        output_dir=config.plan_dir,
    )
    return LineageStageReport(
        lineage_id=config.lineage_id,
        stage="approve",
        lines=(
            "=== STAGE approve: human confirmation recorded",
            f"  decision   : {record.decision}",
            f"  plan_hash  : {record.plan_hash[:32]}...",
            f"  binds plan : {record.plan_hash == compute_plan_hash(plan)}",
            f"  is evidence: {record.is_evidence}",
        ),
    )


def run_generate_stage(config: OfficialLineageConfig) -> LineageStageReport:
    """Ask for the frozen number of independent candidates. Score-blind."""

    from autoresearch.competition.plan_execution_contract import (
        compile_system_authored_plan_execution_contract,
    )
    from autoresearch.research.plan_confirmation import require_approved_plan

    # Candidate authoring is part of executing the scientific plan: it spends the
    # frozen generation budget and determines which method is measured. Gate it before
    # `_freeze` creates or changes any lineage artifact and before the provider is called.
    plan_artifact, plan, decision = _load_formal_system_plan_artifact(config)
    require_approved_plan(plan=plan, decision=decision)
    compile_system_authored_plan_execution_contract(plan_artifact)
    frozen, identity, panel, ledger = _freeze(config)
    budget = frozen["search_budget"]
    count = int(budget["initial_candidate_count"])
    specs: tuple[_AuthoringSpec, ...] = tuple(
        (f"official-{index:02d}", f"official-generate-{index:02d}", 1, None)
        for index in range(1, count + 1)
    )
    ledger, evidence, _audit = _reconcile_authoring_spend(
        config=config,
        ledger=ledger,
        stage="generate-gen1",
        specs=specs,
    )
    registry_path = config.candidates_dir / _CANDIDATE_REGISTRY
    if registry_path.is_file():
        candidates = tuple(_load_registry(registry_path))
        ledger, evidence, audit = _reconcile_authoring_spend(
            config=config,
            ledger=ledger,
            stage="generate-gen1",
            specs=specs,
            records=candidates,
        )
        if audit.canonical_model_interaction_count != audit.logical_model_interaction_count:
            raise OfficialLineageError(
                "completed generate registry contains an incomplete logical interaction"
            )
    else:
        _check_authoring_reservation(
            ledger=ledger,
            stage="generate-gen1",
            specs=specs,
            evidence=evidence,
        )
        try:
            candidates = generate_official_candidates(
                identity=identity,
                panel=panel,
                budget=budget,
                output_dir=config.work_dir,
                research_plan=plan_artifact,
            )
        finally:
            retained_records = (
                tuple(_load_registry(registry_path)) if registry_path.is_file() else None
            )
            ledger, _evidence, _audit = _reconcile_authoring_spend(
                config=config,
                ledger=ledger,
                stage="generate-gen1",
                specs=specs,
                records=retained_records,
            )
        ledger, evidence, audit = _reconcile_authoring_spend(
            config=config,
            ledger=ledger,
            stage="generate-gen1",
            specs=specs,
            records=candidates,
        )
        if audit.canonical_model_interaction_count != audit.logical_model_interaction_count:
            raise OfficialLineageError(
                "generate completed with an incomplete logical interaction"
            )
    lines = ["=== STAGE generate: candidate generation"]
    for record in candidates:
        flag = "OK " if record.static_review_approved else "REJ"
        lines.append(f"  {flag} {record.candidate_id}: {record.implementation_summary[:74]}")
    approved = [item for item in candidates if item.static_review_approved]
    lines.append(f"  approved {len(approved)}/{len(candidates)}")
    lines.append(
        f"  logical model interactions {audit.logical_model_interaction_count}; "
        f"provider request attempts {audit.provider_request_attempt_count}"
    )
    lines.append(
        f"  generations spent {ledger.spent_generations}/{ledger.maximum_generations}"
    )
    lines.append(f"  remaining {ledger.remaining()}")
    return LineageStageReport(
        lineage_id=config.lineage_id, stage="generate", lines=tuple(lines)
    )


def _split_smoke_wave(
    specs: Sequence[OfficialCellSpec],
) -> tuple[tuple[OfficialCellSpec, ...], tuple[OfficialCellSpec, ...]]:
    """Split a frozen stage into a per-candidate smoke wave and the remainder.

    The smoke wave takes one system per DATA TYPE for each candidate, not merely the
    first system. `P-20260804-082`: taking only the first system covered an ODE system
    for all three candidates in `task2695-pde-repair-lineage-v1`, so a candidate whose
    PDE handling exceeds the wall-time budget passed its smoke wave and then failed
    every one of its 12 PDE cells. A gate that cannot see a stratum cannot protect it.

    Splitting a frozen spec list preserves freeze-before-execute: every cell was
    frozen and hashed before any of them ran, and no cell is added, dropped, or
    rewritten here.
    """

    # One representative system per (candidate, data_type) pair.
    representative: dict[tuple[str, str], str] = {}
    for spec in specs:
        representative.setdefault(
            (spec.candidate_id, spec.data_type), spec.system_name
        )
    chosen = set(representative.values())
    smoke = tuple(
        item
        for item in specs
        if representative.get((item.candidate_id, item.data_type)) == item.system_name
    )
    rest = tuple(
        item
        for item in specs
        if representative.get((item.candidate_id, item.data_type)) != item.system_name
    )
    assert len(smoke) + len(rest) == len(specs), chosen
    return smoke, rest


def assert_finalists_can_execute(
    *,
    results: Sequence[OfficialCellResult],
    finalist_ids: Sequence[str],
) -> dict[str, bool]:
    """Refuse to promote a finalist that has never executed a single cell.

    `P-20260804-080`: the pilot executes the PRE-revision candidates, and the loop
    then promoted the POST-revision candidates straight into the full stage, so a
    revised candidate reached 72 official cells without ever having run. In this
    lineage `official-05-r2` failed all 72 with one uniform
    ``TypeError: can't multiply sequence by non-int of type 'numpy.float64'``, an
    unconditional crash that static review cannot catch because static review checks
    structure rather than types. Its failure loss then swamped the estimand.

    A finalist qualifies on evidence, not on having been ranked: at least one cell in
    `results` must have SUCCEEDED for it. Returns the per-finalist verdict so a caller
    can report the refusal instead of hiding it.
    """

    succeeded: dict[str, bool] = {}
    for candidate_id in finalist_ids:
        succeeded[candidate_id] = any(
            item.candidate_id == candidate_id and item.status == "succeeded"
            for item in results
        )
    if not any(succeeded.values()):
        raise OfficialLineageError(
            "no finalist produced a single successful smoke cell, so promoting any of "
            f"them would spend the full stage on code that cannot run: {succeeded}"
        )
    return succeeded


def _policy_excluded_systems(config: OfficialLineageConfig) -> tuple[str, ...]:
    """Return the systems this lineage's preregistered policy excludes, if any.

    A lineage without a policy is unchanged, so the pre-policy lineages stay
    byte-reproducible.
    """

    from autoresearch.competition.official_baseline_policy import (
        BaselinePolicyError,
        load_baseline_policy,
    )

    try:
        policy = load_baseline_policy(output_dir=config.work_dir)
    except BaselinePolicyError:
        return ()
    return tuple(policy.excluded_system_names)


def narrow_panel_by_policy(
    *,
    panel: dict[str, Any],
    excluded_system_names: Sequence[str],
) -> dict[str, Any]:
    """Remove the preregistered policy's excluded systems from a panel.

    Without this the exclusion would be decorative: the frozen gate checks
    `all_baseline_cells_succeeded`, so executing a system whose baseline cannot
    produce a loss keeps that check false no matter what the policy declared. The
    policy states the panel change and its power cost, and this is where that
    declared change actually takes effect.
    """

    excluded = set(excluded_system_names)
    unknown = excluded - {str(item["system_name"]) for item in panel["systems"]}
    if unknown:
        raise OfficialLineageError(
            f"the preregistered policy excludes {sorted(unknown)}, which are not in "
            "this panel, so the policy does not describe this lineage"
        )
    narrowed = dict(panel)
    narrowed["systems"] = [
        item for item in panel["systems"] if str(item["system_name"]) not in excluded
    ]
    if not narrowed["systems"]:
        raise OfficialLineageError("the policy excludes every system in the panel")
    return narrowed


def _stage_shape(
    *,
    stage: Literal["pilot", "baseline", "full"],
    panel: dict[str, Any],
    budget: dict[str, Any],
    identity: OfficialDevelopmentIdentity,
    breadth: PreregisteredStageBreadth | None = None,
) -> tuple[list[dict[str, Any]], list[int]]:
    """Systems and seeds for one execution stage, all read from preregistered facts.

    `panel` must already be narrowed by any preregistered policy, so an excluded
    system cannot reach a cell spec. Without a preregistered `breadth` the frozen
    parent breadth is enforced, so a narrowed panel that cannot supply it is REFUSED
    rather than silently reshaped. With one, this lineage's own preregistered breadth
    applies and the frozen parent plan stays byte-identical.
    """

    if stage == "pilot":
        expected_count = identity.pilot_system_count
        effective_budget = budget
        if breadth is not None:
            # `P-20260804-077`: the frozen breadth is unreachable on the narrowed
            # panel, and the system's own loop chose a new preregistration over
            # rewriting the frozen budget. The artifact binds the parent's numbers as
            # evidence of what it supersedes; the frozen plan itself is untouched.
            if breadth.parent_plan_hash != identity.plan_hash:
                raise OfficialLineageError(
                    "the preregistered stage breadth binds a different parent plan "
                    "than this lineage's frozen identity"
                )
            effective_budget = {
                **budget,
                "pilot_ode_system_count": breadth.pilot_ode_count,
                "pilot_pde_system_count": breadth.pilot_pde_count,
            }
            expected_count = breadth.pilot_system_count
        systems = select_pilot_systems(panel=panel, budget=effective_budget)
        if len(systems) != expected_count:
            raise OfficialLineageError(
                f"pilot breadth {len(systems)} contradicts the preregistered "
                f"pilot_system_count {expected_count}"
            )
        seeds = list(panel["seeds"])[: int(budget["pilot_seed_count"])]
        return systems, seeds
    return list(panel["systems"]), list(panel["seeds"])


def run_execution_stage(
    config: OfficialLineageConfig,
    *,
    stage: Literal["pilot", "baseline", "full"],
) -> LineageStageReport:
    """Freeze every cell of one stage, then execute it under the frozen budget."""

    frozen, identity, panel, ledger = _freeze(config)
    budget = frozen["search_budget"]
    plan_artifact, plan, decision = _load_formal_system_plan_artifact(config)
    registry = _REVISED_REGISTRY if stage == "full" else _CANDIDATE_REGISTRY
    records = _load_registry(config.candidates_dir / registry)
    actors = [item for item in records if item.static_review_approved]
    # A preregistered exclusion has to bind here, or it is decorative: the frozen
    # gate requires every baseline cell to succeed, so a system whose baseline
    # cannot produce a loss must not reach a cell spec at all.
    policy_excluded = _policy_excluded_systems(config)
    if policy_excluded:
        panel = narrow_panel_by_policy(
            panel=panel, excluded_system_names=policy_excluded
        )
    systems, seeds = _stage_shape(
        stage=stage,
        panel=panel,
        budget=budget,
        identity=identity,
        breadth=load_stage_breadth(output_dir=config.work_dir),
    )

    specs: tuple[OfficialCellSpec, ...] = build_official_cell_specs(
        identity=identity,
        candidates=actors,
        stage=stage,
        systems=systems,
        seeds=seeds,
        output_dir=config.work_dir,
    )
    candidate_cells = sum(1 for item in specs if item.method_kind == "candidate")
    baseline_cells = sum(1 for item in specs if item.method_kind == "baseline")
    lines = [
        f"=== STAGE {stage}: {len(specs)} cells "
        f"({len(systems)} systems x {len(identity.conditions)} conditions x "
        f"{len(seeds)} seeds)",
        f"  ledger before {ledger.remaining()}",
    ]

    if stage == "full":
        # `P-20260804-080`: the pilot executes the PRE-revision candidates, so a
        # revised candidate would otherwise reach every full cell having never run.
        # `official-05-r2` did exactly that and failed all 72 with one unconditional
        # TypeError, and its failure loss swamped the estimand. The full stage
        # therefore runs in two waves: a smoke wave of one system per candidate,
        # then the remainder for candidates that proved they can execute. A
        # qualifying candidate's smoke cells are real full cells and stay in the
        # effect, so this costs a healthy candidate nothing.
        smoke_specs, rest_specs = _split_smoke_wave(specs)
        lines.append(
            f"  smoke wave {len(smoke_specs)} cells "
            f"({len({item.candidate_id for item in smoke_specs})} candidates)"
        )
        smoke_results = execute_official_stage(
            identity=identity,
            specs=smoke_specs,
            candidates=actors,
            output_dir=config.work_dir,
            baseline_method=None,
            timeout_seconds=int(budget["maximum_seconds_per_cell"]),
            maximum_parallel_cells=int(budget["maximum_parallel_cells"]),
            research_plan=plan_artifact,
            plan_decision=decision,
            ledger=ledger,
        )
        verdicts = assert_finalists_can_execute(
            results=smoke_results,
            finalist_ids=sorted({item.candidate_id for item in smoke_specs}),
        )
        for candidate_id, ok in sorted(verdicts.items()):
            # Per-stratum detail, so a defect confined to one stratum is visible
            # BEFORE the remaining cells run. Promotion stays all-or-nothing on
            # purpose: refusing only the failing stratum would let a candidate dodge
            # the systems it loses on, which is the cherry-picking this estimand
            # forbids. A stratum it cannot run therefore still costs it failure loss.
            strata = []
            for data_type in sorted({item.data_type for item in smoke_specs}):
                stratum_cells = [
                    item
                    for item in smoke_results
                    if item.candidate_id == candidate_id
                    and item.data_type == data_type
                ]
                succeeded_in_stratum = sum(
                    1 for item in stratum_cells if item.status == "succeeded"
                )
                strata.append(
                    f"{data_type} {succeeded_in_stratum}/{len(stratum_cells)}"
                )
            lines.append(
                f"    smoke {candidate_id}: "
                + ("PASS" if ok else "REFUSED, cannot execute")
                + f" [{', '.join(strata)}]"
            )
            if ok and any(item.endswith(" 0/2") or " 0/" in item for item in strata):
                lines.append(
                    f"      WARNING {candidate_id} cannot run a whole stratum; its "
                    "cells there will take the frozen failure loss, and promotion is "
                    "deliberately not narrowed to avoid cherry-picking"
                )
        qualified = {name for name, ok in verdicts.items() if ok}
        refused = sorted(name for name, ok in verdicts.items() if not ok)
        rest_specs = tuple(
            item for item in rest_specs if item.candidate_id in qualified
        )
        candidate_cells = len(smoke_specs) + len(rest_specs)
        baseline_cells = 0
        results = execute_official_stage(
            identity=identity,
            specs=rest_specs,
            candidates=actors,
            output_dir=config.work_dir,
            baseline_method=None,
            timeout_seconds=int(budget["maximum_seconds_per_cell"]),
            maximum_parallel_cells=int(budget["maximum_parallel_cells"]),
            research_plan=plan_artifact,
            plan_decision=decision,
            ledger=ledger,
            prior_results=smoke_results,
        )
        if refused:
            lines.append(
                f"  promotion refused for {', '.join(refused)}; "
                f"{len(specs) - candidate_cells} cells not spent on code that "
                "cannot run"
            )
    else:
        results = execute_official_stage(
            identity=identity,
            specs=specs,
            candidates=actors,
            output_dir=config.work_dir,
            baseline_method=None,
            timeout_seconds=int(budget["maximum_seconds_per_cell"]),
            maximum_parallel_cells=int(budget["maximum_parallel_cells"]),
            research_plan=plan_artifact,
            plan_decision=decision,
            ledger=ledger,
        )
    ledger = ledger.record(
        stage=stage, candidate_cells=candidate_cells, baseline_cells=baseline_cells
    )
    persist_ledger(ledger=ledger, output_dir=config.work_dir)

    succeeded = sum(1 for item in results if item.status == "succeeded")
    lines.append(f"  COMPLETE {succeeded}/{len(results)} succeeded")
    for candidate_id in sorted({item.candidate_id for item in results}):
        cells = [item for item in results if item.candidate_id == candidate_id]
        good = [item for item in cells if item.status == "succeeded"]
        detail = ""
        if good:
            losses = sorted(item.loss for item in good)
            terms = sorted(item.selected_term_count or 0 for item in good)
            detail = (
                f"  nmse {losses[0]:.4g}..{losses[-1]:.4g}  terms {terms[0]}..{terms[-1]}"
            )
        lines.append(f"    {candidate_id}: {len(good)}/{len(cells)}{detail}")
    zero_term = [
        item
        for item in results
        if item.failure_reason and _ZERO_TERM_MARKER in item.failure_reason
    ]
    lines.append(f"  zero-term failures: {len(zero_term)}")
    lines.append(f"  ledger after {ledger.remaining()}")
    return LineageStageReport(
        lineage_id=config.lineage_id, stage=stage, lines=tuple(lines)
    )


def run_revise_stage(config: OfficialLineageConfig) -> LineageStageReport:
    """Let the best pilot candidates re-author themselves from their OWN failures."""

    from autoresearch.competition.plan_execution_contract import (
        compile_system_authored_plan_execution_contract,
    )
    from autoresearch.research.plan_confirmation import require_approved_plan

    plan_artifact, plan, decision = _load_formal_system_plan_artifact(config)
    require_approved_plan(plan=plan, decision=decision)
    compile_system_authored_plan_execution_contract(plan_artifact)
    frozen, _identity, panel, ledger = _freeze(config)
    budget = frozen["search_budget"]
    parents = _load_registry(config.candidates_dir / _CANDIDATE_REGISTRY)
    pilot = _load_results(config.cells_dir / "pilot-results.json")
    chosen = rank_pilot_finalists(
        candidates=parents,
        pilot_results=pilot,
        finalist_count=int(budget["full_finalist_count"]),
    )
    if not chosen:
        raise OfficialLineageError(
            "no approved candidate produced a usable pilot validation loss, so there "
            "is nothing to revise; the pilot must be inspected before spending again"
        )
    specs: tuple[_AuthoringSpec, ...] = tuple(
        (
            f"{record.candidate_id}-r2",
            f"official-revise-{record.candidate_id}",
            2,
            record.source_sha256,
        )
        for record in chosen
    )
    ledger, evidence, _audit = _reconcile_authoring_spend(
        config=config,
        ledger=ledger,
        stage="revise-gen2",
        specs=specs,
    )
    registry_path = config.candidates_dir / _REVISED_REGISTRY
    if registry_path.is_file():
        revised = tuple(_load_registry(registry_path))
        ledger, _evidence, audit = _reconcile_authoring_spend(
            config=config,
            ledger=ledger,
            stage="revise-gen2",
            specs=specs,
            records=revised,
        )
        if audit.canonical_model_interaction_count != audit.logical_model_interaction_count:
            raise OfficialLineageError(
                "completed revise registry contains an incomplete logical interaction"
            )
    else:
        _check_authoring_reservation(
            ledger=ledger,
            stage="revise-gen2",
            specs=specs,
            evidence=evidence,
        )
        try:
            revised = revise_official_candidates(
                panel=panel,
                budget=budget,
                candidates=chosen,
                results=pilot,
                output_dir=config.work_dir,
                research_plan=plan_artifact,
            )
        finally:
            retained_records = (
                tuple(_load_registry(registry_path)) if registry_path.is_file() else None
            )
            ledger, _evidence, _audit = _reconcile_authoring_spend(
                config=config,
                ledger=ledger,
                stage="revise-gen2",
                specs=specs,
                records=retained_records,
            )
        ledger, _evidence, audit = _reconcile_authoring_spend(
            config=config,
            ledger=ledger,
            stage="revise-gen2",
            specs=specs,
            records=revised,
        )
        if audit.canonical_model_interaction_count != audit.logical_model_interaction_count:
            raise OfficialLineageError(
                "revise completed with an incomplete logical interaction"
            )
    lines = [
        "=== STAGE revise: self-revision",
        f"  chosen {[item.candidate_id for item in chosen]}",
    ]
    for record in revised:
        flag = "OK " if record.static_review_approved else "REJ"
        lines.append(f"  {flag} {record.candidate_id}: {record.implementation_summary[:74]}")
    lines.append(
        f"  logical model interactions {audit.logical_model_interaction_count}; "
        f"provider request attempts {audit.provider_request_attempt_count}"
    )
    lines.append(
        f"  generations spent {ledger.spent_generations}/{ledger.maximum_generations}"
    )
    lines.append(f"  remaining {ledger.remaining()}")
    return LineageStageReport(
        lineage_id=config.lineage_id, stage="revise", lines=tuple(lines)
    )


def run_adjudicate_stage(
    config: OfficialLineageConfig, *, package_output_dir: Path | str | None = None
) -> LineageStageReport:
    """Select, estimate, evaluate the frozen gate, and write the signed package.

    Reads the lineage read-only. `package_output_dir` lets a retained lineage be
    adjudicated without writing anything into the retained directory.
    """

    frozen, identity, ledger = _load_frozen_read_only(config)
    estimand = frozen["estimand"]
    finalists = _load_registry(config.candidates_dir / _REVISED_REGISTRY)
    full = _load_results(config.cells_dir / "full-results.json")
    baseline = _load_results(config.cells_dir / "baseline-results.json")

    selected, basis = select_official_candidate(candidates=finalists, results=full)
    effects = compute_system_effects(
        candidate_id=selected or "", candidate_results=full, baseline_results=baseline
    )
    summary = aggregate_paired_effects(effects)
    selected_cells = [item for item in full if item.candidate_id == selected]

    gate_checks = evaluate_frozen_gate(
        estimand=estimand,
        summary=summary,
        candidate_cells=selected_cells,
        baseline_results=baseline,
        remaining_budget=ledger.remaining(),
    )

    # Full candidate provenance: every generation that this lineage authored.
    parents = _load_registry(config.candidates_dir / _CANDIDATE_REGISTRY)
    known: dict[str, OfficialCandidateRecord] = {
        item.candidate_id: item for item in (*parents, *finalists)
    }
    # Every retained cell from every executed stage, failures included.
    cell_results: list[OfficialCellResult] = []
    stages_executed: list[str] = []
    for stage_name in ("pilot", "baseline", "full"):
        path = config.cells_dir / f"{stage_name}-results.json"
        if path.is_file():
            cell_results.extend(_load_results(path))
            stages_executed.append(stage_name)

    package = write_official_development_search_package(
        identity=identity,
        candidates=[known[key] for key in sorted(known)],
        cell_results=cell_results,
        stages_executed=stages_executed,
        selected_candidate_id=selected,
        selection_basis=basis,
        system_effects=effects,
        summary=summary,
        estimand=estimand,
        gate_checks=gate_checks,
        output_dir=package_output_dir or config.work_dir,
    )

    lines = ["=== STAGE adjudicate", f"  selected {selected}", ""]
    for effect in sorted(effects, key=lambda item: (item.data_type, item.system_name)):
        mark = "" if effect.is_paired else "   [UNPAIRED excluded]"
        lines.append(
            f"  {effect.data_type:3} {effect.system_name[:30]:31}"
            f"cand={effect.candidate_median_loss:.5g} "
            f"base={effect.baseline_median_loss:.5g} "
            f"log={effect.paired_log_effect:+.4f}{mark}"
        )
    lines.append("")
    for key in (
        "paired_system_count",
        "baseline_coverage_gap_count",
        "overall_median_log_effect",
        "bootstrap_lower",
        "bootstrap_upper",
        "ode_stratum_median",
        "pde_stratum_median",
        "candidate_win_count",
    ):
        lines.append(f"  {key:28} {summary.get(key)}")
    lines.append("")
    lines.append("=== FROZEN GATE")
    for name, passed in gate_checks.items():
        lines.append(f"  {name:34} {'PASS' if passed else 'FAIL'}")
    lines.append("")
    lines.append(f"  search_freeze_receipt : {package.search_freeze_receipt_issued}")
    zero_term = [
        item
        for item in full
        if item.failure_reason and _ZERO_TERM_MARKER in item.failure_reason
    ]
    lines.append(f"  zero-term failures    : {len(zero_term)}")
    lines.append(f"  spent candidates      : {ledger.spent_candidate_count}")
    lines.append(f"  spent candidate cells : {ledger.spent_candidate_cells}")
    lines.append(f"  spent total cells     : {ledger.spent_total_cells}")
    lines.append(f"  package               : {package.output_path}")
    lines.append(f"  package_hash          : {package.package_hash}")
    return LineageStageReport(
        lineage_id=config.lineage_id,
        stage="adjudicate",
        lines=tuple(lines),
        package_path=package.output_path,
        search_freeze_receipt_issued=package.search_freeze_receipt_issued,
    )


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    """Load one JSON object with a diagnostic that names the evidence boundary."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OfficialLineageError(f"{label} is missing or invalid: {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise OfficialLineageError(f"{label} must be a JSON object: {path}")
    return dict(payload)


def _path_inside_lineage(root: Path, relative_path: str, *, label: str) -> Path:
    """Resolve a recorded relative path without allowing it to escape the lineage."""

    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise OfficialLineageError(f"{label} escapes the lineage: {relative_path}") from exc
    return candidate


def _raw_result_matches_summary(
    raw: Mapping[str, Any], summary: OfficialCellResult
) -> bool:
    """Project a raw container result to the exact persisted summary fields."""

    status = raw.get("status", "failed")
    if status not in {"succeeded", "failed", "timed_out"}:
        status = "failed"
    expected = {
        "status": status,
        "derivative_nmse": raw.get("derivative_nmse"),
        "validation_nmse": raw.get("validation_nmse"),
        "selected_term_count": raw.get("selected_term_count"),
        "equation_changed_on_shuffled_training": raw.get(
            "equation_changed_on_shuffled_training"
        ),
        "maximum_equation_prediction_delta": raw.get(
            "maximum_equation_prediction_delta"
        ),
        "wall_time_seconds": raw.get("wall_time_seconds"),
        "failure_reason": raw.get("failure_reason"),
        "result_hash": raw.get("result_hash"),
    }
    actual = {key: getattr(summary, key) for key in expected}
    return actual == expected


def _verify_outcome_execution_artifacts(
    *,
    config: OfficialLineageConfig,
    package: OfficialDevelopmentSearchPackage,
    approved_plan_hash: str,
    contract_hash: str,
    frozen: Mapping[str, Any],
    ledger: OfficialSpendLedger,
) -> None:
    """Prove raw cell bytes, summaries, and deterministic adjudication agree.

    This function is deliberately read-only.  It performs no container execution and
    does not create a second scientific result; it only replays deterministic joins and
    hashes before measured numbers may enter a model prompt.
    """

    from autoresearch.competition.plan_execution_contract import (
        load_prospective_plan_execution_contract,
        require_prospective_candidate_plan_alignment,
    )
    from autoresearch.schemas import file_hash

    root = config.work_dir.resolve()
    if tuple(package.stages_executed) != _OUTCOME_EXECUTION_STAGES:
        raise OfficialLineageError(
            "outcome requires the complete pilot -> baseline -> full execution chain"
        )
    if Path(package.identity.data_root).resolve() != config.data_root.resolve():
        raise OfficialLineageError(
            "signed package data root differs from the configured official data root"
        )

    identity_path = root / _IDENTITY_NAME
    identity = OfficialDevelopmentIdentity.model_validate_json(
        identity_path.read_text(encoding="utf-8")
    )
    if identity != package.identity:
        raise OfficialLineageError(
            "signed adjudication package differs from the frozen official identity"
        )
    if ledger.lineage_id != config.lineage_id or ledger.plan_hash != identity.plan_hash:
        raise OfficialLineageError(
            "official spend ledger is not bound to this lineage and frozen plan"
        )

    contract = load_prospective_plan_execution_contract(root)
    if (
        contract.approved_plan_hash != approved_plan_hash
        or contract.contract_hash != contract_hash
    ):
        raise OfficialLineageError(
            "execution contract changed while outcome inputs were being verified"
        )

    parent_candidates = _load_registry(config.candidates_dir / _CANDIDATE_REGISTRY)
    finalists = _load_registry(config.candidates_dir / _REVISED_REGISTRY)
    known = {item.candidate_id: item for item in (*parent_candidates, *finalists)}
    expected_candidates = tuple(known[key] for key in sorted(known))
    if package.candidates != expected_candidates:
        raise OfficialLineageError(
            "signed candidate registry differs from the executed candidate registries"
        )
    for candidate in package.candidates:
        source_path = _path_inside_lineage(
            root,
            candidate.source_relative_path,
            label=f"candidate source {candidate.candidate_id}",
        )
        if not source_path.is_file() or file_hash(source_path) != candidate.source_sha256:
            raise OfficialLineageError(
                f"candidate source hash mismatch: {candidate.candidate_id}"
            )
    selected_record = next(
        (
            item
            for item in package.candidates
            if item.candidate_id == package.selected_candidate_id
        ),
        None,
    )
    if selected_record is None or not selected_record.static_review_approved:
        raise OfficialLineageError(
            "signed adjudication has no statically approved selected candidate"
        )
    require_prospective_candidate_plan_alignment(
        candidates=[selected_record],
        contract=contract,
    )

    runner_matches = [
        path
        for path in (root / "runner").glob("*.py")
        if path.is_file() and file_hash(path) == package.identity.runner_sha256
    ]
    if not runner_matches:
        raise OfficialLineageError("frozen official runner is missing or hash-mismatched")

    stage_results: dict[str, tuple[OfficialCellResult, ...]] = {}
    verified_data: set[tuple[str, str]] = set()
    for stage in _OUTCOME_EXECUTION_STAGES:
        specs_path = config.cells_dir / f"{stage}-specs.json"
        results_path = config.cells_dir / f"{stage}-results.json"
        specs_payload = _load_json_object(specs_path, label=f"{stage} cell specifications")
        results_payload = _load_json_object(results_path, label=f"{stage} result summary")
        try:
            specs = tuple(
                OfficialCellSpec.model_validate(item)
                for item in specs_payload["specs"]
            )
            results = tuple(
                OfficialCellResult.model_validate(item)
                for item in results_payload["results"]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise OfficialLineageError(
                f"{stage} specifications or result summary failed validation: {exc}"
            ) from exc
        if results_payload.get("approved_research_plan_hash") != approved_plan_hash:
            raise OfficialLineageError(
                f"{stage} results do not bind the approved system-authored plan"
            )
        if results_payload.get("plan_execution_contract_hash") != contract_hash:
            raise OfficialLineageError(
                f"{stage} results do not bind the approved plan execution contract"
            )

        spec_by_id = {item.attempt_id: item for item in specs}
        result_by_id = {item.attempt_id: item for item in results}
        if len(spec_by_id) != len(specs) or len(result_by_id) != len(results):
            raise OfficialLineageError(f"{stage} contains duplicate official cell ids")
        if not set(result_by_id).issubset(spec_by_id):
            raise OfficialLineageError(
                f"{stage} contains a terminal result without a frozen cell spec"
            )
        if stage != "full" and set(spec_by_id) != set(result_by_id):
            raise OfficialLineageError(
                f"{stage} frozen cell set differs from its terminal result set"
            )
        if stage == "full" and set(spec_by_id) != set(result_by_id):
            missing_ids = set(spec_by_id) - set(result_by_id)
            missing_candidates = {spec_by_id[item].candidate_id for item in missing_ids}
            for candidate_id in missing_candidates:
                observed = [
                    item for item in results if item.candidate_id == candidate_id
                ]
                if not observed or any(item.status == "succeeded" for item in observed):
                    raise OfficialLineageError(
                        "full-stage cells are missing for a candidate without a "
                        f"recorded failed smoke gate: {candidate_id}"
                    )

        for spec in specs:
            spec_body = spec.model_dump(mode="json")
            spec_hash = spec_body.pop("spec_hash")
            if spec_hash != canonical_model_hash(spec_body):
                raise OfficialLineageError(
                    f"outer cell specification hash mismatch: {spec.attempt_id}"
                )
            data_key = (spec.data_relative_path, spec.data_sha256)
            if data_key not in verified_data:
                data_path = _path_inside_lineage(
                    config.data_root.resolve(),
                    spec.data_relative_path,
                    label=f"official data for {spec.attempt_id}",
                )
                if not data_path.is_file() or file_hash(data_path) != spec.data_sha256:
                    raise OfficialLineageError(
                        f"official input data hash mismatch: {spec.data_relative_path}"
                    )
                verified_data.add(data_key)

        for result in results:
            spec = spec_by_id[result.attempt_id]
            bound_identity = {
                "attempt_id": spec.attempt_id,
                "method_kind": spec.method_kind,
                "candidate_id": spec.candidate_id,
                "stage": spec.stage,
                "system_name": spec.system_name,
                "data_type": spec.data_type,
                "condition": spec.condition,
                "seed": spec.seed,
            }
            result_identity = {key: getattr(result, key) for key in bound_identity}
            if result_identity != bound_identity or result.stage != stage:
                raise OfficialLineageError(
                    f"result summary changed its frozen cell identity: {result.attempt_id}"
                )

            raw_dir = config.cells_dir / stage / result.attempt_id
            raw_spec = _load_json_object(
                raw_dir / "spec.json", label=f"raw execution spec {result.attempt_id}"
            )
            raw_result = _load_json_object(
                raw_dir / "result.json", label=f"raw execution result {result.attempt_id}"
            )
            raw_spec_hash = raw_spec.get("spec_hash")
            raw_spec_body = dict(raw_spec)
            raw_spec_body.pop("spec_hash", None)
            if raw_spec_hash != canonical_model_hash(raw_spec_body):
                raise OfficialLineageError(
                    f"raw execution spec hash mismatch: {result.attempt_id}"
                )
            expected_attempt = {
                "attempt_id": spec.attempt_id,
                "system_name": spec.system_name,
                "condition": spec.condition,
                "data_type": spec.data_type,
                "seed": spec.seed,
            }
            if (
                raw_spec.get("attempt") != expected_attempt
                or raw_spec.get("method_kind") != spec.method_kind
                or raw_spec.get("expected_data_sha256") != spec.data_sha256
                or raw_spec.get("candidate_source_sha256")
                != spec.candidate_source_sha256
                or raw_spec.get("split_policy") != _SPLIT_POLICY
                or raw_spec.get("baseline_method")
                != baseline_method_for(spec.data_type)
                or raw_spec.get("maximum_fit_seconds")
                != int(frozen["search_budget"]["maximum_seconds_per_cell"]) - 30
                or raw_spec.get("maximum_predict_seconds") != 10
            ):
                raise OfficialLineageError(
                    f"raw execution spec differs from the frozen outer spec: "
                    f"{result.attempt_id}"
                )
            baseline_runner_hash = raw_spec.get("expected_baseline_runner_sha256")
            if (
                not isinstance(baseline_runner_hash, str)
                or len(baseline_runner_hash) != 64
                or any(
                    marker not in "0123456789abcdef"
                    for marker in baseline_runner_hash
                )
            ):
                raise OfficialLineageError(
                    f"raw execution spec lacks a baseline runner hash: "
                    f"{result.attempt_id}"
                )
            if raw_result.get("spec_hash") != raw_spec_hash:
                raise OfficialLineageError(
                    f"raw result does not bind its execution spec: {result.attempt_id}"
                )
            raw_result_hash = raw_result.get("result_hash")
            raw_result_body = dict(raw_result)
            raw_result_body.pop("result_hash", None)
            if raw_result_hash != canonical_model_hash(raw_result_body):
                raise OfficialLineageError(
                    f"raw execution result hash mismatch: {result.attempt_id}"
                )
            if result.result_hash != raw_result_hash or not _raw_result_matches_summary(
                raw_result, result
            ):
                raise OfficialLineageError(
                    f"stage summary differs from the raw result: {result.attempt_id}"
                )

        disk_ids = {
            path.parent.name
            for path in (config.cells_dir / stage).glob("*/result.json")
        }
        if disk_ids != set(result_by_id):
            raise OfficialLineageError(
                f"{stage} raw result set differs from the stage summary"
            )
        stage_results[stage] = results

    flattened_results = tuple(
        item
        for stage in _OUTCOME_EXECUTION_STAGES
        for item in stage_results[stage]
    )
    if package.cell_results != flattened_results:
        raise OfficialLineageError(
            "signed adjudication package differs from the verified stage summaries"
        )

    full = stage_results["full"]
    baseline = stage_results["baseline"]
    selected, basis = select_official_candidate(candidates=finalists, results=full)
    effects = compute_system_effects(
        candidate_id=selected or "",
        candidate_results=full,
        baseline_results=baseline,
    )
    summary = aggregate_paired_effects(effects)
    selected_cells = [item for item in full if item.candidate_id == selected]
    gate_checks = evaluate_frozen_gate(
        estimand=dict(frozen["estimand"]),
        summary=summary,
        candidate_cells=selected_cells,
        baseline_results=baseline,
        remaining_budget=ledger.remaining(),
    )
    expected_metrics = {
        "overall_median_log_effect": summary.get("overall_median_log_effect"),
        "bootstrap_lower": summary.get("bootstrap_lower"),
        "bootstrap_upper": summary.get("bootstrap_upper"),
        "ode_stratum_median": summary.get("ode_stratum_median"),
        "pde_stratum_median": summary.get("pde_stratum_median"),
    }
    observed_metrics = {key: getattr(package, key) for key in expected_metrics}
    if (
        package.selected_candidate_id != selected
        or package.selection_basis != basis
        or package.system_effects != tuple(effects)
        or observed_metrics != expected_metrics
        or package.minimum_overall_log_effect
        != float(frozen["estimand"]["minimum_overall_log_effect"])
        or package.gate_checks != gate_checks
        or package.search_freeze_receipt_issued != frozen_gate_receipt(gate_checks)
    ):
        raise OfficialLineageError(
            "signed adjudication cannot be reproduced from the verified real results"
        )


def _load_verified_outcome_inputs(
    config: OfficialLineageConfig,
    *,
    config_path: Path | str = Path("config.yaml"),
) -> tuple[Path, OfficialDevelopmentSearchPackage, str]:
    """Load and verify every authoritative input before an outcome model call."""

    from autoresearch.competition.plan_execution_contract import (
        compile_system_authored_plan_execution_contract,
        load_prospective_plan_execution_contract,
    )
    from autoresearch.competition.scientific_contract_recovery import (
        load_scientific_contract_recovery_plan,
    )
    from autoresearch.competition.system_authored_plan import (
        authored_plan_non_chinese_fields,
    )
    from autoresearch.research.plan_confirmation import require_approved_plan
    from autoresearch.schemas import ResearchPlan

    root = config.work_dir.resolve()
    artifact, plan, decision = _load_formal_system_plan_artifact(
        config,
        config_path=config_path,
    )
    if not isinstance(plan, ResearchPlan):
        raise OfficialLineageError("official research plan failed schema validation")
    plan_payload = plan.model_dump(mode="json")
    if artifact.plan != plan_payload or artifact.plan_hash != canonical_model_hash(
        plan_payload
    ):
        raise OfficialLineageError(
            "approved official plan is not the exact system-authored plan"
        )
    non_chinese_plan = authored_plan_non_chinese_fields(plan)
    if non_chinese_plan:
        raise OfficialLineageError(
            "official plan contains non-Chinese scientific fields: "
            f"{list(non_chinese_plan)}"
        )
    approved_plan_hash = require_approved_plan(plan=plan, decision=decision)
    contract = load_prospective_plan_execution_contract(root)
    if contract != compile_system_authored_plan_execution_contract(artifact):
        raise OfficialLineageError(
            "retained execution contract differs from the approved official plan"
        )
    if contract.approved_plan_hash != approved_plan_hash:
        raise OfficialLineageError(
            "execution contract does not bind the approved official plan hash"
        )

    frozen_plan = load_scientific_contract_recovery_plan(config.frozen_plan_path)
    frozen, identity, ledger = _load_frozen_read_only(config)
    if identity.plan_hash != frozen_plan.plan_hash:
        raise OfficialLineageError(
            "frozen official identity does not bind the hash-valid parent plan"
        )
    package_path = root / _PACKAGE_NAME
    package = OfficialDevelopmentSearchPackage.model_validate_json(
        package_path.read_text(encoding="utf-8")
    )
    if Path(package.output_path).resolve() != package_path:
        raise OfficialLineageError(
            "signed adjudication package output path changed after adjudication"
        )
    if package.identity != identity:
        raise OfficialLineageError(
            "signed adjudication package does not bind the retained official identity"
        )
    _verify_outcome_execution_artifacts(
        config=config,
        package=package,
        approved_plan_hash=approved_plan_hash,
        contract_hash=contract.contract_hash,
        frozen=frozen,
        ledger=ledger,
    )
    return package_path, package, artifact.plan_hash


def run_outcome_stage(
    config: OfficialLineageConfig,
    *,
    completion: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
) -> LineageStageReport:
    """Let the configured model author the Chinese result interpretation.

    All orchestration text below is fixed process metadata.  The model authors every
    scientific sentence through ``author_outcome_interpretation``; this stage only
    validates immutable inputs and deterministic output contracts.
    """

    from autoresearch.competition.model_authorship import (
        load_bound_authorship_receipt,
        outcome_authored_fields,
    )
    from autoresearch.competition.system_authored_outcome import (
        SystemAuthoredOutcome,
        author_outcome_interpretation,
        authored_interpretation_non_chinese_fields,
    )
    from autoresearch.config import ConfigParser, SystemConfig

    root = config.work_dir.resolve()
    outcome_path = root / _OUTCOME_NAME
    if outcome_path.exists():
        raise OfficialLineageError(
            "an outcome artifact already exists; refusing to overwrite model-authored "
            "scientific provenance"
        )
    package_path, package, system_plan_hash = _load_verified_outcome_inputs(
        config,
        config_path=config_path,
    )
    outcome = author_outcome_interpretation(
        lineage_id=config.lineage_id,
        package_path=package_path,
        frozen_plan_path=config.frozen_plan_path,
        output_dir=root,
        completion=completion,
        config_path=config_path,
        env_path=env_path,
        require_chinese=True,
    )
    post_package_path, post_package, post_plan_hash = _load_verified_outcome_inputs(
        config,
        config_path=config_path,
    )
    if (
        post_package_path != package_path
        or post_package != package
        or post_plan_hash != system_plan_hash
    ):
        raise OfficialLineageError(
            "official plan or execution evidence changed during outcome authoring"
        )
    reloaded = SystemAuthoredOutcome.model_validate_json(
        outcome_path.read_text(encoding="utf-8")
    )
    if reloaded != outcome or Path(reloaded.output_path).resolve() != outcome_path:
        raise OfficialLineageError(
            "persisted system-authored outcome differs from the returned artifact"
        )
    if reloaded.lineage_id != config.lineage_id or reloaded.package_hash != package.package_hash:
        raise OfficialLineageError(
            "system-authored outcome does not bind this lineage and signed package"
        )
    non_chinese = authored_interpretation_non_chinese_fields(reloaded.interpretation)
    if non_chinese:
        raise OfficialLineageError(
            "system-authored outcome contains non-Chinese scientific fields: "
            f"{list(non_chinese)}"
        )
    gate_passed = bool(package.gate_checks) and all(package.gate_checks.values())
    if (
        not reloaded.accepted
        or reloaded.refusal_reasons
        or not reloaded.traceability.passed
        or reloaded.traceability.untraceable_numbers
        or reloaded.relation_audit is None
        or not reloaded.relation_audit.passed
        or reloaded.frozen_gate_passed != gate_passed
        or not reloaded.verdict_consistent_with_gate
        or reloaded.interpretation.claims_frozen_gate_passed != gate_passed
    ):
        raise OfficialLineageError(
            "system-authored outcome failed Chinese, numeric, relation, or frozen-gate audit: "
            f"{list(reloaded.refusal_reasons)}"
        )

    receipt = load_bound_authorship_receipt(
        lineage_dir=root,
        relative_path=reloaded.authorship_receipt_relative_path,
        expected_hash=reloaded.authorship_receipt_hash,
        artifact_kind="outcome_interpretation",
        expected_model_name=reloaded.model_name,
        expected_fields=outcome_authored_fields(
            reloaded.interpretation.model_dump(mode="json")
        ),
    )
    details = receipt.usage.get("completion_tokens_details")
    receipt_reasoning_tokens = 0
    if isinstance(details, Mapping):
        receipt_reasoning_tokens = int(details.get("reasoning_tokens") or 0)
    if (
        reloaded.reasoning_tokens <= 0
        or receipt_reasoning_tokens != reloaded.reasoning_tokens
        or receipt.reasoning_transport == "absent"
        or receipt.reasoning_content is None
        or not receipt.reasoning_content.strip()
    ):
        raise OfficialLineageError(
            "outcome reasoning provenance is absent or inconsistent with its receipt"
        )

    parsed_config = ConfigParser().parse_file(config_path, model_type=SystemConfig)
    if not isinstance(parsed_config, SystemConfig):
        raise OfficialLineageError("configured model file did not parse as SystemConfig")
    configured = parsed_config.deployment.llm
    if (
        receipt.provider != configured.provider
        or receipt.base_url.rstrip("/") != configured.base_url.rstrip("/")
        or receipt.model_name != configured.model_name
    ):
        raise OfficialLineageError(
            "outcome authorship receipt model identity differs from the configured model"
        )

    return LineageStageReport(
        lineage_id=config.lineage_id,
        stage="outcome",
        lines=(
            "=== 阶段 outcome：系统自主中文结果解释",
            f"  系统计划哈希：{system_plan_hash}",
            f"  签名结果包哈希：{package.package_hash}",
            f"  结果解释哈希：{reloaded.outcome_hash}",
            f"  配置模型：{reloaded.model_name}",
            f"  推理令牌：{reloaded.reasoning_tokens}",
            "  中文科研字段：通过",
            "  数值溯源与关系复算：通过",
            "  人工补写科研散文：0",
            "  本阶段执行实验、批准、发布或提交：均为 false",
        ),
        package_path=package.output_path,
        search_freeze_receipt_issued=package.search_freeze_receipt_issued,
        outcome_path=reloaded.output_path,
        outcome_hash=reloaded.outcome_hash,
        outcome_accepted=True,
    )


def run_lineage_stage(
    config: OfficialLineageConfig,
    *,
    stage: LineageStage,
    decided_by: str = "operator",
    notes: str = "",
    package_output_dir: Path | str | None = None,
    outcome_completion: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
    outcome_config_path: Path | str = Path("config.yaml"),
    outcome_env_path: Path | str = Path(".env"),
) -> LineageStageReport:
    """Drive exactly one stage of one preregistered lineage.

    Acquires an exclusive advisory lock on the lineage directory before doing any
    work. A concurrent invocation on the same directory is refused immediately with
    an OfficialLineageError rather than silently racing and corrupting the ledger and
    registry (P-20260807-090).
    """

    with exclusive_lineage_lock(config.work_dir, stage=stage):
        if stage == "plan":
            return run_plan_stage(config)
        if stage == "approve":
            if not notes.strip():
                raise OfficialLineageError(
                    "an approval must carry the reviewer's own notes; the driver will "
                    "not invent the reasoning a human is accountable for"
                )
            return run_approve_stage(config, decided_by=decided_by, notes=notes)
        if stage == "generate":
            return run_generate_stage(config)
        if stage == "revise":
            return run_revise_stage(config)
        if stage == "adjudicate":
            return run_adjudicate_stage(config, package_output_dir=package_output_dir)
        if stage == "outcome":
            if package_output_dir is not None:
                raise OfficialLineageError(
                    "outcome reads only the canonical adjudication package inside the "
                    "lineage; --package-output-dir is adjudicate-only"
                )
            return run_outcome_stage(
                config,
                completion=outcome_completion,
                config_path=outcome_config_path,
                env_path=outcome_env_path,
            )
        return run_execution_stage(config, stage=stage)
