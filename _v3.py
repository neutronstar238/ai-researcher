"""Preregister lineage v3: repair the complementary PDE defects (Task 269.5).

The parent `task2694-promotion-gated-lineage-v1` reached ODE parity with every ODE
cell succeeding, and its two structural repairs are reproducible. What blocks the
receipt is `P-20260804-081`: both finalists failed DIFFERENT PDE cells, one on an
off-by-one grid axis across every clean-condition cell, the other on an unknown state
field across every `reaction_diffusion_cylinder` cell.

Nothing scientific is chosen here. The baseline policy comes from the system's own
`268.2` resolution and the stage breadth from its own `P-20260804-077` resolution, and
the PDE defects are carried as evidence for the system to repair itself.
"""

from __future__ import annotations

import json
from pathlib import Path

from autoresearch.competition.official_baseline_policy import (
    assert_policy_precedes_numeric_payload,
    preregister_baseline_policy,
)
from autoresearch.competition.official_plan_generation import (
    build_official_research_plan,
)
from autoresearch.competition.preregistered_stage_breadth import (
    preregister_stage_breadth,
)
from autoresearch.research.plan_confirmation import (
    ResearchPlanConfirmationError,
    compute_plan_hash,
    load_plan_decision,
    record_plan_decision,
    require_approved_plan,
)
from autoresearch.research.plans import audit_research_plan

LINEAGE_ID = "task2695-pde-repair-lineage-v1"
WORK = Path("runs/manual-live") / LINEAGE_ID
PARENT = Path("runs/manual-live/task2694-promotion-gated-lineage-v1")
GRANDPARENT = Path("runs/manual-live/task2693-unified-lineage-v1")
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
    GRANDPARENT / "pilot-breadth-v1" / "pilot-breadth-contradiction-package.json"
)

out: dict[str, object] = {}
WORK.mkdir(parents=True, exist_ok=True)
parent_identity = json.loads(
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
    child_runner_sha256=str(parent_identity["runner_sha256"]),
    output_dir=WORK,
)
out["policy_hash"] = policy.policy_hash
out["ordering_guard"] = assert_policy_precedes_numeric_payload(
    output_dir=WORK, lineage_dir=WORK
).policy_hash[:16]

breadth = preregister_stage_breadth(
    lineage_id=LINEAGE_ID,
    frozen_plan_path=FROZEN_PLAN,
    baseline_policy_hash=policy.policy_hash,
    contradiction_package_path=BREADTH_PACKAGE,
    panel=json.loads(AUTONOMOUS_PLAN.read_text(encoding="utf-8"))["development_panel"],
    excluded_system_names=policy.excluded_system_names,
    output_dir=WORK,
)
out["breadth_hash"] = breadth.breadth_hash
out["frozen_budget_edited"] = breadth.frozen_parent_budget_modified

# Carry the parent's PDE failures as evidence, derived from its retained cells rather
# than written by hand, so the plan states what this lineage exists to repair.
parent_full = json.loads(
    (PARENT / "cells" / "full-results.json").read_text(encoding="utf-8")
)["results"]
pde_fail = [
    item
    for item in parent_full
    if item.get("data_type") == "pde" and item.get("status") != "succeeded"
]
reasons: dict[str, set[str]] = {}
for item in pde_fail:
    reasons.setdefault(str(item["candidate_id"]), set()).add(
        str(item.get("failure_reason") or "")
    )
carried = [item.statement for item in policy.carried_defects]
for candidate_id in sorted(reasons):
    cells = [i for i in pde_fail if i["candidate_id"] == candidate_id]
    systems = sorted({str(i["system_name"]) for i in cells})
    conditions = sorted({str(i["condition"]) for i in cells})
    carried.append(
        f"In the parent lineage {PARENT.name}, candidate {candidate_id} failed "
        f"{len(cells)} PDE cells on {', '.join(systems)} under condition(s) "
        f"{', '.join(conditions)}, with reason(s): "
        f"{'; '.join(sorted(reasons[candidate_id]))}. Every ODE cell of the same "
        "candidate succeeded, so the defect is specific to its PDE handling rather "
        "than a uniformly broken implementation."
    )
out["carried_defect_count"] = len(carried)
out["pde_failures_carried"] = len(pde_fail)

plan_dir = WORK / "plan"
plan_dir.mkdir(parents=True, exist_ok=True)
plan = build_official_research_plan(
    plan_path=FROZEN_PLAN,
    autonomous_plan_path=AUTONOMOUS_PLAN,
    data_root=DATA_ROOT,
    project_id=LINEAGE_ID,
    prior_run_dirs=[RETAINED, GRANDPARENT, PARENT],
    carried_defect_statements=carried,
    extra_evidence_refs=[
        policy.output_path,
        breadth.output_path,
        AUTHORED.as_posix(),
        (PARENT / "official-development-search-package.json").as_posix(),
    ],
)
audit = audit_research_plan(plan)
out["plan_audit"] = f"{audit.verdict.value} score={audit.score}"
out["plan_hash"] = compute_plan_hash(plan)
(plan_dir / "research-plan.json").write_text(
    json.dumps(plan.model_dump(mode="json"), indent=2, sort_keys=True), encoding="utf-8"
)

try:
    require_approved_plan(
        plan=plan,
        decision=load_plan_decision(project_id=plan.project_id, output_dir=plan_dir),
    )
    out["gate_before"] = "ERROR: authorized with no record"
except ResearchPlanConfirmationError as exc:
    out["gate_before"] = f"refused: {exc}"

NOTES = (
    "OPERATOR-DELEGATED SCOPE AUTHORIZATION for lineage v3. The operator granted "
    "blanket authority ('I fully authorize you; I only want the leaderboard "
    "requirement met as fast as possible at the best quality'). This record is an "
    "agent exercising that DELEGATED authority. It is NOT a human scientific review: "
    "no human read these numbers and no human endorsed any scientific claim.\n\n"
    "WHY THIS LINEAGE EXISTS: the parent task2694-promotion-gated-lineage-v1 reached "
    "ODE parity (stratum -0.0553, 120/120 ODE cells succeeded for both finalists, 5 "
    "of 10 ODE systems won) and reproduced both structural repairs "
    "(all_baseline_cells_succeeded PASS at 72/72, zero zero-term failures). The "
    "receipt is blocked by P-20260804-081: both finalists failed DIFFERENT PDE cells, "
    "one on an off-by-one grid axis across every clean-condition cell, the other on "
    "an unknown state field across every reaction_diffusion_cylinder cell. Both "
    "parent generations are spent, so the repair needs a new lineage.\n\n"
    "AUTHORIZED (scope only): open this one new preregistered lineage; spend the "
    "frozen 266.1 budget once inside it; carry the parent's PDE failure reasons as "
    "evidence so the system can repair its own code.\n\n"
    "NOT AUTHORIZED: any scientific conclusion; any effect direction or magnitude; "
    "issuing a receipt; weakening any frozen threshold, estimand, gate, or budget "
    "parameter; combining two candidates' results; repairing candidate code by hand; "
    "unsealing the sealed confirmation panel; publication; external submission.\n\n"
    "A NEGATIVE RESULT REMAINS A VALID OUTCOME. This authorizes a fair measurement, "
    "not a favourable one."
)
record_plan_decision(
    plan=plan,
    decision="approve",
    decided_by="operator-delegated-agent (Kiro, delegated authority 2026-08-04)",
    notes=NOTES,
    output_dir=plan_dir,
)
loaded = load_plan_decision(project_id=plan.project_id, output_dir=plan_dir)
assert loaded is not None
out["gate_after"] = require_approved_plan(plan=plan, decision=loaded)[:16]
edited = plan.model_copy(update={"problem_statement": plan.problem_statement + " x"})
try:
    require_approved_plan(plan=edited, decision=loaded)
    out["gate_after_edit"] = "ERROR: stale approval authorized"
except ResearchPlanConfirmationError as exc:
    out["gate_after_edit"] = f"blocked: {str(exc)[:60]}"

print(json.dumps(out, indent=2, ensure_ascii=False))
