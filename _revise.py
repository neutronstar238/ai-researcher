"""Let each candidate re-author itself from its OWN pilot v2 failures, then re-execute."""
import json
import shutil
import traceback
from pathlib import Path

out = Path("_revise.txt")
lines = []
try:
    from autoresearch.competition.official_development_search import (
        OfficialCandidateRecord,
        OfficialCellResult,
        build_official_cell_specs,
        compute_system_effects,
        execute_official_stage,
        freeze_official_identity,
        revise_official_candidates,
        select_official_candidate,
    )

    source = Path("runs/manual-live/task2663-official-development-pilot-v2")
    work = Path("runs/manual-live/task2663-official-development-revised-v1")
    work.mkdir(parents=True, exist_ok=True)
    if not (work / "candidates").exists():
        shutil.copytree(source / "candidates", work / "candidates")

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
    budget = json.loads(plan_path.read_text(encoding="utf-8"))["search_budget"]

    parents = [
        OfficialCandidateRecord.model_validate(item)
        for item in json.loads(
            (work / "candidates" / "candidate-registry.json").read_text(encoding="utf-8")
        )["candidates"]
    ]
    prior = [
        OfficialCellResult.model_validate(item)
        for item in json.loads(
            (source / "cells" / "pilot-results.json").read_text(encoding="utf-8")
        )["results"]
    ]
    baseline_prior = [
        OfficialCellResult.model_validate(item)
        for item in json.loads(
            (source / "cells" / "baseline-results.json").read_text(encoding="utf-8")
        )["results"]
    ]

    lines.append("=== SYSTEM RE-AUTHORS ITSELF from its own objective failures")
    revised = revise_official_candidates(
        panel=panel,
        budget=budget,
        candidates=parents,
        results=prior,
        output_dir=work,
    )
    for record in revised:
        flag = "OK " if record.static_review_approved else "REJ"
        lines.append(f"  {flag} {record.candidate_id}: {record.implementation_summary[:90]}")
        if not record.static_review_approved:
            for finding in record.static_review_findings[:2]:
                lines.append(f"        {finding[:110]}")
    approved = [r for r in revised if r.static_review_approved]
    lines.append(f"  approved revisions: {len(approved)}/{len(revised)}")
    lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")

    if not approved:
        lines.append("no approved revision; cannot re-execute")
        out.write_text("\n".join(lines), encoding="utf-8")
        raise SystemExit(0)

    ode = [s for s in panel["systems"] if s["data_type"] == "ode"][:3]
    pde = [s for s in panel["systems"] if s["data_type"] == "pde"][:3]
    systems = ode + pde
    specs = build_official_cell_specs(
        identity=identity, candidates=approved, stage="pilot",
        systems=systems, seeds=[panel["seeds"][0]], output_dir=work,
    )
    lines.append(f"=== re-executing {len(specs)} cells with the revised candidates")
    out.write_text("\n".join(lines), encoding="utf-8")

    results = execute_official_stage(
        identity=identity, specs=specs, candidates=approved,
        output_dir=work, baseline_method=None,
        timeout_seconds=300, maximum_parallel_cells=4,
    )
    ok = sum(1 for item in results if item.status == "succeeded")
    lines.append(f"=== REVISED PILOT : {ok}/{len(results)} succeeded")
    for candidate_id in sorted({item.candidate_id for item in results}):
        cells = [item for item in results if item.candidate_id == candidate_id]
        good = [c for c in cells if c.status == "succeeded"]
        detail = ""
        if good:
            losses = sorted(c.loss for c in good)
            terms = sorted(c.selected_term_count or 0 for c in good)
            detail = (
                f"  test nmse {losses[0]:.4g}..{losses[-1]:.4g}"
                f"  terms {terms[0]}..{terms[-1]}"
            )
        lines.append(f"  {candidate_id}: {len(good)}/{len(cells)}{detail}")
    lines.append("")

    selected, basis = select_official_candidate(candidates=approved, results=results)
    lines.append(f"=== SELECTED : {selected}")
    if selected:
        effects = compute_system_effects(
            candidate_id=selected,
            candidate_results=results,
            baseline_results=baseline_prior,
        )
        lines.append("")
        lines.append("=== PAIRED EFFECTS after self-revision")
        values = []
        for effect in sorted(effects, key=lambda x: (x.data_type, x.system_name)):
            values.append(effect.paired_log_effect)
            lines.append(
                f"  {effect.data_type:3} {effect.system_name:30} "
                f"cand={effect.candidate_median_loss:.5g} "
                f"base={effect.baseline_median_loss:.5g} "
                f"log={effect.paired_log_effect:+.4f}"
            )
        if values:
            values.sort()
            mid = len(values) // 2
            median = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2
            lines.append(f"\n  overall median log effect : {median:+.6f}")
            lines.append("  (pilot v2 before revision  : -3.293715)")
    out.write_text("\n".join(lines), encoding="utf-8")
except SystemExit:
    pass
except Exception:
    lines.append("FAILED\n" + traceback.format_exc())
    out.write_text("\n".join(lines), encoding="utf-8")
