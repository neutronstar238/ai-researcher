"""Independent ``python -m`` entrypoint for the persistent competition plan loop."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from autoresearch.competition.continual_plan_loop import (
    CompetitionPlanLoopConfig,
    CompetitionPlanLoopStatus,
    run_competition_plan_loop,
)
from autoresearch.competition.official_lineage import OfficialLineageConfig


def build_parser() -> argparse.ArgumentParser:
    """Build the standalone parser without registering in the shared Typer CLI."""

    parser = argparse.ArgumentParser(
        prog="python -m autoresearch.competition.continual_plan_cli",
        description="持久认领并续跑既有正式中文研究计划链。",
    )
    parser.add_argument("--lineage-id", required=True, help="已初始化的科研谱系标识。")
    parser.add_argument("--work-dir", type=Path, help="正式谱系目录。")
    parser.add_argument(
        "--state-dir",
        type=Path,
        help="独立持久队列目录；默认 runs/continual-plan-loop/<lineage-id>。",
    )
    parser.add_argument(
        "--vault",
        type=Path,
        default=Path("autoresearch-vault"),
        help="主权原始记忆所在 Obsidian vault。",
    )
    parser.add_argument(
        "--plan",
        type=Path,
        default=Path(
            "runs/manual-live/task2661-scientific-contract-recovery-plan-v1/"
            "scientific-contract-recovery-plan.json"
        ),
        help="不可变父级科学合同。",
    )
    parser.add_argument(
        "--autonomous-plan",
        type=Path,
        default=Path(
            "runs/manual-live/task2651-autonomous-recovery-plan-v1/" "autonomous-research-plan.json"
        ),
        help="公开开发面板与密封承诺。",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(
            "runs/manual-live/task259-mdbench-official-v1/data/prepared/" "processed-9fe483c64ad6"
        ),
        help="已校验的 MDBench 数据根目录。",
    )
    parser.add_argument(
        "--prior-run-dir",
        action="append",
        type=Path,
        default=None,
        help="签名先验谱系；可重复。",
    )
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument(
        "--worker-id",
        default="competition-plan-main-agent",
        help="持久 claim 的 worker 标识。",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one persistent plan-loop invocation and return a stable process code."""

    args = build_parser().parse_args(argv)
    lineage_id = str(args.lineage_id)
    work_dir = args.work_dir or Path("runs/manual-live") / lineage_id
    state_dir = args.state_dir or Path("runs/continual-plan-loop") / lineage_id
    priors = tuple(
        args.prior_run_dir
        or (
            Path("runs/manual-live/task2694-promotion-gated-lineage-v1"),
            Path("runs/manual-live/task2695-pde-repair-lineage-v1"),
            Path("runs/manual-live/task2696-stratified-gate-lineage-v1"),
        )
    )
    lineage = OfficialLineageConfig(
        lineage_id=lineage_id,
        work_dir=work_dir,
        frozen_plan_path=args.plan,
        autonomous_plan_path=args.autonomous_plan,
        data_root=args.data_root,
        prior_run_dirs=priors,
    )
    try:
        report = run_competition_plan_loop(
            CompetitionPlanLoopConfig(
                lineage=lineage,
                state_dir=state_dir,
                vault_root=args.vault,
                config_path=args.config,
                env_path=args.env,
                worker_id=str(args.worker_id),
            )
        )
    except (OSError, RuntimeError, ValueError) as exc:
        detail = " ".join(str(exc).split())[:2_000]
        print(f"[BLOCKED] 持续计划命令失败：{type(exc).__name__}: {detail}")
        return 2

    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))
    if report.status is CompetitionPlanLoopStatus.COMPLETED:
        return 0
    if report.status is CompetitionPlanLoopStatus.SCIENTIFIC_PENDING_SHADOW:
        return 3
    if report.status is CompetitionPlanLoopStatus.FORMAT_EXHAUSTED:
        return 4
    return 2


if __name__ == "__main__":  # pragma: no cover - exercised through main().
    raise SystemExit(main())
