"""Dynamic, auditable routing of project-local ``SKILL.md`` methodology.

The router sees only compact skill metadata.  It may select zero or more skills
for the next adaptive research turn, after which the exact selected files are
injected as separate user messages by :mod:`adaptive_sovereign_loop`.  The
generic controller prompt therefore never accumulates discipline-specific
methods, and a skill is never mistaken for literature or experimental evidence.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, field_validator, model_validator

from autoresearch.kernel.contracts import (
    KernelContract,
    Sha256,
    StableId,
    canonical_json,
    canonical_sha256,
)
from autoresearch.knowledge.raw_memory import (
    RawMemoryBinding,
    RawMemorySourceKind,
    RawMemoryStore,
)
from autoresearch.llm.client import LLMJsonCompletionResult, run_llm_json_completion
from autoresearch.research.adaptive_sovereign_loop import (
    AdaptiveResearchBranch,
    AdaptiveResearchLoopError,
    AdaptiveResearchLoopSnapshot,
    AdaptiveResearchSeed,
    LoopSkillContext,
)

CompletionCallable = Callable[..., LLMJsonCompletionResult]

_MIN_REASONING_CHARACTERS = 200
_MAX_CATALOG_SKILLS = 256


class AdaptiveSkillRoutingError(AdaptiveResearchLoopError):
    """Raised when dynamic methodology routing cannot be reproduced exactly."""


class RepositorySkillMetadata(KernelContract):
    """Compact non-evidence metadata shown to the routing model."""

    skill_id: StableId
    description: str = Field(min_length=20, max_length=4_000)
    source_relative_path: str = Field(min_length=1, max_length=1_024)
    content_sha256: Sha256
    content_character_count: int = Field(ge=1, le=80_000)
    is_scientific_evidence: Literal[False] = False


class _AdaptiveSkillSelectionFields(KernelContract):
    """Fields shared by the retained v1 wire shape and the current contract."""

    step_index: int = Field(ge=1)
    branch_id: StableId
    task_classification_cn: str = Field(min_length=20, max_length=2_000)
    selected_skill_ids: list[StableId] = Field(max_length=12)
    selection_rationale_cn: str = Field(min_length=30, max_length=4_000)
    generated_hypothesis: Literal[False] = False
    generated_method_answer: Literal[False] = False
    generated_research_plan: Literal[False] = False
    is_scientific_evidence: Literal[False] = False

    @field_validator("task_classification_cn", "selection_rationale_cn")
    @classmethod
    def _require_chinese(cls, value: str) -> str:
        normalized = value.strip()
        if not any("\u3400" <= char <= "\u9fff" for char in normalized):
            raise ValueError("adaptive skill routing prose must contain Chinese")
        return normalized

    @field_validator("selected_skill_ids")
    @classmethod
    def _require_unique_ids(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized) or len(normalized) != len(set(normalized)):
            raise ValueError("adaptive skill routing IDs must be unique and non-empty")
        return normalized


class AdaptiveSkillSelectionDraftV1(_AdaptiveSkillSelectionFields):
    """Retained reader for old artifacts with a redundant negative-polarity flag."""

    schema_version: Literal["adaptive-skill-selection-v1"] = (
        "adaptive-skill-selection-v1"
    )
    no_skill_required: bool

    @model_validator(mode="after")
    def _validate_partition_shape(self) -> AdaptiveSkillSelectionDraftV1:
        if self.no_skill_required != (not self.selected_skill_ids):
            raise ValueError("no_skill_required must match an empty selection")
        return self


class AdaptiveSkillSelectionDraft(_AdaptiveSkillSelectionFields):
    """Current model-authored applicability decision with one authoritative list."""

    schema_version: Literal["adaptive-skill-selection-v2"] = (
        "adaptive-skill-selection-v2"
    )


class AdaptiveSkillRoutingArtifact(KernelContract):
    """Immutable receipt for one metadata-only routing decision."""

    schema_version: Literal["adaptive-skill-routing-artifact-v1"] = (
        "adaptive-skill-routing-artifact-v1"
    )
    loop_id: StableId
    project_id: StableId
    step_index: int = Field(ge=1)
    branch_id: StableId
    catalog: list[RepositorySkillMetadata] = Field(max_length=_MAX_CATALOG_SKILLS)
    catalog_hash: Sha256
    messages: list[dict[str, str]] = Field(min_length=2)
    messages_sha256: Sha256
    selection: AdaptiveSkillSelectionDraft | AdaptiveSkillSelectionDraftV1
    rejected_skill_ids: list[StableId]
    selected_content_hashes: dict[str, Sha256]
    response_binding: RawMemoryBinding
    reasoning_binding: RawMemoryBinding
    reasoning_character_count: int = Field(ge=_MIN_REASONING_CHARACTERS)
    provider: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    created_at: datetime
    artifact_hash: Sha256
    scientific_content_generated: Literal[False] = False
    is_scientific_evidence: Literal[False] = False
    execution_authorized: Literal[False] = False
    publication_authorized: Literal[False] = False

    @model_validator(mode="after")
    def _validate_hashes_and_partition(self) -> AdaptiveSkillRoutingArtifact:
        if self.catalog_hash != canonical_sha256(
            [item.model_dump(mode="json") for item in self.catalog]
        ):
            raise ValueError("adaptive skill catalog hash mismatch")
        if self.messages_sha256 != canonical_sha256(self.messages):
            raise ValueError("adaptive skill routing message hash mismatch")
        catalog_ids = [item.skill_id for item in self.catalog]
        if len(catalog_ids) != len(set(catalog_ids)):
            raise ValueError("adaptive skill catalog repeats a skill ID")
        accounted = [
            *self.selection.selected_skill_ids,
            *self.rejected_skill_ids,
        ]
        if len(accounted) != len(set(accounted)) or set(accounted) != set(catalog_ids):
            raise ValueError("adaptive skill selection must partition the catalog")
        if self.selection.step_index != self.step_index:
            raise ValueError("adaptive skill routing step mismatch")
        if self.selection.branch_id != self.branch_id:
            raise ValueError("adaptive skill routing branch mismatch")
        expected_selected = {
            item.skill_id: item.content_sha256
            for item in self.catalog
            if item.skill_id in self.selection.selected_skill_ids
        }
        if self.selected_content_hashes != expected_selected:
            raise ValueError("adaptive selected skill hashes mismatch")
        expected_hash = canonical_sha256(
            self.model_dump(mode="json", exclude={"artifact_hash"})
        )
        if self.artifact_hash != expected_hash:
            raise ValueError("adaptive skill routing artifact hash mismatch")
        return self

    @classmethod
    def create(cls, **values: Any) -> AdaptiveSkillRoutingArtifact:
        provisional = cls.model_construct(**values, artifact_hash="0" * 64)
        payload = provisional.model_dump(mode="json", exclude={"artifact_hash"})
        payload["artifact_hash"] = canonical_sha256(payload)
        return cls.model_validate(payload)


class _LoadedRepositorySkill(KernelContract):
    metadata: RepositorySkillMetadata
    content: str = Field(min_length=1, max_length=80_000)

    @model_validator(mode="after")
    def _verify_content(self) -> _LoadedRepositorySkill:
        if hashlib.sha256(self.content.encode("utf-8")).hexdigest() != (
            self.metadata.content_sha256
        ):
            raise ValueError("repository skill content hash mismatch")
        return self


class RepositoryQwenSkillProvider:
    """Select project skills dynamically and retain exact Qwen routing receipts.

    The provider is callable with the legacy ``SkillProvider`` signature used by
    the adaptive loop.  ``required_model_calls`` and ``last_model_call_count``
    let the outer controller count routing calls in the same global model budget.
    A completed step is replayed from its immutable artifact without another
    provider request.
    """

    def __init__(
        self,
        *,
        skill_root: Path | str,
        output_dir: Path | str,
        raw_memory_store: RawMemoryStore,
        completion: CompletionCallable = run_llm_json_completion,
        config_path: Path | str = Path("config.yaml"),
        env_path: Path | str = Path(".env"),
        maximum_selected_skills: int = 5,
        maximum_selected_characters: int = 100_000,
        thinking_budget: int = 2_000,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not 0 <= maximum_selected_skills <= 12:
            raise AdaptiveSkillRoutingError("maximum selected skills is outside bounds")
        if maximum_selected_characters < 1:
            raise AdaptiveSkillRoutingError("selected skill character budget must be positive")
        if thinking_budget < 256 or thinking_budget > 32_000:
            raise AdaptiveSkillRoutingError("skill routing thinking budget is outside bounds")
        self._skills = _load_repository_skills(skill_root)
        self._output_root = Path(output_dir).resolve()
        self._raw_memory_store = raw_memory_store
        self._completion = completion
        self._config_path = Path(config_path)
        self._env_path = Path(env_path)
        self._maximum_selected_skills = maximum_selected_skills
        self._maximum_selected_characters = maximum_selected_characters
        self._thinking_budget = thinking_budget
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.last_model_call_count = 0

    def required_model_calls(
        self,
        *,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
        branch: AdaptiveResearchBranch,
    ) -> int:
        del seed, branch
        return 0 if self._artifact_path(snapshot.next_step_index).is_file() else 1

    def __call__(
        self,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
        branch: AdaptiveResearchBranch,
    ) -> Sequence[LoopSkillContext]:
        artifact_path = self._artifact_path(snapshot.next_step_index)
        if artifact_path.is_file():
            self.last_model_call_count = 0
            artifact = self._load_artifact(
                artifact_path,
                seed=seed,
                snapshot=snapshot,
                branch=branch,
            )
            return self._materialize(artifact.selection.selected_skill_ids)

        catalog = [skill.metadata for skill in self._skills]
        messages = _routing_messages(
            seed=seed,
            snapshot=snapshot,
            branch=branch,
            catalog=catalog,
            maximum_selected_skills=self._maximum_selected_skills,
            maximum_selected_characters=self._maximum_selected_characters,
        )
        result = self._completion(
            messages=messages,
            config_path=self._config_path,
            env_path=self._env_path,
            timeout_seconds=300,
            max_tokens=4_000,
            temperature=0.1,
            thinking_mode="enabled",
            thinking_budget=self._thinking_budget,
            response_schema=_skill_selection_response_schema(
                catalog,
                maximum_selected_skills=self._maximum_selected_skills,
            ),
            response_schema_name="adaptive_skill_selection",
        )
        self.last_model_call_count = 1
        captured_at = self._clock().astimezone(timezone.utc)
        response_capture = self._raw_memory_store.capture_text(
            result.response_text,
            project_id=seed.project_id,
            source_kind=RawMemorySourceKind.MODEL_TRANSCRIPT,
            source_label="自适应科研技能路由可见响应",
            source_ref=(
                f"adaptive-loop:{seed.loop_id}:skill-routing:"
                f"{snapshot.next_step_index}:response"
            ),
            original_name=f"skill-routing-step-{snapshot.next_step_index:04d}-response.json",
            source_authorized=True,
            sensitive_content_reviewed=True,
            captured_at=captured_at,
        )
        reasoning = str(result.reasoning_text or "").strip()
        reasoning_capture = self._raw_memory_store.capture_text(
            reasoning or "技能路由未返回可用思考过程。",
            project_id=seed.project_id,
            source_kind=RawMemorySourceKind.MODEL_TRANSCRIPT,
            source_label="自适应科研技能路由有界思考",
            source_ref=(
                f"adaptive-loop:{seed.loop_id}:skill-routing:"
                f"{snapshot.next_step_index}:reasoning"
            ),
            original_name=f"skill-routing-step-{snapshot.next_step_index:04d}-reasoning.txt",
            source_authorized=True,
            sensitive_content_reviewed=True,
            captured_at=captured_at,
        )
        if len(reasoning) < _MIN_REASONING_CHARACTERS:
            raise AdaptiveSkillRoutingError(
                "configured model did not return 200 characters of skill-routing reasoning"
            )
        try:
            visible_payload = json.loads(result.response_text)
        except json.JSONDecodeError as exc:
            raise AdaptiveSkillRoutingError(
                "adaptive skill routing response is not exact JSON"
            ) from exc
        if visible_payload != result.parsed_json:
            raise AdaptiveSkillRoutingError(
                "visible skill-routing response differs from the parsed payload"
            )
        selection = AdaptiveSkillSelectionDraft.model_validate(result.parsed_json)
        _validate_selection(
            selection,
            step_index=snapshot.next_step_index,
            branch_id=branch.branch_id,
            skills=self._skills,
            maximum_selected_skills=self._maximum_selected_skills,
            maximum_selected_characters=self._maximum_selected_characters,
        )
        selected_hashes = {
            skill.metadata.skill_id: skill.metadata.content_sha256
            for skill in self._skills
            if skill.metadata.skill_id in selection.selected_skill_ids
        }
        rejected_skill_ids = [
            skill.metadata.skill_id
            for skill in self._skills
            if skill.metadata.skill_id not in selection.selected_skill_ids
        ]
        artifact = AdaptiveSkillRoutingArtifact.create(
            loop_id=seed.loop_id,
            project_id=seed.project_id,
            step_index=snapshot.next_step_index,
            branch_id=branch.branch_id,
            catalog=catalog,
            catalog_hash=canonical_sha256(
                [item.model_dump(mode="json") for item in catalog]
            ),
            messages=messages,
            messages_sha256=canonical_sha256(messages),
            selection=selection,
            rejected_skill_ids=rejected_skill_ids,
            selected_content_hashes=selected_hashes,
            response_binding=response_capture.binding(
                self._raw_memory_store.vault_root
            ),
            reasoning_binding=reasoning_capture.binding(
                self._raw_memory_store.vault_root
            ),
            reasoning_character_count=len(reasoning),
            provider=result.provider,
            model_name=result.model_name,
            created_at=captured_at,
        )
        _write_once(
            artifact_path,
            (canonical_json(artifact) + "\n").encode("utf-8"),
        )
        return self._materialize(selection.selected_skill_ids)

    def _artifact_path(self, step_index: int) -> Path:
        return (
            self._output_root
            / "skill-routing"
            / f"step-{step_index:04d}"
            / "adaptive-skill-routing.json"
        )

    def _load_artifact(
        self,
        path: Path,
        *,
        seed: AdaptiveResearchSeed,
        snapshot: AdaptiveResearchLoopSnapshot,
        branch: AdaptiveResearchBranch,
    ) -> AdaptiveSkillRoutingArtifact:
        try:
            raw = path.read_bytes()
            artifact = AdaptiveSkillRoutingArtifact.model_validate_json(raw)
        except (OSError, ValueError) as exc:
            raise AdaptiveSkillRoutingError(
                f"cannot load adaptive skill routing artifact: {exc}"
            ) from exc
        if raw != (canonical_json(artifact) + "\n").encode("utf-8"):
            raise AdaptiveSkillRoutingError("adaptive skill routing JSON is not canonical")
        if (
            artifact.loop_id != seed.loop_id
            or artifact.project_id != seed.project_id
            or artifact.step_index != snapshot.next_step_index
            or artifact.branch_id != branch.branch_id
        ):
            raise AdaptiveSkillRoutingError("adaptive skill routing context mismatch")
        current_catalog = [skill.metadata for skill in self._skills]
        if artifact.catalog != current_catalog:
            raise AdaptiveSkillRoutingError("repository skills changed after routing")
        _verify_raw_binding(
            self._raw_memory_store,
            artifact.response_binding,
            project_id=seed.project_id,
        )
        _verify_raw_binding(
            self._raw_memory_store,
            artifact.reasoning_binding,
            project_id=seed.project_id,
        )
        _validate_selection(
            artifact.selection,
            step_index=snapshot.next_step_index,
            branch_id=branch.branch_id,
            skills=self._skills,
            maximum_selected_skills=self._maximum_selected_skills,
            maximum_selected_characters=self._maximum_selected_characters,
        )
        return artifact

    def _materialize(self, selected_ids: Sequence[str]) -> list[LoopSkillContext]:
        by_id = {skill.metadata.skill_id: skill for skill in self._skills}
        return [
            LoopSkillContext(
                skill_id=skill_id,
                source_ref=by_id[skill_id].metadata.source_relative_path,
                content=by_id[skill_id].content,
                content_sha256=by_id[skill_id].metadata.content_sha256,
            )
            for skill_id in selected_ids
        ]


def load_repository_skill_contexts(
    skill_root: Path | str,
    selected_skill_ids: Sequence[str],
) -> list[LoopSkillContext]:
    """Load an exact, ordered subset for a main-agent temporary dispatch.

    The caller supplies only IDs already selected by the current main-agent
    turn.  This helper performs the same path, frontmatter, and content-hash
    checks as the routing provider, while deliberately allowing an empty
    selection instead of forcing an unrelated methodology into a task.
    """

    normalized = [item.strip() for item in selected_skill_ids]
    if any(not item for item in normalized) or len(normalized) != len(set(normalized)):
        raise AdaptiveSkillRoutingError(
            "temporary dispatch skill IDs must be unique and non-empty"
        )
    skills = _load_repository_skills(skill_root)
    by_id = {skill.metadata.skill_id: skill for skill in skills}
    unknown = [skill_id for skill_id in normalized if skill_id not in by_id]
    if unknown:
        raise AdaptiveSkillRoutingError(
            f"temporary dispatch references unknown skills: {unknown}"
        )
    return [
        LoopSkillContext(
            skill_id=skill_id,
            source_ref=by_id[skill_id].metadata.source_relative_path,
            content=by_id[skill_id].content,
            content_sha256=by_id[skill_id].metadata.content_sha256,
        )
        for skill_id in normalized
    ]


def _load_repository_skills(skill_root: Path | str) -> list[_LoadedRepositorySkill]:
    root = Path(skill_root).resolve()
    if not root.is_dir():
        raise AdaptiveSkillRoutingError(f"repository skill root is absent: {root}")
    loaded: list[_LoadedRepositorySkill] = []
    for directory in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if not directory.is_dir() or directory.is_symlink():
            continue
        path = directory / "SKILL.md"
        if not path.is_file() or path.is_symlink():
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise AdaptiveSkillRoutingError("repository skill escapes its root")
        content = resolved.read_text(encoding="utf-8")
        frontmatter = _parse_frontmatter(content, path=resolved)
        skill_id = str(frontmatter.get("name") or "").strip()
        description = str(frontmatter.get("description") or "").strip()
        if skill_id != directory.name:
            raise AdaptiveSkillRoutingError(
                "repository skill directory and frontmatter name differ"
            )
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        loaded.append(
            _LoadedRepositorySkill(
                metadata=RepositorySkillMetadata(
                    skill_id=skill_id,
                    description=description,
                    source_relative_path=(
                        Path(root.name) / directory.name / "SKILL.md"
                    ).as_posix(),
                    content_sha256=digest,
                    content_character_count=len(content),
                ),
                content=content,
            )
        )
    if not loaded:
        raise AdaptiveSkillRoutingError("repository skill catalog is empty")
    if len(loaded) > _MAX_CATALOG_SKILLS:
        raise AdaptiveSkillRoutingError("repository skill catalog exceeds the safe limit")
    return loaded


def _parse_frontmatter(text: str, *, path: Path) -> Mapping[str, Any]:
    lines = text.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        raise AdaptiveSkillRoutingError(f"SKILL.md lacks YAML frontmatter: {path}")
    try:
        stop = next(
            index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"
        )
    except StopIteration as exc:
        raise AdaptiveSkillRoutingError(
            f"SKILL.md frontmatter is not closed: {path}"
        ) from exc
    parsed = yaml.safe_load("\n".join(lines[1:stop]))
    if not isinstance(parsed, Mapping):
        raise AdaptiveSkillRoutingError(f"SKILL.md frontmatter is invalid: {path}")
    return parsed


def _routing_messages(
    *,
    seed: AdaptiveResearchSeed,
    snapshot: AdaptiveResearchLoopSnapshot,
    branch: AdaptiveResearchBranch,
    catalog: Sequence[RepositorySkillMetadata],
    maximum_selected_skills: int,
    maximum_selected_characters: int,
) -> list[dict[str, str]]:
    instruction = (
        "你是自主科研循环的通用方法技能路由器。你只能判断哪些 SKILL.md 方法论适用于"
        "下一次动作，不能提出研究假设、具体方法答案、实验方案、结果或研究计划。技能可以"
        "选择零个；不得为了凑数强制选择。请比较全部元数据，只返回需要注入的 selected；"
        "selected_skill_ids 的空列表本身就表示本轮无需技能，不要再输出含否定语义的冗余布尔字段。"
        "未入选集合由编排器按目录补集机械生成，避免让格式账本干扰方法判断。只依据当前"
        "任务和分支选择，不把技能当成文献、事实或证据。"
        "reasoning_content 中完成逐项适用性比较并保留至少二百字符，但它不是科学证据。"
        "可见 JSON 的说明字段全部使用简体中文，并严格符合 JSON Schema。"
    )
    recent_feedback = [
        {
            "operator": event.interaction.proposal.operator.value,
            "status": event.feedback.status.value,
            "summary_cn": event.feedback.summary_cn,
            "findings_cn": event.feedback.findings_cn,
        }
        for event in snapshot.events[-4:]
    ]
    payload = {
        "context_kind": "adaptive_skill_metadata_routing",
        "step_index": snapshot.next_step_index,
        "branch_id": branch.branch_id,
        "objective_cn": seed.objective_cn,
        "scope_cn": seed.scope_cn,
        "branch_title_cn": branch.title_cn,
        "working_hypothesis_cn": branch.working_hypothesis_cn,
        "recent_external_feedback": recent_feedback,
        "maximum_selected_skills": maximum_selected_skills,
        "maximum_selected_characters": maximum_selected_characters,
        "available_skill_metadata": [item.model_dump(mode="json") for item in catalog],
    }
    return [
        {"role": "system", "content": instruction},
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
        },
    ]


def _skill_selection_response_schema(
    catalog: Sequence[RepositorySkillMetadata],
    *,
    maximum_selected_skills: int,
) -> dict[str, Any]:
    """Make invalid catalog IDs and the retired polarity flag unrepresentable."""

    schema = AdaptiveSkillSelectionDraft.model_json_schema()
    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise AdaptiveSkillRoutingError("adaptive skill selection schema is malformed")
    schema_version = properties.get("schema_version")
    selected = properties.get("selected_skill_ids")
    if not isinstance(schema_version, dict) or not isinstance(selected, dict):
        raise AdaptiveSkillRoutingError("adaptive skill selection schema lacks core fields")
    if "no_skill_required" in properties:
        raise AdaptiveSkillRoutingError("adaptive skill selection schema retained polarity drift")
    schema_version["const"] = "adaptive-skill-selection-v2"
    selected["items"] = {
        "enum": [item.skill_id for item in catalog],
        "type": "string",
    }
    selected["maxItems"] = maximum_selected_skills
    for field_name in ("schema_version", "selected_skill_ids"):
        if field_name not in required:
            required.append(field_name)
    return schema


def _validate_selection(
    selection: AdaptiveSkillSelectionDraft | AdaptiveSkillSelectionDraftV1,
    *,
    step_index: int,
    branch_id: str,
    skills: Sequence[_LoadedRepositorySkill],
    maximum_selected_skills: int,
    maximum_selected_characters: int,
) -> None:
    if selection.step_index != step_index or selection.branch_id != branch_id:
        raise AdaptiveSkillRoutingError("adaptive skill selection context mismatch")
    catalog_ids = {skill.metadata.skill_id for skill in skills}
    unknown = sorted(set(selection.selected_skill_ids) - catalog_ids)
    if unknown:
        raise AdaptiveSkillRoutingError(
            f"adaptive skill selection references unknown skills: {unknown}"
        )
    if len(selection.selected_skill_ids) > maximum_selected_skills:
        raise AdaptiveSkillRoutingError("adaptive skill selection exceeds the count budget")
    selected = set(selection.selected_skill_ids)
    selected_characters = sum(
        len(skill.content)
        for skill in skills
        if skill.metadata.skill_id in selected
    )
    if selected_characters > maximum_selected_characters:
        raise AdaptiveSkillRoutingError(
            "adaptive skill selection exceeds the context character budget"
        )


def _verify_raw_binding(
    store: RawMemoryStore,
    binding: RawMemoryBinding,
    *,
    project_id: str,
) -> None:
    capture = store.load_record(binding.record_relative_path, project_id=project_id)
    observed = (
        capture.record.record_id,
        capture.record.record_hash,
        capture.record.envelope.payload_sha256,
    )
    expected = (binding.record_id, binding.record_hash, binding.payload_sha256)
    if observed != expected:
        raise AdaptiveSkillRoutingError("adaptive skill routing raw-memory mismatch")


def _write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
    except FileExistsError:
        if path.read_bytes() != payload:
            raise AdaptiveSkillRoutingError(
                f"immutable adaptive skill routing artifact changed: {path}"
            ) from None


__all__ = [
    "AdaptiveSkillRoutingArtifact",
    "AdaptiveSkillRoutingError",
    "AdaptiveSkillSelectionDraft",
    "AdaptiveSkillSelectionDraftV1",
    "RepositoryQwenSkillProvider",
    "RepositorySkillMetadata",
    "load_repository_skill_contexts",
]
