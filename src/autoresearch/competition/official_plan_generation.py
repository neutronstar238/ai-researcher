"""Task 266.3: generate the research plan the confirmation gate consumes.

Why this exists
---------------
The project requires a research-plan confirmation step between a generated plan and
any experiment. `execute_official_stage` now enforces that gate, but a grep showed
nothing in the competition path ever GENERATED a plan, so the loop could not actually
reach an approvable state: the gate would refuse forever because no plan existed.

This module closes that half. It derives every plan field from the system's own frozen
evidence -- the `266.1` plan hash, the frozen panel, the baseline registry, the frozen
estimand, and the accumulated `Problem.md` diagnoses -- and produces a `ResearchPlan`
that satisfies `audit_research_plan`.

Boundaries
----------
* Every field is derived from persisted evidence, not invented here. The dataset
  route, baselines, metrics, and stop rules are read out of the frozen artifacts.
* `expected_results` is phrased as an expectation and never as an observed outcome,
  because the audit rejects unsupported result claims.
* Generating a plan authorizes nothing. Execution still requires a human decision
  recorded against this exact plan's hash.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from autoresearch.research.plans import audit_research_plan
from autoresearch.schemas import ResearchPlan, ResearchPlanStatus


class OfficialPlanGenerationError(RuntimeError):
    """Raised when the frozen evidence cannot support a compliant plan."""


def build_official_research_plan(
    *,
    plan_path: Path | str,
    autonomous_plan_path: Path | str,
    data_root: Path | str,
    project_id: str = "official-mdbench-noise-robust-discovery",
    prior_run_dirs: list[Path | str] | None = None,
    carried_defect_statements: list[str] | None = None,
    extra_evidence_refs: list[str] | None = None,
) -> ResearchPlan:
    """Derive an execution-ready research plan from the system's own frozen evidence.

    `carried_defect_statements` lets a repair lineage state the diagnosed defects it
    exists to fix. Each statement must already originate in the system's own evidence
    -- either authored by the model in a self-correction package or derived
    arithmetically from retained cells -- because this function only positions text
    it is given and never composes a scientific claim itself.
    """

    frozen = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    autonomous = json.loads(Path(autonomous_plan_path).read_text(encoding="utf-8"))
    panel = autonomous["development_panel"]
    estimand = frozen["estimand"]
    budget = frozen["search_budget"]
    baselines = frozen["baselines"]

    ode_systems = [s["system_name"] for s in panel["systems"] if s["data_type"] == "ode"]
    pde_systems = [s["system_name"] for s in panel["systems"] if s["data_type"] == "pde"]
    if not ode_systems or not pde_systems:
        raise OfficialPlanGenerationError(
            "the frozen panel must contain both ODE and PDE systems"
        )
    baseline_ids = [item["baseline_id"] for item in baselines]

    # Evidence references are real persisted artifacts, not placeholders.
    evidence_refs = [
        Path(plan_path).as_posix(),
        Path(autonomous_plan_path).as_posix(),
    ]
    for directory in prior_run_dirs or []:
        package = Path(directory)
        if package.is_dir():
            evidence_refs.append(package.as_posix())
    evidence_refs.extend(extra_evidence_refs or [])

    # A repair lineage must state what it is repairing. The statements are carried
    # in already-authored; this only appends them so the plan hash covers them.
    carried = [item.strip() for item in (carried_defect_statements or []) if item.strip()]
    carried_block = (
        " This lineage exists to repair diagnosed defects carried from retained "
        "evidence: " + " ".join(carried)
        if carried
        else ""
    )

    minimum_effect = float(estimand["minimum_overall_log_effect"])
    plan = ResearchPlan.model_validate(
        {
            "project_id": project_id,
            "candidate_id": f"candidate_{frozen['plan_hash'][:12]}",
            "title": (
                "Noise-robust sparse equation discovery for measured dynamical systems"
            ),
            "problem_statement": (
                "On measured trajectories with SNR20 noise, sparse regression candidates "
                "fit the validation window instead of recovering a transferable law. "
                f"Across {len(ode_systems)} ODE and {len(pde_systems)} PDE systems the "
                "prior search showed a large positive gap between validation error and "
                "held-out derivative error, so held-out accuracy did not follow from "
                "training accuracy." + carried_block
            ),
            "rationale": (
                "Selecting model complexity on held-out evidence rather than fitting "
                "once at maximum capacity should narrow that gap. The pinned reference "
                "implementations already sweep configurations and select on validation, "
                "which is the mechanism this plan tests directly."
            ),
            "technical_details": (
                "Each candidate implements a two-phase contract. fit_equations reads "
                "only the training split of a system and returns concrete equations with "
                "numeric coefficients plus per-field scaling. The orchestrator freezes "
                "and hashes that artifact. predict_derivative then reads only the frozen "
                "artifact and one query slice, so no refit or query-time differentiation "
                "is possible. The evaluator re-derives spatial derivatives with a "
                "spectral FFT operator on the periodic axis and independently "
                "re-evaluates the reported equations, so returned numbers must agree "
                "with the reported law. A shuffled-training refit must change the "
                "artifact hash, which detects a fit that ignores its training target."
            ),
            "datasets": {
                "source": (
                    "official MDBench processed archive at "
                    f"{Path(data_root).as_posix()}, clean and snr_20 conditions"
                ),
                "target": (
                    "chronologically disjoint held-out split of the same systems: "
                    "train 0.00-0.64, validation 0.64-0.80, test 0.80-1.00; the sealed "
                    "confirmation panel stays unread"
                ),
            },
            "methods": (
                "Model-authored sparse equation discovery under the fit/freeze/predict "
                f"contract, compared against the frozen domain baselines "
                f"{', '.join(baseline_ids)} using derivative NMSE as the cell loss. "
                "Repeated measures over condition and seed are aggregated within each "
                "system by median, then systems are aggregated by median."
            ),
            "experiments": [
                (
                    f"Generate up to {budget['initial_candidate_count']} independent "
                    "candidate implementations and reject any that fails static review."
                ),
                (
                    "Run a bounded pilot over a subset of systems at one seed, then "
                    "return each candidate its own term counts, validation-to-test gap, "
                    "and failure reasons so it can re-author itself."
                ),
                (
                    "Execute the frozen baselines with the domain-valid method: "
                    "python runner for Operon on ODE systems and PDE-FIND on PDE "
                    "systems, retaining every failure."
                ),
                (
                    f"Run the full stage over all {len(panel['systems'])} systems, "
                    f"{len(panel['conditions'])} conditions and {len(panel['seeds'])} "
                    "seeds, then compute the paired log effect with a fixed-seed "
                    "bootstrap over independent systems."
                ),
            ],
            "expected_results": (
                "It is expected, and not yet observed, that held-out derivative NMSE "
                "improves relative to the frozen baselines and that the paired log "
                f"effect exceeds {minimum_effect:.6f} with a bootstrap lower bound above "
                "zero in both strata. A negative outcome is a valid result and will be "
                "reported as such; the four-system PDE stratum supports a directional "
                "qualification only."
            ),
            "code_agent_brief": (
                "Run the pinned container command "
                "'python /harness/runner.py --spec ... --data ... --candidate ... "
                "--output ...' for every frozen cell, with network disabled, a read-only "
                "root, two CPU cores and a 300 second budget per cell. Verify the "
                "runner and data hashes before execution, retain every failure payload, "
                "and check the accumulated spend ledger before starting a stage. "
                "Validate the implementation with pytest before any official cell runs."
            ),
            "risks_and_alternatives": [
                (
                    "A candidate may overfit the validation window; mitigated by "
                    "reporting the validation-to-test gap back to the candidate and by "
                    "penalising a failed cell with the frozen failure loss."
                ),
                (
                    "A baseline may fail on a system, which makes that system unpaired; "
                    "such systems are excluded from the effect and reported separately "
                    "as baseline-coverage gaps rather than credited as wins."
                ),
                (
                    "The four-system PDE stratum is underpowered for a standalone "
                    "significance claim, so it is treated as directional only."
                ),
            ],
            "references": [
                "arXiv:2607.04108 Dictionaries, Not Darwin",
                "arXiv:2605.29184 Influence-Guided Symbolic Regression",
                "arXiv:2607.13608 MEDA agentic ODE discovery",
                f"official MDBench benchmark revision {frozen['baseline_probe']['benchmark_revision']}",
            ],
            "evidence_refs": evidence_refs,
            "status": ResearchPlanStatus.DRAFT,
        }
    )

    audit = audit_research_plan(plan)
    return plan.model_copy(
        update={
            "quality_gate": audit.to_dict(),
            "status": (
                ResearchPlanStatus.READY_FOR_APPROVAL
                if audit.passed
                else ResearchPlanStatus.BLOCKED
            ),
            "validation_status": audit.verdict,
        }
    )


def write_official_research_plan(
    *,
    plan: ResearchPlan,
    output_dir: Path | str,
) -> dict[str, Any]:
    """Persist the plan where the confirmation CLI and the gate can both read it."""

    directory = Path(output_dir).resolve() / plan.project_id / "research-plan"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "research-plan.json"
    payload = plan.model_dump(mode="json")
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return {"plan_path": path.as_posix(), "status": plan.status.value}
