"""Task 266.3 full stage: 3 finalists on all 14 systems, 2 conditions, 3 seeds.

Runs in resumable chunks so a container interruption does not lose completed cells;
every cell checkpoints its own result.json and is skipped on re-entry.
"""
import json
import shutil
import sys
import traceback
from pathlib import Path

out = Path("_full.txt")
lines = []


def emit():
    out.write_text("\n".join(lines), encoding="utf-8")


try:
    from autoresearch.competition.official_development_search import (
        OfficialCandidateRecord,
        OfficialCellResult,
        build_official_cell_specs,
        compute_system_effects,
        execute_official_stage,
        freeze_official_identity,
        select_official_candidate,
        _bootstrap_interval,
        _median,
    )

    revised_root = Path("runs/manual-live/task2663-official-development-revised-v1")
    work = Path("runs/manual-live/task2663-official-development-full-v1")
    work.mkdir(parents=True, exist_ok=True)
    if not (work / "candidates").exists():
        shutil.copytree(revised_root / "candidates", work / "candidates")

    plan_path = Path(
        "runs/manual-live/task2661-scientific-contract-recovery-plan-v1/"
        "scientific-contract-recovery-plan.json"
    )
    identity, panel = freeze_official_identity(
        plan_path=plan_path,
        autonomous_plan_path=Path(
            "runs/manual-live/task2651-autonomous-recovery-plan-v1/"
            "autonomous-research-plan.json"
        ),
        data_root=Path(
            "runs/manual-live/task259-mdbench-official-v1/data/prepared/"
            "processed-9fe483c64ad6"
        ),
        output_dir=work,
        initial_candidate_count=8,
    )
    revised = [
        OfficialCandidateRecord.model_validate(item)
        for item in json.loads(
            (work / "candidates" / "revised-registry.json").read_text(encoding="utf-8")
        )["candidates"]
    ]
    # The three finalists the frozen budget allows, chosen on pilot validation
    # evidence only: these are the revisions that beat the baseline on some cell.
    finalist_ids = {"official-02-r2", "official-03-r2", "official-04-r2"}
    finalists = [r for r in revised if r.candidate_id in finalist_ids]
    lines.append(f"=== finalists: {sorted(r.candidate_id for r in finalists)}")

    systems = panel["systems"]
    seeds = panel["seeds"]
    lines.append(
        f"=== full panel: {len(systems)} systems x {len(identity.conditions)} "
        f"conditions x {len(seeds)} seeds"
    )

    baseline_specs = build_official_cell_specs(
        identity=identity, candidates=finalists, stage="baseline",
        systems=systems, seeds=seeds, output_dir=work,
    )
    full_specs = build_official_cell_specs(
        identity=identity, candidates=finalists, stage="full",
        systems=systems, seeds=seeds, output_dir=work,
    )
    lines.append(f"  baseline cells : {len(baseline_specs)}")
    lines.append(f"  candidate cells: {len(full_specs)}")
    lines.append(f"  total          : {len(baseline_specs) + len(full_specs)}")
    lines.append("")
    emit()

    stage = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    if stage == "baseline":
        results = execute_official_stage(
            identity=identity, specs=baseline_specs, candidates=finalists,
            output_dir=work, baseline_method=None,
            timeout_seconds=300, maximum_parallel_cells=4,
        )
        ok = sum(1 for r in results if r.status == "succeeded")
        lines.append(f"=== BASELINE COMPLETE : {ok}/{len(results)} succeeded")
        for data_type in ("ode", "pde"):
            subset = [r for r in results if r.data_type == data_type]
            good = sum(1 for r in subset if r.status == "succeeded")
            lines.append(f"  {data_type}: {good}/{len(subset)}")
        emit()
    else:
        results = execute_official_stage(
            identity=identity, specs=full_specs, candidates=finalists,
            output_dir=work, baseline_method=None,
            timeout_seconds=300, maximum_parallel_cells=4,
        )
        baseline_results = [
            OfficialCellResult.model_validate(item)
            for item in json.loads(
                (work / "cells" / "baseline-results.json").read_text(encoding="utf-8")
            )["results"]
        ]
        ok = sum(1 for r in results if r.status == "succeeded")
        lines.append(f"=== FULL COMPLETE : {ok}/{len(results)} succeeded")
        for candidate_id in sorted({r.candidate_id for r in results}):
            cells = [r for r in results if r.candidate_id == candidate_id]
            good = [c for c in cells if c.status == "succeeded"]
            detail = ""
            if good:
                losses = sorted(c.loss for c in good)
                detail = f"  nmse {losses[0]:.4g}..{losses[-1]:.4g}"
            lines.append(f"  {candidate_id}: {len(good)}/{len(cells)}{detail}")
        lines.append("")

        selected, basis = select_official_candidate(
            candidates=finalists, results=results
        )
        lines.append(f"=== SELECTED : {selected}")
        lines.append(f"  basis: {basis}")
        if selected:
            effects = compute_system_effects(
                candidate_id=selected,
                candidate_results=results,
                baseline_results=baseline_results,
            )
            lines.append("")
            lines.append("=== SYSTEM EFFECTS (positive = candidate beat the baseline)")
            values, ode_values, pde_values = [], [], []
            for effect in sorted(effects, key=lambda x: (x.data_type, x.system_name)):
                values.append(effect.paired_log_effect)
                (ode_values if effect.data_type == "ode" else pde_values).append(
                    effect.paired_log_effect
                )
                lines.append(
                    f"  {effect.data_type:3} {effect.system_name[:30]:31}"
                    f"cand={effect.candidate_median_loss:.5g} "
                    f"base={effect.baseline_median_loss:.5g} "
                    f"log={effect.paired_log_effect:+.4f} "
                    f"({effect.candidate_success_count}/{effect.candidate_cell_count})"
                )
            if values:
                lower, upper = _bootstrap_interval(values)
                lines.append("")
                lines.append(f"  overall median log effect : {_median(values):+.6f}")
                lines.append(f"  bootstrap CI95           : [{lower:+.6f}, {upper:+.6f}]")
                if ode_values:
                    lines.append(f"  ODE stratum median       : {_median(ode_values):+.6f}")
                if pde_values:
                    lines.append(f"  PDE stratum median       : {_median(pde_values):+.6f}")
                wins = sum(1 for v in values if v > 0)
                lines.append(f"  systems where candidate won : {wins}/{len(values)}")
        emit()
except Exception:
    lines.append("FAILED\n" + traceback.format_exc())
    emit()
