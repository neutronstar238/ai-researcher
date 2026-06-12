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

Networked discovery is mandatory, not optional. The Obsidian vault is the evidence memory layer, not a substitute for external search. Project-start novelty checks, similar-direction cross-validation, and scheduled candidate refresh must query external sources such as ArXiv and Semantic Scholar before relying on local vault memory. Summaries written to the vault must cite source documents, query text, retrieval timestamps, and unsupported/unknown claims explicitly; never fabricate results, citations, rankings, or experimental outcomes.

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

  - [x] 6.2 Implement ArXiv and Semantic Scholar clients
    - Start with ArXiv and Semantic Scholar only.
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
    - Fetch fresh papers and research materials automatically from free/public sources, starting with ArXiv and Semantic Scholar.
    - Respect source-specific API limits; ArXiv legacy API access must use a single connection and at least 3 seconds between requests.
    - Optimize search queries from project topics, Obsidian topic indexes, method cards, dataset cards, prior failures, and active candidate gaps.
    - Store raw metadata, normalized `DocumentRecord` items, source query text, timestamps, and rate-limit decisions in the Obsidian vault or retrieval cache.
    - Deduplicate results across sources before candidate update analysis.
    - _References: REQ 12, REQ 6, Horizon-style source pipeline, arXiv API terms_
    - _Verify: unit tests cover query generation, deduplication, cache reuse, and mocked rate-limited daily refresh without network access; opt-in live smoke test fetches real ArXiv/Semantic Scholar documents before completion._

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
