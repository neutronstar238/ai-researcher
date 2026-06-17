"""Research-plan generation and quality gates."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
)
from autoresearch.schemas import (
    ResearchCandidate,
    ResearchPlan,
    ResearchPlanStatus,
    ValidationStatus,
)

FORBIDDEN_PLAN_TERMS = (
    "xh-202619",
    "参赛",
    "赛事",
    "发榜",
    "主办",
    "评审标准",
    "评分标准",
    "评分表",
    "竞赛",
    "比赛方案",
    "浙江阿里巴巴",
    "基于国产开源大模型的 ai scientist",
)
FORBIDDEN_TITLE_TERMS = (
    "ai-researcher",
    "airesearcher",
    "autoresearch",
    "auto research",
    "ai scientist 的研发与应用",
    "基于国产开源大模型",
)
UNSUPPORTED_RESULT_TERMS = (
    "achieved state-of-the-art",
    "state-of-the-art results",
    "outperformed all baselines",
    "实验结果表明",
    "已达到",
    "显著优于所有",
)


@dataclass(frozen=True)
class ResearchPlanAudit:
    """Deterministic gate result for a research plan."""

    verdict: ValidationStatus
    score: float
    issues: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    rubric_scores: Mapping[str, float] | None = None

    @property
    def passed(self) -> bool:
        return self.verdict is ValidationStatus.PASSED

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "passed": self.passed,
            "score": self.score,
            "issues": list(self.issues),
            "warnings": list(self.warnings),
            "rubric_scores": dict(self.rubric_scores or {}),
        }


@dataclass(frozen=True)
class ResearchPlanArtifact:
    """Paths and status for a generated research plan."""

    plan: ResearchPlan
    audit: ResearchPlanAudit
    markdown_path: str
    json_path: str
    tex_path: str
    pdf_path: str | None
    compile_status: str
    compile_reason: str | None = None
    page_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.model_dump(mode="json"),
            "audit": self.audit.to_dict(),
            "markdown_path": self.markdown_path,
            "json_path": self.json_path,
            "tex_path": self.tex_path,
            "pdf_path": self.pdf_path,
            "compile_status": self.compile_status,
            "compile_reason": self.compile_reason,
            "page_count": self.page_count,
        }


def generate_research_plan(
    *,
    candidate: ResearchCandidate,
    project_id: str,
    vault_root: Path | str,
    output_dir: Path | str = Path("outputs"),
    compile_pdf: bool = True,
    similarity_summary: Path | str | None = None,
    literature_summary: Path | str | None = None,
    inspiration_summary: Path | str | None = None,
    timeout_seconds: int = 120,
) -> ResearchPlanArtifact:
    """Generate an evidence-bound research plan and optional PDF artifact."""

    artifact_dir = Path(output_dir) / project_id / "research-plan"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    context_refs = _context_refs(
        similarity_summary=similarity_summary,
        literature_summary=literature_summary,
        inspiration_summary=inspiration_summary,
    )
    plan = _build_plan(candidate=candidate, project_id=project_id, context_refs=context_refs)
    initial_markdown = render_research_plan_markdown(plan=plan, audit=None)
    initial_tex = render_research_plan_tex(plan=plan, audit=None)
    audit = audit_research_plan(plan, rendered_markdown=initial_markdown, rendered_tex=initial_tex)
    plan = plan.model_copy(
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

    markdown = render_research_plan_markdown(plan=plan, audit=audit)
    tex = render_research_plan_tex(plan=plan, audit=audit)
    markdown_path = _write_plan_markdown(
        vault_root=Path(vault_root),
        project_id=project_id,
        plan=plan,
        audit=audit,
        markdown=markdown,
    )

    tex_path = artifact_dir / "research-plan.tex"
    tex_path.write_text(tex, encoding="utf-8")

    pdf_path: Path | None = None
    compile_status = "skipped"
    compile_reason: str | None = None
    page_count: int | None = None
    if compile_pdf:
        if audit.passed:
            compile_status, pdf_path, compile_reason, page_count = compile_research_plan_pdf(
                tex_path,
                timeout_seconds=timeout_seconds,
            )
        else:
            compile_status = "skipped_quality_gate"
            compile_reason = "research-plan audit did not pass"

    json_path = artifact_dir / "research-plan.json"
    artifact = ResearchPlanArtifact(
        plan=plan,
        audit=audit,
        markdown_path=markdown_path.as_posix(),
        json_path=json_path.as_posix(),
        tex_path=tex_path.as_posix(),
        pdf_path=pdf_path.as_posix() if pdf_path is not None else None,
        compile_status=compile_status,
        compile_reason=compile_reason,
        page_count=page_count,
    )
    json_path.write_text(
        json.dumps(artifact.to_dict(), indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return artifact


def audit_research_plan(
    plan: ResearchPlan,
    *,
    rendered_markdown: str | None = None,
    rendered_tex: str | None = None,
) -> ResearchPlanAudit:
    """Block plans that are not specific, evidence-bound, or publication-safe."""

    issues: list[str] = []
    warnings: list[str] = []
    full_text = "\n".join(
        part
        for part in (
            plan.title,
            plan.problem_statement,
            plan.rationale,
            plan.technical_details,
            " ".join(plan.experiments),
            plan.expected_results,
            plan.code_agent_brief,
            rendered_markdown,
            rendered_tex,
        )
        if part
    )
    full_text_lower = _normalize(full_text)
    title_lower = _normalize(plan.title)

    for term in FORBIDDEN_PLAN_TERMS:
        if term in full_text_lower:
            issues.append(f"forbidden contest or organizer term found: {term}")
    for term in FORBIDDEN_TITLE_TERMS:
        if term in title_lower:
            issues.append(f"title must be a discovered research topic, not the system/project: {term}")

    if not plan.evidence_refs:
        issues.append("plan has no evidence_refs")
    if not plan.references:
        issues.append("plan has no source references")
    if not plan.datasets.get("source"):
        issues.append("plan must identify a source dataset or data acquisition route")
    if not plan.datasets.get("target"):
        issues.append("plan must identify a target validation dataset or hold-out route")

    execution_text = _normalize(
        "\n".join([plan.methods, plan.code_agent_brief, *plan.experiments])
    )
    if "baseline" not in execution_text and "对照" not in execution_text:
        issues.append("plan must specify at least one baseline or control")
    if not any(token in execution_text for token in ("metric", "accuracy", "f1", "auc", "mae")):
        issues.append("plan must specify concrete evaluation metrics")
    if not any(token in execution_text for token in ("script", "command", "pytest", "python")):
        issues.append("plan must include a command-oriented code-agent brief")

    expected_lower = _normalize(plan.expected_results)
    for term in UNSUPPORTED_RESULT_TERMS:
        if term in expected_lower:
            issues.append(f"unsupported result claim in expected_results: {term}")
    if "expected" not in expected_lower and "not yet observed" not in expected_lower:
        warnings.append("expected_results should clearly distinguish expectations from observed metrics")

    if len(plan.experiments) < 3:
        warnings.append("plan has fewer than three experiment steps")
    if len(plan.risks_and_alternatives) < 2:
        warnings.append("plan has fewer than two risks or alternatives")

    rubric_scores = _rubric_scores(issue_count=len(issues), warning_count=len(warnings))
    score = round(sum(rubric_scores.values()) / 100.0, 3)
    verdict = ValidationStatus.PASSED if not issues else ValidationStatus.FAILED
    return ResearchPlanAudit(
        verdict=verdict,
        score=score,
        issues=tuple(dict.fromkeys(issues)),
        warnings=tuple(dict.fromkeys(warnings)),
        rubric_scores=rubric_scores,
    )


def render_research_plan_markdown(
    *,
    plan: ResearchPlan,
    audit: ResearchPlanAudit | None,
) -> str:
    """Render the Obsidian archival Markdown version."""

    audit = audit or ResearchPlanAudit(verdict=ValidationStatus.PENDING, score=0.0)
    dataset_lines = [
        f"- **Source:** {plan.datasets.get('source', 'Not specified')}",
        f"- **Target:** {plan.datasets.get('target', 'Not specified')}",
    ]
    experiment_lines = [f"{index}. {item}" for index, item in enumerate(plan.experiments, 1)]
    risk_lines = [f"- {item}" for item in plan.risks_and_alternatives]
    reference_lines = [f"- {item}" for item in plan.references]
    evidence_lines = [f"- {item}" for item in plan.evidence_refs]
    issue_lines = [f"- {item}" for item in audit.issues] or ["- None"]
    warning_lines = [f"- {item}" for item in audit.warnings] or ["- None"]

    return "\n".join(
        [
            f"# {plan.title}",
            "",
            "## Gate Status",
            "",
            f"- Verdict: `{audit.verdict.value}`",
            f"- Score: `{audit.score}`",
            f"- Approval status: `{plan.approval_status}`",
            "",
            "### Gate Issues",
            "",
            *issue_lines,
            "",
            "### Gate Warnings",
            "",
            *warning_lines,
            "",
            "## Problem Statement",
            "",
            plan.problem_statement,
            "",
            "## Rationale",
            "",
            plan.rationale,
            "",
            "## Technical Details",
            "",
            plan.technical_details,
            "",
            "## Datasets",
            "",
            *dataset_lines,
            "",
            "## Methods",
            "",
            plan.methods,
            "",
            "## Experiments",
            "",
            *experiment_lines,
            "",
            "## Expected Results",
            "",
            plan.expected_results,
            "",
            "## Code Agent Brief",
            "",
            plan.code_agent_brief,
            "",
            "## Risks and Alternatives",
            "",
            *risk_lines,
            "",
            "## References and Evidence Sources",
            "",
            *reference_lines,
            "",
            "## Evidence Refs",
            "",
            *evidence_lines,
            "",
        ]
    )


def render_research_plan_tex(
    *,
    plan: ResearchPlan,
    audit: ResearchPlanAudit | None,
) -> str:
    """Render a compact LaTeX research-plan template."""

    audit = audit or ResearchPlanAudit(verdict=ValidationStatus.PENDING, score=0.0)
    experiments = "\n".join(f"\\item {_tex_escape(item)}" for item in plan.experiments)
    risks = "\n".join(f"\\item {_tex_escape(item)}" for item in plan.risks_and_alternatives)
    references = "\n".join(f"\\item {_tex_reference(item)}" for item in plan.references)
    issues = (
        "\n".join(f"\\item {_tex_escape(item)}" for item in audit.issues)
        if audit.issues
        else "\\item None"
    )
    warnings = (
        "\n".join(f"\\item {_tex_escape(item)}" for item in audit.warnings)
        if audit.warnings
        else "\\item None"
    )
    return rf"""\documentclass[11pt,a4paper]{{ctexart}}
\usepackage[margin=2.2cm]{{geometry}}
\usepackage{{booktabs}}
\usepackage{{enumitem}}
\usepackage{{fancyhdr}}
\usepackage{{hyperref}}
\usepackage{{longtable}}
\usepackage{{tabularx}}
\usepackage{{xcolor}}

\definecolor{{planblue}}{{HTML}}{{155A8A}}
\definecolor{{planline}}{{HTML}}{{D8E4EC}}
\hypersetup{{colorlinks=true, linkcolor=planblue, urlcolor=planblue}}
\pagestyle{{fancy}}
\fancyhf{{}}
\lhead{{Research Plan}}
\rhead{{\thepage}}
\setlength{{\headheight}}{{14pt}}
\setlength{{\parindent}}{{0pt}}
\setlength{{\parskip}}{{0.55em}}
\setlist[itemize]{{leftmargin=1.3em, itemsep=0.25em}}
\setlength{{\emergencystretch}}{{3em}}
\sloppy

\title{{\textbf{{{_tex_escape(plan.title)}}}\\[0.4em]\large Evidence-Bound Research Plan}}
\author{{Research Planning Agent}}
\date{{\today}}

\begin{{document}}
\maketitle
\thispagestyle{{fancy}}

\begin{{center}}
\begin{{tabularx}}{{0.94\linewidth}}{{@{{}}lX@{{}}}}
\toprule
Project & {_tex_escape(plan.project_id)} \\
Candidate & {_tex_escape(plan.candidate_id)} \\
Gate verdict & {_tex_escape(audit.verdict.value)} \\
Approval status & {_tex_escape(plan.approval_status)} \\
\bottomrule
\end{{tabularx}}
\end{{center}}

\section{{Problem Statement}}
{_tex_escape(plan.problem_statement)}

\section{{Rationale}}
{_tex_escape(plan.rationale)}

\section{{Technical Details}}
{_tex_escape(plan.technical_details)}

\section{{Datasets}}
\begin{{tabularx}}{{\linewidth}}{{@{{}}lX@{{}}}}
\toprule
Source & {_tex_escape(plan.datasets.get("source", "Not specified"))} \\
Target & {_tex_escape(plan.datasets.get("target", "Not specified"))} \\
\bottomrule
\end{{tabularx}}

\section{{Methods}}
{_tex_escape(plan.methods)}

\section{{Experiments}}
\begin{{enumerate}}
{experiments}
\end{{enumerate}}

\section{{Expected Results}}
{_tex_escape(plan.expected_results)}

\section{{Code Agent Brief}}
{_tex_escape(plan.code_agent_brief)}

\section{{Risks and Alternatives}}
\begin{{itemize}}
{risks}
\end{{itemize}}

\section{{Quality Gate Summary}}
\begin{{tabularx}}{{\linewidth}}{{@{{}}lX@{{}}}}
\toprule
Issues & \begin{{minipage}}[t]{{0.78\linewidth}}\begin{{itemize}}{issues}\end{{itemize}}\end{{minipage}} \\
Warnings & \begin{{minipage}}[t]{{0.78\linewidth}}\begin{{itemize}}{warnings}\end{{itemize}}\end{{minipage}} \\
\bottomrule
\end{{tabularx}}

\section{{References and Evidence Sources}}
\begin{{enumerate}}
{references}
\end{{enumerate}}

\end{{document}}
"""


def compile_research_plan_pdf(
    tex_path: Path | str,
    *,
    timeout_seconds: int = 120,
) -> tuple[str, Path | None, str | None, int | None]:
    """Compile a research-plan PDF with local LaTeX tools."""

    tex_path = Path(tex_path)
    log_path = tex_path.with_suffix(".compile.log")
    command = _latex_command(tex_path)
    if command is None:
        reason = "latexmk or xelatex was not found on PATH"
        log_path.write_text(reason + "\n", encoding="utf-8")
        return "failed_missing_latex", None, reason, None

    try:
        result = subprocess.run(
            command,
            cwd=tex_path.parent,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        reason = f"LaTeX compilation timed out after {timeout_seconds} seconds"
        log_path.write_text(
            f"{reason}\n{_process_output(exc.stdout)}\n{_process_output(exc.stderr)}",
            encoding="utf-8",
        )
        return "failed_timeout", None, reason, None

    log_path.write_text(f"{result.stdout}\n{result.stderr}", encoding="utf-8")
    pdf_path = tex_path.with_suffix(".pdf")
    if result.returncode != 0 or not pdf_path.is_file():
        reason = f"LaTeX exited with code {result.returncode}"
        return "failed", None, reason, None

    page_count = _pdf_page_count(pdf_path)
    return "compiled", pdf_path, None, page_count


def _build_plan(
    *,
    candidate: ResearchCandidate,
    project_id: str,
    context_refs: tuple[str, ...],
) -> ResearchPlan:
    method = _metadata_value(candidate.metadata, "method", "evidence-calibrated method")
    dataset = _metadata_value(candidate.metadata, "dataset", "approved public benchmark")
    baseline = _metadata_value(candidate.metadata, "baseline", "strong public baseline")
    metric = _metadata_value(candidate.metadata, "metric", "primary task metric")
    limitation = _metadata_value(candidate.metadata, "limitation", candidate.research_gap)
    title = _derive_plan_title(candidate=candidate, method=method, dataset=dataset)
    evidence_refs = tuple(dict.fromkeys([*candidate.evidence_refs, *context_refs]))
    references = tuple(_format_reference(ref) for ref in evidence_refs)
    experiments = (
        f"Reproduce the baseline ({baseline}) on {dataset} and record {metric}, "
        "runtime, data split, random seed, and environment hashes.",
        f"Implement the proposed {method} variant as a separate script and compare it "
        f"against the baseline using the same {metric} definition.",
        "Run an ablation that removes the main proposed mechanism so the claimed "
        "contribution can be isolated from prompt, data, and pipeline effects.",
        "Run a robustness check with at least two seeds or an approved hold-out split, "
        "then write metrics, logs, and failure cases into the vault.",
    )
    code_agent_brief = (
        "Create a project-local experiment package under runs/<project-id>/research-plan/ "
        "with scripts for baseline reproduction, proposed-method execution, ablation, "
        "and metric aggregation. Preferred command shape: python -m pytest tests/unit "
        "for code checks, then python scripts/run_experiment.py --config "
        "configs/research-plan.yaml --output runs/<project-id>/metrics.json. Store "
        "raw logs, metrics.json, validation.json, and a short Markdown run record; do "
        "not replace expected results with claims until these files exist."
    )
    return ResearchPlan(
        project_id=project_id,
        candidate_id=candidate.id,
        title=title,
        problem_statement=(
            f"{candidate.research_gap} The plan narrows this gap into a testable "
            f"question on {dataset}: whether {method} can improve the measured "
            f"{metric} while remaining reproducible against {baseline}."
        ),
        rationale=(
            f"The selected direction has candidate scores novelty={candidate.novelty_score:.2f}, "
            f"feasibility={candidate.feasibility_score:.2f}, impact={candidate.impact_score:.2f}. "
            f"Its main rationale is: {candidate.description} The current limitation to address is: "
            f"{limitation}."
        ),
        technical_details=(
            f"Core method: {method}. Baseline/control: {baseline}. Dataset route: {dataset}. "
            f"Primary metric: {metric}. The implementation must keep data ingestion, training or "
            "evaluation, metric calculation, and evidence export as separate steps so each claim can "
            "be mapped back to a concrete artifact."
        ),
        datasets={
            "source": dataset,
            "target": (
                "An approved hold-out split, rerun seed set, or adjacent public benchmark selected "
                "after source-license and leakage checks."
            ),
        },
        methods=(
            f"Use {baseline} as the first control, then evaluate {method} with the same preprocessing, "
            f"split policy, and {metric} implementation. The comparison must include an ablation and "
            "a reproducibility rerun before the plan can feed a paper draft."
        ),
        experiments=list(experiments),
        expected_results=(
            f"Expected, not yet observed: the proposed method should show a measurable {metric} "
            "change relative to the baseline only if the run artifacts support it. Until real "
            "metrics exist, this section is a hypothesis and must not be cited as an experimental result."
        ),
        code_agent_brief=code_agent_brief,
        risks_and_alternatives=[
            "If the baseline cannot be reproduced, stop and write a failure note before changing the method.",
            "If the dataset license, split, or provenance is unclear, switch to an approved public benchmark.",
            "If the proposed method does not improve the primary metric, analyze failure modes and keep the negative result.",
        ],
        references=list(references),
        evidence_refs=list(evidence_refs),
        metadata={
            "candidate_title": candidate.title,
            "candidate_status": candidate.status.value,
            "candidate_validation_status": candidate.validation_status.value,
        },
    )


def _write_plan_markdown(
    *,
    vault_root: Path,
    project_id: str,
    plan: ResearchPlan,
    audit: ResearchPlanAudit,
    markdown: str,
) -> Path:
    entry = KnowledgeEntry(
        entry_type=KnowledgeEntryType.RESEARCH_PLAN,
        zone=KnowledgeZone.PROJECT,
        title=plan.title,
        project_id=project_id,
        tags=["research-plan", "execution-gate", audit.verdict.value],
        keywords=_keywords_for_plan(plan),
        source_refs=plan.evidence_refs,
        body=markdown,
    )
    store = MarkdownKnowledgeStore(vault_root)
    relative_path = Path("projects") / project_id / "plans" / "research-plan.md"
    return store.write_entry(relative_path, entry)


def _derive_plan_title(*, candidate: ResearchCandidate, method: str, dataset: str) -> str:
    title = _clean_title(candidate.title)
    if title and not _contains_any(title, (*FORBIDDEN_TITLE_TERMS, *FORBIDDEN_PLAN_TERMS)):
        return title
    method_title = _smart_title(method) or "Evidence-Calibrated Method"
    dataset_title = _smart_title(dataset) or "Public Benchmark"
    return f"{method_title} for {dataset_title} with Evidence-Calibrated Evaluation"


def _metadata_value(metadata: Mapping[str, Any], key: str, default: str) -> str:
    value = metadata.get(key)
    if value is None:
        return default
    if isinstance(value, str):
        value = value.strip()
        return value or default
    return str(value)


def _context_refs(
    *,
    similarity_summary: Path | str | None,
    literature_summary: Path | str | None,
    inspiration_summary: Path | str | None,
) -> tuple[str, ...]:
    refs: list[str] = []
    for label, value in (
        ("similarity_summary", similarity_summary),
        ("literature_summary", literature_summary),
        ("inspiration_summary", inspiration_summary),
    ):
        if value is not None:
            refs.append(f"{label}:{Path(value).as_posix()}")
    return tuple(refs)


def _format_reference(ref: str) -> str:
    if ref.startswith(("http://", "https://", "doi:", "arxiv:", "pmid:")):
        return ref
    return f"Evidence artifact: {ref}"


def _keywords_for_plan(plan: ResearchPlan) -> list[str]:
    candidates = [
        "research-plan",
        plan.project_id,
        plan.candidate_id,
        *re.split(r"[^A-Za-z0-9_]+", plan.title),
    ]
    return sorted({item.casefold() for item in candidates if item and len(item) > 2})


def _rubric_scores(*, issue_count: int, warning_count: int) -> dict[str, float]:
    penalty = issue_count * 12.0 + warning_count * 2.0
    return {
        "scientific_value": max(0.0, 40.0 - penalty * 0.4),
        "technical_depth": max(0.0, 30.0 - penalty * 0.3),
        "application_potential": max(0.0, 30.0 - penalty * 0.3),
    }


def _latex_command(tex_path: Path) -> list[str] | None:
    if shutil.which("latexmk"):
        return [
            "latexmk",
            "-xelatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            tex_path.name,
        ]
    if shutil.which("xelatex"):
        return ["xelatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
    return None


def _process_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _pdf_page_count(pdf_path: Path) -> int | None:
    pdfinfo = shutil.which("pdfinfo")
    if not pdfinfo:
        return None
    result = subprocess.run(
        [pdfinfo, str(pdf_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if line.startswith("Pages:"):
            _, value = line.split(":", 1)
            try:
                return int(value.strip())
            except ValueError:
                return None
    return None


def _tex_reference(value: str) -> str:
    if value.startswith(("http://", "https://")):
        return rf"\url{{{_tex_url_escape(value)}}}"
    artifact_prefix = "Evidence artifact: "
    if value.startswith(artifact_prefix):
        artifact_ref = value[len(artifact_prefix) :]
        if "/" in artifact_ref or "\\" in artifact_ref or ":" in artifact_ref:
            return rf"{_tex_escape(artifact_prefix)}\url{{{_tex_url_escape(artifact_ref)}}}"
    return _tex_escape(value)


def _tex_escape(value: object) -> str:
    text = str(value)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in text)


def _tex_url_escape(value: object) -> str:
    text = str(value).replace("\\", "/")
    return text.replace("{", "%7B").replace("}", "%7D").replace(" ", "%20")


def _clean_title(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" -:\t\r\n")


def _smart_title(value: str) -> str:
    clean = _clean_title(value)
    if not clean:
        return ""
    return " ".join(_smart_title_token(token) for token in clean.split(" "))


def _smart_title_token(token: str) -> str:
    parts = token.split("-")
    return "-".join(_smart_title_part(part) for part in parts)


def _smart_title_part(part: str) -> str:
    if not part:
        return part
    if part.isupper() and len(part) > 1:
        return part
    if any(char.isupper() for char in part[1:]):
        return part
    return part[:1].upper() + part[1:]


def _contains_any(value: str, terms: Iterable[str]) -> bool:
    normalized = _normalize(value)
    return any(term in normalized for term in terms)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()
