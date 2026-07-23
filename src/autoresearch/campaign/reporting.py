"""Human-readable campaign reports and complete local deliverables exports."""

from __future__ import annotations

import html
import json
import platform
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import Field

from autoresearch.campaign.models import (
    CampaignManifest,
    CampaignOutcome,
    CampaignSpec,
    ContributionGateResult,
    DevelopmentResult,
    FailureDiagnosis,
    HypothesisProposal,
    HypothesisScreening,
    Preregistration,
    RoundDecision,
    RoundManifest,
    StrictCampaignModel,
    UnseenEvaluation,
)
from autoresearch.campaign.service import validate_campaign_directory
from autoresearch.schemas import file_hash


class CampaignExportFile(StrictCampaignModel):
    """One copied or generated file in a local campaign dossier."""

    relative_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    source_path: str


class CampaignExportManifest(StrictCampaignModel):
    """Hash inventory for one complete, local-only campaign export."""

    schema_version: str = "campaign-deliverables-v1"
    campaign_id: str
    campaign_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    campaign_outcome: CampaignOutcome
    external_submission_authorized: bool = False
    files: tuple[CampaignExportFile, ...] = ()
    generated_at: datetime
    output_path: str


class CampaignExportResult(StrictCampaignModel):
    """Small return object for CLI and automation callers."""

    deliverables_dir: str
    index_path: str
    manifest_path: str
    file_count: int = Field(ge=0)
    external_submission_authorized: bool = False


class CampaignRoundReporter:
    """Render mandatory round artifacts from verified structured evidence."""

    def write_round_reports(
        self,
        *,
        campaign_dir: Path,
        spec: CampaignSpec,
        round_manifest: RoundManifest,
        decision: RoundDecision,
    ) -> RoundManifest:
        """Write deterministic Markdown/JSON/SVG reports and return updated pointers."""

        diagnosis = self._load_required(
            campaign_dir,
            round_manifest,
            "failure_diagnosis",
            FailureDiagnosis,
        )
        hypothesis = self._load_required(
            campaign_dir,
            round_manifest,
            "hypothesis",
            HypothesisProposal,
        )
        screening = self._load_required(
            campaign_dir,
            round_manifest,
            "screening",
            HypothesisScreening,
        )
        gate = self._load_required(
            campaign_dir,
            round_manifest,
            "contribution_gate",
            ContributionGateResult,
        )
        preregistration = self._load_optional(
            campaign_dir,
            round_manifest,
            "preregistration",
            Preregistration,
        )
        development = self._load_optional(
            campaign_dir,
            round_manifest,
            "development_result",
            DevelopmentResult,
        )
        evaluation = self._load_optional(
            campaign_dir,
            round_manifest,
            "unseen_evaluation",
            UnseenEvaluation,
        )
        metrics = _metric_payload(development, evaluation)
        round_dir = campaign_dir / "rounds" / round_manifest.round_id

        generated: dict[str, Path] = {}
        generated["hypothesis_report"] = _write_text(
            round_dir / "hypothesis.md",
            _hypothesis_markdown(round_manifest, hypothesis, diagnosis),
        )
        generated["experiment_manifest"] = _write_json(
            round_dir / "experiment-manifest.json",
            _experiment_manifest_payload(
                round_manifest,
                hypothesis,
                screening,
                preregistration,
                development,
                evaluation,
                gate,
                decision,
            ),
        )
        generated["metrics"] = _write_json(round_dir / "metrics.json", metrics)
        generated["validation_report"] = _write_json(
            round_dir / "validation-report.json",
            {
                "round_id": round_manifest.round_id,
                "passed": gate.passed,
                "checks": gate.checks,
                "failures": gate.failures,
                "warnings": gate.warnings,
                "evaluated_result_hash": gate.evaluated_result_hash,
                "gate_hash": gate.gate_hash,
                "scientific_evidence_boundary": (
                    "A passing internal contribution gate is not external-submission approval."
                ),
            },
        )
        generated["failure_analysis"] = _write_text(
            round_dir / "failure-analysis.md",
            _failure_markdown(round_manifest, diagnosis, gate, decision),
        )
        generated["research_report"] = _write_text(
            round_dir / "research-report.md",
            _research_report_markdown(
                round_manifest,
                hypothesis,
                screening,
                preregistration,
                development,
                evaluation,
                gate,
                decision,
            ),
        )
        generated["loop_report"] = _write_text(
            round_dir / "loop-report.md",
            _loop_report_markdown(round_manifest, hypothesis, decision),
        )
        generated["metrics_table"] = _write_text(
            round_dir / "tables" / "metrics.md",
            _metrics_table_markdown(round_manifest.round_id, metrics),
        )
        generated["metrics_figure"] = _write_text(
            round_dir / "figures" / "metric-summary.svg",
            _metrics_svg(round_manifest.round_id, metrics),
        )
        generated["manuscript"] = _write_text(
            round_dir / f"manuscript-v{round_manifest.round_number}.md",
            _manuscript_markdown(
                spec,
                round_manifest,
                hypothesis,
                preregistration,
                evaluation,
                gate,
            ),
        )
        generated["paper_build_status"] = _write_json(
            round_dir / "paper-build-status.json",
            {
                "round_id": round_manifest.round_id,
                "status": "pending_final_paper_build",
                "reason": (
                    "Round manuscript exists; final template compilation and independent "
                    "reproduction belong to task 260.5."
                ),
                "external_submission_authorized": False,
            },
        )
        generated["round_summary"] = _write_json(
            round_dir / "round-summary.json",
            {
                "campaign_id": round_manifest.campaign_id,
                "round_id": round_manifest.round_id,
                "round_number": round_manifest.round_number,
                "track": round_manifest.track.value,
                "parent_round_id": round_manifest.parent_round_id,
                "parent_result_hash": round_manifest.parent_result_hash,
                "outcome": decision.outcome.value,
                "decision": decision.decision.value,
                "decision_hash": decision.decision_hash,
                "contribution_gate_passed": gate.passed,
                "human_intervention_count": round_manifest.human_intervention_count,
                "metrics": metrics,
            },
        )

        updated = _record_generated_artifacts(
            campaign_dir,
            round_manifest,
            generated,
        )
        evidence_map_path = _write_json(
            round_dir / "evidence-map.json",
            _evidence_map_payload(
                campaign_dir,
                updated,
                development,
                evaluation,
                gate,
            ),
        )
        updated = _record_generated_artifacts(
            campaign_dir,
            updated,
            {"evidence_map": evidence_map_path},
        )
        return updated

    def _load_required(
        self,
        campaign_dir: Path,
        manifest: RoundManifest,
        artifact_name: str,
        model_type: type[Any],
    ) -> Any:
        model = self._load_optional(
            campaign_dir,
            manifest,
            artifact_name,
            model_type,
        )
        if model is None:
            raise ValueError(f"required round artifact is missing: {artifact_name}")
        return model

    def _load_optional(
        self,
        campaign_dir: Path,
        manifest: RoundManifest,
        artifact_name: str,
        model_type: type[Any],
    ) -> Any | None:
        raw_path = manifest.artifact_paths.get(artifact_name)
        if raw_path is None:
            return None
        path = _resolve_path(campaign_dir, raw_path)
        return model_type.model_validate_json(path.read_text(encoding="utf-8"))


class CampaignExporter:
    """Export every verified campaign artifact into one indexed local dossier."""

    def export(
        self,
        campaign_dir: Path | str,
        output_root: Path | str,
    ) -> CampaignExportResult:
        """Validate, copy, index, and hash a complete local-only campaign package."""

        source_root = Path(campaign_dir).resolve()
        spec, manifest, rounds = validate_campaign_directory(source_root)
        deliverables = Path(output_root).resolve() / spec.campaign_id / "deliverables"
        campaign_copy = deliverables / "campaign"
        campaign_copy.mkdir(parents=True, exist_ok=True)
        files: list[CampaignExportFile] = []

        for relative_path in ("campaign-spec.json", "campaign-manifest.json"):
            files.append(
                _copy_export_file(
                    source_root / relative_path,
                    campaign_copy / relative_path,
                    deliverables,
                )
            )

        for round_manifest in rounds:
            round_relative = Path("rounds") / round_manifest.round_id
            manifest_source = source_root / round_relative / "round-manifest.json"
            files.append(
                _copy_export_file(
                    manifest_source,
                    campaign_copy / round_relative / "round-manifest.json",
                    deliverables,
                )
            )
            for raw_path in round_manifest.artifact_paths.values():
                source = _resolve_path(source_root, raw_path)
                relative = Path(raw_path) if not Path(raw_path).is_absolute() else Path(source.name)
                destination = (
                    campaign_copy / relative
                    if not Path(raw_path).is_absolute()
                    else campaign_copy / round_relative / "external" / relative
                )
                files.append(
                    _copy_export_file(source, destination, deliverables)
                )
            if round_manifest.vault_note_path:
                vault_note = Path(round_manifest.vault_note_path)
                if vault_note.is_file():
                    files.append(
                        _copy_export_file(
                            vault_note,
                            deliverables
                            / "knowledge"
                            / f"{round_manifest.round_id}.md",
                            deliverables,
                        )
                    )
            files.extend(
                _copy_external_evidence(
                    source_root,
                    deliverables,
                    round_manifest,
                )
            )

        campaign_report = _write_text(
            deliverables / "campaign-report.md",
            _campaign_report_markdown(spec, manifest, rounds),
        )
        environment_lock = _write_json(
            deliverables / "environment-lock.json",
            {
                "campaign_id": spec.campaign_id,
                "adapter_id": spec.adapter_id,
                "python": sys.version,
                "platform": platform.platform(),
                "campaign_manifest_hash": manifest.manifest_hash,
                "external_submission_authorized": False,
            },
        )
        reproduce = _write_text(
            deliverables / "reproduce.ps1",
            _reproduce_script(spec.campaign_id),
        )
        blocked = _write_text(
            deliverables / "EXPORT-BLOCKED.md",
            "# External submission is not authorized\n\n"
            "This directory is a local research dossier. A human must review the "
            "scientific result, target venue, licenses, and final paper before any upload.\n",
        )
        for generated in (campaign_report, environment_lock, reproduce, blocked):
            files.append(_export_file_for_generated(generated, deliverables))

        index_path = _write_text(
            deliverables / "index.md",
            _deliverables_index_markdown(spec, manifest, rounds),
        )
        files.append(_export_file_for_generated(index_path, deliverables))
        files = _deduplicate_export_files(files)
        export_manifest_path = deliverables / "deliverables-manifest.json"
        export_manifest = CampaignExportManifest(
            campaign_id=spec.campaign_id,
            campaign_manifest_hash=_required(manifest.manifest_hash),
            campaign_outcome=manifest.outcome,
            files=tuple(sorted(files, key=lambda item: item.relative_path)),
            generated_at=datetime.now(timezone.utc),
            output_path=export_manifest_path.as_posix(),
        )
        _write_json(export_manifest_path, export_manifest.model_dump(mode="json"))
        return CampaignExportResult(
            deliverables_dir=deliverables.as_posix(),
            index_path=index_path.as_posix(),
            manifest_path=export_manifest_path.as_posix(),
            file_count=len(files) + 1,
        )


def _record_generated_artifacts(
    campaign_dir: Path,
    manifest: RoundManifest,
    generated: dict[str, Path],
) -> RoundManifest:
    paths = dict(manifest.artifact_paths)
    hashes = dict(manifest.artifact_hashes)
    for name, path in generated.items():
        paths[name] = path.relative_to(campaign_dir).as_posix()
        hashes[name] = file_hash(path)
    return manifest.model_copy(update={"artifact_paths": paths, "artifact_hashes": hashes})


def _metric_payload(
    development: DevelopmentResult | None,
    evaluation: UnseenEvaluation | None,
) -> dict[str, Any]:
    return {
        "development": development.metrics if development else {},
        "unseen": evaluation.metrics if evaluation else {},
        "unseen_outcome": evaluation.outcome.value if evaluation else "not_run",
        "mandatory_evidence_complete": (
            evaluation.mandatory_evidence_complete if evaluation else False
        ),
        "human_intervention_count": (
            evaluation.human_intervention_count if evaluation else 0
        ),
    }


def _hypothesis_markdown(
    manifest: RoundManifest,
    hypothesis: HypothesisProposal,
    diagnosis: FailureDiagnosis,
) -> str:
    return "\n".join(
        [
            f"# {hypothesis.title}",
            "",
            f"- Round: `{manifest.round_id}`",
            f"- Parent result: `{hypothesis.parent_result_hash or 'campaign-root'}`",
            f"- Mechanism family: `{hypothesis.mechanism_family}`",
            f"- Primary metric: `{hypothesis.primary_metric}`",
            "",
            "## Failure diagnosis",
            "",
            diagnosis.causal_hypothesis,
            "",
            "## Falsifiable hypothesis",
            "",
            hypothesis.statement,
            "",
            "## Mechanism change",
            "",
            hypothesis.mechanism_change,
            "",
            "## Predicted effect",
            "",
            hypothesis.predicted_effect,
            "",
            "## Falsification conditions",
            "",
            *[f"- {condition}" for condition in hypothesis.falsification_conditions],
            "",
            "Current-round unseen references were not available to proposal generation.",
        ]
    )


def _experiment_manifest_payload(
    manifest: RoundManifest,
    hypothesis: HypothesisProposal,
    screening: HypothesisScreening,
    preregistration: Preregistration | None,
    development: DevelopmentResult | None,
    evaluation: UnseenEvaluation | None,
    gate: ContributionGateResult,
    decision: RoundDecision,
) -> dict[str, Any]:
    return {
        "campaign_id": manifest.campaign_id,
        "round_id": manifest.round_id,
        "track": manifest.track.value,
        "parent_round_id": manifest.parent_round_id,
        "parent_result_hash": manifest.parent_result_hash,
        "design_hash": manifest.design_hash,
        "hypothesis_id": hypothesis.hypothesis_id,
        "proposal_hash": hypothesis.proposal_hash,
        "screening_hash": screening.screening_hash,
        "preregistration_hash": (
            preregistration.preregistration_hash if preregistration else None
        ),
        "development_result_hash": development.result_hash if development else None,
        "unseen_result_hash": evaluation.result_hash if evaluation else None,
        "contribution_gate_hash": gate.gate_hash,
        "decision_hash": decision.decision_hash,
        "seeds": list(preregistration.seeds) if preregistration else [],
        "development_data_refs": (
            list(preregistration.development_data_refs) if preregistration else []
        ),
        "unseen_data_refs": (
            list(preregistration.unseen_data_refs) if preregistration else []
        ),
        "human_intervention_count": manifest.human_intervention_count,
        "external_submission_authorized": False,
    }


def _failure_markdown(
    manifest: RoundManifest,
    diagnosis: FailureDiagnosis,
    gate: ContributionGateResult,
    decision: RoundDecision,
) -> str:
    failures = list(gate.failures) or ["No terminal gate failure; confirmation may still be required."]
    return "\n".join(
        [
            f"# Failure analysis — {manifest.round_id}",
            "",
            f"- Failure class: `{diagnosis.failure_kind.value}`",
            f"- Round outcome: `{decision.outcome.value}`",
            f"- Next action: `{decision.decision.value}`",
            "",
            "## Causal diagnosis",
            "",
            diagnosis.causal_hypothesis,
            "",
            "## Required mechanism change",
            "",
            diagnosis.required_mechanism_change,
            "",
            "## Gate failures",
            "",
            *[f"- {failure}" for failure in failures],
            "",
            "A negative result remains a first-class result and is not rewritten as success.",
        ]
    )


def _research_report_markdown(
    manifest: RoundManifest,
    hypothesis: HypothesisProposal,
    screening: HypothesisScreening,
    preregistration: Preregistration | None,
    development: DevelopmentResult | None,
    evaluation: UnseenEvaluation | None,
    gate: ContributionGateResult,
    decision: RoundDecision,
) -> str:
    metric_rows = _flatten_metrics(_metric_payload(development, evaluation))
    return "\n".join(
        [
            f"# Research report — {manifest.round_id}",
            "",
            "## Research question",
            "",
            hypothesis.statement,
            "",
            "## Proposed mechanism",
            "",
            f"`{hypothesis.mechanism_family}` — {hypothesis.mechanism_change}",
            "",
            "## Result-blind protocol",
            "",
            (
                f"Preregistration `{preregistration.preregistration_hash}` froze "
                f"{len(preregistration.seeds)} seeds and "
                f"{len(preregistration.unseen_data_refs)} unseen references."
                if preregistration
                else "The development screen failed before an unseen protocol was frozen."
            ),
            "",
            "## Development screen",
            "",
            f"- Passed: `{screening.passed}`",
            f"- Score: `{screening.development_score}`",
            "",
            "## Results",
            "",
            *[f"- `{name}`: {value}" for name, value in metric_rows],
            "",
            "## Deterministic contribution gate",
            "",
            *[f"- `{name}`: `{value}`" for name, value in sorted(gate.checks.items())],
            "",
            f"Decision: `{decision.decision.value}` — {decision.reason}",
            "",
            "## Evidence boundary",
            "",
            "This report is generated from persisted runtime evidence. It does not claim "
            "acceptance, publication, or authorization to submit externally.",
        ]
    )


def _loop_report_markdown(
    manifest: RoundManifest,
    hypothesis: HypothesisProposal,
    decision: RoundDecision,
) -> str:
    return "\n".join(
        [
            f"# Loop report — {manifest.round_id}",
            "",
            f"- Parent round: `{manifest.parent_round_id or 'campaign-root'}`",
            f"- Parent result hash: `{manifest.parent_result_hash or 'none'}`",
            f"- Current mechanism: `{hypothesis.mechanism_family}`",
            f"- Current result hash: `{decision.result_hash}`",
            f"- Decision: `{decision.decision.value}`",
            f"- Next-round trigger: `{decision.next_round_trigger or 'none'}`",
            "",
            "A formatting-only change or identical rerun does not count as a new research round.",
        ]
    )


def _metrics_table_markdown(round_id: str, metrics: dict[str, Any]) -> str:
    rows = _flatten_metrics(metrics)
    return "\n".join(
        [
            f"# Metrics — {round_id}",
            "",
            "| Scope | Metric | Value |",
            "|---|---|---:|",
            *[
                f"| {name.split('.', 1)[0]} | {name.split('.', 1)[-1]} | {value} |"
                for name, value in rows
            ],
        ]
    )


def _metrics_svg(round_id: str, metrics: dict[str, Any]) -> str:
    rows = _flatten_metrics(metrics)[:12]
    height = 90 + 28 * max(1, len(rows))
    elements = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="960" '
        f'height="{height}" viewBox="0 0 960 {height}">',
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        '<text x="32" y="42" font-family="Arial, sans-serif" font-size="24" '
        f'fill="#0f172a">Metric summary — {html.escape(round_id)}</text>',
    ]
    if not rows:
        elements.append(
            '<text x="32" y="78" font-family="Arial, sans-serif" font-size="16" '
            'fill="#64748b">No numerical experiment metric was produced.</text>'
        )
    for index, (name, value) in enumerate(rows):
        y = 82 + index * 28
        elements.append(
            f'<text x="32" y="{y}" font-family="Consolas, monospace" font-size="15" '
            f'fill="#334155">{html.escape(name)}</text>'
        )
        elements.append(
            f'<text x="720" y="{y}" font-family="Consolas, monospace" font-size="15" '
            f'fill="#0f766e">{html.escape(str(value))}</text>'
        )
    elements.append("</svg>")
    return "\n".join(elements)


def _manuscript_markdown(
    spec: CampaignSpec,
    manifest: RoundManifest,
    hypothesis: HypothesisProposal,
    preregistration: Preregistration | None,
    evaluation: UnseenEvaluation | None,
    gate: ContributionGateResult,
) -> str:
    result_sentence = (
        f"The frozen evaluation ended as `{evaluation.outcome.value}`."
        if evaluation
        else "The candidate stopped before unseen evaluation."
    )
    return "\n".join(
        [
            f"# {hypothesis.title}",
            "",
            "## Abstract",
            "",
            f"This round evaluates {hypothesis.mechanism_family} under a result-blind, "
            f"hash-bound protocol. {result_sentence}",
            "",
            "## 1. Introduction",
            "",
            hypothesis.repair_rationale,
            "",
            "## 2. Method",
            "",
            hypothesis.mechanism_change,
            "",
            "## 3. Experimental protocol",
            "",
            (
                f"The protocol used {len(preregistration.seeds)} independent seeds and "
                f"froze its adjudicator as `{preregistration.adjudicator_hash}`."
                if preregistration
                else "No unseen protocol was executed."
            ),
            "",
            "## 4. Results",
            "",
            result_sentence,
            "",
            "## 5. Limitations",
            "",
            *[f"- {failure}" for failure in gate.failures],
            (
                "- The internal contribution gate passed, but venue acceptance and external "
                "submission still require human review."
                if gate.passed
                else "- The contribution gate did not pass; this manuscript is a negative-result draft."
            ),
            "",
            "## Evidence availability",
            "",
            f"Campaign `{spec.campaign_id}`, round `{manifest.round_id}`. All claims must "
            "resolve through the campaign deliverables manifest.",
        ]
    )


def _evidence_map_payload(
    campaign_dir: Path,
    manifest: RoundManifest,
    development: DevelopmentResult | None,
    evaluation: UnseenEvaluation | None,
    gate: ContributionGateResult,
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    for name, raw_path in sorted(manifest.artifact_paths.items()):
        path = _resolve_path(campaign_dir, raw_path)
        nodes.append(
            {
                "id": name,
                "kind": "campaign_artifact",
                "path": raw_path,
                "exists": path.is_file(),
                "sha256": file_hash(path) if path.is_file() else None,
            }
        )
    external_refs = {
        *([] if development is None else development.evidence_paths),
        *([] if evaluation is None else evaluation.evidence_paths),
        *gate.evidence_paths,
    }
    for index, raw_path in enumerate(sorted(external_refs), start=1):
        path = _resolve_evidence_path(campaign_dir, manifest.round_id, raw_path)
        nodes.append(
            {
                "id": f"external-evidence-{index}",
                "kind": "adapter_evidence",
                "path": raw_path,
                "exists": path.is_file(),
                "sha256": file_hash(path) if path.is_file() else None,
            }
        )
    return {
        "campaign_id": manifest.campaign_id,
        "round_id": manifest.round_id,
        "nodes": nodes,
        "edges": [
            {
                "source": "hypothesis",
                "relation": "tested_by",
                "target": "preregistration",
            },
            {
                "source": "preregistration",
                "relation": "evaluated_by",
                "target": "unseen_evaluation",
            },
            {
                "source": "unseen_evaluation",
                "relation": "adjudicated_by",
                "target": "contribution_gate",
            },
        ],
        "missing_adapter_evidence": [
            node["path"]
            for node in nodes
            if node["kind"] == "adapter_evidence" and not node["exists"]
        ],
    }


def _campaign_report_markdown(
    spec: CampaignSpec,
    manifest: CampaignManifest,
    rounds: tuple[RoundManifest, ...],
) -> str:
    return "\n".join(
        [
            f"# Campaign report — {spec.campaign_id}",
            "",
            f"- Policy: `{spec.policy.value}`",
            f"- Adapter: `{spec.adapter_id}`",
            f"- Outcome: `{manifest.outcome.value}`",
            f"- Completed rounds: {manifest.completed_round_count}",
            f"- Experimental rounds: {manifest.experimental_round_count}",
            f"- Human interventions: {manifest.human_intervention_count}",
            f"- Lineage hash: `{manifest.lineage_hash}`",
            "",
            "## Round lineage",
            "",
            *[
                f"- `{round_manifest.round_id}`: `{round_manifest.outcome.value}`; "
                f"manifest `{round_manifest.manifest_hash}`"
                for round_manifest in rounds
            ],
            "",
            "This report describes persisted execution evidence, not venue acceptance.",
        ]
    )


def _deliverables_index_markdown(
    spec: CampaignSpec,
    manifest: CampaignManifest,
    rounds: tuple[RoundManifest, ...],
) -> str:
    lines = [
        f"# Deliverables — {spec.campaign_id}",
        "",
        f"- Campaign outcome: `{manifest.outcome.value}`",
        f"- Experimental rounds: {manifest.experimental_round_count}",
        "- External submission authorized: `false`",
        "",
        "## Campaign-level files",
        "",
        "- [Campaign report](campaign-report.md)",
        "- [Campaign manifest](campaign/campaign-manifest.json)",
        "- [Campaign specification](campaign/campaign-spec.json)",
        "- [Environment lock](environment-lock.json)",
        "- [Reproduction entrypoint](reproduce.ps1)",
        "- [Submission block](EXPORT-BLOCKED.md)",
        "",
        "## Round reports",
        "",
    ]
    for round_manifest in rounds:
        prefix = f"campaign/rounds/{round_manifest.round_id}"
        lines.extend(
            [
                f"### {round_manifest.round_id}",
                "",
                f"- [Research report]({prefix}/research-report.md)",
                f"- [Failure analysis]({prefix}/failure-analysis.md)",
                f"- [Loop report]({prefix}/loop-report.md)",
                f"- [Hypothesis]({prefix}/hypothesis.md)",
                f"- [Preregistration]({prefix}/preregistration.json)",
                f"- [Experiment manifest]({prefix}/experiment-manifest.json)",
                f"- [Metrics]({prefix}/metrics.json)",
                f"- [Validation]({prefix}/validation-report.json)",
                f"- [Evidence map]({prefix}/evidence-map.json)",
                f"- [Metrics table]({prefix}/tables/metrics.md)",
                f"- [Metrics figure]({prefix}/figures/metric-summary.svg)",
                (
                    f"- [Manuscript v{round_manifest.round_number}]"
                    f"({prefix}/manuscript-v{round_manifest.round_number}.md)"
                ),
                "",
            ]
        )
    lines.extend(
        [
            "## Boundary",
            "",
            "A local deliverables package is not permission to upload or submit externally.",
        ]
    )
    return "\n".join(lines)


def _reproduce_script(campaign_id: str) -> str:
    return "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            "$deliverablesRoot = Split-Path -Parent $MyInvocation.MyCommand.Path",
            "$campaignDir = Join-Path $deliverablesRoot 'campaign'",
            'poetry run airesearcher campaign status "$campaignDir"',
            (
                "$manifest = Get-Content -Raw "
                '(Join-Path $deliverablesRoot "deliverables-manifest.json") '
                "| ConvertFrom-Json"
            ),
            "foreach ($file in $manifest.files) {",
            "    $path = Join-Path $deliverablesRoot $file.relative_path",
            "    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {",
            '        throw "Missing deliverable: $($file.relative_path)"',
            "    }",
            (
                "    $actual = "
                "(Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()"
            ),
            "    if ($actual -ne $file.sha256) {",
            '        throw "Hash mismatch: $($file.relative_path)"',
            "    }",
            "}",
            (
                f'Write-Host "Verified local campaign {campaign_id} and '
                '$($manifest.files.Count) indexed files"'
            ),
            (
                'Write-Host "Scientific experiment re-execution remains adapter-specific '
                'and is not performed by this integrity check."'
            ),
        ]
    )


def _copy_external_evidence(
    source_root: Path,
    deliverables: Path,
    manifest: RoundManifest,
) -> list[CampaignExportFile]:
    evidence_map_raw = manifest.artifact_paths.get("evidence_map")
    if evidence_map_raw is None:
        return []
    evidence_map = json.loads(
        _resolve_path(source_root, evidence_map_raw).read_text(encoding="utf-8")
    )
    copied: list[CampaignExportFile] = []
    for node in evidence_map.get("nodes", []):
        if node.get("kind") != "adapter_evidence" or not node.get("exists"):
            continue
        source = _resolve_evidence_path(
            source_root,
            manifest.round_id,
            str(node["path"]),
        )
        digest = str(node["sha256"])
        destination = (
            deliverables
            / "campaign"
            / "rounds"
            / manifest.round_id
            / "raw-evidence"
            / f"{digest[:12]}-{source.name}"
        )
        copied.append(_copy_export_file(source, destination, deliverables))
    return copied


def _copy_export_file(
    source: Path,
    destination: Path,
    deliverables: Path,
) -> CampaignExportFile:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    shutil.copyfile(source, temporary)
    temporary.replace(destination)
    return CampaignExportFile(
        relative_path=destination.relative_to(deliverables).as_posix(),
        sha256=file_hash(destination),
        size_bytes=destination.stat().st_size,
        source_path=source.as_posix(),
    )


def _export_file_for_generated(path: Path, deliverables: Path) -> CampaignExportFile:
    return CampaignExportFile(
        relative_path=path.relative_to(deliverables).as_posix(),
        sha256=file_hash(path),
        size_bytes=path.stat().st_size,
        source_path="generated-by-campaign-exporter",
    )


def _deduplicate_export_files(
    files: list[CampaignExportFile],
) -> list[CampaignExportFile]:
    by_path: dict[str, CampaignExportFile] = {}
    for item in files:
        existing = by_path.get(item.relative_path)
        if existing is not None and existing.sha256 != item.sha256:
            raise ValueError(f"export collision with different content: {item.relative_path}")
        by_path[item.relative_path] = item
    return list(by_path.values())


def _flatten_metrics(payload: dict[str, Any], prefix: str = "") -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    for key, value in sorted(payload.items()):
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            rows.extend(_flatten_metrics(value, name))
        else:
            rows.append((name, value))
    return rows


def _resolve_path(root: Path, raw_path: str) -> Path:
    resolved_root = root.resolve()
    path = Path(raw_path)
    candidate = path.resolve() if path.is_absolute() else (resolved_root / path).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("managed report artifact escapes the campaign directory") from exc
    return candidate


def _resolve_evidence_path(root: Path, round_id: str, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    root_candidate = root / path
    if root_candidate.exists():
        return root_candidate
    return root / "rounds" / round_id / path


def _write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content.rstrip() + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    return _write_text(
        path,
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
    )


def _required(value: str | None) -> str:
    if value is None:
        raise ValueError("required persisted hash is missing")
    return value
