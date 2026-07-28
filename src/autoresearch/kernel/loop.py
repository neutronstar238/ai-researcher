"""Versioned LoopSpec contracts and a journal-backed deterministic Control Graph."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Annotated, Any, Literal, Protocol

from pydantic import (
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)

from .contracts import (
    ActorKind,
    ControlCyclePolicy,
    EventActor,
    EventStatus,
    GraphEdge,
    GraphNode,
    GraphPlane,
    GraphSnapshot,
    KernelContract,
    RunEvent,
    Sha256,
    StableId,
    canonical_sha256,
)
from .harness import EpisodeOutcomeStatus, EpisodePackage
from .journal import (
    EventJournal,
    JournalRecoveryRequired,
    JournalSnapshot,
    SensitiveContentError,
    validate_persistable_content,
)

LoopText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=12_000),
]
LoopVersion = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.+-]*$",
    ),
]
FailureCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[a-z][a-z0-9_.-]*$",
    ),
]


class LoopSpecIntegrityError(ValueError):
    """Raised when a loaded or mutated LoopSpec no longer matches its digest."""


class LoopRuntimeError(RuntimeError):
    """Raised when a Control Graph cannot safely start, resume, or replay."""


class LoopReplayError(LoopRuntimeError):
    """Raised when journal events are valid bytes but invalid Loop semantics."""


class LoopNodeKind(str, Enum):
    """Domain-level node roles without binding to one graph runtime."""

    START = "start"
    ACTION = "action"
    APPROVAL = "approval"
    GATE = "gate"
    PIVOT = "pivot"
    COMPENSATION = "compensation"
    SUBGRAPH = "subgraph"
    TERMINAL = "terminal"


class LoopEdgeKind(str, Enum):
    """Explicit transition purposes in a frozen Control Graph."""

    NEXT = "next"
    RETRY = "retry"
    PIVOT = "pivot"
    REJECT = "reject"
    COMPENSATE = "compensate"
    ESCALATE = "escalate"
    STOP = "stop"


class LoopGuardKind(str, Enum):
    """Portable deterministic guard predicates evaluated with AND semantics."""

    ALWAYS = "always"
    OUTCOME = "outcome"
    APPROVAL_DECISION = "approval_decision"
    MECHANISM_CHANGED = "mechanism_changed"
    HOLDOUT_STATE = "holdout_state"


class LoopNodeOutcome(str, Enum):
    """One node invocation's factual outcome."""

    SUCCEEDED = "succeeded"
    NEGATIVE_RESULT = "negative_result"
    FAILED = "failed"
    BLOCKED = "blocked"


class LoopRunStatus(str, Enum):
    """Durable lifecycle states for one frozen graph version."""

    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    NEGATIVE_RESULT = "negative_result"
    FAILED = "failed"
    BLOCKED = "blocked"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    ESCALATED = "escalated"


TERMINAL_LOOP_STATUSES = frozenset(
    {
        LoopRunStatus.SUCCEEDED,
        LoopRunStatus.NEGATIVE_RESULT,
        LoopRunStatus.FAILED,
        LoopRunStatus.BLOCKED,
        LoopRunStatus.REJECTED,
        LoopRunStatus.CANCELLED,
        LoopRunStatus.ESCALATED,
    }
)


class HoldoutState(str, Enum):
    """Visibility of a scientific holdout relative to adaptive work."""

    SEALED = "sealed"
    REVEALED = "revealed"


class LoopApprovalDecision(str, Enum):
    """Explicit human decision consumed by a permission-gated node."""

    APPROVED = "approved"
    REJECTED = "rejected"


class LoopUsage(KernelContract):
    """Resources charged by one node execution."""

    tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)
    wall_time_seconds: float = Field(default=0.0, ge=0.0)
    tool_calls: int = Field(default=0, ge=0)


class LoopBudgetPolicy(KernelContract):
    """Frozen run-wide limits checked before and after every node."""

    policy_id: StableId
    version: LoopVersion
    max_steps: int = Field(ge=1)
    max_tokens: int = Field(ge=0)
    max_estimated_cost_usd: float = Field(ge=0.0)
    max_wall_time_seconds: float = Field(gt=0.0)
    max_tool_calls: int = Field(ge=0)
    max_total_retries: int = Field(ge=0)
    max_failures: int = Field(ge=0)
    max_human_interventions: int = Field(ge=0)


class LoopRetryPolicy(KernelContract):
    """Per-node retry limits; retry execution remains an explicit graph edge."""

    max_attempts: int = Field(default=1, ge=1, le=100)
    retryable_outcomes: list[LoopNodeOutcome] = Field(
        default_factory=lambda: [LoopNodeOutcome.FAILED]
    )
    backoff_seconds: float = Field(default=0.0, ge=0.0)
    require_repair_hypothesis: bool = False
    require_frozen_dimension: bool = False

    @model_validator(mode="after")
    def _normalize(self) -> LoopRetryPolicy:
        values = sorted(set(self.retryable_outcomes), key=lambda item: item.value)
        if LoopNodeOutcome.SUCCEEDED in values:
            raise ValueError("a succeeded node cannot be declared retryable")
        self.retryable_outcomes = values
        return self


class LoopPermissionPolicy(KernelContract):
    """Frozen grants and approval gates; a running graph cannot expand them."""

    policy_id: StableId
    version: LoopVersion
    granted_permission_ids: list[StableId] = Field(default_factory=list)
    approval_required_permission_ids: list[StableId] = Field(default_factory=list)
    forbidden_permission_ids: list[StableId] = Field(default_factory=list)
    deny_unknown: bool = True
    permission_expansion_allowed: Literal[False] = False

    @model_validator(mode="after")
    def _normalize_and_validate(self) -> LoopPermissionPolicy:
        self.granted_permission_ids = _sorted_unique(
            self.granted_permission_ids,
            label="granted permission IDs",
        )
        self.approval_required_permission_ids = _sorted_unique(
            self.approval_required_permission_ids,
            label="approval-required permission IDs",
        )
        self.forbidden_permission_ids = _sorted_unique(
            self.forbidden_permission_ids,
            label="forbidden permission IDs",
        )
        groups = (
            set(self.granted_permission_ids),
            set(self.approval_required_permission_ids),
            set(self.forbidden_permission_ids),
        )
        if groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2]:
            raise ValueError("permission policy sets must be pairwise disjoint")
        return self


class LoopHoldoutPolicy(KernelContract):
    """Rules for revealing and subsequently using a scientific holdout."""

    policy_id: StableId
    version: LoopVersion
    initial_state: HoldoutState = HoldoutState.SEALED
    forbid_adaptive_after_reveal: bool = True
    reveal_permission_id: StableId | None = None


class LoopGuardSpec(KernelContract):
    """One deterministic edge guard; every guard on an edge must pass."""

    guard_id: StableId
    version: LoopVersion = "1"
    kind: LoopGuardKind
    outcomes: list[LoopNodeOutcome] = Field(default_factory=list)
    approval_decisions: list[LoopApprovalDecision] = Field(default_factory=list)
    holdout_states: list[HoldoutState] = Field(default_factory=list)

    @model_validator(mode="after")
    def _normalize_and_validate(self) -> LoopGuardSpec:
        self.outcomes = sorted(set(self.outcomes), key=lambda item: item.value)
        self.approval_decisions = sorted(
            set(self.approval_decisions),
            key=lambda item: item.value,
        )
        self.holdout_states = sorted(
            set(self.holdout_states),
            key=lambda item: item.value,
        )
        if self.kind == LoopGuardKind.ALWAYS:
            if self.outcomes or self.approval_decisions or self.holdout_states:
                raise ValueError("an always guard cannot carry predicate values")
        elif self.kind == LoopGuardKind.OUTCOME:
            if not self.outcomes:
                raise ValueError("an outcome guard requires outcomes")
            if self.approval_decisions or self.holdout_states:
                raise ValueError("an outcome guard cannot carry other predicate values")
        elif self.kind == LoopGuardKind.APPROVAL_DECISION:
            if not self.approval_decisions:
                raise ValueError("an approval guard requires decisions")
            if self.outcomes or self.holdout_states:
                raise ValueError("an approval guard cannot carry other predicate values")
        elif self.kind == LoopGuardKind.HOLDOUT_STATE:
            if not self.holdout_states:
                raise ValueError("a holdout guard requires holdout states")
            if self.outcomes or self.approval_decisions:
                raise ValueError("a holdout guard cannot carry other predicate values")
        elif self.outcomes or self.approval_decisions or self.holdout_states:
            raise ValueError("a mechanism-change guard cannot carry predicate values")
        return self


def always_guard(guard_id: str) -> LoopGuardSpec:
    """Build an explicit unconditional guard."""

    return LoopGuardSpec(guard_id=guard_id, kind=LoopGuardKind.ALWAYS)


class LoopNodeSpec(KernelContract):
    """One versioned node in a frozen Control Graph."""

    node_id: StableId
    version: LoopVersion
    kind: LoopNodeKind
    handler_id: StableId | None = None
    actor_kind: ActorKind = ActorKind.DETERMINISTIC_POLICY
    required_permission_ids: list[StableId] = Field(default_factory=list)
    required_approval_permission_id: StableId | None = None
    retry_policy: LoopRetryPolicy = Field(default_factory=LoopRetryPolicy)
    minimum_usage: LoopUsage = Field(default_factory=LoopUsage)
    side_effecting: bool = False
    compensation_node_id: StableId | None = None
    adaptive: bool = False
    may_reveal_holdout: bool = False
    allowed_after_holdout_reveal: bool = False
    interrupt_after: bool = False
    scientific_gate: bool = False
    subgraph_spec_hash: Sha256 | None = None
    terminal_status: LoopRunStatus | None = None
    authorizes_release: Literal[False] = False
    expands_permissions: Literal[False] = False

    @model_validator(mode="after")
    def _normalize_and_validate(self) -> LoopNodeSpec:
        self.required_permission_ids = _sorted_unique(
            self.required_permission_ids,
            label=f"node {self.node_id} permission IDs",
        )
        automatic_kinds = {
            LoopNodeKind.START,
            LoopNodeKind.APPROVAL,
            LoopNodeKind.TERMINAL,
        }
        if self.kind in automatic_kinds and self.handler_id is not None:
            raise ValueError(f"{self.kind.value} node cannot declare a handler")
        if self.kind not in automatic_kinds and self.handler_id is None:
            raise ValueError(f"{self.kind.value} node requires a handler")
        if self.kind == LoopNodeKind.TERMINAL:
            if self.terminal_status not in TERMINAL_LOOP_STATUSES:
                raise ValueError("terminal node requires a terminal loop status")
            if (
                self.required_permission_ids
                or self.required_approval_permission_id is not None
                or self.compensation_node_id is not None
                or self.side_effecting
                or self.interrupt_after
                or self.minimum_usage != LoopUsage()
            ):
                raise ValueError("terminal node cannot execute work or request permission")
        elif self.terminal_status is not None:
            raise ValueError("only terminal nodes may declare terminal_status")
        if self.kind == LoopNodeKind.START and (
            self.required_permission_ids
            or self.required_approval_permission_id is not None
            or self.minimum_usage != LoopUsage()
            or self.side_effecting
            or self.compensation_node_id is not None
            or self.adaptive
            or self.may_reveal_holdout
            or self.interrupt_after
            or self.scientific_gate
        ):
            raise ValueError("start node cannot execute policy-controlled work")
        if (
            self.kind == LoopNodeKind.APPROVAL
            and self.required_approval_permission_id is None
        ):
            raise ValueError("approval node requires an approval permission")
        if self.compensation_node_id is not None and not self.side_effecting:
            raise ValueError("only a side-effecting node may declare compensation")
        if self.kind == LoopNodeKind.SUBGRAPH:
            if self.subgraph_spec_hash is None:
                raise ValueError("subgraph node requires subgraph_spec_hash")
        elif self.subgraph_spec_hash is not None:
            raise ValueError("only subgraph nodes may declare subgraph_spec_hash")
        if self.scientific_gate and (
            self.kind != LoopNodeKind.GATE
            or self.actor_kind != ActorKind.DETERMINISTIC_POLICY
        ):
            raise ValueError(
                "scientific gates must be deterministic-policy gate nodes"
            )
        if self.compensation_node_id == self.node_id:
            raise ValueError("a node cannot compensate itself")
        if self.may_reveal_holdout and self.kind == LoopNodeKind.TERMINAL:
            raise ValueError("a terminal node cannot reveal a holdout")
        return self


class LoopEdgeSpec(KernelContract):
    """One typed, guarded, priority-ordered graph transition."""

    edge_id: StableId
    version: LoopVersion
    kind: LoopEdgeKind
    source_node_id: StableId
    target_node_id: StableId
    priority: int = Field(default=100, ge=0)
    guards: list[LoopGuardSpec]
    cycle_boundary: bool = False
    max_traversals: int = Field(default=1, ge=1, le=10_000)

    @model_validator(mode="after")
    def _normalize_and_validate(self) -> LoopEdgeSpec:
        if not self.guards:
            raise ValueError("loop edge requires at least one explicit guard")
        guard_ids = [guard.guard_id for guard in self.guards]
        if len(guard_ids) != len(set(guard_ids)):
            raise ValueError(f"edge {self.edge_id} guard IDs must be unique")
        self.guards = sorted(self.guards, key=lambda item: item.guard_id)
        if self.kind == LoopEdgeKind.RETRY and not self.cycle_boundary:
            raise ValueError("retry edges must be explicit cycle boundaries")
        if self.source_node_id == self.target_node_id:
            raise ValueError(
                "self-transitions are forbidden; use an explicit retry or repair node"
            )
        if self.kind == LoopEdgeKind.PIVOT and not _guard_has_outcome(
            self.guards,
            LoopNodeOutcome.NEGATIVE_RESULT,
        ):
            raise ValueError("pivot edge requires a negative-result guard")
        if self.kind == LoopEdgeKind.REJECT and not _guard_has_approval(
            self.guards,
            LoopApprovalDecision.REJECTED,
        ):
            raise ValueError("reject edge requires a rejected-approval guard")
        return self


class _LoopSpecContent(KernelContract):
    schema_version: Literal[1] = 1
    spec_id: StableId
    version: LoopVersion
    graph_version: int = Field(ge=1)
    task_id: StableId
    entry_node_id: StableId
    nodes: list[LoopNodeSpec]
    edges: list[LoopEdgeSpec]
    budget_policy: LoopBudgetPolicy
    permission_policy: LoopPermissionPolicy
    holdout_policy: LoopHoldoutPolicy
    immutable_during_run: Literal[True] = True
    model_graph_proposals_allowed: bool = True
    scientific_gates_deterministic: Literal[True] = True
    permission_expansion_allowed: Literal[False] = False
    release_authorization_allowed: Literal[False] = False

    @model_validator(mode="after")
    def _normalize_and_validate(self) -> _LoopSpecContent:
        if not self.nodes:
            raise ValueError("LoopSpec requires nodes")
        node_ids = [node.node_id for node in self.nodes]
        edge_ids = [edge.edge_id for edge in self.edges]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("LoopSpec node IDs must be unique")
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("LoopSpec edge IDs must be unique")
        self.nodes = sorted(self.nodes, key=lambda item: item.node_id)
        self.edges = sorted(self.edges, key=lambda item: item.edge_id)
        nodes = {node.node_id: node for node in self.nodes}
        if self.entry_node_id not in nodes:
            raise ValueError("LoopSpec entry node does not exist")
        if nodes[self.entry_node_id].kind != LoopNodeKind.START:
            raise ValueError("LoopSpec entry node must have kind=start")
        terminal_ids = {
            node.node_id
            for node in self.nodes
            if node.kind == LoopNodeKind.TERMINAL
        }
        if not terminal_ids:
            raise ValueError("LoopSpec requires at least one terminal node")

        priorities: set[tuple[str, int]] = set()
        adjacency: dict[str, list[str]] = {node_id: [] for node_id in nodes}
        reverse: dict[str, list[str]] = {node_id: [] for node_id in nodes}
        for edge in self.edges:
            if edge.source_node_id not in nodes or edge.target_node_id not in nodes:
                raise ValueError(f"edge {edge.edge_id} has a dangling endpoint")
            if edge.source_node_id in terminal_ids:
                raise ValueError("terminal nodes cannot have outgoing edges")
            priority_key = (edge.source_node_id, edge.priority)
            if priority_key in priorities:
                raise ValueError(
                    "outgoing edge priorities must be unique for deterministic routing"
                )
            priorities.add(priority_key)
            adjacency[edge.source_node_id].append(edge.target_node_id)
            reverse[edge.target_node_id].append(edge.source_node_id)
            source = nodes[edge.source_node_id]
            if (
                edge.kind == LoopEdgeKind.NEXT
                and source.kind != LoopNodeKind.START
                and not any(
                    guard.kind == LoopGuardKind.OUTCOME
                    for guard in edge.guards
                )
            ):
                raise ValueError(
                    f"next edge {edge.edge_id} requires an outcome guard"
                )
            if edge.kind in {
                LoopEdgeKind.RETRY,
                LoopEdgeKind.COMPENSATE,
            } and not any(
                guard.kind == LoopGuardKind.OUTCOME
                and any(
                    outcome in {
                        LoopNodeOutcome.FAILED,
                        LoopNodeOutcome.BLOCKED,
                    }
                    for outcome in guard.outcomes
                )
                for guard in edge.guards
            ):
                raise ValueError(
                    f"{edge.kind.value} edge {edge.edge_id} requires a "
                    "failed or blocked outcome guard"
                )

        reachable = _reachable_from(self.entry_node_id, adjacency)
        if reachable != set(nodes):
            missing = ", ".join(sorted(set(nodes) - reachable))
            raise ValueError(f"LoopSpec has unreachable nodes: {missing}")
        can_reach_terminal = _reverse_reachable(terminal_ids, reverse)
        if can_reach_terminal != set(nodes):
            missing = ", ".join(sorted(set(nodes) - can_reach_terminal))
            raise ValueError(f"LoopSpec nodes cannot reach a terminal: {missing}")

        allowed_permissions = set(
            self.permission_policy.granted_permission_ids
        ) | set(self.permission_policy.approval_required_permission_ids)
        for node in self.nodes:
            required = set(node.required_permission_ids)
            if node.required_approval_permission_id is not None:
                required.add(node.required_approval_permission_id)
                if (
                    node.required_approval_permission_id
                    not in self.permission_policy.approval_required_permission_ids
                ):
                    raise ValueError(
                        f"node {node.node_id} approval permission is not "
                        "approval-required by policy"
                    )
            unknown = sorted(required - allowed_permissions)
            if unknown:
                raise ValueError(
                    f"node {node.node_id} requires unknown permissions: "
                    + ", ".join(unknown)
                )
            if node.compensation_node_id is not None:
                compensation = nodes.get(node.compensation_node_id)
                if compensation is None:
                    raise ValueError(
                        f"node {node.node_id} compensation target does not exist"
                    )
                if compensation.kind != LoopNodeKind.COMPENSATION:
                    raise ValueError(
                        "compensation_node_id must reference a compensation node"
                    )
                matching_edges = [
                    edge
                    for edge in self.edges
                    if edge.source_node_id == node.node_id
                    and edge.target_node_id == compensation.node_id
                    and edge.kind == LoopEdgeKind.COMPENSATE
                ]
                if not matching_edges:
                    raise ValueError(
                        f"node {node.node_id} requires an explicit compensation edge"
                    )
            if (
                node.may_reveal_holdout
                and self.holdout_policy.reveal_permission_id is not None
                and self.holdout_policy.reveal_permission_id
                not in node.required_permission_ids
            ):
                raise ValueError(
                    f"holdout-reveal node {node.node_id} lacks reveal permission"
                )

        self.control_snapshot()
        return self

    def control_snapshot(self) -> GraphSnapshot:
        """Project this LoopSpec into the canonical control graph plane."""

        cycle_policy = (
            ControlCyclePolicy.EXPLICIT_BOUNDARIES
            if any(edge.cycle_boundary for edge in self.edges)
            else ControlCyclePolicy.ACYCLIC
        )
        return GraphSnapshot(
            graph_id=self.spec_id,
            version=self.graph_version,
            plane=GraphPlane.CONTROL,
            control_cycle_policy=cycle_policy,
            nodes=[
                GraphNode(
                    node_id=node.node_id,
                    plane=GraphPlane.CONTROL,
                    node_type=node.kind.value,
                    attributes={
                        "version": node.version,
                        "adaptive": node.adaptive,
                        "scientific_gate": node.scientific_gate,
                    },
                )
                for node in self.nodes
            ],
            edges=[
                GraphEdge(
                    edge_id=edge.edge_id,
                    plane=GraphPlane.CONTROL,
                    edge_type=edge.kind.value,
                    source_id=edge.source_node_id,
                    target_id=edge.target_node_id,
                    cycle_boundary=edge.cycle_boundary,
                    attributes={
                        "version": edge.version,
                        "priority": edge.priority,
                        "max_traversals": edge.max_traversals,
                    },
                )
                for edge in self.edges
            ],
        )


class LoopSpec(_LoopSpecContent):
    """Content-addressed frozen Control Graph and execution policy."""

    spec_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> LoopSpec:
        expected = self.calculated_hash()
        if self.spec_hash != expected:
            raise ValueError(
                f"LoopSpec hash mismatch: expected {expected}, got {self.spec_hash}"
            )
        return self

    @classmethod
    def create(cls, **values: Any) -> LoopSpec:
        """Validate content, attach a digest, and validate the final contract."""

        content = _LoopSpecContent.model_validate(values)
        payload = content.model_dump(mode="json")
        payload["spec_hash"] = canonical_sha256(content)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Calculate the digest over every frozen field except ``spec_hash``."""

        return canonical_sha256(self.model_dump(mode="json", exclude={"spec_hash"}))

    def verify_integrity(self) -> None:
        """Detect in-memory nested mutation before execution or export."""

        if self.spec_hash != self.calculated_hash():
            raise LoopSpecIntegrityError(
                f"LoopSpec {self.spec_id} failed integrity verification"
            )


class LoopGraphProposal(KernelContract):
    """A non-executable proposal for a later graph version."""

    proposal_id: StableId
    proposed_by_actor_id: StableId
    proposed_by_kind: ActorKind
    parent_spec_id: StableId
    parent_spec_hash: Sha256
    proposed_version: LoopVersion
    proposed_spec_hash: Sha256
    rationale: LoopText
    permission_additions: list[StableId] = Field(default_factory=list)
    scientific_gate_status: str | None = None
    authorizes_release: bool = False

    @model_validator(mode="after")
    def _enforce_non_authoritative_boundary(self) -> LoopGraphProposal:
        self.permission_additions = _sorted_unique(
            self.permission_additions,
            label="proposal permission additions",
        )
        if self.permission_additions:
            raise ValueError("a graph proposal cannot expand permissions")
        if self.scientific_gate_status is not None:
            raise ValueError("a graph proposal cannot compute a scientific gate")
        if self.authorizes_release:
            raise ValueError("a graph proposal cannot authorize release")
        return self


class LoopApproval(KernelContract):
    """A safe approval record; free-form comments are intentionally excluded."""

    approval_id: StableId
    permission_id: StableId
    decision: LoopApprovalDecision
    actor_id: StableId
    decided_at: datetime

    @model_validator(mode="after")
    def _require_utc(self) -> LoopApproval:
        self.decided_at = _require_utc(self.decided_at, label="approval decided_at")
        return self


class LoopStartRequest(KernelContract):
    """Initial values for one frozen graph run."""

    run_id: StableId
    task_id: StableId
    mechanism_family: LoopText
    variables: dict[str, JsonValue] = Field(default_factory=dict)
    approvals: list[LoopApproval] = Field(default_factory=list)

    @field_validator("variables", mode="before")
    @classmethod
    def _validate_variables(cls, value: object) -> object:
        validate_persistable_content(value)
        return value

    @model_validator(mode="after")
    def _normalize(self) -> LoopStartRequest:
        self.approvals = _normalize_approvals(self.approvals)
        return self


class LoopResumeRequest(KernelContract):
    """New approval records supplied while resuming a paused run."""

    approvals: list[LoopApproval] = Field(default_factory=list)

    @model_validator(mode="after")
    def _normalize(self) -> LoopResumeRequest:
        self.approvals = _normalize_approvals(self.approvals)
        return self


class LoopNodeExecutionRequest(KernelContract):
    """Bounded, immutable input passed to one node executor."""

    run_id: StableId
    task_id: StableId
    spec_id: StableId
    spec_hash: Sha256
    node: LoopNodeSpec
    attempt: int = Field(ge=1)
    idempotency_key: StableId
    mechanism_family: LoopText
    holdout_state: HoldoutState
    variables: dict[str, JsonValue]
    consumed_usage: LoopUsage


class LoopNodeResult(KernelContract):
    """Truthful node result returned behind the idempotent executor protocol."""

    outcome: LoopNodeOutcome
    summary: LoopText
    usage: LoopUsage = Field(default_factory=LoopUsage)
    output_artifact_ids: list[StableId] = Field(default_factory=list)
    variable_updates: dict[str, JsonValue] = Field(default_factory=dict)
    failure_code: FailureCode | None = None
    retryable: bool = False
    mechanism_family: LoopText | None = None
    reveal_holdout: bool = False
    repair_hypothesis: LoopText | None = None
    frozen_dimensions: list[StableId] = Field(default_factory=list)
    graph_proposal: LoopGraphProposal | None = None
    side_effect_committed: bool = False
    approval_decision: LoopApprovalDecision | None = None

    @field_validator("variable_updates", mode="before")
    @classmethod
    def _validate_variable_updates(cls, value: object) -> object:
        validate_persistable_content(value)
        return value

    @model_validator(mode="after")
    def _normalize_and_validate(self) -> LoopNodeResult:
        self.output_artifact_ids = _sorted_unique(
            self.output_artifact_ids,
            label="output artifact IDs",
        )
        self.frozen_dimensions = _sorted_unique(
            self.frozen_dimensions,
            label="frozen dimensions",
        )
        if self.outcome in {
            LoopNodeOutcome.FAILED,
            LoopNodeOutcome.BLOCKED,
        }:
            if self.failure_code is None:
                raise ValueError("failed or blocked node result requires failure_code")
        elif self.failure_code is not None:
            raise ValueError("successful or negative result cannot carry failure_code")
        if self.outcome == LoopNodeOutcome.SUCCEEDED and self.retryable:
            raise ValueError("a succeeded node result cannot be retryable")
        return self


class LoopNodeExecutor(Protocol):
    """Provider-neutral executor; implementations must deduplicate by request key."""

    executor_id: str
    executor_version: str

    def execute(self, request: LoopNodeExecutionRequest) -> LoopNodeResult:
        """Execute or reuse one node result for the stable idempotency key."""


class DeterministicLoopExecutor:
    """Test/development executor with explicit idempotency caching."""

    executor_id = "loop.fixture"
    executor_version = "1"

    def __init__(
        self,
        results_by_handler: Mapping[str, Sequence[LoopNodeResult]],
    ) -> None:
        self._results = {
            handler_id: list(results)
            for handler_id, results in results_by_handler.items()
        }
        self._cache: dict[str, LoopNodeResult] = {}
        self._handler_offsets: dict[str, int] = {}
        self.invocation_count = 0
        self.execution_count = 0
        self.idempotency_keys: list[str] = []

    def execute(self, request: LoopNodeExecutionRequest) -> LoopNodeResult:
        """Return one configured result and reuse it for duplicate keys."""

        self.invocation_count += 1
        self.idempotency_keys.append(request.idempotency_key)
        cached = self._cache.get(request.idempotency_key)
        if cached is not None:
            return cached.model_copy(deep=True)
        handler_id = request.node.handler_id
        if handler_id is None or handler_id not in self._results:
            raise LoopRuntimeError(
                f"deterministic executor has no result for node {request.node.node_id}"
            )
        offset = self._handler_offsets.get(handler_id, 0)
        configured = self._results[handler_id]
        if offset >= len(configured):
            raise LoopRuntimeError(
                f"deterministic executor exhausted results for {handler_id}"
            )
        result = configured[offset].model_copy(deep=True)
        self._handler_offsets[handler_id] = offset + 1
        self._cache[request.idempotency_key] = result.model_copy(deep=True)
        self.execution_count += 1
        return result


class LoopRunState(KernelContract):
    """State fully derived from the validated event lineage."""

    schema_version: Literal[1] = 1
    run_id: StableId
    task_id: StableId
    spec_id: StableId
    spec_hash: Sha256
    start_request_hash: Sha256
    revision: int = Field(ge=1)
    status: LoopRunStatus
    current_node_id: StableId | None
    step_count: int = Field(default=0, ge=0)
    attempts_by_node: dict[str, int] = Field(default_factory=dict)
    edge_traversals: dict[str, int] = Field(default_factory=dict)
    completed_node_ids: list[StableId] = Field(default_factory=list)
    produced_artifact_ids: list[StableId] = Field(default_factory=list)
    consumed_usage: LoopUsage = Field(default_factory=LoopUsage)
    retry_count: int = Field(default=0, ge=0)
    failure_count: int = Field(default=0, ge=0)
    human_intervention_count: int = Field(default=0, ge=0)
    mechanism_family: LoopText
    holdout_state: HoldoutState
    variables: dict[str, JsonValue] = Field(default_factory=dict)
    approvals: list[LoopApproval] = Field(default_factory=list)
    consumed_approval_ids: list[StableId] = Field(default_factory=list)
    graph_proposals: list[LoopGraphProposal] = Field(default_factory=list)
    last_outcome: LoopNodeOutcome | None = None
    last_failure_code: FailureCode | None = None
    pending_approval_permission_id: StableId | None = None
    pending_interrupt_after_node_id: StableId | None = None
    inflight_idempotency_key: StableId | None = None
    terminal_reason: LoopText | None = None

    @field_validator("variables", mode="before")
    @classmethod
    def _validate_variables(cls, value: object) -> object:
        validate_persistable_content(value)
        return value

    @model_validator(mode="after")
    def _normalize_and_validate(self) -> LoopRunState:
        self.attempts_by_node = _sorted_nonnegative_mapping(
            self.attempts_by_node,
            label="attempt count",
        )
        self.edge_traversals = _sorted_nonnegative_mapping(
            self.edge_traversals,
            label="edge traversal count",
        )
        self.produced_artifact_ids = _sorted_unique(
            self.produced_artifact_ids,
            label="produced artifact IDs",
        )
        self.approvals = _normalize_approvals(self.approvals)
        self.consumed_approval_ids = _sorted_unique(
            self.consumed_approval_ids,
            label="consumed approval IDs",
        )
        proposal_ids = [proposal.proposal_id for proposal in self.graph_proposals]
        if len(proposal_ids) != len(set(proposal_ids)):
            raise ValueError("graph proposal IDs must be unique")
        if self.status == LoopRunStatus.RUNNING:
            if self.current_node_id is None or self.inflight_idempotency_key is None:
                raise ValueError("running state requires current node and inflight key")
        elif self.inflight_idempotency_key is not None:
            raise ValueError("only running state may carry an inflight key")
        if self.status in TERMINAL_LOOP_STATUSES:
            if self.terminal_reason is None:
                raise ValueError("terminal loop state requires terminal_reason")
            if (
                self.pending_approval_permission_id is not None
                or self.pending_interrupt_after_node_id is not None
            ):
                raise ValueError("terminal loop state cannot remain paused")
        else:
            if self.current_node_id is None:
                raise ValueError("non-terminal loop state requires current_node_id")
            if self.terminal_reason is not None:
                raise ValueError("non-terminal loop state cannot carry terminal_reason")
        if self.status == LoopRunStatus.PAUSED and not (
            self.pending_approval_permission_id is not None
            or self.pending_interrupt_after_node_id is not None
        ):
            raise ValueError("paused state requires an approval or interrupt reason")
        return self


class _LoopRunSnapshotContent(KernelContract):
    schema_version: Literal[1] = 1
    run_id: StableId
    task_id: StableId
    spec_id: StableId
    spec_hash: Sha256
    state: LoopRunState
    event_count: int = Field(ge=1)
    lineage_hash: Sha256
    terminal_event_id: StableId | None = None
    terminal_event_hash: Sha256 | None = None
    seal_hash: Sha256 | None = None

    @model_validator(mode="after")
    def _validate_content(self) -> _LoopRunSnapshotContent:
        if self.state.run_id != self.run_id or self.state.task_id != self.task_id:
            raise ValueError("snapshot identity differs from state")
        if (
            self.state.spec_id != self.spec_id
            or self.state.spec_hash != self.spec_hash
        ):
            raise ValueError("snapshot spec identity differs from state")
        if self.state.revision != self.event_count:
            raise ValueError("snapshot state revision must equal event count")
        terminal_fields = (
            self.terminal_event_id,
            self.terminal_event_hash,
            self.seal_hash,
        )
        if self.state.status in TERMINAL_LOOP_STATUSES:
            if any(value is None for value in terminal_fields):
                raise ValueError("terminal snapshot requires terminal event and seal")
        elif any(value is not None for value in terminal_fields):
            raise ValueError("non-terminal snapshot cannot carry terminal seal fields")
        return self


class LoopRunSnapshot(_LoopRunSnapshotContent):
    """Content-addressed view of derived state and journal lineage."""

    snapshot_hash: Sha256

    @model_validator(mode="after")
    def _validate_hash(self) -> LoopRunSnapshot:
        expected = self.calculated_hash()
        if self.snapshot_hash != expected:
            raise ValueError(
                f"loop snapshot hash mismatch: expected {expected}, "
                f"got {self.snapshot_hash}"
            )
        return self

    @classmethod
    def create(
        cls,
        *,
        spec: LoopSpec,
        state: LoopRunState,
        journal_snapshot: JournalSnapshot,
    ) -> LoopRunSnapshot:
        """Bind derived state to one validated journal lineage."""

        terminal = journal_snapshot.events[-1] if journal_snapshot.is_terminal else None
        content = _LoopRunSnapshotContent(
            run_id=state.run_id,
            task_id=state.task_id,
            spec_id=spec.spec_id,
            spec_hash=spec.spec_hash,
            state=state,
            event_count=len(journal_snapshot.events),
            lineage_hash=journal_snapshot.lineage_hash,
            terminal_event_id=terminal.event_id if terminal is not None else None,
            terminal_event_hash=terminal.event_hash if terminal is not None else None,
            seal_hash=(
                journal_snapshot.seal.seal_hash
                if journal_snapshot.seal is not None
                else None
            ),
        )
        payload = content.model_dump(mode="json")
        payload["snapshot_hash"] = canonical_sha256(content)
        return cls.model_validate(payload)

    def calculated_hash(self) -> str:
        """Calculate the snapshot digest without ``snapshot_hash``."""

        return canonical_sha256(
            self.model_dump(mode="json", exclude={"snapshot_hash"})
        )

    def verify_integrity(self) -> None:
        """Detect nested mutation before export."""

        if self.snapshot_hash != self.calculated_hash():
            raise LoopRuntimeError(
                f"loop snapshot for {self.run_id} failed integrity verification"
            )


class ControlGraphRuntime:
    """Execute one frozen LoopSpec with state derived only from EventJournal."""

    _ACTOR = EventActor(
        actor_id="control.runtime",
        kind=ActorKind.DETERMINISTIC_POLICY,
        version="1",
    )

    def __init__(
        self,
        *,
        spec: LoopSpec,
        journal: EventJournal,
        executor: LoopNodeExecutor,
        clock: Callable[[], datetime] | None = None,
        fault_injector: Callable[[str, str], None] | None = None,
    ) -> None:
        self.spec = spec
        self.journal = journal
        self.executor = executor
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.fault_injector = fault_injector
        self._nodes = {node.node_id: node for node in spec.nodes}
        self._edges_by_source: dict[str, list[LoopEdgeSpec]] = {
            node.node_id: [] for node in spec.nodes
        }
        for edge in spec.edges:
            self._edges_by_source[edge.source_node_id].append(edge)
        for edges in self._edges_by_source.values():
            edges.sort(key=lambda item: (item.priority, item.edge_id))

    def start(self, request: LoopStartRequest) -> LoopRunSnapshot:
        """Start a new graph or return the exact existing start idempotently."""

        self._validate_runtime_boundary()
        validate_persistable_content(request.model_dump(mode="json"))
        if request.run_id != self.journal.metadata.run_id:
            raise LoopRuntimeError(
                f"request run {request.run_id} does not match journal "
                f"{self.journal.metadata.run_id}"
            )
        if request.task_id != self.spec.task_id:
            raise LoopRuntimeError("request task differs from frozen LoopSpec")
        journal_snapshot = self._journal_snapshot()
        request_hash = canonical_sha256(request)
        if journal_snapshot.events:
            state = self._replay_state(journal_snapshot)
            if state.start_request_hash != request_hash:
                raise LoopRuntimeError(
                    "journal already belongs to a different start request"
                )
            return self._package(state, journal_snapshot)

        self._validate_approval_permissions(request.approvals)
        initial = LoopRunState(
            run_id=request.run_id,
            task_id=request.task_id,
            spec_id=self.spec.spec_id,
            spec_hash=self.spec.spec_hash,
            start_request_hash=request_hash,
            revision=1,
            status=LoopRunStatus.READY,
            current_node_id=self.spec.entry_node_id,
            mechanism_family=request.mechanism_family,
            holdout_state=self.spec.holdout_policy.initial_state,
            variables=request.variables,
            approvals=request.approvals,
        )
        self._append_state_event(
            state=initial,
            event_type="loop.started",
            action="Start frozen Control Graph",
            event_status=EventStatus.STARTED,
            idempotency_key=_event_idempotency_key(
                "start",
                request.run_id,
                self.spec.spec_hash,
            ),
            payload={
                "loop_spec_hash": self.spec.spec_hash,
                "start_request_hash": request_hash,
            },
        )
        return self._drive(initial)

    def resume(
        self,
        request: LoopResumeRequest | None = None,
    ) -> LoopRunSnapshot:
        """Resume from replayed state, optionally supplying bounded approvals."""

        self._validate_runtime_boundary()
        resume_request = request or LoopResumeRequest()
        validate_persistable_content(resume_request.model_dump(mode="json"))
        self._validate_approval_permissions(resume_request.approvals)
        journal_snapshot = self._journal_snapshot()
        if not journal_snapshot.events:
            raise LoopRuntimeError("cannot resume an empty Control Graph journal")
        state = self._replay_state(journal_snapshot)
        if state.status in TERMINAL_LOOP_STATUSES:
            return self._package(state, journal_snapshot)

        merged_approvals = _merge_approvals(state.approvals, resume_request.approvals)
        if state.status == LoopRunStatus.PAUSED:
            if state.pending_approval_permission_id is not None:
                approval = _approval_for_permission(
                    merged_approvals,
                    state.pending_approval_permission_id,
                )
                if approval is None:
                    return self._package(state, journal_snapshot)
            resumed = self._evolve(
                state,
                revision=state.revision + 1,
                status=LoopRunStatus.READY,
                approvals=merged_approvals,
                pending_approval_permission_id=None,
                pending_interrupt_after_node_id=None,
            )
            self._append_state_event(
                state=resumed,
                event_type="loop.resumed",
                action="Resume frozen Control Graph",
                event_status=EventStatus.STARTED,
                idempotency_key=_event_idempotency_key(
                    "resume",
                    state.run_id,
                    resumed.revision,
                ),
                payload={"new_approval_count": len(resume_request.approvals)},
            )
            state = resumed
        elif resume_request.approvals:
            raise LoopRuntimeError("new approvals may only be supplied to a paused run")
        return self._drive(state)

    def snapshot(self) -> LoopRunSnapshot:
        """Replay and package the current state without advancing the graph."""

        self._validate_runtime_boundary()
        journal_snapshot = self._journal_snapshot()
        if not journal_snapshot.events:
            raise LoopRuntimeError("Control Graph journal is empty")
        state = self._replay_state(journal_snapshot)
        return self._package(state, journal_snapshot)

    def _drive(self, state: LoopRunState) -> LoopRunSnapshot:
        while state.status not in TERMINAL_LOOP_STATUSES:
            if state.status == LoopRunStatus.PAUSED:
                return self._package(state, self._journal_snapshot())
            node = self._node(state.current_node_id)
            if node.kind == LoopNodeKind.TERMINAL:
                state = self._enter_terminal_node(state, node)
                continue
            budget_reason = self._preflight_budget_reason(state, node)
            if budget_reason is not None:
                state = self._terminate(
                    state,
                    status=LoopRunStatus.BLOCKED,
                    reason=budget_reason,
                    event_type="loop.budget.blocked",
                )
                continue
            if self._adaptive_holdout_forbidden(state, node):
                state = self._terminate(
                    state,
                    status=LoopRunStatus.BLOCKED,
                    reason="revealed_holdout_adaptation_forbidden",
                    event_type="loop.holdout.blocked",
                )
                continue
            permission_reason = self._permission_failure_reason(node)
            if permission_reason is not None:
                state = self._terminate(
                    state,
                    status=LoopRunStatus.BLOCKED,
                    reason=permission_reason,
                    event_type="loop.permission.blocked",
                )
                continue
            approval = self._approval_for_node(state, node)
            if (
                node.required_approval_permission_id is not None
                and approval is None
            ):
                state = self._pause_for_approval(
                    state,
                    node.required_approval_permission_id,
                )
                continue
            if (
                approval is not None
                and approval.approval_id not in state.consumed_approval_ids
                and state.human_intervention_count + 1
                > self.spec.budget_policy.max_human_interventions
            ):
                state = self._terminate(
                    state,
                    status=LoopRunStatus.BLOCKED,
                    reason="human_intervention_budget_exhausted",
                    event_type="loop.budget.blocked",
                )
                continue
            state = self._execute_node(state, node, approval)
        return self._package(state, self._journal_snapshot())

    def _execute_node(
        self,
        state: LoopRunState,
        node: LoopNodeSpec,
        approval: LoopApproval | None,
    ) -> LoopRunState:
        if state.status == LoopRunStatus.RUNNING:
            attempt = state.attempts_by_node[node.node_id]
            idempotency_key = state.inflight_idempotency_key
            if idempotency_key is None:
                raise LoopReplayError("running state lost its idempotency key")
        else:
            attempt = state.attempts_by_node.get(node.node_id, 0) + 1
            if attempt > node.retry_policy.max_attempts:
                return self._terminate(
                    state,
                    status=LoopRunStatus.BLOCKED,
                    reason=f"node_attempt_budget_exhausted:{node.node_id}",
                    event_type="loop.retry.blocked",
                )
            idempotency_key = _node_idempotency_key(
                state.run_id,
                self.spec.spec_hash,
                node.node_id,
                attempt,
            )
            attempts = dict(state.attempts_by_node)
            attempts[node.node_id] = attempt
            running = self._evolve(
                state,
                revision=state.revision + 1,
                status=LoopRunStatus.RUNNING,
                attempts_by_node=attempts,
                inflight_idempotency_key=idempotency_key,
            )
            self._append_state_event(
                state=running,
                event_type="loop.node.started",
                action=f"Start node {node.node_id}",
                event_status=EventStatus.STARTED,
                idempotency_key=_event_idempotency_key(
                    "node-started",
                    idempotency_key,
                ),
                payload={
                    "node_id": node.node_id,
                    "attempt": attempt,
                    "node_idempotency_key": idempotency_key,
                    "executor_id": self.executor.executor_id,
                    "executor_version": self.executor.executor_version,
                },
            )
            state = running

        if node.kind == LoopNodeKind.START:
            result = LoopNodeResult(
                outcome=LoopNodeOutcome.SUCCEEDED,
                summary="Frozen Control Graph entry node completed.",
            )
        elif node.kind == LoopNodeKind.APPROVAL:
            if approval is None:
                raise LoopRuntimeError("approval node executed without a decision")
            result = _approval_result(approval)
        elif (
            approval is not None
            and approval.decision == LoopApprovalDecision.REJECTED
        ):
            result = _approval_result(approval)
        else:
            request = LoopNodeExecutionRequest(
                run_id=state.run_id,
                task_id=state.task_id,
                spec_id=self.spec.spec_id,
                spec_hash=self.spec.spec_hash,
                node=node,
                attempt=attempt,
                idempotency_key=idempotency_key,
                mechanism_family=state.mechanism_family,
                holdout_state=state.holdout_state,
                variables=state.variables,
                consumed_usage=state.consumed_usage,
            )
            try:
                result = self.executor.execute(request)
            except Exception as exc:
                result = LoopNodeResult(
                    outcome=LoopNodeOutcome.FAILED,
                    summary=_safe_error_message(exc),
                    failure_code="executor_error",
                    retryable=True,
                )
        try:
            validate_persistable_content(result.model_dump(mode="json"))
        except SensitiveContentError:
            result = LoopNodeResult(
                outcome=LoopNodeOutcome.FAILED,
                summary="Sensitive node result details were suppressed.",
                failure_code="sensitive_node_result",
                retryable=False,
            )
        self._fault("after_node_execute", node.node_id)
        return self._complete_node(state, node, result, approval)

    def _complete_node(
        self,
        state: LoopRunState,
        node: LoopNodeSpec,
        result: LoopNodeResult,
        approval: LoopApproval | None,
    ) -> LoopRunState:
        prior_mechanism = state.mechanism_family
        mechanism = result.mechanism_family or prior_mechanism
        holdout_state = state.holdout_state
        if result.reveal_holdout:
            if not node.may_reveal_holdout:
                return self._terminate(
                    state,
                    status=LoopRunStatus.FAILED,
                    reason=f"unauthorized_holdout_reveal:{node.node_id}",
                    event_type="loop.holdout.failed",
                )
            holdout_state = HoldoutState.REVEALED

        proposal = result.graph_proposal
        proposals = list(state.graph_proposals)
        if proposal is not None:
            if not self.spec.model_graph_proposals_allowed:
                return self._terminate(
                    state,
                    status=LoopRunStatus.BLOCKED,
                    reason="model_graph_proposal_forbidden",
                    event_type="loop.proposal.blocked",
                )
            if (
                proposal.parent_spec_id != self.spec.spec_id
                or proposal.parent_spec_hash != self.spec.spec_hash
                or proposal.proposed_spec_hash == self.spec.spec_hash
                or proposal.proposed_version == self.spec.version
            ):
                return self._terminate(
                    state,
                    status=LoopRunStatus.FAILED,
                    reason="invalid_graph_proposal_parent_or_version",
                    event_type="loop.proposal.failed",
                )
            proposals.append(proposal)

        consumed_approvals = list(state.consumed_approval_ids)
        intervention_count = state.human_intervention_count
        if approval is not None and approval.approval_id not in consumed_approvals:
            consumed_approvals.append(approval.approval_id)
            intervention_count += 1
        if (
            intervention_count
            > self.spec.budget_policy.max_human_interventions
        ):
            return self._terminate(
                state,
                status=LoopRunStatus.BLOCKED,
                reason="human_intervention_budget_exhausted",
                event_type="loop.budget.blocked",
            )

        usage = _add_usage(state.consumed_usage, result.usage)
        variables = dict(state.variables)
        variables.update(result.variable_updates)
        artifacts = sorted(
            set(state.produced_artifact_ids) | set(result.output_artifact_ids)
        )
        failure_count = state.failure_count + int(
            result.outcome in {LoopNodeOutcome.FAILED, LoopNodeOutcome.BLOCKED}
        )
        budget_reason = self._post_result_budget_reason(
            state=state,
            usage=usage,
            failure_count=failure_count,
        )
        if budget_reason is not None:
            return self._terminate(
                state,
                status=LoopRunStatus.BLOCKED,
                reason=budget_reason,
                event_type="loop.budget.blocked",
                usage=usage,
                step_increment=1,
                result=result,
                mechanism_family=mechanism,
                holdout_state=holdout_state,
                variables=variables,
                artifacts=artifacts,
                failure_count=failure_count,
                consumed_approval_ids=consumed_approvals,
                intervention_count=intervention_count,
                proposals=proposals,
            )
        edge = self._select_edge(
            state=state,
            node=node,
            result=result,
            approval=approval,
            resulting_mechanism=mechanism,
            resulting_holdout=holdout_state,
        )
        if edge is None:
            terminal_status = _fallback_terminal_status(result, approval)
            return self._terminate(
                state,
                status=terminal_status,
                reason=(
                    result.failure_code
                    or f"no_eligible_edge_after_{result.outcome.value}:{node.node_id}"
                ),
                event_type="loop.node.terminal",
                usage=usage,
                step_increment=1,
                result=result,
                mechanism_family=mechanism,
                holdout_state=holdout_state,
                variables=variables,
                artifacts=artifacts,
                failure_count=failure_count,
                consumed_approval_ids=consumed_approvals,
                intervention_count=intervention_count,
                proposals=proposals,
            )

        retry_count = state.retry_count
        traversals = dict(state.edge_traversals)
        traversals[edge.edge_id] = traversals.get(edge.edge_id, 0) + 1
        if traversals[edge.edge_id] > edge.max_traversals:
            return self._terminate(
                state,
                status=LoopRunStatus.BLOCKED,
                reason=f"edge_traversal_budget_exhausted:{edge.edge_id}",
                event_type="loop.retry.blocked",
            )
        if edge.kind == LoopEdgeKind.RETRY:
            retry_reason = self._retry_failure_reason(
                state=state,
                node=node,
                result=result,
            )
            if retry_reason is not None:
                return self._terminate(
                    state,
                    status=LoopRunStatus.BLOCKED,
                    reason=retry_reason,
                    event_type="loop.retry.blocked",
                )
            retry_count += 1

        completed = [*state.completed_node_ids, node.node_id]
        paused = node.interrupt_after
        next_state = self._evolve(
            state,
            revision=state.revision + 1,
            status=LoopRunStatus.PAUSED if paused else LoopRunStatus.READY,
            current_node_id=edge.target_node_id,
            step_count=state.step_count + 1,
            edge_traversals=traversals,
            completed_node_ids=completed,
            produced_artifact_ids=artifacts,
            consumed_usage=usage,
            retry_count=retry_count,
            failure_count=failure_count,
            human_intervention_count=intervention_count,
            mechanism_family=mechanism,
            holdout_state=holdout_state,
            variables=variables,
            consumed_approval_ids=consumed_approvals,
            graph_proposals=proposals,
            last_outcome=result.outcome,
            last_failure_code=result.failure_code,
            pending_interrupt_after_node_id=node.node_id if paused else None,
            inflight_idempotency_key=None,
        )
        event_status = EventStatus.PAUSED if paused else EventStatus.STARTED
        self._append_state_event(
            state=next_state,
            event_type="loop.node.completed",
            action=f"Complete node {node.node_id}",
            event_status=event_status,
            idempotency_key=(
                _event_idempotency_key(
                    "node-completed",
                    state.inflight_idempotency_key,
                )
                if state.inflight_idempotency_key is not None
                else _event_idempotency_key(
                    "node-completed",
                    state.run_id,
                    node.node_id,
                    next_state.revision,
                )
            ),
            payload={
                "node_id": node.node_id,
                "edge_id": edge.edge_id,
                "edge_kind": edge.kind.value,
                "result": result.model_dump(mode="json"),
            },
            output_artifact_ids=result.output_artifact_ids,
            approval_id=approval.approval_id if approval is not None else None,
        )
        return next_state

    def _enter_terminal_node(
        self,
        state: LoopRunState,
        node: LoopNodeSpec,
    ) -> LoopRunState:
        terminal_status = node.terminal_status
        if terminal_status is None:
            raise LoopRuntimeError("terminal node lost terminal_status")
        return self._terminate(
            state,
            status=terminal_status,
            reason=f"terminal_node:{node.node_id}",
            event_type="loop.terminal",
        )

    def _terminate(
        self,
        state: LoopRunState,
        *,
        status: LoopRunStatus,
        reason: str,
        event_type: str,
        usage: LoopUsage | None = None,
        step_increment: int = 0,
        result: LoopNodeResult | None = None,
        mechanism_family: str | None = None,
        holdout_state: HoldoutState | None = None,
        variables: dict[str, JsonValue] | None = None,
        artifacts: list[str] | None = None,
        failure_count: int | None = None,
        consumed_approval_ids: list[str] | None = None,
        intervention_count: int | None = None,
        proposals: list[LoopGraphProposal] | None = None,
    ) -> LoopRunState:
        if status not in TERMINAL_LOOP_STATUSES:
            raise LoopRuntimeError("terminate requires a terminal loop status")
        terminal = self._evolve(
            state,
            revision=state.revision + 1,
            status=status,
            step_count=state.step_count + step_increment,
            completed_node_ids=(
                [*state.completed_node_ids, self._node(state.current_node_id).node_id]
                if step_increment
                else state.completed_node_ids
            ),
            produced_artifact_ids=artifacts or state.produced_artifact_ids,
            consumed_usage=usage or state.consumed_usage,
            failure_count=(
                state.failure_count if failure_count is None else failure_count
            ),
            human_intervention_count=(
                state.human_intervention_count
                if intervention_count is None
                else intervention_count
            ),
            mechanism_family=mechanism_family or state.mechanism_family,
            holdout_state=holdout_state or state.holdout_state,
            variables=state.variables if variables is None else variables,
            consumed_approval_ids=(
                state.consumed_approval_ids
                if consumed_approval_ids is None
                else consumed_approval_ids
            ),
            graph_proposals=state.graph_proposals if proposals is None else proposals,
            last_outcome=result.outcome if result is not None else state.last_outcome,
            last_failure_code=(
                result.failure_code if result is not None else state.last_failure_code
            ),
            pending_approval_permission_id=None,
            pending_interrupt_after_node_id=None,
            inflight_idempotency_key=None,
            terminal_reason=reason,
        )
        self._append_state_event(
            state=terminal,
            event_type=event_type,
            action=f"Terminate Control Graph as {status.value}",
            event_status=_loop_event_status(status),
            idempotency_key=_event_idempotency_key(
                "terminal",
                state.run_id,
                terminal.revision,
            ),
            payload={
                "reason": reason,
                "result": result.model_dump(mode="json") if result is not None else None,
            },
            output_artifact_ids=result.output_artifact_ids if result else [],
        )
        return terminal

    def _pause_for_approval(
        self,
        state: LoopRunState,
        permission_id: str,
    ) -> LoopRunState:
        paused = self._evolve(
            state,
            revision=state.revision + 1,
            status=LoopRunStatus.PAUSED,
            pending_approval_permission_id=permission_id,
        )
        self._append_state_event(
            state=paused,
            event_type="loop.approval.requested",
            action=f"Pause for approval {permission_id}",
            event_status=EventStatus.PAUSED,
            idempotency_key=_event_idempotency_key(
                "approval",
                state.run_id,
                permission_id,
            ),
            payload={"permission_id": permission_id},
        )
        return paused

    def _select_edge(
        self,
        *,
        state: LoopRunState,
        node: LoopNodeSpec,
        result: LoopNodeResult,
        approval: LoopApproval | None,
        resulting_mechanism: str,
        resulting_holdout: HoldoutState,
    ) -> LoopEdgeSpec | None:
        for edge in self._edges_by_source[node.node_id]:
            if all(
                _guard_passes(
                    guard,
                    result=result,
                    approval=approval,
                    mechanism_changed=resulting_mechanism != state.mechanism_family,
                    holdout_state=resulting_holdout,
                )
                for guard in edge.guards
            ):
                if (
                    node.compensation_node_id is not None
                    and result.side_effect_committed
                    and result.outcome
                    in {LoopNodeOutcome.FAILED, LoopNodeOutcome.BLOCKED}
                    and edge.kind != LoopEdgeKind.COMPENSATE
                ):
                    continue
                if (
                    edge.kind == LoopEdgeKind.COMPENSATE
                    and not result.side_effect_committed
                ):
                    continue
                return edge
        return None

    def _retry_failure_reason(
        self,
        *,
        state: LoopRunState,
        node: LoopNodeSpec,
        result: LoopNodeResult,
    ) -> str | None:
        policy = node.retry_policy
        if result.outcome not in policy.retryable_outcomes or not result.retryable:
            return f"node_result_not_retryable:{node.node_id}"
        if state.attempts_by_node[node.node_id] >= policy.max_attempts:
            return f"node_attempt_budget_exhausted:{node.node_id}"
        if state.retry_count >= self.spec.budget_policy.max_total_retries:
            return "total_retry_budget_exhausted"
        if policy.require_repair_hypothesis and result.repair_hypothesis is None:
            return f"retry_repair_hypothesis_missing:{node.node_id}"
        if policy.require_frozen_dimension and not result.frozen_dimensions:
            return f"retry_frozen_dimension_missing:{node.node_id}"
        return None

    def _preflight_budget_reason(
        self,
        state: LoopRunState,
        node: LoopNodeSpec,
    ) -> str | None:
        policy = self.spec.budget_policy
        usage = state.consumed_usage
        reserved = node.minimum_usage
        checks = (
            (state.step_count + 1 > policy.max_steps, "step_budget_exhausted"),
            (
                usage.tokens + reserved.tokens > policy.max_tokens,
                "token_budget_exhausted",
            ),
            (
                usage.estimated_cost_usd + reserved.estimated_cost_usd
                > policy.max_estimated_cost_usd,
                "cost_budget_exhausted",
            ),
            (
                usage.wall_time_seconds + reserved.wall_time_seconds
                > policy.max_wall_time_seconds,
                "wall_time_budget_exhausted",
            ),
            (
                usage.tool_calls + reserved.tool_calls > policy.max_tool_calls,
                "tool_budget_exhausted",
            ),
            (state.retry_count > policy.max_total_retries, "retry_budget_exhausted"),
            (state.failure_count > policy.max_failures, "failure_budget_exhausted"),
        )
        for exhausted, reason in checks:
            if exhausted:
                return reason
        return None

    def _post_result_budget_reason(
        self,
        *,
        state: LoopRunState,
        usage: LoopUsage,
        failure_count: int,
    ) -> str | None:
        policy = self.spec.budget_policy
        checks = (
            (state.step_count + 1 > policy.max_steps, "step_budget_exceeded"),
            (usage.tokens > policy.max_tokens, "token_budget_exceeded"),
            (
                usage.estimated_cost_usd > policy.max_estimated_cost_usd,
                "cost_budget_exceeded",
            ),
            (
                usage.wall_time_seconds > policy.max_wall_time_seconds,
                "wall_time_budget_exceeded",
            ),
            (usage.tool_calls > policy.max_tool_calls, "tool_budget_exceeded"),
            (failure_count > policy.max_failures, "failure_budget_exceeded"),
        )
        for exceeded, reason in checks:
            if exceeded:
                return reason
        return None

    def _permission_failure_reason(self, node: LoopNodeSpec) -> str | None:
        policy = self.spec.permission_policy
        granted = set(policy.granted_permission_ids)
        approval_required = set(policy.approval_required_permission_ids)
        for permission_id in node.required_permission_ids:
            if permission_id in granted or permission_id in approval_required:
                continue
            return f"permission_not_granted:{permission_id}"
        return None

    def _approval_for_node(
        self,
        state: LoopRunState,
        node: LoopNodeSpec,
    ) -> LoopApproval | None:
        permission_id = node.required_approval_permission_id
        if permission_id is None:
            return None
        return _approval_for_permission(state.approvals, permission_id)

    def _adaptive_holdout_forbidden(
        self,
        state: LoopRunState,
        node: LoopNodeSpec,
    ) -> bool:
        return bool(
            self.spec.holdout_policy.forbid_adaptive_after_reveal
            and state.holdout_state == HoldoutState.REVEALED
            and node.adaptive
            and not node.allowed_after_holdout_reveal
        )

    def _validate_approval_permissions(
        self,
        approvals: Sequence[LoopApproval],
    ) -> None:
        allowed = set(
            self.spec.permission_policy.approval_required_permission_ids
        )
        unknown = sorted(
            {
                approval.permission_id
                for approval in approvals
                if approval.permission_id not in allowed
            }
        )
        if unknown:
            raise LoopRuntimeError(
                "approval records reference non-approval permissions: "
                + ", ".join(unknown)
            )

    def _validate_runtime_boundary(self) -> None:
        self.spec.verify_integrity()
        validate_persistable_content(self.spec.model_dump(mode="json"))
        if self.journal.metadata.run_id == "":
            raise LoopRuntimeError("journal run identity is empty")

    def _journal_snapshot(self) -> JournalSnapshot:
        try:
            return self.journal.snapshot()
        except JournalRecoveryRequired:
            return self.journal.recover().snapshot

    def _replay_state(self, snapshot: JournalSnapshot) -> LoopRunState:
        state: LoopRunState | None = None
        for event in snapshot.events:
            if event.event_type not in _LOOP_EVENT_TYPES:
                raise LoopReplayError(
                    f"journal contains non-loop event {event.event_type}"
                )
            raw_state = event.payload.get("state")
            if event.payload.get("loop_spec_hash") != self.spec.spec_hash:
                raise LoopReplayError(
                    f"loop event {event.event_id} has the wrong spec hash"
                )
            if not isinstance(raw_state, dict):
                raise LoopReplayError(
                    f"loop event {event.event_id} lacks a state snapshot"
                )
            try:
                next_state = LoopRunState.model_validate(raw_state)
            except ValueError as exc:
                raise LoopReplayError(
                    f"loop event {event.event_id} has invalid state: {exc}"
                ) from exc
            self._validate_replayed_state(event, state, next_state)
            state = next_state
        if state is None:
            raise LoopReplayError("loop journal contains no state")
        return state

    def _validate_replayed_state(
        self,
        event: RunEvent,
        previous: LoopRunState | None,
        state: LoopRunState,
    ) -> None:
        if (
            state.run_id != self.journal.metadata.run_id
            or state.task_id != self.spec.task_id
            or state.spec_id != self.spec.spec_id
            or state.spec_hash != self.spec.spec_hash
        ):
            raise LoopReplayError("loop state identity differs from runtime boundary")
        if state.revision != event.sequence:
            raise LoopReplayError("loop state revision differs from event sequence")
        if state.current_node_id is not None and state.current_node_id not in self._nodes:
            raise LoopReplayError("loop state references an unknown node")
        expected_status = _state_event_status(state.status)
        if event.status != expected_status:
            raise LoopReplayError("event status differs from derived loop state")
        if previous is None:
            if event.event_type != "loop.started" or state.revision != 1:
                raise LoopReplayError("first loop event must be loop.started")
            return
        if state.start_request_hash != previous.start_request_hash:
            raise LoopReplayError("start request hash changed during replay")
        if state.revision != previous.revision + 1:
            raise LoopReplayError("loop state revisions are not contiguous")
        if state.step_count < previous.step_count or (
            state.step_count > previous.step_count + 1
        ):
            raise LoopReplayError("loop step count changed non-monotonically")
        _require_mapping_monotonic(
            previous.attempts_by_node,
            state.attempts_by_node,
            label="attempts",
        )
        _require_mapping_monotonic(
            previous.edge_traversals,
            state.edge_traversals,
            label="edge traversals",
        )
        if not _usage_monotonic(previous.consumed_usage, state.consumed_usage):
            raise LoopReplayError("loop usage decreased during replay")
        if (
            previous.holdout_state == HoldoutState.REVEALED
            and state.holdout_state != HoldoutState.REVEALED
        ):
            raise LoopReplayError("revealed holdout became sealed during replay")
        if not _is_prefix(
            previous.consumed_approval_ids,
            state.consumed_approval_ids,
        ):
            raise LoopReplayError("consumed approval history was rewritten")
        previous_proposals = [
            proposal.proposal_id for proposal in previous.graph_proposals
        ]
        state_proposals = [proposal.proposal_id for proposal in state.graph_proposals]
        if not _is_prefix(previous_proposals, state_proposals):
            raise LoopReplayError("graph proposal history was rewritten")
        _require_approvals_preserved(previous.approvals, state.approvals)
        if not _is_prefix(
            previous.completed_node_ids,
            state.completed_node_ids,
        ):
            raise LoopReplayError("completed-node history was rewritten")
        if not set(previous.produced_artifact_ids).issubset(
            state.produced_artifact_ids
        ):
            raise LoopReplayError("produced artifacts were removed during replay")
        self._validate_event_specific_transition(event, previous, state)

    def _validate_event_specific_transition(
        self,
        event: RunEvent,
        previous: LoopRunState,
        state: LoopRunState,
    ) -> None:
        if event.event_type == "loop.node.started":
            if (
                previous.status != LoopRunStatus.READY
                or state.status != LoopRunStatus.RUNNING
                or state.current_node_id != previous.current_node_id
                or state.step_count != previous.step_count
                or state.consumed_usage != previous.consumed_usage
                or state.variables != previous.variables
                or state.mechanism_family != previous.mechanism_family
                or state.holdout_state != previous.holdout_state
            ):
                raise LoopReplayError("node-start transition rewrote durable state")
            return
        if event.event_type == "loop.node.completed":
            if (
                previous.status != LoopRunStatus.RUNNING
                or state.status
                not in {LoopRunStatus.READY, LoopRunStatus.PAUSED}
                or state.step_count != previous.step_count + 1
                or state.completed_node_ids
                != [*previous.completed_node_ids, previous.current_node_id]
            ):
                raise LoopReplayError("node-completed transition is inconsistent")
            return
        if event.event_type == "loop.resumed":
            if (
                previous.status != LoopRunStatus.PAUSED
                or state.status != LoopRunStatus.READY
                or state.current_node_id != previous.current_node_id
                or state.step_count != previous.step_count
                or state.attempts_by_node != previous.attempts_by_node
                or state.edge_traversals != previous.edge_traversals
                or state.consumed_usage != previous.consumed_usage
                or state.variables != previous.variables
                or state.mechanism_family != previous.mechanism_family
                or state.holdout_state != previous.holdout_state
                or state.completed_node_ids != previous.completed_node_ids
                or state.produced_artifact_ids != previous.produced_artifact_ids
            ):
                raise LoopReplayError("resume transition rewrote execution state")
            return
        if event.event_type == "loop.approval.requested" and (
                previous.status != LoopRunStatus.READY
                or state.status != LoopRunStatus.PAUSED
                or state.current_node_id != previous.current_node_id
                or state.step_count != previous.step_count
                or state.consumed_usage != previous.consumed_usage
                or state.variables != previous.variables
        ):
            raise LoopReplayError("approval pause rewrote execution state")

    def _append_state_event(
        self,
        *,
        state: LoopRunState,
        event_type: str,
        action: str,
        event_status: EventStatus,
        idempotency_key: str,
        payload: dict[str, JsonValue],
        output_artifact_ids: Sequence[str] = (),
        approval_id: str | None = None,
    ) -> None:
        validate_persistable_content(state.model_dump(mode="json"))
        snapshot = self._journal_snapshot()
        sequence = len(snapshot.events) + 1
        if state.revision != sequence:
            raise LoopRuntimeError(
                f"state revision {state.revision} differs from next sequence {sequence}"
            )
        parent = snapshot.events[-1] if snapshot.events else None
        event_payload: dict[str, JsonValue] = {
            **payload,
            "loop_spec_hash": self.spec.spec_hash,
            "state": state.model_dump(mode="json"),
        }
        event = RunEvent.create(
            run_id=state.run_id,
            task_id=state.task_id,
            sequence=sequence,
            actor=self._ACTOR,
            event_type=event_type,
            status=event_status,
            action=action,
            idempotency_key=idempotency_key,
            occurred_at=self._now(),
            parent_event_id=parent.event_id if parent is not None else None,
            parent_event_hash=parent.event_hash if parent is not None else None,
            output_artifact_ids=list(output_artifact_ids),
            approval_id=approval_id,
            payload=event_payload,
        )
        self.journal.append(
            event,
            expected_lineage_hash=snapshot.lineage_hash,
        )

    def _package(
        self,
        state: LoopRunState,
        journal_snapshot: JournalSnapshot,
    ) -> LoopRunSnapshot:
        package = LoopRunSnapshot.create(
            spec=self.spec,
            state=state,
            journal_snapshot=journal_snapshot,
        )
        validate_persistable_content(package.model_dump(mode="json"))
        return package

    def _node(self, node_id: str | None) -> LoopNodeSpec:
        if node_id is None or node_id not in self._nodes:
            raise LoopRuntimeError(f"unknown current loop node: {node_id}")
        return self._nodes[node_id]

    @staticmethod
    def _evolve(state: LoopRunState, **updates: Any) -> LoopRunState:
        payload = state.model_dump(mode="json")
        payload.update(updates)
        return LoopRunState.model_validate(payload)

    def _fault(self, phase: str, node_id: str) -> None:
        if self.fault_injector is not None:
            self.fault_injector(phase, node_id)

    def _now(self) -> datetime:
        return _require_utc(self.clock(), label="Control Graph clock")


_LOOP_EVENT_TYPES = frozenset(
    {
        "loop.started",
        "loop.resumed",
        "loop.node.started",
        "loop.node.completed",
        "loop.node.terminal",
        "loop.approval.requested",
        "loop.terminal",
        "loop.budget.blocked",
        "loop.retry.blocked",
        "loop.holdout.blocked",
        "loop.holdout.failed",
        "loop.permission.blocked",
        "loop.proposal.blocked",
        "loop.proposal.failed",
    }
)


def _guard_passes(
    guard: LoopGuardSpec,
    *,
    result: LoopNodeResult,
    approval: LoopApproval | None,
    mechanism_changed: bool,
    holdout_state: HoldoutState,
) -> bool:
    if guard.kind == LoopGuardKind.ALWAYS:
        return True
    if guard.kind == LoopGuardKind.OUTCOME:
        return result.outcome in guard.outcomes
    if guard.kind == LoopGuardKind.APPROVAL_DECISION:
        return bool(
            approval is not None and approval.decision in guard.approval_decisions
        )
    if guard.kind == LoopGuardKind.MECHANISM_CHANGED:
        return mechanism_changed
    return holdout_state in guard.holdout_states


def _fallback_terminal_status(
    result: LoopNodeResult,
    approval: LoopApproval | None,
) -> LoopRunStatus:
    if (
        approval is not None
        and approval.decision == LoopApprovalDecision.REJECTED
    ):
        return LoopRunStatus.REJECTED
    mapping = {
        LoopNodeOutcome.SUCCEEDED: LoopRunStatus.FAILED,
        LoopNodeOutcome.NEGATIVE_RESULT: LoopRunStatus.NEGATIVE_RESULT,
        LoopNodeOutcome.FAILED: LoopRunStatus.FAILED,
        LoopNodeOutcome.BLOCKED: LoopRunStatus.BLOCKED,
    }
    return mapping[result.outcome]


def _loop_event_status(status: LoopRunStatus) -> EventStatus:
    mapping = {
        LoopRunStatus.SUCCEEDED: EventStatus.SUCCEEDED,
        LoopRunStatus.NEGATIVE_RESULT: EventStatus.NEGATIVE_RESULT,
        LoopRunStatus.FAILED: EventStatus.FAILED,
        LoopRunStatus.BLOCKED: EventStatus.BLOCKED,
        LoopRunStatus.REJECTED: EventStatus.REJECTED,
        LoopRunStatus.CANCELLED: EventStatus.CANCELLED,
        LoopRunStatus.ESCALATED: EventStatus.BLOCKED,
    }
    return mapping[status]


def _state_event_status(status: LoopRunStatus) -> EventStatus:
    if status in TERMINAL_LOOP_STATUSES:
        return _loop_event_status(status)
    if status == LoopRunStatus.PAUSED:
        return EventStatus.PAUSED
    return EventStatus.STARTED


def _approval_result(approval: LoopApproval) -> LoopNodeResult:
    if approval.decision == LoopApprovalDecision.APPROVED:
        return LoopNodeResult(
            outcome=LoopNodeOutcome.SUCCEEDED,
            summary="Required human approval was granted.",
            approval_decision=approval.decision,
        )
    return LoopNodeResult(
        outcome=LoopNodeOutcome.BLOCKED,
        summary="Required human approval was rejected.",
        failure_code="human_rejected",
        retryable=False,
        approval_decision=approval.decision,
    )


def loop_result_from_episode(episode: EpisodePackage) -> LoopNodeResult:
    """Project one verified harness episode into provider-neutral loop semantics."""

    episode.verify_integrity()
    outcome_by_status = {
        EpisodeOutcomeStatus.SUCCEEDED: LoopNodeOutcome.SUCCEEDED,
        EpisodeOutcomeStatus.NEGATIVE_RESULT: LoopNodeOutcome.NEGATIVE_RESULT,
        EpisodeOutcomeStatus.FAILED: LoopNodeOutcome.FAILED,
        EpisodeOutcomeStatus.BLOCKED: LoopNodeOutcome.BLOCKED,
    }
    outcome = outcome_by_status[episode.final_outcome.status]
    usage = LoopUsage(
        tokens=sum(cost.total_tokens for cost in episode.costs),
        estimated_cost_usd=sum(
            cost.estimated_cost_usd for cost in episode.costs
        ),
        wall_time_seconds=sum(cost.wall_time_seconds for cost in episode.costs),
        tool_calls=sum(cost.tool_calls for cost in episode.costs),
    )
    failure_code: str | None = None
    retryable = False
    if outcome == LoopNodeOutcome.FAILED:
        failure_code = "harness_failed"
        retryable = any(failure.retryable for failure in episode.failures)
    elif outcome == LoopNodeOutcome.BLOCKED:
        failure_code = "harness_blocked"
        retryable = any(failure.retryable for failure in episode.failures)
    failure_codes: list[JsonValue] = []
    failure_codes.extend(failure.code for failure in episode.failures)
    failure_codes.sort(key=str)

    return LoopNodeResult(
        outcome=outcome,
        summary=episode.final_outcome.summary,
        usage=usage,
        output_artifact_ids=list(episode.final_outcome.artifact_ids),
        variable_updates={
            "harness_episode_hash": episode.episode_hash,
            "harness_episode_id": episode.episode_id,
            "harness_episode_status": episode.final_outcome.status.value,
            "harness_failure_codes": failure_codes,
            "harness_journal_lineage_hash": episode.journal_lineage_hash,
            "harness_journal_seal_hash": episode.journal_seal_hash,
            "harness_spec_hash": episode.harness_spec_hash,
        },
        failure_code=failure_code,
        retryable=retryable,
    )


def _node_idempotency_key(
    run_id: str,
    spec_hash: str,
    node_id: str,
    attempt: int,
) -> str:
    digest = canonical_sha256(
        {
            "run_id": run_id,
            "spec_hash": spec_hash,
            "node_id": node_id,
            "attempt": attempt,
        }
    )
    return f"loop:node:{digest}"


def _event_idempotency_key(label: str, *parts: object) -> str:
    digest = canonical_sha256({"label": label, "parts": list(parts)})
    return f"loop:{label}:{digest}"


def _add_usage(left: LoopUsage, right: LoopUsage) -> LoopUsage:
    return LoopUsage(
        tokens=left.tokens + right.tokens,
        estimated_cost_usd=(
            left.estimated_cost_usd + right.estimated_cost_usd
        ),
        wall_time_seconds=left.wall_time_seconds + right.wall_time_seconds,
        tool_calls=left.tool_calls + right.tool_calls,
    )


def _usage_monotonic(left: LoopUsage, right: LoopUsage) -> bool:
    return bool(
        right.tokens >= left.tokens
        and right.estimated_cost_usd >= left.estimated_cost_usd
        and right.wall_time_seconds >= left.wall_time_seconds
        and right.tool_calls >= left.tool_calls
    )


def _normalize_approvals(
    approvals: Sequence[LoopApproval],
) -> list[LoopApproval]:
    by_permission: dict[str, LoopApproval] = {}
    approval_ids: set[str] = set()
    for approval in approvals:
        if approval.approval_id in approval_ids:
            raise ValueError("approval IDs must be unique")
        approval_ids.add(approval.approval_id)
        if approval.permission_id in by_permission:
            raise ValueError("only one decision is allowed per permission")
        by_permission[approval.permission_id] = approval
    return [by_permission[key] for key in sorted(by_permission)]


def _merge_approvals(
    existing: Sequence[LoopApproval],
    new: Sequence[LoopApproval],
) -> list[LoopApproval]:
    by_permission = {approval.permission_id: approval for approval in existing}
    by_id = {approval.approval_id: approval for approval in existing}
    for approval in new:
        same_id = by_id.get(approval.approval_id)
        if same_id is not None:
            if same_id != approval:
                raise LoopRuntimeError(
                    f"approval ID {approval.approval_id} changed content"
                )
            continue
        if approval.permission_id in by_permission:
            raise LoopRuntimeError(
                f"permission {approval.permission_id} already has a decision"
            )
        by_permission[approval.permission_id] = approval
        by_id[approval.approval_id] = approval
    return [by_permission[key] for key in sorted(by_permission)]


def _approval_for_permission(
    approvals: Sequence[LoopApproval],
    permission_id: str,
) -> LoopApproval | None:
    return next(
        (
            approval
            for approval in approvals
            if approval.permission_id == permission_id
        ),
        None,
    )


def _sorted_unique(values: Sequence[str], *, label: str) -> list[str]:
    normalized = sorted(values)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label} must be unique")
    return normalized


def _sorted_nonnegative_mapping(
    values: Mapping[str, int],
    *,
    label: str,
) -> dict[str, int]:
    if any(value < 0 for value in values.values()):
        raise ValueError(f"{label} values must be non-negative")
    return {key: values[key] for key in sorted(values)}


def _require_mapping_monotonic(
    previous: Mapping[str, int],
    current: Mapping[str, int],
    *,
    label: str,
) -> None:
    for key, value in previous.items():
        if current.get(key, -1) < value:
            raise LoopReplayError(f"{label} decreased for {key}")


def _require_approvals_preserved(
    previous: Sequence[LoopApproval],
    current: Sequence[LoopApproval],
) -> None:
    current_by_id = {approval.approval_id: approval for approval in current}
    for approval in previous:
        if current_by_id.get(approval.approval_id) != approval:
            raise LoopReplayError(
                f"approval {approval.approval_id} changed during replay"
            )


def _is_prefix(previous: Sequence[str], current: Sequence[str]) -> bool:
    return list(current[: len(previous)]) == list(previous)


def _reachable_from(
    start: str,
    adjacency: Mapping[str, Sequence[str]],
) -> set[str]:
    seen: set[str] = set()
    queue: deque[str] = deque([start])
    while queue:
        node_id = queue.popleft()
        if node_id in seen:
            continue
        seen.add(node_id)
        queue.extend(adjacency[node_id])
    return seen


def _reverse_reachable(
    starts: set[str],
    reverse: Mapping[str, Sequence[str]],
) -> set[str]:
    seen: set[str] = set()
    queue: deque[str] = deque(sorted(starts))
    while queue:
        node_id = queue.popleft()
        if node_id in seen:
            continue
        seen.add(node_id)
        queue.extend(reverse[node_id])
    return seen


def _guard_has_outcome(
    guards: Sequence[LoopGuardSpec],
    outcome: LoopNodeOutcome,
) -> bool:
    return any(
        guard.kind == LoopGuardKind.OUTCOME and outcome in guard.outcomes
        for guard in guards
    )


def _guard_has_approval(
    guards: Sequence[LoopGuardSpec],
    decision: LoopApprovalDecision,
) -> bool:
    return any(
        guard.kind == LoopGuardKind.APPROVAL_DECISION
        and decision in guard.approval_decisions
        for guard in guards
    )


def _require_utc(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{label} must be timezone-aware UTC")
    return value.astimezone(timezone.utc)


def _safe_error_message(error: BaseException) -> str:
    message = (str(error).strip() or type(error).__name__)[:1024]
    try:
        validate_persistable_content(message)
    except SensitiveContentError:
        return "Sensitive error details were suppressed."
    return message
