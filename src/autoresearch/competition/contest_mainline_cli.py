"""Contest mainline delivery: question -> plan -> real preexperiment -> revision -> PDF.

一条命令的榜题主线：从《Science》125 问 PDF 提取首题，生成中文研究计划，
执行真实探索性预实验（不可跳过），让配置模型根据已核验预实验结果修订计划一次，
最后渲染最终 JSON/Markdown/TeX/PDF。

被舍弃的链 2 CLI（``contest_prime_feedback_cli``）不再作为主线使用；本模块直接
编排其底层组件（``run_contest_prime_preexperiment`` / ``revise_contest_direct_plan`` /
``build_contest_plan_embedded_evidence`` / ``materialize_contest_direct_plan``），
并把预实验环节设为主线硬步骤：未执行预实验的主线运行直接失败。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from autoresearch.competition.contest_direct_plan_cli import (
    default_question_one_reference_catalog,
    run_contest_question_one_delivery,
)
from autoresearch.competition.contest_direct_plan_render import (
    ContestDirectPlanArtifacts,
    materialize_contest_direct_plan,
)
from autoresearch.competition.contest_direct_plan_revision import (
    ContestDirectPlanNumberGuardError,
    ContestDirectPlanRevisionArtifact,
    revise_contest_direct_plan,
)
from autoresearch.competition.contest_plan_embedded_evidence import (
    ContestPlanEmbeddedEvidenceBundle,
    build_contest_plan_embedded_evidence,
)
from autoresearch.competition.contest_prime_preexperiment import (
    ContestPrimePreexperimentArtifact,
    load_contest_prime_preexperiment,
    run_contest_prime_preexperiment,
)
from autoresearch.competition.contest_question_input import ContestQuestionInput
from autoresearch.competition.manifest import canonical_model_hash

_DEFAULT_PDF = Path(r"C:\Users\Z\Downloads\sjtu-booklet.pdf")
_DEFAULT_OUTPUT = Path("runs/contest-delivery/mainline")
_DEFAULT_SKILLS_ROOT = Path("skills")

_PLAN_REPORT_NAME = "delivery-report.json"
_QUESTION_NAME = "question-input.json"
_SKILL_MANIFEST_NAME = "selected-method-skills.json"
_ORIGINAL_PLAN_NAME = "system-authored-research-plan.json"
_RENDERED_PLAN_NAME = "plan/research-plan.json"
_PREEXPERIMENT_ARTIFACT_NAME = "prime-preexperiment.json"
_REVISED_PLAN_NAME = "system-authored-revised-research-plan.json"
_DELIVERY_REPORT_NAME = "delivery-report.json"
_DELIVERY_SCHEMA = "contest-mainline-delivery-v1"
_SHA256_LENGTH = 64

# 与已舍弃链 2 的修订要求一致；预实验数字守卫由 revise_contest_direct_plan 内置。
# 最后一条是主链实践约束：模型曾引入验证输入中不存在的 2310（wheel-210 周期积）
# 而被数字守卫拒绝，故明确要求正文不得引入新数值。历史 live 复跑（r1-r6）还暴露
# 另外两类高频违规——自推比值（如“约 1/11”）与改写数量级范围（10^10→10^9），
# 因此把具体负例与定性比较正例一并写入要求，供模型照做。
_MAINLINE_REVISION_REQUIREMENTS = (
    "输出符合榜题模板的完整中文《科学假设与研究计划》",
    "读取并如实反馈已核验的真实探索性预实验结果，据此修订主假设与后续研究设计",
    "观察数字必须来自所给指标或日志，不把有限尺度预实验外推为一般定理或开放猜想证明",
    "明确区分预实验与未来正式实验，并报告不支持主假设的结果及替代解释",
    "除所给指标与日志中已经出现的数值外，正文不得引入任何新数字；"
    "如需引用轮筛周期长度等常数，只写其名称（如 wheel-210），不得写出其数值"
    "（例如不得写 2310 或任何轮筛周期积）。不得计算或写出来源数值的比值、倍数、"
    "百分比或差值（例如不得写“约 1/11”“约 31 倍”）；不得新增或改写数量级"
    "范围（例如不得把 10^10 写成 10^9）。需要定量比较时，只逐字引用证据中"
    "已有的数值并配合定性强弱词（如“远小于”“接近”“无显著差异”）表述。",
)

# 数字守卫拒绝后的重试策略：同提示词重试成功率低（历史 6 连败，input_hash 相同、
# 输出高度趋同），因此每次重试把上次守卫拒绝原因追加为一条新要求，并抖动温度。
_REVISION_RETRY_TEMPERATURES = (0.2, 0.4, 0.6)
_REVISION_RETRY_REQUIREMENT = (
    "上一次修订被程序数字守卫拒绝。重写时正文所有数值必须逐字来自本次输入中"
    "已经出现的预实验 artifact、metrics、日志或原计划；禁止任何派生数值（比值、"
    "倍数、百分比、轮筛周期积、改写数量级范围）；需要定量比较时，只引用证据中"
    "已有的数值并配合定性强弱词（如“远小于”“接近”“无显著差异”）表述。"
)


def _revision_temperatures(attempts: int) -> tuple[float, ...]:
    """Return the per-attempt temperature schedule for the requested attempt count."""

    if attempts < 1:
        raise ContestMainlineDeliveryError("revision_attempts must be at least 1")
    base = _REVISION_RETRY_TEMPERATURES
    if attempts <= len(base):
        return base[:attempts]
    cycles = (attempts + len(base) - 1) // len(base)
    return (base * cycles)[:attempts]


class ContestMainlineDeliveryError(RuntimeError):
    """Raised when the mainline cannot truthfully complete one stage."""


PlanRunner = Callable[..., Mapping[str, Any]]
PreexperimentRunner = Callable[..., ContestPrimePreexperimentArtifact]
PreexperimentLoader = Callable[..., ContestPrimePreexperimentArtifact]
RevisionRunner = Callable[..., ContestDirectPlanRevisionArtifact]
EmbeddedEvidenceBuilder = Callable[..., ContestPlanEmbeddedEvidenceBundle | None]
PlanMaterializer = Callable[..., ContestDirectPlanArtifacts]


def run_contest_mainline_delivery(
    *,
    question_pdf: Path | str = _DEFAULT_PDF,
    output_dir: Path | str = _DEFAULT_OUTPUT,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    skills_root: Path | str = _DEFAULT_SKILLS_ROOT,
    plan_max_tokens: int = 12_000,
    revision_max_tokens: int = 14_000,
    revision_attempts: int = len(_REVISION_RETRY_TEMPERATURES),
    timeout_seconds: int = 900,
    render_timeout_seconds: int = 180,
    plan_source_dir: Path | str | None = None,
    preexperiment_source_dir: Path | str | None = None,
    plan_runner: PlanRunner = run_contest_question_one_delivery,
    preexperiment_runner: PreexperimentRunner = run_contest_prime_preexperiment,
    preexperiment_loader: PreexperimentLoader = load_contest_prime_preexperiment,
    revision_runner: RevisionRunner = revise_contest_direct_plan,
    evidence_builder: EmbeddedEvidenceBuilder = build_contest_plan_embedded_evidence,
    plan_materializer: PlanMaterializer = materialize_contest_direct_plan,
) -> dict[str, Any]:
    """Run the complete mainline once into a fresh ``output_dir``.

    Stages: 01-plan (chain 1) -> 02-preexperiment (real, mandatory) ->
    03-revision (one model call over verified pilot numbers; the observed-number
    guard rejection retries up to ``revision_attempts`` with a jittered temperature
    and the previous rejection reason appended as a requirement) ->
    04-final-plan (rendered JSON/MD/TeX/PDF with embedded pilot evidence).

    ``plan_source_dir`` / ``preexperiment_source_dir`` reuse an already completed
    stage from a previous mainline run instead of re-executing it.  Reused stages
    are still fully verified (plan question/skill hashes, pilot file hashes), and
    the new output directory records fresh bindings to the reused evidence.
    """

    root = Path(output_dir).expanduser().resolve()
    _require_new_or_empty_directory(root, create=True)

    # ---- Step 1: question -> Chinese research plan (chain 1) ----
    if plan_source_dir is None:
        plan_root = root / "01-plan"
        plan_report = dict(
            plan_runner(
                question_pdf=question_pdf,
                output_dir=plan_root,
                config_path=config_path,
                env_path=env_path,
                skills_root=skills_root,
                max_tokens=plan_max_tokens,
                timeout_seconds=timeout_seconds,
                overwrite=False,
            )
        )
        if plan_report.get("status") != "completed":
            raise ContestMainlineDeliveryError(
                f"plan stage did not complete: {plan_report.get('status')}"
            )
    else:
        plan_root = Path(plan_source_dir).expanduser().resolve()
        if not plan_root.is_dir():
            raise ContestMainlineDeliveryError(
                f"plan source directory is missing: {plan_root}"
            )
        plan_report = _read_json_mapping(plan_root / _PLAN_REPORT_NAME)
        if plan_report.get("status") != "completed":
            raise ContestMainlineDeliveryError(
                "reused plan source is not a completed delivery"
            )
    question_path = plan_root / _QUESTION_NAME
    question = ContestQuestionInput.model_validate_json(
        question_path.read_text(encoding="utf-8")
    )
    skill_contexts = _load_selected_skill_contexts(plan_root / _SKILL_MANIFEST_NAME)
    original_plan_path = plan_root / _ORIGINAL_PLAN_NAME
    rendered_plan_path = plan_root / _RENDERED_PLAN_NAME
    if not original_plan_path.is_file() or not rendered_plan_path.is_file():
        raise ContestMainlineDeliveryError(
            "plan stage completed without a system-authored plan or its render"
        )

    # ---- Step 2: real exploratory preexperiment (mandatory mainline step) ----
    if preexperiment_source_dir is None:
        pilot_root = root / "02-preexperiment"
        generated = preexperiment_runner(
            output_dir=pilot_root,
            source_plan_path=rendered_plan_path,
        )
        pilot_path = pilot_root / _PREEXPERIMENT_ARTIFACT_NAME
        if not pilot_path.is_file():
            raise ContestMainlineDeliveryError(
                "preexperiment runner returned without persisting an artifact"
            )
        pilot = preexperiment_loader(pilot_path, verify_files=True)
        if pilot.artifact_hash != generated.artifact_hash or pilot.run_id != generated.run_id:
            raise ContestMainlineDeliveryError(
                "persisted preexperiment differs from the runner result"
            )
    else:
        pilot_root = Path(preexperiment_source_dir).expanduser().resolve()
        if not pilot_root.is_dir():
            raise ContestMainlineDeliveryError(
                f"preexperiment source directory is missing: {pilot_root}"
            )
        pilot_path = pilot_root / _PREEXPERIMENT_ARTIFACT_NAME
        if not pilot_path.is_file():
            raise ContestMainlineDeliveryError(
                "preexperiment source lacks its artifact"
            )
        pilot = preexperiment_loader(pilot_path, verify_files=True)
        if pilot.source_plan_sha256 != _sha256_file(rendered_plan_path):
            raise ContestMainlineDeliveryError(
                "reused preexperiment was not executed from this delivery's verified plan"
            )
    if (
        pilot.status != "completed"
        or pilot.study_phase != "exploratory_pilot"
        or pilot.formal_experiment_executed
        or pilot.mathematical_proof_claimed
    ):
        raise ContestMainlineDeliveryError(
            "only a completed exploratory preexperiment may feed the revision"
        )

    # ---- Step 3: one feedback revision over verified pilot numbers ----
    scientific_problem = (
        f"{question.question_zh}\n"
        f"原始英文问题：{question.question_en}\n"
        f"来源：《{question.source_title}》第{question.ordinal}题。"
    )
    reference_catalog = default_question_one_reference_catalog(question)
    revision_root = root / "03-revision"
    revision_path = root / _REVISED_PLAN_NAME
    # 数字守卫拒绝属于模型输出质量问题：把上次拒绝原因追加为一条新要求，
    # 抖动温度后重试；证据绑定类失败（哈希/文件缺失）不会进入重试，直接抛出。
    revision: ContestDirectPlanRevisionArtifact | None = None
    requirements: tuple[str, ...] = _MAINLINE_REVISION_REQUIREMENTS
    for attempt_index, temperature in enumerate(
        _revision_temperatures(revision_attempts), start=1
    ):
        try:
            revision = revision_runner(
                original_plan=original_plan_path,
                scientific_problem=scientific_problem,
                requirements=requirements,
                selected_skill_contexts=skill_contexts,
                reference_catalog=reference_catalog,
                preexperiment_artifact=pilot_path,
                preexperiment_metrics=None,
                preexperiment_root=pilot_root,
                output_dir=revision_root,
                output_path=revision_path,
                config_path=config_path,
                env_path=env_path,
                timeout_seconds=timeout_seconds,
                max_tokens=revision_max_tokens,
                temperature=temperature,
            )
            break
        except ContestDirectPlanNumberGuardError as exc:
            if attempt_index >= revision_attempts:
                raise
            retry_requirement = _REVISION_RETRY_REQUIREMENT
            if "alternative explanation" in str(exc).casefold():
                retry_requirement += (
                    "Results 中必须明确写出至少一种替代解释，并使用“替代解释”或"
                    "“另一种解释”字样开头。"
                )
            requirements = (*requirements, f"{retry_requirement}（上次拒绝原因：{exc}）")
    if revision is None:  # pragma: no cover - exhaustion re-raises the guard error
        raise ContestMainlineDeliveryError("feedback revision produced no artifact")
    if revision.generation_calls != 1:
        raise ContestMainlineDeliveryError(
            "feedback revision must contain exactly one model revision call"
        )

    # ---- Step 4: render the final plan with embedded pilot evidence ----
    render_payload = revision.flat_payload()
    embedded = evidence_builder(
        pilot,
        artifact_path=pilot_path,
        preexperiment_root=pilot_root,
    )
    if embedded is not None:
        render_payload["embedded_evidence"] = embedded.payload
    render_payload.update(
        {
            "document_type": revision.document_type,
            "status": revision.status,
            "question": question.model_dump(mode="json"),
            "generation": {
                "provider": revision.provider,
                "model_name": revision.model_name,
                "generation_calls": revision.generation_calls,
                "input_hash": revision.input_hash,
                "model_response_hash": revision.model_response_hash,
                "artifact_hash": revision.artifact_hash,
            },
            "preexperiment": {
                "execution_status": pilot.status,
                "study_phase": pilot.study_phase,
                "run_id": pilot.run_id,
                "artifact_hash": pilot.artifact_hash,
                "artifact_file_sha256": _sha256_file(pilot_path),
                "metrics_sha256": pilot.metrics_sha256,
                "manifest_sha256": pilot.manifest_sha256,
                "formal_experiment_executed": False,
                "mathematical_proof_claimed": False,
            },
        }
    )
    final_root = root / "04-final-plan"
    rendered = plan_materializer(
        payload=render_payload,
        output_dir=final_root,
        evidence_bindings=embedded.manifest_bindings if embedded is not None else (),
        overwrite=False,
        timeout_seconds=render_timeout_seconds,
    )

    # ---- Step 5: hash-bound delivery report ----
    report: dict[str, Any] = {
        "schema_version": _DELIVERY_SCHEMA,
        "status": "completed",
        "question_id": question.question_id,
        "question_zh": question.question_zh,
        "question_en": question.question_en,
        "plan_stage": {
            "report": _file_binding(plan_root / _PLAN_REPORT_NAME),
            "selected_skill_ids": list(
                plan_report.get("selected_method_skill_ids", ())
            ),
            "system_authored_plan": _file_binding(original_plan_path),
            "rendered_plan": _file_binding(rendered_plan_path),
        },
        "preexperiment": {
            "run_id": pilot.run_id,
            "status": pilot.status,
            "study_phase": pilot.study_phase,
            "artifact": _file_binding(pilot_path),
            "metrics": _file_binding(
                _inside(pilot_root, Path(*Path(pilot.metrics_relative_path).parts)),
                expected_sha256=pilot.metrics_sha256,
            ),
            "formal_experiment_executed": False,
            "mathematical_proof_claimed": False,
        },
        "revision": {
            "artifact": _file_binding(revision_path),
            "provider": revision.provider,
            "model_name": revision.model_name,
            "generation_calls": revision.generation_calls,
            "artifact_hash": revision.artifact_hash,
            "revision_id": revision.revision_id,
        },
        "rendered": _rendered_bindings(rendered, final_root),
        "reference_catalog_count": len(reference_catalog),
        "reference_catalog_sha256": canonical_model_hash(
            {"references": list(reference_catalog)}
        ),
        "formal_experiment_executed": False,
        "paper_claimed": False,
    }
    report_path = root / _DELIVERY_REPORT_NAME
    _write_new_json(report_path, report)
    returned = dict(report)
    returned["delivery_report_path"] = report_path.as_posix()
    returned["delivery_report_sha256"] = _sha256_file(report_path)
    return returned


def _load_selected_skill_contexts(manifest_path: Path) -> list[dict[str, str]]:
    payload = _read_json_mapping(manifest_path)
    if payload.get("schema_version") != "contest-direct-selected-skills-v1":
        raise ContestMainlineDeliveryError("unsupported selected Skill manifest schema")
    records = payload.get("skills")
    if not isinstance(records, list):
        raise ContestMainlineDeliveryError("selected Skill manifest lacks a skills list")
    contexts: list[dict[str, str]] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            raise ContestMainlineDeliveryError("selected Skill record is not an object")
        skill_id = str(record.get("skill_id") or "").strip()
        expected = str(record.get("content_sha256") or "").strip().lower()
        recorded_path = str(record.get("path") or "").strip()
        if not skill_id or skill_id in seen or not recorded_path:
            raise ContestMainlineDeliveryError(
                "selected Skill IDs must be nonblank and unique"
            )
        if len(expected) != _SHA256_LENGTH or not all(
            character in "0123456789abcdef" for character in expected
        ):
            raise ContestMainlineDeliveryError(
                f"selected Skill record has an invalid hash: {skill_id}"
            )
        skill_path = Path(recorded_path).expanduser().resolve()
        try:
            content = skill_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ContestMainlineDeliveryError(
                f"cannot read selected Skill content: {skill_path}: {exc}"
            ) from exc
        actual = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if actual != expected:
            raise ContestMainlineDeliveryError(
                f"selected Skill content hash mismatch: {skill_id}"
            )
        seen.add(skill_id)
        contexts.append(
            {
                "skill_id": skill_id,
                "name": skill_id,
                "content": content,
                "content_sha256": actual,
            }
        )
    return contexts


def _rendered_bindings(
    rendered: ContestDirectPlanArtifacts,
    root: Path,
) -> dict[str, Any]:
    bindings = {
        "json": _file_binding(_inside(root, rendered.json_path)),
        "markdown": _file_binding(_inside(root, rendered.markdown_path)),
        "tex": _file_binding(_inside(root, rendered.tex_path)),
        "pdf": _file_binding(_inside(root, rendered.pdf_path)),
        "manifest": _file_binding(_inside(root, rendered.manifest_path)),
    }
    if rendered.source_path is not None:
        bindings["internal_source"] = _file_binding(_inside(root, rendered.source_path))
    return {**rendered.to_dict(), "artifacts": bindings}


def _require_new_or_empty_directory(path: Path, *, create: bool) -> None:
    if path.exists():
        if not path.is_dir():
            raise ContestMainlineDeliveryError(
                f"output path is not a directory: {path}"
            )
        if any(path.iterdir()):
            raise ContestMainlineDeliveryError(
                f"output directory must be new or empty: {path}"
            )
    elif create:
        path.mkdir(parents=True, exist_ok=False)


def _inside(root: Path, value: Path) -> Path:
    resolved_root = root.resolve()
    candidate = value.resolve() if value.is_absolute() else (resolved_root / value).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ContestMainlineDeliveryError(
            f"generated artifact escapes its output root: {candidate}"
        ) from exc
    return candidate


def _read_json_mapping(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContestMainlineDeliveryError(
            f"cannot read JSON artifact {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ContestMainlineDeliveryError(f"JSON artifact is not an object: {path}")
    return payload


def _file_binding(
    path: Path,
    *,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ContestMainlineDeliveryError(f"bound file does not exist: {resolved}")
    actual_hash = _sha256_file(resolved)
    if expected_sha256 is not None and actual_hash != expected_sha256:
        raise ContestMainlineDeliveryError(f"bound file hash mismatch: {resolved}")
    return {
        "path": resolved.as_posix(),
        "sha256": actual_hash,
        "size_bytes": resolved.stat().st_size,
    }


def _write_new_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except FileExistsError as exc:
        raise ContestMainlineDeliveryError(
            f"refusing to overwrite delivery artifact: {path}"
        ) from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "榜题主线：题目 → 中文研究计划 → 真实预实验 → 反馈修订 → 最终 PDF。"
        )
    )
    parser.add_argument("--question-pdf", type=Path, default=_DEFAULT_PDF)
    parser.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--skills-root", type=Path, default=_DEFAULT_SKILLS_ROOT)
    parser.add_argument("--plan-max-tokens", type=int, default=12_000)
    parser.add_argument("--revision-max-tokens", type=int, default=14_000)
    parser.add_argument(
        "--revision-attempts",
        type=int,
        default=len(_REVISION_RETRY_TEMPERATURES),
        help=(
            "修订阶段最多尝试次数。数字守卫拒绝后追加拒绝原因并抖动温度重试，"
            "超过次数后失败关闭。"
        ),
    )
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--render-timeout-seconds", type=int, default=180)
    parser.add_argument(
        "--plan-source-dir",
        type=Path,
        default=None,
        help="复用已完成主线的 01-plan 目录（仍全量验证），跳过链 1。",
    )
    parser.add_argument(
        "--preexperiment-source-dir",
        type=Path,
        default=None,
        help="复用已完成主线的 02-preexperiment 目录（仍全量验证），跳过真实预实验。",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_contest_mainline_delivery(
        question_pdf=args.question_pdf,
        output_dir=args.output_dir,
        config_path=args.config,
        env_path=args.env,
        skills_root=args.skills_root,
        plan_max_tokens=args.plan_max_tokens,
        revision_max_tokens=args.revision_max_tokens,
        revision_attempts=args.revision_attempts,
        timeout_seconds=args.timeout_seconds,
        render_timeout_seconds=args.render_timeout_seconds,
        plan_source_dir=args.plan_source_dir,
        preexperiment_source_dir=args.preexperiment_source_dir,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through module smoke
    sys.exit(main())


__all__ = [
    "ContestMainlineDeliveryError",
    "main",
    "run_contest_mainline_delivery",
]
