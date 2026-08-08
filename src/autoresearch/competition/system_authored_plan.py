"""The system authors its own research plan; deterministic graders teach it.

Why this exists
---------------
`P-20260804-086`: `build_official_research_plan` contains no model call. Its
`problem_statement`, `rationale`, `technical_details`, and `expected_results` are
hardcoded string literals, so the scientific FRAMING of every lineage was authored by
an agent rather than by the system. The measured numbers were the system's; the science
around them was not.

This module inverts that. The model authors every prose field. Deterministic graders
decide whether what it wrote is acceptable, and on failure the exact grader findings go
back to the model so it can repair its own plan. Nothing here composes a scientific
claim, suggests a hypothesis, or supplies a sentence the plan can reuse.

The teaching mechanism
---------------------
A grader that only says "no" teaches nothing. Each refusal returns the specific finding
that caused it, so the model converges on the standard rather than guessing at it. This
is the same loop the candidate implementations already use, applied to the plan.

What is deterministic on purpose, and why
-----------------------------------------
* `evidence_refs` are derived from artifacts that EXIST on disk. If the model supplied
  them it could cite a package that was never written, and a plan that cites
  non-existent evidence is worse than one with no citations.
* `project_id` and `candidate_id` are identifiers, not science.
* Every frozen constraint is passed in as context and never re-authored.

Domain-agnostic: this module names no benchmark, stratum, metric, or method family. It
passes whatever frozen evidence it is given and grades whatever comes back.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.competition.language_guard import non_chinese_prose_fields
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.competition.plan_execution_contract import (
    PlanExecutionContractError,
    extract_required_method_tokens,
)
from autoresearch.competition.research_plan_markdown import (
    render_plan_artifact_markdown,
)
from autoresearch.competition.system_authored_outcome import (
    audit_numeric_traceability,
    collect_evidence_numbers,
)
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion
from autoresearch.research.plans import ResearchPlan, ResearchPlanStatus, audit_research_plan

_PLAN_NAME = "system-authored-research-plan.json"
_MAX_AUTHORING_ATTEMPTS = 4

# A plan must admit that its own expectation may fail. Without this a "plan" is an
# announcement of a result, and the preregistration protects nothing.
# A brief that names a script which does not exist is not executable, however
# command-shaped it looks. `P-20260804-089`: an authored brief invoked
# `pytest test_candidate.py` with flags that exist nowhere in the repository, and the
# quality rubric passed it because it contained the word `pytest`.
#
# Only HOST-relative script paths are checked. A brief legitimately references paths
# inside the pinned container (`/harness/runner.py`), which do not exist on the host,
# so absolute and container paths are out of scope for this guard.
_HOST_SCRIPT_PATTERN = re.compile(
    r"(?<![\w./\\-])(?!/)([A-Za-z0-9_][A-Za-z0-9_./\\-]*\.py)\b"
)

# Absolute paths were originally exempt so a brief could reference the pinned
# container. `P-20260804-089` continued: the system then satisfied the guard by
# inventing CONTAINER paths instead (`/app/run_grammar_conditioned_search.py`), so the
# exemption became an escape hatch. An absolute path is now only accepted if the caller
# declared it as a real entry point.
_ABSOLUTE_SCRIPT_PATTERN = re.compile(r"(/[A-Za-z0-9_][A-Za-z0-9_./-]*\.py)\b")

# `P-20260808-095`: 这些标记原本只有英文，而计划的交付语言是中文。系统若用中文撰写，
# 可反驳性检查会永远判定"未声明反驳条件"并拒收，于是系统被迫用英文写作才能通过自己的
# grader——语言混杂正是这么来的，不是模型的选择。
#
# 这与 `P-20260807-092` 同一缺陷类：grader 检的是词汇而非实质。标记因此改为中英双语，
# 让同一份判断在两种语言下都成立。
_FALSIFIABILITY_MARKERS: tuple[str, ...] = (
    # 英文
    "negative",
    "null",
    "may fail",
    "does not",
    "would refute",
    "if the effect",
    "not yet observed",
    "fails to",
    # 中文：反驳、零结果、未达成
    "反驳",
    "推翻",
    "否定",
    "零结果",
    "负结果",
    "负值",
    "无改进",
    "未能",
    "不成立",
    "若未",
    "如果未",
    "低于",
    "尚未观测",
    "有效结果",
)

# 行内引用形如 [1]、[2]，编号对应传入 surveyed_literature 的 index。
_CITATION_PATTERN = re.compile(r"\[(\d{1,2})\]")

# 必须携带行内引用的字段。一份对先前工作零定位的文档不是研究计划。
_FIELDS_REQUIRING_CITATION: tuple[str, ...] = (
    "problem_statement",
    "rationale",
    "methods",
)

def authored_plan_non_chinese_fields(plan: ResearchPlan) -> tuple[str, ...]:
    """Return every model-authored plan field that is not predominantly Chinese.

    Machine identifiers, commands, and standard method names may remain Latin, but
    the surrounding title and scientific prose must be Chinese.  Bibliographic titles,
    DOI/URL values, and derived evidence paths are intentionally excluded.
    """

    prose_failures = non_chinese_prose_fields(
        {
            "title": plan.title,
            "abstract": plan.abstract,
            "problem_statement": plan.problem_statement,
            "rationale": plan.rationale,
            "technical_details": plan.technical_details,
            "datasets.source": plan.datasets.get("source", ""),
            "datasets.target": plan.datasets.get("target", ""),
            "methods": plan.methods,
            "experiments": plan.experiments,
            "baselines": plan.baselines,
            "metrics": plan.metrics,
            "expected_results": plan.expected_results,
            "risks_and_alternatives": plan.risks_and_alternatives,
        }
    )
    # The runnable brief necessarily carries a Python command, paths, flags, and the
    # literal method-token contract.  It still needs Chinese explanatory prose, but a
    # lower ratio prevents those required machine tokens from being mistaken for an
    # English narrative.
    brief_failures = non_chinese_prose_fields(
        {"code_agent_brief": plan.code_agent_brief}, minimum_ratio=0.35
    )
    return prose_failures + brief_failures


class SystemAuthoredPlanError(RuntimeError):
    """Raised when an authored plan cannot be accepted by its own graders."""


class AuthoredPlanGuardReport(StrictFrozenModel):
    """Every deterministic finding about one authored plan."""

    schema_version: Literal["authored-plan-guard-report-v1"] = (
        "authored-plan-guard-report-v1"
    )
    quality_gate_passed: bool
    quality_gate_issues: tuple[str, ...]
    quality_gate_warnings: tuple[str, ...]
    quality_gate_score: float
    # Guards this module adds on top of the shared quality gate.
    all_cited_evidence_exists: bool
    missing_evidence_paths: tuple[str, ...]
    numbers_traceable: bool
    untraceable_numbers: tuple[str, ...]
    states_falsifiable_expectation: bool
    claims_no_unobserved_result: bool
    named_scripts_exist: bool
    missing_script_paths: tuple[str, ...]
    accepted: bool
    findings: tuple[str, ...]
    report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate(self) -> AuthoredPlanGuardReport:
        if self.accepted != (not self.findings):
            raise SystemAuthoredPlanError(
                "the guard verdict contradicts its own finding list"
            )
        if self.all_cited_evidence_exists != (not self.missing_evidence_paths):
            raise SystemAuthoredPlanError(
                "the evidence verdict contradicts its own missing list"
            )
        if self.numbers_traceable != (not self.untraceable_numbers):
            raise SystemAuthoredPlanError(
                "the traceability verdict contradicts its own untraceable list"
            )
        if self.named_scripts_exist != (not self.missing_script_paths):
            raise SystemAuthoredPlanError(
                "the script verdict contradicts its own missing list"
            )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"report_hash"})
        )
        if self.report_hash != expected:
            raise SystemAuthoredPlanError("authored plan guard report hash mismatch")
        return self


class SystemAuthoredPlanArtifact(StrictFrozenModel):
    """An authored plan plus the graders that accepted it."""

    schema_version: Literal["system-authored-research-plan-v1"] = (
        "system-authored-research-plan-v1"
    )
    lineage_id: str = Field(min_length=1)
    plan: dict[str, Any]
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    guard_report: AuthoredPlanGuardReport
    authoring_attempts: int = Field(ge=1)
    model_name: str = Field(min_length=1)
    reasoning_tokens: int = Field(ge=0)
    authored_by_model: Literal[True] = True
    hand_written_prose_field_count: Literal[0] = 0
    execution_authorized: Literal[False] = False
    is_evidence: Literal[False] = False
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate(self) -> SystemAuthoredPlanArtifact:
        if not self.guard_report.accepted:
            raise SystemAuthoredPlanError(
                "a plan artifact cannot be constructed from a refused plan; the "
                "refusal must be raised rather than persisted as an accepted plan"
            )
        expected_plan_hash = canonical_model_hash(self.plan)
        if self.plan_hash != expected_plan_hash:
            raise SystemAuthoredPlanError("system authored plan payload hash mismatch")
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"artifact_hash", "output_path"})
        )
        if self.artifact_hash != expected:
            raise SystemAuthoredPlanError("system authored plan artifact hash mismatch")
        return self


def plan_reachable_numbers(evidence_numbers: set[str]) -> set[str]:
    """Extend evidence numbers with arithmetic a PLAN may legitimately perform.

    `P-20260804-087`: a plan does budget arithmetic. Writing "6 systems by 3 seeds is
    18 cells" is correct reasoning, but 18 appears nowhere in the frozen evidence, so
    strict traceability refused a sound plan.

    This registers pairwise products and sums of the small integers already present in
    the evidence, plus small ordinals for enumerated steps. It is deliberately NOT
    applied to result interpretation, where every number is a measured value and must
    match exactly.
    """

    integers: set[int] = set()
    for token in evidence_numbers:
        try:
            value = float(token)
        except ValueError:
            continue
        if value.is_integer() and 0 <= abs(value) <= 10_000:
            integers.add(int(value))

    reachable = set(evidence_numbers)
    # Ordinals for enumerated steps and short lists.
    reachable.update(str(index) for index in range(1, 21))
    for left in integers:
        for right in integers:
            for derived in (left * right, left + right, left - right):
                if 0 <= abs(derived) <= 1_000_000:
                    reachable.add(str(derived))
    return reachable


def _existing_evidence_refs(paths: Sequence[Path | str]) -> tuple[list[str], list[str]]:
    """Split candidate references into those that exist and those that do not."""

    present: list[str] = []
    missing: list[str] = []
    for item in paths:
        path = Path(item)
        if path.exists():
            present.append(path.as_posix())
        else:
            missing.append(path.as_posix())
    return present, missing


def guard_authored_plan(
    *,
    plan: ResearchPlan,
    evidence_numbers: set[str],
    cited_evidence: Sequence[Path | str],
    repo_root: Path = Path("."),
    container_entry_points: Sequence[str] = (),
    literature_count: int = 0,
    require_chinese: bool = False,
) -> AuthoredPlanGuardReport:
    """Grade an authored plan deterministically. Every finding is actionable.

    Reuses the shared `audit_research_plan` rubric rather than inventing a second
    standard, then adds the three checks that rubric cannot make: that cited evidence
    exists on disk, that every number traces to the frozen evidence, and that the
    expectation is stated falsifiably.
    """

    audit = audit_research_plan(plan)
    findings: list[str] = [f"quality gate: {item}" for item in audit.issues]

    present, missing = _existing_evidence_refs(cited_evidence)
    if missing:
        findings.append(
            "these cited evidence paths do not exist on disk, so they cannot be "
            f"cited: {missing}"
        )

    # `P-20260808-095`：交付语言是中文，但从未有任何检查强制它，于是产出中英混杂。
    if require_chinese:
        too_english = authored_plan_non_chinese_fields(plan)
        if too_english:
            findings.append(
                "以下系统撰写字段必须用简体中文，当前中文占比过低："
                f"{list(too_english)}。技术标识符（字段名、门禁名、系统名、路径、命令）"
                "保持英文原样，其余散文必须中文。"
            )

    # `P-20260808-095`：参考文献曾是装饰——列了 7 条，正文一次都没引用。
    # 根因是我把顺序做反了（先写计划再检索），现在文献先行，于是可以强制引用。
    if literature_count:
        uncited: list[str] = []
        out_of_range: set[str] = set()
        for field in _FIELDS_REQUIRING_CITATION:
            value = str(getattr(plan, field, "") or "")
            hits = _CITATION_PATTERN.findall(value)
            if not hits:
                uncited.append(field)
            for hit in hits:
                if not (1 <= int(hit) <= literature_count):
                    out_of_range.add(hit)
        if uncited:
            findings.append(
                f"以下字段缺少对已调研文献的行内引用：{uncited}。"
                f"请用 [1]..[{literature_count}] 形式引用 surveyed_literature 中的条目；"
                "一份对先前工作零定位的文档不是研究计划。"
            )
        if out_of_range:
            findings.append(
                f"这些引用编号超出已调研文献范围：{sorted(out_of_range)}。"
                f"可用编号只有 1..{literature_count}，超范围的编号等同于虚构引用。"
            )

    prose = "\n".join(
        [
            plan.title,
            plan.problem_statement,
            plan.rationale,
            plan.technical_details,
            plan.methods,
            plan.expected_results,
            plan.code_agent_brief,
            *plan.experiments,
            *plan.risks_and_alternatives,
            str(plan.datasets.get("source", "")),
            str(plan.datasets.get("target", "")),
        ]
    )
    traceability = audit_numeric_traceability(
        prose=prose, allowed_numbers=plan_reachable_numbers(evidence_numbers)
    )
    if not traceability.passed:
        findings.append(
            "these numbers appear in the plan but not in the frozen evidence, so "
            "they were invented rather than derived: "
            f"{list(traceability.untraceable_numbers)}"
        )

    expected_lower = plan.expected_results.lower()
    falsifiable = any(marker in expected_lower for marker in _FALSIFIABILITY_MARKERS)
    if not falsifiable:
        findings.append(
            "expected_results must state what outcome would REFUTE the expectation, "
            "and must acknowledge that a negative or null result is a valid outcome; "
            "a plan that only describes success is an announcement, not a plan"
        )

    # A plan is written before observation, so it must not assert an achieved result.
    # Only PAST-TENSE assertions of an achieved result. `P-20260804-087`: an earlier
    # pattern flagged "outperforms", which is how a legitimate expectation is phrased
    # ("is expected to outperform"), so correct plans were refused.
    # `P-20260808-095`: 中文分支同样必要。原正则只认英文，所以一份中文计划写下
    # "实验结果表明本方法优于基线" 也能过关——检查会漏掉它本该拦住的越界宣称。
    # 中文无词边界，故不用 `\b`。刻意只匹配"已然"语气：
    # "预期优于基线" 是合法的预期表述，不能拦。
    achieved = re.search(
        r"\b(?:we (?:achieved|obtained|observed|showed|demonstrated)|"
        r"(?:the )?results? (?:showed|demonstrated|confirmed)|"
        r"(?:has|have|had) outperformed|outperformed the)\b"
        r"|(?:实验|结果|测量|数据)(?:表明|显示|证实|证明)"
        r"|(?:我们|本方法|该方法)(?:已|已经)(?:达到|取得|获得|实现|观测到|验证)"
        r"|(?:已|已经)(?:优于|超过|超越)(?:基线|baseline)",
        prose.lower(),
    )
    claims_no_result = achieved is None
    if achieved:
        findings.append(
            "the plan asserts an achieved result before any measurement exists: "
            f"{achieved.group(0)!r}; state expectations, not outcomes"
        )

    # A brief naming a script that does not exist cannot be run, so the plan is not
    # executable however command-shaped its prose is.
    brief_text = plan.code_agent_brief + " " + " ".join(plan.experiments)
    named_scripts = sorted(set(_HOST_SCRIPT_PATTERN.findall(brief_text)))
    absent_scripts = [
        name
        for name in named_scripts
        if not (repo_root / name).exists() and not Path(name).exists()
    ]
    # An absolute path must be one the caller declared as real, or it is invented.
    allowed_absolute = set(container_entry_points or ())
    absent_scripts.extend(
        sorted(
            name
            for name in set(_ABSOLUTE_SCRIPT_PATTERN.findall(brief_text))
            if name not in allowed_absolute
        )
    )
    briefs_runnable = not absent_scripts
    if absent_scripts:
        findings.append(
            "the plan names these host scripts, none of which exist, so the brief "
            f"cannot be executed as written: {absent_scripts}. Reference an entry "
            "point that exists, or describe the command in terms of the pinned "
            "container path."
        )

    # A runnable command alone does not prove which scientific method will be coded.
    # Require model-authored, source-checkable method tokens before accepting the plan.
    try:
        extract_required_method_tokens(plan.code_agent_brief)
    except PlanExecutionContractError as exc:
        findings.append(str(exc))

    payload: dict[str, Any] = {
        "schema_version": "authored-plan-guard-report-v1",
        "quality_gate_passed": audit.passed,
        "quality_gate_issues": tuple(audit.issues),
        "quality_gate_warnings": tuple(audit.warnings),
        "quality_gate_score": float(audit.score),
        "all_cited_evidence_exists": not missing,
        "missing_evidence_paths": tuple(missing),
        "numbers_traceable": traceability.passed,
        "untraceable_numbers": traceability.untraceable_numbers,
        "states_falsifiable_expectation": falsifiable,
        "claims_no_unobserved_result": claims_no_result,
        "named_scripts_exist": briefs_runnable,
        "missing_script_paths": tuple(absent_scripts),
        "accepted": not findings,
        "findings": tuple(dict.fromkeys(findings)),
    }
    payload["report_hash"] = canonical_model_hash(payload)
    return AuthoredPlanGuardReport.model_validate(payload)


_AUTHORED_FIELDS: tuple[str, ...] = (
    "title",
    # 榜题《生成结果规范》要求摘要含背景、方法、预期结果三部分。
    "abstract",
    "problem_statement",
    "rationale",
    "technical_details",
    "methods",
    "experiments",
    # 榜题点名要求实验设计包含 Baselines 与 Metrics，所以拆成独立字段，
    # 而不是指望它们埋在 experiments 的散文里。
    "baselines",
    "metrics",
    "expected_results",
    "code_agent_brief",
    "risks_and_alternatives",
    "dataset_source",
    "dataset_target",
    "references",
)

_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": list(_AUTHORED_FIELDS),
    "properties": {
        "title": {"type": "string"},
        "abstract": {"type": "string"},
        "problem_statement": {"type": "string"},
        "rationale": {"type": "string"},
        "technical_details": {"type": "string"},
        "methods": {"type": "string"},
        "experiments": {"type": "array", "items": {"type": "string"}, "minItems": 3},
        "baselines": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "metrics": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "expected_results": {"type": "string"},
        "code_agent_brief": {"type": "string"},
        "risks_and_alternatives": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
        },
        "dataset_source": {"type": "string"},
        "dataset_target": {"type": "string"},
        "references": {"type": "array", "items": {"type": "string"}, "minItems": 1},
    },
}


def _authoring_messages(
    *,
    frozen_context: Mapping[str, Any],
    prior_findings: Sequence[str],
    container_entry_points: Sequence[str] = (),
    literature: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, str]]:
    """Give the system its constraints, its evidence, and the surveyed literature.

    Supply no science. `literature` is passed so the plan can CITE prior work:
    `P-20260808-095` recorded that surveying after authoring left the reference list
    decorative, because the plan had never seen the papers it was supposed to build on.
    """

    instruction = (
        "You are the autonomous research system. Author your OWN research plan for the "
        "next lineage. You decide the problem framing, the mechanism you believe is "
        "responsible, what you will test, and what result would refute you.\n\n"
        "Nothing scientific is supplied to you. The context below carries only frozen "
        "constraints you may not change, and evidence retained from your own prior "
        "lineages. Do not restate the constraints as if they were your reasoning.\n\n"
        # `P-20260808-095`: 交付文档是中文的《科学假设与研究计划》，此前提示词全英文，
        # 导致中文标题配英文正文。语言要求放在最前，因为它约束下面每一条的写法。
        "LANGUAGE: write every prose field in CHINESE (简体中文). This plan is delivered "
        "as a Chinese document and is read by Chinese reviewers. Keep these in their "
        "original form and do NOT translate them, because they are literal identifiers "
        "that a reader must be able to search for in the code and artifacts: field "
        "names (overall_median_log_effect), system names "
        "(reaction_diffusion_cylinder), metric names (NMSE), gate names "
        "(pde_stratum_non_negative), file paths, and commands. Write natural technical "
        "Chinese around them; do not transliterate them into Chinese characters.\n\n"
        # 质量要求。此前产出是 "Risk: ... Alternative: ..." 这类标签拼接，读起来像填表
        # 而非科学写作，所以在这里明确要求成文。
        "WRITING QUALITY: write connected technical prose, not label-prefixed "
        "fragments. Do NOT open items with bare labels like 'Risk:' / 'Alternative:' / "
        "'Phase 1:'; state the risk and its mitigation as complete sentences that "
        "explain the causal reason. Each field must read as if written by a researcher "
        "who understands the mechanism, not as a form filled in. Avoid restating a "
        "number without saying what it implies. Do not pad with the frozen constraints "
        "you were given.\n\n"
        "Hard requirements, each enforced by a deterministic grader that will return "
        "its exact findings to you if you fail:\n"
        "1. Every number you write must already appear in the supplied evidence. An "
        "invented number is refused.\n"
        "2. expected_results must state what outcome would REFUTE your expectation, "
        "and must acknowledge that a negative or null result is a valid outcome. "
        "Writing in Chinese, use explicit wording such as 「若…则假设被反驳」、"
        "「零结果同样是有效结果」、「低于该阈值即推翻本假设」, because the grader looks "
        "for that commitment and a plan that only describes success is an "
        "announcement, not a plan.\n"
        "3. Do not assert any achieved result. No measurement exists yet.\n"
        "4. Name at least one baseline or control, and concrete evaluation metrics. "
        "Put these in the dedicated `baselines` and `metrics` arrays, not only inside "
        "the experiments prose, because they are graded as separate fields.\n"
        "4a. `abstract` must be a self-contained abstract covering THREE parts in "
        "order: the background/problem, the method you propose, and the expected "
        "result. It is read on its own, so do not open with 'as stated above' or refer "
        "to sections the reader has not seen.\n"
        "5. code_agent_brief must be COMMAND-ORIENTED and RUNNABLE: it has to contain "
        "an actual command line, and the grader looks for one of the literal words "
        "'python', 'command', 'script', or 'pytest'. It must NOT invent a script name. "
        "EVERY `.py` path you write is checked, host-relative and absolute alike. The "
        "ONLY entry points that exist are listed below; inventing a plausible-looking "
        "path is refused whether it starts with a slash or not: "
        + (json.dumps(list(container_entry_points)) if container_entry_points else "[]")
        + "\n"
        "5a. End code_agent_brief with 2-8 distinctive ASCII method identifiers in "
        "the literal form required_method_tokens=[token_a, token_b]. Choose tokens "
        "that identify YOUR proposed scientific mechanism, not generic interface "
        "words such as model, method, fit, runner, or candidate. Candidate source is "
        "later checked by AST: every token must occur in a callable actually reached "
        "from fit_equations or predict_derivative; comments, prose, variable names, "
        "and unused helpers cannot pass.\n"
        "6. Use no placeholder text and no reference to any contest or organizer.\n"
        "7. WRITE THE TITLE AND EVERY PROSE FIELD IN CHINESE (简体中文). This document is read by "
        "Chinese reviewers. Keep these in their original form because they are literal "
        "identifiers a reader must be able to match against code and data, and "
        "translating them makes them unfindable: field and gate names, metric names, "
        "system names, file paths, commands, and original bibliography titles. All "
        "authored prose surrounding those literal identifiers must be Chinese.\n"
        "8. WRITE FOR AN EXTERNAL SCIENTIFIC READER, not for an internal issue "
        "tracker. Do NOT build sentences around internal bookkeeping identifiers such "
        "as lineage ids, ledger counters, or budget field names. A reader outside this "
        "system has never seen them and cannot verify them. State the SCIENTIFIC "
        "problem, mechanism, and evidence. When a number matters, say what it measures "
        "and why it matters, not merely which internal gate it belongs to.\n"
        "9. CITE THE SUPPLIED LITERATURE INLINE using bracket numerals that match the "
        "`index` of each paper in `surveyed_literature` below, for example 「稀疏回归"
        "方法[1]」. At minimum, `problem_statement`, `rationale`, and `methods` must "
        "each carry at least one citation, because a plan that positions itself "
        "against no prior work is not a research plan. Cite ONLY the supplied indices: "
        "there is no other literature available to you, and an index that is not in "
        "the list will be treated as fabricated.\n\n"
        "Think first, then answer. Your reasoning is process provenance only and is "
        "never scientific evidence.\n"
        "Return exactly one json object satisfying this schema, with no prose outside "
        "it; local strict validation will reject every extra, missing, or invalid "
        "field: " + json.dumps(_PLAN_SCHEMA, ensure_ascii=False, sort_keys=True)
    )
    if prior_findings:
        instruction += (
            "\n\nYour previous attempt was REFUSED by the graders with these exact "
            "findings. Repair each one. Change only what the findings name; keep the "
            "rest of your plan: " + json.dumps(list(prior_findings), ensure_ascii=False)
        )
    user_payload: dict[str, Any] = dict(frozen_context)
    if literature:
        # 文献以 index 呈现，与提示词里要求的行内引用编号一致，也与最终 LaTeX 参考
        # 文献表的顺序一致，这样正文的 [n] 能被读者对上号。
        user_payload["surveyed_literature"] = [
            {
                "index": position,
                "title": item.get("title"),
                "authors": list(item.get("authors") or [])[:6],
                "venue": item.get("venue"),
                "publication_date": item.get("publication_date"),
                "doi": item.get("doi"),
                "relevance_noted_by_you": item.get("relevance_to_plan"),
            }
            for position, item in enumerate(literature, 1)
        ]
    return [
        {"role": "system", "content": instruction},
        {
            "role": "user",
            "content": json.dumps(user_payload, ensure_ascii=False, sort_keys=True),
        },
    ]


def author_research_plan(
    *,
    lineage_id: str,
    project_id: str,
    candidate_id: str,
    frozen_context: Mapping[str, Any],
    evidence_paths: Sequence[Path | str],
    output_dir: Path | str,
    completion: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    max_attempts: int = _MAX_AUTHORING_ATTEMPTS,
    container_entry_points: Sequence[str] = (),
    literature: Sequence[Mapping[str, Any]] = (),
    require_chinese: bool = True,
) -> SystemAuthoredPlanArtifact:
    """Have the system author its own plan, and let the graders teach it.

    Raises `SystemAuthoredPlanError` if the system cannot satisfy its own graders
    within `max_attempts`. A plan that cannot pass is not quietly downgraded.
    """

    evidence_numbers = collect_evidence_numbers(dict(frozen_context))
    present, missing_inputs = _existing_evidence_refs(evidence_paths)
    if missing_inputs:
        raise SystemAuthoredPlanError(
            f"cannot author a plan against evidence that does not exist: "
            f"{missing_inputs}"
        )
    if not present:
        raise SystemAuthoredPlanError(
            "a plan must cite at least one retained artifact; authoring against no "
            "evidence would produce an unfalsifiable plan"
        )

    findings: list[str] = []
    last_report: AuthoredPlanGuardReport | None = None
    for attempt in range(1, max_attempts + 1):
        result = completion(
            messages=_authoring_messages(
                frozen_context=frozen_context,
                prior_findings=findings,
                container_entry_points=container_entry_points,
                literature=literature,
            ),
            config_path=config_path,
            env_path=env_path,
            timeout_seconds=300,
            max_tokens=8_000,
            temperature=0.3,
            thinking_mode="enabled",
            thinking_budget=4_000,
            response_schema=None,
            response_schema_name="authored_research_plan",
        )
        authored = result.parsed_json
        absent = [field for field in _AUTHORED_FIELDS if field not in authored]
        if absent:
            findings = [f"your json object omitted required fields: {absent}"]
            continue

        plan = ResearchPlan.model_validate(
            {
                "project_id": project_id,
                "candidate_id": candidate_id,
                "title": authored["title"],
                "abstract": authored["abstract"],
                "problem_statement": authored["problem_statement"],
                "rationale": authored["rationale"],
                "technical_details": authored["technical_details"],
                "datasets": {
                    "source": authored["dataset_source"],
                    "target": authored["dataset_target"],
                },
                "methods": authored["methods"],
                "experiments": list(authored["experiments"]),
                "baselines": list(authored["baselines"]),
                "metrics": list(authored["metrics"]),
                "expected_results": authored["expected_results"],
                "code_agent_brief": authored["code_agent_brief"],
                "risks_and_alternatives": list(authored["risks_and_alternatives"]),
                "references": list(authored["references"]),
                # Derived, never authored: a model cannot cite what does not exist.
                "evidence_refs": present,
                # 检索所得的真实文献随计划一起留存，顺序与正文 [n] 编号一致，
                # 这样 LaTeX 参考文献表能与行内引用对上号。
                "literature_references": list(literature),
                "status": ResearchPlanStatus.DRAFT,
            }
        )
        report = guard_authored_plan(
            plan=plan,
            evidence_numbers=evidence_numbers,
            cited_evidence=present,
            container_entry_points=container_entry_points,
            literature_count=len(literature),
            require_chinese=require_chinese,
        )
        last_report = report
        if not report.accepted:
            findings = list(report.findings)
            continue

        audit = audit_research_plan(plan)
        graded = plan.model_copy(
            update={
                "quality_gate": audit.to_dict(),
                "status": ResearchPlanStatus.READY_FOR_APPROVAL,
                "validation_status": audit.verdict,
            }
        )
        usage = result.usage if isinstance(result.usage, dict) else {}
        details = usage.get("completion_tokens_details")
        reasoning_tokens = (
            int(details.get("reasoning_tokens") or 0) if isinstance(details, dict) else 0
        )
        plan_payload = graded.model_dump(mode="json")
        output_path = Path(output_dir).resolve() / _PLAN_NAME
        payload: dict[str, Any] = {
            "schema_version": "system-authored-research-plan-v1",
            "lineage_id": lineage_id,
            "plan": plan_payload,
            "plan_hash": canonical_model_hash(plan_payload),
            "guard_report": report.model_dump(mode="json"),
            "authoring_attempts": attempt,
            "model_name": result.model_name,
            "reasoning_tokens": reasoning_tokens,
            "authored_by_model": True,
            "hand_written_prose_field_count": 0,
            "execution_authorized": False,
            "is_evidence": False,
        }
        payload["artifact_hash"] = canonical_model_hash(payload)
        payload["output_path"] = output_path.as_posix()
        artifact = SystemAuthoredPlanArtifact.model_validate(payload)
        write_json_model(output_path, artifact)
        # 同时落盘一份给人读的 Markdown。JSON 仍是唯一权威（plan_hash 绑定它的规范字节），
        # Markdown 由 JSON 单向派生，且头部写明两个哈希，任何引文都能回溯。
        # 渲染失败不能让一份已经通过全部 grader 的计划丢失，所以这里不向外抛。
        try:
            markdown_path = output_path.with_suffix(".md")
            markdown_path.write_text(
                render_plan_artifact_markdown(artifact.model_dump(mode="json")),
                encoding="utf-8",
            )
        except (OSError, ValueError):
            pass
        # 再落一份《科学假设与研究计划》LaTeX。参考文献用非严格模式：文献调研是独立
        # 步骤，尚未接入时缺口会被显著写进文档，而不是静默放过或由渲染器编造条目。
        try:
            from autoresearch.competition.research_plan_latex import (
                render_research_plan_latex,
            )

            output_path.with_suffix(".tex").write_text(
                render_research_plan_latex(
                    plan=plan_payload,
                    references=plan_payload.get("literature_references") or (),
                    plan_hash=payload["plan_hash"],
                    artifact_hash=payload["artifact_hash"],
                    lineage_id=lineage_id,
                    model_name=result.model_name,
                    strict_references=False,
                ),
                encoding="utf-8",
            )
        except (OSError, ValueError, RuntimeError):
            pass
        return artifact

    detail = list(last_report.findings) if last_report else findings
    raise SystemAuthoredPlanError(
        f"the system could not author a plan its own graders accept in {max_attempts} "
        f"attempts; final findings: {detail}"
    )
