"""Lineage v5: the SYSTEM authors the plan that gates its own execution.

Every prior lineage executed a plan whose prose I wrote. This one executes a plan the
system authored, validated by deterministic graders, written to the exact path the
lineage's approval gate reads.

Fixes my omission from `P-20260804-088`: the authoring context now carries the
EFFECTIVE narrowed panel alongside the frozen budget, so the system reasons about the
panel it will actually get rather than the pre-exclusion one.

Usage:
    python _v5.py prereg     # policy, breadth, system-authored plan, approval
    python _v5.py <stage>
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

LINEAGE_ID = "task2698-system-authored-lineage-v1"
WORK = Path("runs/manual-live") / LINEAGE_ID
PARENT = Path("runs/manual-live/task2696-stratified-gate-lineage-v1")
AUTHORED_PLAN_LINEAGE = Path("runs/manual-live/task2697-system-authored-plan-v1")
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

    # THE FIX for P-20260804-088: tell the system the panel it will actually receive,
    # not the pre-exclusion frozen budget it cannot have.
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
            Path(policy.output_path),
            Path(breadth.output_path),
        ],
        output_dir=WORK,
        # The ONLY real entry point. Declaring it stops the system inventing a
        # plausible-looking container path to satisfy the runnability guard.
        container_entry_points=("/harness/runner.py",),
    )

    # Write the SYSTEM'S plan where the lineage's approval gate reads it. Previous
    # lineages had a templated plan here; this one is authored.
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
            "OPERATOR-DELEGATED SCOPE AUTHORIZATION for lineage v5. Delegated blanket "
            "authority; NOT a human scientific review, and no human read these "
            "numbers.\n\n"
            "WHAT IS DIFFERENT ABOUT THIS LINEAGE: the plan being approved was "
            "AUTHORED BY THE SYSTEM, not by an agent. Every prose field came from the "
            "model and was accepted by deterministic graders that check numeric "
            "traceability against retained evidence, falsifiability of the "
            "expectation, absence of any claimed-but-unobserved result, and the shared "
            "plan quality rubric. The agent supplied only frozen constraints, the "
            "effective narrowed panel, and the system's own retained evidence. No "
            "hypothesis, mechanism, title, or framing was supplied.\n\n"
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
    if sys.argv[1] == "prereg":
        prereg()
    else:
        stage(sys.argv[1])
