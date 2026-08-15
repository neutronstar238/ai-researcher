"""Narrow adapters from web contracts to existing frozen project services."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any


class ContestDirectionSkillEvolutionAdapter:
    """Invoke the evidence-to-Skill shadow pipeline without activating a Skill."""

    def __init__(
        self,
        *,
        skills_root: Path | str = Path("skills"),
        runner: Callable[..., Any] | None = None,
    ) -> None:
        self.skills_root = Path(skills_root).expanduser().resolve()
        self._runner = runner

    def evolve_run(
        self,
        *,
        run_id: str,
        delivery_root: Path,
        vault_root: Path,
        config_path: Path,
        env_path: Path,
    ) -> Mapping[str, Any]:
        del vault_root  # Raw memory remains owned by the completed direction run.
        runner = self._runner
        if runner is None:
            from autoresearch.competition.contest_direction_skill_evolution import (
                run_evidence_to_skill_evolution,
            )

            runner = run_evidence_to_skill_evolution
        result = runner(
            delivery_dir=delivery_root,
            output_dir=delivery_root.parent / "evolution" / "service",
            skills_root=self.skills_root,
            config_path=config_path,
            env_path=env_path,
        )
        artifact = result.artifact
        return {
            "status": artifact.candidate_status,
            "run_id": run_id,
            "candidate_skill_id": artifact.candidate_skill_id,
            "parent_skill_id": artifact.parent_skill_id,
            "promotion_eligible": artifact.promotion_eligible,
            "production_enabled": artifact.production_enabled,
            "active_skill_written": artifact.active_skill_written,
            "development_validation_passed": artifact.development_validation_passed,
            "heldout_validation_passed": artifact.heldout_validation_passed,
            "artifact_hash": artifact.artifact_hash,
            "artifact_path": Path(result.artifact_path).as_posix(),
            "report_path": Path(result.report_path).as_posix(),
            "candidate_skill_dir": Path(result.candidate_skill_dir).as_posix(),
            "resumed_existing": result.resumed_existing,
            "promotion_authorized": False,
        }


class Science125BatchAdapter:
    """Delegate PDF-derived batch work to the repository's stable batch service."""

    def __init__(
        self,
        *,
        skills_root: Path | str = Path("skills"),
        runner: Callable[..., Mapping[str, Any]] | None = None,
        min_interval_seconds: float = 1.0,
    ) -> None:
        self.skills_root = Path(skills_root).expanduser().resolve()
        self._runner = runner
        self.min_interval_seconds = min_interval_seconds

    def submit_batch(
        self,
        *,
        question_pdf: Path,
        output_root: Path,
        start: int,
        limit: int,
        include_question_ids: Sequence[int],
        resume: bool,
        dry_run: bool,
        config_path: Path,
        env_path: Path,
        preexperiment_policy: str,
        dreaming_recall_enabled: bool,
    ) -> Mapping[str, Any]:
        runner = self._runner
        if runner is None:
            module = importlib.import_module("autoresearch.competition.science125_batch")
            loaded = module.__dict__.get("run_science125_batch")
            if not callable(loaded):  # pragma: no cover - malformed installation
                raise RuntimeError("science125 batch entrypoint is not callable")
            runner = loaded
        return runner(
            question_pdf=question_pdf,
            output_root=output_root / "delivery",
            start=start,
            limit=limit,
            include_question_ids=tuple(include_question_ids),
            resume=resume,
            dry_run=dry_run,
            min_interval_seconds=self.min_interval_seconds,
            preexperiment_policy=preexperiment_policy,
            dreaming_recall_enabled=dreaming_recall_enabled,
            config_path=config_path,
            env_path=env_path,
            skills_root=self.skills_root,
        )


__all__ = ["ContestDirectionSkillEvolutionAdapter", "Science125BatchAdapter"]
