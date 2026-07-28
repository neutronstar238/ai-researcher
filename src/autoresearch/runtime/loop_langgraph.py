"""Characterized LangGraph adapter behind the canonical Control Graph runtime."""

from __future__ import annotations

import json
import operator
from importlib.metadata import version
from typing import Annotated, Any, Literal, TypedDict, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import model_validator

from autoresearch.kernel.contracts import KernelContract, Sha256, canonical_sha256
from autoresearch.kernel.loop import (
    ControlGraphRuntime,
    LoopResumeRequest,
    LoopRunSnapshot,
    LoopStartRequest,
)


class LangGraphAdapterPayload(TypedDict, total=False):
    """JSON-safe adapter state; the EventJournal remains canonical."""

    operation: Literal["start", "resume"]
    start_request: dict[str, Any]
    resume_request: dict[str, Any]
    loop_snapshot: dict[str, Any]


class _CharacterizationState(TypedDict, total=False):
    count: int
    trace: Annotated[list[str], operator.add]
    approved: bool


class _LangGraphCharacterizationContent(KernelContract):
    schema_version: Literal[1] = 1
    langgraph_version: str
    langchain_core_version: str
    checkpoint_resume: bool
    static_interrupt: bool
    dynamic_interrupt: bool
    subgraph_execution: bool
    parallel_superstep: bool
    resume_idempotent: bool
    json_state_serializable: bool


class LangGraphCharacterizationReport(_LangGraphCharacterizationContent):
    """Content-addressed behavior baseline required before dependency upgrades."""

    report_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> LangGraphCharacterizationReport:
        expected = self.calculated_hash()
        if self.report_hash != expected:
            raise ValueError(
                f"LangGraph characterization hash mismatch: "
                f"expected {expected}, got {self.report_hash}"
            )
        return self

    @classmethod
    def create(cls, **values: Any) -> LangGraphCharacterizationReport:
        """Validate behavior flags and attach a deterministic digest."""

        content = _LangGraphCharacterizationContent.model_validate(values)
        payload = content.model_dump(mode="json")
        payload["report_hash"] = canonical_sha256(content)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Calculate the report digest without ``report_hash``."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"report_hash"}))

    @property
    def all_passed(self) -> bool:
        """Whether every frozen compatibility behavior was observed."""

        return all(
            (
                self.checkpoint_resume,
                self.static_interrupt,
                self.dynamic_interrupt,
                self.subgraph_execution,
                self.parallel_superstep,
                self.resume_idempotent,
                self.json_state_serializable,
            )
        )


class LangGraphControlAdapter:
    """Thin optional adapter that never replaces journal-derived loop state."""

    def __init__(
        self,
        *,
        runtime: ControlGraphRuntime,
        checkpointer: Any | None = None,
        interrupt_before_drive: bool = False,
        interrupt_after_drive: bool = False,
    ) -> None:
        self.runtime = runtime
        graph = StateGraph(LangGraphAdapterPayload)
        graph.add_node("drive", cast(Any, self._drive))
        graph.add_edge(START, "drive")
        graph.add_edge("drive", END)
        self.graph = graph.compile(
            checkpointer=checkpointer or _strict_memory_saver(),
            interrupt_before=["drive"] if interrupt_before_drive else None,
            interrupt_after=["drive"] if interrupt_after_drive else None,
            name="autoresearch_control_adapter",
        )

    def start(
        self,
        request: LoopStartRequest,
        *,
        thread_id: str,
    ) -> LangGraphAdapterPayload:
        """Submit a domain start request through one checkpointed adapter node."""

        payload: LangGraphAdapterPayload = {
            "operation": "start",
            "start_request": request.model_dump(mode="json"),
        }
        return cast(
            LangGraphAdapterPayload,
            self.graph.invoke(payload, self._config(thread_id)),
        )

    def resume(
        self,
        request: LoopResumeRequest | None = None,
        *,
        thread_id: str,
    ) -> LangGraphAdapterPayload:
        """Submit a domain resume request; journal replay remains authoritative."""

        payload: LangGraphAdapterPayload = {
            "operation": "resume",
            "resume_request": (request or LoopResumeRequest()).model_dump(mode="json"),
        }
        return cast(
            LangGraphAdapterPayload,
            self.graph.invoke(payload, self._config(thread_id)),
        )

    def continue_from_checkpoint(
        self,
        *,
        thread_id: str,
    ) -> LangGraphAdapterPayload:
        """Continue after a static LangGraph interrupt without new domain input."""

        return cast(
            LangGraphAdapterPayload,
            self.graph.invoke(None, self._config(thread_id)),
        )

    def checkpoint_state(self, *, thread_id: str) -> Any:
        """Expose the adapter checkpoint only for characterization and diagnostics."""

        return self.graph.get_state(self._config(thread_id))

    def _drive(self, payload: LangGraphAdapterPayload) -> LangGraphAdapterPayload:
        operation = payload.get("operation")
        if operation == "start":
            raw_request = payload.get("start_request")
            if raw_request is None:
                raise ValueError("LangGraph adapter start request is missing")
            snapshot = self.runtime.start(LoopStartRequest.model_validate(raw_request))
        elif operation == "resume":
            raw_request = payload.get("resume_request", {})
            snapshot = self.runtime.resume(LoopResumeRequest.model_validate(raw_request))
        else:
            raise ValueError(f"unsupported LangGraph adapter operation: {operation}")
        snapshot.verify_integrity()
        serialized = snapshot.model_dump(mode="json")
        json.dumps(serialized, sort_keys=True)
        return {"loop_snapshot": serialized}

    @staticmethod
    def _config(thread_id: str) -> RunnableConfig:
        clean = thread_id.strip()
        if not clean:
            raise ValueError("thread_id must be non-empty")
        return {"configurable": {"thread_id": clean}}


def characterize_installed_langgraph() -> LangGraphCharacterizationReport:
    """Execute a bounded local probe over the currently installed LangGraph."""

    checkpoint_resume, static_interrupt, resume_idempotent, serializable = (
        _characterize_checkpoint_and_interrupt()
    )
    return LangGraphCharacterizationReport.create(
        langgraph_version=version("langgraph"),
        langchain_core_version=version("langchain-core"),
        checkpoint_resume=checkpoint_resume,
        static_interrupt=static_interrupt,
        dynamic_interrupt=_characterize_dynamic_interrupt(),
        subgraph_execution=_characterize_subgraph(),
        parallel_superstep=_characterize_parallel_superstep(),
        resume_idempotent=resume_idempotent,
        json_state_serializable=serializable,
    )


def _characterize_checkpoint_and_interrupt() -> tuple[bool, bool, bool, bool]:
    calls: list[str] = []

    def first(state: _CharacterizationState) -> _CharacterizationState:
        calls.append("first")
        return {
            "count": state.get("count", 0) + 1,
            "trace": ["first"],
        }

    def second(state: _CharacterizationState) -> _CharacterizationState:
        calls.append("second")
        return {
            "count": state.get("count", 0) + 1,
            "trace": ["second"],
        }

    builder = StateGraph(_CharacterizationState)
    builder.add_node("first", first)
    builder.add_node("second", second)
    builder.add_edge(START, "first")
    builder.add_edge("first", "second")
    builder.add_edge("second", END)
    graph = builder.compile(
        checkpointer=_strict_memory_saver(),
        interrupt_after=["first"],
        name="autoresearch_checkpoint_characterization",
    )
    config: RunnableConfig = {"configurable": {"thread_id": "characterize-checkpoint"}}
    first_output = graph.invoke({"count": 0, "trace": []}, config)
    checkpoint = graph.get_state(config)
    final_output = graph.invoke(None, config)
    history = list(graph.get_state_history(config))
    checkpoint_resume = bool(
        first_output.get("trace") == ["first"]
        and final_output.get("trace") == ["first", "second"]
        and final_output.get("count") == 2
        and len(history) >= 3
    )
    static_interrupt = tuple(checkpoint.next) == ("second",)
    resume_idempotent = calls == ["first", "second"]
    serializable_payload = {
        "values": dict(graph.get_state(config).values),
        "next": list(graph.get_state(config).next),
        "history_values": [dict(item.values) for item in history],
    }
    try:
        json.loads(json.dumps(serializable_payload, sort_keys=True))
    except (TypeError, ValueError):
        serializable = False
    else:
        serializable = True
    return checkpoint_resume, static_interrupt, resume_idempotent, serializable


def _characterize_dynamic_interrupt() -> bool:
    def approval_node(
        _state: _CharacterizationState,
    ) -> _CharacterizationState:
        decision = interrupt(
            {
                "approval_id": "approval.characterization",
                "question": "continue",
            }
        )
        return {
            "approved": bool(decision),
            "trace": ["approved" if decision else "rejected"],
        }

    builder = StateGraph(_CharacterizationState)
    builder.add_node("approval", cast(Any, approval_node))
    builder.add_edge(START, "approval")
    builder.add_edge("approval", END)
    graph = builder.compile(
        checkpointer=_strict_memory_saver(),
        name="autoresearch_dynamic_interrupt_characterization",
    )
    config: RunnableConfig = {"configurable": {"thread_id": "characterize-dynamic-interrupt"}}
    paused = graph.invoke({"trace": []}, config)
    checkpoint = graph.get_state(config)
    resumed = graph.invoke(Command(resume=False), config)
    tasks = tuple(checkpoint.tasks)
    return bool(
        paused.get("trace") == []
        and len(tasks) == 1
        and tasks[0].interrupts
        and resumed.get("approved") is False
        and resumed.get("trace") == ["rejected"]
    )


def _characterize_subgraph() -> bool:
    child = StateGraph(_CharacterizationState)
    child.add_node("child", lambda _state: {"trace": ["child"]})
    child.add_edge(START, "child")
    child.add_edge("child", END)

    parent = StateGraph(_CharacterizationState)
    parent.add_node("subgraph", child.compile(name="characterization_child"))
    parent.add_node("after", lambda _state: {"trace": ["after"]})
    parent.add_edge(START, "subgraph")
    parent.add_edge("subgraph", "after")
    parent.add_edge("after", END)
    graph = parent.compile(
        checkpointer=_strict_memory_saver(),
        name="autoresearch_subgraph_characterization",
    )
    output = graph.invoke(
        {"trace": []},
        {"configurable": {"thread_id": "characterize-subgraph"}},
    )
    return output.get("trace") == ["child", "after"]


def _characterize_parallel_superstep() -> bool:
    calls: list[str] = []

    def branch_a(_state: _CharacterizationState) -> _CharacterizationState:
        calls.append("a")
        return {"trace": ["a"]}

    def branch_b(_state: _CharacterizationState) -> _CharacterizationState:
        calls.append("b")
        return {"trace": ["b"]}

    builder = StateGraph(_CharacterizationState)
    builder.add_node("a", cast(Any, branch_a))
    builder.add_node("b", cast(Any, branch_b))
    builder.add_node("join", lambda _state: {"trace": ["join"]})
    builder.add_edge(START, "a")
    builder.add_edge(START, "b")
    builder.add_edge(["a", "b"], "join")
    builder.add_edge("join", END)
    output = builder.compile(name="autoresearch_parallel_characterization").invoke({"trace": []})
    return calls == ["a", "b"] and output.get("trace") == ["a", "b", "join"]


def adapter_snapshot(payload: LangGraphAdapterPayload) -> LoopRunSnapshot:
    """Parse and validate the domain snapshot returned by an adapter invocation."""

    raw = payload.get("loop_snapshot")
    if raw is None:
        raise ValueError("LangGraph adapter invocation has no loop snapshot")
    snapshot = LoopRunSnapshot.model_validate(raw)
    snapshot.verify_integrity()
    return snapshot


def _strict_memory_saver() -> MemorySaver:
    """Use an explicit JSON-safe serializer allowlist for local checkpoints."""

    return MemorySaver(
        serde=JsonPlusSerializer(
            pickle_fallback=False,
            allowed_json_modules=(),
            allowed_msgpack_modules=(),
        )
    )
