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
