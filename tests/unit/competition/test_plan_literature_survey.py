"""文献调研的测试：真实性必须是结构性事实，而不是提示词里的承诺。

榜题明令"严禁虚构"。模型写一条假引文和写一条真引文的成本完全相同，所以不能靠请求。
这里验证的核心性质是：**引文只能来自检索器返回的条目**。模型可以挑选、可以解释关联，
但它给出的越界索引会被丢弃，而不是被当成一条新文献。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

import pytest

from autoresearch.competition.plan_literature_survey import (
    PlanLiteratureSurveyError,
    survey_literature_for_plan,
)
from autoresearch.literature.models import AcademicPaper


def _result(payload: dict[str, Any]) -> Any:
    from autoresearch.llm.client import LLMJsonCompletionResult

    return LLMJsonCompletionResult(
        provider="qwen-dashscope",
        base_url="https://dashscope.example/compatible-mode/v1",
        model_name="qwen3.7-max",
        endpoint="https://dashscope.example/v1/chat/completions",
        response_text=json.dumps(payload),
        parsed_json=payload,
        usage={"prompt_tokens": 100, "completion_tokens": 200},
        temperature=0.2,
    )


_PLAN = {
    "title": "Stratified Symbolic Regression",
    "problem_statement": "上一条 lineage 未通过门禁。",
    "rationale": "无约束搜索产生未支持字段。",
    "methods": "受约束的符号回归。",
}


def _papers() -> list[AcademicPaper]:
    return [
        AcademicPaper(
            title="Sparse identification of nonlinear dynamics",
            authors=["S. L. Brunton", "J. L. Proctor", "J. N. Kutz"],
            venue="PNAS",
            publication_date=date(2016, 4, 12),
            doi="10.1073/pnas.1517384113",
            url="https://www.pnas.org/doi/10.1073/pnas.1517384113",
            source="openalex",
        ),
        AcademicPaper(
            title="Data-driven discovery of partial differential equations",
            authors=["S. H. Rudy"],
            venue="Science Advances",
            publication_date=date(2017, 4, 26),
            url="https://arxiv.org/abs/1609.06401",
            source="arxiv",
        ),
    ]


class _Scripted:
    """依次返回排定的响应：第一次是检索词，第二次是选择结果。"""

    def __init__(self, *payloads: dict[str, Any]) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        payload = self.payloads[min(len(self.calls) - 1, len(self.payloads) - 1)]
        return _result(payload)


def test_引文全部来自检索结果() -> None:
    """最要紧的性质：真实性由结构保证。"""

    papers = _papers()
    completion = _Scripted(
        {"queries": ["symbolic regression governing equations"]},
        {"selections": [{"index": 0, "relevance": "本计划的稀疏回归基础"}]},
    )
    refs = survey_literature_for_plan(
        focus=_PLAN,
        searchers={"openalex": lambda q, limit=8: papers},
        completion=completion,
        clock=datetime(2026, 8, 7, tzinfo=timezone.utc),
    )
    assert len(refs) == 1
    assert refs[0]["title"] == "Sparse identification of nonlinear dynamics"
    assert refs[0]["doi"] == "10.1073/pnas.1517384113"
    assert refs[0]["retrieved_from"] == "openalex"
    assert refs[0]["retrieved_at"].startswith("2026-08-07")
    assert refs[0]["relevance_to_plan"] == "本计划的稀疏回归基础"


def test_模型无法凭越界索引新增一条不存在的文献() -> None:
    """模型试图引用第 99 条时，该条必须被丢弃而不是被凭空构造出来。"""

    papers = _papers()
    completion = _Scripted(
        {"queries": ["symbolic regression"]},
        {
            "selections": [
                {"index": 0, "relevance": "真实条目"},
                {"index": 99, "relevance": "这条检索结果里并不存在"},
                {"index": -5, "relevance": "负索引同样不可信"},
            ]
        },
    )
    refs = survey_literature_for_plan(
        focus=_PLAN,
        searchers={"openalex": lambda q, limit=8: papers},
        completion=completion,
    )
    assert len(refs) == 1
    assert all(r["title"] in {p.title for p in papers} for r in refs)


def test_重复索引只计一次() -> None:
    papers = _papers()
    completion = _Scripted(
        {"queries": ["q"]},
        {
            "selections": [
                {"index": 1, "relevance": "第一次"},
                {"index": 1, "relevance": "重复"},
            ]
        },
    )
    refs = survey_literature_for_plan(
        focus=_PLAN,
        searchers={"arxiv": lambda q, limit=8: papers},
        completion=completion,
    )
    assert len(refs) == 1


def test_检索无结果时拒绝退化成模型自行撰写() -> None:
    """宁可失败，也不能让参考文献变成生成物。"""

    completion = _Scripted({"queries": ["q"]}, {"selections": []})
    with pytest.raises(PlanLiteratureSurveyError, match="没有返回结果"):
        survey_literature_for_plan(
            focus=_PLAN,
            searchers={"arxiv": lambda q, limit=8: []},
            completion=completion,
        )


def test_模型一条都没选中时明确失败() -> None:
    papers = _papers()
    completion = _Scripted({"queries": ["q"]}, {"selections": [{"index": 42, "relevance": "无效"}]})
    with pytest.raises(PlanLiteratureSurveyError, match="不会用编造的条目填补"):
        survey_literature_for_plan(
            focus=_PLAN,
            searchers={"arxiv": lambda q, limit=8: papers},
            completion=completion,
        )


def test_单个检索源报错不终止整次调研() -> None:
    """一个源不可用是运维问题，不该让科学步骤整体失败。"""

    papers = _papers()

    def broken(query: str, limit: int = 8) -> list[AcademicPaper]:
        raise RuntimeError("网络不可用")

    completion = _Scripted(
        {"queries": ["q"]},
        {"selections": [{"index": 0, "relevance": "仍能完成"}]},
    )
    refs = survey_literature_for_plan(
        focus=_PLAN,
        searchers={"arxiv": broken, "openalex": lambda q, limit=8: papers},
        completion=completion,
    )
    assert len(refs) == 1


def test_检索词由系统撰写且看到了自己的计划() -> None:
    """检索什么是科学判断，必须属于系统而不是 agent 硬编码。"""

    papers = _papers()
    completion = _Scripted(
        {"queries": ["constrained symbolic regression"]},
        {"selections": [{"index": 0, "relevance": "r"}]},
    )
    survey_literature_for_plan(
        focus=_PLAN,
        searchers={"openalex": lambda q, limit=8: papers},
        completion=completion,
    )
    first_prompt = json.dumps(completion.calls[0]["messages"], ensure_ascii=False)
    assert "Stratified Symbolic Regression" in first_prompt
    assert "无约束搜索产生未支持字段" in first_prompt


def test_选择阶段提示词明确禁止新增条目() -> None:
    papers = _papers()
    completion = _Scripted(
        {"queries": ["q"]},
        {"selections": [{"index": 0, "relevance": "r"}]},
    )
    survey_literature_for_plan(
        focus=_PLAN,
        searchers={"openalex": lambda q, limit=8: papers},
        completion=completion,
    )
    select_prompt = json.dumps(completion.calls[1]["messages"], ensure_ascii=False)
    assert "REAL papers" in select_prompt
    assert "will be discarded" in select_prompt


def test_调研结果能通过_latex_的可核验检查() -> None:
    """两个模块必须对得上：调研产出的引文要能直接过 guard_references。"""

    from autoresearch.competition.research_plan_latex import guard_references

    papers = _papers()
    completion = _Scripted(
        {"queries": ["q"]},
        {
            "selections": [
                {"index": 0, "relevance": "r1"},
                {"index": 1, "relevance": "r2"},
            ]
        },
    )
    refs = survey_literature_for_plan(
        focus=_PLAN,
        searchers={"openalex": lambda q, limit=8: papers},
        completion=completion,
    )
    assert guard_references(refs) == []
