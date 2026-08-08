"""诊断：v7 的反面解读为何被 counter-reading guard 拒收。

只读产物、只做匹配，不修改任何证据。
"""

from __future__ import annotations

import json
from pathlib import Path

from autoresearch.competition.system_authored_outcome import _COUNTER_READING_CONCEPTS

WORK = Path("runs/manual-live/task2700-latex-plan-lineage-v1")
payload = json.loads((WORK / "system-authored-outcome.json").read_text(encoding="utf-8"))
counter = payload["interpretation"]["strongest_counter_reading"]
lower = counter.lower()

lines: list[str] = []
lines.append(f"counter-reading 字符数：{len(counter)}")
lines.append(f"概念组总数：{len(_COUNTER_READING_CONCEPTS)}")
lines.append("")

matched: list[int] = []
for idx, group in enumerate(_COUNTER_READING_CONCEPTS):
    hits = [phrase for phrase in group if phrase in lower]
    if hits:
        matched.append(idx)
        lines.append(f"命中组 {idx}: {hits}")

lines.append("")
lines.append(f"命中组数：{len(matched)}")
lines.append("")
lines.append("未命中的组（各组首个短语作为代表）：")
for idx, group in enumerate(_COUNTER_READING_CONCEPTS):
    if idx not in matched:
        lines.append(f"  组 {idx}: {list(group)[:6]}")

lines.append("")
lines.append("--- counter-reading 原文 ---")
lines.append(counter)

Path("_cr_probe.txt").write_text("\n".join(lines), encoding="utf-8")
print("written")
