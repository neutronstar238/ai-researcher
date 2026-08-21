"""Re-render all 125 delivered plans with the fixed renderer and overwrite the delivery folder.

Read-only on all batch sources; zero model calls. q001 comes from the local
fixed mainline source payload. Every produced PDF is leak-checked with
pdftotext before it is copied over the Desktop delivery folder.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from autoresearch.competition.contest_direct_plan import (
    contest_direct_plan_template_payload,
    load_contest_direct_plan,
)
from autoresearch.competition.contest_direct_plan_render import materialize_contest_direct_plan
from autoresearch.competition.contest_question_input import Science125QuestionInput

BATCH_BASE = Path(r"E:\ai-researcher-loop\ai-researcher-loop-main\runs\contest-delivery")
WORK_ROOT = Path(r"E:\ai-researcher-source\runs\delivery-125-final")
DESKTOP = Path(r"C:\Users\Z\Desktop\揭榜挂帅提交材料\delivery-125-plan")
Q001_SOURCE = Path(
    r"E:\ai-researcher-source\runs\contest-delivery\mainline-q1-e2e-fixed-20260816"
    r"\04-final-plan\_private\research-plan-source.json"
)
PDFTOTEXT = r"C:\texlive\2026\bin\windows\pdftotext.exe"

PLAN_NAME = "system-authored-research-plan.json"
LEAK_MARKERS = (
    "\\mathcal",
    "\\mathbb",
    "\\mathfrak",
    "\\mathscr",
    "\\gtrsim",
    "\\lesssim",
    "\\cos",
    "\\ln",
    "\\hat",
    "\\bar",
    "\\dot",
    "text{",
    "tilde{",
    "hat{",
    "bar{",
    "vec{",
    "mathrm{",
    "operatorname{",
    "\\text",
    "\\frac",
    "\\sqrt",
    "\\sim",
    "\\times",
    "\\to ",
    "\\n ",
)


def ordinal_of(name: str) -> int | None:
    match = re.match(r"^q0?(\d+)-", name)
    return int(match.group(1)) if match else None


def collect_plans() -> dict[int, Path]:
    candidates: dict[int, list[tuple[float, Path]]] = {}
    for root in BATCH_BASE.glob("science125-batch*"):
        questions = root / "questions"
        if not questions.is_dir():
            continue
        for question_dir in questions.iterdir():
            ordinal = ordinal_of(question_dir.name)
            if ordinal is None:
                continue
            state = question_dir / "state.json"
            if not state.is_file():
                continue
            try:
                if json.loads(state.read_text(encoding="utf-8")).get("status") != "completed":
                    continue
            except (OSError, json.JSONDecodeError):
                continue
            for plan in question_dir.glob(f"attempts/*/plan-only/{PLAN_NAME}"):
                candidates.setdefault(ordinal, []).append((plan.stat().st_mtime, plan))
    chosen: dict[int, Path] = {}
    for ordinal in range(1, 126):
        options = sorted(candidates.get(ordinal, []), key=lambda item: item[0], reverse=True)
        if options:
            chosen[ordinal] = options[0][1]
    return chosen


def extract_text(pdf: Path) -> str:
    result = subprocess.run(
        [PDFTOTEXT, "-layout", str(pdf), "-"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    return result.stdout


def build_payload(plan: Path, question_dir: Path) -> dict:
    attempt_dir = plan.parents[1]
    research_loop = attempt_dir / "research-loop"
    question = Science125QuestionInput.model_validate_json(
        (question_dir / "question-input.json").read_text(encoding="utf-8")
    )
    direction_input = json.loads(
        (research_loop / "direction-input.json").read_text(encoding="utf-8")
    )
    direction = direction_input["direction"]
    focus = json.loads(
        (research_loop / "literature" / "refinement" / "direction-focus.json").read_text(
            encoding="utf-8"
        )
    )
    focused = focus.get("focused_direction_cn") or ""
    loaded = load_contest_direct_plan(plan)
    payload = contest_direct_plan_template_payload(loaded)
    payload.update(
        {
            "document_type": "科学假设与研究计划",
            "status": "completed_plan_only_no_compatible_real_preexperiment_adapter",
            "science125_question": question.model_dump(mode="json"),
            "specified_direction": direction,
            "focused_direction": focused,
            "preexperiment": {
                "executed": False,
                "status_zh": "尚无兼容真实预实验适配器，未执行预实验",
            },
            "formal_experiment_executed": False,
            "result_paper_generated": False,
        }
    )
    return payload


def render_q001() -> Path:
    payload = json.loads(Q001_SOURCE.read_text(encoding="utf-8"))
    output = WORK_ROOT / "q001"
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    materialize_contest_direct_plan(payload=payload, output_dir=output / "plan", timeout_seconds=180)
    return output / "plan" / "research-plan.pdf"


def main() -> int:
    plans = collect_plans()
    print(f"batch plans found: {len(plans)} (ordinals {min(plans)}..{max(plans)})")
    failures: list[str] = []
    rendered: list[tuple[int, Path]] = []

    pdf = render_q001()
    rendered.append((1, pdf))

    for ordinal in sorted(plans):
        plan = plans[ordinal]
        question_dir = plan.parents[3]
        qid = f"q{ordinal:03d}"
        try:
            payload = build_payload(plan, question_dir)
            output = WORK_ROOT / qid
            if output.exists():
                shutil.rmtree(output)
            output.mkdir(parents=True)
            materialize_contest_direct_plan(
                payload=payload, output_dir=output / "plan", timeout_seconds=180
            )
            rendered.append((ordinal, output / "plan" / "research-plan.pdf"))
            print(f"{qid} rendered", flush=True)
        except Exception as exc:  # noqa: BLE001 - collect and continue
            failures.append(f"{qid}: {type(exc).__name__}: {exc}")
            print(f"{qid} FAILED: {type(exc).__name__}: {exc}", flush=True)

    print(f"rendered {len(rendered)}/125; failures: {failures or 'NONE'}", flush=True)

    # Leak-check every rendered PDF before overwriting the delivery folder.
    leaky: list[str] = []
    for ordinal, pdf in sorted(rendered):
        text = extract_text(pdf)
        leaks = [marker for marker in LEAK_MARKERS if marker in text]
        if leaks:
            leaky.append(f"q{ordinal:03d}: {leaks}")
    print(f"leak check: {leaky or 'ALL CLEAN'}", flush=True)

    if failures:
        return 2

    # Overwrite the delivery folder with the final md + pdf pair per question.
    for ordinal, pdf in sorted(rendered):
        qid = f"q{ordinal:03d}"
        md = pdf.parent / "research-plan.md"
        if md.is_file():
            shutil.copy2(md, DESKTOP / f"{qid}.md")
        shutil.copy2(pdf, DESKTOP / f"{qid}.pdf")
    print(f"overwritten {DESKTOP} with {len(rendered)} pairs", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
