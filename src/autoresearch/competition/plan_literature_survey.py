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
from typing import Any, Literal

from pydantic import Field, model_validator

from autoresearch.competition.language_guard import non_chinese_prose_fields
from autoresearch.competition.manifest import canonical_model_hash, write_json_model
from autoresearch.competition.model_authorship import (
    ModelAuthorshipReceipt,
    record_model_authorship_receipt,
)
from autoresearch.competition.models import StrictFrozenModel
from autoresearch.literature.models import AcademicPaper, deduplicate_papers
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion

_MAX_QUERIES = 4
_RESULTS_PER_QUERY = 8
_MAX_SELECTED = 10
_MIN_PLAN_REFERENCES = 3
_SURVEY_NAME = "plan-literature-survey.json"
_FOCUS_FIELDS = (
    "title",
    "problem_statement",
    "rationale",
    "methods",
    "observed_failures",
    "domain",
    "public_data_profile_summaries",
    "observed_system_effects",
    "exploratory_evidence_panels",
)


class PlanLiteratureSurveyError(RuntimeError):
    """当文献调研无法在不虚构的前提下完成时抛出。"""


class PlanLiteratureSurveyArtifact(StrictFrozenModel):
    """一次先于计划撰写、可重放作者与检索来源的文献调研。"""

    schema_version: Literal["plan-literature-survey-v1"] = (
        "plan-literature-survey-v1"
    )
    lineage_id: str = Field(min_length=1)
    focus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    queries: tuple[str, ...] = Field(min_length=1)
    query_authorship_receipt_relative_path: str
    query_authorship_receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieved_catalog: tuple[dict[str, Any], ...] = Field(min_length=1)
    selected_references: tuple[dict[str, Any], ...] = Field(
        min_length=_MIN_PLAN_REFERENCES
    )
    selection_authorship_receipt_relative_path: str
    selection_authorship_receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    surveyed_before_authoring: bool
    created_at: datetime
    survey_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_path: str

    @model_validator(mode="after")
    def _validate(self) -> PlanLiteratureSurveyArtifact:
        if not self.surveyed_before_authoring:
            raise PlanLiteratureSurveyError("文献调研必须先于研究计划撰写")
        catalog_indices = [item.get("retrieval_index") for item in self.retrieved_catalog]
        if catalog_indices != list(range(len(self.retrieved_catalog))):
            raise PlanLiteratureSurveyError(
                "真实检索目录的 retrieval_index 必须从零连续、唯一且保持检索顺序"
            )
        catalog_by_index = {
            int(item["retrieval_index"]): item for item in self.retrieved_catalog
        }
        selected_indices: list[int] = []
        for reference in self.selected_references:
            retrieval_index = reference.get("retrieval_index")
            if (
                not isinstance(retrieval_index, int)
                or isinstance(retrieval_index, bool)
                or retrieval_index not in catalog_by_index
            ):
                raise PlanLiteratureSurveyError("入选引文的 retrieval_index 不在真实检索目录中")
            selected_indices.append(retrieval_index)
            catalog_item = catalog_by_index[retrieval_index]
            for field_name in ("title", "doi", "url"):
                if reference.get(field_name) != catalog_item.get(field_name):
                    raise PlanLiteratureSurveyError(
                        f"入选引文 {retrieval_index} 的 {field_name} 与检索目录不符"
                    )
            if not str(catalog_item.get("abstract") or "").strip():
                raise PlanLiteratureSurveyError(
                    f"入选引文 {retrieval_index} 缺少摘要，无法进行新颖性核查"
                )
            if not str(reference.get("relevance_to_plan") or "").strip():
                raise PlanLiteratureSurveyError(
                    f"入选引文 {retrieval_index} 缺少中文关联说明"
                )
        if len(set(selected_indices)) != len(selected_indices):
            raise PlanLiteratureSurveyError("入选引文的 retrieval_index 必须互不相同")
        language_failures = non_chinese_prose_fields(
            {
                "relevance_to_plan": tuple(
                    str(item.get("relevance_to_plan") or "")
                    for item in self.selected_references
                )
            }
        )
        if language_failures:
            raise PlanLiteratureSurveyError(
                f"文献关联说明不是中文：{list(language_failures)}"
            )
        expected = canonical_model_hash(
            self.model_dump(mode="json", exclude={"survey_hash", "output_path"})
        )
        if self.survey_hash != expected:
            raise PlanLiteratureSurveyError("文献调研制品哈希不符")
        return self


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
) -> tuple[list[str], LLMJsonCompletionResult, list[dict[str, str]]]:
    """让系统读自己的研究焦点，决定该检索什么。检索词是科学判断，属于系统。

    `focus` 可以是一份已写好的计划，也可以只是冻结证据。后者是**正确的调用时机**：
    `P-20260808-095` 记录过，先写计划再检索会让计划无法引用它还没见过的文献，
    参考文献于是退化成装饰。文献调研应当先行，计划据此撰写。
    """

    context = {
        "your_research_focus": {
            key: focus.get(key) for key in _FOCUS_FIELDS if focus.get(key)
        },
        "instruction": (
            "You are about to survey the real literature BEFORE you write your research "
            "plan, so that the plan can cite and build on prior work. Write the search "
            "queries you want run against ArXiv and OpenAlex. Author four mutually "
            "distinct queries: one for the mainstream method family, one for failures "
            "or negative results, one for identifiability or benchmark-validity limits, "
            "and one for candidate-by-system interactions or component ablations that "
            "could explain the same observations. Use the hash-bound public profile "
            "summaries, signed per-system effects, within-data-type associations, and "
            "cross-lineage effect matrix to target measured contrasts instead of "
            "guessing from system names. Treat those associations as exploratory, "
            "not causal, and treat the "
            "jointly different candidate implementations as component-confounded, not "
            "causal. At least two queries must directly investigate a measured "
            "within-type association or cross-candidate reversal present in those "
            "panels. Do not "
            "merely paraphrase one broad query four times. Target the mechanism and "
            "method family implied by the focus above, not any "
            "internal benchmark or lineage identifier: those names appear in no "
            "published paper. Use English keywords, since these indexes are "
            "English-language."
        ),
    }
    messages = [
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
    ]
    result = completion(
        messages=messages,
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
    return cleaned[:_MAX_QUERIES], result, messages


def _select_papers(
    *,
    focus: Mapping[str, Any],
    papers: Sequence[AcademicPaper],
    completion: Callable[..., LLMJsonCompletionResult],
    config_path: Path | str,
    env_path: Path | str,
    minimum_selected: int,
) -> tuple[
    list[tuple[int, AcademicPaper, str]],
    LLMJsonCompletionResult,
    list[dict[str, str]],
]:
    """让系统从检索结果里挑选并说明关联。越界索引被丢弃，而不是被信任。"""

    if not 1 <= minimum_selected <= _MAX_SELECTED:
        raise PlanLiteratureSurveyError(
            f"minimum_selected 必须介于 1 和 {_MAX_SELECTED} 之间"
        )
    catalog = [
        {
            "index": index,
            "title": paper.title,
            "authors": paper.authors[:6],
            "venue": paper.venue,
            "date": str(paper.publication_date) if paper.publication_date else None,
            "abstract": (paper.abstract or "")[:600],
            "abstract_available": bool(str(paper.abstract or "").strip()),
        }
        for index, paper in enumerate(papers)
    ]
    context = {
        "your_research_focus": {
            key: focus.get(key) for key in _FOCUS_FIELDS if focus.get(key)
        },
        "retrieved_papers": catalog,
        "instruction": (
            "These are REAL papers retrieved from ArXiv and OpenAlex. Select the ones "
            "your work genuinely builds on or is positioned against, and state in "
            "natural SIMPLIFIED CHINESE for each what it contributes. Refer to papers "
            "ONLY by their index from the "
            "list above. You cannot add a paper that is not listed: an index outside "
            "the list will be discarded. You MUST select only entries whose "
            "abstract_available is true, because downstream novelty review must "
            "inspect the retrieved abstract. Select at least "
            f"{minimum_selected} distinct eligible papers and at most {_MAX_SELECTED}; "
            "never pad with an entry that lacks an abstract."
        ),
    }
    messages = [
        {
            "role": "system",
            "content": (
                "You are the autonomous research system selecting citations for "
                "your own plan. Every relevance string must be natural simplified "
                "Chinese. Return exactly one json object satisfying this schema, "
                "with no prose outside it: "
                + json.dumps(_SELECT_SCHEMA, ensure_ascii=False, sort_keys=True)
            ),
        },
        {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
    ]
    result = completion(
        messages=messages,
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
    chosen: list[tuple[int, AcademicPaper, str]] = []
    seen: set[int] = set()
    for item in selections:
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        # 越界索引说明模型试图引用不存在的条目，丢弃而不是补一条。
        if (
            index < 0
            or index >= len(papers)
            or index in seen
            or not str(papers[index].abstract or "").strip()
        ):
            continue
        seen.add(index)
        chosen.append(
            (index, papers[index], str(item.get("relevance") or "").strip())
        )
    if len(chosen) < minimum_selected:
        raise PlanLiteratureSurveyError(
            "系统未能从检索结果中选出至少 "
            f"{minimum_selected} 篇具有摘要的不同文献；"
            "不会用编造或无摘要条目填补"
        )
    return chosen[:_MAX_SELECTED], result, messages


def survey_literature_for_plan(
    *,
    focus: Mapping[str, Any],
    searchers: Mapping[str, Callable[..., list[AcademicPaper]]],
    completion: Callable[..., LLMJsonCompletionResult] = run_llm_json_completion,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    clock: datetime | None = None,
    lineage_id: str | None = None,
    output_dir: Path | str | None = None,
    require_chinese_relevance: bool = True,
    minimum_selected: int = _MIN_PLAN_REFERENCES,
) -> list[dict[str, Any]]:
    """做一次真实文献调研，返回可核验的引文列表。

    应当在撰写计划**之前**调用，把结果作为撰写上下文传入，这样计划才能真正引用先前
    工作。`focus` 因此接受冻结证据而不强求一份完整计划。

    `searchers` 形如 `{"arxiv": client.search, "openalex": client.search}`。注入而非
    内部构造，使测试可以在不联网的前提下验证"引文只能来自检索结果"这条性质。
    """

    if (lineage_id is None) != (output_dir is None):
        raise PlanLiteratureSurveyError(
            "lineage_id 与 output_dir 必须同时提供，才能保存完整调研来源"
        )
    now = clock or datetime.now(timezone.utc)
    queries, query_result, query_messages = _author_queries(
        focus=focus, completion=completion, config_path=config_path, env_path=env_path
    )
    query_receipt: ModelAuthorshipReceipt | None = None
    selection_receipt: ModelAuthorshipReceipt | None = None
    if output_dir is not None:
        query_receipt = record_model_authorship_receipt(
            artifact_kind="literature_queries",
            interaction_id="plan-literature-queries",
            attempt=1,
            messages=query_messages,
            completion=query_result,
            output_dir=output_dir,
            clock=now,
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
    selected, selection_result, selection_messages = _select_papers(
        focus=focus,
        papers=unique,
        completion=completion,
        config_path=config_path,
        env_path=env_path,
        minimum_selected=minimum_selected,
    )
    if output_dir is not None:
        selection_receipt = record_model_authorship_receipt(
            artifact_kind="literature_selection",
            interaction_id="plan-literature-selection",
            attempt=1,
            messages=selection_messages,
            completion=selection_result,
            output_dir=output_dir,
            clock=now,
        )

    retrieved_at = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    references: list[dict[str, Any]] = []
    for index, paper, relevance in selected:
        references.append(
            {
                "retrieval_index": index,
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
    if require_chinese_relevance:
        failures = non_chinese_prose_fields(
            {
                "relevance_to_plan": tuple(
                    str(item["relevance_to_plan"]) for item in references
                )
            }
        )
        if failures:
            raise PlanLiteratureSurveyError(
                f"系统选择文献时没有用中文说明关联：{list(failures)}"
            )

    if output_dir is not None:
        assert lineage_id is not None
        assert query_receipt is not None
        assert selection_receipt is not None
        output_root = Path(output_dir).resolve()
        output_path = output_root / _SURVEY_NAME
        catalog = tuple(
            {
                "retrieval_index": index,
                **paper.model_dump(mode="json"),
                "retrieved_from": origin.get(paper.title.casefold(), paper.source),
            }
            for index, paper in enumerate(unique)
        )
        payload: dict[str, Any] = {
            "schema_version": "plan-literature-survey-v1",
            "lineage_id": lineage_id,
            "focus_sha256": canonical_model_hash(dict(focus)),
            "queries": tuple(queries),
            "query_authorship_receipt_relative_path": _receipt_relative_path(
                query_receipt, output_root=output_root
            ),
            "query_authorship_receipt_hash": query_receipt.receipt_hash,
            "retrieved_catalog": catalog,
            "selected_references": tuple(references),
            "selection_authorship_receipt_relative_path": _receipt_relative_path(
                selection_receipt, output_root=output_root
            ),
            "selection_authorship_receipt_hash": selection_receipt.receipt_hash,
            "surveyed_before_authoring": True,
            "created_at": retrieved_at,
        }
        payload["survey_hash"] = canonical_model_hash(payload)
        payload["output_path"] = output_path.as_posix()
        artifact = PlanLiteratureSurveyArtifact.model_validate(payload)
        write_json_model(output_path, artifact)
    return references


def _receipt_relative_path(
    receipt: ModelAuthorshipReceipt, *, output_root: Path
) -> str:
    path = Path(receipt.output_path).resolve()
    try:
        return path.relative_to(output_root).as_posix()
    except ValueError as exc:
        raise PlanLiteratureSurveyError("模型调用回执位于调研谱系目录之外") from exc
