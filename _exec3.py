"""Drive one stage of lineage v3 per invocation."""

from __future__ import annotations

import sys
from pathlib import Path

from autoresearch.competition.official_lineage import (
    OfficialLineageConfig,
    run_lineage_stage,
)

config = OfficialLineageConfig(
    lineage_id="task2695-pde-repair-lineage-v1",
    work_dir=Path("runs/manual-live/task2695-pde-repair-lineage-v1"),
    frozen_plan_path=Path(
        "runs/manual-live/task2661-scientific-contract-recovery-plan-v1/"
        "scientific-contract-recovery-plan.json"
    ),
    autonomous_plan_path=Path(
        "runs/manual-live/task2651-autonomous-recovery-plan-v1/"
        "autonomous-research-plan.json"
    ),
    data_root=Path(
        "runs/manual-live/task259-mdbench-official-v1/data/prepared/"
        "processed-9fe483c64ad6"
    ),
)
report = run_lineage_stage(config, stage=sys.argv[1])  # type: ignore[arg-type]
for line in report.lines:
    print(line)
if report.package_path:
    print("package:", report.package_path)
if report.search_freeze_receipt_issued is not None:
    print("search_freeze_receipt_issued:", report.search_freeze_receipt_issued)
