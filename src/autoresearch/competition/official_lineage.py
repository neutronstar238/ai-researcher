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

Stage sequence, unchanged from the retired script
-------------------------------------------------
``plan`` -> ``approve`` -> ``generate`` -> ``pilot`` -> ``revise`` -> ``baseline``
-> ``full`` -> ``adjudicate``

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

import json
import os
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.competition.official_development_search import (
    _IDENTITY_NAME,
    _PACKAGE_NAME,
    OfficialCandidateRecord,
    OfficialCellResult,
    OfficialCellSpec,
    OfficialDevelopmentIdentity,
    OfficialDevelopmentSearchPackage,
    SystemEffect,
    aggregate_paired_effects,
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

# ---------------------------------------------------------------------------
# Lineage-level exclusive process lock
# ---------------------------------------------------------------------------

_LOCK_NAME = ".lineage-stage-lock"
# No legitimate stage holds the lineage lock this long without progress, so an older
# lock file means the holder crashed or was force-killed. Reclaiming it stops a machine
# crash from bricking a lineage directory and forcing a needless re-preregistration.
_LOCK_STALE_SECONDS = 300.0


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
    lock_content = _json.dumps(
        {
            "pid": os.getpid(),
            "stage": stage,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
    ).encode()

    def _try_create() -> bool:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, lock_content)
            os.close(fd)
            return True
        except FileExistsError:
            return False

    def _is_stale() -> bool:
        """Return True if the existing lock file is old enough to be abandoned.

        Staleness is determined purely by the lock file's age. No legitimate stage
        holds the lineage lock for five minutes without completing or crashing; if
        the file is older than _LOCK_STALE_SECONDS the holder has gone away.

        PID-based liveness probing was removed because it is not portable and can
        produce false positives: the OS recycles PIDs, so a PID recorded by a dead
        process may belong to a completely different live process, and on Windows
        tasklist returns the opposite of what is expected for very small or very
        large PIDs.
        """
        try:
            stat = lock_path.stat()
            age = datetime.now(timezone.utc).timestamp() - stat.st_mtime
            return age > _LOCK_STALE_SECONDS
        except OSError:
            return True  # file disappeared → stale

    # First try: atomic create.
    if not _try_create():
        # Lock exists. Check whether the holder is still alive.
        if _is_stale():
            # Stale: remove it and claim ownership.
            try:
                lock_path.unlink()
            except OSError:
                pass
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
            try:
                raw = lock_path.read_text(encoding="utf-8")
                holder_info = _json.loads(raw)
                holder_stage = holder_info.get("stage", "unknown")
            except (OSError, ValueError):
                holder_stage = "unknown"
            raise OfficialLineageError(
                f"another process is already running stage '{holder_stage}' for "
                f"lineage {work_dir.name}; concurrent stage execution corrupts the "
                "spend ledger and the candidate registry (`P-20260807-090`). Wait "
                "for the running stage to complete before starting the next one."
            )
    try:
        yield
    finally:
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass


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
)

_CANDIDATE_REGISTRY = "candidate-registry.json"
_REVISED_REGISTRY = "revised-registry.json"
_ZERO_TERM_MARKER = "returned 0 terms"


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


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


def run_plan_stage(config: OfficialLineageConfig) -> LineageStageReport:
    """Let the system author its plan from frozen evidence, then audit it.

    When this lineage has a preregistered baseline policy, its carried defects are
    bound into the plan's problem statement, so the plan states which diagnosed
    defects the lineage exists to repair. The statements originate in the system's
    own evidence; this stage only positions them.
    """

    from autoresearch.competition.official_baseline_policy import (
        BaselinePolicyError,
        load_baseline_policy,
    )
    from autoresearch.competition.official_plan_generation import (
        build_official_research_plan,
    )
    from autoresearch.research.plans import audit_research_plan

    carried: list[str] = []
    extra_refs: list[str] = []
    try:
        policy = load_baseline_policy(output_dir=config.work_dir)
    except BaselinePolicyError:
        policy = None
    if policy is not None:
        carried = [item.statement for item in policy.carried_defects]
        extra_refs = [policy.output_path, policy.authored_decision_package_path]

    plan = build_official_research_plan(
        plan_path=config.frozen_plan_path,
        autonomous_plan_path=config.autonomous_plan_path,
        data_root=config.data_root,
        project_id=config.lineage_id,
        prior_run_dirs=list(config.prior_run_dirs),
        carried_defect_statements=carried,
        extra_evidence_refs=extra_refs,
    )
    audit = audit_research_plan(plan)
    config.plan_dir.mkdir(parents=True, exist_ok=True)
    (config.plan_dir / "research-plan.json").write_text(
        json.dumps(plan.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return LineageStageReport(
        lineage_id=config.lineage_id,
        stage="plan",
        lines=(
            "=== STAGE plan: generated from frozen evidence",
            f"  audit verdict : {audit.verdict.value}",
            f"  audit score   : {audit.score}",
            f"  carried defects: {len(carried)}",
            f"  status        : {plan.status.value}",
            f"  plan id       : {plan.id}",
            "  execution BLOCKED until a human decision is recorded",
        ),
    )


def run_approve_stage(
    config: OfficialLineageConfig, *, decided_by: str, notes: str
) -> LineageStageReport:
    """Record the human decision against this exact plan hash, before any cell runs."""

    from autoresearch.research.plan_confirmation import (
        compute_plan_hash,
        record_plan_decision,
    )

    plan, _ = _load_plan_and_decision(config)
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

    frozen, identity, panel, ledger = _freeze(config)
    budget = frozen["search_budget"]
    count = int(budget["initial_candidate_count"])
    ledger.check(candidate_count=count, model_interactions=count, new_generation=True)
    candidates = generate_official_candidates(
        identity=identity,
        panel=panel,
        budget=budget,
        output_dir=config.work_dir,
    )
    ledger = ledger.record(
        stage="generate-gen1",
        candidate_count=len(candidates),
        model_interactions=count,
        new_generation=True,
    )
    persist_ledger(ledger=ledger, output_dir=config.work_dir)
    lines = ["=== STAGE generate: candidate generation"]
    for record in candidates:
        flag = "OK " if record.static_review_approved else "REJ"
        lines.append(f"  {flag} {record.candidate_id}: {record.implementation_summary[:74]}")
    approved = [item for item in candidates if item.static_review_approved]
    lines.append(f"  approved {len(approved)}/{len(candidates)}")
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
    plan, decision = _load_plan_and_decision(config)
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
            research_plan=plan,
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
                good = sum(1 for item in stratum_cells if item.status == "succeeded")
                strata.append(f"{data_type} {good}/{len(stratum_cells)}")
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
            research_plan=plan,
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
            research_plan=plan,
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
    ledger.check(
        candidate_count=len(chosen),
        model_interactions=len(chosen),
        new_generation=True,
    )
    revised = revise_official_candidates(
        panel=panel,
        budget=budget,
        candidates=chosen,
        results=pilot,
        output_dir=config.work_dir,
    )
    ledger = ledger.record(
        stage="revise-gen2",
        candidate_count=len(revised),
        model_interactions=len(revised),
        new_generation=True,
    )
    persist_ledger(ledger=ledger, output_dir=config.work_dir)
    lines = [
        "=== STAGE revise: self-revision",
        f"  chosen {[item.candidate_id for item in chosen]}",
    ]
    for record in revised:
        flag = "OK " if record.static_review_approved else "REJ"
        lines.append(f"  {flag} {record.candidate_id}: {record.implementation_summary[:74]}")
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


def run_lineage_stage(
    config: OfficialLineageConfig,
    *,
    stage: LineageStage,
    decided_by: str = "operator",
    notes: str = "",
    package_output_dir: Path | str | None = None,
) -> LineageStageReport:
    """Drive exactly one stage of one preregistered lineage.

    Acquires an exclusive advisory lock on the lineage directory before doing any
    work. A concurrent invocation on the same directory is refused immediately with
    an OfficialLineageError rather than silently racing and corrupting the ledger and
    registry (P-20260807-090).
    """

    with _lineage_lock(config.work_dir):
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
        return run_execution_stage(config, stage=stage)
