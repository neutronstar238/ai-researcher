# AutoResearch vNext Compatibility and Migration Guide

Status: internal compatibility boundary R1

Task: `262.10`

Effective date: 2026-07-29

Public release or submission authority: **not granted**

## What changed

AutoResearch now pins and characterizes the LangGraph 1.x runtime while keeping the project-owned
Event Journal and Control Graph authoritative. The upgrade is deliberately narrower than a product
or scientific release:

- `langgraph==1.2.10`
- `langchain==1.3.14`
- `langchain-core==1.5.2`
- `langgraph-checkpoint==4.1.1`
- `langgraph-prebuilt==1.1.0`
- `langgraph-sdk==0.4.2`
- `langsmith==0.10.11`

The exact graph-stack versions are checked against both `poetry.lock` and the installed
environment. At the implementation point, the lock SHA-256 is
`9e1894adecae09877114222fded4251113618dd9fe967668201153559573bbad` and the
content-addressed dependency audit is
`2e31dccf9c69af830bc0dfb8337085138ec633357e525ae0aa401b15af9a6fab`.
Regenerate these values only through a reviewed dependency task; a mismatch closes R1.

The pre-upgrade and post-upgrade behavior reports are frozen:

| Runtime | Version | Characterization SHA-256 | Result |
|---|---:|---|---|
| LangGraph baseline | 0.2.76 / Core 0.2.43 | `92983004c099b14799cd4102b644072013016541ae3da659e7380161b448fb3e` | checkpoint/resume, static/dynamic interrupt, subgraph, parallel superstep, resume idempotency, and JSON state passed |
| LangGraph target | 1.2.10 / Core 1.5.2 | `dd62c3faef638b905755dbc26f6761957e5657175de7a3b641b6e5c718ebebd3` | the same seven behaviors passed |

LangGraph remains an adapter. Durable domain state is reconstructed from the sealed Event Journal;
a LangGraph checkpoint is never accepted as the scientific source of truth.

## Persisted-state migration inventory

| Surface | New writes | Existing reads | Migration | Rollback target |
|---|---|---|---|---|
| LangGraph adapter checkpoints | In-memory only, strict JSON-plus serializer with no pickle fallback or custom module allowlist | No repository or production persistent checkpoint store exists | None required; no checkpoint bytes are rewritten | Revert the dependency pins and reinstall the previous lock before introducing a persistent checkpointer |
| `audit/audit.jsonl` | Retired; new audit events go only to `audit/audit.journal/` | Retained for one compatibility window | On the first new append, valid legacy events are imported in order; the JSONL file remains unchanged and read-only | `AuditLog.export_legacy_snapshot()` creates an explicit validated JSONL snapshot at a new operator-chosen path |
| `agents/workflow.py` JSON checkpoints | Deprecated compatibility writer remains callable | Retained for one compatibility window | No bulk conversion; new durable work must use `ControlGraphRuntime` | Continue reading the v1 JSON checkpoint while the compatibility window is open |
| Competition legacy state | Retained because the scientific engine still writes it | Retained | vNext is a parity-checked journal/graph lifecycle projection | `AUTORESEARCH_COMPETITION_MIGRATION_MODE=legacy` |
| Campaign legacy state | Retained because the scientific engine still writes it | Retained | vNext is a parity-checked journal/graph lifecycle projection | `AUTORESEARCH_CAMPAIGN_MIGRATION_MODE=legacy` |
| Sprint legacy state | Retained because the scientific engine still writes it | Retained | vNext is a parity-checked journal/graph lifecycle projection | `AUTORESEARCH_SPRINT_MIGRATION_MODE=legacy` |
| `EvidenceGraph` v1 | Retained for current readers and projections | Retained | Provenance v2 is additive and content addressed; historical v1 evidence is not rewritten | Continue with the v1 reader and the frozen source artifacts |

This inventory is intentionally asymmetric. The two formal vertical runs and rollback rehearsal
prove the Sprint lifecycle boundary and justify retiring the shallow audit JSONL writer. They do
not prove that the legacy scientific writers or EvidenceGraph v1 can be deleted. Those paths remain
until a later task migrates their actual scientific write semantics and repeats the parity gates.

## Compatibility and schema policy

- Writers emit only the current schema.
- Readers support the current schema plus one prior compatibility generation.
- The named window is `vnext-plus-one-release`; it is not shortened by time alone.
- Removing a retained reader requires a new task, usage audit, migration fixture, two distinct
  formal runs where applicable, rollback rehearsal, and a focused commit.
- Historical run artifacts, revealed panels, scientific endpoints, journal events, and provenance
  bundles are immutable. There is no in-place or bulk rewrite.
- Unknown schema versions, unknown dependency versions, incomplete formal evidence, a failed
  rollback, or an enabled protected action fail closed.

## R1 evidence and independent reproduction

R1 consumes two different persisted real Sprints:

- `task261-bounded-autonomous-clean-v1`, formal ID `task262-sprint-formal-1`;
- `task261-bounded-autonomous-clean-v2`, formal ID `task262-sprint-formal-2`.

Both are verified scientific negative results with different source fingerprints and independently
sealed journal lineages. The smoke does not rerun or reinterpret the model, literature search,
experiment, manuscript, or paper. It verifies the stored parity reports and journals after the
dependency upgrade.

The same adoption smoke projects the persisted blocked Sprint
`task261-bounded-autonomous-live-v1` under vNext authority and rehearses the return to
`AUTORESEARCH_SPRINT_MIGRATION_MODE=legacy`. A second opt-in smoke:

1. audits the exact dependency lock and installed versions;
2. executes the LangGraph 1.x characterization;
3. reopens and verifies both formal journals and parity reports;
4. revalidates the rollback report;
5. launches `python -I -m autoresearch.runtime.release` in a separate process and clean directory
   to reproduce the canonical evidence digest without network access;
6. emits a content-addressed `vnext-release-report.json`.

The R1 report cannot be persisted as passing when any nested result, hash, version, compatibility
decision, capability claim, or approval boundary is inconsistent.

## Rollback procedure

1. Stop new work at a safe run boundary. Do not modify or delete existing journals.
2. For Competition, Campaign, or Sprint, set the corresponding migration mode to `legacy` and run
   that service's status/parity check.
3. If the dependency upgrade itself must be reverted, restore the pre-`262.10` `pyproject.toml` and
   `poetry.lock`, run `poetry install --sync`, and rerun the frozen 0.2 characterization before
   accepting work. This is safe only while the adapter has no persistent LangGraph checkpoint
   store; the domain Event Journal remains readable because it is runtime-neutral.
4. If an older audit consumer is unavoidable, call `AuditLog.export_legacy_snapshot()` to a new
   path, verify it with the retained reader, then point the isolated old consumer at that snapshot.
   Do not resume dual writes and do not overwrite the original JSONL.
5. Re-run the service rollback rehearsal and the full quality gates. Record any mismatch in
   `Problem.md`.

## Truthful capability matrix

| Capability | R1 status | What the status does not mean |
|---|---|---|
| Atomic event journal, replay, fork, and seal | Verified locally | Not a trusted execution environment or external attestation |
| Bounded HarnessSpec and episode package | Verified locally, one provider-neutral adapter contract | Not unrestricted tool or cloud execution |
| Durable Control Graph and LangGraph 1.x adapter | Verified locally | LangGraph checkpoints are not the domain truth |
| Provenance/evidence v2 | Verified over frozen real artifacts | Does not prove an external fact merely because lineage is complete |
| Open Science research objects | Verified for internal/review views | No upload, DOI minting, public release, or submission occurred |
| Competition/Campaign/Sprint vNext lifecycle | Parity and rollback verified | Their legacy scientific engines are not yet removed |
| Unified evaluation and Agentic security matrix | Verified on the bounded local suite | Not a substitute for expensive external benchmarks |
| Unrestricted execution | Human-approval gated | Disabled by R1 |
| Public release | Human-approval gated | Disabled by R1 |
| External submission | Human-approval gated | Disabled by R1 |
| Safety-policy self-modification | Human-approval gated | Disabled by R1 |

R1 is an **internal compatibility release boundary**, not a claim that AutoResearch autonomously
discovered a novel result, is production-ready for arbitrary workloads, or may publish on a
person's behalf.

## Verification commands

```powershell
poetry check --lock
poetry run python -m pytest tests/unit/runtime/test_loop_langgraph.py tests/unit/runtime/test_vnext_release.py -q
poetry run python -m pytest tests/unit/observability/test_audit.py tests/unit/knowledge/test_rollback.py -q
poetry run python -m pytest -q
poetry run ruff check .
poetry run mypy src/autoresearch
```

The two opt-in smokes are run in order with fresh output directories:

```powershell
$env:AUTORESEARCH_SPRINT_MIGRATION_LIVE='1'
$env:AUTORESEARCH_SPRINT_MIGRATION_OUTPUT='runs/manual-live/task262-sprint-migration-release-live-v1'
poetry run python -m pytest tests/smoke/test_sprint_migration_live.py -q

$env:AUTORESEARCH_VNEXT_RELEASE_LIVE='1'
$env:AUTORESEARCH_VNEXT_RELEASE_MIGRATION_ROOT='runs/manual-live/task262-sprint-migration-release-live-v1/migration'
$env:AUTORESEARCH_VNEXT_RELEASE_OUTPUT='runs/manual-live/task262-vnext-release-live-v1'
poetry run python -m pytest tests/smoke/test_vnext_release_live.py -q
```

## Upstream compatibility basis

- [LangGraph v1 migration guide](https://docs.langchain.com/oss/python/migrate/langgraph-v1)
- [LangChain v1 migration guide](https://docs.langchain.com/oss/python/migrate/langchain-v1)
- [LangGraph persistence and checkpoint semantics](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangChain/LangGraph versioning policy](https://docs.langchain.com/oss/python/versioning)
- [LangGraph checkpoint package and serializer safety notice](https://pypi.org/project/langgraph-checkpoint/)

The project relies on its own frozen tests and lock audit rather than treating upstream semantic
versioning as sufficient evidence of application compatibility.
