from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from autoresearch.competition.contest_direct_plan_render import (
    ContestDirectPlanRenderError,
    materialize_contest_direct_plan,
    materialize_versioned_contest_plan_presentation,
    render_contest_plan_markdown,
    render_contest_plan_tex,
    validate_contest_plan_payload,
)


def _payload() -> dict[str, object]:
    return {
        "title": "面向暗物质本质问题的多信使证据一致性研究",
        "abstract": "本研究提出一套可检验的多信使分析框架，并以预实验结果约束后续研究。",
        "problem_statement": "暗物质由什么构成，以及不同观测通道能否给出一致约束？",
        "rationale": "若同一候选机制成立，其引力透镜、星系动力学与粒子探测信号应满足共同参数约束。",
        "technical_details": "使用贝叶斯层次模型、公开巡天数据和可复现的后验预测检查。",
        "datasets": {
            "source": "公开的星系旋转曲线、弱引力透镜和直接探测上限数据",
            "target": "预先冻结的留出天区与跨观测通道参数一致性",
        },
        "methods": "先统一误差模型，再联合估计共享参数，并通过留出数据检验可迁移性。",
        "experiments": [
            "复现各观测通道的公开基线结果。",
            "运行联合模型并保存原始日志、后验样本与诊断量。",
            "执行去除单一观测通道的消融实验。",
        ],
        "baselines": ["各观测通道独立拟合", "标准冷暗物质基准模型"],
        "metrics": ["留出集对数似然", "后验预测覆盖率", "跨通道参数张力"],
        "results": "预实验已完成最小数据管线，三个公开样例均可读取，联合模型的诊断日志已保存。",
        "references": [
            {
                "title": "The AI Scientist: Towards Fully Automated Open-Ended Scientific Discovery",
                "authors": ["Lu et al."],
                "year": "2024",
                "url": "https://github.com/SakanaAI/AI-Scientist",
            },
            "《Science》125 个前沿科学问题，https://www.science.org/cms/asset/example.pdf",
        ],
    }


def _embedded_evidence() -> dict[str, object]:
    return {
        "schema_version": "contest-plan-embedded-evidence-v1",
        "section_title_zh": "真实预实验数据、图表与分析",
        "execution_label_zh": "探索性预实验",
        "summary_zh": "本节直接汇总已真实执行的探索性预实验结果。",
        "tables": [
            {
                "table_id": "aggregate-comparison",
                "title_zh": "预实验总体对照结果",
                "columns": [
                    {"key": "null_model", "label_zh": "零模型"},
                    {
                        "key": "delta_observed_minus_null",
                        "label_zh": "差值（真实值－零模型）",
                    },
                    {
                        "key": "fixed_interval_resampling_delta_ci95",
                        "label_zh": "固定区间重采样范围",
                    },
                ],
                "rows": [
                    {
                        "null_model": "global_permutation",
                        "delta_observed_minus_null": -0.04,
                        "fixed_interval_resampling_delta_ci95": [-0.05, -0.03],
                    },
                    {
                        "null_model": "residue_path_conditioned_permutation",
                        "delta_observed_minus_null": -0.002,
                        "fixed_interval_resampling_delta_ci95": [-0.003, -0.001],
                    },
                ],
                "caption_zh": "负值表示真实序列指标低于零模型。",
                "analysis_zh": "强条件对照下差值明显缩小，结论应相应收窄。",
            }
        ],
        "figures": [
            {
                "figure_id": "observed-minus-null-interval-plot",
                "kind": "horizontal_interval_plot",
                "title_zh": "真实观测与零模型差值",
                "x_label_zh": "真实观测值－零模型均值",
                "series": [
                    {
                        "label": "global_permutation",
                        "value": -0.04,
                        "lower": -0.05,
                        "upper": -0.03,
                    },
                    {
                        "label": "residue_path_conditioned_permutation",
                        "value": -0.002,
                        "lower": -0.003,
                        "upper": -0.001,
                    },
                    {
                        "label": "local_block_permutation",
                        "value": -0.02,
                        "lower": -0.03,
                        "upper": -0.01,
                    },
                ],
                "caption_zh": "横线为固定分析单元重采样的描述性范围。",
                "analysis_zh": "图中范围不是总体置信区间。",
            }
        ],
        "analysis_zh": "大部分差异可由更强条件对照解释。",
        "scope_note_zh": "仅限本次探索性预实验，不作总体外推。",
    }


def test_minimal_validation_has_no_ids_hashes_lengths_or_opportunity_gate() -> None:
    payload = _payload()

    validate_contest_plan_payload(payload)

    assert "id" not in payload
    assert "hash" not in payload
    assert "opportunity" not in payload


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda payload: payload.pop("results"), "results"),
        (lambda payload: payload["datasets"].pop("target"), "datasets.target"),
        (lambda payload: payload.pop("metrics"), "metrics"),
    ],
)
def test_validation_reports_only_missing_template_fields(mutation: object, expected: str) -> None:
    payload = _payload()
    mutation(payload)  # type: ignore[operator]

    with pytest.raises(ContestDirectPlanRenderError, match=expected):
        validate_contest_plan_payload(payload)


def test_markdown_and_tex_contain_all_required_chinese_sections() -> None:
    payload = _payload()
    payload["technical_details"] = (
        "保留 5% 留出集，并记录 run_id 与 A&B 条件；要求 p≤0.02、τ=1、ΔH≥0，" "区间上界为 2×10^6。"
    )
    payload["datasets"] = {
        "source": "consecutive_integer_primes",
        "target": "ordered_consecutive_prime_gaps",
    }
    payload["baselines"] = (
        "global_permutation；local_block_permutation；"
        "residue_path_conditioned_permutation；wheel_210"
    )
    payload["metrics"] = "tie_aware_normalized_permutation_entropy_m5"

    markdown = render_contest_plan_markdown(payload)
    tex = render_contest_plan_tex(payload)

    for heading in (
        "待研究问题",
        "解决思路",
        "必要的技术手段",
        "数据集",
        "方法论",
        "实验设计",
        "基线对比",
        "评估指标",
        "实验结果",
        "参考论文",
    ):
        assert heading in markdown
        assert heading in tex
    assert "5\\%" in tex
    assert "A\\&B" in tex
    assert r"p\ensuremath{\leq}0.02" in tex
    assert r"\ensuremath{\tau}=1" in tex
    assert r"\ensuremath{\Delta}H\ensuremath{\geq}0" in tex
    assert r"2\ensuremath{\times}10\textasciicircum{}6" in tex
    assert "\\url{https://github.com/SakanaAI/AI-Scientist}" in tex
    for forbidden in (
        "run_id",
        "consecutive_integer_primes",
        "ordered_consecutive_prime_gaps",
        "global_permutation",
        "local_block_permutation",
        "residue_path_conditioned_permutation",
        "tie_aware_normalized_permutation_entropy_m5",
    ):
        assert forbidden not in markdown
        assert forbidden not in tex
    assert "运行批次" in markdown
    assert "连续整数区间内按升序生成的素数序列" in markdown
    assert "含并列修正的五阶归一化排列熵" in markdown


def test_structured_catalog_reference_is_projected_to_clean_bibliography() -> None:
    payload = _payload()
    payload["references"] = [
        "\n".join(
            (
                "[71] record_id=direction-paper-deadbeef",
                "题名：Empirical verification of prime gaps up to 4⋅10¹⁸",
                "作者：Tomás Oliveira e Silva、Siegfried Herzog、Silvio Pardi",
                "日期：2013-11-18",
                "期刊或会议：Mathematics of Computation",
                "正式发表DOI：10.1090/s0025-5718-2013-02787-1",
                "仓储DOI：未提供",
                "URL：https://doi.org/10.1090/s0025-5718-2013-02787-1",
                "论文来源字段：openalex",
                "被引次数：170（来源：openalex；截至：2026-08-13）",
                "完整摘要：Abstract with <mml:math>transport markup</mml:math>.",
                "真实检索谱系：openalex|query|2026-08-13T00:00:00+00:00",
                "record_sha256=" + "a" * 64,
            )
        )
    ]

    markdown = render_contest_plan_markdown(payload)
    tex = render_contest_plan_tex(payload)

    for expected in (
        "作者：Tomás Oliveira e Silva、Siegfried Herzog、Silvio Pardi",
        "题名：Empirical verification of prime gaps up to 4×10^18",
        "年份：2013",
        "期刊/会议：Mathematics of Computation",
        "正式 DOI：10.1090/s0025-5718-2013-02787-1",
        "URL：https://doi.org/10.1090/s0025-5718-2013-02787-1",
    ):
        assert expected in markdown
    for forbidden in (
        "record_id",
        "被引次数",
        "完整摘要",
        "mml:math",
        "真实检索谱系",
        "record_sha256",
    ):
        assert forbidden not in markdown
        assert forbidden not in tex
    assert "4⋅10¹⁸" not in markdown
    assert "4⋅10¹⁸" not in tex
    assert r"4\ensuremath{\times}10\textasciicircum{}18" in tex


def test_reference_display_normalizes_unicode_super_and_subscript_runs() -> None:
    payload = _payload()
    payload["references"] = [
        {
            "title": "Bounds at 4∙10⁻³ and coefficients a₁₂",
            "authors": ["A. Author"],
            "year": "2025",
            "url": "https://example.org/math",
        }
    ]

    markdown = render_contest_plan_markdown(payload)
    tex = render_contest_plan_tex(payload)

    assert "Bounds at 4×10^-3 and coefficients a_12" in markdown
    assert not any(character in markdown for character in "∙⁻³₁₂")
    assert r"4\ensuremath{\times}10\textasciicircum{}-3 and coefficients a\_12" in tex


def test_q1_source_reference_keeps_public_url_without_local_path_or_hash() -> None:
    payload = _payload()
    payload["references"] = [
        (
            "Science/AAAS. 125 Questions: Exploration and Discovery (2021), "
            "question 1: What makes prime numbers so special? Local source SHA-256: "
            + "a"
            * 64
            + "; source: C:/Users/Z/Downloads/sjtu-booklet.pdf; "
            "https://www.science.org/cms/asset/booklet/sjtu-booklet.pdf"
        )
    ]

    markdown = render_contest_plan_markdown(payload)
    tex = render_contest_plan_tex(payload)

    for rendered in (markdown, tex):
        assert "Local source" not in rendered
        assert "C:/Users" not in rendered
        assert "a" * 64 not in rendered
    assert "What makes prime numbers so special?" in markdown
    assert "https://www.science.org/cms/asset/booklet/sjtu-booklet.pdf" in markdown


def test_unstructured_reference_with_two_public_urls_is_not_redacted_as_windows_path() -> None:
    payload = _payload()
    payload["references"] = [
        (
            "A. Author. A generic study. Journal (2025). "
            "https://doi.org/10.1000/example; preprint: "
            "https://example.org/preprints/1234"
        )
    ]

    markdown = render_contest_plan_markdown(payload)
    tex = render_contest_plan_tex(payload)

    for rendered in (markdown, tex):
        assert "本计划内嵌证据" not in rendered
        assert "http本计划内嵌证据" not in rendered
        assert "preprint" in rendered
    assert "https://doi.org/10.1000/example" in markdown
    assert "URL：https://example.org/preprints/1234" in markdown


def test_repository_doi_is_used_only_when_formal_doi_is_absent() -> None:
    payload = _payload()
    payload["references"] = [
        {
            "title": "A repository paper",
            "authors": ["A. Author"],
            "publication_date": "2024-05-01",
            "venue": "arXiv",
            "doi": "未提供",
            "repository_doi": "https://doi.org/10.48550/arXiv.2405.00001",
            "source_url": "https://arxiv.org/abs/2405.00001",
            "paper_source": "arxiv",
            "abstract": "This evidence remains in JSON but not the bibliography.",
            "record_sha256": "b" * 64,
        }
    ]

    markdown = render_contest_plan_markdown(payload)

    assert "仓储 DOI：10.48550/arXiv.2405.00001" in markdown
    assert "URL：https://arxiv.org/abs/2405.00001" in markdown
    assert "abstract" not in markdown
    assert "record_sha256" not in markdown


def test_embedded_evidence_renders_inline_tables_plot_and_analysis() -> None:
    payload = _payload()
    payload["embedded_evidence"] = _embedded_evidence()

    markdown = render_contest_plan_markdown(payload)
    tex = render_contest_plan_tex(payload)

    assert "### 表 1" in markdown
    assert "-0.04" in markdown
    assert "[-0.05, -0.03]" in markdown
    assert "<svg" in markdown and "</svg>" in markdown
    assert "表格分析" in markdown and "图形分析" in markdown
    assert "全局置换零模型" in markdown
    assert "global_permutation" not in markdown
    assert r"\begin{table}[H]" in tex
    assert r"\begin{tikzpicture}" in tex
    assert "axis cs:-0.05,1" in tex
    assert "axis y line*=left" in tex
    assert "axis y line=none" not in tex
    assert "anchor=west,xshift=2pt" in tex
    assert "anchor=east,xshift=-2pt" in tex
    assert "解释边界" in tex


def test_conflicting_existing_artifact_is_protected_by_default(tmp_path: Path) -> None:
    output = tmp_path / "plan"
    output.mkdir()
    (output / "research-plan.json").write_text("old", encoding="utf-8")

    with pytest.raises(ContestDirectPlanRenderError, match="overwrite=True"):
        materialize_contest_direct_plan(payload=_payload(), output_dir=output)

    assert (output / "research-plan.json").read_text(encoding="utf-8") == "old"
    assert not (output / "research-plan.pdf").exists()


def test_compile_failure_never_creates_a_placeholder_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_compile(
        tex_path: Path,
        *,
        timeout_seconds: int,
    ) -> tuple[str, None, str, None]:
        del tex_path, timeout_seconds
        return "failed_missing_latex", None, "latexmk or xelatex was not found on PATH", None

    monkeypatch.setattr(
        "autoresearch.competition.contest_direct_plan_render.compile_research_plan_pdf",
        fail_compile,
    )

    output = tmp_path / "plan"
    with pytest.raises(ContestDirectPlanRenderError, match="latexmk or xelatex"):
        materialize_contest_direct_plan(payload=_payload(), output_dir=output)

    assert not (output / "research-plan.pdf").exists()
    assert not (output / "research-plan-manifest.json").exists()


@pytest.mark.skipif(
    (shutil.which("latexmk") is None and shutil.which("xelatex") is None)
    or shutil.which("pdftotext") is None,
    reason="A TeX compiler and pdftotext are required for the physical PDF smoke test",
)
def test_materialize_real_chinese_pdf_and_manifest(tmp_path: Path) -> None:
    output = tmp_path / "plan"
    payload = _payload()
    payload["embedded_evidence"] = _embedded_evidence()
    payload["generation"] = {
        "run_id": "run-secret",
        "adapter_id": "adapter-secret",
        "artifact_hash": "a" * 64,
    }
    payload["postpilot_objective"] = {
        "artifact_path": "E:/private/postpilot-objective.json",
        "artifact_hash": "b" * 64,
    }
    evidence_file = tmp_path / "private" / "metrics.json"
    evidence_file.parent.mkdir()
    evidence_file.write_text('{"metric": 0.91}\n', encoding="utf-8")
    evidence_binding = {
        "role": "preexperiment_metrics",
        "path": evidence_file.as_posix(),
        "sha256": hashlib.sha256(evidence_file.read_bytes()).hexdigest(),
        "size_bytes": evidence_file.stat().st_size,
    }
    artifact = materialize_contest_direct_plan(
        payload=payload,
        output_dir=output,
        evidence_bindings=(evidence_binding,),
    )

    assert artifact.pdf_path.is_file() and artifact.pdf_path.stat().st_size > 0
    assert artifact.pdf_text_verified is True
    for path in (
        artifact.json_path,
        artifact.markdown_path,
        artifact.tex_path,
        artifact.pdf_path,
        artifact.manifest_path,
        artifact.source_path,
    ):
        assert path is not None and path.is_file()

    manifest = json.loads(artifact.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "contest-direct-plan-render-v3"
    assert manifest["reference_projection_version"] == "bibliographic-display-v2"
    assert len(manifest["display_references_sha256"]) == 64
    assert manifest["compile_status"] == "compiled"
    assert manifest["pdf_text_verified"] is True
    assert manifest["embedded_evidence"]["table_count"] == 1
    assert manifest["embedded_evidence"]["figure_count"] == 1
    assert manifest["embedded_evidence"]["provenance_bindings"][0]["path"] == (
        evidence_file.resolve().as_posix()
    )
    for record in manifest["artifacts"].values():
        path = output / record["filename"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]

    extracted = subprocess.run(
        (shutil.which("pdftotext"), "-layout", str(artifact.pdf_path), "-"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout
    compact = "".join(extracted.split())
    assert "暗物质" in compact
    assert "实验结果" in compact
    assert "参考论文" in compact
    assert "预实验总体对照结果" in compact
    assert "真实观测与零模型差值" in compact
    # This label occurs only in the figure fixture, not the evidence table, so
    # extraction proves the y-axis labels survive real PDF compilation.
    assert "局部分块置换零模型" in compact

    public_json = json.loads(artifact.json_path.read_text(encoding="utf-8"))
    public_text = json.dumps(public_json, ensure_ascii=False, sort_keys=True)
    markdown_text = artifact.markdown_path.read_text(encoding="utf-8")
    tex_text = artifact.tex_path.read_text(encoding="utf-8")
    for forbidden in (
        "artifact_path",
        "artifact_hash",
        "run_id",
        "adapter_id",
        "record_id",
        "revision_id",
        "E:/private",
        "a" * 64,
        "b" * 64,
    ):
        assert forbidden not in public_text
        assert forbidden not in markdown_text
        assert forbidden not in tex_text
    assert "fixed_interval_resampling_delta_ci95" not in public_text
    assert "固定区间重采样范围" in public_text
    for external_artifact_suffix in (".json", ".csv", ".log"):
        assert external_artifact_suffix not in public_text.casefold()
        assert external_artifact_suffix not in markdown_text.casefold()
        assert external_artifact_suffix not in tex_text.casefold()
    assert artifact.source_path is not None
    source_text = artifact.source_path.read_text(encoding="utf-8")
    assert "run-secret" in source_text
    assert "E:/private/postpilot-objective.json" in source_text

    second = materialize_contest_direct_plan(
        payload=payload,
        output_dir=output,
        evidence_bindings=(evidence_binding,),
    )
    assert second.to_dict() == artifact.to_dict()


def test_versioned_presentation_preserves_completed_standard_and_binds_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_compile(
        tex_path: Path,
        *,
        timeout_seconds: int,
    ) -> tuple[str, Path, None, int]:
        del timeout_seconds
        pdf_path = tex_path.with_suffix(".pdf")
        pdf_path.write_bytes(b"%PDF-1.4\n% deterministic test fixture\n")
        return "compiled", pdf_path, None, 1

    monkeypatch.setattr(
        "autoresearch.competition.contest_direct_plan_render.compile_research_plan_pdf",
        fake_compile,
    )
    monkeypatch.setattr(
        "autoresearch.competition.contest_direct_plan_render._extract_pdf_text",
        lambda *_args, **_kwargs: (
            "面向暗物质本质问题的多信使证据一致性研究 " "待研究问题 实验结果 参考论文"
        ),
    )

    standard = tmp_path / "plan"
    source = materialize_contest_direct_plan(payload=_payload(), output_dir=standard)
    assert source.source_path is not None
    standard_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (
            source.json_path,
            source.markdown_path,
            source.tex_path,
            source.pdf_path,
            source.manifest_path,
            source.source_path,
        )
    }
    receipt = tmp_path / "08-render-plan.json"
    receipt.write_text('{"status":"completed"}\n', encoding="utf-8")

    presentation = materialize_versioned_contest_plan_presentation(
        source_dir=standard,
        output_dir=tmp_path / "plan-polished-v2",
        completion_bindings={"render_stage_receipt": receipt},
    )

    assert standard_hashes == {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in standard.rglob("*")
        if path.is_file()
    }
    assert presentation.rendered.json_path.read_bytes() == source.json_path.read_bytes()
    assert presentation.rendered.source_path is not None
    assert presentation.rendered.source_path.read_bytes() == source.source_path.read_bytes()
    audit = json.loads(presentation.audit_path.read_text(encoding="utf-8"))
    assert audit["scientific_content_changed"] is False
    assert audit["source_json_byte_identical"] is True
    assert audit["model_calls"] == 0
    assert audit["source_completion_bindings"]["render_stage_receipt"]["sha256"] == (
        hashlib.sha256(receipt.read_bytes()).hexdigest()
    )
    assert (
        audit["source_standard_artifacts"]["research-plan.pdf"]["sha256"]
        == (standard_hashes["research-plan.pdf"])
    )


def test_versioned_presentation_refuses_to_replace_standard_dir(tmp_path: Path) -> None:
    with pytest.raises(ContestDirectPlanRenderError, match="不得与已完成标准计划目录相同"):
        materialize_versioned_contest_plan_presentation(
            source_dir=tmp_path / "plan",
            output_dir=tmp_path / "plan",
        )
