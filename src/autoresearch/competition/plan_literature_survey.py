"""让系统自主完成文献调研，并保证引文可核验。

为什么不能让模型直接写参考文献
------------------------------
榜题明令"严禁虚构"。但语言模型写出一条格式完美、作者像真人、DOI 像真 DOI 的引文，
成本与写一条真引文完全相同。提示词里说"不要编造"是一个请求，不是一个保证。

所以这里把文献调研拆成两步，让"真实"成为结构性事实而不是承诺：

1. **检索词由系统撰写**。模型读自己的计划，决定该查什么。这一步是科学判断，属于系统。
2. **引文由检索器返回**。条目只能来自 ArXiv / OpenAlex 的真实响应。模型不能新增条目，
   只能从检索结果里挑选并说明每条与本计划的关联。

模型能选、能解释，但不能凭空生成一条引文。这样即使模型倾向于编造，编造的对象也不存在。

选择性的边界
------------
让模型挑选是必要的：检索前十条里通常只有几条真正相关，全塞进参考文献是充数。但挑选
必须落在检索结果的索引上，越界的索引会被丢弃而不是被信任。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autoresearch.literature.models import AcademicPaper, deduplicate_papers
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion

_MAX_QUERIES = 4
_RESULTS_PER_QUERY = 8
_MAX_SELECTED = 10


class PlanLiteratureSurveyError(RuntimeError):
    """当文献调研无法在不虚构的前提下完成时抛出。"""


_QUERY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["queries"],
    "properties": {
        "queries": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": _MAX_QUERIES,
        }
    },
}

_SELECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["selections"],
    "properties": {
        "selections": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["index", "relevance"],
                "properties": {
                    "index": {"type": "integer"},
                    "relevance": {"type": "string"},
                },
            },
            "minItems": 1,
        }
    },
}


def _author_queries(
    *,
    focus: Mapping[str, Any],
    completion: Callable[..., LLMJsonCompletionResult],
    config_path: Path | str,
    env_path: Path | str,
) -> list[str]:
    """让系统读自己的研究焦点，决定该检索什么。检索词是科学判断，属于系统。

    `focus` 可以是一份已写好的计划，也可以只是冻结证据。后者是**正确的调用时机**：
    `P-20260808-095` 记录过，先写计划再检索会让计划无法引用它还没见过的文献，
    参考文献于是退化成装饰。文献调研应当先行，计划据此撰写。
    """

    context = {
        "your_research_focus": {
            key: focus.get(key)
            for key in (
                "title",
                "problem_statement",
                "rationale",
                "methods",
                "observed_failures",
                "domain",
            )
            if focus.get(key)
        },
        "instruction": (
            "You are about to survey the real literature BEFORE you write your research "
            "plan, so that the plan can cite and build on prior work. Write the search "
            "queries you want run against ArXiv and OpenAlex. Target the mechanism and "
            "the method family implied by the focus above, not any internal benchmark "
            "or lineage identifier: those names appear in no published paper. Use "
            "English keywords, since these indexes are English-language."
        ),
    }
    result = completion(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are the autonomous research system choosing what literature "
                    "to retrieve. Return exactly one json object satisfying this "
                    "schema, with no prose outside it: "
                    + json.dumps(_QUERY_SCHEMA, ensure_ascii=False, sort_keys=True)
                ),
            },
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ],
        config_path=config_path,
        env_path=env_path,
        timeout_seconds=120,
        max_tokens=1_500,
        temperature=0.3,
        thinking_mode="enabled",
        thinking_budget=2_000,
        response_schema=None,
        response_schema_name="literature_queries",
    )
    queries = result.parsed_json.get("queries") or []
    cleaned = [str(q).strip() for q in queries if str(q).strip()]
    if not cleaned:
        raise PlanLiteratureSurveyError("系统未能给出任何检索词")
    return cleaned[:_MAX_QUERIES]


def _select_papers(
    *,
    focus: Mapping[str, Any],
    papers: Sequence[AcademicPaper],
    completion: Callable[..., LLMJsonCompletionResult],
    config_path: Path | str,
    env_path: Path | str,
) -> list[tuple[AcademicPaper, str]]:
    """让系统从检索结果里挑选并说明关联。越界索引被丢弃，而不是被信任。"""

    catalog = [
        {
            "index": index,
            "title": paper.title,
            "authors": paper.authors[:6],
            "venue": paper.venue,
            "date": str(paper.publication_date) if paper.publication_date else None,
            "abstract": (paper.abstract or "")[:600],
        }
        for index, paper in enumerate(papers)
    ]
    context = {
        "your_research_focus": {
            key: focus.get(key)
            for key in (
                "title",
                "problem_statement",
                "rationale",
                "methods",
                "observed_failures",
                "domain",
            )
            if focus.get(key)
        },
        "retrieved_papers": catalog,
        "instruction": (
            "These are REAL papers retrieved from ArXiv and OpenAlex. Select the ones "
            "your work genuinely builds on or is positioned against, and state for "
            "each what it contributes. Refer to papers ONLY by their index from the "
            "list above. You cannot add a paper that is not listed: an index outside "
            "the list will be discarded. Selecting fewer, more relevant papers is "
            "better than padding the list."
        ),
    }
    result = completion(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are the autonomous research system selecting citations for "
                    "your own plan. Return exactly one json object satisfying this "
                    "schema, with no prose outside it: "
                    + json.dumps(_SELECT_SCHEMA, ensure_ascii=False, sort_keys=True)
                ),
            },
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ],
        config_path=config_path,
        env_path=env_path,
        timeout_seconds=180,
        max_tokens=3_000,
        temperature=0.2,
        thinking_mode="enabled",
        thinking_budget=2_000,
        response_schema=None,
        response_schema_name="literature_selection",
    )
    selections = result.parsed_json.get("selections") or []
    chosen: list[tuple[AcademicPaper, str]] = []
    seen: set[int] = set()
    for item in selections:
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        # 越界索引说明模型试图引用不存在的条目，丢弃而不是补一条。
        if index < 0 or index >= len(papers) or index in seen:
            continue
        seen.add(index)
        chosen.append((papers[index], str(item.get("relevance") or "").strip()))
    if not chosen:
        raise PlanLiteratureSurveyError(
            "系统未能从检索结果中选出任何文献；不会用编造的条目填补"
        )
    return chosen[:_MAX_SELECTED]


def survey_literature_for_plan(
    *,
    focus: Mapping[str, Any],
    searchers: Mapping[str, Callable[..., list[AcademicPaper]]],
    completion: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    clock: datetime | None = None,
) -> list[dict[str, Any]]:
    """做一次真实文献调研，返回可核验的引文列表。

    应当在撰写计划**之前**调用，把结果作为撰写上下文传入，这样计划才能真正引用先前
    工作。`focus` 因此接受冻结证据而不强求一份完整计划。

    `searchers` 形如 `{"arxiv": client.search, "openalex": client.search}`。注入而非
    内部构造，使测试可以在不联网的前提下验证"引文只能来自检索结果"这条性质。
    """

    now = clock or datetime.now(timezone.utc)
    queries = _author_queries(
        focus=focus, completion=completion, config_path=config_path, env_path=env_path
    )

    collected: list[AcademicPaper] = []
    origin: dict[str, str] = {}
    for query in queries:
        for source_name, search in searchers.items():
            try:
                found = search(query, limit=_RESULTS_PER_QUERY)
            except Exception:  # noqa: BLE001 - 单个检索源失败不应终止整次调研
                continue
            for paper in found:
                collected.append(paper)
                origin.setdefault(paper.title.casefold(), source_name)

    if not collected:
        raise PlanLiteratureSurveyError(
            "所有检索源都没有返回结果；不会退化成让模型自行写参考文献"
        )

    unique = deduplicate_papers(collected)
    selected = _select_papers(
        focus=focus,
        papers=unique,
        completion=completion,
        config_path=config_path,
        env_path=env_path,
    )

    retrieved_at = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    references: list[dict[str, Any]] = []
    for paper, relevance in selected:
        references.append(
            {
                "title": paper.title,
                "authors": list(paper.authors),
                "venue": paper.venue,
                "publication_date": (
                    str(paper.publication_date) if paper.publication_date else None
                ),
                "doi": paper.doi,
                "url": paper.url,
                # 来源与时间使引文可追溯到一次具体的检索，而非一次生成。
                "retrieved_from": origin.get(paper.title.casefold(), paper.source),
                "retrieved_at": retrieved_at,
                "relevance_to_plan": relevance,
            }
        )
    return references
