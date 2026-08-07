"""Lineage v6: the SYSTEM authors the plan, executed under an exclusive lineage lock.

Why this lineage exists rather than a continuation of v5
-------------------------------------------------------
`P-20260807-090`: I launched `generate` three times concurrently against
`task2698-system-authored-lineage-v1`. Each process loaded its own copy of the spend
ledger, so the persisted ledger recorded ONE `generate-gen1` entry of 8 candidates
while up to 24 were authored, and last-writer-wins interleaved
`candidate-registry.json` against `candidate.py`, so 50 of 80 pilot cells failed with
`candidate source bytes differ from the frozen record`. That lineage's budget ledger
is not truthful and its pilot ranking is not a scientific signal, so it is RETAINED
UNCHANGED as evidence of the defect and superseded here rather than reinterpreted.

`run_lineage_stage` now holds an exclusive lock for the whole stage, so the operator
error that produced `P-20260807-090` is refused by the engine instead of depending on
my discipline.

Usage:
    python _v6.py prereg     # policy, breadth, system-authored plan, approval
    python _v6.py <stage>    # generate | pilot | revise | baseline | full | adjudicate
    python _v6.py interpret  # the system reads its own signed result
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

LINEAGE_ID = "task2699-system-authored-lineage-v2"
WORK = Path("runs/manual-live") / LINEAGE_ID
PARENT = Path("runs/manual-live/task2696-stratified-gate-lineage-v1")
AUTHORED_PLAN_LINEAGE = Path("runs/manual-live/task2697-system-authored-plan-v1")
# The superseded v5 lineage is cited as evidence, so the new plan can see WHY it exists.
SUPERSEDED = Path("runs/manual-live/task2698-system-authored-lineage-v1")
RETAINED = Path("runs/manual-live/task2663-conformant-v1")
RECHECK = Path("runs/manual-live/task2663-term-cap-recheck-v2")
AUTHORED = Path(
    "runs/manual-live/task2682-frozen-protocol-self-correction-reasoning-v5/"
    "frozen-protocol-contradiction-package.json"
)
FROZEN_PLAN = Path(
    "runs/manual-live/task2661-scientific-contract-recovery-plan-v1/"
    "scientific-contract-recovery-plan.json"
)
AUTONOMOUS_PLAN = Path(
    "runs/manual-live/task2651-autonomous-recovery-plan-v1/"
    "autonomous-research-plan.json"
)
DATA_ROOT = Path(
    "runs/manual-live/task259-mdbench-official-v1/data/prepared/processed-9fe483c64ad6"
)
BREADTH_PACKAGE = (
    Path("runs/manual-live/task2693-unified-lineage-v1")
    / "pilot-breadth-v1"
    / "pilot-breadth-contradiction-package.json"
)


def prereg() -> None:
    from autoresearch.competition.official_baseline_policy import (
        assert_policy_precedes_numeric_payload,
        preregister_baseline_policy,
    )
    from autoresearch.competition.preregistered_stage_breadth import (
        preregister_stage_breadth,
    )
    from autoresearch.competition.preregistered_stratum_breadth import (
        derive_available_breadth,
    )
    from autoresearch.competition.system_authored_plan import author_research_plan
    from autoresearch.research.plan_confirmation import (
        load_plan_decision,
        record_plan_decision,
        require_approved_plan,
    )

    WORK.mkdir(parents=True, exist_ok=True)
    identity = json.loads(
        (RETAINED / "official-development-identity.json").read_text(encoding="utf-8")
    )
    policy = preregister_baseline_policy(
        lineage_id=LINEAGE_ID,
        parent_lineage_id="task2663-conformant-v1",
        frozen_plan_path=FROZEN_PLAN,
        authored_decision_package_path=AUTHORED,
        parent_identity_path=RETAINED / "official-development-identity.json",
        prior_baseline_results_path=RETAINED / "cells" / "baseline-results.json",
        prior_full_results_path=RETAINED / "cells" / "full-results.json",
        zero_term_evidence_root=RECHECK,
        child_runner_sha256=str(identity["runner_sha256"]),
        output_dir=WORK,
    )
    assert_policy_precedes_numeric_payload(output_dir=WORK, lineage_dir=WORK)
    panel = json.loads(AUTONOMOUS_PLAN.read_text(encoding="utf-8"))["development_panel"]
    breadth = preregister_stage_breadth(
        lineage_id=LINEAGE_ID,
        frozen_plan_path=FROZEN_PLAN,
        baseline_policy_hash=policy.policy_hash,
        contradiction_package_path=BREADTH_PACKAGE,
        panel=panel,
        excluded_system_names=policy.excluded_system_names,
        output_dir=WORK,
    )
    available = derive_available_breadth(
        members=panel["systems"],
        stratum_key="data_type",
        excluded_names=policy.excluded_system_names,
    )

    frozen = json.loads(FROZEN_PLAN.read_text(encoding="utf-8"))
    pkg = json.loads(
        (PARENT / "official-development-search-package.json").read_text(encoding="utf-8")
    )
    full = json.loads(
        (PARENT / "cells" / "full-results.json").read_text(encoding="utf-8")
    )["results"]
    failures: Counter = Counter()
    for cell in full:
        if cell.get("status") != "succeeded":
            failures[str(cell.get("failure_reason") or "")[:160]] += 1

    context = {
        "frozen_constraints_you_may_not_change": {
            "estimand": frozen["estimand"],
            "contract_gate": frozen["contract_gate"],
            "search_budget": {
                k: v
                for k, v in frozen["search_budget"].items()
                if isinstance(v, int | float | str)
            },
        },
        "effective_panel_after_preregistered_exclusion": {
            "note": (
                "This is the panel you will actually receive. It is narrower than the "
                "frozen budget because two systems were excluded before any number was "
                "observed: their pinned baseline cannot produce a loss at all."
            ),
            "excluded_system_names": list(policy.excluded_system_names),
            "available_members_per_stratum": available,
            "preregistered_pilot_breadth": {
                "ode": breadth.pilot_ode_count,
                "pde": breadth.pilot_pde_count,
                "total": breadth.pilot_system_count,
            },
            "paired_system_count": policy.paired_system_count,
        },
        "your_own_retained_evidence_from_the_previous_lineage": {
            "lineage_id": PARENT.name,
            "selected_candidate_id": pkg.get("selected_candidate_id"),
            "overall_median_log_effect": pkg.get("overall_median_log_effect"),
            "bootstrap_lower": pkg.get("bootstrap_lower"),
            "bootstrap_upper": pkg.get("bootstrap_upper"),
            "ode_stratum_median": pkg.get("ode_stratum_median"),
            "pde_stratum_median": pkg.get("pde_stratum_median"),
            "gate_checks": pkg.get("gate_checks"),
            "per_system_paired_effects": [
                {
                    "system_name": e["system_name"],
                    "data_type": e["data_type"],
                    "paired_log_effect": e["paired_log_effect"],
                    "candidate_median_loss": e.get("candidate_median_loss"),
                    "baseline_median_loss": e.get("baseline_median_loss"),
                }
                for e in pkg.get("system_effects", [])
            ],
            "failure_reason_counts": dict(failures),
            "total_full_cells": len(full),
            "succeeded_full_cells": sum(
                1 for c in full if c.get("status") == "succeeded"
            ),
        },
        "what_you_must_decide_yourself": [
            "what problem this lineage should attack, given the above",
            "what mechanism you believe is responsible",
            "what you will test and how, within the frozen budget",
            "what observation would REFUTE your expectation",
        ],
    }

    plan_dir = WORK / "plan"
    plan_dir.mkdir(parents=True, exist_ok=True)
    artifact = author_research_plan(
        lineage_id=LINEAGE_ID,
        project_id=LINEAGE_ID,
        candidate_id=f"candidate_{str(frozen['plan_hash'])[:12]}",
        frozen_context=context,
        evidence_paths=[
            FROZEN_PLAN,
            PARENT / "official-development-search-package.json",
            PARENT / "cells" / "full-results.json",
            PARENT / "system-authored-outcome.json",
            AUTHORED_PLAN_LINEAGE / "system-authored-research-plan.json",
            SUPERSEDED / "system-authored-research-plan.json",
            Path(policy.output_path),
            Path(breadth.output_path),
        ],
        output_dir=WORK,
        container_entry_points=("/harness/runner.py",),
    )

    from autoresearch.schemas import ResearchPlan

    plan = ResearchPlan.model_validate(artifact.plan)
    (plan_dir / "research-plan.json").write_text(
        json.dumps(plan.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    record_plan_decision(
        plan=plan,
        decision="approve",
        decided_by="operator-delegated-agent (Kiro, delegated authority 2026-08-04)",
        notes=(
            "OPERATOR-DELEGATED SCOPE AUTHORIZATION for lineage v6. Delegated blanket "
            "authority; NOT a human scientific review, and no human read these "
            "numbers.\n\n"
            "WHY THIS LINEAGE REPLACES v5: lineage v5 "
            "(task2698-system-authored-lineage-v1) was corrupted by concurrent stage "
            "execution, recorded as `P-20260807-090`. Three generate processes ran "
            "against one directory, so its spend ledger understates real spend and 50 "
            "of 80 pilot cells failed on a source-hash mismatch rather than on "
            "science. That lineage is retained unchanged and is NOT reinterpreted as "
            "conformant. `run_lineage_stage` now takes an exclusive per-lineage lock, "
            "so the same operator error is refused by the engine.\n\n"
            "WHAT IS AUTHORED BY THE SYSTEM: every prose field of the plan being "
            "approved came from the model and was accepted by deterministic graders "
            "checking numeric traceability against retained evidence, falsifiability "
            "of the expectation, absence of any claimed-but-unobserved result, that "
            "every cited artifact exists on disk, and the shared plan quality rubric. "
            "The agent supplied only frozen constraints, the effective narrowed panel, "
            "and the system's own retained evidence. No hypothesis, mechanism, title, "
            "or framing was supplied.\n\n"
            "I am approving SCOPE, not science: open this one preregistered lineage "
            "and spend the frozen 266.1 budget once inside it. I am not endorsing the "
            "system's hypothesis, and I did not choose it.\n\n"
            "NOT AUTHORIZED: any scientific conclusion; any effect direction or "
            "magnitude; issuing a receipt; weakening any frozen threshold, estimand, "
            "gate, or budget parameter; combining candidates' results; repairing "
            "candidate code by hand; unsealing the confirmation panel; publication.\n\n"
            "A NULL OR NEGATIVE RESULT IS A VALID PREREGISTERED OUTCOME and will be "
            "reported as one."
        ),
        output_dir=plan_dir,
    )
    loaded = load_plan_decision(project_id=plan.project_id, output_dir=plan_dir)
    assert loaded is not None
    print(
        json.dumps(
            {
                "policy_hash": policy.policy_hash,
                "breadth_hash": breadth.breadth_hash,
                "effective_available_per_stratum": available,
                "authored_plan_artifact": artifact.artifact_hash,
                "authored_plan_hash": artifact.plan_hash,
                "authoring_attempts": artifact.authoring_attempts,
                "reasoning_tokens": artifact.reasoning_tokens,
                "quality_score": artifact.guard_report.quality_gate_score,
                "hand_written_prose_fields": artifact.hand_written_prose_field_count,
                "gate_binds": require_approved_plan(plan=plan, decision=loaded)[:16],
                "authored_title": plan.title,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def interpret() -> None:
    """Let the system read its OWN signed result, audited against its own evidence."""

    from autoresearch.competition.system_authored_outcome import (
        author_outcome_interpretation,
    )

    outcome = author_outcome_interpretation(
        lineage_id=LINEAGE_ID,
        package_path=WORK / "official-development-search-package.json",
        frozen_plan_path=FROZEN_PLAN,
        output_dir=WORK,
    )
    print(
        json.dumps(
            {
                "accepted": outcome.accepted,
                "verdict": outcome.interpretation.verdict,
                "frozen_gate_passed": outcome.frozen_gate_passed,
                "verdict_consistent_with_gate": outcome.verdict_consistent_with_gate,
                "numbers_checked": outcome.traceability.checked_number_count,
                "numbers_traceable": outcome.traceability.traceable_number_count,
                "untraceable": list(outcome.traceability.untraceable_numbers),
                "refusal_reasons": list(outcome.refusal_reasons),
                "reasoning_tokens": outcome.reasoning_tokens,
                "outcome_hash": outcome.outcome_hash,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def stage(name: str) -> None:
    from autoresearch.competition.official_lineage import (
        OfficialLineageConfig,
        run_lineage_stage,
    )

    config = OfficialLineageConfig(
        lineage_id=LINEAGE_ID,
        work_dir=WORK,
        frozen_plan_path=FROZEN_PLAN,
        autonomous_plan_path=AUTONOMOUS_PLAN,
        data_root=DATA_ROOT,
    )
    report = run_lineage_stage(config, stage=name)  # type: ignore[arg-type]
    for line in report.lines:
        print(line)
    if report.package_path:
        print("package:", report.package_path)
    if report.search_freeze_receipt_issued is not None:
        print("receipt:", report.search_freeze_receipt_issued)


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "prereg":
        prereg()
    elif command == "interpret":
        interpret()
    else:
        stage(command)
