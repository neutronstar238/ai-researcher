"""Run the remaining lineage stages in order, in ONE process, logging as it goes.

Why this exists
---------------
Each stage is long (Docker-backed cells at up to 300 s each), and driving them through
separate shell invocations both burns turns and risks the `P-20260807-090` failure mode
if two invocations ever overlap. Running them sequentially inside one process makes the
ordering explicit and keeps exactly one holder of the lineage lock at a time.

A stage that raises ABORTS the chain. That is deliberate: `revise` feeding a broken
registry into `baseline` would spend frozen budget on cells that cannot inform the
estimand.

Usage:
    python _chain.py <driver_module> <stage> [<stage> ...]
"""

from __future__ import annotations

import importlib
import sys
import traceback
from datetime import datetime, timezone

LOG = "chain-log.txt"


def _emit(line: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    text = f"[{stamp}] {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def main() -> int:
    driver = importlib.import_module(sys.argv[1])
    stages = sys.argv[2:]
    _emit(f"CHAIN START stages={stages}")
    for name in stages:
        _emit(f"--- STAGE {name} begin")
        try:
            if name == "interpret":
                driver.interpret()
            else:
                driver.stage(name)
        except Exception as exc:  # noqa: BLE001 - the chain must report, not mask
            _emit(f"!!! STAGE {name} FAILED: {type(exc).__name__}: {exc}")
            with open(LOG, "a", encoding="utf-8") as handle:
                handle.write(traceback.format_exc() + "\n")
            _emit("CHAIN ABORTED; later stages were NOT run")
            return 1
        _emit(f"--- STAGE {name} done")
    _emit("CHAIN COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
