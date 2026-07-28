"""Persistent, idempotent competition research-cycle service."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel

from autoresearch.competition.manifest import (
    build_competition_submission,
    canonical_model_hash,
    load_cycle_manifest,
    validate_cycle_evidence,
    write_cycle_manifest,
    write_evidence_gate_report,
    write_json_model,
)
from autoresearch.competition.mdbench import MDBenchAdapter
from autoresearch.competition.migration import (
    CompetitionMigrationCoordinator,
    CompetitionMigrationError,
    CompetitionMigrationMode,
    resolve_competition_formal_run_id,
    resolve_competition_migration_mode,
)
from autoresearch.competition.models import (
    AccessKind,
    AccessRequest,
    CapabilityGrant,
    ClaimBinding,
    CompetitionRunSpec,
    CycleManifest,
    CycleOutcome,
    CycleResult,
    CycleStage,
    EvidenceGateReport,
    ExperimentProtocol,
    HypothesisProposal,
    TopicCandidate,
    TopicSelectionReport,
)
from autoresearch.competition.planning import PlanCompiler, hypothesis_from_topic
from autoresearch.competition.selection import (
    TopicSelectionEngine,
    competition_topic_candidates,
    selected_candidate,
)
from autoresearch.knowledge import (
    KnowledgeEntry,
    KnowledgeEntryType,
    KnowledgeZone,
    MarkdownKnowledgeStore,
    create_vault_layout,
)


class ResearchCycleService:
    """Run or resume the Gate-A-first unattended research lifecycle."""

    def __init__(
        self,
        *,
        output_root: Path | str = Path("runs/competition"),
        vault_root: Path | str = Path("autoresearch-vault"),
        capability_grant: CapabilityGrant | None = None,
        adapter: MDBenchAdapter | None = None,
        migration_mode: CompetitionMigrationMode | str | None = None,
        migration_root: Path | str | None = None,
        migration_formal_run_id: str | None = None,
    ) -> None:
        self.output_root = Path(output_root).resolve()
        self.vault_root = Path(vault_root).resolve()
        self.capability_grant = capability_grant
        self.adapter = adapter or MDBenchAdapter()
        self.selector = TopicSelectionEngine()
        self.compiler = PlanCompiler()
        self.migration_mode = resolve_competition_migration_mode(migration_mode)
        formal_run_id = resolve_competition_formal_run_id(migration_formal_run_id)
        if self.migration_mode is CompetitionMigrationMode.LEGACY:
            if formal_run_id is not None:
                raise CompetitionMigrationError(
                    "formal Competition runs require shadow migration mode"
                )
            self._migration: CompetitionMigrationCoordinator | None = None
        else:
            root = (
                Path(migration_root)
                if migration_root is not None
                else self.output_root / ".vnext-migration" / "competition"
            )
            self._migration = CompetitionMigrationCoordinator(
                root=root,
                mode=self.migration_mode,
                formal_run_id=formal_run_id,
            )

    def run(self, spec: CompetitionRunSpec) -> CycleResult:
        """Start a new cycle, or idempotently resume the same run ID."""

        self._assert_migration_mode_allowed()
        _validate_run_id(spec.run_id)
        cycle_dir = self.output_root / spec.run_id
        manifest_path = cycle_dir / "cycle-manifest.json"
        if manifest_path.exists():
            return self.resume(cycle_dir)

        try:
            cycle_dir.mkdir(parents=True, exist_ok=True)
            spec_path = write_json_model(cycle_dir / "competition-run-spec.json", spec)
            manifest = CycleManifest(
                run_id=spec.run_id,
                project_id=spec.project_id,
                spec_hash=canonical_model_hash(spec),
                artifact_paths={"run_spec": spec_path.as_posix()},
            )
            manifest = write_cycle_manifest(manifest_path, manifest)
            result = self._continue(spec, cycle_dir, manifest)
        except Exception as exc:
            self._record_migration_failure(
                cycle_dir=cycle_dir,
                run_id=spec.run_id,
                invocation_kind="run",
                error=exc,
            )
            raise
        return self._record_migration_result(
            cycle_dir=cycle_dir,
            result=result,
            invocation_kind="run",
        )

    def resume(self, cycle_dir: Path | str) -> CycleResult:
        """Resume from the last persisted stage without rerunning completed seeds."""

        self._assert_migration_mode_allowed()
        resolved = Path(cycle_dir)
        if resolved.is_file():
            resolved = resolved.parent
        spec_path = resolved / "competition-run-spec.json"
        manifest_path = resolved / "cycle-manifest.json"
        spec = CompetitionRunSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))
        manifest = load_cycle_manifest(manifest_path)
        if manifest.spec_hash != canonical_model_hash(spec):
            raise ValueError("competition run spec hash does not match cycle manifest")
        if manifest.stage is CycleStage.COMPLETE:
            result = _cycle_result(resolved, manifest)
        else:
            try:
                result = self._continue(spec, resolved, manifest)
            except Exception as exc:
                self._record_migration_failure(
                    cycle_dir=resolved,
                    run_id=spec.run_id,
                    invocation_kind="resume",
                    error=exc,
                )
                raise
        return self._record_migration_result(
            cycle_dir=resolved,
            result=result,
            invocation_kind="resume",
        )

    def _assert_migration_mode_allowed(self) -> None:
        if self._migration is not None:
            self._migration.assert_mode_allowed()

    def _record_migration_result(
        self,
        *,
        cycle_dir: Path,
        result: CycleResult,
        invocation_kind: Literal["run", "resume"],
    ) -> CycleResult:
        if self._migration is None:
            return result
        return self._migration.record_result(
            cycle_dir=cycle_dir,
            result=result,
            invocation_kind=invocation_kind,
        )

    def _record_migration_failure(
        self,
        *,
        cycle_dir: Path,
        run_id: str,
        invocation_kind: Literal["run", "resume"],
        error: Exception,
    ) -> None:
        if self._migration is None:
            return
        manifest_path = cycle_dir / "cycle-manifest.json"
        if not manifest_path.is_file():
            return
        self._migration.record_failure(
            cycle_dir=cycle_dir,
            run_id=run_id,
            invocation_kind=invocation_kind,
            error=error,
        )

    def export(self, cycle_dir: Path | str, output_dir: Path | str) -> Path:
        """Export required competition fields without bypassing the release gate."""

        resolved = Path(cycle_dir)
        manifest_path = resolved / "cycle-manifest.json"
        manifest = load_cycle_manifest(manifest_path)
        topic = _load_model(resolved / "selected-topic.json", TopicCandidate)
        protocol = _load_model(resolved / "experiment-protocol.json", ExperimentProtocol)
        gate = _load_model(resolved / "evidence-gate.json", EvidenceGateReport)
        submission = build_competition_submission(
            manifest_path=manifest_path,
            manifest=manifest,
            topic=topic,
            protocol=protocol,
            evidence_gate=gate,
        )
        target = Path(output_dir) / manifest.run_id / "competition-submission.json"
        write_json_model(target, submission)
        if not submission.submission_ready:
            blocked_path = target.parent / "EXPORT-BLOCKED.md"
            blocked_path.write_text(
                "# Competition export is not submission-ready\n\n"
                + "\n".join(f"- {reason}" for reason in submission.blocked_reasons)
                + "\n",
                encoding="utf-8",
            )
        return target

    def _continue(
        self,
        spec: CompetitionRunSpec,
        cycle_dir: Path,
        manifest: CycleManifest,
    ) -> CycleResult:
        manifest_path = cycle_dir / "cycle-manifest.json"
        access_result = self._check_capability_reference(spec, cycle_dir, manifest)
        if access_result is not None:
            return access_result

        topic, selection, manifest = self._topic_stage(spec, cycle_dir, manifest)
        if topic is None:
            manifest = manifest.model_copy(
                update={
                    "stage": CycleStage.COMPLETE,
                    "outcome": CycleOutcome.NEGATIVE_RESULT,
                    "artifact_paths": {
                        **manifest.artifact_paths,
                        "topic_selection": (cycle_dir / "topic-selection.json").as_posix(),
                    },
                }
            )
            write_cycle_manifest(manifest_path, manifest)
            _write_negative_report(cycle_dir, selection.negative_reason or "no viable topic")
            return _cycle_result(cycle_dir, load_cycle_manifest(manifest_path))

        hypothesis, manifest = self._hypothesis_stage(topic, cycle_dir, manifest)
        protocol, manifest = self._plan_stage(
            spec,
            topic,
            hypothesis,
            cycle_dir,
            manifest,
        )
        manifest = self._experiment_stage(
            spec,
            topic,
            hypothesis,
            protocol,
            cycle_dir,
            manifest,
        )
        claims = _claims_for_attempts(topic, hypothesis, manifest)
        manifest = manifest.model_copy(update={"claims": claims})
        gate = validate_cycle_evidence(
            manifest=manifest,
            topic=topic,
            hypothesis=hypothesis,
            protocol=protocol,
        )
        gate = write_evidence_gate_report(cycle_dir / "evidence-gate.json", gate)
        smoke_passed = gate.passed and all(
            attempt.metrics.get("smoke_passed") == 1.0 for attempt in manifest.attempts
        )
        outcome = (
            CycleOutcome.DEVELOPMENT_SMOKE_PASSED
            if smoke_passed
            else CycleOutcome.NEGATIVE_RESULT
        )
        vault_note = self._write_vault_note(
            spec=spec,
            topic=topic,
            hypothesis=hypothesis,
            protocol=protocol,
            manifest=manifest,
            gate=gate,
            outcome=outcome,
        )
        summary_path = _write_summary(
            cycle_dir=cycle_dir,
            spec=spec,
            topic=topic,
            selection=selection,
            manifest=manifest,
            gate=gate,
            outcome=outcome,
        )
        manifest = manifest.model_copy(
            update={
                "stage": CycleStage.COMPLETE,
                "outcome": outcome,
                "release_eligible": gate.release_allowed,
                "artifact_paths": {
                    **manifest.artifact_paths,
                    "evidence_gate": (gate.output_path or ""),
                    "cycle_summary": summary_path.as_posix(),
                    "vault_note": vault_note.as_posix(),
                },
            }
        )
        manifest = write_cycle_manifest(manifest_path, manifest)
        return _cycle_result(cycle_dir, manifest)

    def _check_capability_reference(
        self,
        spec: CompetitionRunSpec,
        cycle_dir: Path,
        manifest: CycleManifest,
    ) -> CycleResult | None:
        if spec.capability_grant_id is None:
            return None
        if (
            self.capability_grant is not None
            and self.capability_grant.grant_id == spec.capability_grant_id
            and self.capability_grant.valid_until > datetime.now(timezone.utc)
        ):
            return None
        if manifest.outcome is CycleOutcome.ACCESS_REQUIRED and manifest.access_request_ids:
            return _cycle_result(cycle_dir, manifest)
        request = AccessRequest(
            run_id=spec.run_id,
            kind=AccessKind.CAPABILITY_GRANT,
            reason="referenced CapabilityGrant is missing, expired, or has a different ID",
            minimum_scope=f"CapabilityGrant {spec.capability_grant_id}",
        )
        request_path = cycle_dir / "access-requests" / f"{request.request_id}.json"
        write_json_model(request_path, request)
        next_manifest = manifest.model_copy(
            update={
                "outcome": CycleOutcome.ACCESS_REQUIRED,
                "access_request_ids": (*manifest.access_request_ids, request.request_id),
                "artifact_paths": {
                    **manifest.artifact_paths,
                    f"access_request_{request.request_id}": request_path.as_posix(),
                },
            }
        )
        next_manifest = write_cycle_manifest(cycle_dir / "cycle-manifest.json", next_manifest)
        return _cycle_result(cycle_dir, next_manifest)

    def _topic_stage(
        self,
        spec: CompetitionRunSpec,
        cycle_dir: Path,
        manifest: CycleManifest,
    ) -> tuple[TopicCandidate | None, TopicSelectionReport, CycleManifest]:
        selected_path = cycle_dir / "selected-topic.json"
        selection_path = cycle_dir / "topic-selection.json"
        if manifest.topic_id is not None and selected_path.exists() and selection_path.exists():
            return (
                _load_model(selected_path, TopicCandidate),
                _load_model(selection_path, TopicSelectionReport),
                manifest,
            )

        candidates = competition_topic_candidates(spec)
        candidates_path = write_json_model(
            cycle_dir / "topic-candidates.json",
            {"candidates": [candidate.model_dump(mode="json") for candidate in candidates]},
        )
        report = self.selector.select(
            spec=spec,
            candidates=candidates,
            probe=lambda candidate: self.adapter.run_feasibility_probe(
                candidate=candidate,
                root=cycle_dir / "feasibility",
                project_id=spec.project_id,
                timeout_seconds=spec.timeout_seconds,
            ),
        )
        write_json_model(selection_path, report)
        topic = selected_candidate(candidates, report)
        artifact_paths = {
            **manifest.artifact_paths,
            "topic_candidates": candidates_path.as_posix(),
            "topic_selection": selection_path.as_posix(),
        }
        if topic is None:
            next_manifest = manifest.model_copy(update={"artifact_paths": artifact_paths})
            next_manifest = write_cycle_manifest(cycle_dir / "cycle-manifest.json", next_manifest)
            return None, report, next_manifest
        write_json_model(selected_path, topic)
        next_manifest = manifest.model_copy(
            update={
                "stage": CycleStage.TOPIC_SELECTED,
                "outcome": CycleOutcome.RUNNING,
                "topic_id": topic.topic_id,
                "artifact_paths": {
                    **artifact_paths,
                    "selected_topic": selected_path.as_posix(),
                },
            }
        )
        next_manifest = write_cycle_manifest(cycle_dir / "cycle-manifest.json", next_manifest)
        return topic, report, next_manifest

    def _hypothesis_stage(
        self,
        topic: TopicCandidate,
        cycle_dir: Path,
        manifest: CycleManifest,
    ) -> tuple[HypothesisProposal, CycleManifest]:
        path = cycle_dir / "hypothesis.json"
        if manifest.hypothesis_id is not None and path.exists():
            return _load_model(path, HypothesisProposal), manifest
        hypothesis = hypothesis_from_topic(topic)
        write_json_model(path, hypothesis)
        next_manifest = manifest.model_copy(
            update={
                "stage": CycleStage.HYPOTHESIS_DEFINED,
                "hypothesis_id": hypothesis.hypothesis_id,
                "artifact_paths": {**manifest.artifact_paths, "hypothesis": path.as_posix()},
            }
        )
        next_manifest = write_cycle_manifest(cycle_dir / "cycle-manifest.json", next_manifest)
        return hypothesis, next_manifest

    def _plan_stage(
        self,
        spec: CompetitionRunSpec,
        topic: TopicCandidate,
        hypothesis: HypothesisProposal,
        cycle_dir: Path,
        manifest: CycleManifest,
    ) -> tuple[ExperimentProtocol, CycleManifest]:
        path = cycle_dir / "experiment-protocol.json"
        if manifest.protocol_id is not None and path.exists():
            return _load_model(path, ExperimentProtocol), manifest
        protocol = self.compiler.compile(
            project_id=spec.project_id,
            topic=topic,
            hypothesis=hypothesis,
            timeout_seconds=spec.timeout_seconds,
        )
        plan_hash = canonical_model_hash(protocol)
        write_json_model(path, protocol)
        next_manifest = manifest.model_copy(
            update={
                "stage": CycleStage.PLAN_COMPILED,
                "protocol_id": protocol.protocol_id,
                "plan_hash": plan_hash,
                "artifact_paths": {
                    **manifest.artifact_paths,
                    "experiment_protocol": path.as_posix(),
                },
            }
        )
        next_manifest = write_cycle_manifest(cycle_dir / "cycle-manifest.json", next_manifest)
        return protocol, next_manifest

    def _experiment_stage(
        self,
        spec: CompetitionRunSpec,
        topic: TopicCandidate,
        hypothesis: HypothesisProposal,
        protocol: ExperimentProtocol,
        cycle_dir: Path,
        manifest: CycleManifest,
    ) -> CycleManifest:
        if manifest.plan_hash is None:
            raise ValueError("experiment stage requires a persisted plan hash")
        attempts = list(manifest.attempts)
        completed_seeds = {attempt.seed for attempt in attempts}
        parent_id = attempts[0].attempt_id if attempts else None
        code_hashes = dict(manifest.code_hashes)
        data_hashes = dict(manifest.data_hashes)
        artifact_paths = dict(manifest.artifact_paths)
        for seed in protocol.seeds:
            if seed in completed_seeds:
                continue
            executed = self.adapter.execute_attempt(
                cycle_dir=cycle_dir,
                project_id=spec.project_id,
                candidate=topic,
                hypothesis=hypothesis,
                protocol=protocol,
                plan_hash=manifest.plan_hash,
                seed=seed,
                parent_attempt_id=parent_id,
                timeout_seconds=spec.timeout_seconds,
            )
            attempt = executed.attempt
            if parent_id is None:
                parent_id = attempt.attempt_id
            attempts.append(attempt)
            code_hashes[f"seed-{seed}"] = attempt.code_hash
            data_hashes[f"seed-{seed}"] = attempt.data_hash
            artifact_paths[f"attempt_seed_{seed}"] = executed.record_path.as_posix()
            manifest = manifest.model_copy(
                update={
                    "attempts": tuple(attempts),
                    "code_hashes": code_hashes,
                    "data_hashes": data_hashes,
                    "artifact_paths": artifact_paths,
                }
            )
            manifest = write_cycle_manifest(cycle_dir / "cycle-manifest.json", manifest)
            if attempt.status.value == "failed":
                break
        next_manifest = manifest.model_copy(update={"stage": CycleStage.EXPERIMENTS_EXECUTED})
        return write_cycle_manifest(cycle_dir / "cycle-manifest.json", next_manifest)

    def _write_vault_note(
        self,
        *,
        spec: CompetitionRunSpec,
        topic: TopicCandidate,
        hypothesis: HypothesisProposal,
        protocol: ExperimentProtocol,
        manifest: CycleManifest,
        gate: EvidenceGateReport,
        outcome: CycleOutcome,
    ) -> Path:
        create_vault_layout(self.vault_root, spec.project_id)
        rows = "\n".join(
            f"| {attempt.seed} | {attempt.metrics.get('derivative_nmse', 0.0):.8f} | "
            f"{attempt.metrics.get('equation_structure_f1', 0.0):.4f} |"
            for attempt in manifest.attempts
        )
        body = f"""# Gate A cycle {spec.run_id}

- Topic: `{topic.topic_id}`
- Hypothesis: `{hypothesis.hypothesis_id}`
- Protocol: `{protocol.protocol_id}`
- Outcome: `{outcome.value}`
- Human intervention count: `{manifest.human_intervention_count}`
- Release eligible: `{gate.release_allowed}`

## Executed metrics

| Seed | Derivative NMSE | Equation structure F1 |
| ---: | ---: | ---: |
{rows}

## Evidence boundary

This run used a generated characterization fixture. It validates the unattended causal
chain but does not claim that the official MDBench 10 ODE / 4 PDE Gate A has passed.

## Links

- [[projects/{spec.project_id}/index|Project index]]
"""
        entry = KnowledgeEntry(
            entry_type=KnowledgeEntryType.EXPERIMENT_RECORD,
            zone=KnowledgeZone.PROJECT,
            project_id=spec.project_id,
            title=f"Gate A cycle {spec.run_id}",
            tags=["competition", "gate-a", "mdbench", "development-smoke"],
            keywords=["model discovery", "dynamical systems", "causal manifest"],
            source_refs=list(topic.literature_evidence),
            related_run_ids=[spec.run_id],
            body=body,
        )
        return MarkdownKnowledgeStore(self.vault_root).write_entry(
            Path("projects") / spec.project_id / "experiments" / f"{spec.run_id}.md",
            entry,
        )


def load_capability_grant(path: Path | str) -> CapabilityGrant:
    return CapabilityGrant.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _claims_for_attempts(
    topic: TopicCandidate,
    hypothesis: HypothesisProposal,
    manifest: CycleManifest,
) -> tuple[ClaimBinding, ...]:
    if not manifest.attempts:
        return ()
    return (
        ClaimBinding(
            text=(
                "On the generated characterization fixture, the compiled sparse polynomial "
                "method improved derivative NMSE over its executed constant baseline."
            ),
            topic_id=topic.topic_id,
            hypothesis_id=hypothesis.hypothesis_id,
            metric_name="relative_nmse_improvement",
            attempt_ids=tuple(attempt.attempt_id for attempt in manifest.attempts),
            scope="generated characterization fixture only",
        ),
    )


def _write_summary(
    *,
    cycle_dir: Path,
    spec: CompetitionRunSpec,
    topic: TopicCandidate,
    selection: TopicSelectionReport,
    manifest: CycleManifest,
    gate: EvidenceGateReport,
    outcome: CycleOutcome,
) -> Path:
    path = cycle_dir / "cycle-summary.json"
    write_json_model(
        path,
        {
            "run_id": spec.run_id,
            "project_id": spec.project_id,
            "topic_mode": spec.topic_mode.value,
            "selected_topic_id": topic.topic_id,
            "selection": selection.model_dump(mode="json"),
            "outcome": outcome.value,
            "attempt_count": len(manifest.attempts),
            "human_intervention_count": manifest.human_intervention_count,
            "access_request_count": len(manifest.access_request_ids),
            "evidence_gate": gate.model_dump(mode="json"),
            "release_eligible": gate.release_allowed,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return path


def _write_negative_report(cycle_dir: Path, reason: str) -> Path:
    path = cycle_dir / "negative-result.md"
    path.write_text(
        "# No viable research topic selected\n\n"
        f"Reason: {reason}\n\n"
        "The unattended cycle stopped without requesting a scientific decision.\n",
        encoding="utf-8",
    )
    return path


ModelT = TypeVar("ModelT", bound=BaseModel)


def _load_model(path: Path, model_type: type[ModelT]) -> ModelT:
    return model_type.model_validate_json(path.read_text(encoding="utf-8"))


def _cycle_result(cycle_dir: Path, manifest: CycleManifest) -> CycleResult:
    return CycleResult(
        cycle_dir=cycle_dir.as_posix(),
        manifest_path=(cycle_dir / "cycle-manifest.json").as_posix(),
        evidence_gate_path=manifest.artifact_paths.get("evidence_gate"),
        outcome=manifest.outcome,
        release_eligible=manifest.release_eligible,
        human_intervention_count=manifest.human_intervention_count,
        access_request_count=len(manifest.access_request_ids),
    )


def _validate_run_id(run_id: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", run_id):
        raise ValueError("run_id must be a path-safe identifier")
