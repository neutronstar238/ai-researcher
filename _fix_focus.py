"""把测试里的 plan=_PLAN 改为 focus=_PLAN，并把结果打到文件以便确认。"""

from pathlib import Path

p = Path("tests/unit/competition/test_plan_literature_survey.py")
s = p.read_text(encoding="utf-8")
count = s.count("plan=_PLAN,")
n = s.replace("plan=_PLAN,", "focus=_PLAN,")
p.write_text(n, encoding="utf-8")
after = n.count("focus=_PLAN,")
Path("_fix_focus.txt").write_text(
    f"before={count} after={after} residual={n.count('plan=_PLAN,')}\n",
    encoding="utf-8",
)
