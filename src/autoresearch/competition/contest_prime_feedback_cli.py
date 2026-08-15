"""Delivery-first bridge from a real prime pilot to one revised research plan.

This module deliberately does not reopen topic selection, brainstorming, formal
experimentation, or paper writing.  It consumes the already-authored first-question
delivery, executes (or verifies and reuses) one exploratory prime preexperiment,
asks the configured model for exactly one evidence-based revision, and materializes
the synchronized JSON/Markdown/TeX/PDF views.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from autoresearch.competition.contest_direct_plan import (
    ContestDirectPlanArtifact,
    load_contest_direct_plan,
)
from autoresearch.competition.contest_direct_plan_cli import (
    default_question_one_reference_catalog,
)
from autoresearch.competition.contest_direct_plan_render import (
    ContestDirectPlanArtifacts,
    materialize_contest_direct_plan,
)
from autoresearch.competition.contest_direct_plan_revision import (
    ContestDirectPlanRevisionArtifact,
    revise_contest_direct_plan,
)
from autoresearch.competition.contest_plan_embedded_evidence import (
    build_contest_plan_embedded_evidence,
)
from autoresearch.competition.contest_prime_preexperiment import (
    ContestPrimePreexperimentArtifact,
    load_contest_prime_preexperiment,
    run_contest_prime_preexperiment,
)
from autoresearch.competition.contest_question_input import ContestQuestionInput
from autoresearch.competition.manifest import canonical_model_hash

_DEFAULT_SOURCE_DELIVERY = Path(
    "runs/contest-delivery/science125-question-001-objective-review-final-v2"
)
_DEFAULT_OUTPUT = Path("runs/contest-delivery/science125-question-001-preexperiment-feedback-v1")
_QUESTION_NAME = "question-input.json"
_SKILL_MANIFEST_NAME = "selected-method-skills.json"
_ORIGINAL_PLAN_NAME = "system-authored-research-plan.json"
_PREEXPERIMENT_ARTIFACT_NAME = "prime-preexperiment.json"
_REVISION_ARTIFACT_NAME = "system-authored-revised-research-plan.json"
_SHA256_LENGTH = 64
_REVISION_REQUIREMENTS = (
    "输出符合榜题模板的完整中文《科学假设与研究计划》",
    "读取并如实反馈已核验的真实探索性预实验结果，据此修订主假设与后续研究设计",
    "观察数字必须来自所给指标或日志，不把有限尺度预实验外推为一般定理或开放猜想证明",
    "明确区分预实验与未来正式实验，并报告不支持主假设的结果及替代解释",
)


class ContestPrimeFeedbackDeliveryError(RuntimeError):
    """Raised when an input/evidence binding or the one-pass delivery fails."""


def run_contest_prime_feedback_delivery(
    *,
    source_delivery_dir: Path | str = _DEFAULT_SOURCE_DELIVERY,
    output_dir: Path | str = _DEFAULT_OUTPUT,
    preexperiment_artifact: Path | str | None = None,
    config_path: Path | str = Path("config.yaml"),
    env_path: Path | str = Path(".env"),
    max_tokens: int | None = 14_000,
    timeout_seconds: int | None = 900,
    render_timeout_seconds: int = 180,
    preexperiment_runner: Callable[..., ContestPrimePreexperimentArtifact] = (
        run_contest_prime_preexperiment
    ),
    preexperiment_loader: Callable[..., ContestPrimePreexperimentArtifact] = (
        load_contest_prime_preexperiment
    ),
    revision_runner: Callable[..., ContestDirectPlanRevisionArtifact] = (
        revise_contest_direct_plan
    ),
    plan_materializer: Callable[..., ContestDirectPlanArtifacts] = (
        materialize_contest_direct_plan
    ),
) -> dict[str, Any]:
    """Close the real-pilot -> one model feedback -> revised-plan loop.

    ``output_dir`` must be absent or empty.  Supplying ``preexperiment_artifact``
    reuses a previous execution only after ``load_contest_prime_preexperiment`` has
    re-hashed its manifest and every evidence file.  Omitting it runs the real pilot
    under ``output_dir/preexperiment``.
    """

    source_root = Path(source_delivery_dir).expanduser().resolve()
    if not source_root.is_dir():
        raise ContestPrimeFeedbackDeliveryError(
            f"source delivery directory does not exist: {source_root}"
        )
    output_root = Path(output_dir).expanduser().resolve()
    _require_new_or_empty_directory(output_root, create=False)

    question_path = source_root / _QUESTION_NAME
    skill_manifest_path = source_root / _SKILL_MANIFEST_NAME
    original_plan_path = source_root / _ORIGINAL_PLAN_NAME
    question = _load_question(question_path)
    original_plan = _load_original_plan(original_plan_path)
    if question.question_zh not in original_plan.scientific_problem:
        raise ContestPrimeFeedbackDeliveryError(
            "original system-authored plan is not bound to the selected first question"
        )
    question_source_binding = _verify_question_source(question)
    selected_skill_contexts, selected_skill_bindings, routing_binding = (
        _load_and_verify_selected_skills(skill_manifest_path)
    )
    preexperiment_source_plan_path = _preexperiment_source_plan(
        source_root=source_root,
        original_plan=original_plan,
        question=question,
        fallback=original_plan_path,
    )
    original_plan_binding = _file_binding(original_plan_path)
    preexperiment_source_plan_binding = _file_binding(preexperiment_source_plan_path)

    executed_in_this_delivery = preexperiment_artifact is None
    if preexperiment_artifact is None:
        _require_new_or_empty_directory(output_root, create=True)
        pilot_root = output_root / "preexperiment"
        generated = preexperiment_runner(
            output_dir=pilot_root,
            source_plan_path=preexperiment_source_plan_path,
        )
        pilot_artifact_path = pilot_root / _PREEXPERIMENT_ARTIFACT_NAME
        if not pilot_artifact_path.is_file():
            raise ContestPrimeFeedbackDeliveryError(
                "preexperiment runner returned without persisting prime-preexperiment.json"
            )
        pilot = preexperiment_loader(pilot_artifact_path, verify_files=True)
        if pilot.artifact_hash != generated.artifact_hash or pilot.run_id != generated.run_id:
            raise ContestPrimeFeedbackDeliveryError(
                "persisted preexperiment differs from the runner return value"
            )
    else:
        pilot_artifact_path = Path(preexperiment_artifact).expanduser().resolve()
        pilot_root = pilot_artifact_path.parent
        pilot = preexperiment_loader(pilot_artifact_path, verify_files=True)
        _require_new_or_empty_directory(output_root, create=True)

    _verify_pilot_scope(
        pilot,
        question=question,
        expected_source_plan_sha256=preexperiment_source_plan_binding["sha256"],
    )
    pilot_report = _preexperiment_report(
        pilot,
        artifact_path=pilot_artifact_path,
        root=pilot_root,
        executed_in_this_delivery=executed_in_this_delivery,
    )

    scientific_problem = (
        f"{question.question_zh}\n"
        f"原始英文问题：{question.question_en}\n"
        f"来源：《{question.source_title}》第{question.ordinal}题。"
    )
    reference_catalog = default_question_one_reference_catalog(question)
    revision_root = output_root / "revision"
    revision_artifact_path = output_root / _REVISION_ARTIFACT_NAME
    revision = revision_runner(
        original_plan=original_plan_path,
        scientific_problem=scientific_problem,
        requirements=_REVISION_REQUIREMENTS,
        selected_skill_contexts=selected_skill_contexts,
        reference_catalog=reference_catalog,
        preexperiment_artifact=pilot_artifact_path,
        preexperiment_metrics=None,
        preexperiment_root=pilot_root,
        output_dir=revision_root,
        output_path=revision_artifact_path,
        config_path=config_path,
        env_path=env_path,
        timeout_seconds=timeout_seconds,
        max_tokens=max_tokens,
        temperature=0.2,
    )
    if revision.generation_calls != 1:
        raise ContestPrimeFeedbackDeliveryError(
            "research-plan feedback must contain exactly one model revision call"
        )
    revision_report = _revision_report(
        revision,
        artifact_path=revision_artifact_path,
        root=revision_root,
    )

    render_payload = revision.flat_payload()
    embedded_evidence = build_contest_plan_embedded_evidence(
        pilot,
        artifact_path=pilot_artifact_path,
        preexperiment_root=pilot_root,
    )
    if embedded_evidence is not None:
        render_payload["embedded_evidence"] = embedded_evidence.payload
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
                "artifact_file_sha256": pilot_report["artifact"]["sha256"],
                "metrics_sha256": pilot.metrics_sha256,
                "manifest_sha256": pilot.manifest_sha256,
                "formal_experiment_executed": False,
                "mathematical_proof_claimed": False,
            },
        }
    )
    rendered = plan_materializer(
        payload=render_payload,
        output_dir=output_root / "plan",
        evidence_bindings=(
            embedded_evidence.manifest_bindings
            if embedded_evidence is not None
            else ()
        ),
        overwrite=False,
        timeout_seconds=render_timeout_seconds,
    )
    rendered_report = _rendered_report(rendered, root=output_root / "plan")

    report: dict[str, Any] = {
        "schema_version": "contest-prime-feedback-delivery-v1",
        "status": "completed",
        "question_id": question.question_id,
        "question_zh": question.question_zh,
        "question_en": question.question_en,
        "source_delivery": {
            "path": source_root.as_posix(),
            "question_input": _file_binding(question_path),
            "question_source": question_source_binding,
            "selected_method_skills_manifest": _file_binding(skill_manifest_path),
            "selected_method_skills": selected_skill_bindings,
            "skill_routing": routing_binding,
            "original_system_authored_plan": {
                **original_plan_binding,
                "plan_id": original_plan.plan_id,
                "artifact_hash": original_plan.artifact_hash,
            },
            "preexperiment_source_plan": preexperiment_source_plan_binding,
        },
        "requirements_sha256": canonical_model_hash({"requirements": list(_REVISION_REQUIREMENTS)}),
        "reference_catalog_count": len(reference_catalog),
        "reference_catalog_sha256": canonical_model_hash({"references": list(reference_catalog)}),
        "preexperiment_executed": True,
        "preexperiment_executed_in_this_delivery": executed_in_this_delivery,
        "preexperiment": pilot_report,
        "plan_revision_model_calls": 1,
        "revision": revision_report,
        "rendered": rendered_report,
        "formal_experiment_executed": False,
        "paper_claimed": False,
    }
    report_path = output_root / "delivery-report.json"
    _write_new_json(report_path, report)
    returned = dict(report)
    returned["delivery_report_path"] = report_path.as_posix()
    returned["delivery_report_sha256"] = _sha256_file(report_path)
    return returned


def _load_question(path: Path) -> ContestQuestionInput:
    try:
        return ContestQuestionInput.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ContestPrimeFeedbackDeliveryError(
            f"invalid source question input: {path}: {exc}"
        ) from exc


def _load_original_plan(path: Path) -> ContestDirectPlanArtifact:
    try:
        return load_contest_direct_plan(path)
    except Exception as exc:
        raise ContestPrimeFeedbackDeliveryError(
            f"invalid source system-authored plan: {path}: {exc}"
        ) from exc


def _verify_question_source(question: ContestQuestionInput) -> dict[str, Any]:
    source_path = Path(question.source_pdf_path).expanduser().resolve()
    binding = _file_binding(source_path, expected_sha256=question.source_file_sha256)
    binding["source_kind"] = "science_125_booklet_pdf"
    return binding


def _load_and_verify_selected_skills(
    manifest_path: Path,
) -> tuple[tuple[dict[str, str], ...], list[dict[str, Any]], dict[str, Any]]:
    manifest = _read_json_mapping(manifest_path)
    if manifest.get("schema_version") != "contest-direct-selected-skills-v1":
        raise ContestPrimeFeedbackDeliveryError("unsupported selected Skill manifest schema")
    records = manifest.get("skills")
    if not isinstance(records, list):
        raise ContestPrimeFeedbackDeliveryError("selected Skill manifest lacks a skills list")

    contexts: list[dict[str, str]] = []
    bindings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            raise ContestPrimeFeedbackDeliveryError("selected Skill record is not an object")
        skill_id = str(record.get("skill_id") or "").strip()
        expected = str(record.get("content_sha256") or "").strip().lower()
        recorded_path = str(record.get("path") or "").strip()
        if not skill_id or skill_id in seen:
            raise ContestPrimeFeedbackDeliveryError(
                "selected Skill IDs must be nonblank and unique"
            )
        if not _is_sha256(expected) or not recorded_path:
            raise ContestPrimeFeedbackDeliveryError(
                f"selected Skill record has an invalid path/hash: {skill_id}"
            )
        skill_path = _recorded_path(recorded_path, base=manifest_path.parent)
        try:
            content = skill_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ContestPrimeFeedbackDeliveryError(
                f"cannot read selected Skill content: {skill_path}: {exc}"
            ) from exc
        actual = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if actual != expected:
            raise ContestPrimeFeedbackDeliveryError(
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
        bindings.append(
            {
                "skill_id": skill_id,
                "content_sha256": actual,
                **_file_binding(skill_path),
            }
        )

    routing_path_text = str(manifest.get("routing_artifact_path") or "").strip()
    expected_routing_hash = str(manifest.get("routing_artifact_hash") or "").strip()
    if not routing_path_text or not _is_sha256(expected_routing_hash):
        raise ContestPrimeFeedbackDeliveryError(
            "selected Skill manifest lacks a valid routing artifact binding"
        )
    routing_path = _recorded_path(routing_path_text, base=manifest_path.parent)
    routing = _read_json_mapping(routing_path)
    internal_hash = str(routing.get("artifact_hash") or "")
    calculated_hash = canonical_model_hash(
        {key: value for key, value in routing.items() if key != "artifact_hash"}
    )
    if internal_hash != expected_routing_hash or calculated_hash != expected_routing_hash:
        raise ContestPrimeFeedbackDeliveryError("Skill routing artifact hash mismatch")
    routed_ids = tuple(str(item) for item in routing.get("selected_skill_ids", ()))
    routed_hashes = routing.get("selected_skill_hashes")
    expected_ids = tuple(item["skill_id"] for item in contexts)
    expected_hashes = {item["skill_id"]: item["content_sha256"] for item in contexts}
    if routed_ids != expected_ids or routed_hashes != expected_hashes:
        raise ContestPrimeFeedbackDeliveryError(
            "selected Skill manifest differs from the verified routing decision"
        )
    routing_binding = {
        **_file_binding(routing_path),
        "artifact_hash": internal_hash,
    }
    return tuple(contexts), bindings, routing_binding


def _preexperiment_source_plan(
    *,
    source_root: Path,
    original_plan: ContestDirectPlanArtifact,
    question: ContestQuestionInput,
    fallback: Path,
) -> Path:
    rendered_path = source_root / "plan" / "research-plan.json"
    if not rendered_path.is_file():
        return fallback
    private_source = source_root / "plan" / "_private" / "research-plan-source.json"
    rendered = _read_json_mapping(
        private_source if private_source.is_file() else rendered_path
    )
    generation = rendered.get("generation")
    rendered_question = rendered.get("question")
    if not isinstance(generation, Mapping) or not isinstance(rendered_question, Mapping):
        raise ContestPrimeFeedbackDeliveryError(
            "rendered source plan lacks generation/question bindings"
        )
    if generation.get("artifact_hash") != original_plan.artifact_hash:
        raise ContestPrimeFeedbackDeliveryError(
            "rendered source plan is not bound to the original model artifact"
        )
    if rendered_question.get("question_id") != question.question_id:
        raise ContestPrimeFeedbackDeliveryError(
            "rendered source plan is not bound to the source question"
        )
    return rendered_path


def _verify_pilot_scope(
    pilot: ContestPrimePreexperimentArtifact,
    *,
    question: ContestQuestionInput,
    expected_source_plan_sha256: str,
) -> None:
    if pilot.status != "completed" or pilot.study_phase != "exploratory_pilot":
        raise ContestPrimeFeedbackDeliveryError(
            "only a completed exploratory preexperiment can revise the plan"
        )
    if pilot.scientific_question != question.question_zh:
        raise ContestPrimeFeedbackDeliveryError(
            "preexperiment scientific question differs from the source question"
        )
    if pilot.source_plan_sha256 != expected_source_plan_sha256:
        raise ContestPrimeFeedbackDeliveryError(
            "preexperiment was not executed from this delivery's verified plan"
        )
    if pilot.formal_experiment_executed or pilot.mathematical_proof_claimed:
        raise ContestPrimeFeedbackDeliveryError(
            "preexperiment artifact overstates formal execution or mathematical proof"
        )


def _preexperiment_report(
    pilot: ContestPrimePreexperimentArtifact,
    *,
    artifact_path: Path,
    root: Path,
    executed_in_this_delivery: bool,
) -> dict[str, Any]:
    root = root.resolve()
    artifact_binding = _file_binding(_inside(root, artifact_path))
    metrics_binding = _file_binding(
        _inside(root, _relative_path(pilot.metrics_relative_path)),
        expected_sha256=pilot.metrics_sha256,
    )
    manifest_binding = _file_binding(
        _inside(root, _relative_path(pilot.manifest_relative_path)),
        expected_sha256=pilot.manifest_sha256,
    )
    stdout_binding = _file_binding(
        _inside(root, _relative_path(pilot.stdout_log_relative_path)),
        expected_sha256=pilot.stdout_log_sha256,
    )
    stderr_binding = _file_binding(
        _inside(root, _relative_path(pilot.stderr_log_relative_path)),
        expected_sha256=pilot.stderr_log_sha256,
    )
    evidence: list[dict[str, Any]] = []
    for item in pilot.evidence_files:
        binding = _file_binding(
            _inside(root, _relative_path(item.relative_path)),
            expected_sha256=item.sha256,
            expected_size=item.bytes,
        )
        evidence.append({"kind": item.kind, "relative_path": item.relative_path, **binding})
    return {
        "execution_mode": (
            "executed_in_this_delivery"
            if executed_in_this_delivery
            else "reused_after_full_hash_verification"
        ),
        "run_id": pilot.run_id,
        "status": pilot.status,
        "study_phase": pilot.study_phase,
        "artifact_hash": pilot.artifact_hash,
        "artifact": artifact_binding,
        "metrics": metrics_binding,
        "manifest": {**manifest_binding, "manifest_hash": pilot.manifest_hash},
        "stdout_log": stdout_binding,
        "stderr_log": stderr_binding,
        "evidence_files": evidence,
        "formal_experiment_executed": False,
        "mathematical_proof_claimed": False,
    }


def _revision_report(
    revision: ContestDirectPlanRevisionArtifact,
    *,
    artifact_path: Path,
    root: Path,
) -> dict[str, Any]:
    artifact_binding = _file_binding(artifact_path)
    artifact_payload = _read_json_mapping(artifact_path)
    if artifact_payload.get("artifact_hash") != revision.artifact_hash:
        raise ContestPrimeFeedbackDeliveryError(
            "persisted revision differs from the returned revision artifact"
        )
    response_path = _inside(root, _relative_path(revision.raw_response_relative_path))
    response_binding = _file_binding(response_path, expected_sha256=revision.model_response_hash)
    receipt_path = _inside(
        root,
        _relative_path(revision.authorship_receipt_relative_path),
    )
    receipt_payload = _read_json_mapping(receipt_path)
    if receipt_payload.get("receipt_hash") != revision.authorship_receipt_hash:
        raise ContestPrimeFeedbackDeliveryError("revision authorship receipt hash mismatch")
    return {
        "revision_id": revision.revision_id,
        "status": revision.status,
        "provider": revision.provider,
        "model_name": revision.model_name,
        "generation_calls": revision.generation_calls,
        "input_hash": revision.input_hash,
        "model_response_hash": revision.model_response_hash,
        "artifact_hash": revision.artifact_hash,
        "artifact": artifact_binding,
        "raw_response": response_binding,
        "authorship_receipt": {
            **_file_binding(receipt_path),
            "receipt_hash": revision.authorship_receipt_hash,
        },
    }


def _rendered_report(
    rendered: ContestDirectPlanArtifacts,
    *,
    root: Path,
) -> dict[str, Any]:
    bindings = {
        "json": _file_binding(_inside(root, rendered.json_path)),
        **(
            {"internal_source": _file_binding(_inside(root, rendered.source_path))}
            if rendered.source_path is not None
            else {}
        ),
        "markdown": _file_binding(_inside(root, rendered.markdown_path)),
        "tex": _file_binding(_inside(root, rendered.tex_path)),
        "pdf": _file_binding(_inside(root, rendered.pdf_path)),
        "manifest": _file_binding(_inside(root, rendered.manifest_path)),
    }
    return {
        **rendered.to_dict(),
        "artifacts": bindings,
    }


def _read_json_mapping(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContestPrimeFeedbackDeliveryError(f"cannot read JSON artifact {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContestPrimeFeedbackDeliveryError(f"JSON artifact is not an object: {path}")
    return payload


def _require_new_or_empty_directory(path: Path, *, create: bool) -> None:
    if path.exists():
        if not path.is_dir():
            raise ContestPrimeFeedbackDeliveryError(f"output path is not a directory: {path}")
        if any(path.iterdir()):
            raise ContestPrimeFeedbackDeliveryError(
                f"output directory must be new or empty: {path}"
            )
    elif create:
        path.mkdir(parents=True, exist_ok=False)


def _recorded_path(value: str, *, base: Path) -> Path:
    candidate = Path(value).expanduser()
    return candidate.resolve() if candidate.is_absolute() else (base / candidate).resolve()


def _relative_path(value: str) -> Path:
    candidate = Path(*PurePosixPath(value).parts)
    return candidate if not candidate.is_absolute() else candidate.resolve()


def _inside(root: Path, value: Path) -> Path:
    resolved_root = root.resolve()
    candidate = value.resolve() if value.is_absolute() else (resolved_root / value).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ContestPrimeFeedbackDeliveryError(
            f"generated artifact escapes its output root: {candidate}"
        ) from exc
    return candidate


def _file_binding(
    path: Path,
    *,
    expected_sha256: str | None = None,
    expected_size: int | None = None,
) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ContestPrimeFeedbackDeliveryError(f"bound file does not exist: {resolved}")
    actual_hash = _sha256_file(resolved)
    size = resolved.stat().st_size
    if expected_sha256 is not None and actual_hash != expected_sha256:
        raise ContestPrimeFeedbackDeliveryError(f"bound file hash mismatch: {resolved}")
    if expected_size is not None and size != expected_size:
        raise ContestPrimeFeedbackDeliveryError(f"bound file size mismatch: {resolved}")
    return {"path": resolved.as_posix(), "sha256": actual_hash, "size_bytes": size}


def _write_new_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except FileExistsError as exc:
        raise ContestPrimeFeedbackDeliveryError(
            f"refusing to overwrite delivery artifact: {path}"
        ) from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == _SHA256_LENGTH and all(
        character in "0123456789abcdef" for character in value
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="执行或复核真实素数预实验，并让配置模型一次反馈修订中文研究计划。"
    )
    parser.add_argument("--source-delivery-dir", type=Path, default=_DEFAULT_SOURCE_DELIVERY)
    parser.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT)
    parser.add_argument(
        "--preexperiment-artifact",
        type=Path,
        default=None,
        help="可选：已执行 prime-preexperiment.json；将全量验哈希并跳过重复运行。",
    )
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--max-tokens", type=int, default=14_000)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--render-timeout-seconds", type=int, default=180)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_contest_prime_feedback_delivery(
        source_delivery_dir=args.source_delivery_dir,
        output_dir=args.output_dir,
        preexperiment_artifact=args.preexperiment_artifact,
        config_path=args.config,
        env_path=args.env,
        max_tokens=args.max_tokens,
        timeout_seconds=args.timeout_seconds,
        render_timeout_seconds=args.render_timeout_seconds,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through module smoke
    raise SystemExit(main())


__all__ = [
    "ContestPrimeFeedbackDeliveryError",
    "main",
    "run_contest_prime_feedback_delivery",
]
