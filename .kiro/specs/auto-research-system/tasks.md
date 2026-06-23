# Implementation Plan: AI-Researcher

## Overview

This task plan turns the two root planning documents into executable engineering work:

- `AutoResearch_System_Research_Plan.md`
- `AutoResearch_System_Execution_Plan.md`

The project must be built in the order described by those plans: first a minimal trusted research loop, then automation, then self-looping research, then controlled self-evolution, and only later productization.

The MVP is not "an AI that writes papers." The MVP is a reproducible computational research loop:

```text
research direction
  -> literature search
  -> knowledge records
  -> hypothesis
  -> experiment task
  -> generated runnable code
  -> sandbox execution
  -> result collection
  -> validation
  -> Markdown report with evidence links
```

Core innovation: the Obsidian-compatible knowledge vault is the system's shared memory and evolution substrate. Its canonical project-root path is `autoresearch-vault/`. It is not a replaceable storage detail. The vault must connect global exploration, per-project knowledge, experiment records, issues, failures, skills, evidence, strategy versions, topic indexes, wiki-links, and rollback history so the system can self-loop and self-evolve while staying human-readable and auditable.

Networked discovery is mandatory, not optional. The Obsidian vault is the evidence memory layer, not a substitute for external search. Project-start novelty checks, similar-direction cross-validation, and scheduled candidate refresh must query external sources such as ArXiv and OpenAlex before relying on local vault memory; Semantic Scholar is an optional enhancement source when enabled or keyed. Summaries written to the vault must cite source documents, query text, retrieval timestamps, and unsupported/unknown claims explicitly; never fabricate results, citations, rankings, or experimental outcomes.

## Source References

- `RP`: `AutoResearch_System_Research_Plan.md`
- `EP`: `AutoResearch_System_Execution_Plan.md`
- `REQ`: `.kiro/specs/auto-research-system/requirements.md`
- `DES`: `.kiro/specs/auto-research-system/design.md`

## Global Execution Rules

- [ ] Work on one task or subtask at a time.
- [ ] Before implementing a non-trivial task, state the assumptions and success criteria.
- [ ] Keep changes surgical and tied to the active task.
- [ ] Update `Agent.md` after every file-changing task.
- [ ] Update `Problem.md` when a blocker, defect, failed command, unclear requirement, or skipped verification appears.
- [ ] After a task or subtask is completed and verified, create one focused git commit for that completed task or subtask.
- [ ] Do not mark a task complete if verification is blocked.
- [ ] Do not claim planned capabilities as implemented capabilities in README or docs.
- [ ] Treat `autoresearch-vault/` as the canonical Obsidian knowledge substrate unless a task explicitly says otherwise.

## Definition of Done

A task can be checked only when all applicable items are true:

- [ ] Code or documentation changes are complete.
- [ ] Acceptance checks in the task have passed.
- [ ] New or changed behavior has focused tests, unless the task is documentation-only.
- [ ] `Agent.md` records files changed, summary, verification, problems, and follow-up.
- [ ] `Problem.md` is updated for any known issue.
- [ ] A focused git commit exists for the completed task or subtask.

## Tasks

### Phase 0: Project Governance and Engineering Baseline (Weeks 0-2)

- [x] 0. Establish repository governance and documentation baseline
  - [x] 0.1 Create agent collaboration instructions
    - Add `AGENTS.md` as repository-wide instructions for future coding agents.
    - Require agents to read plans, tasks, problems, and prior change logs before non-trivial edits.
    - Define MVP priority order: trusted loop, evidence graph, paper draft, multi-agent automation, self-loop, controlled self-evolution, productization.
    - _References: RP 1-3, EP 1, EP 20_
    - _Verify: `AGENTS.md` exists and mentions `Agent.md`, `Problem.md`, task-driven work, verification, and safety rules._

  - [x] 0.2 Create agent development standard and change log
    - Add `Agent.md`.
    - Include development standards, task discipline, change scope, verification expectations, problem tracking, and git version management.
    - Require one focused git commit after each completed and verified task or subtask.
    - Include an entry template for future agents.
    - Add the initial Codex documentation bootstrap entry.
    - _References: User project convention request, EP 16.2_
    - _Verify: `Agent.md` contains both "Development Standard" and "Git Version Management" sections._

  - [x] 0.3 Create problem tracking document
    - Add `Problem.md`.
    - Define statuses, severity values, and a reusable problem entry template.
    - Record the initial scaffold issue discovered during repository inspection.
    - _References: EP 6, EP 20.2, DES Error Handling_
    - _Verify: `Problem.md` exists and contains `P-20260611-001`._

  - [x] 0.4 Rewrite README as open-source landing pages
    - Replace the root `README.md` with an English default project page.
    - Add `README.zh-CN.md` as the Chinese page.
    - Link English to Chinese and Chinese back to English.
    - Describe status accurately as planning/scaffold, not completed runtime.
    - Include architecture, roadmap, repository layout, setup notes, docs links, contribution rules, and license status.
    - _References: User README request, RP 13, EP 18_
    - _Verify: both README files exist; English README links to `README.zh-CN.md`; Chinese README links to `README.md`._

  - [x] 0.5 Rewrite this executable task plan
    - Replace the leftover task plan with a detailed executable plan based on `RP` and `EP`.
    - Preserve the Kiro-style checkbox structure.
    - Add verification notes and source references to each task group.
    - Include git commit discipline as a global rule and completion requirement.
    - _References: User tasks request, RP final judgment, EP full plan_
    - _Verify: this file contains Phase 0 through Phase 5 and a task dependency graph._

  - [x] 0.6 Audit current scaffold against documented claims
    - Inspect `pyproject.toml`, `src/autoresearch/__init__.py`, and `src/autoresearch/config/__init__.py`.
    - Identify missing modules and CLI entry point before claiming tests can pass.
    - Record the issue in `Problem.md`.
    - _References: EP 3.3, DES Installation and Configuration_
    - _Verify: `Problem.md` includes the missing config and CLI scaffold issue._

  - [x] 0.7 Reconcile the plan with Kiro's core Obsidian and self-evolution design
    - Read Kiro `requirements.md` and `design.md` sections for Agent evolution, Knowledge Base structure, permissions, knowledge auto-evolution, version history, and Obsidian rationale.
    - Promote Obsidian-compatible Markdown vault from a storage detail to the central self-loop and self-evolution substrate.
    - Update README, `AGENTS.md`, `Problem.md`, and this task plan so future agents preserve the original product idea.
    - _References: REQ 2, REQ 6, REQ 7, REQ 8, REQ 28, DES Knowledge Base Component, DES Obsidian rationale_
    - _Verify: docs mention Obsidian as the unified knowledge substrate and `Problem.md` records `P-20260611-002` as resolved._

- [x] 1. Repair Python package scaffold so basic imports are honest
  - [x] 1.1 Add config data models
    - Create `src/autoresearch/config/models.py`.
    - Define minimal Pydantic models: `SystemConfig`, `AgentConfig`, `ComputeConfig`, `KnowledgeBaseConfig`, `LiteratureConfig`.
    - Keep defaults small and local-first.
    - Include fields needed by Phase 1 only: project root, knowledge root, sandbox defaults, literature database list, logging level, cost limits.
    - _References: EP 3.5, EP 13, REQ 30_
    - _Verify: `python -c "from autoresearch.config import SystemConfig"` succeeds._

  - [x] 1.2 Add config parser
    - Create `src/autoresearch/config/parser.py`.
    - Support YAML, TOML, and JSON.
    - Return descriptive errors for malformed files and missing required fields.
    - Add `ConfigFormat` enum or equivalent typed discriminator.
    - Avoid custom string parsing when library parsers are available.
    - _References: EP 14.2, REQ 30, DES Property 13 and Property 36_
    - _Verify: unit tests cover valid YAML/TOML/JSON and one invalid file per format._

  - [x] 1.3 Add minimal CLI skeleton
    - Create `src/autoresearch/cli/main.py`.
    - Expose a Typer app matching `pyproject.toml`.
    - Add `airesearcher version`, `airesearcher doctor`, and `airesearcher init-demo` commands.
    - `doctor` should check Python version, import health, config parser availability, and planned directory roots.
    - Do not add research workflow execution yet.
    - _References: EP 3.3, DES CLI Interface_
    - _Verify: `poetry run airesearcher version` and `poetry run airesearcher doctor` run without import errors._

  - [x] 1.4 Add test scaffold
    - Create `tests/unit`, `tests/integration`, `tests/property`, and `tests/smoke`.
    - Add a smoke test for importing `autoresearch`.
    - Add a smoke test for importing `autoresearch.config`.
    - Add a CLI smoke test for the Typer app without invoking external services.
    - _References: EP 14, DES Testing Strategy_
    - _Verify: `poetry run pytest tests/smoke tests/unit/config` passes._

  - [x] 1.5 Add repository quality commands
    - Confirm `ruff`, `black`, `mypy`, and `pytest` settings match actual package layout.
    - Adjust config only if commands fail because of stale paths or missing test directories.
    - Do not relax quality rules unless a specific rule blocks legitimate Phase 0 code.
    - _References: EP 16.2, DES Development Guidelines_
    - _Verify: `poetry run ruff check src tests`, `poetry run mypy src`, and focused `pytest` pass._

- [x] 2. Define core schemas and run identity
  - [x] 2.1 Implement research lifecycle schemas
    - Add data models for `DocumentRecord`, `KnowledgeNode`, `ResearchCandidate`, `Hypothesis`, `ExperimentTask`, `ExecutionRun`, `ResultBundle`, `EvidenceEdge`, `PaperDraft`, and `StrategyCard`.
    - Place them in a clear module such as `src/autoresearch/schemas/`.
    - Include stable IDs, timestamps, provenance fields, status fields, and validation status.
    - Keep fields minimal for MVP and add extension points only where the plans require them.
    - _References: EP 3.5, EP 12, RP 6_
    - _Verify: unit tests instantiate each schema and serialize to JSON._

  - [x] 2.2 Add run ID and provenance helpers
    - Implement deterministic helper functions for run IDs, config hashes, data hashes, and artifact references.
    - Ensure every `ExecutionRun` can store commit SHA, config hash, data hash, start/end time, status, metrics path, artifact URI, and cost JSON.
    - _References: EP 11.3, EP 12.2, RP 6.2_
    - _Verify: unit tests cover stable hash generation and unique run ID generation._

  - [x] 2.3 Add schema round-trip tests
    - Add tests for JSON serialization and deserialization of each core schema.
    - Add tests that reject missing required evidence fields.
    - Add tests that preserve unknown optional metadata only if explicitly supported.
    - _References: DES Correctness Properties_
    - _Verify: `poetry run pytest tests/unit/schemas -vv` passes._

- [x] 3. Establish logging, audit, and cost foundations
  - [x] 3.1 Add structured logging
    - Implement a logger factory that includes `run_id`, component name, task ID, and project ID when available.
    - Keep output human-readable locally and JSON-compatible for future observability.
    - _References: EP 3.3, EP 15_
    - _Verify: unit test confirms log records include run context._

  - [x] 3.2 Add audit event schema
    - Define audit event types for permission checks, sandbox denials, config changes, approval gates, strategy changes, and publication gates.
    - Store audit events as append-only JSONL in a local project audit directory for MVP.
    - _References: RP 3.3, EP 17, DES Audit Logging_
    - _Verify: unit tests append and reload audit events without loss._

  - [x] 3.3 Add cost record schema
    - Define token input/output, model name, CPU time, GPU hours, storage artifact size, network cost placeholder, and human approval count.
    - Ensure cost records can attach to `ExecutionRun`.
    - _References: EP 11.3, RP 8.2_
    - _Verify: schema test validates required cost fields and numeric bounds._

- [x] 4. Add continuous integration baseline
  - [x] 4.1 Add GitHub Actions workflow
    - Add a workflow for Python 3.10.
    - Run install, ruff, mypy, and pytest.
    - Keep external network/API tests excluded by default.
    - _References: EP 3.3, EP 16.2_
    - _Verify: workflow file exists and local commands match CI commands._

  - [x] 4.2 Add local developer check command
    - Add a documented command or script for `ruff`, `mypy`, and `pytest`.
    - Prefer a small script only if it reduces repeated command drift.
    - _References: AGENTS.md Verification Expectations_
    - _Verify: command runs locally or the blocker is recorded in `Problem.md`._

  - [x] 4.3 Add release gate checklist
    - Document release requirements: unit tests pass, golden tests do not regress, security tests pass, docs updated, migrations reversible, changelog/tag complete.
    - Put release details in README or a dedicated docs file only if needed.
    - _References: EP 16.2_
    - _Verify: release gate is linked from README or tasks._

### Phase 1: Minimal Trusted Research Loop (Weeks 3-8)

- [x] 5. Build Obsidian unified knowledge vault MVP
  - [x] 5.1 Create Obsidian vault contract and directory layout
    - Implement the vault root at project-root `autoresearch-vault/`.
    - Create `autoresearch-vault/exploration/` for global cross-project knowledge.
    - Create `autoresearch-vault/exploration/topics/`, `autoresearch-vault/exploration/skills/`, `autoresearch-vault/exploration/methodologies/`, `autoresearch-vault/exploration/datasets/`, `autoresearch-vault/exploration/failure_patterns/`, `autoresearch-vault/exploration/strategy_cards/`, and `autoresearch-vault/exploration/index.md`.
    - Create `autoresearch-vault/projects/<project-id>/knowledge/`, `autoresearch-vault/projects/<project-id>/progress/`, `autoresearch-vault/projects/<project-id>/issues/`, `autoresearch-vault/projects/<project-id>/experience/`, `autoresearch-vault/projects/<project-id>/experiments/`, `autoresearch-vault/projects/<project-id>/results/`, `autoresearch-vault/projects/<project-id>/evidence/`, and `autoresearch-vault/projects/<project-id>/paper/`.
    - Keep the layout compatible with plain filesystem access and Obsidian GUI use.
    - _References: REQ 6, DES Knowledge Base Structure, DES Obsidian rationale_
    - _Verify: unit test creates the full vault layout in a temp directory and confirms all required folders and index files exist._

  - [x] 5.2 Implement Markdown knowledge entry model
    - Store all knowledge entries as Markdown files with YAML frontmatter.
    - Include stable entry ID, entry type, zone, project ID, tags, keywords, source refs, created/updated timestamps, and related task/run IDs.
    - Support entry types: Paper Note, Dataset Card, Method Card, Experiment Record, Failure Case, Skill Card, Strategy Card, Evidence Note, Project Progress, Issue Note, and Review Note.
    - Keep entries readable in Obsidian without custom rendering.
    - _References: RP 6.3, REQ 6.4, DES Knowledge Base Interface_
    - _Verify: tests write and read each entry type while preserving frontmatter and body._

  - [x] 5.3 Add Obsidian wiki-links, backlinks, and topic index
    - Support `[[entry-id]]` or `[[path|label]]` wiki-link syntax.
    - Maintain bidirectional links between literature, hypotheses, experiments, evidence, failures, skills, and strategies.
    - Maintain a topic index mapping keywords to relevant entries.
    - Update links and index when entries are created or modified.
    - _References: REQ 6.5, REQ 6.6, DES Knowledge Base Interface, DES Property 18, DES Property 21_
    - _Verify: tests create linked literature, experiment, and skill entries and confirm backlinks plus topic index retrieval._

  - [x] 5.4 Enforce zone and project permissions
    - Implement `PermissionManager` for Main Agent, Fixed Agents, Project Agents, and future Validator Agents.
    - Main and Fixed Agents may read/write authorized global and project areas.
    - Project Agents may read Exploration Zone and write only their own Project Zone directory.
    - Every write operation must call permission checks before touching the vault.
    - Denied writes must produce audit events and leave target files unchanged.
    - _References: REQ 7, DES Access Control Matrix, DES Property 19, DES Property 20_
    - _Verify: property tests deny cross-project writes and confirm Main Agent universal access._

  - [x] 5.5 Add Obsidian-friendly version history, backups, and rollback
    - Preserve previous versions of modified Markdown entries.
    - Support manual rollback to a previous version.
    - Create automatic vault backups at a configurable interval between 1 and 26 hours.
    - Store version metadata so users can inspect history in Obsidian and Git.
    - _References: REQ 8.6, REQ 28, DES Property 22_
    - _Verify: tests modify an entry N times and confirm N+1 versions are retrievable and rollback restores prior content._

- [x] 6. Build literature retrieval MVP
  - [x] 6.1 Implement academic paper model and deduplication
    - Define structured paper metadata with title, authors, abstract, date, venue, DOI, URL, citation count, and source.
    - Deduplicate by DOI first and title similarity second.
    - _References: RP 5.2, EP 4.3, REQ 9_
    - _Verify: property test removes DOI duplicates and high-similarity title duplicates._

  - [x] 6.2 Implement ArXiv, OpenAlex, and optional Semantic Scholar clients
    - Start with free/public academic APIs first, and keep Semantic Scholar optional when rate limits or credentials make it unsuitable as a default source.
    - Add rate limiting and retry backoff.
    - Keep CNKI, WanFang, DBLP, and PubMed as later extensions unless a task explicitly needs them.
    - _References: EP 4.3, REQ 9_
    - _Verify: mocked client tests pass; one optional live smoke test is documented and skipped by default._

  - [x] 6.3 Implement retrieval cache
    - Cache successful search responses for 24 hours.
    - Cache key must include query, source, page/limit, and relevant config.
    - _References: DES Literature Retrieval Pipeline_
    - _Verify: test confirms repeated identical query uses cache and different query misses cache._

  - [x] 6.4 Store paper notes in knowledge base
    - Convert retrieved paper metadata into `DocumentRecord` and Markdown note.
    - Include source URL/DOI and retrieval timestamp.
    - Do not summarize beyond available metadata until the summarizer exists.
    - _References: RP 6.3, REQ 11_
    - _Verify: integration test retrieves mocked papers and writes knowledge entries._

- [x] 7. Implement research candidate and hypothesis workflow
  - [x] 7.1 Generate research candidates from retrieved literature
    - Build a simple candidate generator using recent paper clusters, repeated limitations, datasets, and methods.
    - Score novelty, feasibility, expected impact, evidence coverage, and estimated cost.
    - Mark low-evidence candidates as draft, not ready.
    - _References: RP 8, EP 6.3, REQ 12_
    - _Verify: unit test ranks sample candidates deterministically._

  - [x] 7.2 Add human approval gate for candidate selection
    - Candidate must be approved before a project directory and Project Agent are created.
    - Approval record must include user, timestamp, candidate ID, and notes.
    - _References: RP 3.3, EP 17_
    - _Verify: test rejects project creation without approval record._

  - [x] 7.3 Generate hypotheses
    - Convert an approved candidate into one or more `Hypothesis` records.
    - Each hypothesis must include measurable prediction, target dataset or benchmark, baseline, metric, and evidence references.
    - _References: RP 2.2, RP 5, EP 4.3_
    - _Verify: schema validation fails hypotheses without metric or evidence references._

- [x] 8. Implement experiment task design and code generation MVP
  - [x] 8.1 Convert hypotheses into experiment tasks
    - Implement a deterministic planner that creates `ExperimentTask` records.
    - Include code entry point, dataset assumptions, metrics, resource budget, timeout, expected outputs, and validation checks.
    - _References: EP 4.3, REQ 15_
    - _Verify: unit tests confirm required fields and budget limits._

  - [x] 8.2 Generate minimal runnable experiment directories
    - Create an experiment directory with `README.md`, `config.yaml`, `requirements.txt`, `run.py`, `logs/`, and expected `metrics.json`.
    - Use small local demo tasks first.
    - Generated code must write logs and metrics even when the experiment fails gracefully.
    - _References: EP 21, REQ 15_
    - _Verify: generated demo experiment runs locally and writes `metrics.json`._

  - [x] 8.3 Add generated code review checks
    - Check for dangerous commands, path traversal, secret reads, unrestricted network access, and missing metric writes before execution.
    - Reject or quarantine unsafe generated code.
    - _References: EP 17, REQ 16, DES Security Considerations_
    - _Verify: tests detect representative unsafe patterns._

- [x] 9. Build sandbox executor MVP
  - [x] 9.1 Implement local sandbox path restrictions
    - Allow read/write only within the experiment directory and configured cache/output directories.
    - Deny access to project root secrets and user home secrets.
    - _References: EP 17.1, REQ 16_
    - _Verify: property tests block attempts to access paths outside the sandbox._

  - [x] 9.2 Implement runtime limits
    - Enforce timeout, memory limit, and process cleanup for local subprocess execution.
    - Store exit code, stdout, stderr, start/end time, and limit violations in `ExecutionRun`.
    - _References: REQ 16, DES Experiment Execution Workflow_
    - _Verify: tests cover timeout and nonzero exit code handling._

  - [x] 9.3 Add restricted network policy placeholder
    - Define allowed domains for academic APIs and package sources.
    - For MVP, document unsupported enforcement clearly if OS-level network sandboxing is not implemented yet.
    - Record any unsupported enforcement in `Problem.md`.
    - _References: EP 17.2, REQ 16.3_
    - _Verify: tests confirm policy data structure and audit logging for blocked requests where enforceable._

- [x] 10. Collect and validate results
  - [x] 10.1 Implement result collector
    - Parse `metrics.json`, configured CSV outputs, logs, and generated artifacts.
    - Produce `ResultBundle`.
    - Reject missing metric files unless the experiment explicitly failed.
    - _References: EP 4.3, REQ 19_
    - _Verify: unit tests parse valid results and reject incomplete result directories._

  - [x] 10.2 Implement validation report
    - Validate run completion, metric presence, metric bounds, artifact existence, config hash, data hash, and cost record.
    - Store validation output as Markdown and JSON.
    - _References: RP 7, EP 14_
    - _Verify: tests cover pass, warning, and fail validation states._

  - [x] 10.3 Add evidence binding
    - Convert validated metrics into `EvidenceEdge` records.
    - Prevent report generation from using metrics without evidence binding.
    - _References: RP 6.2, RP 10_
    - _Verify: unit test blocks claim generation from unvalidated result bundles._

- [x] 11. Generate MVP research report
  - [x] 11.1 Generate Markdown report from evidence
    - Report sections: question, literature summary, hypothesis, experiment design, run metadata, results, validation, limitations, next steps.
    - Every quantitative claim must link to an evidence ID and artifact path.
    - _References: RP 10, EP 4.3, EP 21_
    - _Verify: snapshot test confirms required sections and evidence links._

  - [x] 11.2 Add report readability checks
    - Validate table formatting, link existence, heading order, and missing evidence references.
    - Keep checks deterministic and local.
    - _References: EP 14.1, RP 10.3_
    - _Verify: report lint test fails on broken evidence links._

  - [x] 11.3 Build reproducibility notes
    - Include command, Python version, dependency lock status, run ID, commit SHA, config hash, and data hash.
    - _References: EP 18.1, RP 15_
    - _Verify: generated report includes reproducibility block._

- [x] 12. Create ScientistBench-Lite MVP checks
  - [x] 12.1 Add local demo task `tabular_baseline`
    - Use a tiny public or synthetic dataset that can run quickly on CPU.
    - Include baseline metric and expected artifact list.
    - _References: EP 14.3_
    - _Verify: full loop completes under the configured local timeout._

  - [x] 12.2 Add local demo task `text_classifier_stub`
    - Use a tiny fixture dataset or mocked vectorizer.
    - Focus on loop correctness, not model quality.
    - _References: EP 14.3_
    - _Verify: full loop produces metrics and validation report._

  - [x] 12.3 Add MVP end-to-end command
    - Provide a CLI command or script that runs one demo from direction to report.
    - Persist outputs under a project demo directory.
    - _References: EP 21_
    - _Verify: command creates code, logs, metrics, validation report, evidence map, and Markdown report._

  - [x] 12.4 Establish MVP acceptance run
    - Run 5 to 10 small tasks when available.
    - Target at least 60 percent full-loop success and 80 percent rerun success for successful tasks.
    - Record failures in `Problem.md` and failure library.
    - _References: EP 4.4_
    - _Verify: acceptance report exists with run IDs and rerun outcomes._

### Phase 2: Automated Research Assistant (Weeks 9-16)

- [x] 13. Implement multi-agent runtime
  - [x] 13.1 Add base Agent class and registry
    - Define agent ID, role, capabilities, permissions, lifecycle state, and task execution contract.
    - Add registry operations for add, remove, get, list, and capability query.
    - _References: RP 5, REQ 1, DES Agent Architecture_
    - _Verify: property tests cover registry consistency and unique IDs._

  - [x] 13.2 Add structured message protocol
    - Define message fields: message ID, from agent, to agent, task ID, intent, input refs, expected output schema, deadline, budget, and risk level.
    - Reject unstructured free-text-only messages for inter-agent task execution.
    - _References: RP 5.3_
    - _Verify: schema tests reject messages missing intent or expected output schema._

  - [x] 13.3 Integrate LangGraph for stateful workflows
    - Model the research pipeline as resumable workflow states.
    - Add checkpoint and resume support for long-running projects.
    - _References: EP 9, DES Technology Stack_
    - _Verify: integration test pauses and resumes a mock workflow._

- [x] 14. Build evidence graph
  - [x] 14.1 Implement claim-evidence-source graph
    - Model `Claim -> Evidence -> Source -> Artifact -> ValidationStatus`.
    - Store graph as JSON for MVP and keep database migration optional.
    - _References: RP 6.2, EP 5.3_
    - _Verify: tests traverse from claim to source artifact and validation state._

  - [x] 14.2 Enforce evidence coverage
    - Require every core claim to have at least one evidence edge.
    - Mark unsupported claims as draft or blocked.
    - _References: EP 5.4, RP 10_
    - _Verify: paper/report generation fails when a core claim has no evidence._

  - [x] 14.3 Add evidence consistency checks
    - Check that metric values in text, tables, and figures match source result files.
    - _References: EP 5.4, REQ 22_
    - _Verify: tests catch a deliberate table/text mismatch._

- [x] 15. Add baseline, ablation, and statistics support
  - [x] 15.1 Implement baseline reproducer
    - Reproduce at least one baseline before running a proposed method.
    - Store baseline config, run ID, metrics, and validation state.
    - _References: EP 5.3, RP 10.3_
    - _Verify: demo project has a validated baseline run._

  - [x] 15.2 Add ablation planner
    - Generate a minimal ablation matrix based on hypothesis variables.
    - Avoid combinatorial explosion by requiring budget limits.
    - _References: EP 5.3_
    - _Verify: planner output respects max experiment count and cost budget._

  - [x] 15.3 Add statistical sanity checks
    - Provide simple confidence interval or repeated-run comparison where appropriate.
    - Do not overstate significance when sample size is too small.
    - _References: RP 7, EP 14_
    - _Verify: validation report labels underpowered comparisons clearly._

- [x] 16. Build scientific figures and tables
  - [x] 16.1 Generate publication-quality figure artifacts
    - Use source result files only.
    - Generate vector PDF where possible and PNG preview where useful.
    - Use consistent style across figures.
    - _References: REQ 22, EP 5.3_
    - _Verify: tests confirm figure files exist and data source paths are recorded._

  - [x] 16.2 Generate comparison tables
    - Create method comparison and ablation tables from validated metrics.
    - Include run IDs or evidence IDs in machine-readable table metadata.
    - _References: RP 10, EP 5.4_
    - _Verify: table values match metrics file values._

  - [x] 16.3 Add figure/table consistency validator
    - Validate that figures, tables, and report text do not disagree.
    - _References: EP 5.4_
    - _Verify: validator fails on injected mismatch._

- [x] 17. Build paper draft pipeline
  - [x] 17.1 Generate LaTeX skeleton from evidence
    - Sections: abstract, introduction, related work, method, experiments, results, limitations, conclusion.
    - Insert placeholders only when evidence is missing; do not fabricate.
    - _References: RP 10, REQ 20_
    - _Verify: LaTeX skeleton compiles for a demo project._

  - [x] 17.2 Generate BibTeX from verified citations
    - Use DOI/URL when available.
    - Mark unverifiable citations as blocked.
    - _References: REQ 20, RP 11_
    - _Verify: citation validator reports DOI/URL status._

  - [x] 17.3 Add paper draft versioning
    - Store draft versions with timestamps and source evidence graph version.
    - _References: REQ 28_
    - _Verify: generating a second draft preserves the first version._

- [x] 18. Add review simulator and quality gates
  - [x] 18.1 Implement review dimensions
    - Score novelty, technical soundness, experimental rigor, reproducibility, writing quality, and compliance.
    - Calibrate scores conservatively; never auto-score perfect results by default.
    - _References: RP 10.3, REQ 24, REQ 29_
    - _Verify: tests confirm missing evidence lowers technical soundness and reproducibility._

  - [x] 18.2 Add venue criteria configuration
    - Support generic and venue-specific review criteria.
    - Fall back to generic criteria when venue rules are absent.
    - _References: REQ 25_
    - _Verify: tests load default and custom criteria._

  - [x] 18.3 Feed review findings into task backlog
    - Convert actionable review comments into follow-up tasks or problem entries.
    - _References: RP 12, EP 5.3_
    - _Verify: demo review creates structured follow-up records._

- [x] 19. Build reproducibility package
  - [x] 19.1 Package code, config, metrics, reports, and evidence map
    - Include environment notes, run commands, artifact manifest, and validation status.
    - Exclude secrets and large raw data unless explicitly configured.
    - _References: EP 5.3, EP 18.2_
    - _Verify: package manifest lists every included artifact with hash._

  - [x] 19.2 Add package validation
    - Validate that package commands and paths are self-contained.
    - _References: RP 15_
    - _Verify: validation command reports pass/fail and missing artifacts._

### Phase 3: Self-Loop Research Platform (Weeks 17-24)

- [x] 20. Build Obsidian-backed research candidate pool
  - [x] 20.1 Store candidate lifecycle
    - Track candidate status: draft, ready_for_review, approved, active, completed, rejected, archived.
    - Store candidates as Obsidian Markdown entries under `autoresearch-vault/exploration/topics/` or a dedicated candidate folder linked from `autoresearch-vault/exploration/index.md`.
    - Link each candidate to source papers, topic index entries, prior failures, useful skills, and related strategy cards.
    - _References: RP 8, EP 6.3_
    - _Verify: unit tests cover legal status transitions and confirm candidate wiki-links are written._

  - [x] 20.2 Add trend and gap analyzer
    - Generate candidate updates from recent literature and knowledge base gaps.
    - Require source evidence for each gap.
    - Compare recent literature against Obsidian topic indexes, method cards, dataset cards, and prior project experience.
    - _References: REQ 12, REQ 6, EP 6.3_
    - _Verify: analyzer output includes evidence references and vault paths._

- [x] 21. Add scheduler for recurring work
  - [x] 21.1 Implement local task scheduler
    - Support daily/weekly candidate refresh and queued experiment checks.
    - Keep external orchestrators optional.
    - The scheduled candidate refresh must call the literature retrieval layer before trend/gap analysis.
    - Use Horizon-style pipeline separation: configured sources, fetch, deduplicate, score/filter, enrich, summarize or persist.
    - _References: EP 6.3, RP 8_
    - _Verify: scheduler runs a mock recurring task and records audit logs._

  - [x] 21.2 Add daily online literature refresh pipeline
    - Fetch fresh papers and research materials automatically from free/public sources, starting with ArXiv and OpenAlex.
    - Respect source-specific API limits; ArXiv legacy API access must use a single connection and at least 3 seconds between requests.
    - Optimize search queries from project topics, Obsidian topic indexes, method cards, dataset cards, prior failures, and active candidate gaps.
    - Store raw metadata, normalized `DocumentRecord` items, source query text, timestamps, and rate-limit decisions in the Obsidian vault or retrieval cache.
    - Deduplicate results across sources before candidate update analysis.
    - _References: REQ 12, REQ 6, Horizon-style source pipeline, arXiv API terms_
    - _Verify: unit tests cover query generation, deduplication, cache reuse, and mocked rate-limited daily refresh without network access; opt-in live smoke test fetches real ArXiv/OpenAlex documents before completion._

  - [x] 21.3 Add project-start online similarity and novelty cross-check
    - Before a candidate is approved into a project, run a broad online search for similar directions, adjacent methods, known baselines, datasets, negative results, and competing claims.
    - Generate multiple query variants from candidate title, research gap, method, dataset, limitation, Obsidian topic index context, and prior failure/skill cards.
    - Cross-check online results against local vault entries and classify each finding as direct duplicate, adjacent work, supporting prior work, contradictory evidence, benchmark gap, or unknown.
    - Store the structured similarity summary in Obsidian under `autoresearch-vault/exploration/topics/` before project creation, and link it into `autoresearch-vault/projects/<project-id>/knowledge/` after approval.
    - Include source URL/DOI, source database, query text, retrieval timestamp, evidence refs, and confidence/unsupported markers for every summarized finding.
    - Do not invent paper results, benchmark scores, citations, venue status, code availability, or experimental outcomes. Missing evidence must be written as `unknown` or `pending verification`.
    - _References: REQ 12, REQ 6, RP 3.3, RP 8, Horizon-style source pipeline_
    - _Verify: mocked online search writes an Obsidian similarity summary with source-backed findings and rejects unsupported claims._

  - [x] 21.4 Add budget-aware execution gates
    - Pause or require approval when a task approaches 80 percent of budget.
    - _References: EP 15.2, RP 3.3_
    - _Verify: test triggers budget approval state._

- [x] 22. Build Obsidian failure library
  - [x] 22.1 Record failed runs as first-class knowledge
    - Capture error type, logs, config, environment, hypothesis, experiment task, and suspected cause.
    - Store failure cases as Markdown entries under `autoresearch-vault/exploration/failure_patterns/` and link project-local copies from `autoresearch-vault/projects/<project-id>/issues/`.
    - Link each failure to the run, experiment, evidence status, and any strategy or skill that should change.
    - _References: RP 6.3, RP 12, REQ 2.4, EP 6.3_
    - _Verify: failed demo run creates a failure case entry with Obsidian wiki-links to run and project issue notes._

  - [x] 22.2 Classify recurring failure patterns
    - Group failures by dependency, data, runtime, metric, citation, permission, cost, and validation causes.
    - Update global failure pattern notes when similar failures repeat.
    - Feed repeated failure patterns into skill extraction and strategy proposal tasks.
    - _References: REQ 8.1, REQ 8.4, RP 12_
    - _Verify: tests classify representative failure records and update a shared failure pattern note._

- [x] 23. Build Obsidian skill library
  - [x] 23.1 Extract reusable skill cards
    - Convert repeated successful patterns into skill cards with trigger conditions, actions, success metrics, and examples.
    - Store skills under `autoresearch-vault/exploration/skills/` with usage examples linked to project experience notes and failure patterns.
    - Skills must be retrievable by ID, tags, keywords, and wiki-links.
    - _References: REQ 2.3, REQ 2.5, REQ 8.5, RP 9.3, EP 6.3_
    - _Verify: successful pattern examples generate a skill card in the vault._

  - [x] 23.2 Retrieve skills for similar tasks
    - Match new tasks to skill cards based on trigger conditions and metadata.
    - Search both structured frontmatter and Obsidian topic links.
    - _References: REQ 2.6, DES Property 8, DES Property 9_
    - _Verify: property tests retrieve the expected skill for generated similar tasks._

- [x] 24. Add monitoring and reporting
  - [x] 24.1 Track system metrics
    - Metrics: task success rate, reproduction rate, validator rejection rate, cost per success, human interventions, agent loop depth, rollback count, citation error rate, evidence coverage.
    - _References: EP 15.1_
    - _Verify: metrics are computed from fixture run history._

  - [x] 24.2 Add local dashboard export
    - Produce a static HTML or Markdown status report before building a full web dashboard.
    - Include costs, failure rates, evidence coverage, and active project state.
    - _References: EP 8, EP 15_
    - _Verify: export renders from sample metrics without external services._

- [x] 25. Implement rollback foundations
  - [x] 25.1 Version strategy, config, and knowledge entries
    - Track versions for prompts, workflow templates, configs, and knowledge records.
    - Store strategy-related knowledge in Obsidian Markdown with version history and rollback metadata.
    - _References: REQ 28, RP 9.4, EP 6.3_
    - _Verify: tests roll back a fixture config, strategy card, and knowledge entry._

  - [x] 25.2 Add rollback audit trail
    - Record who or what triggered rollback, reason, old version, new version, and verification result.
    - _References: EP 7.4, DES Audit Logging_
    - _Verify: rollback event appears in audit JSONL._

### Phase 4: Controlled Self-Evolution (Weeks 25-36)

- [x] 26. Build strategy library
  - [x] 26.1 Define strategy card schema
    - Cover prompt templates, workflow templates, tool routing policy, retrieval policy, experiment search policy, scheduling policy, and validation policy.
    - Explicitly exclude safety policy, approval gates, license policy, and publication rules from automatic mutation.
    - Store each strategy card as an Obsidian Markdown entry under `autoresearch-vault/exploration/strategy_cards/` with machine-readable frontmatter and human-readable rationale.
    - Link strategies to failure patterns, skill cards, replay results, golden tests, shadow evaluations, and rollback targets.
    - _References: REQ 2, REQ 8, RP 9.1, EP 7.3_
    - _Verify: schema rejects prohibited strategy targets and writes a linkable strategy card._

  - [x] 26.2 Add strategy versioning
    - Track parent strategy, candidate strategy, evaluation score, golden test status, shadow status, release status, and rollback target.
    - _References: EP 12.2, RP 9.2_
    - _Verify: tests preserve lineage from parent to candidate._

- [x] 27. Build offline replay and golden tests
  - [x] 27.1 Create replay dataset from historical tasks
    - Store enough inputs, outputs, evidence, costs, and validation outcomes to replay strategy changes offline.
    - _References: EP 7.3, RP 9.2_
    - _Verify: replay fixture reproduces expected baseline score._

  - [x] 27.2 Create golden test set
    - Fix a regression suite of known tasks covering literature retrieval, config parsing, sandbox denial, result validation, citation validation, and report generation.
    - _References: EP 7.3_
    - _Verify: current stable strategy passes all golden tests before comparison._

- [x] 28. Add shadow evaluation
  - [x] 28.1 Run candidate strategies in shadow mode
    - Candidate strategy can observe and produce proposed outputs but cannot affect production results.
    - _References: RP 9.2, EP 7.3_
    - _Verify: shadow output is recorded separately and production output remains unchanged._

  - [x] 28.2 Compare strategy rewards
    - Calculate reward from quality gain, reproducibility, evidence completeness, compute cost, human intervention, and risk penalty.
    - _References: RP 8.2_
    - _Verify: reward calculation test covers improvement, cost increase, and risk penalty cases._

- [x] 29. Add gray release and automatic rollback
  - [x] 29.1 Promote strategies through approval and gray release
    - Require golden test pass, no safety regression, evidence coverage not reduced, and human approval before gray release.
    - Start gray release at a small traffic share.
    - _References: EP 7.4, RP 9.4_
    - _Verify: promotion fails without approval or golden test pass._

  - [x] 29.2 Roll back negative strategies
    - Automatically roll back after repeated negative reward or safety incident.
    - Freeze the strategy family until reviewed.
    - _References: RP 12 Scenario C_
    - _Verify: simulated negative reward triggers rollback event._

- [x] 30. Generate evolution reports
  - [x] 30.1 Summarize strategy changes
    - Report reason, evidence, evaluation, reward delta, risks, release history, rollback target, and final decision.
    - _References: EP 7.3, RP 9.4_
    - _Verify: report includes all required fields and links to strategy cards._

  - [x] 30.2 Add human-readable audit review
    - Produce a compact review document for maintainers before strategy promotion.
    - _References: RP 3.3_
    - _Verify: promotion workflow links to audit review._

### Phase 5: Productization and Open-Source Readiness (Future)

- [x] 31. Design product surface before building full dashboard
  - [x] 31.1 Define dashboard users and workflows
    - Users: individual researcher, team lead, reviewer, system administrator.
    - Workflows: candidate review, run monitoring, validation review, paper draft review, cost inspection, rollback approval.
    - _References: RP 13, EP 8_
    - _Verify: product brief exists before dashboard implementation._

  - [x] 31.2 Build dashboard MVP only after Phase 1 is stable
    - Show project status, runs, metrics, failures, costs, evidence coverage, and approval queue.
    - Avoid marketing-style landing pages inside the app.
    - _References: EP 8, Build Web Apps plugin perspective_
    - _Verify: browser-based UI test covers desktop and mobile layout._

- [x] 32. Add multi-user permissions
  - [x] 32.1 Define roles and project permissions
    - Roles: owner, maintainer, researcher, reviewer, admin.
    - Permissions: project read, project write, approve high-cost run, approve full-permission run, approve publication, manage strategies.
    - _References: EP 8, RP 3.3_
    - _Verify: authorization tests cover allowed and denied actions._

- [x] 33. Add plugin system
  - [x] 33.1 Define plugin interfaces
    - Literature source plugins, experiment framework plugins, compute provider plugins, notification plugins, report export plugins.
    - _References: EP 8, DES Plugin System_
    - _Verify: sample plugin loads and can be disabled safely._

- [x] 34. Add deployment packages
  - [x] 34.1 Create Docker Compose deployment
    - Include app runtime, optional database, artifact storage path, and environment template.
    - _References: EP 8, DES Deployment Architecture_
    - _Verify: container starts and `doctor` command passes._

  - [x] 34.2 Plan Kubernetes deployment
    - Add Helm chart only after Docker Compose is stable.
    - Include resource limits, secrets handling, persistent volumes, and health checks.
    - _References: EP 8_
    - _Verify: chart lint passes when chart exists._

- [x] 35. Add compliance, cost, and SLA controls
  - [x] 35.1 Add license scanner integration
    - Check datasets, third-party code, and generated packages for license metadata.
    - _References: RP 11, EP 17_
    - _Verify: scanner reports missing license metadata as warning or failure according to policy._

  - [x] 35.2 Add cost management
    - Track project budget, GPU hours, API token cost, storage cost, and alerts.
    - _References: EP 11, EP 15_
    - _Verify: cost alert triggers at 80 percent threshold._

  - [x] 35.3 Add service health and SLA metrics
    - Track queue latency, run failure rate, validator latency, dashboard health, and scheduler health.
    - _References: EP 8, EP 15_
    - _Verify: health endpoint or report includes all metrics._

- [x] 36. Prepare public release
  - [x] 36.1 Choose and add license
    - Select a license before public redistribution.
    - Update README license section.
    - _References: README License_
    - _Verify: `LICENSE` exists and README links to it._

  - [x] 36.2 Add contribution guide
    - Document development setup, task workflow, commit rule, testing gates, problem log, and code review expectations.
    - _References: AGENTS.md, Agent.md_
    - _Verify: `CONTRIBUTING.md` exists and links to `AGENTS.md`._

  - [x] 36.3 Add changelog and release notes
    - Track user-visible changes by version.
    - Include migration notes and known problems.
    - _References: EP 16_
    - _Verify: `CHANGELOG.md` has an unreleased section._

- [x] 37. Add first-deploy onboarding CLI and slash command templates
  - [x] 37.1 Add provider-agnostic deployment config
    - Store LLM provider label, API base URL, model name, and API key environment variable name without binding to one vendor.
    - Store WeChat and Feishu channel settings as environment-variable references so secrets stay in `.env`.
    - _References: user deploy CLI request, OpenClaw onboarding/configure/channel model, Hermes model no-lock-in pattern_
    - _Verify: config model tests confirm deployment defaults and channel secret env references._

  - [x] 37.2 Add first-deploy CLI setup command
    - Add `airesearcher deploy-setup`.
    - Prompt interactively for provider, base URL, model name, API key, and optional WeChat/Feishu channel credentials.
    - Support `--non-interactive` scripted deployment with explicit flags.
    - Write API keys and channel secrets only to `.env`; write non-secret deployment metadata to `config.yaml`.
    - _References: OpenClaw `setup`/`onboard`/`configure` split, user API-key and channel setup request_
    - _Verify: CLI tests confirm config and `.env` output and reject enabled channels without credentials._

  - [x] 37.3 Add project slash command templates
    - Add `airesearcher slash-commands init` and `airesearcher slash-commands list`.
    - Create project-scoped TOML prompt templates for literature refresh, similarity check, local demo run, and status review.
    - _References: Gemini CLI project-scoped TOML slash command pattern_
    - _Verify: CLI tests confirm template files are written and listed._

- [x] 38. Add operator CLI for real online discovery
  - [x] 38.1 Add daily literature refresh CLI
    - Add `airesearcher literature-refresh`.
    - Read Obsidian vault context, call real literature APIs, preserve source fetch errors, and write guarded Obsidian summaries.
    - _References: user real-network discovery requirement, tasks 21.2 and 37.3_
    - _Verify: mocked CLI unit test passes and a real CLI run writes a source-backed literature refresh summary._

  - [x] 38.2 Add project-start similarity check CLI
    - Add `airesearcher similarity-check --candidate-file`.
    - Accept Windows UTF-8 BOM candidate JSON, call real literature APIs, write source-backed similarity findings, and optionally link the report into a project vault.
    - _References: user project-start cross-check requirement, tasks 21.3 and 37.3_
    - _Verify: mocked CLI unit tests pass and a real CLI run writes exploration and project Obsidian notes._

- [x] 39. Add release notice and visible local environment template
  - [x] 39.1 Add Apache-2.0 NOTICE file
    - Add root `NOTICE` with project attribution required by the current public-release package.
    - Link README license sections to `NOTICE`.
    - _References: user NOTICE request, task 36.1_
    - _Verify: `NOTICE` exists and contains the requested AI Researcher copyright and Apache License notice._

  - [x] 39.2 Add root `.env` template for model testing handoff
    - Add tracked `.env.example` with provider-agnostic LLM fields and optional WeChat/Feishu channel fields.
    - Add an ignored local `.env` placeholder so the user can fill real model credentials before full-chain LLM testing.
    - Document that `.env` is git-ignored and should hold real secrets only locally.
    - _References: user request to fill a model in `.env`, task 37.2_
    - _Verify: `.env.example` and ignored local `.env` exist; `git check-ignore .env` confirms `.env` is not tracked._

- [x] 40. Fix first-deploy environment semantics and CI mypy portability
  - [x] 40.1 Make deploy setup own the environment template path
    - Ensure `airesearcher deploy-setup` writes the real local `.env` and creates adjacent `.env.example` when that public template is missing.
    - Preserve an existing `.env.example` instead of overwriting local or repository template edits.
    - Document that `.env.example` is a public non-secret template and `.env` is the ignored real secret file.
    - _References: user feedback on first-deploy CLI `.env` flow, task 37.2_
    - _Verify: CLI tests confirm `.env` receives secrets, `.env.example` contains no secrets, and existing templates are preserved._

  - [x] 40.2 Fix GitHub Actions mypy failure on non-Windows runners
    - Avoid direct static access to the Windows-only `subprocess.CREATE_NEW_PROCESS_GROUP` attribute on Linux type-checking runners.
    - Remove stale mypy override entries that trigger unused-config warnings.
    - _References: GitHub Actions screenshot for Python 3.10 `mypy src` failure_
    - _Verify: `poetry run mypy src` passes without the Windows-only subprocess attribute error._

- [x] 41. Add live LLM deployment smoke and quality gate
  - [x] 41.1 Add provider-agnostic LLM smoke client
    - Read `config.yaml` plus ignored `.env`, call the configured OpenAI-compatible chat completions endpoint, and avoid binding to one vendor SDK.
    - Require structured JSON output from the model and capture token usage when returned by the provider.
    - Redact API keys from API error messages and fail if a model response leaks a key-shaped secret.
    - _References: user DeepSeek live deployment request, task 37.2_
    - _Verify: unit tests cover output quality scoring and live CLI smoke calls the configured model._

  - [x] 41.2 Add CLI output quality inspection
    - Add `airesearcher llm-smoke`.
    - Write a JSON quality report under ignored `runs/`.
    - Check non-empty output, valid JSON, status, summary, evidence-policy language, risks, next steps, secret leakage, and fake URL leakage.
    - _References: user output quality inspection request_
    - _Verify: `poetry run airesearcher llm-smoke --config config.yaml --env-path .env` passes against the configured DeepSeek model._

  - [x] 41.3 Convert live smoke suite to real API coverage
    - Add a live LLM smoke test.
    - Use `AUTORESEARCH_LIVE_APIS=1` as the shared switch for real LLM and literature API smoke tests.
    - Keep mocked unit tests only for parser/control-flow coverage, not for claiming external integration success.
    - _References: user request to change smoke checks to real API calls_
    - _Verify: live smoke tests pass with real LLM, ArXiv, literature refresh, and similarity-check API calls._

  - [x] 41.4 Run user-style full-chain deployment check
    - Configure DeepSeek V4 Flash through `airesearcher deploy-setup`.
    - Run `doctor`, `llm-smoke`, `literature-refresh`, `similarity-check`, `run-demo`, and deterministic report lint.
    - Record source errors and output quality findings without claiming unavailable provider success.
    - _References: user request to deploy as a user and inspect full flow_
    - _Verify: all full-chain CLI commands pass; report lint returns zero issues._

- [x] 42. Fix Python 3.10 CI test collection compatibility
  - [x] 42.1 Make observability logging importable on Python 3.10
    - Remove runtime use of the Python 3.11+ `logging.LoggerAdapter[...]` generic form from the logging adapter base class.
    - Keep the structured logging behavior unchanged for run, project, task, and component context fields.
    - Reproduce the GitHub Actions failure locally under Python 3.10 before validating the fix.
    - _References: user-provided GitHub Actions Python 3.10 log, task 40.2_
    - _Verify: Python 3.10 Poetry environment runs `pytest tests/smoke tests/unit`, `ruff`, and `mypy` successfully._

- [x] 43. Harden real literature API access and smoke-test boundaries
  - [x] 43.1 Add Semantic Scholar throttling, optional API key, and 429 circuit breaker
    - Load optional `SEMANTIC_SCHOLAR_API_KEY` from `.env` for online discovery commands.
    - Send the API key through the Semantic Scholar `x-api-key` header when present.
    - Use a more conservative unauthenticated Semantic Scholar rate limit, exponential retry backoff for transient errors, and a 429 circuit breaker to avoid repeated hammering.
    - Preserve per-source errors in literature refresh and similarity-check outputs rather than fabricating missing source results.
    - Document that `test_cli.py` and `test_imports.py` remain local installation/import smoke checks; live API smoke tests stay opt-in and explicitly named.
    - _References: user follow-up on Semantic Scholar access limits and smoke-test boundaries_
    - _Verify: unit tests cover API key headers, retry backoff, 429 circuit breaking, CLI `.env` loading, and live literature smoke tests pass against real APIs._

- [x] 44. Add evidence-constrained LLM reviewer quality gate
  - [x] 44.1 Add local-evidence LLM review CLI
    - Add `airesearcher llm-review` to call the configured provider-agnostic OpenAI-compatible model against a local subject file and one or more local evidence files.
    - Assign outer evidence IDs such as `evidence_1` and require every reviewer finding to cite only those provided IDs.
    - Treat missing evidence references, unknown nested evidence IDs, secret leakage, and fake URLs as hard quality failures below the CLI threshold.
    - Keep `test_cli.py` and `test_imports.py` local-only; use the new review command for explicit live LLM quality inspection.
    - Document the command in both README files, including the higher default review token budget needed by reasoning-token models.
    - _References: user follow-up requesting an LLM-as-reviewer second-stage quality review that must cite local evidence_
    - _Verify: unit tests cover deterministic review quality checks and CLI report writing; real DeepSeek `llm-review` passes against local run artifacts while preserving `needs_revision` findings when evidence is incomplete._

- [x] 45. Persist LLM review outcomes into Obsidian project memory
  - [x] 45.1 Add project review-note storage for evidence-constrained LLM reviews
    - Add `review/` to the project vault layout so project-level human and model review notes have a canonical Obsidian location.
    - Convert passing `llm-review` results into `KnowledgeEntryType.REVIEW_NOTE` Markdown with YAML frontmatter, subject/evidence refs, quality checks, findings, unsupported claims, next steps, and raw reviewer JSON.
    - Add `--vault`, `--project-id`, and `--source-task-id` to `airesearcher llm-review`; write to the vault only after the deterministic review quality threshold passes.
    - Preserve failed or low-quality reviewer outputs under ignored `runs/` but do not promote them into long-term project memory.
    - _References: RP Obsidian self-loop memory, task 44.1, user requirement that outputs and quality findings feed the project vault_
    - _Verify: unit tests cover review-note storage and CLI vault wiring; real DeepSeek `llm-review --project-id` writes an Obsidian `review_note` under the project review directory._

- [x] 46. Convert LLM review findings into project issue notes
  - [x] 46.1 Add review-to-issue promotion for actionable model findings
    - Convert passing `llm-review` results with `blocking`, `critical`, `high`, or `warning` findings into project `issue_note` entries under `autoresearch-vault/projects/<project-id>/issues/`.
    - Link each issue note back to the source `review_note` with an Obsidian wiki-link and preserve subject/evidence refs in frontmatter.
    - Include severity, claim, evidence refs, reviewer verdict, quality score, and next actions in each issue note.
    - Add `--write-issues/--no-write-issues` to `airesearcher llm-review`, defaulting to issue-note creation when `--project-id` is provided and the deterministic review quality gate passes.
    - _References: RP self-loop task pool, task 45.1 follow-up, user requirement that quality problems feed the project vault_
    - _Verify: unit tests cover issue-note creation and CLI wiring; real DeepSeek `llm-review --project-id` writes review and issue notes in a temporary Obsidian vault._

- [x] 47. Deduplicate LLM review issue notes for self-loop stability
  - [x] 47.1 Add stable issue fingerprints for reviewer findings
    - Generate project issue-note paths from the reviewed subject hash plus a normalized claim fingerprint, not from the model output order.
    - Skip duplicate actionable findings with the same normalized claim in one review result.
    - Preserve an explicit issue fingerprint in each note body so repeated model reviews can be audited and matched by humans.
    - Keep existing Obsidian version preservation when a repeated review updates the same issue note.
    - _References: task 46.1 follow-up, RP self-loop task pool hygiene_
    - _Verify: unit tests cover duplicate findings and reordered reviewer findings producing the same issue-note file set._

- [x] 48. Queue self-loop follow-up tasks from Obsidian issue notes
  - [x] 48.1 Add issue-note to scheduler queued-task adapter
    - Read open `KnowledgeEntryType.ISSUE_NOTE` files from `autoresearch-vault/projects/<project-id>/issues/`.
    - Generate one-shot queued scheduler tasks with stable IDs from the issue fingerprint when present, falling back to entry ID for older issue notes.
    - Skip closed issue notes and invalid Markdown/frontmatter files without blocking the scheduler.
    - Emit deterministic task metadata with issue ID, title, vault path, project ID, and related task IDs.
    - _References: task 47.1 follow-up, RP Obsidian self-loop task pool_
    - _Verify: unit tests cover open issue notes, closed issue skips, stable task IDs, and action metadata._

- [x] 49. Add operator CLI for issue follow-up task discovery
  - [x] 49.1 Expose Obsidian issue follow-ups through CLI and slash commands
    - Add `airesearcher issue-followups` to list scheduler follow-up tasks derived from open project issue notes.
    - Support `--vault`, `--project-id`, and optional JSON `--output` for review before execution.
    - Print deterministic task IDs and source issue paths without executing follow-up work.
    - Add `/research:issue-followups` to default slash command templates.
    - _References: task 48.1 follow-up, user request for CLI and slash-command style workflows_
    - _Verify: CLI unit tests cover output JSON and slash template creation._

- [x] 50. Persist issue follow-up task discovery across sessions
  - [x] 50.1 Add local scheduler state merge for issue follow-ups
    - Add optional `--state` to `airesearcher issue-followups`.
    - Merge generated issue follow-up records into a local JSON scheduler state file by stable `task_id`.
    - Re-running the command must update existing tasks rather than appending duplicates.
    - Keep the state file local/operator-controlled and do not execute tasks automatically.
    - _References: task 49.1 follow-up, RP auditable self-loop queue_
    - _Verify: CLI unit tests cover state writing and duplicate-safe merge behavior._

- [x] 51. Manage persisted scheduler-state follow-up tasks
  - [x] 51.1 Add scheduler-state list, complete, and remove CLI commands
    - Add `airesearcher scheduler-state list` for local state inspection, hiding completed tasks by default.
    - Add `airesearcher scheduler-state complete <task-id>` to mark a task record completed with a timestamp.
    - Add `airesearcher scheduler-state remove <task-id>` to delete stale local task records.
    - Preserve completed state when `issue-followups --state` rediscovers the same issue task.
    - Keep these commands local, operator-controlled, and non-executing.
    - _References: task 50.1 follow-up, RP auditable self-loop queue_
    - _Verify: CLI unit tests cover list filtering, complete, remove, missing-task failure, and completed-state preservation._

- [x] 52. Make Semantic Scholar rate policy tunable for real deployments
  - [x] 52.1 Add env-configurable Semantic Scholar rate and circuit settings
    - Keep the existing conservative unauthenticated and API-key defaults.
    - Add optional `SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS` for deployment-specific request spacing.
    - Add optional `SEMANTIC_SCHOLAR_CIRCUIT_RESET_SECONDS` for deployment-specific 429 cooldown windows.
    - Validate invalid numeric values early instead of silently using a risky rate policy.
    - Include the new settings in `.env.example` and first-deploy template generation.
    - _References: user follow-up on Semantic Scholar access limits and real external API behavior_
    - _Verify: unit tests cover env-based rate/circuit settings, invalid values, existing 429 circuit behavior, and first-deploy template output._

- [x] 53. Remove GitHub Actions Node 20 deprecation warning
  - [x] 53.1 Upgrade official checkout and setup-python actions to Node 24 majors
    - Update `actions/checkout` from `v4` to `v5`.
    - Update `actions/setup-python` from `v5` to `v6`.
    - Do not change the Python version, Poetry install path, or quality gates.
    - _References: GitHub Actions CI #21 warning, official checkout/setup-python Node 24 releases_
    - _Verify: workflow diff is limited to action major versions and pushed CI completes without the Node 20 deprecation warning._

- [x] 54. Add one-command autonomous research loop CLI
  - [x] 54.1 Add `airesearcher autopilot` orchestration command
    - Run live literature refresh, generate a source-backed candidate, run project-start similarity checking, execute the local ScientistBench-Lite loop, and write a cycle summary from one command.
    - Support `--watch --cycles 0 --interval-seconds <seconds>` for an always-on local loop after first deploy.
    - Run the evidence-constrained live LLM reviewer by default when `.env` is configured, with `--no-review` for offline dry runs.
    - Promote passing review outputs into Obsidian review/issue notes and merge issue follow-ups into local scheduler state.
    - Add `/research:autopilot` to slash command templates.
    - Document references to AI-Researcher, long-horizon auto-research roadmaps, daily literature refreshers, SkillOpt, and OpenClaw in the README.
    - _References: user request for one-command always-on CLI, SkillOpt, OpenClaw/hemenus-style operator experience_
    - _Verify: unit tests cover a non-review autopilot cycle and slash template creation; real `.env` single-cycle run calls live literature APIs and the configured live LLM reviewer._

- [x] 55. Add Obsidian vault structure and visual setup
  - [x] 55.1 Add safe Obsidian setup assets and CLI
    - Add a reusable helper that creates `Home.md`, a research-loop dashboard, Obsidian templates, plugin recommendations, and CSS snippet assets under the vault.
    - Add `airesearcher obsidian-setup` so users can structure the vault after first deploy without manually copying files.
    - Keep `.obsidian/` local and ignored by git, while allowing `--write-local-snippet` to generate a local CSS snippet for the current machine.
    - Add `/research:obsidian-setup` to slash command templates.
    - Document the command in both README files without claiming third-party plugins are bundled.
    - _References: user request for Obsidian skill/plugin structuring and vault beautification_
    - _Verify: unit tests cover helper asset generation, local snippet generation, CLI output, and slash template creation._

- [x] 56. Close live reviewer evidence-quality findings from autopilot
  - [x] 56.1 Make report reproduction metadata evidence-backed
    - Write reproduction command, Python version, dependency lock status, commit hash, config hash, and data hash into the local run record.
    - Clarify the LLM reviewer prompt so subject reports may use internal metric edge IDs when those IDs are defined in the supplied evidence map, while reviewer JSON findings must still cite outer evidence artifact IDs.
    - Add tests for run-record reproducibility evidence and prompt wording.
    - Re-run a local demo and a real `.env` LLM review against the fixed evidence bundle.
    - _References: live autopilot review issues from task `54.1`, `P-20260612-078` follow-up_
    - _Verify: focused tests pass, full smoke/unit tests pass, and real DeepSeek LLM review no longer reports reproduction metadata as unsupported._

- [x] 57. Add SkillOpt-inspired bounded skill evolution candidates
  - [x] 57.1 Create evidence-linked skill evolution candidate workflow
    - Add a skill evolution helper that creates a candidate skill card instead of mutating the parent skill.
    - Require issue or failure evidence refs, proposed actions, validation checks, rollback target, and a rejected-edit buffer.
    - Add `airesearcher skill-evolve` so operators and future autopilot loops can create bounded skill candidates from vault evidence.
    - Add `/research:skill-evolve` to slash command templates.
    - Document the command and the non-promotion rule in README files.
    - _References: user request for SkillOpt-style skill evolution, SkillOpt bounded edits and validation gates_
    - _Verify: unit tests cover candidate generation, rejected-edit buffer creation, evidence/validation requirements, CLI output, and slash template creation._

- [x] 58. Rename the public CLI and operator state namespace to `airesearcher`
  - [x] 58.1 Make `airesearcher` the canonical user-facing command
    - Replace the Poetry console script `autoresearch` with `airesearcher` to avoid name collisions with adjacent open-source projects.
    - Update README examples, Chinese README examples, slash command templates, generated vault operator commands, deployment notes, and reproducibility command output to use `airesearcher`.
    - Move default local operator state from `.autoresearch/` to `.airesearcher/` while keeping the old ignored path out of git history.
    - Keep the internal Python package import path `autoresearch` unchanged for now to avoid a broad import/package migration.
    - Keep `autoresearch-vault/` unchanged as the canonical Obsidian knowledge vault path.
    - _References: user request to rename public project command to `airesearcher`_
    - _Verify: `poetry run airesearcher version`, `poetry run airesearcher doctor`, focused CLI/config/report tests, ruff, mypy, and full smoke/unit tests pass._

- [x] 59. Add third-party open-source notice coverage
  - [x] 59.1 Track referenced upstream projects and license boundaries
    - Add `THIRD_PARTY_NOTICES.md` for referenced projects used as design inspiration, naming context, or implementation-pattern references.
    - Include license status and incorporation status for HKUDS AI-Researcher, karpathy/autoresearch, Horizon, agent-arxiv-daily, SkillOpt, and OpenClaw.
    - Clearly distinguish conceptual references from copied, vendored, adapted, or redistributed third-party code/assets.
    - Link `NOTICE`, English README, and Chinese README to the third-party notice file.
    - Add a compliance regression test so future edits keep the notice policy visible.
    - _References: user request to include notice/license statements for open-source projects used as references_
    - _Verify: compliance tests, `rg` notice checks, ruff, mypy, and full smoke/unit tests pass._

- [x] 60. Add always-on operator runtime and approval queue
  - [x] 60.1 Introduce `airesearcher serve` with dangerous-action approval
    - Add a runtime approval state model for pending and approved local actions.
    - Add `airesearcher serve` as the default long-running operator entry point over the existing autopilot loop.
    - Support `--permission-mode allow-all` for trusted deployments and `--permission-mode approve-dangerous` for deployments where dangerous actions wait for human approval.
    - Add `airesearcher runtime list` and `airesearcher runtime approve` so WeChat/Feishu `/approve` adapters can map to the same local approval queue.
    - Add `/research:serve` and `/research:approve` slash command templates.
    - Add repository-tracked OpenClaw channel plugin mount metadata for official/common Lark/Feishu, Weixin, WeCom, Telegram, Discord, Slack, WhatsApp, Microsoft Teams, QQ Bot, Signal, and Zalo channels.
    - Add `airesearcher channels openclaw init|list` and `/research:openclaw-channels` so deployments can generate and inspect that integration runbook without vendoring third-party npm packages.
    - Document the current core runtime honestly: channel credentials are collected by `deploy-setup`, while channel webhook adapters are future transports over the same approval queue.
    - _References: user request for OpenClaw-style one-command service, WeChat/Feishu communication, `/approve` dangerous-command approval, and 24h local/server runtime._
    - _Verify: runtime approval unit tests, OpenClaw integration manifest tests, CLI approval/channel tests, slash template tests, ruff, mypy, and full smoke/unit tests pass._

- [x] 61. Add publication-level quality gate for autonomous cycles
  - [x] 61.1 Audit CCF-B/Q3 readiness instead of trusting loop completion
    - Add a deterministic publication audit over completed `cycle-summary.json` files.
    - Verify that experiment scripts actually executed against local data by checking run records, entrypoint existence, data hash, metrics path, artifacts, logs, exit code, and validation status.
    - Score literature and similar-work cross-search breadth separately from local evidence support.
    - Treat source failures such as Semantic Scholar 429s as novelty-coverage risks instead of silently passing missing sources.
    - Require real dataset strength, baseline reproduction, ablation evidence, statistical sanity, and manuscript sections for `ccf-b` and `q3-journal` targets.
    - Add `airesearcher publication-audit` and `/research:publication-audit`.
    - Run the publication audit automatically in `autopilot`/`serve` cycles and write failed audits into Obsidian review/issue notes so the self-loop can queue follow-up work.
    - _References: user requirement that system outputs be strictly checked against CCF-B / Q3 journal quality, real data evidence, broad online cross-search, and no fabricated publication claims._
    - _Verify: publication-audit unit tests, CLI tests, slash template test, ruff, mypy, full smoke/unit tests, and a real `.env` full-loop publication audit that rejects the current toy-data cycle._

- [x] 62. Clarify HKUDS AI-Researcher reference and license boundary
  - [x] 62.1 Treat HKUDS AI-Researcher as a conceptual reference, not copied code
    - Review the current HKUDS AI-Researcher repository, README, package metadata, and open license-clarification issue.
    - Record that the repository is public and `setup.cfg` declares MIT metadata, but no repository `LICENSE` file was found and upstream issue #94 requests explicit license clarification.
    - Update README references to explain the core differentiation: this project centers Obsidian as a self-loop/self-evolution memory substrate, permissioned always-on operation, evidence graphs, real run records, and publication audits before paper claims.
    - Keep `THIRD_PARTY_NOTICES.md` conservative: no HKUDS code, prompts, benchmark data, generated examples, or assets are copied or adapted unless upstream adds explicit license text or written permission is obtained.
    - _References: user request to understand how HKUDS AI-Researcher differs from this project and verify whether the upstream project is open-source._
    - _Verify: web review of upstream repository/README/package metadata/issue #94, focused license notice tests, and text search for the updated reference boundary._

- [x] 63. Add a real public benchmark demo for publication-audit progression
  - [x] 63.1 Run UCI Pendigits through the local evidence loop
    - Add an opt-in `pendigits_centroid_baseline` demo that downloads the public UCI Pendigits train/test files at run time instead of vendoring data into the repository.
    - Merge the downloaded files into a local CSV under ignored `runs/` artifacts and record source URLs, source byte counts, split policy, data hash, metrics, logs, artifacts, and run metadata.
    - Run a nearest-centroid baseline over all 16 features and a first-8-features ablation, then emit `accuracy`, `macro_f1`, `test_rows`, `train_rows`, `dataset_rows`, ablation accuracy, accuracy delta, and standard error.
    - Add validation statistical checks so the validation report records a confidence interval and ablation delta for the benchmark result.
    - Update publication audit logic so real-dataset metadata, ablation metadata/artifacts, and statistical notes satisfy their respective data-evidence gates without weakening literature, similarity, manuscript, or review gates.
    - Document the benchmark command and UCI dataset license/attribution boundary without claiming the baseline run is publication-ready.
    - _References: user requirement that the system verify scripts really run on real data and that CCF-B/Q3-level quality gates distinguish data evidence from unsupported paper claims._
    - _Verify: focused unit tests, ruff, mypy, full smoke/unit tests, live `run-demo --demo pendigits_centroid_baseline`, and live `serve --once --demo pendigits_centroid_baseline --review` showing script/data/baseline/ablation/statistical gates pass while publication audit still blocks weak literature/manuscript coverage._

- [x] 64. Add OpenAlex as a real fallback source for literature and novelty breadth
  - [x] 64.1 Use OpenAlex by default when ArXiv/Semantic Scholar are insufficient
    - Add an `OpenAlexClient` for the OpenAlex Works API with query search, selected metadata fields, optional `OPENALEX_API_KEY`, optional `OPENALEX_MAILTO`, request spacing, retry, and 429 circuit-breaker handling.
    - Parse OpenAlex title, authors, reconstructed abstract, publication date/year, venue, DOI, URL, citation count, and source label into the existing `AcademicPaper` schema.
    - Include OpenAlex in the default source set for daily literature refresh and project-start similarity checks while preserving source-specific fetch errors.
    - Update `.env.example`, README, third-party notices, and changelog to document OpenAlex as a runtime metadata source, not vendored data.
    - Add unit tests proving OpenAlex parsing, optional key/mailto settings, default-source participation, and Semantic Scholar failure fallback behavior.
    - _References: `P-20260613-004` and `P-20260613-003`, where live publication audits failed source-breadth checks because Semantic Scholar 429/circuit errors left ArXiv as the only successful source._
    - _Verify: focused unit tests, ruff, mypy, full smoke/unit tests, live OpenAlex client query, live `literature-refresh` showing ArXiv and OpenAlex successes even if Semantic Scholar is rate-limited, and live `similarity-check` showing OpenAlex participates in project-start cross-search._

- [x] 65. Improve project-start similarity query breadth
  - [x] 65.1 Expand sparse candidates into four evidence-oriented search queries
    - Add a minimum query floor to `SimilarityCheckConfig` so CCF-B/Q3 novelty checks do not silently issue too few distinct searches when candidate title, research gap, and metadata overlap.
    - Generate fallback queries from candidate description, seed document title, and core prior-work/benchmark terms while keeping query origins explicit for auditability.
    - Filter low-value Obsidian topic headings that look like operational run IDs instead of scholarly concepts.
    - Add unit tests for sparse candidates and low-value topic filtering.
    - _References: `P-20260613-004`, where live publication audits still failed similarity query breadth after data-side evidence was fixed._
    - _Verify: focused similarity tests, ruff, mypy, full smoke/unit tests, live query-generation check over the real Pendigits candidate, live `similarity-check` with four queries, and live `serve --once --demo pendigits_centroid_baseline --review` showing similarity query breadth passes._

- [x] 66. Clarify AutoResearchClaw MIT reference and differentiation
  - [x] 66.1 Track AutoResearchClaw as a usable MIT reference without copying it
    - Review the current AutoResearchClaw repository, README, and visible license status.
    - Record that AutoResearchClaw has a top-level MIT license and can be used as a clearer open-source reference than projects with ambiguous repository license text.
    - Update English and Chinese README reference sections to explain the difference: AutoResearchClaw emphasizes a 23-stage one-command/OpenClaw-compatible research pipeline, while AI-Researcher centers the Obsidian vault as the auditable self-loop/self-evolution substrate plus strict publication-readiness gates.
    - Update `THIRD_PARTY_NOTICES.md` and compliance tests so any future copied/adapted code, prompts, benchmark files, skills, assets, or docs preserve MIT license text and attribution.
    - _References: user request to compare against `aiming-lab/AutoResearchClaw` and note that it has MIT licensing._
    - _Verify: web review of upstream repository/README/license status, focused compliance tests, README/notice text search, ruff, mypy, and full smoke/unit tests._

- [x] 67. Align always-on runtime defaults with publication evidence gates
  - [x] 67.1 Use publication-grade default search breadth for autopilot and serve
    - Add shared CLI defaults for publication-gate evidence breadth: 4 generated queries and up to 10 papers per source/query.
    - Make `airesearcher autopilot` and `airesearcher serve` use these defaults instead of smoke-width 1/1 values.
    - Keep CLI overrides so operators can still lower breadth for explicit smoke or cost-control runs.
    - Update slash command and README guidance so the one-command runtime is documented as a real evidence-width loop.
    - Add CLI tests proving `autopilot` and `serve` pass the publication-width defaults into literature and similarity stages.
    - _References: `P-20260613-004`, where live publication audits showed the loop could execute real data/script/review gates but still needed sufficient literature and similarity breadth before publication claims._
    - _Verify: focused CLI tests, ruff, mypy, full smoke/unit tests, and live `serve --once --permission-mode allow-all --demo pendigits_centroid_baseline --review` without explicit breadth flags showing literature documents and similarity findings pass breadth gates while Semantic Scholar source errors and manuscript structure remain blockers._

- [x] 68. Add cc-switch / Claude Code external code-agent boundary
  - [x] 68.1 Treat cc-switch as provider-routing infrastructure, not copied runtime code
    - Review the current `farion1231/cc-switch` repository, top-level MIT license, provider-management docs, Universal Provider behavior, and Claude Code model-routing caveat.
    - Add repository-tracked metadata for a `claude-code-via-cc-switch` external code-agent backend.
    - Make the execution contract explicit: Claude Code may draft code through cc-switch provider routing, but AI-Researcher owns diff capture, validation gates, dangerous-command approval, merge/rollback, Obsidian memory, and `Agent.md` logging.
    - Add `airesearcher code-agents cc-switch init|list` and `/research:code-agent-backends` so operators can generate and inspect the contract without copying upstream code or secrets.
    - Update README, Chinese README, changelog, third-party notices, and compliance tests to record cc-switch's MIT reference boundary and secret-handling rules.
    - _References: user question about whether a coding agent should combine cc-switch with Claude Code CLI to share this project's API model while keeping AI-Researcher validation authority._
    - _Verify: web review of cc-switch repository/license/provider docs and Claude Code model config docs, focused cc-switch integration tests, CLI tests, compliance tests, ruff, mypy, full smoke/unit tests, generated manifest inspection, and CI._

- [x] 69. Generate evidence-backed paper-style Markdown reports
  - [x] 69.1 Make demo reports satisfy manuscript-structure audit without weakening evidence gates
    - Extend `generate_markdown_report` so the run report includes publication-style sections: Abstract, Introduction, Related Work, Method, Experiments, Results, Limitations, Conclusion, and References.
    - Preserve the existing Question, Literature Summary, Hypothesis, Experiment Design, Run Metadata, Reproducibility, Results, Validation, Limitations, and Next Steps evidence blocks so deterministic readability and metric-evidence checks still apply.
    - Keep quantitative result lines bound to evidence edges; do not infer novelty, significance, or publication readiness from the manuscript structure alone.
    - Treat this Markdown report as the Obsidian-readable evidence manuscript, not as the final paper-level artifact.
    - Update report lint expectations and publication audit tests so manuscript structure can pass only when required sections are actually present.
    - Run a real `serve --once --review --demo pendigits_centroid_baseline` cycle and confirm `manuscript_structure` passes while true source failures still keep the audit at `needs_revision`.
    - _References: `P-20260613-004`, where the live default-width publication audit passed literature breadth, similarity breadth, data/script/baseline/ablation/statistical/reviewer gates but still failed manuscript structure._
    - _Verify: focused report tests, report ruff/mypy checks, full smoke/unit tests, and live `serve --once --permission-mode allow-all --demo pendigits_centroid_baseline --review` showing manuscript structure passes without hiding Semantic Scholar 429 source errors._

- [x] 70. Add LaTeX template compatibility testing for paper delivery
  - [x] 70.1 Start with generic journal single-column and double-column templates
    - Add a LaTeX template registry that distinguishes built-in generic templates from externally fetched official templates.
    - Generate smoke manuscripts with the same required paper sections used by the Markdown manuscript audit.
    - Keep process data, experiment records, evidence summaries, and final run summaries as Markdown entries in `autoresearch-vault/`.
    - Define the final paper-level artifact as a template-specific LaTeX build that produces a PDF, not merely a Markdown report.
    - Compile generic single-column and double-column article templates when a LaTeX engine is available; otherwise emit a structured skipped compatibility result.
    - Preserve compile logs and template provenance under ignored run artifacts, not as vendored template source.
    - _References: user requirement that paper structure should be tested against real LaTeX templates, starting with generic journal single/double-column templates._
    - _Verify: unit tests for registry/rendering/result schema plus a local compile smoke or an explicit skipped result when no TeX engine is installed._

  - [x] 70.2 Expand template compatibility to selected conference and publisher templates
    - Fetch official or canonical template sources/metadata for IEEEtran, ACM `acmart`, and Springer Nature `sn-jnl` from their current public template locations.
    - Respect upstream licenses and notices; do not vendor template packages into the repository unless license and attribution requirements are explicitly satisfied.
    - Add a compatibility matrix report with status, source URL, fetched timestamp, engine, compile command, log path, and failure reason.
    - Keep source fetching rate-limited and cached, and mark unavailable templates as `source_unavailable` rather than fabricating compatibility.
    - Current live matrix fetches source pages for IEEEtran, ACM `acmart`, and Springer Nature, compiles IEEEtran and ACM PDFs when local TeX Live provides the classes, and records Springer Nature as `source_unavailable` when `sn-jnl.cls` is not installed.
    - _References: user requirement to later expand beyond generic templates to partial conference template compatibility._
    - _Verify: web/source review, notice updates, focused template tests, and a live source fetch plus compile/source-unavailable result per configured external template._

- [x] 71. Build final LaTeX PDF paper artifacts from Obsidian-readable Markdown manuscripts
  - [x] 71.1 Add a Markdown-to-LaTeX paper build command and artifact summary
    - Accept an evidence-bound Markdown report with the paper sections introduced in task `69.1`.
    - Convert the report into a selected registered LaTeX template without fabricating missing sections or claims.
    - Refuse to compile when required paper sections are missing; record missing sections in JSON and Markdown.
    - Compile to PDF when a LaTeX engine and the selected template class are available.
    - Write `paper-build.json`, `paper-build.md`, generated `.tex`, optional `.pdf`, compile log, and an Obsidian Markdown summary under `autoresearch-vault/projects/<project-id>/paper/`.
    - Keep generated TeX/PDF/log files under ignored run artifacts; only the human-readable build summary belongs in the vault.
    - Current real build compiled `runs/manual-live/paper-build-task71/main.pdf` from the live `serve-paper-structure` Markdown report and wrote `autoresearch-vault/projects/ai_researcher_system/paper/paper-build.md`.
    - _References: user requirement that process data remain Markdown in Obsidian while the final paper-level result is generated by compiling a LaTeX template to PDF._
    - _Verify: focused paper-build tests, CLI test, report ruff/mypy checks, full smoke/unit tests, and a real build against an existing live cycle report._

- [x] 72. Add SCALE-inspired physical evidence gates for autonomous release claims
  - [x] 72.1 Add a release evidence gate command and Obsidian records
    - Review the current SCALE Engine repository and license boundary before referencing it.
    - Treat SCALE as a design reference for executable gates, evidence files, review-gated shipping, and session coordination; do not copy or vendor upstream code, generated packs, templates, dashboards, prompts, screenshots, or package artifacts.
    - Add a lightweight `evidence-gate` command that turns the research-cycle release decision into a physical gate instead of a prompt-only instruction.
    - Require readable cycle summary evidence plus local literature summary, similarity summary, experiment report, validation report, evidence map, run record, review artifact, publication audit artifact, and compiled paper-build PDF before release claims.
    - By default, block release when the evidence-constrained review is not `pass`, the publication audit is not `publishable=true`, or the paper build has not produced a compiled PDF.
    - Write JSON and Markdown gate reports and optional Obsidian `review_note`/`issue_note` records so failed gates become self-loop follow-up evidence.
    - Add `/research:evidence-gate`, README/Chinese README guidance, changelog notes, third-party notice coverage, and compliance tests.
    - Current live evidence-gate verification over `serve-paper-structure` plus `paper-build-task71` correctly blocks release because the publication audit is still `needs_revision` due Semantic Scholar source errors, while confirming the paper PDF exists.
    - _References: user request to incorporate SCALE-style "no evidence, no release" physical gates without dragging a small-team prototype into a heavyweight full lifecycle._
    - _Verify: web review of SCALE Engine repository/license, focused evidence-gate and CLI tests, compliance tests, ruff, mypy, full smoke/unit tests, and a real `evidence-gate` run over the latest live cycle and paper build._

  - [x] 72.2 Add lightweight agent session coordination for overlapping file edits
    - Add a local JSON session coordinator so concurrent coding/research agents can claim file or directory scopes before editing.
    - Detect exact and parent/child path overlaps against active sessions and block the second claim with a non-zero CLI exit by default.
    - Support session release so completed agents stop blocking later work.
    - Add `airesearcher sessions claim|list|release` and `/research:session-claim`.
    - Keep the feature local, deterministic, and lightweight; do not introduce a central server, database, or heavyweight lifecycle orchestration.
    - Record real session-claim evidence showing one session claim allowed, a second overlapping claim blocked, and the second claim allowed after release.
    - _References: user request to borrow SCALE's multi-agent traffic-control idea without adopting the whole heavyweight lifecycle._
    - _Verify: focused runtime/CLI tests, ruff, mypy, full smoke/unit tests, and a real session claim/release conflict demo._

  - [x] 72.3 Add a local lock around session state mutations
    - Serialize `sessions claim` and `sessions release` state mutations with a local lock file so simultaneous agents cannot both read an empty state and pass the gate.
    - Keep the lock file local, short-lived, and stale-lock tolerant; do not introduce a daemon, database, or remote coordinator.
    - Expose a CLI `--lock-timeout-seconds` option so automation can choose fail-fast or wait behavior.
    - Add tests for an active lock blocking a claim without corrupting the state file.
    - _References: user request to convert multi-agent prompt discipline into physical governance gates._
    - _Verify: focused runtime lock tests, CLI tests, ruff, mypy, full smoke/unit tests, and a real fail-fast locked-state CLI demo._

- [x] 73. Remove manual release-gate steps from the always-on research loop
  - [x] 73.1 Run paper build and evidence gate automatically in each `autopilot`/`serve` cycle
    - After the publication audit, build the evidence-bound Markdown report through the generic LaTeX template inside the cycle directory.
    - Write `paper_build` into `cycle-summary.json` with the paper-build JSON/PDF/log paths.
    - Run `run_evidence_gate` over the updated cycle summary and write `evidence_gate` into `cycle-summary.json`.
    - Keep blocked gates non-fatal for the always-on loop; blocked output becomes Obsidian review/issue evidence and self-loop follow-up material instead of a prompt-only warning.
    - Echo the evidence-gate verdict from `autopilot` and `serve` so operators can see whether the cycle is releasable.
    - _References: user requirement for a one-command 24h system where paper-level outputs and quality gates are automatic, not manually chained._
    - _Verify: focused autopilot CLI test, ruff, mypy, full smoke/unit tests, and a real local single-cycle run showing `paper_build` plus `evidence_gate` in `cycle-summary.json`._

- [x] 74. Add command-line reproduction proof to the release gate
  - [x] 74.1 Rerun each cycle experiment from a command-line entry point
    - After the first experiment run, rerun the selected demo into `cycle_dir/reproduction-check/rerun`.
    - Store `reproduction_check` in `cycle-summary.json` with command, exit code, output directory, run-record paths, validation-report paths, stdout/stderr tails, and JSON/Markdown report paths.
    - Require `reproduction_check.status=passed`, exit code `0`, a fresh `run-record.json`, and a fresh `validation-report.json` in the physical evidence gate before release.
    - Keep this as a real subprocess command invocation, not a mocked metadata check.
    - Write the reproduction evidence into ignored run artifacts while preserving a summary path in the cycle summary for later Obsidian review/issue records.
    - _References: user requirement to verify that scripts and data are actually run, plus SCALE-style "no evidence, no release" governance._
    - _Verify: focused reproduction/evidence-gate tests, ruff, mypy, full smoke/unit tests, and a real local single-cycle run showing fresh reproduction artifacts._

- [x] 75. Harden publication-level innovation review
  - [x] 75.1 Block baseline-only reports without file-backed method innovation evidence
    - Add a publication-audit target requirement for method innovation evidence at CCF-B and Q3-journal levels.
    - Require structured task metadata describing a proposed mechanism/contribution plus an existing innovation/mechanism/contribution artifact in the experiment outputs.
    - Treat `baseline_only=true` or baseline-named tasks as insufficient for publication-level innovation claims, even when data, ablation, statistics, literature breadth, and manuscript sections pass.
    - Keep `mvp-demo` exempt so basic loop checks can still verify runtime correctness without pretending to be publishable research.
    - Record the failure as a high-severity audit check named `method_innovation_evidence` with a concrete next action.
    - _References: user requirement that generated papers be checked for real innovation and evidence strong enough for CCF-B/Q3-style targets._
    - _Verify: focused publication-audit tests, ruff, mypy, full smoke/unit tests, and a real `publication-audit` run showing the method-innovation gate blocks a baseline-only cycle._

- [x] 76. Add a real non-baseline method candidate demo
  - [x] 76.1 Implement UCI Pendigits prototype-shrinkage candidate with honest innovation evidence
    - Add `pendigits_prototype_shrinkage` as an opt-in public benchmark demo.
    - Reuse official UCI Pendigits train/test files and local caching.
    - Compare a nearest-centroid full-feature baseline, a first-8-feature ablation, and a class-prototype shrinkage candidate.
    - Write `artifacts/innovation_evidence.json` with proposed mechanism, alpha, prototype shift, baseline/candidate accuracy, deltas, support artifacts, and honest interpretation.
    - Keep empirical gain claims bounded; zero or negative delta must be recorded as no gain or underperformance, not hidden.
    - Make `run-demo`, `autopilot`, validation, report generation, and publication audit consume the new demo.
    - Use the SCALE-inspired gate lesson narrowly: evidence files and review gates decide publishability, not prompt-only self-discipline or the presence of a paper-shaped PDF.
    - _References: user requirement for real executable experiments, publication-quality innovation checks, and lightweight physical gates inspired by SCALE Engine._
    - _Verify: focused demo tests, ruff, mypy, full smoke/unit tests, real `run-demo`, and real `autopilot`/publication audit showing innovation evidence exists, is checked, and does not mask a negative result._

- [x] 77. Harden method-effect publication gating
  - [x] 77.1 Block method candidates whose innovation artifact lacks positive baseline effect
    - Add a `method_effect_evidence` publication-audit check for targets requiring novel contribution.
    - Read file-backed innovation/mechanism/contribution artifacts and extract a numeric baseline-vs-candidate delta.
    - Pass only when the recorded method-candidate delta is positive; fail neutral, negative, or missing effect evidence for CCF-B/Q3-style targets.
    - Keep `mvp-demo` exempt so runtime smoke tests do not need method-effect claims.
    - Preserve negative evidence as useful research memory while blocking empirical-gain and paper-ready claims.
    - _References: user requirement that the system meet strict CCF-B/Q3-style evidence standards and not rely on prompt-only "AI self-discipline" for innovation claims._
    - _Verify: focused publication-audit tests, ruff, mypy, full smoke/unit tests, and a real `publication-audit` over the task `76.1` negative-result cycle showing `method_innovation_evidence=pass` but `method_effect_evidence=fail`._

- [x] 78. Add a positive-effect real method candidate path
  - [x] 78.1 Implement UCI Pendigits variance-calibrated prototype candidate
    - Add `pendigits_variance_calibrated_prototypes` as an opt-in public benchmark demo.
    - Reuse official UCI Pendigits train/test files and local caching.
    - Compare a nearest-centroid baseline, a z-score centroid ablation, and a diagonal variance-calibrated prototype candidate.
    - Write `artifacts/innovation_evidence.json` with proposed mechanism, variance shrinkage, baseline/candidate accuracy, z-score ablation accuracy, deltas, support artifacts, and effect direction.
    - Make `run-demo`, `autopilot`, validation, report generation, publication audit, and reproduction rerun consume the new demo.
    - Keep the result framed as a real positive method-effect candidate, not as a complete CCF-B/Q3 paper until broad novelty search and LLM evidence review pass.
    - _References: task `77.1` method-effect gate and the user requirement for real executable experiments with strict innovation-quality checks._
    - _Verify: focused demo tests, ruff, mypy, full smoke/unit tests, real `run-demo`, and real `autopilot` showing `method_innovation_evidence=pass`, `method_effect_evidence=pass`, and `reproduction_check=passed`._

- [x] 79. Align autonomous novelty search with the executed method
  - [x] 79.1 Add demo-specific literature seeds and candidate metadata for autopilot
    - Add a query floor and optional seed-query list to `LiteratureRefreshConfig` so publication-mode refresh runs cannot silently collapse to one query on a sparse or empty vault.
    - Generate deterministic, method-specific literature seed queries for Pendigits baseline, prototype-shrinkage, and variance-calibrated prototype demos.
    - Make autopilot-generated candidates include demo-aligned title, method, dataset, benchmark, baseline, and limitation metadata when a known demo is selected.
    - Preserve the generic self-evolving research-loop candidate only for generic/default demos.
    - Ensure similarity search, literature refresh, and the executed experiment are about the same research object before publication-level claims are evaluated.
    - Keep required-source errors as source-coverage blockers; Semantic Scholar 429s are optional-source risks when ArXiv/OpenAlex coverage is sufficient.
    - _References: task `78.1` real positive-effect candidate, the user requirement for broad cross-checking before paper claims, and the task `79` full-width cycle showing query breadth collapsed to one and candidate/experiment topic mismatch._
    - _Verify: focused literature/CLI tests, ruff, mypy, full smoke/unit tests, and a real no-review `autopilot --demo pendigits_variance_calibrated_prototypes --max-queries 4` showing `literature.query_count=4`, demo-aligned candidate metadata, real source fetches, and publication gating still blocks unresolved required-source/review evidence._

- [x] 80. Make source rate-limit state persist across one autopilot cycle
  - [x] 80.1 Share literature clients between refresh and similarity checks
    - Create one source-client mapping per `autopilot`/`serve` cycle and pass it to both daily literature refresh and project similarity checking.
    - Preserve per-source rate limiter and 429 circuit-breaker state across both retrieval phases.
    - Prevent the similarity phase from rebuilding a fresh Semantic Scholar client immediately after the literature phase has opened a 429 circuit.
    - Keep source failures visible in publication audit; this change improves source politeness and evidence integrity, not publishability.
    - _References: task `79.1` aligned real cycle showing Semantic Scholar 429 remains the current novelty-coverage blocker._
    - _Verify: focused CLI tests, ruff, mypy, full smoke/unit tests, and a real no-review `autopilot` cycle showing Semantic Scholar 429 opens once in literature refresh and similarity receives only circuit-open errors from the shared breaker._

- [x] 81. Persist source cooldowns across autopilot cycles
  - [x] 81.1 Add optional on-disk 429 circuit state for literature clients
    - Add optional state-file support to `RateLimitCircuitBreaker` using wall-clock expiry times so cooldowns survive process restarts.
    - Let Semantic Scholar and OpenAlex clients accept a circuit-state path while preserving default in-memory behavior for ordinary unit tests and direct client use.
    - Store autopilot/serve source circuit state under `<cache-root>/source-circuit-breakers.json`.
    - Clear expired or successful source entries so stale cooldowns do not permanently disable a source.
    - Keep source failures visible in publication audit; persistent cooldown avoids repeated hammering but does not convert failed source coverage into publication-ready evidence.
    - _References: task `80.1` follow-up and user requirement for a 24h loop that respects real API access limits._
    - _Verify: focused client/CLI tests, ruff, mypy, full smoke/unit tests, and two consecutive real no-review `autopilot` cycles sharing a cache root where the second cycle starts Semantic Scholar as `CircuitBreakerOpenError` rather than another immediate 429._

- [x] 82. Add SCALE-lite source preflight gate before costly cycle work
  - [x] 82.1 Block autopilot/serve early when a persisted source cooldown is active
    - Add a no-network source preflight gate immediately after autopilot/serve source clients are created.
    - Inspect existing persisted source circuit-breaker state before literature refresh, experiments, LLM review, paper build, and evidence gate.
    - When a source is still cooling down, write `source-preflight.json` and `source-preflight.md`, write an Obsidian `issue_note`, merge the issue into scheduler state, and return a blocked cycle summary without running costly work.
    - Keep normal cycles unchanged when all source cooldown gates are clear, and record the preflight report in `cycle-summary.json`.
    - Read persisted source state as `utf-8-sig` so operator-created JSON files with a UTF-8 BOM do not silently bypass the gate.
    - _References: user request to adopt the useful part of SCALE Engine as physical gates rather than prompt-only discipline; tasks `80.1` and `81.1` source-politeness follow-ups._
    - _Verify: focused client/CLI tests, ruff, mypy, full smoke/unit tests, and a real CLI `autopilot` run with a BOM-bearing persisted Semantic Scholar cooldown file showing `[BLOCKED] source_preflight: blocked`, skipped review, a blocked cycle summary, and a queued Obsidian issue follow-up._

- [x] 83. Make source preflight fail closed on unverifiable state
  - [x] 83.1 Block autopilot/serve when persisted source state is malformed
    - Validate the persisted source circuit-breaker JSON during source preflight before reading cooldown values.
    - Treat unreadable JSON, non-object payloads, and non-numeric expiry values as `state_error` blockers.
    - Preserve the no-network preflight contract: state validation must not ping external sources.
    - Write `state_error` source checks into `source-preflight.json` and the generated Obsidian issue note.
    - Tag generated malformed-state issue notes with both `82.1` and `83.1` so scheduler follow-ups retain the source-preflight origin and the fail-closed hardening task.
    - _References: task `82.1` follow-up and `P-20260613-020` recommendation to avoid fail-open behavior for operator-edited state files._
    - _Verify: focused CLI tests, ruff, mypy, full smoke/unit tests, and a real CLI `autopilot` run with malformed `source-circuit-breakers.json` showing `[BLOCKED] source_preflight: blocked`, `state_error` checks for Semantic Scholar/OpenAlex, skipped review, and a queued Obsidian issue follow-up._

- [x] 84. Harden persisted source-state writes
  - [x] 84.1 Write source circuit-breaker state atomically
    - Replace direct writes to `source-circuit-breakers.json` with same-directory temporary-file writes followed by atomic replace.
    - Preserve the previous valid state file if the replacement step fails.
    - Clean temporary state files after both successful and failed replacement attempts.
    - Keep task `83.1` fail-closed behavior as the fallback if a state file is still externally corrupted or manually edited into an invalid form.
    - _References: `P-20260613-021` follow-up and the SCALE-lite requirement that source-politeness gates should be enforced by evidence files and filesystem behavior, not prompt-only care._
    - _Verify: focused literature-client tests for successful cleanup and replacement failure, ruff, mypy, full smoke/unit tests, and a real CLI `autopilot` run that touches persisted source state while leaving no temporary state files behind._

- [x] 85. Serialize persisted source-state mutations
  - [x] 85.1 Add a local lock around source circuit state read-modify-write
    - Guard persisted source cooldown read-modify-write operations with an exclusive same-directory `.lock` file.
    - Fail closed with `SourceCircuitStateLockError` if another process holds the lock past the configured timeout.
    - Clear stale state locks before writing so a crashed process does not permanently block source-state updates.
    - Treat active source-state locks as `state_locked` source preflight blockers in `autopilot` and `serve`, with JSON/Markdown evidence and Obsidian issue notes.
    - Tag locked-state issue notes with task `85.1` so follow-up records point to the concurrency gate.
    - _References: task `84.1` follow-up and the SCALE-lite multi-agent/source-politeness requirement that concurrent workers must not silently overwrite shared evidence state._
    - _Verify: focused literature-client and CLI tests, ruff, mypy, full smoke/unit tests, and a real CLI `autopilot` run with an active `source-circuit-breakers.json.lock` showing `[BLOCKED] source_preflight: blocked`, `state_locked` checks, skipped review, and a queued Obsidian issue follow-up._

- [x] 86. Harden publication novelty classification coverage
  - [x] 86.1 Block publication claims when similarity findings are all unknown
    - Add a `similarity_classification_coverage` publication-audit check for CCF-B/Q3-style targets.
    - Treat similarity findings that are all `unknown` or unclassified as a high-severity failure instead of letting raw finding count imply novelty coverage.
    - Keep direct-duplicate and adjacent-work handling unchanged; at least one non-unknown evidence-backed classification is required before similarity evidence can support novelty claims.
    - Write the failed check into publication-audit JSON/Markdown and Obsidian review/issue notes so the self-loop receives a concrete novelty-classification follow-up.
    - _References: user request for strict innovation quality control and SCALE-style physical gates that do not rely on prompt-only self-discipline._
    - _Verify: focused publication-audit tests, ruff, mypy, full smoke/unit tests, and a real `publication-audit` CLI run over a real autopilot cycle showing `similarity_classification_coverage=fail` when all findings remain `unknown`._

- [x] 87. Improve conservative similarity classification without weakening unknowns
  - [x] 87.1 Add evidence-backed token-overlap classification basis
    - Add conservative token-overlap matching for method and dataset metadata when exact phrase matching misses source-backed adjacent work.
    - Require enough method-token overlap, and dataset-token overlap for `adjacent_work`, before promoting an online finding above `unknown`.
    - Keep weak or irrelevant live hits as `unknown` with pending-verification basis rather than fabricating novelty positioning.
    - Record matched method and dataset tokens in the similarity summary classification basis so publication audits can inspect why a finding was classified.
    - _References: task `86.1` follow-up and user requirement that novelty checks be broad and strict enough for CCF-B/Q3-style claims._
    - _Verify: focused similarity tests for positive token-overlap classification and weak-overlap unknown behavior, ruff, mypy, full smoke/unit tests, and a real `similarity-check` CLI run against live sources showing irrelevant real hits remain `unknown` rather than being over-classified._

- [x] 88. Tighten publication audit around classified similar-work breadth
  - [x] 88.1 Require enough non-unknown similarity findings for publication targets
    - Add `similarity_classified_finding_breadth` to publication audit for targets requiring a novel contribution.
    - Count only non-`unknown` similarity classifications toward the target finding breadth.
    - Keep raw `similarity_finding_breadth` for retrieval volume, but do not let unknown findings satisfy novelty-positioning breadth.
    - Block CCF-B/Q3 publishability when classified similar-work evidence is below target, even if raw finding count is high.
    - _References: task `86.1`, task `87.1`, and user requirement that cross-search breadth be strong enough for CCF-B/Q3-style claims._
    - _Verify: focused publication-audit tests, ruff, mypy, full smoke/unit tests, and a real `publication-audit` CLI run showing `similarity_classified_finding_breadth=fail` on a real cycle whose findings remain unknown._

- [x] 89. Add SCALE-lite lifecycle trace evidence to the release gate
  - [x] 89.1 Require physical define/plan/build/verify/review/ship evidence
    - Extend `evidence-gate` JSON/Markdown output with a structured `lifecycle_trace`.
    - Map `define` to candidate, literature, and similarity evidence.
    - Map `plan` to experiment `README.md` and `config.yaml` evidence.
    - Map `build` to the runnable experiment entrypoint evidence.
    - Map `verify` to validation, evidence map, and reproduction-check evidence.
    - Map `review` to LLM evidence review and publication-audit evidence.
    - Map `ship` to paper-build JSON and compiled PDF evidence.
    - Add a blocking `lifecycle_trace_gate` so missing required lifecycle stages cannot be overridden by prompt-only assurances.
    - _References: task `72.1`, task `74.1`, SCALE Engine design review, and user requirement to borrow the lightweight "no evidence, no release" gate without adopting a heavyweight lifecycle._
    - _Verify: focused evidence-gate tests, ruff, mypy, full smoke/unit tests, and a real `evidence-gate` CLI run over a real cycle showing lifecycle stages and blocking the missing review stage._

- [x] 90. Harden live LLM output quality gates
  - [x] 90.1 Cap critical structured-output failures and retry once with repair prompt
    - Treat malformed JSON, missing required structured fields, quoted array fields, unknown/missing review refs, fake URLs, and secret leaks as hard quality failures capped below the default quality threshold.
    - Retry `llm-smoke` once with deterministic repair instructions when critical smoke checks fail.
    - Record the final attempt count in `LLMSmokeResult`, CLI output, and the JSON quality artifact.
    - Keep the deterministic local quality gate as final authority; a repair prompt may help the model comply, but cannot override failed checks.
    - _References: task `41.1`, task `44.1`, task `89.1`, and user requirement to replace prompt-only self-discipline with evidence-producing hard gates._
    - _Verify: focused LLM/CLI tests, ruff, mypy, full smoke/unit tests, and real DeepSeek `llm-smoke` calls showing the strict gate catches bad structure and the one-shot repair path can pass._

- [x] 91. Harden LLM reviewer repair gates
  - [x] 91.1 Add bounded repair attempts to local-evidence review
    - Add `attempts` to `LLMReviewResult` and `llm-review` CLI output.
    - Retry `llm-review` once with deterministic repair instructions when critical local-evidence review checks fail.
    - Instruct review repair to use only allowed outer evidence IDs, avoid new uncited claims, and move claims without allowed refs into `unsupported_claims`.
    - Keep finding citation checks, unknown-ref checks, fake URL checks, and secret-leak checks as local hard gates that repair prompts cannot override.
    - _References: task `44.1`, task `90.1`, and user requirement that output quality and evidence support be physically checked rather than trusted to prompt self-discipline._
    - _Verify: focused LLM/CLI tests, ruff, mypy, full smoke/unit tests, and real DeepSeek `llm-review` calls showing incomplete evidence is blocked while a complete local evidence bundle can pass._

- [x] 92. Allow post-hoc review evidence in the physical release gate
  - [x] 92.1 Add explicit review artifact override to `evidence-gate`
    - Add `--review-json` to `airesearcher evidence-gate`.
    - Let `run_evidence_gate` accept a standalone `llm-review.json` artifact when `cycle_summary.review` is missing or skipped.
    - Parse standalone review artifacts from their deterministic `quality.score` and `quality.parsed_output.verdict` fields.
    - Include the explicit review path in JSON/Markdown reports, Obsidian gate notes, review checks, and the `lifecycle_trace` review stage.
    - Keep publication-audit and paper-build gates independent; a post-hoc passing review cannot make a non-publishable cycle release-ready.
    - _References: task `89.1`, task `91.1`, and real evidence-gate run showing a valid post-hoc review artifact could not previously clear the review stage._
    - _Verify: focused evidence-gate/CLI tests, ruff, mypy, full smoke/unit tests, and a real `evidence-gate --review-json` run over a real cycle showing review/lifecycle pass while publication audit remains blocking._

- [x] 93. Allow post-hoc review evidence in publication audit
  - [x] 93.1 Add explicit review artifact override to `publication-audit`
    - Add `--review-json` to `airesearcher publication-audit`.
    - Let `audit_publication_quality` accept a standalone `llm-review.json` artifact when `cycle_summary.review` is missing or skipped.
    - Parse standalone review artifacts from deterministic `quality.score` and `quality.parsed_output.verdict` fields.
    - Include the explicit review path in JSON/Markdown reports, Obsidian review notes, Obsidian issue notes, and review check evidence refs.
    - Keep literature breadth, similar-work breadth, source error, classified novelty, method-effect, manuscript, and paper-build gates independent; a post-hoc passing review cannot make weak external-search evidence publication-ready.
    - _References: task `92.1`, task `91.1`, and real publication-audit run showing a valid post-hoc review artifact could not previously clear publication-audit review checks._
    - _Verify: focused publication-audit/CLI tests, ruff, mypy, full smoke/unit tests, and a real `publication-audit --review-json` run over a real cycle showing review checks pass while literature/similarity blockers remain blocking._

- [x] 94. Bind standalone review artifacts to cycle evidence
  - [x] 94.1 Require explicit review artifacts to match the audited cycle
    - Add blocking `review_artifact_binding` checks to `publication-audit` and `evidence-gate`.
    - Verify explicit `llm-review.json` subject hash or path matches the cycle `demo.report_path`.
    - Verify the review evidence bundle covers the cycle validation report and evidence map by hash or path.
    - Block unrelated passing review artifacts so post-hoc review cannot be reused across cycles.
    - _References: task `92.1`, task `93.1`, SCALE Engine physical gate lesson, and user request to prevent prompt-only or fake evidence._
    - _Verify: focused report tests, ruff, mypy, full smoke/unit tests, and real publication-audit/evidence-gate runs showing binding pass for the real DeepSeek review artifact while release remains blocked by publication-audit quality._

- [x] 95. Improve real online novelty-search prompt quality
  - [x] 95.1 Prioritize concise structured similarity queries
    - Generate method-plus-benchmark, baseline-plus-benchmark, and limitation-risk-plus-benchmark similarity queries from candidate metadata before long research-gap prose.
    - Preserve vault-context, negative-result, and long research-gap queries as fallback breadth rather than default top-four search prompts.
    - Handle hyphenated risk terms such as `distance-metric` when building novelty stress queries.
    - Keep weakly supported live hits as `unknown`; do not reclassify findings without title/abstract metadata evidence.
    - _References: user requirement to optimize online search prompts, task `86.1`, task `87.1`, task `88.1`, and the real task 95 baseline cycle with 36 unknown similarity findings._
    - _Verify: focused similarity tests, ruff, mypy, full smoke/unit tests, and a real autopilot cycle showing structured queries in the similarity summary, 57 source-backed findings, 1 evidence-classified finding, and continued publication blocking because classified breadth is still below target._

- [x] 96. Harden LaTeX paper artifact quality gates
  - [x] 96.1 Add page-count, technical-depth, and layout-overflow checks
    - Add deterministic `paper_quality` output to `paper-build.json` and `paper-build.md`.
    - Require a minimum PDF page count, total manuscript word count, technical term coverage, and per-section word depth before a compiled paper can remain status `compiled`.
    - Parse LaTeX compile logs for `Overfull \hbox` warnings and treat layout overflow as a paper-readiness blocker.
    - Downgrade successfully compiled but thin or overflowing PDFs to `compiled_with_quality_issues` instead of allowing "PDF exists" to imply paper-ready output.
    - Add `paper_quality_gate` to `evidence-gate` so paper-level release claims require both a compiled PDF and passing paper-quality evidence.
    - _References: user review that the generated LaTeX paper had too few pages, insufficient technical detail, and visible layout overflow; task `89.1` SCALE-lite physical gate; task `95.1` real autopilot paper-build artifact._
    - _Verify: focused paper-build/evidence-gate tests, ruff, mypy, full smoke/unit tests, a real `paper-build` rerun over the task `95.1` report showing `compiled_with_quality_issues`, and a real `evidence-gate` rerun showing `paper_quality_gate=fail`._

- [x] 97. Add direct OpenCode code-agent backend boundary
  - [x] 97.1 Prefer OpenCode direct integration over cc-switch for code drafting
    - Review current OpenCode docs for CLI `run`, headless `serve`, ACP, permissions, project commands, and project skills.
    - Add repository-tracked metadata for an `opencode-direct` external code-agent backend.
    - Make the execution contract explicit: OpenCode may draft code through `run`/`serve`/ACP, but AI-Researcher owns diff capture, validation gates, dangerous-command approval, merge/rollback, Obsidian memory, and `Agent.md` logging.
    - Add `airesearcher code-agents opencode init|list` and update `/research:code-agent-backends` so operators can generate and inspect the preferred direct contract without copying upstream code or secrets.
    - Keep cc-switch available only as an optional Claude Code provider-routing bridge when that backend is explicitly required.
    - Update README, Chinese README, changelog, third-party notices, and compliance tests to record OpenCode's MIT reference boundary and secret-handling rules.
    - _References: user request to replace the cc CLI / cc-switch plan with direct OpenCode integration because the OpenCode ecosystem is more compatible; OpenCode docs for CLI, permissions, and skills._
    - _Verify: web review of OpenCode docs and repository/license metadata, `npm view opencode-ai version license repository --json`, focused OpenCode integration tests, focused CLI/compliance tests, ruff, mypy, full smoke/unit tests, generated manifest inspection, and CI._

- [x] 98. Add Luban-inspired skill polish gate
  - [x] 98.1 Audit skill candidates before promotion or public release
    - Review `LearnPrompt/luban-skill`, its MIT license, installation path, five-action workflow, evidence/validation claims, and safety boundaries.
    - Treat Luban as a methodology reference only; do not copy upstream skill text, examples, assets, plugin manifests, screenshots, or generated reports.
    - Add a deterministic Obsidian skill-polish audit that checks material challenge evidence, peer positioning, real validation evidence, bounded edit/rollback records, installable/shareable asset refs, and follow-up observation refs.
    - Add `airesearcher skill-polish-audit` plus `/research:skill-polish-audit` so skill candidates can be blocked before promotion when they lack public-quality evidence.
    - Update README, Chinese README, changelog, third-party notices, compliance tests, and Obsidian progress memory.
    - _References: user suggestion to evaluate `github.com/LearnPrompt/luban-skill`; Luban's "material check, peer visit, measurement, slow carving, furnace loop" workflow; SkillOpt task `23.1` and `skill-evolve`._
    - _Verify: live web review of the Luban repository/license/README, focused skill/CLI/compliance tests, ruff, mypy, full smoke/unit tests, a real generated `skill-polish-audit` report over an Obsidian skill candidate, and CI._

- [x] 99. Add broad non-scholarly inspiration discovery
  - [x] 99.1 Search dataset/community/news signals without weakening evidence gates
    - Review Hugging Face Hub API/rate-limit guidance and Hacker News Algolia Search API availability before implementation.
    - Add `airesearcher inspiration-refresh` and `/research:inspiration-refresh` for real online discovery outside academic databases.
    - Search public Hugging Face dataset metadata and Hacker News stories as initial dataset/community signals, with explicit per-source fetch records, conservative one-second default request spacing, and visible source errors.
    - Write Obsidian summaries under `autoresearch-vault/exploration/inspiration/` that state these items are inspiration only and cannot be cited as scholarly evidence without separate validation.
    - Wire the broad inspiration refresh into each non-blocked `autopilot`/`serve` cycle as a non-scoring context artifact, while keeping publication audit and evidence gate based on academic sources, executed experiments, review evidence, and compiled paper quality.
    - Update README, Chinese README, changelog, third-party notices, compliance tests, and Obsidian progress memory.
    - _References: user requirement that project-start and cross-check search should not be limited to local data or academic databases; Hugging Face Hub API/rate limits; Hacker News Algolia Search API._
    - _Verify: focused inspiration/CLI/compliance tests, ruff, mypy, full smoke/unit tests, a real `inspiration-refresh` run against live Hugging Face/Hacker News sources, and CI._

- [x] 100. Harden external execution and LaTeX dependency recovery evidence
  - [x] 100.1 Verify OpenCode locally and recover missing LaTeX template classes
    - Run a disposable local OpenCode CLI smoke after the operator installs OpenCode, using a bounded write-only task and recording the version, model, output file, and session evidence.
    - Add structured LaTeX template dependency resolution fields so compatibility reports and paper-build artifacts show whether a class was already available, installed by TeX Live, downloaded from an official archive, skipped, or unavailable.
    - Configure external templates with explicit TeX Live package names or official archive URLs without vendoring upstream template files in the repository.
    - Make missing external template classes trigger recorded recovery before compile, and fail closed with the recovery reason when recovery cannot prove the class is available.
    - Expose `paper-build --timeout-seconds` and print dependency-recovery status in the CLI so long downloads/compiles are configurable and visible.
    - Keep paper-readiness quality gates strict: a successfully compiled PDF remains `compiled_with_quality_issues` when page count, word count, section depth, or layout checks fail.
    - _References: user requirement to test installed OpenCode; user requirement that LaTeX missing packages/classes should be automatically downloaded or explicitly reported, not silently ignored; task `96.1` paper-quality gate._
    - _Verify: OpenCode real smoke writes `opencode-smoke.txt`; focused LaTeX/paper-build/CLI tests; ruff; mypy; live Springer Nature official archive fetch with `sn-jnl.cls` extraction and PDF compile; real Springer paper-build over the prior live Pendigits report showing dependency recovery succeeded but quality gate still blocked publishability._

- [x] 101. Run real full-cycle and self-evolution acceptance audit
  - [x] 101.1 Verify the autonomous loop, Obsidian issue loop, and SkillOpt-style evolution gate
    - Run `airesearcher serve --once` with real online literature/similarity search, real UCI Pendigits experiment execution, real LLM evidence review from `.env`, reproduction rerun, publication audit, LaTeX paper build, evidence gate, and Obsidian vault outputs.
    - Inspect the generated publication audit, evidence gate, paper build, metrics, review, reproduction, and source preflight artifacts instead of relying on console success lines.
    - Run `issue-followups` over the generated Obsidian issue notes and confirm the scheduler state receives follow-up tasks from the blocked publication/evidence gates.
    - Create a temporary parent skill card from the full-cycle evidence, run `skill-evolve` from the generated issue notes, and confirm the candidate remains in shadow evaluation with a rejected-edit buffer instead of mutating the parent skill.
    - Run `skill-polish-audit` over the candidate with real run evidence, peer methodology reference, install/share refs, and release/follow-up refs.
    - Write an Obsidian-readable acceptance review summarizing whether the loop ran, whether self-evolution is implemented, and whether the output meets a CCF-B/Q3 publication bar.
    - _References: user requirement to run the real full chain, verify self-evolution, and strictly judge whether the output is directly publishable._
    - _Verify: real `serve --once` returns `source_preflight=pass`, `review_status=passed`, `publication_audit=fail`, `evidence_gate=blocked`; `issue-followups` writes 2 open tasks; `skill-evolve` writes a shadow candidate and rejected buffer; `skill-polish-audit` passes 60/60; Obsidian acceptance review records that the current paper is not directly publishable._

- [x] 102. Clarify source policy and README positioning
  - [x] 102.1 Make Semantic Scholar optional and improve bilingual README positioning
    - Rewrite the English and Chinese README opening/status/source-policy copy so the project reads like an open-source evidence-first research operator rather than a generic paper-writing bot.
    - Keep README claims bounded to implemented capabilities and the current publication-quality gates.
    - Change default literature and similarity clients to use ArXiv plus OpenAlex first.
    - Include Semantic Scholar only when `AUTORESEARCH_ENABLE_SEMANTIC_SCHOLAR=1` or `SEMANTIC_SCHOLAR_API_KEY` is present.
    - Treat Semantic Scholar 429/source errors as optional-source warnings in publication audits when ArXiv/OpenAlex core source breadth passes, while preserving hard failures for required source errors.
    - Ensure `autopilot`/`serve` loads `.env` before constructing source clients so the optional-source policy is honored in real deployments.
    - Update `.env.example`, generated deploy template text, tests, task plan, problem log, and agent log.
    - Do not hand-write a root project-vault progress note for this maintenance task; only vault notes produced by AI-Researcher runtime commands count as system-written knowledge.
    - _References: user request to optimize `README.md` and the Chinese README; user request to lower Semantic Scholar priority because 429s are common and to prefer free APIs first._
    - _Verify: focused literature/similarity/publication-audit/CLI tests, focused ruff, focused mypy, and live `literature-refresh` using default ArXiv/OpenAlex sources without Semantic Scholar._

- [x] 103. Generate evidence-bound publication manuscripts before LaTeX build
  - [x] 103.1 Compose paper manuscripts from cycle evidence instead of thin experiment reports
    - Add a deterministic manuscript composer that reads the cycle summary, candidate metadata, run record, validation report, evidence map, literature summary, and similarity summary before writing paper text.
    - Write `paper-manuscript/manuscript.md` and `paper-manuscript/manuscript.json` with section word counts, evidence refs, and explicit publishability caveats when gates still fail.
    - Mirror the manuscript into the runtime-selected Obsidian vault project paper area only when AI-Researcher executes the command; do not hand-write root-vault maintenance progress notes.
    - Wire `autopilot` and `serve` to generate this manuscript before publication audit and LaTeX paper-build, then compile the manuscript instead of the thin demo report.
    - Make publication audit prefer `cycle_summary.paper_manuscript.markdown_path` while keeping `cycle_summary.demo.report_path` as a fallback for older cycles.
    - Preserve the hard CCF-B/Q3 release boundary: paper quality can pass while publication audit and evidence gate still block when novelty/similarity evidence is insufficient.
    - _References: user correction that Obsidian project notes should be system-written runtime output; task `96.1` paper-quality gate; task `101.1` full-cycle paper quality failure; `P-20260613-036`._
    - _Verify: focused manuscript/publication-audit/autopilot tests, focused ruff and mypy, real manuscript compose from the task `101.1` cycle, real LaTeX paper-build producing 9 pages / 2856 words / 0 overfull hbox, real publication audit failing only the similarity-classified breadth blocker, real evidence gate passing paper quality but blocking release._

- [x] 104. Improve source-backed similar-work classification quality
  - [x] 104.1 Classify query-backed adjacent method families without weakening unknowns
    - Add query-aware method-family classification for project-start similarity findings, covering prototype/centroid classifiers, Mahalanobis metric-learning/classification work, and clustering/prototype classification.
    - Add dataset alias handling for Pendigits-style wording such as `UCI Pendigits`, `pen based`, and `handwritten digit` only as supporting classification evidence.
    - Require classification/recognition/learning/metric context before method-family matches can count, so generic prototype, centroid, Gaussian, variance, covariance, or shrinkage papers remain `unknown` when they lack classification-method evidence.
    - Preserve the strict publication gate: raw findings and unknown findings do not satisfy `similarity_classified_finding_breadth`.
    - Verify against the real task `101.1` candidate and source metadata; do not hand-write root-vault progress notes for this maintenance task.
    - _References: user requirement for strict CCF-B/Q3 novelty cross-checks; task `86.1`, task `88.1`, task `95.1`, task `101.1`, task `103.1`; `P-20260613-036`._
    - _Verify: focused similarity tests, ruff, mypy, real ArXiv/OpenAlex similarity-check over the task `101.1` candidate with 57 findings and 18 non-unknown classifications, CCF-B `publication-audit` pass with `similarity_classified_finding_breadth=18/10`, and `evidence-gate` pass with `release_allowed=true`._

- [x] 105. Add cross-cycle publication stability gates
  - [x] 105.1 Block stable CCF-B/Q3 claims until a multi-cycle matrix passes
    - Add a publication-stability auditor that reads completed cycle summaries plus their publication-audit, evidence-gate, paper-build, and run-record artifacts.
    - Require the `ccf-b-matrix` target to include at least 3 completed cycles, 3 release-allowed cycles, 100% release pass rate, 3 distinct real public datasets, at least 2 LaTeX templates, and at most 2 publication-audit warnings per cycle.
    - Add a lighter `mvp-matrix` target for local development while keeping `ccf-b-matrix` as the default CLI target.
    - Add `airesearcher publication-stability` and `/research:publication-stability` so operators can gate stable-output claims from one command.
    - Prefer the paper-build artifact path recorded by the evidence gate when it is available, because the release decision must inspect the artifact actually reviewed by the physical gate rather than stale inline cycle-summary fields.
    - Write optional Obsidian review/issue notes only through the AI-Researcher runtime command and only to the operator-selected vault; do not hand-write root-vault project progress notes for this maintenance task.
    - _References: user correction that Obsidian project notes should be system-written runtime output; user requirement for strict CCF-B/Q3 stability evidence across topics; task `101.1`, task `103.1`, task `104.1`; `P-20260613-040`._
    - _Verify: focused stability and CLI tests, ruff, mypy, and real `publication-stability` over the task `104.1` Pendigits cycle blocking stable claims with `score=0.500` while confirming paper quality evidence is read from the evidence-gate-reviewed task `103.1` paper build._

- [x] 106. Expand real public benchmark coverage for the stability matrix
  - [x] 106.1 Add Letter Recognition and Spambase variance-calibrated prototype demos
    - Add `letter_variance_calibrated_prototypes` and `spambase_variance_calibrated_prototypes` as `run-demo`/`autopilot --demo` selectors.
    - Download each dataset from the public UCI ML Repository source file at run time unless a cache file already exists under the run directory.
    - Write source provenance with URL, byte count, SHA256, split policy, and license field into `artifacts/dataset_sources.json`.
    - Compare a train-set z-score nearest-centroid baseline against diagonal variance-calibrated prototypes, then write `metrics.json`, `predictions.csv`, `ablation.csv`, `summary.md`, and `innovation_evidence.json`.
    - Preserve `real_dataset=true`, `dataset_realism=real_public_benchmark`, method metadata, and baseline-vs-candidate deltas in the run record for publication audit and stability-matrix consumption.
    - Add autopilot literature seed queries and candidate metadata for both new demos so topic selection, search, and experiment execution stay aligned.
    - Do not claim these demo runs are publication-ready; they only add real benchmark coverage for later full-cycle audit/stability work.
    - _References: `P-20260613-040`; task `105.1`; user request to run real scripts/data and build a multi-cycle, multi-dataset stability bar._
    - _Verify: focused demo/acceptance tests, ruff, mypy, real `run-demo` over UCI Letter Recognition and UCI Spambase with downloaded source files, positive recorded deltas, validation reports passing, and run records preserving real dataset metadata._

- [x] 107. Tighten publication evidence against weak positive effects
  - [x] 107.1 Require uncertainty-aware method-effect strength for CCF-B/Q3 gates
    - Add a publication-audit target parameter for the minimum baseline-vs-candidate delta measured in standard errors.
    - Require CCF-B and Q3 journal targets to reject positive method deltas that are smaller than 2.0 standard errors when uncertainty evidence is available.
    - Read uncertainty evidence from run-record metrics such as `accuracy_standard_error` as well as innovation artifacts such as `accuracy_delta_standard_error`.
    - Keep MVP demo targets usable for local loop correctness by not applying the standard-error threshold there.
    - Add a regression test showing that a weak positive delta fails publication audit instead of becoming a publishable claim.
    - Run a real Spambase autonomous cycle and confirm the system completes the loop but blocks publication/evidence release because the positive delta is only 0.76 standard errors.
    - Rerun publication audit on the stronger Pendigits and Letter cycles and confirm they still pass.
    - Rerun the cross-cycle CCF-B stability matrix over Pendigits, Letter, and Spambase and confirm stable-output claims remain blocked.
    - Do not hand-write root `autoresearch-vault/projects/.../progress` notes; only runtime-selected vault outputs under `runs/manual-live/...` count as system-written evidence for this task.
    - _References: `P-20260613-042`; task `105.1`; task `106.1`; user requirement for strict CCF-B/Q3 quality gates and real data/API validation._
    - _Verify: focused publication-audit tests, focused ruff, focused mypy, real Spambase `autopilot` with live search/LLM review/paper build/evidence gate, real Pendigits and Letter publication-audit reruns, and real three-cycle `publication-stability` rerun._

- [x] 108. Add autonomous LaTeX template diversity control
  - [x] 108.1 Make autopilot and serve paper templates configurable
    - Add `--paper-template-id` to `airesearcher autopilot`.
    - Add `--paper-template-id` to `airesearcher serve` so always-on operation can collect venue-template compatibility evidence without manual artifact patching.
    - Pass the selected template ID into the autonomous `paper-build` step and preserve it in the cycle summary, paper-build JSON, and evidence-gate-reviewed artifact.
    - Update the autopilot slash command template text to mention template selection.
    - Add a CLI regression test proving the selected template reaches `build_latex_paper_from_markdown`.
    - Run a real Letter Recognition autonomous cycle with `generic-article-two-column` and confirm publication audit, paper build, paper quality, and evidence gate pass.
    - Rerun the CCF-B stability matrix using release-allowed Pendigits plus Letter one-column/two-column cycles and confirm `paper_template_diversity` passes while `distinct_real_datasets` still blocks stable CCF-B/Q3 claims.
    - Do not hand-write root `autoresearch-vault/projects/.../progress` notes; template evidence must be runtime-generated under the selected vault.
    - _References: task `105.1`; `P-20260613-040`; user requirement that LaTeX template compatibility be tested, first with generic templates and later with venue templates._
    - _Verify: focused CLI tests, focused ruff, focused mypy, real two-column Letter `autopilot`, and real three-cycle `publication-stability` rerun with template diversity passing._

- [x] 109. Add third strong real-dataset release cycle for the stability matrix
  - [x] 109.1 Add UCI Skin Segmentation and repair domain similarity classification
    - Add `skin_variance_calibrated_prototypes` as a `run-demo` and `autopilot --demo` selector.
    - Extend the shared UCI variance demo runner to parse both comma-delimited and whitespace-delimited UCI source files without hand-edited run artifacts.
    - Download the real public UCI Skin Segmentation `Skin_NonSkin.txt` file at run time unless cached under the run directory.
    - Compare a z-score nearest-centroid RGB baseline against diagonal variance-calibrated skin/non-skin prototypes.
    - Record source URL, byte count, SHA256, split policy, data hash, validation report, evidence map, run record, ablation, predictions, and innovation evidence.
    - Add demo-aligned autopilot literature seeds and candidate metadata for Skin Segmentation so live search targets skin detection, RGB prototype classification, Gaussian/Bayesian segmentation, and skin-color prior work.
    - Add conservative similarity classifier support for skin-color and skin-segmentation adjacent work while keeping broad `skin color` social-media usage and unrelated segmentation tasks unknown.
    - Run a real Skin autonomous cycle and require publication audit, LLM evidence review, reproduction check, LaTeX paper quality, and evidence gate to pass.
    - Rerun the `ccf-b-matrix` over release-allowed Pendigits, Letter, and Skin cycles and require stable output to pass with 3 distinct real datasets and at least 2 LaTeX templates.
    - Do not hand-write root `autoresearch-vault/projects/.../progress` notes; only runtime-selected vault outputs under `runs/manual-live/...` count as system-written evidence for this task.
    - _References: task `105.1`; task `108.1`; `P-20260613-040`; `P-20260613-043`; user requirement for strict CCF-B/Q3 quality gates, real scripts/data, real API calls, and no fabricated results._
    - _Verify: focused demo/CLI/similarity tests, focused ruff, focused mypy, real UCI Skin `run-demo`, first real Skin `autopilot` blocked by classified-similarity breadth, fixed classifier, second real Skin `autopilot` passing publication/evidence gates, real `publication-stability --target ccf-b-matrix` passing with score `1.000`, then full ruff, mypy, and smoke/unit tests._

- [x] 110. Require venue-template evidence for stable CCF-B/Q3 claims
  - [x] 110.1 Add external venue-template coverage to the publication stability matrix
    - Extend publication-stability cycle records to preserve the paper-build template source kind, not only the template ID.
    - Require the `ccf-b-matrix` target to include at least one release-allowed cycle compiled with an external fetched venue or publisher template.
    - Keep the lighter `mvp-matrix` usable without an external template requirement.
    - Add a regression test proving three release-allowed generic-template cycles are blocked even when dataset and template-count diversity pass.
    - Add a regression test proving a matrix with an external fetched template passes the new coverage check.
    - Update `/research:publication-stability` wording so operators know generic article templates do not satisfy the venue-template bar.
    - Run a real external-template paper build first to catch missing LaTeX packages or layout failures.
    - Run a real autonomous cycle with an external venue or publisher template and require publication audit, LLM evidence review, reproduction check, paper quality, and evidence gate to pass.
    - Rerun `publication-stability --target ccf-b-matrix` with at least one external-template release cycle and require `external_template_coverage` to pass.
    - Do not hand-write root `autoresearch-vault/projects/.../progress` notes; only runtime-selected vault outputs under `runs/manual-live/...` count as system-written evidence for this task.
    - _References: task `100.1`; task `105.1`; task `108.1`; task `109.1`; `P-20260613-044`; user requirement that final paper-level output use LaTeX templates compatible with real venues or journals._
    - _Verify: focused stability/CLI tests, focused ruff, focused mypy, real generic-only `publication-stability` blocking on `external_template_coverage`, real Springer Nature `paper-build` preflight downloading `sn-jnl.cls` and passing paper quality, real Skin Segmentation `autopilot` with `springer-nature-sn-jnl` passing publication/evidence gates, and real three-cycle `ccf-b-matrix` passing with 1 external fetched template._

- [x] 111. Require conference and journal template evidence plus final-manuscript review
  - [x] 111.1 Gate stable output on external conference and journal templates
    - Extend publication-stability targets to distinguish external fetched conference templates from external fetched journal templates.
    - Require `ccf-b-matrix` to include at least one release-allowed external conference template and at least one release-allowed external journal template.
    - Keep `mvp-matrix` free of conference/journal template category requirements.
    - Add regression tests proving generic-only and journal-only matrices are blocked even when release count, datasets, and generic template diversity pass.
    - Repair conference-template manuscript quality so ACM/IEEE-style two-column builds meet page count, word count, section-depth, and zero-overfull-hbox requirements.
    - Change autonomous LLM evidence review to review the final `paper-manuscript/manuscript.md` instead of the thin demo report.
    - Add a compact `review-evidence-context.json` evidence bundle so live review sees final-manuscript context without overlong prompts.
    - Tighten manuscript prose so title-level literature hits, per-paper similarity classifications, audit/build pre-announcements, ablation labels, and script-step reconstructions are not promoted beyond local evidence.
    - Require publication audit and evidence gate review binding to prefer `paper_manuscript.markdown_path`, while continuing to require run record, validation report, and evidence map coverage.
    - Run real ACM and IEEE conference-template preflights and require paper quality to pass.
    - Run a real ACM `autopilot` cycle with live ArXiv/OpenAlex search, live LLM review, reproduction check, publication audit, LaTeX build, paper quality, and evidence gate all passing.
    - Rerun `publication-stability --target ccf-b-matrix` with release-allowed generic, ACM conference, and Springer journal cycles and require `external_conference_template_coverage` plus `external_journal_template_coverage` to pass.
    - Do not hand-write root `autoresearch-vault/projects/.../progress` notes; project progress notes in the canonical vault are runtime-owned by AI-Researcher, while coding agents only update `Agent.md`, `Problem.md`, tasks, changelog, code, and tests.
    - _References: task `103.1`; task `108.1`; task `110.1`; `P-20260613-045`; `P-20260613-046`; `P-20260613-047`; user requirement that CCF-B/Q3 claims use real conference/journal LaTeX templates, real API review, strict evidence gates, and no manually fabricated Obsidian progress notes._
    - _Verify: focused manuscript/LLM/CLI/publication-audit/evidence-gate/stability tests, focused ruff, focused mypy, real ACM and IEEE preflight `paper-build` runs passing quality, repeated real ACM `autopilot` runs until live LLM/evidence feedback was resolved, final real ACM `autopilot` with `evidence_gate=pass` and 0 follow-up tasks, and real three-cycle `ccf-b-matrix` passing with score `1.000`._

- [x] 112. Require verified citation packages before CCF-B/Q3 paper claims
  - [x] 112.1 Add autopilot citation-package generation and publication-audit citation gates
    - Generate `references.bib` and `references.metadata.json` from the real `DocumentRecord` objects returned by online literature refresh inside every non-blocked autopilot cycle.
    - Record citation package status, verified count, blocked count, BibTeX path, metadata path, blocked document IDs, and per-citation status in `cycle-summary.json`.
    - Add citation package artifacts to the compact review context and LLM review evidence bundle.
    - Update the publication manuscript references section so formal literature references come only from DOI/URL-verified citation metadata, while local run/audit artifacts remain separate evidence references.
    - Extend `ccf-b` and `q3-journal` publication-audit targets with minimum verified citation counts and maximum blocked citation counts; keep `mvp-demo` unblocked by citation package requirements.
    - Block CCF-B/Q3 publication audit when citation metadata or BibTeX is missing, when verified DOI/URL citation breadth is too low, or when any citation remains blocked.
    - Add regressions proving missing citation packages and blocked citations fail CCF-B/Q3 audit, while valid citation packages pass.
    - Run a real old-cycle audit to prove historical cycles without citation packages are no longer treated as publishable.
    - Run a new real ACM `autopilot` cycle with live literature retrieval, generated citation package, final-manuscript LLM review, publication audit, paper build, and evidence gate all passing.
    - Do not hand-write root `autoresearch-vault/projects/.../progress` notes; only runtime outputs under `runs/manual-live/...` count as AI-Researcher-written vault evidence for this task.
    - _References: task `17.2`; task `103.1`; task `111.1`; `P-20260613-047`; `P-20260613-048`; user requirement that publication-grade claims use real online sources and must not fabricate citations or results._
    - _Verify: focused citation/publication-audit/manuscript/CLI tests, focused ruff, focused mypy, old real ACM cycle blocked on missing citation package, new real ACM `autopilot` producing 54 verified citations and 0 blocked citations with `review_status=passed`, `publication_audit=pass`, `paper_quality=true`, and `evidence_gate=pass`._

- [x] 113. Require related-work relevance before CCF-B/Q3 paper claims
  - [x] 113.1 Add citation relevance metadata, audit gates, and evidence-review-safe manuscript wording
    - Preserve abstract, venue, source URI, authors, and tags in citation metadata so publication audit can inspect source context instead of only DOI/URL presence.
    - Extend `ccf-b` and `q3-journal` publication targets with minimum relevant verified citation counts while keeping `mvp-demo` unblocked by relevance requirements.
    - Build relevance anchors from candidate metadata, demo metadata, task metadata, and the executed run record; count only verified citations whose title, abstract, venue, source URI, authors, or tags overlap with method, dataset, benchmark, baseline, or task anchors.
    - Add regression tests proving DOI/URL-verified but topically unrelated references fail `citation_relevance_breadth`.
    - Tighten the deterministic manuscript composer so it does not promote implementation details, ablation wording, artifact names, or metric-file interpretations beyond the attached run script, metrics, validation report, and evidence map.
    - Treat SciPilot Figure Skill, Nature Skills, and Research Architect / literature-review skills as reference-only future quality-gate candidates unless a later task explicitly installs or adapts them under their licenses.
    - Run a real old-cycle publication audit and require relevant verified citation breadth to pass only when metadata supports the research topic.
    - Run a new real ACM `autopilot` cycle with live ArXiv/OpenAlex retrieval, generated citation metadata, final-manuscript DeepSeek review, publication audit, paper build, and evidence gate all passing.
    - Do not hand-write root `autoresearch-vault/projects/.../progress` notes; only runtime outputs under `runs/manual-live/...` count as AI-Researcher-written vault evidence for this task.
    - _References: task `112.1`; task `111.1`; `P-20260613-047`; `P-20260613-048`; `P-20260613-049`; SciPilot Figure Skill, Nature Skills, and Research Architect repositories as reference-only quality-gate ideas._
    - _Verify: focused citation/publication-audit/manuscript/CLI tests, focused ruff, focused mypy, real old-cycle audit at `runs/manual-live/task113-relevance-old-cycle-audit-v3` passing relevance over the existing citation cycle, first real task `113.1` cycle blocked by live LLM `needs_revision`, and final real ACM `autopilot` at `runs/manual-live/task113-relevance-cycle-v2/cycle-20260613T130219Z/cycle-summary.json` with 54 verified citations, 46 relevant verified citations, 0 blocked citations, `review_status=passed`, reviewer `verdict=pass`, unsupported claims `[]`, `publication_audit=pass`, paper PDF compiled with 6 pages / 4095 words / 0 overfull hboxes, and `evidence_gate=pass`._

- [x] 114. Align strict live reviewer evidence windows with CCF-B/Q3 release gates
  - [x] 114.1 Block weak reviewer verdicts and expose compact manuscript support evidence
    - Treat strict CCF-B/Q3 live-review `verdict=needs_revision` as a blocking publication-audit result even when the structured review status field is `passed`.
    - Build the autopilot review evidence context after final manuscript and paper-build artifacts exist, so the LLM reviewer sees the actual manuscript, paper quality, citation package, audit summary, candidate metadata, selected run record, task metadata, and formal-reference provenance.
    - Add compact candidate, method, research-gap, run-metric, and citation-metadata summaries to `review-evidence-context.json` without embedding secrets or unrelated full artifacts.
    - Record `feature_count` and key method parameters such as `variance_shrinkage` in variance-calibrated UCI demos, run records, task metadata, and manuscript method/results prose.
    - Weaken manuscript wording that implied exact similarity query templates or classified-result counts unless those statements are directly present in local artifacts.
    - Add regression tests proving strict reviewer verdicts block CCF-B audit and that review context exposes candidate, metric, formal-reference, and citation-metadata evidence needed by live review.
    - Fix the full smoke/unit regression where Pendigits variance-calibrated demo metrics omitted `feature_count` even though the task contract required it.
    - Run a real ACM `autopilot` cycle with live ArXiv/OpenAlex retrieval, real LLM review, generated citations, paper build, publication audit, and evidence gate all passing under the stricter evidence window.
    - Rerun a real `publication-stability --target ccf-b-matrix` over the current passing ACM cycle plus historical passing template cycles; record that the current cycle has the newest strict evidence-window fix.
    - Do not hand-write root `autoresearch-vault/projects/.../progress` notes; only runtime outputs under `runs/manual-live/...` count as AI-Researcher-written vault evidence for this task.
    - _References: task `113.1`; task `112.1`; task `111.1`; `P-20260613-049`; `P-20260613-050`; `P-20260613-051`; user requirement that publication output be evidence-backed to a CCF-B/Q3-style standard and checked by real API calls._
    - _Verify: focused CLI/manuscript/demo/publication-audit tests; full `tests/smoke tests/unit`; focused ruff; focused mypy; old-cycle audit proving `needs_revision` is now blocking; final real ACM `autopilot` at `runs/manual-live/task114-citation-context-cycle/cycle-20260613T144509Z/cycle-summary.json` with `review_status=passed`, reviewer `verdict=pass`, unsupported claims `[]`, `publication_audit=pass`, `evidence_gate=pass`, and 0 follow-up tasks; real stability matrix at `runs/manual-live/task114-citation-context-stability/publication-stability.json` with `stable=true` and score `1.000`._

- [x] 115. Require strict review-context freshness in publication stability matrices
  - [x] 115.1 Add matrix-level strict context gates and regenerate stale release cells
    - Add `require_strict_review_context` to the `ccf-b-matrix` stability target so release candidates cannot be counted from historical cycles that predate the final-manuscript review evidence window.
    - Parse each cycle's `llm-review.json` and `review-evidence-context.json` in the publication-stability report, then record reviewer verdict, reviewer quality score, strict context path, and strict context status for every matrix cell.
    - Require every release-allowed CCF-B/Q3 matrix cell to have reviewer `verdict=pass`, a present final-manuscript review evidence context, formal-reference citation metadata coverage, candidate `feature_count`, and passing paper-quality context.
    - Keep the lighter `mvp-demo` stability target usable without strict review context so local scaffolding and early demos are not blocked by publication-grade checks.
    - Run the current strict matrix gate against the old task `114.1` stability set and confirm it blocks stale Pendigits/Skin cells that lack `review-evidence-context.json`.
    - Rerun real live `autopilot` cycles for Pendigits/generic and Skin/Springer using the current strict review context, real online literature retrieval, real LLM review, publication audit, paper build, and evidence gate.
    - Tighten deterministic manuscript prose when live review detects unsupported wording about similarity query coverage or parsed/classified nearby-work trails.
    - Rerun `publication-stability --target ccf-b-matrix` over fresh Pendigits/generic, current Letter/ACM, and fresh Skin/Springer cycles; require score `1.000`, three release-allowed real datasets, three LaTeX templates, at least one external conference template, at least one external journal template, and `strict_review_context_all_releases=pass`.
    - Do not hand-write root `autoresearch-vault/projects/.../progress` notes; only runtime outputs under `runs/manual-live/...` count as AI-Researcher-written vault evidence for this task.
    - _References: task `114.1`; task `113.1`; task `112.1`; `P-20260613-052`; `P-20260613-053`; user requirement that stability claims be backed by current real API calls, real evidence, and strict CCF-B/Q3-style quality gates._
    - _Verify: focused manuscript/stability tests; focused ruff; focused mypy; old real matrix at `runs/manual-live/task115-strict-context-old-matrix/publication-stability.json` blocked on missing strict review context; fresh Skin/Springer live cycle at `runs/manual-live/task115-skin-strict-v2-cycle/cycle-20260613T150624Z/cycle-summary.json` with `review_status=passed`, `publication_audit=pass`, `evidence_gate=pass`; fresh Pendigits/generic live cycle at `runs/manual-live/task115-pendigits-strict-v2-cycle/cycle-20260613T151155Z/cycle-summary.json` with `review_status=passed`, `publication_audit=pass`, `evidence_gate=pass`; final matrix at `runs/manual-live/task115-strict-context-current-matrix/publication-stability.json` with `stable=true`, score `1.000`, and `strict_review_context_all_releases=pass`._

- [x] 116. Require source-backed related-work inspection before CCF-B/Q3 release
  - [x] 116.1 Add related-work inspection artifacts, audit gates, and refreshed strict matrix
    - Generate a first-class `related-work/related-work-inspection.json` and `related-work/related-work-inspection.md` artifact from live citation metadata in every non-blocked autopilot cycle.
    - Record per-citation inspection fields including citation status, BibTeX key, title, source locator, evidence basis, abstract snippet, method/dataset/baseline overlap terms, comparison status, and whether the comparison is source-backed or only metadata-backed.
    - Treat the inspection as a screening artifact, not proof of novelty: label direct method candidates, benchmark/baseline context, method-term context, metadata-only rows, blocked rows, and unrelated rows without inventing conclusions beyond local source evidence.
    - Add CCF-B/Q3 publication-audit gates for related-work inspection package presence, minimum inspected records, minimum abstract-backed records, and minimum direct method candidates; keep `mvp-demo` unblocked by these publication-grade thresholds.
    - Add the related-work inspection summary and artifact paths into autopilot review context, review evidence paths, manuscript evidence references, and publication-audit summary.
    - Extend publication-stability strict context so release-allowed CCF-B/Q3 matrix cells must include related-work inspection evidence with nonzero inspected, abstract-backed, and direct-method counts.
    - Tighten deterministic manuscript wording after live review rejected system-design overclaims, so manuscripts describe implementation controls as evidence boundaries rather than standalone contributions.
    - Run an old-cycle publication audit and old three-cycle matrix to prove historical release evidence without source-backed related-work inspection is blocked under the new gate.
    - Rerun real live `autopilot` cycles for Pendigits/generic, Letter/ACM, and Skin/Springer with live ArXiv/OpenAlex retrieval, generated citation packages, related-work inspection artifacts, real LLM review, publication audit, LaTeX build, paper quality, evidence gate, and 0 follow-up tasks.
    - Rerun `publication-stability --target ccf-b-matrix` over the three refreshed cycles and require score `1.000`, three release-allowed real datasets, three LaTeX templates, external conference and journal coverage, paper-quality pass, strict review context pass, and related-work inspection counts in every matrix cell.
    - Do not hand-write root `autoresearch-vault/projects/.../progress` notes; only runtime outputs under `runs/manual-live/...` count as AI-Researcher-written vault evidence for this task.
    - _References: task `115.1`; task `114.1`; task `113.1`; `P-20260613-054`; `P-20260613-055`; user requirement that generated papers use real online literature, source-backed cross-checking, conservative claims, and strict CCF-B/Q3-style quality gates._
    - _Verify: focused related-work/publication-audit/stability/manuscript/CLI tests; focused ruff; focused mypy; old real audit at `runs/manual-live/task116-related-work-old-audit/publication-audit.json` blocked on missing related-work inspection; old real matrix at `runs/manual-live/task116-related-work-old-matrix/publication-stability.json` blocked with `missing_related_work_inspection`; fresh Pendigits/generic cycle at `runs/manual-live/task116-related-work-pendigits-cycle/cycle-20260613T154024Z/cycle-summary.json` with `review_status=passed`, `publication_audit=pass`, `evidence_gate=pass`; fresh Letter/ACM cycle at `runs/manual-live/task116-related-work-letter-v2-cycle/cycle-20260613T153611Z/cycle-summary.json` with 54 inspected related-work records, 51 abstract-backed records, 11 direct-method candidates, `review_status=passed`, `publication_audit=pass`, and `evidence_gate=pass`; fresh Skin/Springer cycle at `runs/manual-live/task116-related-work-skin-cycle/cycle-20260613T154125Z/cycle-summary.json` with `review_status=passed`, `publication_audit=pass`, `evidence_gate=pass`; final matrix at `runs/manual-live/task116-related-work-current-matrix/publication-stability.json` with `stable=true`, score `1.000`, `strict_review_context_all_releases=pass`, and related-work abstract/direct counts present for every release cell._

- [x] 117. Make deployment and paper outputs user-facing from guided setup
  - [x] 117.1 Add guided setup, root output bundle, and OA-first PDF-source manifest
    - Add `airesearcher setup` as the default first-deploy configuration wizard that walks a normal user through provider selection, API base URL, model name, API key, optional WeChat/Feishu channel values, Obsidian vault assets, channel adapter runbooks, OpenCode backend manifest, ScanSci PDF source manifest, and slash command templates.
    - Keep `airesearcher deploy-setup` as the narrower backward-compatible configuration command.
    - Add an npm-style wrapper so normal users can run `npm run setup`, `npm run serve`, and `npm run doctor` without learning Poetry command prefixes.
    - Remove hard-coded default completion-token limits from live LLM smoke/review/autopilot paths; `--max-tokens` must be optional and omitted from the OpenAI-compatible request payload unless the operator explicitly provides it.
    - Publish completed autopilot paper bundles under project-root `outputs/<project-id>/`, with `<project-id>-<cycle-id>.pdf` when LaTeX compilation succeeds plus a manifest and Markdown index whose paths are relative to the project root when possible.
    - Record ScanSci PDF as an optional PDF retrieval backend only with OA/legal-first defaults; keep Sci-Hub, LibGen, WebVPN/CARSI, Tor, Cloudflare bypass, and credentialed proxy paths approval-gated and license-review-gated.
    - Update English and Chinese README quick-start guidance to make `airesearcher setup` / `npm run setup` the normal guided entry point, document `outputs/<project-id>/`, and explain the ScanSci PDF boundary.
    - Run focused unit tests for LLM request payloads, CLI setup, ScanSci integration, and autopilot deliverable export; run focused lint/type checks for touched modules; run real `airesearcher setup`, real `llm-smoke`, and one real live autopilot cycle using the configured `.env`; verify the generated PDF bundle exists under `outputs/`.
    - Do not install third-party coding backends or channel plugins from `airesearcher setup`; upstream plugin commands may appear only in generated adapter runbooks and must require a separate operator decision.
    - Verify that the guided setup experience mirrors the safe parts of provider onboarding: choose provider, enter or reuse credentials, choose optional channels, then write local AI-Researcher config without executing third-party plugin installers.
    - Add an operator-facing terminal monitor so users can see Agent messages, active session claims, approval/task queues, research information flow, git changes, and output previews in one CLI surface.
    - _References: user request for guided setup rather than manual subcommands, no manual `max_tokens`, ScanSci PDF review, root `outputs/` PDF publication, Computer Use deployment check, OpenCode `/connect` provider flow, WeChat/Feishu upstream plugin reuse without runtime fusion, Hermes/skills self-evolution inspiration, and npm-like UX._
    - _Verify: focused tests, ruff, mypy, real guided setup smoke, real LLM smoke without `max_tokens`, real autopilot cycle with `outputs/<project-id>/<project-id>-<cycle-id>.pdf`, manifest path inspection, monitor rendering smoke, and verification that setup does not install third-party channel plugins._

- [x] 118. Final prelaunch paper artifact quality sprint
  - [x] 118.1 Fix bibliography, visual analysis, and archive/deliverable separation
    - Move run evidence records such as cycle summary, validation, evidence map, literature refresh, citation package, related-work inspection, similarity check, reproduction check, publication audit, and paper build out of the formal References section.
    - Render those records as an evidence/artifact availability table inside the manuscript so the Obsidian Markdown version remains useful for project experience, evidence tracing, and archival review.
    - Keep `autoresearch-vault/` as the canonical Markdown memory/archive target for manuscript and paper-build summaries; keep project-root `outputs/<project-id>/` as the publication/deliverable target for PDF, TeX, manifest, and release bundle copies.
    - Generate at least one source-backed visual analysis figure from the real run metrics object and include it in the final LaTeX/PDF artifact.
    - Generate at least one source-backed data-analysis table from the same real run metrics and include it in both the Obsidian Markdown manuscript and the final PDF.
    - Convert formal literature references into LaTeX `thebibliography` entries with stable citation keys instead of plain bracket labels, and block paper quality when non-bibliographic bracket labels remain in the References section.
    - Apply reference-only academic-writing guidance inspired by `Leey21/awesome-ai-research-writing`: reviewer-perspective logic checks, clean LaTeX, concise paper-style prose, experiment-analysis tables, figure/caption discipline, and submission-checklist thinking without copying upstream prompt text into the repository.
    - Extend the paper quality gate so missing figures, missing data tables, missing formal bibliography entries, reference-format regressions, and layout overflow are release blockers.
    - Rerun the real manuscript/PDF build path with configured live evidence and verify that the new PDF in `outputs/<project-id>/` contains the bibliography, figure/table analysis, relative paths, and no screenshot-style pseudo-reference labels.
    - _References: user screenshot showing malformed `[Cycle summary]`-style references; user requirement that Markdown versions are vault knowledge/archive artifacts while PDF versions under `outputs/` are direct publication artifacts; task `117.1` output bundle._
    - _Verify: `python -m ruff check src tests` passed; `python -m mypy src\autoresearch` passed; `python -m pytest tests\smoke tests\unit -q` passed with 464 passed, 4 skipped, and 1 warning. Real live autopilot final-v2 runs passed review, publication audit, and evidence gate for Pendigits/generic at `runs/manual-live/task118-final-release-pendigits-v2/cycle-20260615T030141Z/cycle-summary.json`, Letter/ACM at `runs/manual-live/task118-final-release-letter-v2/cycle-20260615T025959Z/cycle-summary.json`, and Skin/Springer at `runs/manual-live/task118-final-release-skin-v2/cycle-20260615T030309Z/cycle-summary.json`. Generated PDFs are `outputs/ai_researcher_task118_final_pendigits_v2/ai_researcher_task118_final_pendigits_v2-cycle-20260615T030141Z.pdf`, `outputs/ai_researcher_task118_final_letter_v2/ai_researcher_task118_final_letter_v2-cycle-20260615T025959Z.pdf`, and `outputs/ai_researcher_task118_final_skin_v2/ai_researcher_task118_final_skin_v2-cycle-20260615T030309Z.pdf`. TeX inspection confirmed `thebibliography`, `\bibitem`, `\includegraphics`, `tabular`, Data Analysis, and Evidence and Artifact Availability; regression search found no `[Cycle summary]`-style pseudo-reference labels, `Springer Nature build`, `publication score`, `configured audit target`, or `This draft` in final Markdown/TeX._

- [x] 119. V1.0 release-readiness cleanup and user onboarding
  - [x] 119.1 Add inspiration push, repository hygiene, and V1.0 README release guide
    - Run Git object maintenance after the loose-object warning and verify loose object and garbage counts return to zero.
    - Keep runtime outputs out of GitHub by ignoring `outputs/`, runtime cache/state directories, and generated vault run notes while preserving the tracked Obsidian vault scaffold and selected durable knowledge files.
    - Add a direct webhook notification path for broad-inspiration digests so `inspiration-refresh --push` and `serve/autopilot --push-inspiration` can push to configured WeChat/Feishu webhooks.
    - Keep push delivery evidence explicit: `sent`, `failed`, or `skipped`, with JSON records in command output artifacts and cycle summaries.
    - Update npm `serve` to the V1.0 recommended operator entry point with approval gates and inspiration push enabled.
    - Bump project version metadata to `1.0.0` consistently across Python and npm entry points.
    - Rewrite `README.md` and `README.zh-CN.md` as product-style onboarding pages with guided setup, daily loop, push behavior, slash commands, parameters, outputs, boundaries, references, and license notes.
    - Add a README-visible CLI monitor screenshot asset showing agent messages, active agents, information flow, approvals/tasks, changes, and output previews.
    - Remove stale user-facing command fragments such as nonexistent `--live` literature/similarity options and old Poetry-prefixed operator commands from generated templates.
    - _References: user request to handle Git loose objects, keep GitHub repository focused on necessary code, perform a final V1.0 check, document guided setup and slash commands, include the CLI Agent-flow UI screenshot, and verify daily scheduled retrieval plus inspiration push._
    - _Verify: `git gc --prune=now` completed and `git count-objects -vH` reported `count: 0`, `packs: 1`, `garbage: 0` immediately after maintenance; full `python -m ruff check src tests`, `python -m mypy src\autoresearch`, and `python -m pytest tests\smoke tests\unit -q` passed with 468 passed, 4 skipped, and 1 warning; real `inspiration-refresh --push --push-channel feishu` fetched one live Hacker News inspiration item and recorded Feishu push as `skipped` because `AUTORESEARCH_FEISHU_WEBHOOK_URL` was not set; `serve --once --permission-mode approve-dangerous --push-inspiration` and `npm run serve -- --once` both stopped at the expected approval gate; `node .\bin\airesearcher.mjs version` returned `1.0.0`; `node .\bin\airesearcher.mjs monitor --no-diff --max-agent-entries 2` rendered the operator console; `node .\bin\airesearcher.mjs slash-commands init/list --directory .tmp-slash-check` generated and listed 20 slash command templates; command-help checks confirmed `inspiration-refresh --env-path/--push`, `autopilot --push-inspiration`, `serve --push-inspiration`, `--cycles 0`, and default `--interval-seconds 86400` exist; README/source-template regression search found no stale `literature-refresh --live`, `similarity-check ... --live`, `poetry run airesearcher`, old `autoresearch deploy`, or mojibake markers in the release docs/source templates._

- [x] 120. IM channel setup UX correction
  - [x] 120.1 Make setup own WeChat QR and Feishu App credential onboarding
    - Treat `.env` as setup-owned local storage, not a manual user-editing step for normal deployment.
    - Add channel connection mode metadata to config so WeChat QR, Feishu app gateway, and webhook fallback are distinguishable.
    - Add `--wechat-qr`, `--run-wechat-qr-setup`, `--feishu-connection-mode`, `--feishu-home-chat-id`, and `--feishu-allowed-users` to `deploy-setup` and `setup`.
    - Make the interactive setup wizard recommend WeChat QR adapter onboarding and Feishu App ID/App Secret onboarding before webhook fallback.
    - When an interactive setup user chooses WeChat QR onboarding, start the QR setup command after writing config and wait for the adapter's scan/login result; non-interactive scripts may record QR setup state without blocking unless explicitly requested.
    - Add Feishu App credential digest delivery through the Feishu/Lark tenant token and message API when `AUTORESEARCH_FEISHU_HOME_CHAT_ID` is available.
    - Keep WeChat QR delivery honest: record QR gateway/session state as required and do not claim delivery when the adapter session is not active.
    - Update `.env.example`, README, README.zh-CN, THIRD_PARTY_NOTICES, slash-template wording, and the README monitor image so user-facing docs no longer imply webhook-only IM setup.
    - _References: user correction that Hermes-style IM setup should collect Feishu App credentials and WeChat QR login during setup rather than asking users to hand-edit `.env`; Hermes Feishu/Lark setup docs and WeChat QR setup issue review._
    - _Verify: `python -m ruff check src tests` passed; `python -m mypy src\autoresearch` passed; `python -m pytest tests\smoke tests\unit -q` passed with 473 passed, 4 skipped, and 1 warning. `python -m pytest tests\unit\cli\test_main.py::test_setup_guided_wechat_qr_runs_qr_setup tests\unit\cli\test_main.py::test_deploy_setup_configures_qr_wechat_and_feishu_app_gateway tests\unit\test_notifications.py -q` passed with 8 tests. Real non-interactive `node .\bin\airesearcher.mjs setup ... --wechat --wechat-qr --feishu ... --non-interactive` wrote WeChat QR and Feishu websocket config and printed the QR setup next step without blocking; interactive coverage verifies setup runs the QR setup runner automatically when the user chooses QR. Real `node .\bin\airesearcher.mjs inspiration-refresh --query "AI research agents datasets" ... --push --push-channel wechat` fetched one Hacker News item and recorded WeChat QR gateway state as `skipped` instead of fake delivery._

- [x] 121. External research-skill watchlist
  - [x] 121.1 Capture screenshot-discovered research skill ideas as quarantined Obsidian candidates
    - Treat user-provided research-skill screenshots as discovery signals, not verified upstream projects or validated capabilities.
    - Review public sources for related projects before documenting them: SimpleMem/Omni-SimpleMem, SkillClaw, Auto-Empirical Research Skills, paper-craft-skills, citation-management, Deep-Research-skills, and deer-flow deep-research.
    - Add an Obsidian watchlist writer that stores external skill candidates under `exploration/skills/external-research-skill-watchlist.md` with source refs, license status, adoption stage, expected benefit, risk notes, validation gates, and quarantine policy.
    - Add `airesearcher skill-watchlist` and `/research:skill-watchlist` so the system, not manual Markdown edits, can ingest these candidates into the vault.
    - Keep all third-party skill projects reference-only: do not copy, vendor, adapt, install, or promote upstream skill text, prompts, assets, examples, generated outputs, or code.
    - Update README, README.zh-CN, third-party notices, compliance tests, and skill tests so future agents preserve the license and validation boundary.
    - _References: user screenshots listing CCFA-Skill, Paper-Skill, Question-Validator, Empirical-Paper, Paper-to-Patent, In-depth-Research, Paper-to-Storyboard, Source-Tracing, Paper2Beamer, Research-Genealogy, plus the Omni-SimpleMem memory-base screenshot; live web review of related public repositories and papers._
    - _Verify: `python -m ruff check src\autoresearch\knowledge\skills.py src\autoresearch\knowledge\__init__.py src\autoresearch\cli\main.py tests\unit\knowledge\test_skills.py tests\unit\cli\test_main.py tests\unit\compliance\test_licenses.py` passed; `python -m mypy src\autoresearch` passed; `python -m pytest tests\unit\knowledge\test_skills.py tests\unit\cli\test_main.py::test_skill_watchlist_writes_external_candidates tests\unit\cli\test_main.py::test_slash_commands_init_and_list_project_templates tests\unit\compliance\test_licenses.py::test_project_notice_tracks_third_party_reference_policy -q` passed with 15 tests; full `python -m pytest tests\smoke tests\unit -q` passed with 476 passed, 4 skipped, and 1 warning. Real `node .\bin\airesearcher.mjs skill-watchlist --vault runs\manual-live\task121-skill-watchlist-vault --source-note "2026-06-15 user screenshot skill scouting smoke"` wrote `runs/manual-live/task121-skill-watchlist-vault/exploration/skills/external-research-skill-watchlist.md` with 12 quarantined candidates._

- [x] 122. External agent-harness reference quarantine
  - [x] 122.1 Add oh-my-openagent as a license-risk, reference-only watchlist candidate
    - Review public upstream sources before documenting the project: GitHub README, raw `LICENSE.md`, package metadata, and installer/setup behavior.
    - Treat `code-yeongyu/oh-my-openagent` / LazyCodex as an OpenCode/Codex agent-harness reference, not as an AI-Researcher dependency, research skill, installer step, or bundled component.
    - Add a default watchlist candidate with source refs, SUL-1.0 license status, `reference-only-license-risk` adoption stage, expected benefit, risk notes, and validation gates.
    - Update README, README.zh-CN, third-party notices, compliance tests, and skill tests so future agents preserve the no-install/no-vendor boundary.
    - Keep concepts such as Team Mode visualization, hash-anchored edits, LSP/AST tooling, rule injection, and long-running coding loops available for later independent design only after license, security, telemetry, config-mutation, validation, and rollback review.
    - _References: user-provided `https://github.com/code-yeongyu/oh-my-openagent`; live review found upstream `package.json` declaring `SUL-1.0`, raw `LICENSE.md` limiting use/modification to internal, non-commercial, or personal use, README installer docs that can write Codex/OpenCode config and enable autonomous permissions, and README telemetry notes._
    - _Verify: Live web review checked `https://github.com/code-yeongyu/oh-my-openagent`, raw `LICENSE.md`, installer README sections, and `package.json`; upstream package metadata declares `SUL-1.0`, raw license text limits use/modification to internal business, non-commercial, or personal use, installer docs describe Codex/OpenCode config writes plus optional autonomous permissions, and telemetry is documented as enabled by default. `python -m ruff check src\autoresearch\knowledge\skills.py tests\unit\knowledge\test_skills.py tests\unit\compliance\test_licenses.py` passed; `python -m mypy src\autoresearch` passed; `python -m pytest tests\unit\knowledge\test_skills.py tests\unit\compliance\test_licenses.py::test_project_notice_tracks_third_party_reference_policy -q` passed with 13 tests; real `node .\bin\airesearcher.mjs skill-watchlist --vault runs\manual-live\task122-openagent-watchlist-vault --source-note "2026-06-15 oh-my-openagent reference smoke"` wrote 13 quarantined candidates, and `rg` confirmed the oh-my-openagent entry contains `reference-only-license-risk`, `SUL-1.0`, and no-install gates; full `python -m pytest tests\smoke tests\unit -q` passed with 476 passed, 4 skipped, and 1 warning; `git diff --check` passed._

- [x] 123. Browser-native source acquisition reference
  - [x] 123.1 Add PageAgent as a quarantined browser-source adapter reference
    - Review public upstream sources before documenting the project: GitHub README, raw `LICENSE`, package metadata, and official docs/page positioning.
    - Treat `alibaba/page-agent` as a future browser-source acquisition and AI-native browser UX reference for Horizon-style broad discovery beyond public APIs, not as a V1.0 crawler, bundled dependency, or default runtime tool.
    - Add a default watchlist candidate with MIT license status, browser-source adoption stage, expected benefit, risk notes, and validation gates for robots/ToS, rate limits, isolated profiles, source snapshots, action logs, and approval.
    - Update README, README.zh-CN, third-party notices, compliance tests, and skill tests so future agents preserve the distinction between current API-first inspiration refresh and future browser acquisition.
    - _References: user note that PageAgent could let the Horizon-style loop avoid being limited to API-only web sources; live review found `alibaba/page-agent` is MIT, in-page JavaScript based, uses text-based DOM manipulation, supports optional Chrome extension and MCP server ideas, and upstream states it is client-side web enhancement rather than server-side automation._
    - _Verify: Live web review checked `https://github.com/alibaba/page-agent`, raw `LICENSE`, `package.json`, and official docs/site; upstream README describes in-page JavaScript, text-based DOM manipulation, optional Chrome extension, and MCP server ideas, while also stating PageAgent is client-side web enhancement rather than server-side automation; raw license and package metadata are MIT. `python -m ruff check src\autoresearch\knowledge\skills.py tests\unit\knowledge\test_skills.py tests\unit\compliance\test_licenses.py` passed; `python -m mypy src\autoresearch` passed; `python -m pytest tests\unit\knowledge\test_skills.py tests\unit\compliance\test_licenses.py::test_project_notice_tracks_third_party_reference_policy -q` passed with 13 tests; real `node .\bin\airesearcher.mjs skill-watchlist --vault runs\manual-live\task123-pageagent-watchlist-vault --source-note "2026-06-16 PageAgent browser-source reference smoke"` wrote 14 quarantined candidates, and `rg` confirmed the generated PageAgent entry contains `browser-source-reference`, robots/ToS, isolated-browser, action-trace, and no-default-crawler gates; full `python -m pytest tests\smoke tests\unit -q` passed with 476 passed, 4 skipped, and 1 warning._

- [x] 124. Post-direction research-plan gate
  - [x] 124.1 Generate Obsidian Markdown and LaTeX/PDF research plans before experiments
    - Add a first-class `ResearchPlan` lifecycle schema between `ResearchCandidate` and executable experiments.
    - Add a deterministic research-plan generator that consumes a user-confirmed candidate, source evidence refs, dataset/method/baseline/metric metadata, and optional adjacent-work summaries.
    - Write the archival Markdown plan into the Obsidian vault under `projects/<project-id>/plans/research-plan.md` with `research_plan` entry type.
    - Write publication-facing plan artifacts under `outputs/<project-id>/research-plan/` as `research-plan.json`, `research-plan.tex`, and `research-plan.pdf` when LaTeX is available.
    - Keep the PDF as a normal research plan: no contest title, contest number, organizer, scoring table, competition wrapper, or project-name-as-topic.
    - Add quality gates for source references, evidence refs, source/target dataset route, baseline/control, concrete metric, command-oriented code-agent brief, and unsupported-result claims.
    - Add `airesearcher research-plan` and `airesearcher research-plan-audit`, plus `/research:research-plan`, so operators can run and re-audit the gate from CLI or slash templates.
    - Update English and Chinese README workflow, slash-command, parameter, and output documentation so users see the plan gate before experiments and paper builds.
    - Add schema, research, and CLI tests covering generation, audit blocking, slash-template initialization, and schema round trips.
    - _References: user requirement that after the user confirms a research direction the system must first create a detailed, specific, feasible, rigorous research plan that can guide code agents and experiments; the Markdown version belongs in the Obsidian knowledge base, while the PDF version belongs in `outputs/`; the plan/PDF should be a normal research plan for a system-discovered topic, not a contest proposal or the AI-Researcher project itself._
    - _Verify: `python -m ruff check src tests` passed; `python -m mypy src\autoresearch` passed; focused `python -m pytest tests\unit\research\test_plans.py tests\unit\cli\test_main.py::test_research_plan_command_writes_vault_markdown_and_outputs tests\unit\cli\test_main.py::test_research_plan_audit_blocks_forbidden_title -q` passed with 5 tests; full `python -m pytest tests\smoke tests\unit -q` passed with 482 passed, 4 skipped, and 1 warning. Real CLI smoke `node .\bin\airesearcher.mjs research-plan --candidate-file runs\manual-live\task124-research-plan\candidate.json --project-id task124_research_plan --vault runs\manual-live\task124-research-plan\vault --output-dir runs\manual-live\task124-research-plan\outputs --compile-pdf --timeout-seconds 180` passed, compiled a 3-page A4 PDF, wrote vault Markdown and JSON/TEX/PDF artifacts, and `research-plan-audit` passed on the generated JSON. `pdfinfo` confirmed 3 pages; `rg` confirmed the generated Markdown/TEX title preserves `UCI` and contains no `XH-202619`, `参赛`, `赛事`, `发榜`, `主办`, `评分`, `浙江阿里巴巴`, `AI-Researcher competition proposal`, or `AI-Researcher system`; `pdftoppm` rendered page 1 and visual inspection found no obvious overflow._

- [x] 125. Autopilot research-plan enforcement
  - [x] 125.1 Require a passed research-plan gate before inspiration, experiment, paper, and review work
    - Insert `generate_research_plan` into the autopilot cycle after source preflight, literature refresh, candidate generation, and similarity check, but before inspiration refresh and demo/code-agent execution.
    - Pass literature and similarity summary paths into the research-plan generator so the plan can bind claims to adjacent-work evidence.
    - Fail closed when the research-plan audit does not pass or the plan PDF does not compile: write a blocked `cycle-summary.json`, record `blocked_reason=research_plan_gate`, preserve scheduler follow-ups, and skip inspiration, experiment, paper, and review stages.
    - Include the research-plan artifact payload in successful cycle summaries and CLI status output.
    - Include the research-plan gate in the review audit context and add plan Markdown/JSON/TEX artifacts to review evidence inputs.
    - Export plan Markdown/JSON/TEX/PDF files through the autopilot deliverables manifest under the project output directory.
    - Add unit coverage for the successful autopilot path and the blocked-before-experiment path.
    - _References: Task `124.1` follow-up; user requirement that after research direction selection the system writes a concrete plan into Obsidian before code agents implement experiments; strict evidence-first loop where no unsupported or unplanned experiment should run._
    - _Verify: `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; focused `python -m pytest tests\unit\cli\test_main.py::test_autopilot_command_runs_one_non_review_cycle tests\unit\cli\test_main.py::test_autopilot_research_plan_gate_blocks_before_experiment -q` passed with 2 tests; `python -m mypy src\autoresearch` passed; `python -m ruff check src tests` passed; full `python -m pytest tests\smoke tests\unit -q` passed with 483 passed, 4 skipped, and 1 warning. Real autopilot smoke `node .\bin\airesearcher.mjs autopilot --vault runs\manual-live\task125-autopilot-plan\vault --cache runs\manual-live\task125-autopilot-plan\cache --output-dir runs\manual-live\task125-autopilot-plan\runs --deliverables-dir runs\manual-live\task125-autopilot-plan\outputs --state runs\manual-live\task125-autopilot-plan\scheduler-state.json --project-id task125_autopilot_plan --max-queries 1 --max-results-per-source 1 --timeout-seconds 60 --paper-template-id generic-article-one-column --no-review` passed, printed `[OK] research_plan: passed`, compiled a 3-page A4 research-plan PDF, ran the demo/reproduction path after the plan gate, exported `research_plan_markdown`, `research_plan_json`, `research_plan_tex`, and `research_plan_pdf` in the deliverables manifest, and kept the final publication/evidence gates blocked because the LLM evidence review was intentionally skipped by `--no-review`. `rg` confirmed the generated plan Markdown/TEX contains no `赛题`, `参赛`, `比赛`, `人工评审`, `manual review`, `TODO`, or `TBD`._

- [x] 126. Publication-grade live acceptance and LaTeX build stabilization
  - [x] 126.1 Verify a real benchmark cycle reaches release gates and stabilize paper-build reruns
    - Run a real always-on loop with the default publication search breadth, live model review, and a real public benchmark rather than the smoke-only tabular fixture.
    - Verify the generated paper-level PDF, research-plan PDF, LLM review, publication audit, evidence gate, citation package, related-work breadth, similarity breadth, reproduction rerun, data analysis figure/table package, and deliverables manifest.
    - Record the difference between smoke-loop failures and publication-grade acceptance: smoke runs may intentionally fail CCF-B/Q3 gates when they use tiny fixtures or `--no-review`.
    - Update the LaTeX paper builder so a successful first compile that reports changed labels, cross-reference rerun requests, or citation rerun requests automatically executes one more pass.
    - Keep failed LaTeX attempts diagnosable, but keep successful release logs focused on the final stable attempt and record `RERUNS_COMPLETED`.
    - Add unit coverage for the second-pass compile behavior without requiring a live LaTeX binary.
    - _References: user requirement that the system run real data/calls, produce a PDF under `outputs/`, fix reference/layout issues, include figures/tables, and only claim publication-readiness when the evidence and review gates pass._
    - _Verify: Real publication-grade autopilot `node .\bin\airesearcher.mjs autopilot --vault runs\manual-live\task126-pendigits-live\vault --cache runs\manual-live\task126-pendigits-live\cache --output-dir runs\manual-live\task126-pendigits-live\runs --deliverables-dir runs\manual-live\task126-pendigits-live\outputs --state runs\manual-live\task126-pendigits-live\scheduler-state.json --project-id task126_pendigits_live --demo pendigits_variance_calibrated_prototypes --timeout-seconds 180 --paper-template-id generic-article-one-column` passed with `[OK] research_plan: passed`, `[OK] review_status: passed`, `[OK] publication_audit: pass`, `[OK] evidence_gate: pass`, and `followup_tasks: 0`; summary inspection confirmed review verdict `pass`, quality score `1.0`, publication score `0.985`, publishable `true`, release allowed `true`, 4 literature queries, 65 normalized documents, 57 similarity findings, 65 verified citations, and a 3-page research plan. `pdfinfo` confirmed the paper PDF has 14 pages and the research-plan PDF has 3 pages. `pdftotext` confirmed references are numeric `[1]` style rather than operational pseudo-labels. `python -m ruff check src\autoresearch\reports\paper_build.py tests\unit\reports\test_paper_build.py` passed; `python -m pytest tests\unit\reports\test_paper_build.py -q` passed with 6 tests; `python -m mypy src\autoresearch` passed; `python -m ruff check src tests` passed; full `python -m pytest tests\smoke tests\unit -q` passed with 484 passed, 4 skipped, and 1 warning. Real paper rebuild `node .\bin\airesearcher.mjs paper-build runs\manual-live\task126-pendigits-live\runs\cycle-20260616T094744Z\paper-manuscript\manuscript.md --output-dir runs\manual-live\task126-paper-rerun-final\paper-build --template-id generic-article-one-column --vault runs\manual-live\task126-paper-rerun-final\vault --project-id task126_paper_rerun_final --timeout-seconds 180` passed, produced a 14-page PDF, and `rg` confirmed the final `compile.log` contains `RERUNS_COMPLETED: 1` plus `ATTEMPT 2` with no label/rerun/undefined/overfull/error matches._

- [x] 127. Always-on serve gate visibility
  - [x] 127.1 Show research-plan status in `serve` and verify approval gating
    - Share the research-plan status echo path between `autopilot` and `serve` so the always-on runtime makes the post-direction plan gate visible to operators.
    - Add unit coverage proving `serve --permission-mode allow-all --once` prints `[OK] research_plan: passed` when the cycle summary contains a passed plan audit.
    - Run a real `serve --once` cycle with live literature/model review and a real public benchmark to verify the serve entrypoint enters the same evidence-first loop as autopilot.
    - Run `serve --permission-mode approve-dangerous --once` and confirm it queues a pending approval request without creating run artifacts until approved.
    - Record any publication-quality blockers from the live serve run as follow-up issues instead of weakening the release gates.
    - _References: user requirement that one command can keep AI-Researcher running 24h with visible agent/gate flow, while dangerous actions require `/approve`-style human approval._
    - _Verify: `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; focused `python -m pytest tests\unit\cli\test_main.py::test_serve_allow_all_runs_without_approval_state tests\unit\cli\test_main.py::test_autopilot_command_runs_one_non_review_cycle tests\unit\cli\test_main.py::test_autopilot_research_plan_gate_blocks_before_experiment -q` passed with 3 tests; `python -m mypy src\autoresearch` passed; `python -m ruff check src tests` passed; full `python -m pytest tests\smoke tests\unit -q` passed with 484 passed, 4 skipped, and 1 warning. Real serve run `node .\bin\airesearcher.mjs serve --permission-mode allow-all --once --vault runs\manual-live\task127-serve-live\vault --cache runs\manual-live\task127-serve-live\cache --output-dir runs\manual-live\task127-serve-live\runs --deliverables-dir runs\manual-live\task127-serve-live\outputs --state runs\manual-live\task127-serve-live\scheduler-state.json --approvals-state runs\manual-live\task127-serve-live\approvals.json --project-id task127_serve_live --demo pendigits_variance_calibrated_prototypes --timeout-seconds 180 --paper-template-id generic-article-one-column` printed `[OK] research_plan: passed`, generated the PDF deliverable, and correctly blocked release because the live LLM review verdict was `needs_revision`; direct approval-gate smoke with `node .\bin\airesearcher.mjs serve --permission-mode approve-dangerous --once ...` printed `[WAITING] approval_required`, wrote only `approvals.json`, and a propagated exit-code check confirmed `LASTEXIT=2`._

- [x] 128. Review-driven manuscript claim repair
  - [x] 128.1 Repair reviewer-blocking manuscript evidence claims and rerun live serve
    - Remove unsupported related-work and similarity-positioning prose that overstated the retrieval process.
    - Add an explicit caveat that the recorded `variance_shrinkage=0.05` value is a fixed configuration, not an optimized hyperparameter or sensitivity result.
    - Rename the paper evidence table artifact from `Cycle record` to the real `Cycle summary` artifact.
    - Add `cycle-summary.json` to the LLM review evidence bundle so the reviewer can inspect the machine-readable cycle state directly.
    - Add focused tests for the manuscript wording and review evidence bundle.
    - Rerun a real `serve --once` cycle with live literature/model review and the public Pendigits benchmark, and require review, publication audit, evidence gate, and follow-up queues to pass.
    - _References: `P-20260616-070`; user requirement that release gates remain strict, outputs must not overclaim unsupported evidence, and the system should rerun real data/calls until the loop reaches a publication-quality gate._
    - _Verify: `python -m ruff check src\autoresearch\reports\manuscript.py src\autoresearch\cli\main.py tests\unit\reports\test_manuscript.py tests\unit\cli\test_main.py` passed; focused `python -m pytest tests\unit\reports\test_manuscript.py tests\unit\cli\test_main.py::test_autopilot_command_runs_one_non_review_cycle -q` passed with 2 tests; `python -m mypy src\autoresearch` passed; `python -m ruff check src tests` passed; full `python -m pytest tests\smoke tests\unit -q` passed with 484 passed, 4 skipped, and 1 warning. Real serve run `node .\bin\airesearcher.mjs serve --permission-mode allow-all --once --vault runs\manual-live\task128-serve-final\vault --cache runs\manual-live\task128-serve-final\cache --output-dir runs\manual-live\task128-serve-final\runs --deliverables-dir runs\manual-live\task128-serve-final\outputs --state runs\manual-live\task128-serve-final\scheduler-state.json --approvals-state runs\manual-live\task128-serve-final\approvals.json --project-id task128_serve_final --demo pendigits_variance_calibrated_prototypes --timeout-seconds 180 --paper-template-id generic-article-one-column` passed with `[OK] review_status: passed`, `[OK] publication_audit: pass`, `[OK] evidence_gate: pass`, and `[OK] followup_tasks: 0`; `pdfinfo` confirmed the exported paper PDF has 14 pages; `rg` confirmed the final manuscript uses `Cycle summary`, the LLM evidence includes `cycle-summary.json`, and paper-build `compile.log` contains `RERUNS_COMPLETED: 1` and `ATTEMPT 2`._

- [x] 129. Research-plan PDF layout hardening
  - [x] 129.1 Render long evidence locators as breakable TeX URL text
    - Investigate the research-plan PDF overfull warning found during task `128.1`.
    - Keep HTTP(S) references and long evidence artifact locators breakable in LaTeX without adding a new package dependency.
    - Add unit coverage proving long similarity/literature evidence references render through `\url{}` rather than escaped unbreakable text.
    - Rerun a real `research-plan --compile-pdf` smoke with long similarity and literature summary paths and confirm the compile log has no `Overfull` or LaTeX error markers.
    - _References: `P-20260617-071`; user requirement that generated PDFs be publication-quality and that layout problems be fixed rather than silently ignored._
    - _Verify: `python -m ruff check src\autoresearch\research\plans.py tests\unit\research\test_plans.py` passed; `python -m pytest tests\unit\research\test_plans.py -q` passed with 4 tests; real research-plan compile `node .\bin\airesearcher.mjs research-plan --candidate-file runs\manual-live\task128-serve-final\runs\cycle-20260617T150322Z\candidate.json --project-id task129_plan_layout --vault runs\manual-live\task129-plan-layout\vault --output-dir runs\manual-live\task129-plan-layout\outputs --similarity-summary runs\manual-live\task128-serve-final\vault\exploration\topics\similarity_check_autopilot_task128_serve_final_20260617150322.md --literature-summary runs\manual-live\task128-serve-final\vault\exploration\topics\literature_refresh_20260617.md --compile-pdf --timeout-seconds 180` passed with `compile_status: compiled` and 3 pages; `rg -n "Overfull|LaTeX Error|Undefined|undefined|Emergency stop|Fatal error" runs\manual-live\task129-plan-layout\outputs\task129_plan_layout\research-plan\research-plan.compile.log` returned no matches; `pdfinfo` confirmed the generated research-plan PDF is 3 pages A4; `python -m mypy src\autoresearch` passed; `python -m ruff check src tests` passed; full `python -m pytest tests\smoke tests\unit -q` passed with 485 passed, 4 skipped, and 1 warning._

- [x] 130. Verification dependency diagnostics
  - [x] 130.1 Surface Requests dependency warning source in `doctor`
    - Add a dependency diagnostic that uses package metadata instead of importing `requests`, so the check does not create the warning it is trying to explain.
    - Report the Requests, urllib3, charset-normalizer, and chardet set in `airesearcher doctor`.
    - Treat unsupported combinations as `[WARN]` rather than a failing doctor gate when the declared runtime dependencies are present; fail only if required declared packages are missing.
    - Keep the project Poetry environment separate from the host/global Python warning and document that boundary in `Problem.md`.
    - Add focused unit coverage for the locked Poetry set, the observed unsupported chardet set, and missing Requests.
    - _References: `P-20260612-057`; repeated verification warning that polluted local test output._
    - _Verify: `python -m ruff check src\autoresearch\observability\dependencies.py src\autoresearch\observability\__init__.py src\autoresearch\cli\main.py tests\unit\observability\test_dependencies.py tests\unit\cli\test_main.py` passed; `python -m mypy src\autoresearch\observability\dependencies.py src\autoresearch\cli\main.py` passed; `python -m pytest tests\unit\observability\test_dependencies.py tests\unit\cli\test_main.py::test_doctor_command_checks_local_scaffold -q` passed with 4 tests; `poetry run airesearcher doctor` reported `[OK] requests dependency set: requests 2.32.5, urllib3 2.7.0, charset-normalizer 3.4.7, chardet not installed`, while the host Python 3.13 still emitted the known external warning after command completion; `python -m ruff check src tests` passed; `python -m mypy src\autoresearch` passed; full `python -m pytest tests\smoke tests\unit -q` passed with 488 passed, 4 skipped, and 1 warning._

- [x] 131. Publication problem-log reconciliation
  - [x] 131.1 Close stale publication-readiness problem records using latest live evidence
    - Reconcile old open problem records that were created before the review-driven manuscript repair and final live serve pass.
    - Mark the positive Pendigits method-effect publication-readiness blocker as resolved only if a later live cycle has review, publication audit, evidence gate, and follow-up queues passing.
    - Mark the first negative shrinkage method candidate as resolved as an archived negative result rather than a still-open defect.
    - Mark the broad live full-loop publication-readiness problem as resolved by the latest publishable live serve cycle, while preserving future multi-dataset/venue work as follow-up rather than weakening the historical evidence.
    - Do not change runtime code or stale artifacts; this is a bookkeeping task to keep the self-loop issue substrate current.
    - _References: `P-20260613-004`, `P-20260613-014`, `P-20260613-016`, task `128.1` live pass._
    - _Verify: `rg` confirmed the task `128.1` cycle summary records `review.verdict=pass`, `publication_audit.verdict=pass`, `publication_audit.publishable=true`, `evidence_gate.verdict=pass`, `evidence_gate.release_allowed=true`, `followup_tasks=[]`, 65 literature documents, 57 similarity findings, 65 verified citations, a 14-page paper build, and a 3-page research plan; `Test-Path` confirmed the exported task `128.1` paper PDF exists; `rg` confirmed the task `76.1` negative shrinkage metrics and task `78.1` positive variance-calibrated metrics remain recorded._

- [x] 132. HKUDS AI-Researcher license boundary refresh
  - [x] 132.1 Re-check upstream license status and keep reference-only boundary executable
    - Re-check HKUDS AI-Researcher's current upstream repository, `setup.cfg`, GitHub license API, root file list, and license-clarification issue before changing the repository boundary.
    - Keep HKUDS AI-Researcher as conceptual/reference-only unless a top-level license file or written permission exists.
    - Update `THIRD_PARTY_NOTICES.md` with the current evidence instead of copying upstream code, prompts, assets, benchmark data, or generated examples.
    - Add a compliance test that fails if the reference-only boundary disappears from the third-party notice.
    - Update `P-20260613-006` to distinguish project-side mitigation from unresolved upstream license text.
    - _References: `P-20260613-006`; user request to understand differences from HKUDS AI-Researcher and whether it is open source._
    - _Verify: Live web/API review on 2026-06-17 found `setup.cfg` still declares `license = MIT`, GitHub license API returned 404, root contents did not list `LICENSE`, `LICENCE`, `COPYING`, or `NOTICE`, and issue #94 remains open; `python -m ruff check tests\unit\compliance\test_licenses.py` passed; `python -m pytest tests\unit\compliance\test_licenses.py -q` passed._

- [x] 133. Similar-work breadth problem reconciliation
  - [x] 133.1 Resolve stale classified-similar-work blocker using the latest real release evidence
    - Re-inspect the latest real release-allowed Pendigits cycle before changing any problem status.
    - Update `P-20260613-030` from task `95.1` history only if the current cycle proves the classified similar-work breadth target, publication audit, and evidence gate all pass.
    - Keep Semantic Scholar source reliability tracked separately in `P-20260613-003`; do not conflate optional source 429 mitigation with resolved novelty evidence.
    - Preserve the historical task `95.1` failure evidence while pointing future agents to the task `128.1` release pass.
    - _References: `P-20260613-030`; task `128.1` live serve pass; user requirement that the system cross-search similar work broadly and not fabricate publication novelty._
    - _Verify: PowerShell inspection of `runs\manual-live\task128-serve-final\runs\cycle-20260617T150322Z\cycle-summary.json` confirmed publication audit `verdict=pass`, `publishable=True`, `similarity_classified_finding_breadth` message `18; target requires at least 10`, evidence gate `verdict=pass`, and `release_allowed=True`; `rg -n "P-20260613-030|133\.1|similarity_classified_finding_breadth|P-20260613-003" Problem.md .kiro\specs\auto-research-system\tasks.md` passed._

- [x] 134. Release-gate problem reconciliation
  - [x] 134.1 Resolve stale always-on release-gate mitigations using final serve evidence
    - Re-inspect the final task `128.1` live serve cycle before changing old release-gate problem statuses.
    - Update `P-20260613-011` only if the automatic `serve`/`autopilot` path contains paper-build and evidence-gate outputs without manual chaining.
    - Update `P-20260613-012` only if the current release gate records a fresh command-line reproduction rerun with run-record and validation artifacts.
    - Update `P-20260613-013` only if the publication audit blocks baseline-only releases and the latest non-baseline release path passes method innovation and method-effect checks.
    - Preserve historical blocked/mitigated evidence so future agents can see why the release gates exist.
    - _References: `P-20260613-011`, `P-20260613-012`, `P-20260613-013`; user requirement that the system really executes scripts, reruns experiments, and does not rely on AI self-reporting or baseline-only paper packaging._
    - _Verify: PowerShell inspection of `runs\manual-live\task128-serve-final\runs\cycle-20260617T150322Z\cycle-summary.json` confirmed publication audit `verdict=pass`, `publishable=True`, evidence gate `verdict=pass`, `release_allowed=True`, `method_innovation_evidence=pass`, `method_effect_evidence=pass`, `reproduction_rerun_gate=pass`, `publication_release_gate=pass`, `paper_pdf_gate=pass`, and `paper_quality_gate=pass`; `rg -n "P-20260613-011|P-20260613-012|P-20260613-013|134\.1|reproduction_rerun_gate|method_effect_evidence|paper_quality_gate" Problem.md .kiro\specs\auto-research-system\tasks.md` passed._

- [x] 135. Prompt-only release discipline reconciliation
  - [x] 135.1 Resolve stale SCALE-lite release-gate problem using lifecycle trace evidence
    - Re-inspect the final task `128.1` evidence gate before changing `P-20260613-008`.
    - Resolve only the release-claim part of the prompt-only governance risk; keep concurrent edit coordination tracked separately in `P-20260613-009`.
    - Confirm the evidence gate has `release_allowed=true`, no failed checks, and a full lifecycle trace for define, plan, build, verify, review, and ship.
    - Preserve the earlier blocked `serve-paper-structure` evidence that motivated the physical gate.
    - _References: `P-20260613-008`, `P-20260613-009`; user request to borrow SCALE Engine's physical evidence/review gate idea without adopting the whole heavyweight lifecycle._
    - _Verify: PowerShell inspection of `runs\manual-live\task128-serve-final\runs\cycle-20260617T150322Z\cycle-summary.json` confirmed evidence gate `verdict=pass`, `release_allowed=True`, `failed_check_count=0`, and lifecycle stages `define`, `plan`, `build`, `verify`, `review`, and `ship` all `pass`; `rg -n "P-20260613-008|P-20260613-009|135\.1|lifecycle trace|release_allowed" Problem.md .kiro\specs\auto-research-system\tasks.md` passed._

- [x] 136. Runtime session gate automation
  - [x] 136.1 Automatically claim runtime write scopes for `autopilot` and `serve`
    - Add automatic agent-session claiming to the long-running runtime entrypoints before any approval queue, online retrieval, experiment execution, vault write, or deliverable export can start.
    - Claim the vault, cache, run output, deliverables output, scheduler state, and runtime approval state paths for the current project, and fail closed when another active session overlaps any claimed scope.
    - Release the runtime session on normal completion, queued approval exit, or cycle failure so a failed run does not leave stale active state.
    - Keep a `--sessions-state` override for operators while defaulting the session state next to the scheduler or approval state when those paths are custom.
    - Add focused CLI tests for automatic claim/release, approval-queue release, allow-all release, and conflict-before-cycle behavior.
    - _References: `P-20260613-009`; user request to make multi-agent traffic control a physical gate rather than relying on prompt discipline._
    - _Verify: `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; focused `python -m pytest tests\unit\cli\test_main.py::test_autopilot_command_runs_one_non_review_cycle tests\unit\cli\test_main.py::test_serve_queues_dangerous_action_until_runtime_approval tests\unit\cli\test_main.py::test_serve_allow_all_runs_without_approval_state tests\unit\cli\test_main.py::test_serve_blocks_overlapping_runtime_session_before_cycle -q` passed with 4 tests; `python -m mypy src\autoresearch` passed; full `python -m pytest tests\unit\cli\test_main.py -q` passed with 56 tests; real CLI smoke `node .\bin\airesearcher.mjs sessions claim --state runs\manual-live\task136-runtime-session-gate\agent-sessions.json --session-id task136_active ...` allowed the first claim, real `node .\bin\airesearcher.mjs serve --permission-mode allow-all --once --sessions-state runs\manual-live\task136-runtime-session-gate\agent-sessions.json ...` exited `1` with `[OK] session_claim: blocked` and `[CONFLICT] session_id=task136_active` before any cycle started, real `node .\bin\airesearcher.mjs sessions release task136_active ...` released the session, and `node .\bin\airesearcher.mjs sessions list --include-released ...` showed only `status=released`; `python -m ruff check src tests` passed; full `python -m pytest tests\smoke tests\unit -q` passed with 490 passed, 4 skipped, and 1 known external warning._

- [x] 137. Optional Semantic Scholar default-source reconciliation
  - [x] 137.1 Resolve stale Semantic Scholar 429 default-source risk using live default-source evidence
    - Re-check the current implementation before changing `P-20260613-003`.
    - Confirm the default automatic discovery clients are ArXiv and OpenAlex, and Semantic Scholar is included only when `AUTORESEARCH_ENABLE_SEMANTIC_SCHOLAR=1` or `SEMANTIC_SCHOLAR_API_KEY` is set.
    - Confirm README guidance already describes Semantic Scholar as optional and lower priority.
    - Run a real default `literature-refresh` smoke with bounded query/result counts and verify the fetch list contains ArXiv and OpenAlex only.
    - Preserve Semantic Scholar 429 as an optional enhancement-source reliability caveat, not as a default release blocker when core free/public source breadth passes.
    - _References: `P-20260613-003`; user request to prefer free APIs first and demote Semantic Scholar because 429s are common._
    - _Verify: `rg -n "Semantic Scholar|semantic_scholar|AUTORESEARCH_ENABLE_SEMANTIC|core free" src tests .kiro\specs\auto-research-system\tasks.md README.md README.zh-CN.md` confirmed code, tests, tasks, and READMEs describe Semantic Scholar as optional; real CLI `node .\bin\airesearcher.mjs literature-refresh --vault runs\manual-live\task137-default-sources\vault --cache runs\manual-live\task137-default-sources\cache --max-queries 1 --max-results-per-source 1` printed only `[FETCH] source=arxiv` and `[FETCH] source=openalex`, wrote 2 documents, and wrote `runs\manual-live\task137-default-sources\vault\exploration\topics\literature_refresh_20260617.md` with ArXiv/OpenAlex provenance._

- [x] 138. CI polling environment reconciliation
  - [x] 138.1 Resolve stale missing-`gh` local environment problem
    - Re-check whether GitHub CLI is now installed and visible in the active PowerShell session.
    - Run a real GitHub Actions list query for the project repository instead of relying on version output only.
    - Update `P-20260613-033` only if both the executable and a real `gh run list` query work.
    - _References: `P-20260613-033`; previous CI polling fallback because `gh` was missing locally._
    - _Verify: `gh --version` printed `gh version 2.93.0 (2026-05-27)`; real `gh run list --repo neutronstar238/ai-researcher --limit 1 --json databaseId,status,conclusion,workflowName,url,createdAt` returned CI run `27544632808` with `status=completed` and `conclusion=success`._

- [x] 139. Code-agent trust-boundary reconciliation
  - [x] 139.1 Resolve stale cc-switch validation-boundary risk using OpenCode/cc-switch contract evidence
    - Re-check the current OpenCode direct backend contract and the optional cc-switch bridge contract before changing `P-20260613-007`.
    - Confirm OpenCode is the preferred direct external code-writing backend, while cc-switch remains an optional Claude Code provider-routing bridge only when explicitly required.
    - Confirm both CLI list commands expose `validator=AI-Researcher`, and tests keep generated code-agent diffs as proposals until AI-Researcher gates pass.
    - Preserve the no-vendoring, no-secret, approval-gated execution boundary in third-party notices and manifests.
    - _References: `P-20260613-007`; user decision to move from cc-switch/Claude Code compatibility concerns to direct OpenCode while keeping AI-Researcher as code acceptance owner._
    - _Verify: real `node .\bin\airesearcher.mjs code-agents opencode list` printed backend `opencode-direct` with `validator=AI-Researcher`; real `node .\bin\airesearcher.mjs code-agents cc-switch list` printed backend `claude-code-via-cc-switch` with `validator=AI-Researcher`; `python -m pytest tests\unit\integrations\test_opencode.py tests\unit\integrations\test_cc_switch.py -q` passed with 9 tests._

- [x] 140. Publication figure readability hardening
  - [x] 140.1 Render source-backed metric figures with readable labels
    - Treat the final PDF visual QA issue as a release-facing quality defect: generated metric figures must not expose truncated raw metric keys as tiny axis labels.
    - Render metric figures as horizontal source-backed bar charts with human-readable labels while preserving raw metric keys and values in metadata.
    - Keep the figure lightweight and deterministic so CI does not require a plotting dependency.
    - Add focused tests proving long metric keys are mapped to readable labels and are not emitted as truncated raw labels inside the generated figure PDF.
    - Re-run a real autonomous Pendigits cycle and visually inspect the generated paper PDF pages for figure readability, references, tables, page count, and overfull boxes.
    - _References: `P-20260617-072`; user PDF QA feedback that paper artifacts need readable citations, figures, and data analysis instead of text-only or malformed output._
    - _Verify: `python -m ruff check src\autoresearch\reports\figures.py tests\unit\reports\test_figures.py` passed; `python -m pytest tests\unit\reports\test_figures.py -q` passed with 3 tests; `python -m mypy src\autoresearch` passed; real `node .\bin\airesearcher.mjs autopilot --project-id live_release_candidate_20260617_v2 --demo pendigits_variance_calibrated_prototypes --timeout-seconds 120 --paper-template-id generic-article-one-column` passed source preflight, research plan, live LLM review, publication audit, evidence gate, and deliverable export; `pdfinfo` confirmed the release PDF has 14 pages; paper-build JSON recorded `figure_count=1`, `table_count=2`, `overfull_hbox_count=0`, `page_count=14`, and `paper_quality.passed=true`; visual PDF rendering confirmed the metric figure uses readable horizontal labels and the references/tables do not overflow; `pdftotext` confirmed numeric references and no old operational reference labels; `rg -n "Overfull|LaTeX Error|Undefined|undefined|Emergency stop|Fatal error"` over paper and research-plan compile logs returned no matches; `python -m ruff check src tests` passed; `python -m pytest tests\smoke tests\unit -q` passed with 491 passed, 4 skipped, and 1 warning._

- [x] 141. Deterministic figure readability release gate
  - [x] 141.1 Block paper-quality pass when metric figure metadata exposes unreadable labels
    - Promote the task `140.1` visual QA lesson into `paper_build` so future release PDFs cannot pass solely because a human happened not to inspect the figure page.
    - Read adjacent source-backed figure metadata sidecars for Markdown image references.
    - For `metric_bar` figures, fail `paper_quality` with `figure_label_readability` when long machine metric names lack a readable label, reuse raw snake-case labels, or use non-horizontal layout for long metric names.
    - Preserve compatibility with external/non-metric figures by applying the strict label check only when `figure_type=metric_bar` metadata is present.
    - Write issue counts and messages into `paper-build.json` and `paper-build.md` so the Obsidian paper-build note and release manifest expose the reason.
    - _References: `P-20260618-073`, `P-20260618-074`; user requirement that PDF visual quality be physically gated rather than trusted to prompt self-discipline or one-off manual screenshots._
    - _Verify: `python -m ruff check src\autoresearch\reports\paper_build.py tests\unit\reports\test_paper_build.py tests\unit\reports\test_manuscript.py` passed; `python -m pytest tests\unit\reports\test_paper_build.py tests\unit\reports\test_manuscript.py -q` passed with 8 tests; `python -m mypy src\autoresearch` passed; `python -m ruff check src tests` passed; `python -m pytest tests\smoke tests\unit -q` passed with 492 passed, 4 skipped, and 1 warning. A real paper rebuild over `runs\autopilot\cycle-20260617T160833Z\paper-manuscript\manuscript.md` with `node .\bin\airesearcher.mjs paper-build ... --timeout-seconds 180` compiled a 14-page PDF, recorded `figure_readability_issue_count=0`, `paper_quality.passed=true`, `failures=[]`, and `overfull_hbox_count=0`; visual rendering of page 8 confirmed the metric figure labels remain readable._

- [x] 142. Operator console release-flow hardening
  - [x] 142.1 Render release-critical cycle stages and artifact previews in `monitor`
    - Treat the long-running CLI monitor as the product operator console for the autonomous research loop.
    - Replace the previous summary-only information-flow table with stage rows for source preflight, literature refresh, research plan, novelty/similarity check, related-work inspection, citation package, experiment, reproduction check, LLM review, publication audit, paper build, evidence gate, follow-ups, and deliverables.
    - Pull concise status details from real cycle-summary fields, including document/source counts, research-plan compile/audit/page status, related-work inspected/direct counts, citation blocked count, paper quality/page status, follow-up queue count, and deliverable count.
    - Bind each stage to specific artifact evidence paths instead of pointing every row to `cycle-summary.json`.
    - Keep the terminal UI readable in narrow Rich panels by using short stage labels, folding table text instead of Unicode ellipsis truncation, and shortening preview/evidence paths with ASCII `...`.
    - Extend CLI tests with a release-like cycle summary fixture and structured assertions for citation metadata, deliverable manifest/PDF paths, and paper-quality status.
    - _References: `P-20260618-075`, `P-20260618-076`; user request for a good CLI showing Agent messages, information flow, changes, previews, and release-quality evidence rather than hidden JSON._
    - _Verify: `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; focused `python -m pytest tests\unit\cli\test_main.py::test_monitor_renders_agent_flow_changes_and_preview -q` passed; real `node .\bin\airesearcher.mjs monitor --cycle-summary runs\autopilot\cycle-20260617T160833Z\cycle-summary.json --outputs-dir outputs\live_release_candidate_20260617_v2 --no-diff --max-agent-entries 1` rendered source, literature, plan, novelty, related work, citations, experiment, reproduction, review, publication, paper, evidence, follow-ups, and deliverables without Unicode truncation artifacts; structured `_cycle_stage_rows` over the same real summary showed `paper` status `compiled; quality=pass; pages=14`, `citations` evidence including `references.metadata.json`, and `deliverables` evidence including the manifest and PDF paths; `python -m mypy src\autoresearch` passed; `python -m ruff check src tests` passed; full `python -m pytest tests\unit\cli\test_main.py -q` passed with 56 tests; full `python -m pytest tests\smoke tests\unit -q` passed with 492 passed, 4 skipped, and 1 warning._

- [x] 143. README operator console release-alignment
  - [x] 143.1 Refresh monitor documentation and screenshot asset
    - Treat the README operator-console image as release-facing product evidence, not as a decorative placeholder.
    - Update English and Chinese monitor documentation to describe the release-critical stage table added by `142.1`.
    - Refresh `docs/assets/readme/cli-monitor.svg` so the visible console preview names release gates, stage evidence paths, paper-quality status, and output previews instead of stale task `119.1` examples.
    - Keep the asset lightweight, repository-native, and directly referenced by both README files.
    - _References: `P-20260618-077`; user request for a visible, polished CLI that shows Agent messages, information flow, changes, previews, and release-quality evidence._
    - _Verify: `python -c "import xml.etree.ElementTree as ET; ET.parse('docs/assets/readme/cli-monitor.svg'); print('svg ok')"` passed; `python -c "... readme monitor checks ok ..."` passed for README and SVG key terms; `python -c "... asset link ok ..."` passed for the README screenshot link; `git diff --check -- README.md README.zh-CN.md docs\assets\readme\cli-monitor.svg` passed._

- [x] 144. Host requests warning boundary re-audit
  - [x] 144.1 Reconfirm project dependency health without mutating host Python
    - Reproduce the current `RequestsDependencyWarning` behavior in the active local shell.
    - Confirm whether the warning is emitted by project code, the project Poetry virtual environment, the npm wrapper, or the host/global Python environment.
    - Preserve the existing non-mutating boundary: do not change global site-packages and do not hide a real project dependency failure.
    - Update `P-20260612-057` with current evidence and the recommended command boundary for future agents.
    - _References: `P-20260612-057`; user request to keep verification output clean without pretending local-only smoke tests are live external checks._
    - _Verify: `python -m pytest tests\smoke tests\unit -q` passed with 492 passed, 4 skipped, 1 LangGraph warning, and then reproduced the host Python 3.13 `RequestsDependencyWarning`; `python -m ruff check src tests` and `python -m mypy src\autoresearch` passed without the requests warning; `poetry run airesearcher doctor` reported the project Poetry set as `[OK] requests 2.32.5, urllib3 2.7.0, charset-normalizer 3.4.7, chardet not installed` but Poetry still emitted the host Python 3.13 warning after exit; `node .\bin\airesearcher.mjs doctor` reported the host set as `[WARN] requests 2.31.0, urllib3 2.7.0, charset-normalizer 3.4.7, chardet 7.4.3` without importing requests or emitting `RequestsDependencyWarning`; no dependency or code change was made._

- [x] 145. HKUDS AI-Researcher license boundary freshness
  - [x] 145.1 Refresh upstream license evidence and compliance guard
    - Re-check the current HKUDS AI-Researcher repository metadata, GitHub license API, root contents, `setup.cfg`, and issue #94 before changing the boundary.
    - Keep the project as conceptual/reference-only unless GitHub exposes a top-level license file or upstream grants written permission.
    - Update `THIRD_PARTY_NOTICES.md` with the latest reviewed date and `licenseInfo=null` evidence.
    - Extend the compliance regression test so the ambiguous-license boundary remains executable.
    - _References: `P-20260613-006`; user request to understand the difference from HKUDS AI-Researcher and verify whether it is open source._
    - _Verify: Live web/API review on 2026-06-18 found repository metadata `licenseInfo=null`, GitHub license API returned 404, root contents listed no `LICENSE`, `LICENCE`, `COPYING`, or `NOTICE`, `setup.cfg` still declares `license = MIT`, and issue #94 is still `OPEN`; `python -m ruff check tests\unit\compliance\test_licenses.py` passed; `python -m pytest tests\unit\compliance\test_licenses.py -q` passed with 6 tests and then emitted the known host Python `RequestsDependencyWarning` tracked in `P-20260612-057`._

- [x] 146. Spambase weak-effect release quarantine audit
  - [x] 146.1 Confirm weak Spambase evidence is excluded from stable release claims
    - Re-check the original Spambase weak-effect record and the later passing CCF-B/Q3 stability matrices.
    - Confirm Spambase remains useful as a real benchmark execution path but does not contribute to release-allowed stability evidence while its effect is below the method-effect standard-error gate.
    - Update `P-20260613-042` so future agents do not treat the mitigated weak result as an unresolved publication blocker or as positive publication evidence.
    - _References: `P-20260613-042`; tasks `107.1`, `109.1`, `114.1`, `115.1`, `116.1`; user requirement that data must prove claims and weak effects must not be promoted into publication claims._
    - _Verify: Parsed passing `publication-stability.json` reports and confirmed the current stable matrices use release-allowed Pendigits, Letter Recognition, and Skin Segmentation cycles; `runs\manual-live\task116-related-work-current-matrix\publication-stability.json` reports `stable=true` and `score=1.0` with datasets Pen-Based Recognition of Handwritten Digits, Letter Recognition, and Skin Segmentation; no passing stable matrix relies on Spambase. `git diff --check` passed for the task documentation files._

- [x] 147. Executor network preflight gate
  - [x] 147.1 Block unapproved network imports before local subprocess execution
    - Reuse the generated-code review findings for `unrestricted_network` imports inside the local experiment executor.
    - Fail closed before starting the subprocess when generated experiment code imports `requests`, `httpx`, `aiohttp`, `socket`, or `urllib` without explicit task metadata approval.
    - Preserve a narrow escape hatch for approved work through `task.metadata["network_access_approved"]=True`, so future `/approve`-style permission flow can set the same key instead of bypassing the executor.
    - Mark trusted built-in UCI public benchmark demos with scoped network approval metadata, approved domains, source URLs, and cache-first scope text so their cached-data tests and public-data fallback remain explicit.
    - Record the preflight finding details in `ExecutionRun.metadata["network_preflight"]` and return `NetworkPreflightDenied` with `network_preflight` in `limit_violations` when blocked.
    - Keep `P-20260611-014` mitigated rather than resolved because this is an executor gate, not OS/container/proxy-level network interception.
    - _References: `P-20260611-014`; tasks `8.3`, `9.2`, `9.3`; user requirement for permission modes and dangerous-command approval instead of prompt-only self-discipline._
    - _Verify: `python -m ruff check src\autoresearch\experiments\executor.py tests\unit\experiments\test_executor.py` passed; `python -m pytest tests\unit\experiments\test_executor.py -q` passed with 6 tests and then emitted the known host Python `RequestsDependencyWarning` tracked in `P-20260612-057`; `python -m pytest tests\unit\experiments\test_executor.py tests\unit\experiments\test_review.py tests\unit\experiments\test_network.py -q` passed with 22 tests and the same known host warning; the first full smoke/unit run exposed `P-20260618-078`, then `python -m pytest tests\unit\experiments\test_demos.py tests\unit\experiments\test_executor.py -q` passed with 22 tests after the scoped UCI metadata fix; `python -m ruff check src tests`, `python -m mypy src\autoresearch`, `git diff --check`, and `python -m pytest tests\smoke tests\unit -q` passed with 494 passed, 4 skipped, 1 LangGraph warning, and the known host Python `RequestsDependencyWarning` after pytest exit._

- [x] 148. Network approval audit metadata
  - [x] 148.1 Preserve scoped network approval details in execution records
    - Copy scoped approval metadata from `ExperimentTask.metadata` into `ExecutionRun.metadata["network_preflight"]` whenever the executor sees network-import findings.
    - Preserve `network_access_scope`, `approved_network_domains`, `network_source_urls`, `network_approval_id`, and `network_approved_by` so approval can be audited after the run.
    - Add regression coverage that approved network imports retain scope/domain/source metadata in the execution record.
    - Add regression coverage that built-in UCI public benchmark tasks define cache-first scoped network approval metadata.
    - _References: task `147.1`; `P-20260611-014`; user requirement for approval-based dangerous operation gates and auditable evidence._
    - _Verify: `python -m ruff check src\autoresearch\experiments\executor.py tests\unit\experiments\test_executor.py tests\unit\experiments\test_demos.py` passed; `python -m pytest tests\unit\experiments\test_executor.py tests\unit\experiments\test_demos.py -q` passed with 23 tests and then emitted the known host Python `RequestsDependencyWarning` tracked in `P-20260612-057`; `python -m mypy src\autoresearch\experiments\executor.py` passed; `python -m ruff check src tests`, `python -m mypy src\autoresearch`, `git diff --check`, and `python -m pytest tests\smoke tests\unit -q` passed with 495 passed, 4 skipped, 1 LangGraph warning, and the known host Python `RequestsDependencyWarning` after pytest exit._

- [x] 149. Runtime approval bridge for network metadata
  - [x] 149.1 Convert approved runtime decisions into network task metadata
    - Add a runtime helper that converts an allowed `RuntimeApprovalDecision` into the exact task metadata keys consumed by the executor network preflight gate.
    - Require the decision to be allowed; pending or rejected dangerous work must not produce `network_access_approved=True`.
    - Preserve approval mode, approval request ID, approving operator, scope, approved domains, and source URLs in the generated metadata.
    - Export the helper from `autoresearch.runtime` for future CLI, WeChat, and Feishu approval adapters.
    - Extend executor metadata passthrough so `network_approval_mode` is retained in `ExecutionRun.metadata["network_preflight"]`.
    - _References: tasks `60.1`, `147.1`, `148.1`; user requirement that `/approve` and communication-channel approvals map to the same permissioned local runtime._
    - _Verify: `python -m ruff check src\autoresearch\runtime\approval.py src\autoresearch\runtime\__init__.py src\autoresearch\experiments\executor.py tests\unit\runtime\test_runtime_approval.py tests\unit\experiments\test_executor.py` passed; `python -m pytest tests\unit\runtime\test_runtime_approval.py tests\unit\experiments\test_executor.py -q` passed with 10 tests and then emitted the known host Python `RequestsDependencyWarning` tracked in `P-20260612-057`; `python -m mypy src\autoresearch\runtime\approval.py src\autoresearch\experiments\executor.py` passed; `python -m ruff check src tests`, `python -m mypy src\autoresearch`, `git diff --check`, and `python -m pytest tests\smoke tests\unit -q` passed with 497 passed, 4 skipped, 1 LangGraph warning, and the known host Python `RequestsDependencyWarning` after pytest exit._

- [x] 150. Serve-to-executor network approval propagation
  - [x] 150.1 Pass approved runtime network metadata into autonomous demo tasks
    - Convert the already-allowed `serve` runtime decision into auditable network metadata before each autonomous cycle starts.
    - Pass the metadata through `_run_autopilot_cycle()` into `run_scientistbench_demo()` so generated `ExperimentTask` records and run records retain the approval mode, request ID, approving operator, scope, domains, and source URLs.
    - Keep normal `airesearcher autopilot` and `airesearcher run-demo` behavior local by default; only the runtime-gated `serve` path injects the approval context.
    - Merge runtime approval domains and source URLs with task-scoped public dataset metadata without overwriting the narrower UCI benchmark provenance.
    - _References: tasks `147.1`, `148.1`, `149.1`; user requirement that always-on server/WeChat/Feishu approvals flow into actual execution gates, not just prompts._
    - _Verify: `python -m ruff check src\autoresearch\cli\main.py src\autoresearch\experiments\demo_workflow.py tests\unit\cli\test_main.py tests\unit\experiments\test_demos.py` passed; `python -m mypy src\autoresearch\cli\main.py src\autoresearch\experiments\demo_workflow.py` passed; corrected focused pytest selectors passed with 5 tests; `python -m pytest tests\unit\cli\test_main.py tests\unit\experiments\test_demos.py -q` passed with 75 tests and the known host Python `RequestsDependencyWarning`; `python -m ruff check src tests`, `python -m mypy src\autoresearch`, `git diff --check`, and `python -m pytest tests\smoke tests\unit -q` passed with 499 passed, 4 skipped, 1 LangGraph warning, and the known host Python `RequestsDependencyWarning` after pytest exit._

- [x] 151. Cycle-summary network approval audit visibility
  - [x] 151.1 Promote demo network approval metadata into cycle summaries and review context
    - Read the generated demo `run-record.json` after the experiment stage and extract only auditable network approval fields.
    - Add `demo.network_approval` to `cycle-summary.json` only when approval or network preflight metadata exists.
    - Preserve direct tabular `airesearcher autopilot` output without a noisy network approval section.
    - Include the same approval fields in the candidate review evidence summary so LLM and deterministic reviewers can see the execution permission boundary.
    - Avoid copying raw preflight finding bodies into the summary; keep them in the detailed run record.
    - _References: tasks `148.1`, `149.1`, `150.1`; user requirement that approvals and execution evidence are visible rather than hidden behind prompt self-discipline._
    - _Verify: `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; `python -m mypy src\autoresearch\cli\main.py` passed; `python -m pytest tests\unit\cli\test_main.py::test_autopilot_command_runs_one_non_review_cycle tests\unit\cli\test_main.py::test_autopilot_demo_network_summary_promotes_approval_audit_fields -q` passed with 2 tests and the known host Python `RequestsDependencyWarning`; `python -m ruff check src tests`, `python -m mypy src\autoresearch`, `git diff --check`, and `python -m pytest tests\smoke tests\unit -q` passed with 500 passed, 4 skipped, 1 LangGraph warning, and the known host Python `RequestsDependencyWarning` after pytest exit._

- [x] 152. Operator monitor network approval visibility
  - [x] 152.1 Surface experiment network approval status in the Rich monitor
    - Extend the monitor experiment row status to summarize `demo.network_approval`.
    - Show approval mode, shortened approval ID, approved domain count, preflight pass/blocked state, and finding count when present.
    - Keep the monitor compact and leave raw preflight finding bodies in the detailed run record.
    - Update the monitor fixture to prove approval/preflight details appear in the operator console and structured stage rows.
    - _References: task `151.1`; user requirement for a visible CLI UI showing agent flow, changed content, and approval-gated execution state._
    - _Verify: `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; `python -m mypy src\autoresearch\cli\main.py` passed; the first focused pytest selector used a stale monitor test name and collected no tests, then `python -m pytest tests\unit\cli\test_main.py::test_monitor_renders_agent_flow_changes_and_preview -q` passed with 1 test and the known host Python `RequestsDependencyWarning`; `python -m ruff check src tests`, `python -m mypy src\autoresearch`, `git diff --check`, and `python -m pytest tests\smoke tests\unit -q` passed with 500 passed, 4 skipped, 1 LangGraph warning, and the known host Python `RequestsDependencyWarning` after pytest exit._

- [x] 153. WeChat QR setup status evidence
  - [x] 153.1 Record and surface WeChat QR setup status from guided deployment
    - Add a setup-owned status artifact for WeChat QR onboarding at `.airesearcher/channels/wechat/setup-status.json`.
    - Make the QR runner print an explicit waiting message before the upstream adapter displays the QR code and waits for scan/login.
    - Record command, session path, timestamps, return code, and completion/failure status without storing secrets.
    - Add `AUTORESEARCH_WECHAT_SETUP_STATUS_PATH` to setup output and `.env.example`.
    - Make inspiration push skips for QR-mode WeChat include the setup-status state so operators can distinguish missing setup, running setup, and completed setup from real delivery.
    - Update README onboarding notes to point users to the status artifact.
    - _References: task `120.1`; user correction that WeChat QR setup should happen during setup and wait for scan feedback, not as a hidden later command._
    - _Verify: `python -m ruff check src\autoresearch\cli\main.py src\autoresearch\notifications.py tests\unit\cli\test_main.py tests\unit\test_notifications.py` passed; `python -m mypy src\autoresearch\cli\main.py src\autoresearch\notifications.py` passed; `python -m pytest tests\unit\cli\test_main.py::test_deploy_setup_runs_wechat_qr_setup_with_status_artifact tests\unit\cli\test_main.py::test_setup_guided_wechat_qr_runs_qr_setup tests\unit\test_notifications.py::test_send_inspiration_digest_reports_wechat_qr_gateway_without_webhook -q` passed with 3 tests and the known host Python `RequestsDependencyWarning`; `python -m pytest tests\unit\cli\test_main.py tests\unit\test_notifications.py -q` passed with 64 tests and the known host Python `RequestsDependencyWarning`; `python -m ruff check src tests`, `python -m mypy src\autoresearch`, `git diff --check`, and `python -m pytest tests\smoke tests\unit -q` passed with 501 passed, 4 skipped, 1 LangGraph warning, and the known host Python `RequestsDependencyWarning` after pytest exit._

- [x] 154. Operator channel self-test command
  - [x] 154.1 Add a setup-channel self-test command and slash template
    - Add `airesearcher channels test` so operators can verify WeChat/Feishu delivery after setup without waiting for a full research cycle.
    - Use the same `send_inspiration_digest()` path as inspiration pushes so the self-test does not drift from runtime delivery behavior.
    - Load setup-written `.env`, support repeated `--channel`, write a JSON result artifact, and print each `sent`, `failed`, or `skipped` record.
    - Add `--require-sent` so deployment scripts can fail when any selected channel is not actually sent.
    - Add `/research:channel-test` slash-command template and README guidance in English and Chinese.
    - _References: tasks `119.1`, `120.1`, and `153.1`; user requirement that setup-configured WeChat/Feishu channels should be operationally verifiable before 24h unattended runs._
    - _Verify: Initial focused ruff found unused fake-sender arguments and was fixed under `P-20260618-080`; `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed after the fix; `python -m mypy src\autoresearch\cli\main.py` passed; `python -m pytest tests\unit\cli\test_main.py::test_channels_test_command_sends_probe_and_writes_result tests\unit\cli\test_main.py::test_channels_test_requires_sent_when_requested tests\unit\cli\test_main.py::test_slash_commands_init_and_list_project_templates -q` passed with 3 tests and the known host Python `RequestsDependencyWarning`; `python -m pytest tests\unit\cli\test_main.py tests\unit\test_notifications.py -q` passed with 66 tests and the known host Python `RequestsDependencyWarning`; `python -m ruff check src tests`, `python -m mypy src\autoresearch`, `git diff --check`, and `python -m pytest tests\smoke tests\unit -q` passed with 503 passed, 4 skipped, 1 LangGraph warning, and the known host Python `RequestsDependencyWarning` after pytest exit. GitHub Actions run `27709729783` then failed on Python 3.10/Linux because the test read `result.stderr` when Click/Typer mixed stderr into `result.output`; fixed under `P-20260618-081`; after the fix, `python -m pytest tests\unit\cli\test_main.py::test_channels_test_requires_sent_when_requested -q`, `python -m ruff check src tests`, `python -m mypy src\autoresearch`, `git diff --check`, and `python -m pytest tests\smoke tests\unit -q` passed locally, and GitHub Actions run `27710036107` passed._

- [x] 155. Deployment readiness preflight
  - [x] 155.1 Add a readiness command for unattended daily operation
    - Add `airesearcher readiness` to write a JSON preflight report before starting a 24h loop.
    - Check `.env`, provider-agnostic LLM values, setup config, Obsidian vault path, writable `outputs/`, planned daily interval, optional scheduler state, and WeChat/Feishu channel configuration.
    - Support `--push-inspiration` and `--require-channel-config` so operators can fail fast when push delivery is required but no configured channel is ready.
    - Add `/research:readiness` slash-command template plus English and Chinese README guidance.
    - _References: tasks `119.1`, `120.1`, `153.1`, and `154.1`; user requirement that the system verify daily scheduled retrieval and inspiration push readiness before V1.0-style 24h operation._
    - _Verify: `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; `python -m mypy src\autoresearch\cli\main.py` passed; `python -m pytest tests\unit\cli\test_main.py::test_readiness_command_writes_daily_loop_report tests\unit\cli\test_main.py::test_readiness_requires_channel_config_for_push tests\unit\cli\test_main.py::test_slash_commands_init_and_list_project_templates -q` passed with 3 tests and the known host Python `RequestsDependencyWarning`; direct `python -m autoresearch.cli.main readiness --allow-missing-channel` failed because the package is not installed in the active interpreter and was recorded under `P-20260618-082`; `poetry run airesearcher readiness --allow-missing-channel` passed, wrote `.airesearcher/readiness/report.json`, and reported current local model/config/vault/outputs/daily-loop checks as ready with one operator-channel warning because no WeChat/Feishu delivery channel is configured; `python -m ruff check src tests`, `python -m mypy src\autoresearch`, `git diff --check`, and `python -m pytest tests\smoke tests\unit -q` passed with 505 passed, 4 skipped, 1 LangGraph warning, and the known host Python `RequestsDependencyWarning` after pytest exit; GitHub Actions run `27710878005` passed._

- [x] 156. Channel delivery evidence readiness gate
  - [x] 156.1 Require recent channel self-test evidence when push delivery matters
    - Extend `airesearcher readiness` with `--channel-test-result` and `--require-channel-sent`.
    - Read the JSON artifact produced by `airesearcher channels test` and add a separate `channel_delivery_test` check.
    - Fail readiness when `--require-channel-sent` is set and no selected channel has a `sent` record in the latest self-test artifact.
    - Update `/research:readiness` and bilingual README guidance so operators know that configuration alone is not enough for push-readiness.
    - _References: tasks `154.1` and `155.1`; user requirement that prelaunch checks verify actual push/delivery evidence, not just assumed configuration._
    - _Verify: `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; `python -m mypy src\autoresearch\cli\main.py` passed; `python -m pytest tests\unit\cli\test_main.py::test_readiness_command_writes_daily_loop_report tests\unit\cli\test_main.py::test_readiness_requires_sent_channel_self_test tests\unit\cli\test_main.py::test_readiness_requires_channel_config_for_push tests\unit\cli\test_main.py::test_slash_commands_init_and_list_project_templates -q` passed with 4 tests and the known host Python `RequestsDependencyWarning`; `poetry run airesearcher readiness --allow-missing-channel --allow-untested-channel` passed and reported the current local checkout ready with warnings for missing configured WeChat/Feishu delivery channel and missing latest `channels test` sent evidence; `python -m ruff check src tests`, `python -m mypy src\autoresearch`, `git diff --check`, and `python -m pytest tests\smoke tests\unit -q` passed with 506 passed, 4 skipped, 1 LangGraph warning, and the known host Python `RequestsDependencyWarning` after pytest exit._

- [x] 157. Setup next-step guidance for push readiness
  - [x] 157.1 Print channel self-test and readiness commands after setup
    - After `setup`/`deploy-setup` writes config and `.env`, print a `[NEXT] channel_test` command when WeChat and/or Feishu are enabled.
    - Print strict `readiness --push-inspiration --require-channel-config --require-channel-sent` when channels are enabled.
    - Print `readiness --no-push-inspiration` when no operator channel is configured, so no-channel deployments do not get a guaranteed-failing push gate as the next step.
    - Add CLI tests for both channel-enabled and channel-disabled setup output.
    - _References: tasks `154.1`, `155.1`, and `156.1`; user requirement that deployment be guided rather than forcing users to manually discover one command after another._
    - _Verify: `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; `python -m mypy src\autoresearch\cli\main.py` passed; `python -m pytest tests\unit\cli\test_main.py::test_deploy_setup_writes_provider_config_and_env_without_committing_secret tests\unit\cli\test_main.py::test_setup_guided_wechat_qr_runs_qr_setup tests\unit\cli\test_main.py::test_setup_bootstraps_env_vault_manifests_and_slash_commands -q` passed with 3 tests and the known host Python `RequestsDependencyWarning`; `python -m ruff check src tests`, `python -m mypy src\autoresearch`, `git diff --check`, and `python -m pytest tests\smoke tests\unit -q` passed with 506 passed, 4 skipped, 1 LangGraph warning, and the known host Python `RequestsDependencyWarning` after pytest exit._

- [x] 158. Readiness next-action remediation
  - [x] 158.1 Add structured next actions to readiness reports
    - Add `next_actions` to `.airesearcher/readiness/report.json` so blocked or warning readiness output records executable remediation commands.
    - Print each action as `[NEXT] readiness_action.<id>: <command>` in the CLI output.
    - Recommend setup repair for missing first-deploy config, channel setup for missing WeChat/Feishu delivery config, channel self-test for configured channels without sent evidence, and daily-loop start only when there are no failures or warnings.
    - Add CLI tests for clean readiness, missing sent channel evidence, and missing channel configuration.
    - _References: tasks `155.1`, `156.1`, and `157.1`; user requirement that setup and prelaunch checks guide operators through real push-readiness instead of relying on manual `.env` edits or hidden assumptions._
    - _Verify: `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; `python -m mypy src\autoresearch\cli\main.py` passed; `python -m pytest tests\unit\cli\test_main.py::test_readiness_command_writes_daily_loop_report tests\unit\cli\test_main.py::test_readiness_requires_sent_channel_self_test tests\unit\cli\test_main.py::test_readiness_requires_channel_config_for_push -q` passed with 3 tests and the known host Python `RequestsDependencyWarning`; `poetry run airesearcher readiness --allow-missing-channel --allow-untested-channel` passed on the real local checkout and wrote `.airesearcher/readiness/report.json` with a `configure_operator_channel` next action but no premature `start_daily_loop` action while warnings remain; `python -m ruff check src tests`, `python -m mypy src\autoresearch`, `git diff --check`, and `python -m pytest tests\smoke tests\unit -q` passed with 506 passed, 4 skipped, 1 LangGraph warning, and the known host Python `RequestsDependencyWarning` after pytest exit._

- [x] 159. npm prelaunch onboarding shortcuts
  - [x] 159.1 Add npm wrappers for channel self-test and readiness
    - Add npm scripts for `channel:test`, `readiness`, and strict `prelaunch`.
    - Document the npm shortcuts in English and Chinese README quick-start and CLI reference sections.
    - Add a package-json unit test that guards the guided deployment script names and command wiring.
    - Verify the npm readiness wrapper against the real local checkout and verify strict `prelaunch` blocks when channel config and sent evidence are absent.
    - _References: tasks `119.1`, `155.1`, `156.1`, `157.1`, and `158.1`; user requirement that deployment feel like a normal guided product entry rather than a sequence of manually discovered commands._
    - _Verify: `python -m pytest tests\unit\test_npm_scripts.py -q` passed with 1 test plus an expected coverage no-data warning because the test only inspects `package.json`; `npm run readiness -- --no-push-inspiration` passed on the real local checkout and printed `start_daily_loop` for no-push mode; `npm run channel:test -- --help` rendered the channel self-test CLI help through the Node wrapper; `npm run prelaunch` exited 1 as expected because this checkout has no configured WeChat/Feishu channel or latest sent channel-test artifact, and it printed `configure_operator_channel` as the repair action; `python -m ruff check src tests`, `python -m mypy src\autoresearch`, `git diff --check`, and `python -m pytest tests\smoke tests\unit -q` passed with 507 passed, 4 skipped, 1 LangGraph warning, and the known host Python `RequestsDependencyWarning` after pytest exit._

- [x] 160. Host Python warning cleanup
  - [x] 160.1 Resolve local `RequestsDependencyWarning` verification noise
    - Confirm the warning source with `pip check`, package metadata, and the installed `requests` compatibility code.
    - Align the host/global Python environment to versions compatible with project and transitive requirements.
    - Update `Problem.md` so future agents know the warning was a host dependency drift issue, not a project code failure.
    - _References: `P-20260612-057`; user request to clean up final verification noise rather than leave known warnings unexplained._
    - _Verify: `python -m pip check` initially failed because `langchain-community 0.3.31` requires `requests>=2.32.5` while host Python had `requests 2.31.0`; `python -m pip show requests urllib3 chardet charset-normalizer` confirmed host Python had `requests 2.31.0`, `urllib3 2.7.0`, `chardet 7.4.3`, and `charset-normalizer 3.4.7`; `python -m pip install "requests==2.32.5" "chardet==5.2.0"` succeeded; `python -m pip check` then returned `No broken requirements found`; `python -c "import requests; print(requests.__version__)"` printed `2.32.5` without `RequestsDependencyWarning`; `python -m pytest tests\unit\test_npm_scripts.py -q` passed with 1 test and no Requests warning; `python -m ruff check src tests`, `python -m mypy src\autoresearch`, `git diff --check`, and `python -m pytest tests\smoke tests\unit -q` passed with 507 passed, 4 skipped, and only the LangGraph deprecation warning._

- [x] 161. Agent import warning hygiene
  - [x] 161.1 Lazy-load LangGraph workflow exports from the agent package
    - Remove eager workflow imports from `autoresearch.agents` so message, registry, and base-agent imports do not initialize LangGraph.
    - Preserve public package exports for `ResearchWorkflow`, `ResearchWorkflowStage`, `ResearchWorkflowState`, and `WorkflowCheckpointStore` through lazy module attribute loading.
    - Add a unit regression test proving ordinary agent message imports do not load `autoresearch.agents.workflow`.
    - Keep true workflow execution tests available in the integration suite, where the third-party LangGraph deprecation warning remains scoped to explicit workflow use.
    - _References: task `160.1`; recurring verification noise from the LangGraph `allowed_objects` warning after Requests warning cleanup._
    - _Verify: `python -m pytest tests\unit\agents -q` passed with 6 tests and no warnings; `python -m pytest tests\integration\agents\test_workflow.py -q` passed with 1 test and retained the third-party LangGraph warning only for explicit workflow use; first broad `python -m pytest tests\smoke tests\unit -q` exposed `P-20260618-083` from a duplicate test module basename and was fixed by renaming the new test; `python -m ruff check src tests` passed; `python -m mypy src\autoresearch` passed with no issues in 104 source files; `git diff --check` passed with expected CRLF notices for unrelated dirty vault files and touched agent files; final `python -m pytest tests\smoke tests\unit -q` passed with 508 passed, 4 skipped, and no LangGraph or Requests warning._

- [x] 162. Daily loop startup evidence
  - [x] 162.1 Print explicit loop-plan evidence when `autopilot` or `serve` starts
    - Echo the command name, loop mode, cycle count, interval seconds, and inspiration-push flag before the loop claims runtime paths or starts a cycle.
    - Represent `--once` and non-watch runs as `single-cycle`, finite watch runs as `watch-limited`, and `--watch --cycles 0` as `watch-forever`.
    - Cover both `autopilot` and `serve` in CLI tests, including a `serve --once --push-inspiration` startup path.
    - Verify a real Node-wrapper `serve --once --push-inspiration` smoke prints the loop plan and stops at the approval gate while writing approval/session evidence.
    - _References: user requirement that the system can run unattended every day and push inspiration through configured channels; tasks `127.1`, `155.1`, `158.1`, and `159.1`._
    - _Verify: `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; `python -m mypy src\autoresearch\cli\main.py` passed with no issues in 1 source file; focused `python -m pytest tests\unit\cli\test_main.py::test_autopilot_command_runs_one_non_review_cycle tests\unit\cli\test_main.py::test_serve_allow_all_runs_without_approval_state -q` passed with 2 tests; `python -m ruff check src tests` passed; `python -m mypy src\autoresearch` passed with no issues in 104 source files; `python -m pytest tests\smoke tests\unit -q` passed with 508 passed, 4 skipped, and no Requests or LangGraph warning; real smoke `node .\bin\airesearcher.mjs serve --once --permission-mode approve-dangerous --state runs\manual-live\task162-loop-plan\scheduler-state.json --approvals-state runs\manual-live\task162-loop-plan\approvals.json --sessions-state runs\manual-live\task162-loop-plan\sessions.json --vault runs\manual-live\task162-loop-plan\vault --cache runs\manual-live\task162-loop-plan\cache --output-dir runs\manual-live\task162-loop-plan\runs --deliverables-dir runs\manual-live\task162-loop-plan\outputs --project-id task162_loop_plan --no-review --push-inspiration` printed `[OK] loop_plan: command=serve, mode=single-cycle, cycles=1, interval_seconds=86400, push_inspiration=true`, stopped at the approval gate as expected, wrote the approval request command with `--push-inspiration`, and released the runtime session._

- [x] 163. Runtime approval polling responsiveness
  - [x] 163.1 Separate approval polling from the daily cycle interval
    - Add a `serve --approval-poll-seconds` option with a short default for waiting on dangerous-cycle approval.
    - Keep `serve --interval-seconds 86400` as the daily post-cycle interval rather than the approval wait interval.
    - Include the approval poll interval in `serve` loop-plan output and bilingual README parameter tables.
    - Add a watch-mode test proving approval waiting sleeps for the approval poll interval, not the daily interval.
    - _References: `P-20260618-084`; user requirement for `/approve`-style dangerous-command approval in a 24h service._
    - _Verify: `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; `python -m mypy src\autoresearch\cli\main.py` passed with no issues in 1 source file; focused `python -m pytest tests\unit\cli\test_main.py::test_serve_allow_all_runs_without_approval_state tests\unit\cli\test_main.py::test_serve_watch_uses_approval_poll_interval_before_cycle tests\unit\cli\test_main.py::test_serve_queues_dangerous_action_until_runtime_approval -q` passed with 3 tests; `python -m ruff check src tests` passed; `python -m mypy src\autoresearch` passed with no issues in 104 source files; `python -m pytest tests\smoke tests\unit -q` passed with 509 passed, 4 skipped, and no Requests or LangGraph warning._

- [x] 164. Per-cycle approval boundaries
  - [x] 164.1 Require a fresh `serve` approval action ID for each cycle attempt
    - Include the next cycle number in the `serve` dangerous-action approval ID instead of reusing one project/demo-level ID forever.
    - Preserve the existing pending/approved retry behavior for the current cycle: approving `cycle-1` lets that same cycle run after restart or retry.
    - Add a watch-mode regression test proving a second cycle queues/checks `cycle-2` after `cycle-1` completes.
    - Document that `approve-dangerous` is per-cycle and `allow-all` is the intentional no-per-cycle-approval mode.
    - _References: `P-20260618-085`; user requirement for `/approve` dangerous-command gates in a 24h always-on service._
    - _Verify: `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; `python -m mypy src\autoresearch\cli\main.py` passed with no issues in 1 source file; focused `python -m pytest tests\unit\cli\test_main.py::test_serve_queues_dangerous_action_until_runtime_approval tests\unit\cli\test_main.py::test_serve_watch_requires_new_approval_for_next_cycle -q` passed with 2 tests; `python -m ruff check src tests` passed; `python -m mypy src\autoresearch` passed with no issues in 104 source files; `git diff --check` passed with expected CRLF notices for touched files and unrelated dirty vault files; `python -m pytest tests\smoke tests\unit -q` passed with 510 passed, 4 skipped, and no Requests or LangGraph warning._

- [x] 165. Approval operator visibility
  - [x] 165.1 Print the per-cycle action ID directly in `serve` approval wait output
    - When a dangerous `serve` cycle is waiting for approval, echo the same per-cycle `action_id` shown by `runtime list`.
    - Cover first-cycle pending output and second-cycle watch-mode pending output in CLI tests.
    - Document that both waiting output and `runtime list` expose the per-cycle action ID for operator confirmation.
    - _References: `P-20260618-086`; task `164.1`; user requirement for approval gates that are understandable from CLI and IM surfaces._
    - _Verify: `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; `python -m mypy src\autoresearch\cli\main.py` passed with no issues in 1 source file; focused `python -m pytest tests\unit\cli\test_main.py::test_serve_queues_dangerous_action_until_runtime_approval tests\unit\cli\test_main.py::test_serve_watch_uses_approval_poll_interval_before_cycle tests\unit\cli\test_main.py::test_serve_watch_requires_new_approval_for_next_cycle -q` passed with 3 tests; `python -m ruff check src tests` passed; `python -m mypy src\autoresearch` passed with no issues in 104 source files; `git diff --check` passed with expected CRLF notices for touched files and unrelated dirty vault files; `python -m pytest tests\smoke tests\unit -q` passed with 510 passed, 4 skipped, and no Requests or LangGraph warning._

- [x] 166. Prelaunch entrypoint alignment
  - [x] 166.1 Make readiness recommend the approval-gated `serve` runtime
    - Change the readiness report's `planned_daily_command` from direct `autopilot --watch` to `serve --permission-mode approve-dangerous --watch`.
    - Keep `autopilot` available as the lower-level direct loop, but ensure strict prelaunch points ordinary operators to the approval service wrapper.
    - Update the readiness unit test and README text to make this policy explicit.
    - Run the real `npm run prelaunch` command and record whether the planned command and blocking checks match the current local deployment state.
    - _References: `P-20260618-087`; tasks `163.1` through `165.1`; user requirement that the 24h system use dangerous-command approval gates._
    - _Verify: focused `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py`, `python -m mypy src\autoresearch\cli\main.py`, and `python -m pytest tests\unit\cli\test_main.py::test_readiness_command_writes_daily_loop_report -q` passed; real `npm run prelaunch` printed `[OK] planned_daily_command: airesearcher serve --permission-mode approve-dangerous --watch --cycles 0 --interval-seconds 86400 --push-inspiration` and correctly blocked on missing WeChat/Feishu channel configuration plus missing sent channel self-test evidence; `python -m ruff check src tests` passed; `python -m mypy src\autoresearch` passed with no issues in 104 source files; `git diff --check` passed with expected CRLF notices for touched files and unrelated dirty vault files; `python -m pytest tests\smoke tests\unit -q` passed with 510 passed, 4 skipped, and no Requests or LangGraph warning._

- [x] 167. Live source policy smoke alignment
  - [x] 167.1 Align the live daily literature refresh smoke with ArXiv/OpenAlex defaults
    - Update the opt-in live daily refresh smoke to require ArXiv and OpenAlex coverage instead of Semantic Scholar coverage.
    - Preserve the separate optional live client/similarity smokes for Semantic Scholar telemetry when enabled or available.
    - Run the live literature/similarity smoke against real APIs to prove the default source policy works outside mocks.
    - _References: `P-20260618-088`; tasks `102.1` and `137.1`; user requirement that Semantic Scholar be lower-priority and optional while free public APIs carry the default literature loop._
    - _Verify: first live run with `AUTORESEARCH_LIVE_APIS=1` failed because `test_literature_refresh_live.py` still required Semantic Scholar while the real refresh returned ArXiv/OpenAlex; after updating the smoke, `python -m pytest tests\smoke\test_literature_live.py tests\smoke\test_literature_refresh_live.py tests\smoke\test_similarity_live.py -q` passed with 3 live tests; `python -m ruff check src tests` passed; `python -m mypy src\autoresearch` passed with no issues in 104 source files; `git diff --check` passed with expected CRLF notices for touched files and unrelated dirty vault files; `python -m pytest tests\smoke tests\unit -q` passed with 510 passed, 4 skipped, and no Requests or LangGraph warning._

- [x] 168. WeChat QR delivery self-test path
  - [x] 168.1 Add OpenClaw target-backed delivery for WeChat QR mode
    - Add setup-owned environment fields for the OpenClaw WeChat message target, channel id, login command, and message-send command.
    - Let QR-mode notification delivery call `openclaw message send` when QR login is completed and a target is configured.
    - Keep QR-mode delivery `skipped` when login status or target binding is missing; do not claim sent delivery from setup status alone.
    - Make readiness treat WeChat QR as push-ready only when QR setup completed and an OpenClaw target is configured.
    - _References: `P-20260618-089`; user requirement that WeChat QR setup happen in `setup` and that channel self-tests use real delivery rather than `.env` hand-edit assumptions; upstream OpenClaw WeChat docs and `@tencent-weixin/openclaw-weixin-cli` installer behavior._
    - _Verify: focused `python -m pytest tests\unit\test_notifications.py tests\unit\cli\test_main.py::test_deploy_setup_configures_qr_wechat_and_feishu_app_gateway tests\unit\cli\test_main.py::test_setup_guided_wechat_qr_runs_qr_setup tests\unit\cli\test_main.py::test_readiness_requires_wechat_qr_openclaw_target_for_push -q` passed with 10 tests; focused `python -m ruff check src\autoresearch\notifications.py src\autoresearch\cli\main.py tests\unit\test_notifications.py tests\unit\cli\test_main.py` passed; focused `python -m mypy src\autoresearch\notifications.py src\autoresearch\cli\main.py` passed with no issues._

- [x] 169. Post-pairing channel target binding
  - [x] 169.1 Add a channels command for binding delivery targets after setup
    - Add `airesearcher channels bind-target --channel wechat --target <target>` to write WeChat QR OpenClaw delivery target fields into `.env`.
    - Add `airesearcher channels bind-target --channel feishu --target <chat-id>` to write the Feishu/Lark home chat ID after a bot conversation reveals it.
    - Reject unsupported channels and empty targets.
    - Document the command in English and Chinese README channel setup tables.
    - _References: `P-20260618-090`; task `168.1`; user requirement that setup and channel configuration be CLI-owned rather than manual `.env` editing._
    - _Verify: focused `python -m pytest tests\unit\cli\test_main.py::test_channels_bind_target_writes_wechat_openclaw_target tests\unit\cli\test_main.py::test_channels_bind_target_writes_feishu_home_chat tests\unit\cli\test_main.py::test_channels_bind_target_rejects_unknown_channel tests\unit\cli\test_main.py::test_channels_test_command_sends_probe_and_writes_result -q` passed with 4 tests; focused `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; focused `python -m mypy src\autoresearch\cli\main.py` passed; real `node ./bin/airesearcher.mjs channels bind-target --env-path runs\manual-live\task169-bind-target\.env --channel wechat --target peer:wx_user` passed and printed the channel-test next step._

- [x] 170. Readiness repair action precision for QR target binding
  - [x] 170.1 Point completed WeChat QR setups without a target to `channels bind-target`
    - Let `channels bind-target` prompt for the target when `--target` is omitted, so readiness can print an executable repair command.
    - Detect `wechat_mode=qr`, completed QR setup status, and missing OpenClaw target in readiness evidence.
    - Emit `bind_wechat_target` next action instead of rerunning full setup for that specific post-pairing state.
    - Document the optional prompt behavior in English and Chinese README parameter tables.
    - _References: `P-20260618-090`; `P-20260618-091`; tasks `168.1` and `169.1`; user requirement that setup/channel onboarding avoid manual `.env` edits and guide the operator through QR setup._
    - _Verify: focused `python -m pytest tests\unit\cli\test_main.py::test_channels_bind_target_prompts_for_missing_target tests\unit\cli\test_main.py::test_channels_bind_target_writes_wechat_openclaw_target tests\unit\cli\test_main.py::test_readiness_requires_wechat_qr_openclaw_target_for_push -q` passed with 3 tests; focused `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; focused `python -m mypy src\autoresearch\cli\main.py` passed; first real readiness probe failed because a BOM-bearing temporary `.env` hid the first LLM key and was logged as `P-20260618-091`; the second no-BOM real probe printed `[NEXT] readiness_action.bind_wechat_target: airesearcher channels bind-target --channel wechat --env-path runs/manual-live/task170-readiness-bind-target-v2/.env`._

- [x] 171. BOM-safe env onboarding
  - [x] 171.1 Parse BOM-bearing `.env` files in CLI readiness/setup helpers
    - Read CLI-managed `.env` files with UTF-8 BOM handling so the first key is not hidden when Windows editors write `EF BB BF`.
    - Add a readiness regression test where the first line is `\ufeffAUTORESEARCH_LLM_BASE_URL=...`.
    - Verify the real Node CLI readiness entrypoint against a temporary BOM-bearing `.env`.
    - _References: `P-20260618-091`; task `170.1`; user requirement that setup/readiness be practical for normal deployment users instead of requiring manual `.env` expertise._
    - _Verify: focused `python -m pytest tests\unit\cli\test_main.py::test_readiness_accepts_bom_prefixed_env_file tests\unit\cli\test_main.py::test_readiness_requires_channel_config_for_push -q` passed with 2 tests; focused `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; focused `python -m mypy src\autoresearch\cli\main.py` passed; real `node ./bin/airesearcher.mjs readiness --config config.yaml --env-path runs\manual-live\task171-bom-env\.env --vault runs\manual-live\task171-bom-env\vault --outputs-dir runs\manual-live\task171-bom-env\outputs --output runs\manual-live\task171-bom-env\readiness.json --require-channel-config` produced expected blocked readiness with `llm_credentials=pass` and `operator_channels=fail`; broad `python -m ruff check src tests`, `python -m mypy src\autoresearch`, `git diff --check`, and `python -m pytest tests\smoke tests\unit -q` passed with 517 passed and 4 skipped._

- [x] 172. BOM-safe QR status and self-test handoff
  - [x] 172.1 Parse BOM-bearing JSON status files for readiness
    - Read shared JSON status files with UTF-8 BOM handling.
    - Cover a completed WeChat QR setup status file that starts with a BOM.
    - Verify readiness recognizes QR as a ready channel and points to `channels test --channel wechat --require-sent` when delivery evidence is still missing.
    - _References: `P-20260618-092`; tasks `168.1`, `170.1`, and `171.1`; user requirement that setup/QR/prelaunch be usable by normal Windows deployment users and proceed to real push self-tests._
    - _Verify: initial real readiness probe against `runs\manual-live\task172-wechat-ready-action` failed with `wechat_openclaw_target_configured=true` but `wechat_qr_status=null`; focused `python -m pytest tests\unit\cli\test_main.py::test_readiness_accepts_bom_prefixed_wechat_qr_status_file tests\unit\cli\test_main.py::test_readiness_requires_wechat_qr_openclaw_target_for_push tests\unit\cli\test_main.py::test_readiness_requires_sent_channel_self_test -q` passed with 3 tests; focused `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; focused `python -m mypy src\autoresearch\cli\main.py` passed; real Node CLI readiness rerun against the same fixture reported `operator_channels=pass`, `channel_delivery_test=fail`, and `run_channel_self_test` for `--channel wechat`; broad `python -m ruff check src tests`, `python -m mypy src\autoresearch`, `git diff --check`, and `python -m pytest tests\smoke tests\unit -q` passed with 518 passed and 4 skipped._

- [x] 173. Prelaunch QR action clarity
  - [x] 173.1 Make readiness setup repair explicitly launch WeChat QR setup
    - Add `--run-wechat-qr-setup` to the `configure_operator_channel` next action when readiness asks the operator to set up WeChat QR.
    - Update the readiness regression test for missing channel configuration.
    - Verify strict prelaunch still blocks without a real channel but now prints the direct QR setup command.
    - _References: `P-20260618-093`; user requirement that setup show the WeChat QR code during configuration instead of relying on later manual commands._
    - _Verify: focused `python -m pytest tests\unit\cli\test_main.py::test_readiness_requires_channel_config_for_push tests\unit\cli\test_main.py::test_readiness_requires_sent_channel_self_test -q` passed with 2 tests; focused `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; focused `python -m mypy src\autoresearch\cli\main.py` passed; real `npm run prelaunch` still blocked as expected on missing channel configuration and missing sent evidence, but printed `[NEXT] readiness_action.configure_operator_channel: airesearcher setup --config config.yaml --env-path .env --wechat --wechat-qr --run-wechat-qr-setup`; broad `python -m ruff check src tests`, `python -m mypy src\autoresearch`, `git diff --check`, and `python -m pytest tests\smoke tests\unit -q` passed with 518 passed and 4 skipped._

- [x] 174. Operator monitor publication gate visibility
  - [x] 174.1 Surface publication blockers, evidence blockers, and real follow-up counts in `monitor`
    - Extend the release-critical monitor stage table so `publication` summarizes score, target, blocker count, and the first failed check.
    - Extend the `evidence` row so blocked release gates summarize failed-check count, `release_allowed`, and the first failed check.
    - Read both legacy `followup_tasks` and current `followups.tasks` structures so real serve cycles display queued issue follow-ups instead of `none`.
    - Preserve compact terminal output while keeping full blocker messages and next actions available in the stage evidence text.
    - _References: `P-20260618-094`; real `serve --once` task174 cycle; user requirement that the CLI operator console show agent flow, output quality, and actionable gates during 24h autonomous operation._
    - _Verify: focused `python -m pytest tests\unit\cli\test_main.py::test_monitor_renders_agent_flow_changes_and_preview -q` passed with 1 test after an initial assertion adjustment for Rich column truncation; focused `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; focused `python -m mypy src\autoresearch\cli\main.py` passed; real `node ./bin/airesearcher.mjs monitor --runtime-state runs\manual-live\task174-serve-no-push\approvals.json --scheduler-state runs\manual-live\task174-serve-no-push\scheduler-state.json --sessions-state runs\manual-live\task174-serve-no-push\sessions.json --outputs-dir runs\manual-live\task174-serve-no-push\outputs --cycle-summary runs\manual-live\task174-serve-no-push\runs\cycle-20260617T203842Z\cycle-summary.json --no-diff --max-agent-entries 2` rendered `publication` as `fail; score=0.327; target=ccf-b; blockers=19; first=literature_query_breadth`, `evidence` as `blocked; failed=2; release_allowed=false; first=review_gate`, and `follow-ups` as `5 open / 5 total`; broad `python -m ruff check src tests`, `python -m mypy src\autoresearch`, `git diff --check`, and `python -m pytest tests\smoke tests\unit -q` passed with 518 passed and 4 skipped._
  - [x] 174.2 Stabilize monitor CI assertion for terminal-width truncation
    - Remove the stdout assertion that required `evidence-gate.md` to survive Rich terminal column truncation.
    - Keep exact path coverage in structured `_cycle_stage_rows()` assertions where terminal width cannot hide content.
    - _References: `P-20260618-095`; failed GitHub Actions run `27718801671`; task `174.1`._
    - _Verify: `python -m pytest tests\unit\cli\test_main.py::test_monitor_renders_agent_flow_changes_and_preview -q` passed locally; GitHub Actions failure evidence confirmed the previous assertion was the only failing test on the pushed `d230920` commit._

- [x] 175. Default autonomous loop uses a real public benchmark, not the toy smoke fixture
  - [x] 175.1 Switch `serve` and `autopilot` defaults to Pendigits variance-calibrated prototypes
    - Add a shared CLI default demo constant for long-running research loops.
    - Set `serve` and `autopilot` to default to `pendigits_variance_calibrated_prototypes` while leaving `run-demo` on `tabular_baseline` for explicit quick smoke runs.
    - Update approval-action tests, autopilot single-cycle tests, and docs so default cycle IDs, inspiration queries, reproduction checks, and candidate summaries follow the real benchmark default.
    - Document in English and Chinese README that `tabular_baseline` is only for tiny local smoke and that the always-on loop defaults to UCI Pendigits with at least 1,000 validation rows.
    - _References: `P-20260618-096`; real task174 cycle publication blockers caused by toy data scale; user requirement that default unattended operation run real research/data rather than agent-assumed smoke fixtures._
    - _Verify: real approval-blocking smoke `node ./bin/airesearcher.mjs serve --once --permission-mode approve-dangerous --approvals-state runs\manual-live\task175-default-demo\approvals.json --state runs\manual-live\task175-default-demo\scheduler-state.json --sessions-state runs\manual-live\task175-default-demo\sessions.json --project-id task175_default_demo --no-review` exited 1 as expected and printed `serve:autopilot-cycle:task175_default_demo:pendigits_variance_calibrated_prototypes:cycle-1`; real public benchmark `node ./bin/airesearcher.mjs run-demo --demo pendigits_variance_calibrated_prototypes --output-dir runs\manual-live\task175-pendigits-demo --timeout-seconds 120` passed with 3,498 test rows, 10,992 dataset rows, accuracy 0.823327615780446, baseline accuracy 0.7775871926815323, and validation status passed; focused `python -m pytest tests\unit\cli\test_main.py::test_autopilot_command_runs_one_non_review_cycle -q` passed after replacing toy-demo test expectations; broad `python -m ruff check src tests`, `python -m mypy src\autoresearch`, `git diff --check`, and `python -m pytest tests\smoke tests\unit -q` passed with 518 passed and 4 skipped._

- [x] 176. Review and publication gate console wording stays evidence-honest
  - [x] 176.1 Surface review verdicts and distinguish publication warnings from blockers
    - Print `review_status` with status, verdict, and quality score in `serve` and `autopilot`.
    - Mark a review line as `[BLOCKED]` when the evidence-constrained review executed successfully but returned a non-pass verdict.
    - In the monitor publication row, count only fail/blocked/error or `severity=blocking` checks as `blockers`; report other non-pass checks as `warnings`.
    - Render publication warning evidence as `issue:` while preserving `blocker:` wording for true evidence-gate blockers.
    - _References: `P-20260618-097`; real task176 cycles `cycle-20260617T210513Z` and `cycle-20260617T210941Z`; user requirement that quality gates must not overstate paper readiness._
    - _Verify: first real default `serve --once --permission-mode allow-all` cycle exposed `review status=passed, verdict=needs_revision, quality_score=1.0` while evidence gate blocked release; second real default `serve --once --permission-mode allow-all` cycle after the display change printed `review_status: passed; verdict=pass; quality=1.000`, `publication_audit: pass`, `evidence_gate: pass`, `followup_tasks: 0`, and generated PDF `runs/manual-live/task176-review-status/outputs/task176_review_status/task176_review_status-cycle-20260617T210941Z.pdf`; real monitor rerun on that cycle displayed `publication pass; score=0.985; target=ccf-b; warnings=1` and `evidence pass; failed=0; release_allowed=true`; focused review/monitor tests passed; broad `python -m ruff check src tests`, `python -m mypy src\autoresearch`, `git diff --check`, and `python -m pytest tests\smoke tests\unit -q` passed with 521 passed and 4 skipped._
  - [x] 176.2 Stabilize review status helper for CI ruff version
    - Replace tuple-style `isinstance(score, (int, float))` with `isinstance(score, int | float)` in the review status display helper.
    - _References: `P-20260618-098`; failed GitHub Actions run `27720376566`; task `176.1`._
    - _Verify: `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; `python -m mypy src\autoresearch\cli\main.py` passed; `python -m ruff check src tests` passed._

- [x] 177. Root `outputs/` publication path is real-cycle verified
  - [x] 177.1 Verify default deliverables path with a real `serve --once` cycle
    - Run a real default-Pendigits cycle with isolated vault/cache/run state but without overriding `--deliverables-dir`, so the CLI uses the project-root `outputs/` default.
    - Confirm the manifest uses relative project-root paths and exports the publication PDF, paper build files, manuscript Markdown, evidence gate, publication audit, related work, and research plan artifacts.
    - Confirm the generated PDF is readable and has the expected 14-page paper-build output.
    - _References: user requirement that publication-grade PDFs be generated under the project-root `outputs/` folder with relative paths._
    - _Verify: `node ./bin/airesearcher.mjs serve --once --permission-mode allow-all --vault runs\manual-live\task177-root-output\vault --cache runs\manual-live\task177-root-output\cache --output-dir runs\manual-live\task177-root-output\runs --state runs\manual-live\task177-root-output\scheduler-state.json --approvals-state runs\manual-live\task177-root-output\approvals.json --sessions-state runs\manual-live\task177-root-output\sessions.json --project-id task177_root_output --timeout-seconds 120 --no-push-inspiration` passed with `review_status: passed; verdict=pass; quality=1.000`, `publication_audit: pass`, `evidence_gate: pass`, `followup_tasks: 0`, and `pdf_output: outputs/task177_root_output/task177_root_output-cycle-20260617T212210Z.pdf`; manifest `outputs\task177_root_output\task177_root_output-cycle-20260617T212210Z-manifest.json` records relative paths; `pdfinfo outputs\task177_root_output\task177_root_output-cycle-20260617T212210Z.pdf` reported 14 pages and PDF version 1.7._

- [x] 178. Guided WeChat QR setup terminal clarity
  - [x] 178.1 Show an explicit run-state line before launching the QR adapter setup
    - Keep interactive setup behavior unchanged: choosing WeChat QR still starts the upstream QR setup runner after config and `.env` are written.
    - Add a visible `[RUN] wechat_qr_setup` line immediately before the runner starts so operators can see that setup has moved from "next step" into the live scan/login phase.
    - Extend the guided setup regression test to assert the explicit run-state line.
    - _References: tasks `120.1`, `153.1`, and `173.1`; user requirement that choosing WeChat QR during setup should display the QR scan flow immediately rather than requiring a hidden later command._
    - _Verify: focused `python -m pytest tests\unit\cli\test_main.py::test_setup_guided_wechat_qr_runs_qr_setup tests\unit\cli\test_main.py::test_deploy_setup_runs_wechat_qr_setup_with_status_artifact tests\unit\cli\test_main.py::test_readiness_requires_channel_config_for_push -q` passed with 3 tests; focused `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; focused `python -m mypy src\autoresearch\cli\main.py` passed._

- [x] 179. Repository hygiene for launch artifacts
  - [x] 179.1 Ignore local Codex attachment scratch files
    - Confirm generated runtime artifacts, outputs, caches, and PDFs are not tracked by Git.
    - Add `.codex-remote-attachments/` to `.gitignore` so local screenshots and uploaded reference images cannot be accidentally committed.
    - Keep existing local attachment files in place; this task only changes ignore rules.
    - _References: user requirement that the GitHub repository keep only necessary code and project files._
    - _Verify: `git ls-files outputs runs htmlcov .cache tmp .pytest_cache .mypy_cache .ruff_cache .airesearcher .codex-remote-attachments` returned no tracked paths; tracked artifact pattern scan returned no matches; after the ignore update, `git status --short` no longer lists `.codex-remote-attachments/`._

- [x] 180. Publication reference locator quality
  - [x] 180.1 Preserve real DOI/URL locators in formal references and LaTeX output
    - Keep prose URL elision for ordinary manuscript text, but preserve DOI, URL, and source URI fields used by formal bibliography lines.
    - Ensure LaTeX URL wrapping captures dotted domains and strips only trailing sentence punctuation.
    - Add regression coverage that the Markdown References section contains the real URL and no `source URL recorded in artifact` placeholder.
    - Verify the generated TeX contains a complete `\url{...}` reference locator.
    - Run a real default-Pendigits `serve --once` cycle and inspect the generated PDF references.
    - _References: `P-20260618-099`; user screenshot and repeated requirement that reference format be publication-facing and not placeholder-like._
    - _Verify: after an initial incorrect pytest selector and an intermediate TeX URL-splitting failure, focused report tests passed; `python -m pytest tests\unit\reports -q` passed with 89 tests; `python -m ruff check src tests` passed; `python -m mypy src\autoresearch` passed with no issues; real `node ./bin/airesearcher.mjs serve --once --permission-mode allow-all --vault runs\manual-live\task180-reference-urls\vault --cache runs\manual-live\task180-reference-urls\cache --output-dir runs\manual-live\task180-reference-urls\runs --deliverables-dir outputs --state runs\manual-live\task180-reference-urls\scheduler-state.json --approvals-state runs\manual-live\task180-reference-urls\approvals.json --sessions-state runs\manual-live\task180-reference-urls\sessions.json --project-id task180_reference_urls --timeout-seconds 120 --no-push-inspiration` passed with review, publication audit, evidence gate, zero follow-ups, and PDF output; `pdftotext` on the generated PDF showed real arXiv/DOI URLs in References; `pdfinfo` reported a 14-page PDF; `python -m pytest tests\smoke tests\unit -q` passed with 521 passed and 4 skipped._

- [x] 181. Formal reference relevance and template-readiness honesty
  - [x] 181.1 Filter seed-topic drift out of formal references and stop generic-template overclaims
    - Exclude seed-document title text from the formal reference relevance context so an unrelated inspiration paper cannot pull weak references into the bibliography.
    - Require direct formal references to carry task anchors such as prototype/classifier, nearest/centroid, handwritten/digit/recognition, or adjacent metric-classifier evidence.
    - Add regression coverage proving a seed-style Boolean variance citation is not rendered in the manuscript References.
    - Rewrite manuscript template-build prose so a passing generic article build only certifies the selected template and does not imply ACM, IEEE, Springer, or other venue-template compatibility.
    - Run a real default-Pendigits `serve --once` cycle and inspect the generated PDF text, LLM review, publication audit, and evidence gate.
    - _References: `P-20260618-100`; user requirement that reference lists be real, relevant, publication-facing, and that LaTeX/PDF readiness not overclaim untested conference templates._
    - _Verify: focused `python -m pytest tests\unit\reports\test_manuscript.py tests\unit\reports\test_paper_build.py::test_build_latex_paper_from_markdown_writes_tex_and_vault_summary -q` passed; focused `python -m ruff check src\autoresearch\reports\manuscript.py tests\unit\reports\test_manuscript.py` passed; focused `python -m mypy src\autoresearch\reports\manuscript.py` passed; real `node ./bin/airesearcher.mjs serve --once --permission-mode allow-all --vault runs\manual-live\task181-reference-relevance-v3\vault --cache runs\manual-live\task181-reference-relevance-v3\cache --output-dir runs\manual-live\task181-reference-relevance-v3\runs --deliverables-dir outputs --state runs\manual-live\task181-reference-relevance-v3\scheduler-state.json --approvals-state runs\manual-live\task181-reference-relevance-v3\approvals.json --sessions-state runs\manual-live\task181-reference-relevance-v3\sessions.json --project-id task181_reference_relevance_v3 --timeout-seconds 120 --no-push-inspiration` passed with `review_status: passed; verdict=pass; quality=1.000`, `publication_audit: pass`, `evidence_gate: pass`, `followup_tasks: 0`, and `pdf_output: outputs/task181_reference_relevance_v3/task181_reference_relevance_v3-cycle-20260617T215414Z.pdf`; `pdfinfo` reported 14 pages; `pdftotext` confirmed the formal References section excludes the Boolean variance seed, Catoni variance, Gaussian excursions, latent Gaussian model, and `source URL recorded in artifact` text._

- [x] 182. Related-work inspection directness is conservative
  - [x] 182.1 Stop weak variance and generic recognition papers from inflating direct-method screening
    - Remove candidate prose and demo IDs from dataset-context tokens so method words in titles or task IDs do not masquerade as benchmark overlap.
    - Require direct related-work candidates to have title-level method anchors such as prototype, centroid, nearest, metric, or Mahalanobis, or a strong method anchor plus a real handwriting/digit/recognition domain anchor.
    - Demote generic variance, calibration, or generic recognition papers to contextual statuses unless they satisfy the stricter direct-method rule.
    - Add regression coverage showing a Boolean variance seed paper is inspected but does not count as a direct method candidate.
    - Run a real default-Pendigits `serve --once` cycle and inspect related-work JSON plus the generated PDF references.
    - _References: `P-20260618-101`; user requirement that cross-search and related-work screening be broad but not inflated by irrelevant or weakly related papers._
    - _Verify: after recording an invalid pytest selector, a missing import-path rerun, and an over-specific fixture failure, focused `python -m pytest tests\unit\reports\test_related_work.py -q` passed; focused `python -m ruff check src\autoresearch\reports\related_work.py tests\unit\reports\test_related_work.py` passed; focused `python -m mypy src\autoresearch\reports\related_work.py` passed; real `node ./bin/airesearcher.mjs serve --once --permission-mode allow-all --vault runs\manual-live\task182-related-work-directness\vault --cache runs\manual-live\task182-related-work-directness\cache --output-dir runs\manual-live\task182-related-work-directness\runs --deliverables-dir outputs --state runs\manual-live\task182-related-work-directness\scheduler-state.json --approvals-state runs\manual-live\task182-related-work-directness\approvals.json --sessions-state runs\manual-live\task182-related-work-directness\sessions.json --project-id task182_related_work_directness --timeout-seconds 120 --no-push-inspiration` passed with review, publication audit, evidence gate, zero follow-ups, and PDF output; real related-work inspection reported 9 direct candidates and demoted Boolean variance/Catoni variance; `pdftotext` confirmed the weak entries and placeholder text were absent from formal References._

- [x] 183. Adjacent-work positioning is evidence-backed and PDF-safe
  - [x] 183.1 Resolve adjacent-work warning with a manuscript-bound positioning artifact
    - Generate `similarity-positioning-summary.json` and `.md` under the manuscript analysis directory from parsed project-start similarity findings.
    - Add an Adjacent-Work Positioning subsection that summarizes adjacent method families with short, source-backed counts instead of long title rows that can overflow LaTeX.
    - Let publication audit treat adjacent-work risk as passed only when the manuscript has the positioning subsection and the generated positioning artifact reports matching adjacent-work coverage.
    - Add regression coverage where adjacent-work findings occur after the first eight similarity rows so the manuscript cannot miss them due to retrieval ordering.
    - Run real default-Pendigits `serve --once` cycles and verify reviewer verdict, publication audit, evidence gate, paper quality, PDF page count, overfull boxes, and PDF text.
    - _References: `P-20260618-102`; user requirement that novelty and related-work positioning be strict, evidence-backed, PDF-ready, and not hand-waved as a warning._
    - _Verify: focused `python -m pytest tests\unit\reports\test_manuscript.py tests\unit\reports\test_publication_audit.py -q` passed; focused `python -m ruff check src\autoresearch\reports\manuscript.py src\autoresearch\reports\publication_audit.py tests\unit\reports\test_manuscript.py tests\unit\reports\test_publication_audit.py` passed; focused `python -m mypy src\autoresearch\reports\manuscript.py src\autoresearch\reports\publication_audit.py` passed; real `task183_adjacent_positioning` cycle exposed that slicing the first eight findings missed adjacent rows; real `task183_adjacent_positioning_v2` exposed reviewer concerns and one LaTeX overfull box from long title rows; final real `node ./bin/airesearcher.mjs serve --once --permission-mode allow-all --vault runs\manual-live\task183-adjacent-positioning-v3\vault --cache runs\manual-live\task183-adjacent-positioning-v3\cache --output-dir runs\manual-live\task183-adjacent-positioning-v3\runs --deliverables-dir outputs --state runs\manual-live\task183-adjacent-positioning-v3\scheduler-state.json --approvals-state runs\manual-live\task183-adjacent-positioning-v3\approvals.json --sessions-state runs\manual-live\task183-adjacent-positioning-v3\sessions.json --project-id task183_adjacent_positioning_v3 --timeout-seconds 120 --no-push-inspiration` passed with review verdict `pass`, publication audit score `1.0`, evidence gate pass, zero follow-ups, `paper_quality.passed=true`, 15-page PDF, no overfull boxes, and root output `outputs/task183_adjacent_positioning_v3/task183_adjacent_positioning_v3-cycle-20260617T222724Z.pdf`; `pdftotext` confirmed the new positioning section is present and prior placeholder/weak-reference strings are absent._

- [x] 184. Research-plan specificity and evidence-table honesty
  - [x] 184.1 Block placeholder research-plan metrics and remove unsupported readiness artifact claims
    - Infer concrete metrics and validation routes for known public benchmark candidates when metadata omits them.
    - Fail the research-plan audit when rendered plans contain placeholder terms such as `primary task metric`, `task-specific metric`, `approved public benchmark`, or `approved hold-out split`.
    - Include dataset source/target fields in the deterministic plan audit text so vague validation routes cannot pass hidden in structured fields.
    - Remove the static `Readiness report` row from the manuscript evidence availability table unless a future evidence bundle explicitly provides that artifact.
    - Run real default-Pendigits `serve --once` cycles and verify the research-plan PDF, LLM review, publication audit, evidence gate, paper quality, and PDF text.
    - _References: `P-20260618-103`; user requirement that the post-direction research plan be concrete, executable, scientifically rigorous, written to Obsidian/PDF, and that every manuscript artifact claim be backed by provided evidence._
    - _Verify: initial focused `python -m pytest tests\unit\research\test_plans.py -q` failed because stricter placeholder scanning exposed generic default robustness/risk wording; fixed by tying robustness to the inferred validation route. Focused `python -m pytest tests\unit\research\test_plans.py tests\unit\reports\test_manuscript.py -q` passed; focused `python -m ruff check src\autoresearch\research\plans.py src\autoresearch\reports\manuscript.py tests\unit\research\test_plans.py tests\unit\reports\test_manuscript.py` passed; focused `python -m mypy src\autoresearch\research\plans.py src\autoresearch\reports\manuscript.py` passed. Real `task184_research_plan_specificity` cycle produced a specific research-plan PDF but blocked with reviewer `needs_revision` because `Readiness report` was listed without evidence. Final real `node ./bin/airesearcher.mjs serve --once --permission-mode allow-all --vault runs\manual-live\task184-research-plan-specificity-v2\vault --cache runs\manual-live\task184-research-plan-specificity-v2\cache --output-dir runs\manual-live\task184-research-plan-specificity-v2\runs --deliverables-dir outputs --state runs\manual-live\task184-research-plan-specificity-v2\scheduler-state.json --approvals-state runs\manual-live\task184-research-plan-specificity-v2\approvals.json --sessions-state runs\manual-live\task184-research-plan-specificity-v2\sessions.json --project-id task184_research_plan_specificity_v2 --timeout-seconds 120 --no-push-inspiration` passed with research plan `passed`, review verdict `pass`, publication audit `pass`, evidence gate `pass`, zero follow-ups, 3-page research-plan PDF, 15-page paper PDF, and paper quality `passed=true` with zero overfull hboxes. `pdftotext` confirmed the research-plan PDF uses `classification accuracy and macro_f1` and no `primary task metric`/`approved hold-out`; the paper PDF contains `Adjacent-Work Positioning` and no `Readiness report` row._

- [x] 185. Autopilot seed evidence is method-aligned
  - [x] 185.1 Prevent unrelated or domain-only literature seeds from becoming candidate evidence
    - Select autopilot seed documents with demo-specific method anchors instead of blindly using the first retrieved paper.
    - Keep a truthful `literature_refresh:method_aligned_seed_not_found` fallback evidence marker when no method-aligned seed exists, so schema validation stays honest without fabricating a paper citation.
    - Filter that fallback marker out of generated research plans when real context evidence such as literature and similarity summaries is available.
    - Add regression tests proving a Boolean variance paper and a domain-only handwritten-digit paper cannot beat a prototype/centroid method paper for the Pendigits demo.
    - Run real default-Pendigits `serve --once` cycles and inspect candidate evidence, research-plan Markdown/PDF, review verdict, publication audit, evidence gate, and paper quality.
    - _References: `P-20260618-104`; user requirement that online retrieval and project-start cross-search summarize source-backed evidence without polluting plans with unrelated or fabricated results._
    - _Verify: focused `python -m pytest tests\unit\cli\test_main.py::test_autopilot_pendigits_demo_uses_method_aligned_search_contract tests\unit\cli\test_main.py::test_autopilot_command_runs_one_non_review_cycle tests\unit\research\test_plans.py::test_generate_research_plan_filters_unmatched_seed_marker_when_context_exists -q` passed; focused `python -m ruff check src\autoresearch\cli\main.py src\autoresearch\research\plans.py tests\unit\cli\test_main.py tests\unit\research\test_plans.py` passed; focused `python -m mypy src\autoresearch\cli\main.py src\autoresearch\research\plans.py` passed. Real `task185_aligned_seed_evidence` cycle passed all gates but exposed that domain-only handwritten-digit work could still become seed evidence. Final real `node ./bin/airesearcher.mjs serve --once --permission-mode allow-all --vault runs\manual-live\task185-aligned-seed-evidence-v2\vault --cache runs\manual-live\task185-aligned-seed-evidence-v2\cache --output-dir runs\manual-live\task185-aligned-seed-evidence-v2\runs --deliverables-dir outputs --state runs\manual-live\task185-aligned-seed-evidence-v2\scheduler-state.json --approvals-state runs\manual-live\task185-aligned-seed-evidence-v2\approvals.json --sessions-state runs\manual-live\task185-aligned-seed-evidence-v2\sessions.json --project-id task185_aligned_seed_evidence_v2 --timeout-seconds 120 --no-push-inspiration` passed with research plan `passed`, review verdict `pass`, publication audit `pass`, evidence gate `pass`, zero follow-ups, seed title `Prototype Completion for Few-Shot Learning`, 3-page research-plan PDF, 15-page paper PDF, and paper quality `passed=true` with zero overfull hboxes. `pdftotext` confirmed the research-plan PDF cites the method-aligned prototype seed and summary artifacts, with no `method_aligned_seed_not_found`, Boolean variance seed, or domain-only Bangla seed in the research-plan evidence sources._

- [x] 186. Formal bibliography requires method-direct evidence
  - [x] 186.1 Exclude domain-only handwritten-recognition papers from publication references
    - Tighten formal bibliography selection so handwritten/digit/recognition context is not sufficient by itself.
    - Require title or tag level method anchors such as prototype, centroid, nearest, Mahalanobis, metric, distance, or KNN before a domain-adjacent paper is rendered in the publication-facing References section.
    - Keep method-direct prototype, nearest-centroid, metric-recognition, and K-nearest-neighbor citations eligible.
    - Add a regression fixture where a verified handwritten Bangla MLP classifier paper is available as metadata but excluded from formal References.
    - Run a real default-Pendigits `serve --once` cycle and inspect formal-reference evidence, PDF text, PDF page counts, review verdict, publication audit, evidence gate, and paper quality.
    - _References: `P-20260618-105`; user requirement that the final PDF reference list be publication-facing, relevant, evidence-backed, and not padded with broad background literature._
    - _Verify: focused `python -m pytest tests\unit\reports\test_manuscript.py -q` passed; focused `python -m ruff check src\autoresearch\reports\manuscript.py tests\unit\reports\test_manuscript.py` passed; focused `python -m mypy src\autoresearch\reports\manuscript.py` passed. Real `node ./bin/airesearcher.mjs serve --once --permission-mode allow-all --vault runs\manual-live\task186-formal-reference-directness-v2\vault --cache runs\manual-live\task186-formal-reference-directness-v2\cache --output-dir runs\manual-live\task186-formal-reference-directness-v2\runs --deliverables-dir outputs --state runs\manual-live\task186-formal-reference-directness-v2\scheduler-state.json --approvals-state runs\manual-live\task186-formal-reference-directness-v2\approvals.json --sessions-state runs\manual-live\task186-formal-reference-directness-v2\sessions.json --project-id task186_formal_reference_directness_v2 --timeout-seconds 120 --no-push-inspiration` passed with research plan `passed`, review verdict `pass`, publication audit `pass`, evidence gate `pass`, zero follow-ups, 3-page research-plan PDF, 15-page paper PDF, `paper_quality.passed=true`, `bibliography_item_count=10`, and zero overfull hboxes. `formal-reference-evidence.md` no longer listed `wahid2022` or `basu2012`, and `pdftotext` confirmed the final PDF References preserve method-direct prototype/nearest/metric/KNN sources while omitting broad Bangla/MLP/domain-only entries._

- [x] 187. Formal reference evidence keeps full locators
  - [x] 187.1 Preserve dotted URL locators in compact reference evidence
    - Fix formal-reference locator extraction so dotted URLs such as `http://arxiv.org/abs/...` are not truncated to `http://arxiv`.
    - Keep DOI locator extraction and trailing punctuation cleanup intact.
    - Add CLI regression coverage where the manuscript reference line contains a dotted URL without the legacy DOI/URL marker.
    - Run a real default-Pendigits `serve --once` cycle and inspect `formal-reference-evidence.md`, review verdict, publication audit, evidence gate, PDF page count, and paper quality.
    - _References: `P-20260618-106`; user requirement that citation evidence and reference formatting be publication-facing and traceable._
    - _Verify: focused `python -m pytest tests\unit\cli\test_main.py::test_autopilot_command_runs_one_non_review_cycle -q` passed; focused `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; focused `python -m mypy src\autoresearch\cli\main.py` passed. Real `node ./bin/airesearcher.mjs serve --once --permission-mode allow-all --vault runs\manual-live\task187-formal-locator-integrity\vault --cache runs\manual-live\task187-formal-locator-integrity\cache --output-dir runs\manual-live\task187-formal-locator-integrity\runs --deliverables-dir outputs --state runs\manual-live\task187-formal-locator-integrity\scheduler-state.json --approvals-state runs\manual-live\task187-formal-locator-integrity\approvals.json --sessions-state runs\manual-live\task187-formal-locator-integrity\sessions.json --project-id task187_formal_locator_integrity --timeout-seconds 120 --no-push-inspiration` passed with research plan `passed`, review verdict `pass`, publication audit `pass`, evidence gate `pass`, zero follow-ups, 15-page paper PDF, `paper_quality.passed=true`, `bibliography_item_count=10`, and zero overfull hboxes. The real `formal-reference-evidence.md` now preserves full `http://arxiv.org/abs/...` manuscript locators instead of exact backtick-wrapped `http://arxiv` fragments._

- [x] 188. Formal reference evidence title cells stay readable
  - [x] 188.1 Remove locator duplication from compact title cells
    - Strip DOI and URL locator substrings from the compact `Title` field after extracting the first locator into `doi_or_url_evidence`.
    - Preserve full manuscript locators in the dedicated locator column.
    - Add regression coverage proving the displayed reference title no longer contains `https://` when the locator column carries the URL.
    - Run a real default-Pendigits `serve --once` cycle and inspect `formal-reference-evidence.md`, review verdict, publication audit, evidence gate, PDF page count, and paper quality.
    - _References: `P-20260618-107`; user requirement that citation evidence artifacts be readable and publication-facing, not only technically complete._
    - _Verify: focused `python -m pytest tests\unit\cli\test_main.py::test_autopilot_command_runs_one_non_review_cycle -q` passed; focused `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; focused `python -m mypy src\autoresearch\cli\main.py` passed. Real `node ./bin/airesearcher.mjs serve --once --permission-mode allow-all --vault runs\manual-live\task188-formal-title-cleanup\vault --cache runs\manual-live\task188-formal-title-cleanup\cache --output-dir runs\manual-live\task188-formal-title-cleanup\runs --deliverables-dir outputs --state runs\manual-live\task188-formal-title-cleanup\scheduler-state.json --approvals-state runs\manual-live\task188-formal-title-cleanup\approvals.json --sessions-state runs\manual-live\task188-formal-title-cleanup\sessions.json --project-id task188_formal_title_cleanup --timeout-seconds 120 --no-push-inspiration` passed with research plan `passed`, review verdict `pass`, publication audit `pass`, evidence gate `pass`, zero follow-ups, 15-page paper PDF, `paper_quality.passed=true`, `bibliography_item_count=10`, and zero overfull hboxes. The real `formal-reference-evidence.md` keeps full locators in `Metadata locator` and `Manuscript locator` columns while the `Title` cells no longer repeat DOI/URL strings._

- [x] 189. Strict prelaunch reports the full operator-channel recovery path
  - [x] 189.1 Add channel self-test next action when strict prelaunch has no configured channel
    - When `readiness --push-inspiration --require-channel-config --require-channel-sent` has no ready channel and no sent-delivery artifact, list both the QR setup action and the follow-up `channels test --require-sent` action.
    - Keep the readiness verdict blocked until a real channel is configured and a real sent-delivery result exists.
    - Add regression coverage for the unconfigured strict prelaunch case.
    - Rerun strict `npm run prelaunch` with the real local `.env` and confirm it blocks honestly while printing both next actions.
    - _References: `P-20260618-108`; user requirement that first deployment be guided and that WeChat/Feishu setup happen through setup without manual `.env` editing._
    - _Verify: focused readiness CLI tests passed; focused `ruff` and `mypy` passed. Real `npm run prelaunch -- --output runs/manual-live/prelaunch-readiness/strict-prelaunch-task189.json` remained blocked because no operator channel is configured and no sent-delivery self-test exists, while the report now lists both `configure_operator_channel` and `run_channel_self_test` next actions._

- [x] 190. Default configuration matches ArXiv plus OpenAlex source policy
  - [x] 190.1 Replace stale Semantic Scholar defaults in config and network allowlist
    - Change `SystemConfig` literature defaults from ArXiv plus Semantic Scholar to ArXiv plus OpenAlex.
    - Add `export.arxiv.org` and `api.openalex.org` to config-model network defaults; repair the ignored local `config.yaml` used for live readiness without force-adding it to Git.
    - Keep Semantic Scholar available as an optional source only when enabled by environment.
    - Add config and network tests for the OpenAlex default.
    - Rerun a real `literature-refresh` with default sources and confirm ArXiv/OpenAlex participate without Semantic Scholar.
    - _References: `P-20260618-109`; user requirement that Semantic Scholar be lower priority because 429s are common and that free APIs such as ArXiv/OpenAlex be default._
    - _Verify: focused config/network/default-source tests passed; focused `ruff` and `mypy` passed. Real `npm run readiness -- --no-push-inspiration --output runs/manual-live/task190-config-defaults/readiness.json` passed with the ignored local `config.yaml` parsed as `SystemConfig`. Real `node ./bin/airesearcher.mjs literature-refresh --vault runs\manual-live\task190-config-defaults\vault --cache runs\manual-live\task190-config-defaults\cache --max-queries 1 --max-results-per-source 1` fetched one ArXiv paper and one OpenAlex paper, wrote 2 documents, and did not query Semantic Scholar._

- [x] 191. Obsidian topic index stays readable for self-loop retrieval
  - [x] 191.1 Filter low-value operational keywords from the generated topic index
    - Keep raw entry keywords intact for evidence recovery and exact lookup.
    - Exclude stopword-only headings, generated run/candidate slugs, long timestamped identifiers, file-artifact names, and sentence-length reviewer notes from `autoresearch-vault/exploration/index.md`.
    - Normalize underscore-separated human keywords into readable topic headings.
    - Add regression coverage so useful topics such as `alignment`, `source-preflight`, and `similarity classification coverage` remain indexed while `adds`, `are`, `candidate_*`, `autopilot_*`, file names, and long prose do not.
    - Rebuild the real project Obsidian vault index with the project store and inspect the generated headings.
    - _References: `P-20260618-111`; user requirement that Obsidian be the self-loop/self-evolution substrate rather than an unreadable log dump._
    - _Verify: `python -m pytest tests\unit\knowledge\test_links.py tests\unit\knowledge\test_entries.py -q` passed; `python -m ruff check src\autoresearch\knowledge\entries.py tests\unit\knowledge\test_links.py` passed; `python -m mypy src\autoresearch\knowledge\entries.py` passed; real `python -c "import sys; from pathlib import Path; sys.path.insert(0, 'src'); from autoresearch.knowledge import MarkdownKnowledgeStore; MarkdownKnowledgeStore(Path('autoresearch-vault')).rebuild_indexes()"` rebuilt the vault; `Select-String` confirmed the generated topic index no longer has headings for `adds`, `are`, `candidate_*`, `autopilot_*`, file-artifact keywords, or the long nearest-centroid reviewer sentence._

- [x] 192. Vault rebuild skips system templates and avoids unchanged-entry churn
  - [x] 192.1 Protect `_system` templates from knowledge-entry rebuild side effects
    - Exclude `_system` from Markdown knowledge-entry scanning so Obsidian templates are never treated as durable knowledge records.
    - Rebuild links/backlinks in memory, but write an entry file only when its computed links or backlinks actually changed.
    - Add regression coverage proving `_system/templates/*.md` files stay byte-stable and do not contribute `template-noise` topics.
    - Rebuild the real vault with the updated store and confirm templates do not contain generated `entry_id`, `created_at`, or `updated_at` fields.
    - _References: `P-20260618-112`; user requirement that Obsidian templates/skills remain structured project assets rather than noisy self-loop records._
    - _Verify: `python -m pytest tests\unit\knowledge\test_links.py tests\unit\knowledge\test_entries.py -q` passed; `python -m ruff check src\autoresearch\knowledge\entries.py tests\unit\knowledge\test_links.py` passed; `python -m mypy src\autoresearch\knowledge\entries.py` passed; real vault rebuild succeeded; `rg -n "^entry_id:|^created_at:|^updated_at:|template-noise|entry_87cf|entry_58ebb" autoresearch-vault\_system\templates autoresearch-vault\exploration\index.md` returned no matches._

- [x] 193. Persist validated Obsidian historical memory notes
  - [x] 193.1 Commit live literature refresh and project progress memory entries
    - Keep the real online `literature_refresh_20260612` note with ArXiv/OpenAlex/Semantic Scholar circuit-breaker evidence.
    - Keep project progress entries for tasks `82.1` through `93.1` so the vault carries prior source-preflight, similarity, lifecycle, LLM-review, evidence-gate, and publication-audit lessons.
    - Validate all changed notes through `KnowledgeEntry.from_markdown()` before commit.
    - Keep line-ending-only vault status out of this content commit.
    - _References: user requirement that project data and conclusions accumulate as Markdown in the Obsidian vault._
    - _Verify: parsed 13 changed vault entries with `KnowledgeEntry.from_markdown()`, confirmed 30 source refs in the literature refresh note and related task IDs `82.1` through `93.1`; `rg` placeholder/noise scan returned no matches; `git diff --check` for the 13 vault notes passed._

- [x] 194. Repository text line endings are pinned for vault automation
  - [x] 194.1 Add `.gitattributes` and clear line-ending-only vault status
    - Add a small `.gitattributes` policy that pins common text files, especially Markdown vault files, to LF.
    - Refresh the remaining line-ending-only vault files without staging semantic content changes.
    - Confirm the only staged content is `.gitattributes` and `git status` is otherwise clean before commit.
    - _References: `P-20260618-113`; repeated CRLF warnings from automated vault writes._
    - _Verify: `git ls-files --eol` reported the checked vault files as `i/lf w/lf attr/text eol=lf`; after `git add`, `git diff --cached --stat` showed only `.gitattributes`; `git status --short` showed only `.gitattributes` staged before documentation log updates._

- [x] 195. Adjacent-work family counts are bound to generated evidence
  - [x] 195.1 Remove unsupported zero-count positioning rows from publication manuscripts
    - Add `adjacent_work_family_counts` to the generated `similarity-positioning-summary.json` artifact.
    - Render the manuscript Adjacent-Work Positioning table only from nonzero adjacent-work family counts recorded by the generated similarity-positioning artifact.
    - Prefer structured `query family overlap ...` evidence in similarity bases over broad source-query text when classifying adjacent-work families.
    - Add regression coverage proving zero-count metric/other family rows are not rendered and structured prototype overlap wins over a Mahalanobis source-query string.
    - Rerun real default-Pendigits `serve --once` cycles with live online retrieval, real UCI execution, live LLM review, publication audit, evidence gate, LaTeX build, and root `outputs/` PDF export.
    - _References: `P-20260618-114`; live LLM evidence review blocked `task195_full_cycle` because the manuscript reported adjacent-work subfamily counts that were not directly present in the evidence artifact._
    - _Verify: focused `python -m pytest tests\unit\reports\test_manuscript.py tests\unit\reports\test_publication_audit.py tests\unit\reports\test_evidence_gate.py tests\unit\reports\test_paper_build.py -q` passed with 39 tests; focused `python -m ruff check src\autoresearch\reports\manuscript.py tests\unit\reports\test_manuscript.py` passed; focused `python -m mypy src\autoresearch\reports\manuscript.py` passed. Final real `node ./bin/airesearcher.mjs serve --once --permission-mode allow-all --vault runs\manual-live\task195-full-cycle-v3\vault --cache runs\manual-live\task195-full-cycle-v3\cache --output-dir runs\manual-live\task195-full-cycle-v3\runs --deliverables-dir outputs --state runs\manual-live\task195-full-cycle-v3\scheduler-state.json --approvals-state runs\manual-live\task195-full-cycle-v3\approvals.json --sessions-state runs\manual-live\task195-full-cycle-v3\sessions.json --project-id task195_full_cycle_v3 --timeout-seconds 120 --no-push-inspiration` passed with review verdict `pass`, publication audit `pass`, evidence gate `pass`, zero follow-ups, and PDF output `outputs/task195_full_cycle_v3/task195_full_cycle_v3-cycle-20260618T002038Z.pdf`; paper quality reported 15 pages, 3957 words, one figure, three tables, ten bibliography items, and zero overfull hboxes. Broad `python -m pytest tests\smoke tests\unit -q` passed with 529 passed and 4 skipped; broad `python -m ruff check src tests` passed; broad `python -m mypy src\autoresearch` passed._

- [x] 196. First-deploy channel delivery self-test is evidence-bearing
  - [x] 196.1 Run optional setup channel self-test with fail-closed evidence
    - Add `--run-channel-test/--skip-channel-test` to `airesearcher setup` and `airesearcher deploy-setup`.
    - In guided setup, prompt users who enabled WeChat or Feishu whether to send a real delivery self-test immediately after credentials and channel settings are written.
    - Reuse the production notification path so setup validation covers the same code used by scheduled inspiration pushes.
    - Write a JSON result artifact beside the chosen `.env` path by default, preserving channel records even when delivery fails.
    - Fail closed after printing per-channel delivery evidence when `--run-channel-test` is selected and any enabled channel is not `sent`.
    - Fail before writing setup files when `--run-channel-test` is selected without any enabled channel.
    - Keep setup/channel self-test `.env` loading local to the send call so it cannot leak test credentials into process-wide notification state.
    - Keep `channels test --require-sent` behavior evidence-first by writing and printing records before exiting nonzero.
    - Add regression coverage for guided QR setup prompt flow, setup self-test success, setup self-test failure, no-channel setup rejection, `channels test` success, and `channels test` failure evidence.
    - _References: `P-20260618-115`; user requirement that WeChat/Feishu setup should test real delivery during setup instead of only printing a later command._
    - _Verify: focused `python -m pytest tests\unit\cli\test_main.py::test_setup_guided_wechat_qr_runs_qr_setup tests\unit\cli\test_main.py::test_setup_run_channel_test_writes_sent_artifact tests\unit\cli\test_main.py::test_setup_run_channel_test_fails_after_writing_artifact tests\unit\cli\test_main.py::test_setup_run_channel_test_requires_enabled_channel_before_writing tests\unit\cli\test_main.py::test_channels_test_command_sends_probe_and_writes_result tests\unit\cli\test_main.py::test_channels_test_requires_sent_when_requested -q` passed with 6 tests; `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; `python -m mypy src\autoresearch\cli\main.py` passed. Real CLI negative self-test `node .\bin\airesearcher.mjs setup --config runs\manual-live\task196-setup-channel-test\config.yaml --env-path runs\manual-live\task196-setup-channel-test\.env --provider openai-compatible --base-url https://llm.example.test/v1 --model-name research-model --api-key sk-test --no-wechat --feishu --feishu-webhook-url http://127.0.0.1:9/webhook --non-interactive --run-channel-test --channel-test-output channel-test.json --channel-test-timeout-seconds 1 --skip-obsidian --skip-integrations --skip-slash` exited 1 by design after writing `runs\manual-live\task196-setup-channel-test\channel-test.json` with a failed Feishu send record; real CLI no-channel setup `node .\bin\airesearcher.mjs setup --config runs\manual-live\task196-setup-channel-test-ok\config.yaml --env-path runs\manual-live\task196-setup-channel-test-ok\.env --provider openai-compatible --base-url https://llm.example.test/v1 --model-name research-model --api-key sk-test --no-wechat --no-feishu --non-interactive --skip-obsidian --skip-integrations --skip-slash` exited 0. CI-failure regression checks `python -m pytest tests\unit\cli\test_main.py::test_setup_run_channel_test_requires_enabled_channel_before_writing tests\unit\test_notifications.py::test_send_inspiration_digest_records_missing_webhook_without_network -q`, targeted `python -m ruff check src\autoresearch\cli\main.py src\autoresearch\notifications.py tests\unit\cli\test_main.py tests\unit\test_notifications.py`, and targeted `python -m mypy src\autoresearch\cli\main.py src\autoresearch\notifications.py` passed. Full local CI mirror `python -m pytest tests\smoke tests\unit -q` passed with 532 passed and 4 skipped; full `python -m ruff check src tests` passed; full `python -m mypy src\autoresearch` passed._

- [x] 197. V1.0 README setup guidance matches the channel self-test flow
  - [x] 197.1 Document in-wizard and scripted setup channel self-tests
    - Update the English and Chinese V1.0 scope tables so guided setup includes the optional real channel self-test.
    - Update the guided setup walkthrough to include the self-test decision after channel configuration.
    - Clarify that interactive setup can send the test immediately, while scripted deployments can use `--run-channel-test` to fail closed or `--skip-channel-test` to defer.
    - Add `--run-channel-test`, `--skip-channel-test`, and `--channel-test-output` to the setup command reference in both README files.
    - Keep the deferred `channels test --require-sent` commands documented for operators who finish QR pairing or chat binding after setup.
    - _References: task `196.1`; user requirement that setup should not look like a deferred manual checklist after choosing a channel._
    - _Verify: `git diff --check` passed; `rg -n "optional real channel self-test|--run-channel-test|--skip-channel-test|可选真实通道自检|立即发送通道送达自检|发送或延后送达自检" README.md README.zh-CN.md` found the English and Chinese setup summary, workflow, and command-reference entries._

- [x] 198. Strict readiness repair commands include setup-time delivery evidence
  - [x] 198.1 Attach channel self-test output to strict setup remediation
    - When `readiness --require-channel-sent` is blocked because no operator channel is configured, make `configure_operator_channel` invoke `airesearcher setup --wechat --wechat-qr --run-wechat-qr-setup --run-channel-test`.
    - Include the same `--channel-test-output` path used by the strict readiness report so the first deploy flow produces machine-readable delivery evidence.
    - Keep non-strict channel-configuration remediation unchanged so ordinary `--require-channel-config` does not force a delivery test.
    - Preserve the separate follow-up `channels test --require-sent` action for operators who need to retry after QR pairing or target binding.
    - Add regression coverage for strict and non-strict readiness repair command differences.
    - _References: tasks `156.1`, `158.1`, `173.1`, and `196.1`; user requirement that choosing WeChat setup should display QR and wait for scan during setup, not defer real delivery evidence to a hidden manual `.env` step._
    - _Verify: focused `python -m pytest tests\unit\cli\test_main.py::test_readiness_requires_channel_config_for_push tests\unit\cli\test_main.py::test_strict_readiness_lists_channel_setup_and_self_test_when_unconfigured tests\unit\cli\test_main.py::test_readiness_requires_sent_channel_self_test -q` passed with 3 tests; `python -m pytest tests\unit\cli\test_main.py -q` passed with 79 tests; focused `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; focused `python -m mypy src\autoresearch\cli\main.py` passed. Real CLI setup plus strict readiness probe under `runs\manual-live\task198-readiness-setup-action` exited blocked by design and printed `configure_operator_channel` with `--run-wechat-qr-setup --run-channel-test --channel-test-output runs/manual-live/task198-readiness-setup-action/channel-test.json`; broad `python -m pytest tests\smoke tests\unit -q` passed with 532 passed and 4 skipped; broad `python -m ruff check src tests` passed; broad `python -m mypy src\autoresearch` passed._

- [x] 199. Guided setup defaults to proving delivery when channels are configured
  - [x] 199.1 Make interactive setup channel self-test default to yes
    - Change the guided setup confirmation so enabled WeChat/Feishu channels default to sending the real delivery self-test.
    - Preserve explicit user control: entering `n` in the wizard or passing `--skip-channel-test` still defers the self-test.
    - Add an interactive regression test proving a Feishu webhook setup sends the self-test when the user accepts the default prompt.
    - Update English and Chinese README deployment guidance and command-reference text to say the interactive wizard defaults to sending the delivery self-test.
    - Verify the Node CLI entrypoint with a real interactive negative setup that writes channel-test evidence before failing closed on an unreachable webhook.
    - _References: tasks `196.1`, `197.1`, and `198.1`; user expectation that first deploy should be a guided, evidence-producing setup flow rather than a manual afterthought._
    - _Verify: focused `python -m pytest tests\unit\cli\test_main.py::test_setup_guided_channel_self_test_defaults_to_yes tests\unit\cli\test_main.py::test_setup_guided_wechat_qr_runs_qr_setup tests\unit\cli\test_main.py::test_setup_run_channel_test_writes_sent_artifact tests\unit\cli\test_main.py::test_setup_run_channel_test_fails_after_writing_artifact -q` passed with 4 tests; focused `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; focused `python -m mypy src\autoresearch\cli\main.py` passed. Real Node setup probe under `runs\manual-live\task199-setup-default-channel-test` accepted the default `[Y/n]` self-test prompt, attempted a real Feishu webhook send to `127.0.0.1:9`, wrote `.airesearcher/channels/test-result.json`, and exited 1 by design with a failed send record. README keyword check found the default-on self-test wording in both English and Chinese pages. Broad `python -m pytest tests\smoke tests\unit -q` passed with 533 passed and 4 skipped; broad `python -m ruff check src tests` passed; broad `python -m mypy src\autoresearch` passed; `git diff --check` passed._

- [x] 200. Operator console agent activity is current
  - [x] 200.1 Show newest Agent.md entries first in `monitor`
    - Fix the monitor Agent Messages panel so append-only `Agent.md` logs show the newest entries first.
    - Add a regression test with three Agent.md entries proving `max_entries=2` returns Task `199.1` before Task `198.1` and excludes old Task `117.1`.
    - Verify against a real release-like monitor render after a successful live cycle.
    - Record the stale-agent-panel defect in `Problem.md`.
    - _References: `P-20260618-116`; user requirement for a visible CLI UI showing current agent messages, information flow, changes, and previews during long-running operation._
    - _Verify: focused `python -m pytest tests\unit\cli\test_main.py::test_recent_agent_entries_text_shows_latest_entries_first tests\unit\cli\test_main.py::test_monitor_renders_agent_flow_changes_and_preview -q` passed with 2 tests; focused `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; focused `python -m mypy src\autoresearch\cli\main.py` passed. Real monitor over `runs\manual-live\task200-post-setup-cycle\runs\cycle-20260618T011001Z\cycle-summary.json` with `--max-agent-entries 2` rendered Task `199.1` and Task `198.1` instead of old Task `187.1` and `186.1`. Broad `python -m pytest tests\smoke tests\unit -q` passed with 534 passed and 4 skipped; broad `python -m ruff check src tests` passed; broad `python -m mypy src\autoresearch` passed; `git diff --check` passed._

- [x] 201. Operator console agent messages are actionable
  - [x] 201.1 Include compact detail bullets in the `monitor` Agent Messages panel
    - Extend the monitor Agent Messages panel beyond bare section headers so operators can see the first concrete Summary, Verification, Problems, and Follow-up bullet from each recent `Agent.md` entry.
    - Keep newest-first ordering from task `200.1`.
    - Truncate long detail lines so command-heavy verification evidence cannot overflow the console layout.
    - Add regression coverage proving recent entries include their first detail bullet while old entries remain excluded.
    - Verify against a real monitor render from the latest successful full-cycle run.
    - _References: task `200.1`; user requirement for a good-looking CLI that shows agent messages, information flow, changed content, and preview results during autonomous operation._
    - _Verify: focused `python -m pytest tests\unit\cli\test_main.py::test_recent_agent_entries_text_shows_latest_entries_first tests\unit\cli\test_main.py::test_monitor_renders_agent_flow_changes_and_preview -q` passed with 2 tests; focused `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; focused `python -m mypy src\autoresearch\cli\main.py` passed. Real monitor over `runs\manual-live\task200-post-setup-cycle\runs\cycle-20260618T011001Z\cycle-summary.json` with `--max-agent-entries 1` rendered the latest Agent entry with Summary, Verification, Problems, and Follow-up detail bullets and truncated long command lines. Broad `python -m pytest tests\smoke tests\unit -q` passed with 534 passed and 4 skipped; broad `python -m ruff check src tests` passed; broad `python -m mypy src\autoresearch` passed; `git diff --check` passed._

- [x] 202. Channel self-test failures are actionable during setup
  - [x] 202.1 Print bind-target next actions for missing channel delivery targets
    - When `channels test --require-sent` or setup-time `--run-channel-test` fails because WeChat QR lacks `AUTORESEARCH_WECHAT_OPENCLAW_TARGET`, print the exact `airesearcher channels bind-target --channel wechat --env-path ...` repair command.
    - When the same path fails because Feishu App mode lacks `AUTORESEARCH_FEISHU_HOME_CHAT_ID`, print the matching `airesearcher channels bind-target --channel feishu --env-path ...` command.
    - Keep fail-closed self-test behavior and JSON evidence writing unchanged.
    - Update README setup guidance in English and Chinese so operators know missing targets are repaired through CLI, not manual `.env` edits.
    - Add regression coverage for WeChat and Feishu missing-target next actions.
    - _References: tasks `196.1`, `198.1`, and `199.1`; user requirement that setup be a guided deployment flow instead of hidden manual `.env` work._
    - _Verify: focused `python -m pytest tests\unit\cli\test_main.py::test_channels_test_requires_sent_when_requested tests\unit\cli\test_main.py::test_setup_channel_test_missing_feishu_home_chat_prints_bind_next_action -q` passed with 2 tests; focused `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; focused `python -m mypy src\autoresearch\cli\main.py` passed. Real Node setup probe under `runs\manual-live\task202-channel-next-actions` wrote channel-test evidence, exited 1 by design for missing Feishu home chat, and printed `bind_feishu_target`. Broad `python -m pytest tests\smoke tests\unit -q` passed with 535 passed and 4 skipped; broad `python -m ruff check src tests` passed; broad `python -m mypy src\autoresearch` passed; `git diff --check` passed._

- [x] 203. Readiness channel configuration matches real delivery requirements
  - [x] 203.1 Require Feishu home chat before marking App-mode delivery ready
    - Change `readiness` so Feishu App ID/App Secret alone are not treated as a ready push channel.
    - Add `feishu_home_chat_configured` evidence to the operator-channel readiness report.
    - When Feishu App credentials are present but home chat is missing, emit `bind_feishu_target` before `run_channel_self_test`.
    - Keep webhook-mode Feishu readiness unchanged.
    - Add regression coverage for Feishu App mode without `AUTORESEARCH_FEISHU_HOME_CHAT_ID`.
    - Record the resolved mismatch in `Problem.md`.
    - _References: `P-20260618-117`; tasks `196.1`, `198.1`, `199.1`, and `202.1`; user requirement that setup/readiness be a guided deploy flow and not push hidden `.env` work onto the operator._
    - _Verify: focused `python -m pytest tests\unit\cli\test_main.py::test_readiness_requires_sent_channel_self_test tests\unit\cli\test_main.py::test_readiness_requires_feishu_home_chat_for_app_gateway tests\unit\cli\test_main.py::test_readiness_command_writes_daily_loop_report -q` passed with 3 tests; focused `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; focused `python -m mypy src\autoresearch\cli\main.py` passed. Real Node readiness probe under `runs\manual-live\task203-feishu-readiness` blocked on missing Feishu home chat and missing sent evidence, with next actions `bind_feishu_target` then `run_channel_self_test`. Broad `python -m pytest tests\smoke tests\unit -q` passed with 536 passed and 4 skipped; broad `python -m ruff check src tests` passed; broad `python -m mypy src\autoresearch` passed; `git diff --check` passed._

- [x] 204. Generated Obsidian vault copy uses current project name
  - [x] 204.1 Align generated vault index wording with AI-Researcher
    - Change the first-run exploration and project index copy from old `AutoResearch` wording to `AI-Researcher`.
    - Add regression coverage that reads the generated index Markdown files and asserts the current project name appears.
    - Verify through the real Node `obsidian-setup` CLI entrypoint, not only direct unit calls.
    - Record the stale-name defect and the stale CLI flag verification miss in `Problem.md`.
    - _References: `P-20260618-118`; user requirement to rename product-facing project text to AI-Researcher while preserving the canonical `autoresearch-vault/` knowledge path._
    - _Verify: focused `python -m pytest tests\unit\knowledge\test_vault.py -q` passed with 6 tests; focused `python -m ruff check src\autoresearch\knowledge\vault.py tests\unit\knowledge\test_vault.py` passed; focused `python -m mypy src\autoresearch\knowledge\vault.py` passed. Initial real CLI probe with stale `--local-snippet` failed and was recorded; corrected real `node .\bin\airesearcher.mjs obsidian-setup --vault runs\manual-live\task204-vault-naming\autoresearch-vault --project-id project-001 --write-local-snippet` passed. Generated `exploration/index.md` and `projects/project-001/index.md` contain `AI-Researcher`, and `rg -n "knowledge index for AutoResearch" runs\manual-live\task204-vault-naming\autoresearch-vault` returned no matches. Broad `python -m pytest tests\smoke tests\unit -q` passed with 536 passed and 4 skipped; broad `python -m ruff check src tests` passed; broad `python -m mypy src\autoresearch` passed; `git diff --check` passed._

- [x] 205. Source package prose uses current project name
  - [x] 205.1 Align source docstrings with AI-Researcher naming
    - Update explanatory module/class/function docstrings that describe this project as `AutoResearch`.
    - Preserve Python package/module names, logger namespaces, command names, external project references, and historical planning file names.
    - Verify that `src/autoresearch` no longer contains stale `AutoResearch` product prose.
    - _References: `P-20260618-119`; user requirement to use AI-Researcher as the project name while keeping compatibility names where needed._
    - _Verify: `rg -n "AutoResearch" src\autoresearch` returned no matches; focused `python -m ruff check src\autoresearch\cli\__init__.py src\autoresearch\config\models.py src\autoresearch\config\parser.py src\autoresearch\observability\logging.py src\autoresearch\schemas\__init__.py src\autoresearch\schemas\models.py` passed; focused `python -m mypy src\autoresearch\config\models.py src\autoresearch\config\parser.py src\autoresearch\observability\logging.py src\autoresearch\schemas\models.py` passed. Broad `python -m pytest tests\smoke tests\unit -q` passed with 536 passed and 4 skipped; broad `python -m ruff check src tests` passed; broad `python -m mypy src\autoresearch` passed; `git diff --check` passed._

- [x] 206. Executor security preflight is fail-closed
  - [x] 206.1 Block dangerous static findings at executor entry
    - Reuse generated-code static review inside `execute_experiment_task()`.
    - Fail closed on `dangerous_command`, `path_traversal`, and `secret_read` findings before launching the local subprocess.
    - Preserve the existing approved-network path for `unrestricted_network` findings.
    - Record structured `static_preflight` metadata when blocking execution.
    - Add regression tests proving dangerous subprocess/curl and secret-read code cannot write `metrics.json`.
    - _References: `P-20260618-120`; `P-20260611-014`; user requirement for real evidence gates and physical execution guardrails rather than relying on prompt self-discipline._
    - _Verify: focused `python -m pytest tests\unit\experiments\test_executor.py tests\unit\experiments\test_review.py tests\unit\experiments\test_network.py -q` passed with 25 tests; focused `python -m ruff check src\autoresearch\experiments\executor.py tests\unit\experiments\test_executor.py` passed; focused `python -m mypy src\autoresearch\experiments\executor.py` passed. Broad `python -m pytest tests\smoke tests\unit -q` passed with 538 passed and 4 skipped; broad `python -m ruff check src tests` passed; broad `python -m mypy src\autoresearch` passed; `git diff --check` passed._

- [x] 207. Static review detects dynamic import bypasses
  - [x] 207.1 Flag dynamic imports of network and command modules
    - Detect `__import__()` and `importlib.import_module()` when they target known network modules or command-execution modules.
    - Classify dynamic network imports as `unrestricted_network` so the executor's existing approval gate blocks them unless approved.
    - Classify dynamic command-execution imports as `dangerous_command` so the executor's static preflight blocks them unconditionally.
    - Add static review tests for dynamic `socket` and `subprocess` imports.
    - Add executor coverage proving dynamic network imports cannot write `metrics.json` without approval.
    - _References: `P-20260618-121`; `P-20260611-014`; user requirement to harden execution gates against AI-generated workarounds rather than trusting prompt discipline._
    - _Verify: focused `python -m pytest tests\unit\experiments\test_review.py tests\unit\experiments\test_executor.py -q` passed with 18 tests; focused `python -m ruff check src\autoresearch\experiments\review.py tests\unit\experiments\test_review.py tests\unit\experiments\test_executor.py` passed; focused `python -m mypy src\autoresearch\experiments\review.py src\autoresearch\experiments\executor.py` passed. Broad `python -m pytest tests\smoke tests\unit -q` passed with 541 passed and 4 skipped; broad `python -m ruff check src tests` passed; broad `python -m mypy src\autoresearch` passed; `git diff --check` passed._

- [x] 208. Static review catches PowerShell web command markers
  - [x] 208.1 Flag PowerShell web request commands
    - Add PowerShell `Invoke-WebRequest` and `Invoke-RestMethod` markers to generated-code string-literal review.
    - Classify those command strings as `dangerous_command`, matching existing `curl` and `wget` treatment.
    - Add regression coverage for a generated-code PowerShell web request command string.
    - Keep `P-20260611-014` mitigated rather than resolved because this is a static executor gate, not OS/container/proxy-level network interception.
    - _References: `P-20260618-122`; `P-20260611-014`; user requirement for real execution guardrails and dangerous-operation gates._
    - _Verify: focused `python -m pytest tests\unit\experiments\test_review.py -q` passed with 10 tests; focused `python -m ruff check src\autoresearch\experiments\review.py tests\unit\experiments\test_review.py` passed; focused `python -m mypy src\autoresearch\experiments\review.py` passed. Broad `python -m pytest tests\smoke tests\unit -q` passed with 542 passed and 4 skipped; broad `python -m ruff check src tests` passed; broad `python -m mypy src\autoresearch` passed; `git diff --check` passed._

- [x] 209. Static review catches Windows downloader aliases
  - [x] 209.1 Flag PowerShell aliases, `curl.exe`, BITS, and .NET downloader strings
    - Add bounded generated-code command patterns for PowerShell aliases `iwr` and `irm`, `curl.exe`, `wget.exe`, `Start-BitsTransfer`, and .NET `WebClient` downloader calls.
    - Keep these string patterns classified as `dangerous_command` so executor preflight blocks them before local subprocess launch.
    - Add regression coverage for `iwr`, `curl.exe`, `Start-BitsTransfer`, and `System.Net.WebClient.DownloadFile`.
    - Keep the change scoped to static review; OS/container/proxy enforcement remains tracked by `P-20260611-014`.
    - _References: `P-20260618-123`; `P-20260611-014`; user requirement for hard execution guardrails rather than prompt-only safety._
    - _Verify: focused `python -m pytest tests\unit\experiments\test_review.py -q` passed with 14 tests; focused `python -m ruff check src\autoresearch\experiments\review.py tests\unit\experiments\test_review.py` passed; focused `python -m mypy src\autoresearch\experiments\review.py` passed. Broad `python -m pytest tests\smoke tests\unit -q` passed with 546 passed and 4 skipped; broad `python -m ruff check src tests` passed; broad `python -m mypy src\autoresearch` passed; `git diff --check` passed._

- [x] 210. Network sandbox mitigation trail is current
  - [x] 210.1 Refresh `P-20260611-014` with executor/static-review mitigations
    - Update the OS-level network sandbox problem entry so it records tasks `206.1` through `209.1` as mitigation, not resolution.
    - Keep the distinction clear: executor/static-review gates are useful physical gates, but they are not OS/container/proxy-level network interception.
    - Record the real post-hardening `serve --once` cycle as verification that the normal research loop still runs after the static-review hardening.
    - _References: `P-20260611-014`; tasks `206.1`, `207.1`, `208.1`, `209.1`; user requirement for evidence-backed safety gates and accurate project memory._
    - _Verify: `rg -n "206\\.1|207\\.1|208\\.1|209\\.1|Windows downloader aliases|OS-level enforcement|post-hardening" Problem.md .kiro\specs\auto-research-system\tasks.md Agent.md` confirmed the updated mitigation trail; `git diff --check` passed._

- [x] 211. Root Obsidian vault defaults use current project ID
  - [x] 211.1 Point checked-in vault homepage, dashboard, and templates at `ai_researcher_system`
    - Update `autoresearch-vault/Home.md`, `_system/dashboards/research-loop.md`, and `_system/templates/*` defaults that still route operators to `projects/autoresearch-system`.
    - Add a lightweight `projects/ai_researcher_system/index.md` so the default homepage link resolves to the current project area.
    - Leave historical `projects/autoresearch-system` records untouched.
    - _References: `P-20260618-124`; user requirement that Obsidian is the unified memory substrate for the AI-Researcher self-loop._
    - _Verify: `rg -n "projects/autoresearch-system|project_id: autoresearch-system|--project-id autoresearch-system" autoresearch-vault\Home.md autoresearch-vault\_system` returned no matches; `Test-Path autoresearch-vault\projects\ai_researcher_system\index.md` returned true; `git diff --check` passed._

- [x] 212. Meta-Harness harness-search reference quarantine
  - [x] 212.1 Add Meta-Harness as a controlled self-evolution reference
    - Live-check `stanford-iris-lab/meta-harness`, its license, README, onboarding prompt, and paper before documenting it.
    - Treat Meta-Harness as a MIT design reference only: do not copy, vendor, adapt, install, or redistribute upstream code, prompts, proposer wrappers, reference experiments, assets, benchmark data, or generated harnesses.
    - Add a quarantined Obsidian watchlist candidate for harness-search ideas: domain-spec-first onboarding, fixed base model/tool boundary, candidate source/scores/traces archive, proposer interaction logs, search/held-out split, anti-leakage review, and Pareto-aware promotion.
    - Update README, Chinese README, changelog, third-party notices, compliance tests, and skill-watchlist tests so future agents preserve the reference-only boundary.
    - Record the risk that uncontrolled harness search can become self-modifying production policy without held-out validation, and resolve it with shadow evaluation, evidence gates, and rollback requirements.
    - _References: user request to learn from `meta-harness`; Phase 4 controlled self-evolution; `P-20260619-001`._
    - _Verify: Live web review checked `https://github.com/stanford-iris-lab/meta-harness`, raw `LICENSE`, raw `ONBOARDING.md`, raw `README.md`, and arXiv `2603.28052`; upstream is MIT and frames Meta-Harness as fixed-base-model harness-code search with candidate source, scores, and traces, plus onboarding rules for domain spec, evaluation split, trace logging, and leakage caution. Focused `python -m pytest tests\unit\knowledge\test_skills.py tests\unit\compliance\test_licenses.py -q` passed with 18 tests; focused `python -m ruff check src\autoresearch\knowledge\skills.py tests\unit\knowledge\test_skills.py tests\unit\compliance\test_licenses.py` passed; focused `python -m mypy src\autoresearch\knowledge\skills.py` passed. Real CLI `node .\bin\airesearcher.mjs skill-watchlist --vault runs\manual-live\task212-meta-harness-watchlist-vault --source-note "2026-06-19 Meta-Harness reference smoke"` passed and wrote 15 quarantined candidates; `rg` confirmed the generated watchlist contains `Meta-Harness`, `harness-search-reference`, `domain_spec-style`, `trace archive`, and held-out leakage gates. Broad `python -m pytest tests\smoke tests\unit -q` passed with 546 passed and 4 skipped; broad `python -m ruff check src tests` passed; broad `python -m mypy src\autoresearch` passed; `git diff --check` passed._

- [x] 213. LightAgent lightweight runtime reference quarantine
  - [x] 213.1 Add LightAgent/LightFlow as a trace-safe orchestration reference
    - Live-check `wanxingai/LightAgent`, its license, README, LightFlow docs, trace docs, memory/trace/swarm boundary docs, and multi-agent failure map before documenting it.
    - Treat LightAgent as an Apache-2.0 design reference only: do not copy, vendor, adapt, install, or redistribute upstream source, docs text, examples, images, prompts, generated traces, memory adapters, browser-use integration code, MCP integration code, or assets.
    - Add a quarantined Obsidian watchlist candidate for lightweight orchestration ideas: explicit DAG dependencies, step-local retries, opt-in trace events, prompt-safe model request summaries, memory provenance filters, trace/reflection/delegation scoping, and multi-agent failure diagnostics.
    - Update README, Chinese README, changelog, third-party notices, compliance tests, and skill-watchlist tests so future agents preserve the no-dependency/no-vendor boundary.
    - Record the risk that self-learning memory and trace logs can pollute project memory if user, trace, reflection, and delegation scopes are mixed; resolve it with provenance filters and evidence-safe vault summaries.
    - _References: user request to learn from `Light`; Phase 2 multi-agent workflow; Phase 3 Obsidian memory; Phase 4 controlled evolution; `P-20260620-001`._
    - _Verify: Live web review checked `https://github.com/wanxingai/LightAgent`, raw `LICENSE`, raw `README.md`, raw `docs/lightflow.md`, raw `docs/tracing.md`, raw `docs/memory_trace_swarm_boundaries.md`, and raw `docs/multi_agent_failure_map.md`; upstream is Apache-2.0 and frames LightAgent as a lightweight Skills/MCP/memory/multi-agent framework with LightFlow DAG steps, opt-in trace events, memory/trace/delegation scope guidance, and multi-agent failure diagnostics. Focused `python -m pytest tests\unit\knowledge\test_skills.py tests\unit\compliance\test_licenses.py -q` passed with 18 tests; focused `python -m ruff check src\autoresearch\knowledge\skills.py tests\unit\knowledge\test_skills.py tests\unit\compliance\test_licenses.py` passed; focused `python -m mypy src\autoresearch\knowledge\skills.py` passed. Real CLI `node .\bin\airesearcher.mjs skill-watchlist --vault runs\manual-live\task213-lightagent-watchlist-vault --source-note "2026-06-20 LightAgent reference smoke"` passed and wrote 16 quarantined candidates; `rg` confirmed the generated watchlist contains `LightAgent / LightFlow`, `lightweight-agent-runtime-reference`, trace observability, memory/trace/delegation boundaries, shared-memory pollution checks, and evidence-safe summaries. Broad `python -m pytest tests\smoke tests\unit -q` passed with 546 passed and 4 skipped; broad `python -m ruff check src tests` passed; broad `python -m mypy src\autoresearch` passed; `git diff --check` passed._

- [x] 214. Loop Engineering closed-loop campaign layer
  - [x] 214.1 Add campaign schema, optimizer, metrics, and release gates
    - Add a `ClosedLoopCampaign` protocol-as-code model covering research objective, measurable metrics, budget, data sources, candidate space, baselines, stop criteria, approval policy, and evidence requirements.
    - Add first-round DOE/grid selection and later-round evidence-gain/repair selection so LLM output can propose context but cannot bypass budget, failure, evidence, or reproduction gates.
    - Add loop metrics for acceleration factor, effect improvement factor, metadata completeness, reproduction delta, failure recovery rate, evidence coverage, experiment count, and reward.
    - Classify closed-loop failures into `source`, `protocol`, `execution`, `metric`, `validation`, `review`, `cost`, and `safety`, and freeze high-risk variables after consecutive failures instead of blind retry.
    - Write structured `loop-campaign.json`, `loop-report.md`, and an Obsidian project-progress note for each campaign artifact.
    - Wire the loop layer into `autopilot`/`serve` after the research-plan gate and before experiment execution, then surface loop status in CLI output and review evidence.
    - Require loop campaign artifacts and passing loop metrics in evidence gate, publication audit, and strategy promotion decisions.
    - Update README/README.zh-CN so users see AI-Researcher as an evidence-first closed-loop research system rather than an open-world paper-writing chatbot.
    - _References: user-provided "AI-Researcher Loop Engineering Evolution Plan"; Kiro Obsidian-first self-loop direction; project requirement that unsupported conclusions must not enter paper drafts._
    - _Verify: focused `python -m pytest tests\unit\experiments\test_loop.py tests\unit\experiments\test_promotion.py tests\unit\reports\test_evidence_gate.py tests\unit\reports\test_publication_audit.py tests\unit\cli\test_main.py::test_autopilot_research_plan_gate_blocks_before_experiment -q` passed with 42 tests; focused `python -m ruff check src\autoresearch\experiments\loop.py src\autoresearch\experiments\promotion.py src\autoresearch\reports\evidence_gate.py src\autoresearch\reports\publication_audit.py src\autoresearch\cli\main.py tests\unit\experiments\test_loop.py tests\unit\experiments\test_promotion.py tests\unit\reports\test_evidence_gate.py tests\unit\reports\test_publication_audit.py` passed; focused `python -m mypy src\autoresearch\experiments\loop.py src\autoresearch\experiments\promotion.py src\autoresearch\reports\evidence_gate.py src\autoresearch\reports\publication_audit.py src\autoresearch\cli\main.py` passed. Real isolated CLI `node .\bin\airesearcher.mjs autopilot --env-path .env --vault runs\manual-live\task214-loop\vault --cache runs\manual-live\task214-loop\cache --output-dir runs\manual-live\task214-loop\runs --deliverables-dir runs\manual-live\task214-loop\outputs --state runs\manual-live\task214-loop\scheduler.json --sessions-state runs\manual-live\task214-loop\sessions.json --project-id task214-loop-smoke --demo tabular_baseline --max-queries 1 --max-results-per-source 1 --timeout-seconds 30 --cycles 1 --no-push-inspiration` completed `cycle-20260623T050627Z`, wrote loop campaign/report/vault note/PDF artifacts, passed `loop_campaign_gate`, and correctly blocked release because publication audit and evidence gate found toy-data and literature-breadth gaps. Broad `python -m pytest tests\smoke tests\unit -q` passed with 556 passed and 4 skipped; broad `python -m ruff check src tests` passed; broad `python -m mypy src\autoresearch` passed._

- [x] 215. Per-agent custom skill and MCP profiles
  - [x] 215.1 Bind custom skills and MCP tool allowlists to one named agent
    - Add an `AgentProfile` model that binds custom skills and MCP servers to one `agent_id` and `AgentRole`.
    - Preserve research-first behavior with a default scientific thinking contract: questions, hypotheses, data, baselines, falsification, evidence, and publication gates come before engineering abstractions.
    - Require MCP servers to declare explicit allowed tools and environment variable names instead of storing secret values or implicit full access.
    - Allow the runtime `BaseAgent` and `AgentRegistry` to attach a validated profile and expose safe runtime context for structured agent messages.
    - Add `airesearcher agents profile write` and `airesearcher agents profile inspect` plus `/research:agent-profile` slash template support.
    - Write optional Obsidian profile notes under `autoresearch-vault/projects/<project-id>/agents/` so agent-specific skill/MCP imports remain visible in project memory.
    - Update README/README.zh-CN with per-agent custom skill/MCP usage and safety boundaries.
    - _References: user request to add custom skills and MCP import ability for a specific Agent while keeping the system focused on publishable scientific output rather than over-engineered AI behavior._
    - _Verify: focused `python -m pytest tests\unit\agents\test_profiles.py tests\unit\agents\test_agent_imports.py tests\unit\cli\test_main.py::test_agent_profile_write_and_inspect_cli tests\unit\cli\test_main.py::test_agent_profile_write_cli_rejects_mcp_without_tools tests\unit\cli\test_main.py::test_slash_commands_init_and_list_project_templates -q` passed with 8 tests; focused `python -m mypy src\autoresearch\agents src\autoresearch\cli\main.py` passed; focused ruff initially failed on import ordering in `src\autoresearch\cli\main.py`, then `python -m ruff check src\autoresearch\cli\main.py --fix` fixed it. Real CLI `node .\bin\airesearcher.mjs agents profile write --agent-id literature-agent --role project_agent --skill source-tracing=autoresearch-vault/_system/templates/skill-card.md --mcp "obsidian=npx -y obsidian-mcp --vault autoresearch-vault" --mcp-tool obsidian:search_notes --mcp-tool obsidian:read_note --vault runs\manual-live\task215-agent-profile\vault --project-id task215-agent-profile --output runs\manual-live\task215-agent-profile\profiles\literature-agent.json` passed and wrote profile JSON plus vault note; real CLI `node .\bin\airesearcher.mjs agents profile inspect runs\manual-live\task215-agent-profile\profiles\literature-agent.json` returned the scientific thinking contract, skill binding, and MCP allowlist. Broad `python -m pytest tests\smoke tests\unit -q` passed with 562 passed and 4 skipped; broad `python -m ruff check src tests` passed; broad `python -m mypy src\autoresearch` passed._

- [x] 216. Runtime agent profile loading
  - [x] 216.1 Load per-agent skill/MCP profiles into `serve`, `autopilot`, review evidence, and monitor
    - Add repeatable `--agent-profile <json>` flags to `serve` and `autopilot`.
    - Validate and deduplicate profile files at cycle start before online retrieval or experiment execution.
    - Write loaded profile summaries and safe runtime contexts into every `cycle-summary.json`, including blocked preflight and blocked research-plan branches.
    - Include agent profile context in `review-evidence-context.json` and the review evidence path bundle so reviewer/audit stages can inspect which skill/MCP context was available.
    - Print loaded agent IDs in CLI status output without implying that profile context is publication evidence.
    - Render an Agent Profiles panel in `airesearcher monitor` with agent ID, role, skill IDs, and MCP tool allowlists.
    - Update README/README.zh-CN so operators know how to create and attach profile JSON files to long-running cycles.
    - _References: task `215.1`; user request that custom skills and MCP imports can be assigned to a specific Agent and remain visible while the system keeps scientific evidence gates._
    - _Verify: focused `python -m pytest tests\unit\cli\test_main.py::test_autopilot_command_runs_one_non_review_cycle tests\unit\cli\test_main.py::test_monitor_renders_agent_flow_changes_and_preview -q` passed; focused `python -m ruff check src\autoresearch\cli\main.py tests\unit\cli\test_main.py` passed; focused `python -m mypy src\autoresearch\cli\main.py` passed; broad and live verification recorded in `Agent.md`._

- [x] 217. Loop-stage agent responsibility mapping
  - [x] 217.1 Bind agent profiles to closed-loop research stages
    - Add optional `assigned_stages` to `AgentProfile`, normalized to snake_case and serialized into runtime context.
    - Add repeatable `--stage` to `airesearcher agents profile write`, with a fixed allowlist matching the release-critical loop stages.
    - Reject unknown or duplicate stage assignments before a profile can be loaded into `serve` or `autopilot`.
    - Include `stage_assignments` in `cycle-summary.json` and `review-evidence-context.json` so review/audit stages can inspect responsibility boundaries.
    - Render profile role plus assigned stages in `airesearcher monitor` without treating stage context as publication evidence.
    - Update README/README.zh-CN usage docs with `--stage` examples and safety language.
    - _References: tasks `214.1`, `215.1`, and `216.1`; Loop Engineering requirement that closed-loop stages are auditable and cannot be bypassed by prompt-only agent behavior._
    - _Verify: focused `python -m pytest tests\unit\agents\test_profiles.py tests\unit\cli\test_main.py::test_agent_profile_write_and_inspect_cli tests\unit\cli\test_main.py::test_agent_profile_write_cli_rejects_unknown_stage tests\unit\cli\test_main.py::test_autopilot_command_runs_one_non_review_cycle tests\unit\cli\test_main.py::test_monitor_renders_agent_flow_changes_and_preview -q` passed with 8 tests; focused `python -m ruff check src\autoresearch\agents\profiles.py src\autoresearch\cli\main.py tests\unit\agents\test_profiles.py tests\unit\cli\test_main.py` passed; focused `python -m mypy src\autoresearch\agents src\autoresearch\cli\main.py` passed. Loop regression `python -m pytest tests\unit\experiments\test_loop.py tests\unit\experiments\test_promotion.py tests\unit\reports\test_evidence_gate.py tests\unit\reports\test_publication_audit.py tests\unit\cli\test_main.py::test_autopilot_research_plan_gate_blocks_before_experiment -q` passed with 42 tests; broad `python -m pytest tests\smoke tests\unit -q` passed with 563 passed and 4 skipped; broad `python -m ruff check src tests` passed; broad `python -m mypy src\autoresearch` passed; `git diff --check` passed. Real CLI wrote a staged profile with `--stage literature --stage similarity --stage review`, ran `autopilot` once with that profile, confirmed `[OK] agent_profiles: 1; agents=literature-agent; assigned_stages=3`, confirmed summary/review context include `stage_assignments`, and `monitor` rendered `project_agent; literature,similarity,review`._

- [x] 218. Stage-scoped agent context consumption
  - [x] 218.1 Expose bounded runtime contexts per loop stage
    - Add reusable helpers that normalize loop stage names and filter loaded agent runtime contexts by assigned stage.
    - Include `stage_runtime_contexts` in `cycle-summary.json`, keyed by loop stage, so downstream stage workers can consume only the skill/MCP context assigned to that stage.
    - Include `stage_agent_contexts` in `review-evidence-context.json` so review and audit can inspect the stage-scoped context without re-deriving it from display rows.
    - Keep stage contexts bounded to profile runtime context and do not treat them as publication evidence or approval to bypass gates.
    - Update README/README.zh-CN with the runtime artifact fields and safety boundary.
    - _References: tasks `214.1`, `215.1`, `216.1`, and `217.1`; Loop Engineering requirement that LLM and tool use stay inside auditable stage responsibilities._
    - _Verify: focused profile and CLI tests passed; loop regression, broad smoke/unit, ruff, mypy, real staged-profile autopilot smoke, and `git diff --check` passed. Full commands and real artifact checks are recorded in `Agent.md`._

- [x] 219. LLM reviewer profile-context boundary
  - [x] 219.1 Prevent stage profiles from being treated as scientific evidence
    - Clarify the evidence-constrained LLM reviewer prompt that `agent_profiles`, `stage_runtime_contexts`, `stage_agent_contexts`, skills, and MCP allowlists are process metadata only.
    - Allow profile context to support findings about responsibility boundaries or available tool context, but not scientific results, novelty, benchmark metrics, citation validity, publication readiness, or proof that a tool was invoked.
    - Apply the same boundary to repair prompts so failed-review retries cannot promote profile metadata into scientific evidence.
    - Add unit coverage that fixes the prompt contract for stage-scoped profile context.
    - Update README/README.zh-CN so operators know profile context is reviewable process metadata, not a publication claim shortcut.
    - _References: tasks `216.1`, `217.1`, and `218.1`; Loop Engineering requirement that evidence gates cannot be bypassed by agent/tool declarations._
    - _Verify: focused LLM reviewer prompt tests, ruff, mypy, broad smoke/unit tests, and `git diff --check` passed. Full commands are recorded in `Agent.md`._

- [x] 220. Deterministic reviewer profile-context misuse gate
  - [x] 220.1 Block reviewer outputs that use profiles as scientific evidence
    - Add a local LLM-review quality check named `profile_context_not_used_as_scientific_evidence`.
    - Fail review outputs that combine profile/stage/skill/MCP context with proof language for scientific results, novelty, benchmark metrics, citations, publication readiness, or tool invocation.
    - Keep legitimate process findings about responsibility boundaries and available tool context passing.
    - Make the new check critical so bad outputs trigger repair or fail closed.
    - Update README/README.zh-CN to describe the deterministic gate, not only the prompt instruction.
    - _References: task `219.1`; user requirement to rely on evidence gates instead of prompt-only self-discipline._
    - _Verify: focused LLM-review quality tests, ruff, mypy, broad smoke/unit tests, and `git diff --check` passed. Full commands are recorded in `Agent.md`._

- [x] 221. Machine-readable Agent profile evidence policy
  - [x] 221.1 Tag runtime profile contexts as process metadata
    - Add `context_kind=agent_profile_process_metadata` to every safe Agent profile runtime context.
    - Add a machine-readable `evidence_policy` listing what profile context can support and what it cannot support.
    - Ensure stage-scoped contexts in `cycle-summary.json` and `review-evidence-context.json` carry the same policy.
    - Keep the policy narrowly focused on evidence boundaries instead of adding a new orchestration abstraction.
    - Update README/README.zh-CN to document the runtime field for downstream stage workers.
    - _References: tasks `218.1`, `219.1`, and `220.1`; user requirement that custom skills/MCP can be assigned to Agents without weakening research evidence gates._
    - _Verify: focused profile and CLI artifact tests, ruff, mypy, broad smoke/unit tests, and `git diff --check` passed. Full commands are recorded in `Agent.md`._

- [x] 222. Protocol-as-code stop decisions
  - [x] 222.1 Add explicit campaign protocol fields and stop criteria
    - Add first-class `data_sources`, `baselines`, and `protocol_artifacts` fields to `ClosedLoopCampaign` so the campaign JSON exposes the protocol-as-code inputs named in the Loop Engineering plan.
    - Add a deterministic `LoopStopDecision` with stop reasons for budget exhaustion, target reached, metadata gaps, evidence gaps, reproduction regression, consecutive failures, and human approval requirements.
    - Write `stop_decision` into `loop-campaign.json`, `cycle-summary.json`, and `loop-report.md`.
    - Block blind retry after repeated same-category failures unless a repair hypothesis or frozen dimension is recorded.
    - Update README/README.zh-CN, `Agent.md`, and `Problem.md` so loop failures, evidence gaps, metadata gaps, reproduction gaps, and approval points must leave auditable traces.
    - _References: user-provided "AI-Researcher Loop Engineering Evolution Plan"; attached loop-engineering research report; task `214.1`; Scale-style physical gate idea that prompts are not enough._
    - _Verify: focused loop tests, ruff, mypy, broad smoke/unit tests, and real isolated `autopilot` smoke passed. Full commands are recorded in `Agent.md`._

## Checkpoints

- [x] Checkpoint A: Phase 0 baseline
  - `poetry run airesearcher doctor` passes.
  - `poetry run pytest tests/smoke tests/unit/config` passes.
  - `poetry run ruff check src tests` passes.
  - `poetry run mypy src` passes or typed-scope exceptions are documented.
  - `Agent.md` and `Problem.md` are current.
  - A focused commit exists for each completed Phase 0 task or subtask.

- [x] Checkpoint B: Phase 1 MVP loop
  - At least one ScientistBench-Lite task completes from direction to Markdown report.
  - Every run has run ID, commit SHA, config hash, data hash, logs, metrics, artifacts, validation report, and cost record.
  - Every quantitative claim in the report links to evidence.
  - At least 60 percent of 5 to 10 demo tasks complete the full loop when the demo suite exists.
  - At least 80 percent of successful demo tasks rerun successfully.

- [x] Checkpoint C: Phase 2 research assistant
  - Multi-agent workflow can pause and resume.
  - Evidence graph blocks unsupported claims.
  - Paper draft compiles for a validated demo project.
  - Citation, figure/table, and review checks produce structured reports.
  - Reproducibility package validates.

- [x] Checkpoint D: Phase 3 self-loop
  - Candidate pool updates on schedule.
  - Candidate pool, failures, and skills are stored as Obsidian Markdown entries with wiki-links and topic index entries.
  - Failures are classified and searchable.
  - Skill cards are generated from repeated success patterns and linked to project experience notes.
  - Monitoring export shows cost, failure rate, reproduction rate, and evidence coverage.
  - Rollback works for config or strategy fixtures.

- [x] Checkpoint E: Phase 4 controlled evolution
  - Strategy candidates pass offline replay and golden tests before shadow mode.
  - Strategy cards are stored in the Obsidian vault and linked to failure patterns, skills, evaluation reports, and rollback targets.
  - Shadow evaluation cannot affect production outputs.
  - Gray release requires human approval.
  - Negative strategy reward triggers rollback.
  - Evolution report documents benefit, risk, evidence, and decision.

## Task Dependency Graph

```json
{
  "waves": [
    {
      "id": 0,
      "tasks": ["0.1", "0.2", "0.3", "0.4", "0.5", "0.6", "0.7"]
    },
    {
      "id": 1,
      "tasks": ["1.1", "1.2", "1.3", "1.4"]
    },
    {
      "id": 2,
      "tasks": ["1.5", "2.1", "2.2", "2.3", "3.1", "3.2", "3.3", "4.1", "4.2", "4.3"]
    },
    {
      "id": 3,
      "tasks": ["5.1", "5.2", "5.3", "5.4", "5.5", "6.1", "6.2", "6.3", "6.4"]
    },
    {
      "id": 4,
      "tasks": ["7.1", "7.2", "7.3", "8.1", "8.2", "8.3"]
    },
    {
      "id": 5,
      "tasks": ["9.1", "9.2", "9.3", "10.1", "10.2", "10.3", "11.1", "11.2", "11.3", "12.1", "12.2", "12.3", "12.4"]
    },
    {
      "id": 6,
      "tasks": ["13.1", "13.2", "13.3", "14.1", "14.2", "14.3"]
    },
    {
      "id": 7,
      "tasks": ["15.1", "15.2", "15.3", "16.1", "16.2", "16.3", "17.1", "17.2", "17.3"]
    },
    {
      "id": 8,
      "tasks": ["18.1", "18.2", "18.3", "19.1", "19.2"]
    },
    {
      "id": 9,
      "tasks": ["20.1", "20.2", "21.1", "21.2", "22.1", "22.2", "23.1", "23.2", "24.1", "24.2", "25.1", "25.2"]
    },
    {
      "id": 10,
      "tasks": ["26.1", "26.2", "27.1", "27.2", "28.1", "28.2", "29.1", "29.2", "30.1", "30.2"]
    },
    {
      "id": 11,
      "tasks": ["31.1", "31.2", "32.1", "33.1", "34.1", "34.2", "35.1", "35.2", "35.3", "36.1", "36.2", "36.3"]
    },
    {
      "id": 12,
      "tasks": ["37.1", "37.2", "37.3"]
    },
    {
      "id": 13,
      "tasks": ["38.1", "38.2"]
    },
    {
      "id": 14,
      "tasks": ["39.1", "39.2"]
    },
    {
      "id": 15,
      "tasks": ["40.1", "40.2"]
    },
    {
      "id": 16,
      "tasks": ["41.1", "41.2", "41.3", "41.4"]
    },
    {
      "id": 17,
      "tasks": ["42.1"]
    },
    {
      "id": 18,
      "tasks": ["43.1"]
    },
    {
      "id": 19,
      "tasks": ["44.1"]
    },
    {
      "id": 20,
      "tasks": ["45.1"]
    },
    {
      "id": 21,
      "tasks": ["46.1"]
    },
    {
      "id": 22,
      "tasks": ["47.1"]
    },
    {
      "id": 23,
      "tasks": ["48.1"]
    },
    {
      "id": 24,
      "tasks": ["49.1"]
    },
    {
      "id": 25,
      "tasks": ["50.1"]
    },
    {
      "id": 26,
      "tasks": ["51.1"]
    },
    {
      "id": 27,
      "tasks": ["52.1"]
    },
    {
      "id": 28,
      "tasks": ["53.1"]
    },
    {
      "id": 29,
      "tasks": ["54.1"]
    },
    {
      "id": 30,
      "tasks": ["55.1"]
    },
    {
      "id": 31,
      "tasks": ["56.1"]
    },
    {
      "id": 32,
      "tasks": ["57.1"]
    },
    {
      "id": 33,
      "tasks": ["58.1"]
    },
    {
      "id": 34,
      "tasks": ["59.1"]
    },
    {
      "id": 35,
      "tasks": ["60.1"]
    },
    {
      "id": 36,
      "tasks": ["61.1"]
    },
    {
      "id": 37,
      "tasks": ["62.1", "63.1", "64.1", "65.1", "66.1", "67.1", "68.1", "69.1", "70.1", "70.2"]
    },
    {
      "id": 38,
      "tasks": ["71.1"]
    },
    {
      "id": 39,
      "tasks": ["72.1", "72.2", "72.3"]
    },
    {
      "id": 40,
      "tasks": ["73.1"]
    },
    {
      "id": 41,
      "tasks": ["74.1"]
    },
    {
      "id": 42,
      "tasks": ["75.1"]
    },
    {
      "id": 43,
      "tasks": ["76.1"]
    },
    {
      "id": 44,
      "tasks": ["77.1"]
    },
    {
      "id": 45,
      "tasks": ["78.1"]
    },
    {
      "id": 46,
      "tasks": ["79.1"]
    },
    {
      "id": 47,
      "tasks": ["80.1"]
    },
    {
      "id": 48,
      "tasks": ["81.1"]
    },
    {
      "id": 49,
      "tasks": ["82.1"]
    },
    {
      "id": 50,
      "tasks": ["83.1"]
    },
    {
      "id": 51,
      "tasks": ["84.1"]
    },
    {
      "id": 52,
      "tasks": ["85.1"]
    },
    {
      "id": 53,
      "tasks": ["86.1"]
    },
    {
      "id": 54,
      "tasks": ["87.1"]
    },
    {
      "id": 55,
      "tasks": ["88.1"]
    },
    {
      "id": 56,
      "tasks": ["89.1"]
    },
    {
      "id": 57,
      "tasks": ["90.1"]
    },
    {
      "id": 58,
      "tasks": ["91.1"]
    },
    {
      "id": 59,
      "tasks": ["92.1"]
    },
    {
      "id": 60,
      "tasks": ["93.1"]
    },
    {
      "id": 61,
      "tasks": ["94.1"]
    },
    {
      "id": 62,
      "tasks": ["95.1"]
    },
    {
      "id": 63,
      "tasks": ["96.1"]
    },
    {
      "id": 64,
      "tasks": ["97.1"]
    },
    {
      "id": 65,
      "tasks": ["98.1"]
    },
    {
      "id": 66,
      "tasks": ["99.1"]
    },
    {
      "id": 67,
      "tasks": ["100.1"]
    },
    {
      "id": 68,
      "tasks": ["101.1"]
    },
    {
      "id": 69,
      "tasks": ["102.1"]
    },
    {
      "id": 70,
      "tasks": ["103.1"]
    },
    {
      "id": 71,
      "tasks": ["104.1"]
    },
    {
      "id": 72,
      "tasks": ["105.1"]
    },
    {
      "id": 73,
      "tasks": ["106.1"]
    },
    {
      "id": 74,
      "tasks": ["107.1"]
    },
    {
      "id": 75,
      "tasks": ["108.1"]
    },
    {
      "id": 76,
      "tasks": ["109.1"]
    },
    {
      "id": 77,
      "tasks": ["110.1"]
    },
    {
      "id": 78,
      "tasks": ["111.1"]
    },
    {
      "id": 79,
      "tasks": ["112.1"]
    },
    {
      "id": 80,
      "tasks": ["113.1"]
    },
    {
      "id": 81,
      "tasks": ["114.1"]
    },
    {
      "id": 82,
      "tasks": ["115.1"]
    },
    {
      "id": 83,
      "tasks": ["116.1"]
    },
    {
      "id": 84,
      "tasks": ["117.1"]
    },
    {
      "id": 85,
      "tasks": ["118.1"]
    },
    {
      "id": 86,
      "tasks": ["119.1"]
    },
    {
      "id": 87,
      "tasks": ["120.1"]
    },
    {
      "id": 88,
      "tasks": ["121.1"]
    },
    {
      "id": 89,
      "tasks": ["122.1"]
    },
    {
      "id": 90,
      "tasks": ["123.1"]
    },
    {
      "id": 91,
      "tasks": ["124.1"]
    },
    {
      "id": 92,
      "tasks": ["125.1"]
    },
    {
      "id": 93,
      "tasks": ["126.1"]
    },
    {
      "id": 94,
      "tasks": ["127.1"]
    },
    {
      "id": 95,
      "tasks": ["128.1"]
    },
    {
      "id": 96,
      "tasks": ["129.1"]
    },
    {
      "id": 97,
      "tasks": ["130.1"]
    },
    {
      "id": 98,
      "tasks": ["131.1"]
    },
    {
      "id": 99,
      "tasks": ["132.1"]
    },
    {
      "id": 100,
      "tasks": ["133.1"]
    },
    {
      "id": 101,
      "tasks": ["134.1"]
    },
    {
      "id": 102,
      "tasks": ["135.1"]
    },
    {
      "id": 103,
      "tasks": ["136.1"]
    },
    {
      "id": 104,
      "tasks": ["137.1"]
    },
    {
      "id": 105,
      "tasks": ["138.1"]
    },
    {
      "id": 106,
      "tasks": ["139.1"]
    },
    {
      "id": 107,
      "tasks": ["140.1"]
    },
    {
      "id": 108,
      "tasks": ["141.1"]
    },
    {
      "id": 109,
      "tasks": ["142.1"]
    },
    {
      "id": 110,
      "tasks": ["143.1"]
    },
    {
      "id": 111,
      "tasks": ["144.1"]
    },
    {
      "id": 112,
      "tasks": ["145.1"]
    },
    {
      "id": 113,
      "tasks": ["146.1"]
    },
    {
      "id": 114,
      "tasks": ["147.1"]
    },
    {
      "id": 115,
      "tasks": ["148.1"]
    },
    {
      "id": 116,
      "tasks": ["149.1"]
    },
    {
      "id": 117,
      "tasks": ["214.1"]
    },
    {
      "id": 118,
      "tasks": ["215.1"]
    },
    {
      "id": 119,
      "tasks": ["216.1"]
    },
    {
      "id": 120,
      "tasks": ["217.1"]
    },
    {
      "id": 121,
      "tasks": ["218.1"]
    },
    {
      "id": 122,
      "tasks": ["219.1"]
    },
    {
      "id": 123,
      "tasks": ["220.1"]
    },
    {
      "id": 124,
      "tasks": ["221.1"]
    },
    {
      "id": 125,
      "tasks": ["222.1"]
    }
  ]
}
```

## Notes for Future Agents

- The first code task should fix `P-20260611-001` before running broad test gates.
- The first knowledge task should preserve Kiro's Obsidian-first design under project-root `autoresearch-vault/`: Exploration Zone, Project Zone, wiki-links, topic index, permissions, version history, and rollback.
- If a task is checked in this file, verify there is a corresponding `Agent.md` entry and focused git commit.
- If implementation reality diverges from this plan, update the smallest relevant part of this file and record why in `Agent.md`.
- Keep `README.md` English-first and keep `README.zh-CN.md` in sync when user-facing project status changes.
