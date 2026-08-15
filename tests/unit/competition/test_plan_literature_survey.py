"""文献调研的测试：真实性必须是结构性事实，而不是提示词里的承诺。

榜题明令"严禁虚构"。模型写一条假引文和写一条真引文的成本完全相同，所以不能靠请求。
这里验证的核心性质是：**引文只能来自检索器返回的条目**。模型可以挑选、可以解释关联，
但它给出的越界索引会被丢弃，而不是被当成一条新文献。
"""

# 检索器测试替身必须保留真实 callback 签名，即使固定夹具不消费参数。
# ruff: noqa: ARG001, ARG005

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from autoresearch.competition.manifest import canonical_model_hash
from autoresearch.competition.plan_literature_survey import (
    PlanLiteratureSurveyArtifact,
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
            abstract=(
                "Sparse regression identifies parsimonious nonlinear dynamical "
                "systems from measured state trajectories."
            ),
        ),
        AcademicPaper(
            title="Data-driven discovery of partial differential equations",
            authors=["S. H. Rudy"],
            venue="Science Advances",
            publication_date=date(2017, 4, 26),
            url="https://arxiv.org/abs/1609.06401",
            source="arxiv",
            abstract=(
                "Sparse regression and numerical differentiation recover governing "
                "partial differential equations from spatiotemporal observations."
            ),
        ),
        AcademicPaper(
            title="Discovering governing equations from data by sparse identification",
            authors=["K. Champion", "B. Lusch", "J. N. Kutz", "S. L. Brunton"],
            venue="Proceedings of the IEEE",
            publication_date=date(2020, 4, 1),
            doi="10.1109/JPROC.2020.2977444",
            url="https://doi.org/10.1109/JPROC.2020.2977444",
            source="openalex",
            abstract=(
                "A review of sparse system identification, model selection, noise "
                "robustness, and validation across ordinary and partial differential "
                "equations."
            ),
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
        minimum_selected=1,
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
        minimum_selected=1,
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
        minimum_selected=1,
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
    with pytest.raises(PlanLiteratureSurveyError, match="不会用编造或无摘要条目填补"):
        survey_literature_for_plan(
            focus=_PLAN,
            searchers={"arxiv": lambda q, limit=8: papers},
            completion=completion,
            minimum_selected=1,
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
        minimum_selected=1,
    )
    assert len(refs) == 1


def test_检索词由系统撰写且看到了自己的计划() -> None:
    """检索什么是科学判断，必须属于系统而不是 agent 硬编码。"""

    papers = _papers()
    completion = _Scripted(
        {"queries": ["constrained symbolic regression"]},
        {"selections": [{"index": 0, "relevance": "用于界定候选方法"}]},
    )
    survey_literature_for_plan(
        focus=_PLAN,
        searchers={"openalex": lambda q, limit=8: papers},
        completion=completion,
        minimum_selected=1,
    )
    first_prompt = json.dumps(completion.calls[0]["messages"], ensure_ascii=False)
    assert "Stratified Symbolic Regression" in first_prompt
    assert "无约束搜索产生未支持字段" in first_prompt


def test_检索模型实际收到紧凑公开画像与逐系统签名效果() -> None:
    papers = _papers()
    completion = _Scripted(
        {"queries": ["equation discovery profile effect heterogeneity"]},
        {"selections": [{"index": 0, "relevance": "用于解释跨系统差异"}]},
    )
    focus = {
        "domain": {"conditions": ["clean", "snr_20"]},
        "public_data_profile_summaries": [
            {
                "system_name": "system-a",
                "profile_hash": "a" * 64,
                "channels": [
                    {
                        "state_derivative_correlation": -0.9,
                        "clean_derivative_root_mean_square": 0.01,
                    }
                ],
            }
        ],
        "observed_system_effects": [
            {
                "lineage_id": "signed-parent",
                "system_effects": [
                    {"system_name": "system-a", "paired_log_effect": -1.2}
                ],
            }
        ],
        "exploratory_evidence_panels": [
            {
                "fact_id": "E099",
                "fact_kind": "cross_lineage_effect_matrix",
                "value": {
                    "candidate_differences_jointly_confounded": True,
                    "component_attribution_authorized": False,
                    "comparable_system_rows": [
                        {
                            "system_name": "system-a",
                            "observations": [
                                {"lineage_id": "one", "paired_log_effect": -1.2},
                                {"lineage_id": "two", "paired_log_effect": 0.8},
                            ],
                        }
                    ],
                },
            }
        ],
    }

    survey_literature_for_plan(
        focus=focus,
        searchers={"openalex": lambda q, limit=8: papers},
        completion=completion,
        minimum_selected=1,
    )

    first_prompt = json.dumps(completion.calls[0]["messages"], ensure_ascii=False)
    selection_prompt = json.dumps(
        completion.calls[1]["messages"], ensure_ascii=False
    )
    assert "public_data_profile_summaries" in first_prompt
    assert "state_derivative_correlation" in first_prompt
    assert "paired_log_effect" in first_prompt
    assert "exploratory, not causal" in first_prompt
    assert "cross_lineage_effect_matrix" in first_prompt
    assert "candidate-by-system interactions" in first_prompt
    assert "component-confounded" in first_prompt
    assert "public_data_profile_summaries" in selection_prompt
    assert "cross_lineage_effect_matrix" in selection_prompt


def test_选择阶段提示词明确禁止新增条目() -> None:
    papers = _papers()
    completion = _Scripted(
        {"queries": ["q"]},
        {"selections": [{"index": 0, "relevance": "用于核对先前方法"}]},
    )
    survey_literature_for_plan(
        focus=_PLAN,
        searchers={"openalex": lambda q, limit=8: papers},
        completion=completion,
        minimum_selected=1,
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
                {"index": 0, "relevance": "构成稀疏识别基础"},
                {"index": 1, "relevance": "构成偏微分方程发现基础"},
            ]
        },
    )
    refs = survey_literature_for_plan(
        focus=_PLAN,
        searchers={"openalex": lambda q, limit=8: papers},
        completion=completion,
        minimum_selected=2,
    )
    assert guard_references(refs) == []


def test_正式调研保留两次模型调用与真实检索目录(tmp_path: Path) -> None:
    papers = _papers()
    completion = _Scripted(
        {"queries": ["governing equation discovery"]},
        {
            "selections": [
                {"index": 1, "relevance": "用于比较偏微分方程发现机制"},
                {"index": 0, "relevance": "用于界定稀疏动力学识别基线"},
                {"index": 2, "relevance": "用于核查噪声鲁棒性与验证边界"},
            ]
        },
    )
    refs = survey_literature_for_plan(
        focus={
            "domain": {"data_types": ["ode", "pde"]},
            "observed_failures": ["contract failure"],
        },
        searchers={"openalex": lambda q, limit=8: papers},
        completion=completion,
        clock=datetime(2026, 8, 8, tzinfo=timezone.utc),
        lineage_id="lineage-zh",
        output_dir=tmp_path,
    )

    artifact = json.loads(
        (tmp_path / "plan-literature-survey.json").read_text(encoding="utf-8")
    )
    assert refs == artifact["selected_references"]
    assert artifact["surveyed_before_authoring"] is True
    assert len(artifact["retrieved_catalog"]) == 3
    assert artifact["queries"] == ["governing equation discovery"]
    assert (tmp_path / artifact["query_authorship_receipt_relative_path"]).is_file()
    assert (
        tmp_path / artifact["selection_authorship_receipt_relative_path"]
    ).is_file()
    assert refs[0]["relevance_to_plan"] == "用于比较偏微分方程发现机制"


def test_正式调研拒绝英文关联说明() -> None:
    completion = _Scripted(
        {"queries": ["governing equation discovery"]},
        {"selections": [{"index": 0, "relevance": "relevant prior method"}]},
    )
    with pytest.raises(PlanLiteratureSurveyError, match="没有用中文说明关联"):
        survey_literature_for_plan(
            focus={"domain": {"data_types": ["ode"]}},
            searchers={"openalex": lambda q, limit=8: _papers()},
            completion=completion,
            minimum_selected=1,
        )


def test_无摘要条目不能进入正式计划但不妨碍有效选择() -> None:
    papers = [
        *_papers(),
        AcademicPaper(
            title="Physics-informed machine learning",
            authors=["G. E. Karniadakis"],
            venue="Nature Reviews Physics",
            doi="10.1038/s42254-021-00314-5",
            url="https://doi.org/10.1038/s42254-021-00314-5",
            source="openalex",
            abstract=None,
        ),
    ]
    completion = _Scripted(
        {"queries": ["governing equation discovery"]},
        {
            "selections": [
                {"index": 3, "relevance": "这篇没有摘要"},
                {"index": 0, "relevance": "用于界定稀疏识别基线"},
                {"index": 1, "relevance": "用于比较偏微分方程发现"},
                {"index": 2, "relevance": "用于核查验证与噪声边界"},
            ]
        },
    )

    references = survey_literature_for_plan(
        focus=_PLAN,
        searchers={"openalex": lambda q, limit=8: papers},
        completion=completion,
    )

    assert [item["retrieval_index"] for item in references] == [0, 1, 2]
    selection_prompt = str(completion.calls[1]["messages"][1]["content"])
    assert '"abstract_available": false' in selection_prompt
    assert "Select at least 3 distinct eligible papers" in selection_prompt


def test_少于三篇有摘要文献时在计划前失败() -> None:
    papers = _papers()
    papers[2] = papers[2].model_copy(update={"abstract": None})
    completion = _Scripted(
        {"queries": ["governing equation discovery"]},
        {
            "selections": [
                {"index": 0, "relevance": "用于界定稀疏识别基线"},
                {"index": 1, "relevance": "用于比较偏微分方程发现"},
                {"index": 2, "relevance": "试图用无摘要条目填充"},
            ]
        },
    )

    with pytest.raises(PlanLiteratureSurveyError, match="至少 3 篇具有摘要"):
        survey_literature_for_plan(
            focus=_PLAN,
            searchers={"openalex": lambda q, limit=8: papers},
            completion=completion,
        )


@pytest.mark.parametrize("tamper_kind", ["empty_abstract", "crossed_index"])
def test_正式调研制品按检索索引回连摘要并拒绝篡改(
    tmp_path: Path, tamper_kind: str
) -> None:
    completion = _Scripted(
        {"queries": ["governing equation discovery"]},
        {
            "selections": [
                {"index": 0, "relevance": "用于界定稀疏识别基线"},
                {"index": 1, "relevance": "用于比较偏微分方程发现"},
                {"index": 2, "relevance": "用于核查验证与噪声边界"},
            ]
        },
    )
    survey_literature_for_plan(
        focus=_PLAN,
        searchers={"openalex": lambda q, limit=8: _papers()},
        completion=completion,
        lineage_id="tamper-test",
        output_dir=tmp_path,
    )
    payload = json.loads(
        (tmp_path / "plan-literature-survey.json").read_text(encoding="utf-8")
    )
    if tamper_kind == "empty_abstract":
        payload["retrieved_catalog"][0]["abstract"] = ""
        expected_message = "缺少摘要"
    else:
        payload["selected_references"][0]["retrieval_index"] = 1
        expected_message = "与检索目录不符"
    hash_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"survey_hash", "output_path"}
    }
    payload["survey_hash"] = canonical_model_hash(hash_payload)

    with pytest.raises(PlanLiteratureSurveyError, match=expected_message):
        PlanLiteratureSurveyArtifact.model_validate(payload)
