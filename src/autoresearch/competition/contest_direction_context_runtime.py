"""Task-scoped context memory for the lightweight direction research loop.

The runtime is deliberately a thin adapter over the existing provider-bound
``AutonomousTaskContextSession``.  It does not own a context-window number and
does not summarize arbitrary workflow state.  Each model stage is an active
task until its runner returns successfully; only calls from earlier completed
stages may enter the 80-percent compaction projection.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from autoresearch.competition.contest_direction_stage_checkpoint import (
    replayable_stage_completion,
)
from autoresearch.config.models import SystemConfig
from autoresearch.config.parser import ConfigParser
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion
from autoresearch.llm.model_capabilities import load_official_model_capability
from autoresearch.llm.task_context import (
    AutonomousTaskContextCompletion,
    AutonomousTaskContextSession,
)

CompletionCallable = Callable[..., LLMJsonCompletionResult]

_SAFE_STAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ContestDirectionContextRuntime:
    """Give every Qwen stage one explicit active-task boundary.

    ``AutonomousTaskContextSession`` resolves the configured provider/model on
    every actual call and derives its trigger from the verified official model
    capability cache.  This adapter therefore accepts no token-limit override.
    Exact request/response transcripts remain in the sovereign raw-memory
    store; the session directory contains only hash-bound completed-task and
    rebuildable context-preparation projections.
    """

    def __init__(
        self,
        *,
        direction_id: str,
        output_dir: Path | str,
        vault_root: Path | str = Path("autoresearch-vault"),
        completion: CompletionCallable = run_llm_json_completion,
        capability_cache_dir: Path | str = Path(".cache/autoresearch/model-capabilities"),
    ) -> None:
        if not _SAFE_STAGE_ID.fullmatch(direction_id):
            raise ValueError("direction_id is not a safe context-session identifier")
        self.direction_id = direction_id
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.capability_cache_dir = Path(capability_cache_dir)
        self.vault_root = Path(vault_root)
        self._provider_completion = completion
        self.session = AutonomousTaskContextSession(
            project_id=direction_id,
            conversation_id=f"{direction_id}-lightweight-loop",
            output_dir=self.output_dir,
            vault_root=vault_root,
            completion=completion,
            cache_dir=self.capability_cache_dir,
        )

    @contextmanager
    def stage(
        self,
        stage_name: str,
        *,
        input_hash: str | None = None,
    ) -> Iterator[AutonomousTaskContextCompletion]:
        """Keep one model stage active until all of its calls finish successfully."""

        stage_id = self.stage_task_id(stage_name, input_hash=input_hash)
        with self.session.task(stage_id) as completion:
            yield completion

    @contextmanager
    def checkpointed_stage(
        self,
        stage_name: str,
        *,
        input_hash: str,
        checkpoint_root: Path | str,
    ) -> Iterator[AutonomousTaskContextCompletion]:
        """Put task context outside the durable provider-response escrow.

        The order is ``stage -> context -> escrow -> provider``.  Consequently,
        a crash after the escrow write but before stage materialization can replay
        the exact provider result locally *through* the context layer, capture its
        raw transcript, and promote it into completed history without a second
        provider request.
        """

        stage_id = self.stage_task_id(stage_name, input_hash=input_hash)
        checkpointed_provider = replayable_stage_completion(
            root=checkpoint_root,
            stage_name=stage_name,
            stage_input_hash=input_hash,
            completion=self._provider_completion,
        )
        session = AutonomousTaskContextSession(
            project_id=self.direction_id,
            conversation_id=f"{self.direction_id}-lightweight-loop",
            output_dir=self.output_dir,
            vault_root=self.vault_root,
            completion=checkpointed_provider,
            cache_dir=self.capability_cache_dir,
        )
        with session.task(stage_id) as completion:
            completion._autoresearch_provider_checkpoint_owner = True
            yield completion

    @staticmethod
    def stage_task_id(stage_name: str, *, input_hash: str | None = None) -> str:
        """Derive a stable task ID without asking a model to invent an ID."""

        if not _SAFE_STAGE_ID.fullmatch(stage_name):
            raise ValueError("stage_name is not a safe context task identifier")
        if input_hash is None:
            return stage_name
        if not _SHA256.fullmatch(input_hash):
            raise ValueError("stage input_hash must be a canonical SHA-256 value")
        return f"{stage_name}-{input_hash[:16]}"

    def verify_official_capability(
        self,
        *,
        config_path: Path | str = Path("config.yaml"),
    ) -> dict[str, object]:
        """Resolve the configured model through the official capability source.

        Call this before any non-model source-reuse branch so a fresh lightweight
        run cannot silently skip the same fail-closed model-limit provenance that
        normal context-managed calls enforce.
        """

        path = Path(config_path)
        config = (
            ConfigParser().parse_file(path, model_type=SystemConfig)
            if path.is_file()
            else SystemConfig()
        )
        if not isinstance(config, SystemConfig):
            raise ValueError("context runtime could not load SystemConfig")
        llm = config.deployment.llm
        capability = load_official_model_capability(
            provider=llm.provider,
            model_name=llm.model_name,
            cache_dir=self.capability_cache_dir,
        )
        return {
            "provider": capability.provider,
            "model_name": capability.model_name,
            "official_source_url": capability.official_source_url,
            "capability_hash": capability.capability_hash,
            "context_window_tokens": capability.context_window_tokens,
        }


__all__ = ["ContestDirectionContextRuntime"]
