"""Block until a lineage stage finishes, then print a compact summary.

Why this exists
---------------
Polling a long Docker-backed stage through many separate shell calls burns turns and
tells me nothing between checks. This waits INSIDE one process, polls cheaply, and
returns as soon as the stage's terminal artifact appears (or the deadline passes).

Usage:
    python _wait.py <lineage_dir> <marker_relative_path> [timeout_seconds]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def summarize(root: Path, marker: Path) -> dict[str, object]:
    """Report what actually exists, so a caller never guesses at stage state."""

    out: dict[str, object] = {
        "marker": marker.name,
        "marker_present": marker.is_file(),
        "lock_held": (root / ".lineage-stage-lock").exists(),
    }
    if marker.is_file() and marker.suffix == ".json":
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            out["parse_error"] = str(exc)
            return out
        results = payload.get("results")
        if isinstance(results, list):
            statuses: dict[str, int] = {}
            per_candidate: dict[str, list[int]] = {}
            for cell in results:
                status = str(cell.get("status"))
                statuses[status] = statuses.get(status, 0) + 1
                cid = str(cell.get("candidate_id") or "?")
                slot = per_candidate.setdefault(cid, [0, 0])
                slot[1] += 1
                if status == "succeeded":
                    slot[0] += 1
            out["total_cells"] = len(results)
            out["status_counts"] = statuses
            out["per_candidate"] = {
                k: f"{v[0]}/{v[1]}" for k, v in sorted(per_candidate.items())
            }
            reasons: dict[str, int] = {}
            for cell in results:
                if cell.get("status") != "succeeded":
                    key = str(cell.get("failure_reason") or "")[:90]
                    reasons[key] = reasons.get(key, 0) + 1
            if reasons:
                out["failure_reasons"] = dict(
                    sorted(reasons.items(), key=lambda kv: -kv[1])[:6]
                )
    return out


def main() -> int:
    root = Path(sys.argv[1])
    marker = root / sys.argv[2]
    timeout = float(sys.argv[3]) if len(sys.argv) > 3 else 1800.0

    deadline = time.time() + timeout
    while time.time() < deadline:
        if marker.is_file():
            # The stage writes the marker then releases the lock; give it a moment so
            # the summary reflects a settled directory rather than a mid-write one.
            time.sleep(3)
            print(json.dumps(summarize(root, marker), indent=2))
            return 0
        time.sleep(10)
    print(json.dumps({"timed_out": True, **summarize(root, marker)}, indent=2))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
