# Implementation Plan: AutoResearch System

## Overview

This implementation plan details the complete development roadmap for the AutoResearch System - a full-stack automated research platform with multi-agent architecture, intelligent resource management, and end-to-end research workflow automation. The system will be implemented in **Python 3.10+** across 6 phases over 24 weeks.

## Tasks

### Phase 1: Core Infrastructure (Weeks 1-4)

- [ ] 1. Set up project structure and core framework
  - [x] 1.1 Create Python project with modular directory structure
    - Initialize project with `pyproject.toml` and dependency management (Poetry or pip-tools)
    - Create modular package structure: `agents/`, `knowledge/`, `scheduler/`, `literature/`, `experiments/`, `paper/`, `config/`, `security/`, `cli/`
    - Set up development tools: black, ruff, mypy for code quality
    - Create initial configuration system with YAML/TOML support
    - _Requirements: 30.5_
  
  - [ ] 1.2 Write property test for configuration round-trip (Property 13)
    - **Property 13: Configuration Format Round-Trip**
    - **Validates: Requirements 30.4**
    - Test that JSON, YAML, and TOML configs serialize and deserialize correctly
  
  - [ ] 1.3 Write property test for invalid configuration error reporting (Property 36)
    - **Property 36: Invalid Configuration Error Reporting**
    - **Validates: Requirements 30.2, 30.6**
    - Test that malformed configs generate descriptive error messages

- [ ] 2. Implement base agent architecture
  - [ ] 2.1 Create base Agent class with state management
    - Define `Agent` base class with `agent_id`, `capabilities`, and state management
    - Implement message passing interface with typed schemas
    - Create agent lifecycle methods: `initialize()`, `execute_task()`, `shutdown()`
    - _Requirements: 1.1, 1.4_
  
  - [ ] 2.2 Implement AgentRegistry for tracking active agents
    - Create `AgentRegistry` class with add/remove/get operations
    - Implement thread-safe registry with locking for concurrent access
    - Add agent capability querying and filtering
    - _Requirements: 1.6_
  
  - [ ] 2.3 Write property tests for agent management (Properties 1, 3, 4)
    - **Property 1: Project Agent Creation** (Requirements 1.3)
    - **Property 3: Message Delivery** (Requirements 1.5)
    - **Property 4: Agent Registry Consistency** (Requirements 1.6)
    - Use hypothesis to generate random agent configurations and verify creation/messaging/registry

- [ ] 3. Implement Main Agent orchestration
  - [ ] 3.1 Create MainAgent class with task delegation capabilities
    - Implement Main Agent singleton pattern with user interaction handling
    - Create task decomposition and delegation logic
    - Implement decision-making framework based on agent outputs
    - Add progress monitoring and error handling
    - _Requirements: 1.1, 1.4, 1.5_
  
  - [ ] 3.2 Write property test for task routing correctness (Property 2)
    - **Property 2: Task Routing Correctness**
    - **Validates: Requirements 1.4**
    - Verify tasks are assigned to agents with matching capabilities

- [ ] 4. Implement LangGraph integration for stateful workflows
  - [ ] 4.1 Set up LangGraph runtime with state persistence
    - Integrate LangGraph for stateful multi-agent workflows
    - Define state schemas for agent communication
    - Implement checkpoint/resume capability for long-running workflows
    - Create workflow graph definitions for research pipeline
    - _Requirements: 1.5_

- [ ] 5. Build Knowledge Base foundation
  - [ ] 5.1 Implement KnowledgeBase interface and Obsidian integration
    - Create `KnowledgeBase` class with CRUD operations for Markdown files
    - Implement Exploration Zone and Project Zone directory structures
    - Add file-based versioning with timestamp tracking
    - Create wiki-link parsing and bidirectional link creation
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_
  
  - [ ] 5.2 Implement permission system for zone-based access control
    - Create `PermissionManager` with access control matrix (Main/Fixed/Project agents)
    - Implement permission checks before all write operations
    - Add access denial logging for security auditing
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_
  
  - [ ] 5.3 Write property tests for knowledge base operations (Properties 17-22)
    - **Property 17: Project Directory Structure** (Requirements 6.3)
    - **Property 18: Bidirectional Link Creation** (Requirements 6.5)
    - **Property 19: Permission Enforcement for Project Agents** (Requirements 7.4, 7.5)
    - **Property 20: Main Agent Universal Access** (Requirements 7.1)
    - **Property 21: Knowledge Entry Retrieval** (Requirements 6.6)
    - **Property 22: Version History Preservation** (Requirements 8.6, 28.2)

- [ ] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

### Phase 2: Resource Management (Weeks 5-8)

- [ ] 7. Implement SSH resource discovery
  - [ ] 7.1 Create SSH config parser and connectivity tester
    - Implement SSH config file parser (`~/.ssh/config`) to extract host entries
    - Create connectivity probe with timeout and error handling
    - Implement hardware specification query via SSH commands
    - Parse CPU, memory, GPU information from remote servers
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_
  
  - [ ] 7.2 Write property test for SSH config parsing (Properties 10, 11, 12)
    - **Property 10: SSH Config Parsing Round-Trip** (Requirements 3.2, 30.4)
    - **Property 11: SSH Entry Count Preservation** (Requirements 3.3)
    - **Property 12: Registry Update Consistency** (Requirements 3.6)

- [ ] 8. Build Compute Scheduler core
  - [ ] 8.1 Implement ComputeScheduler with resource registry
    - Create `ComputeScheduler` class with resource discovery integration
    - Implement resource registry with status tracking (available/busy/offline)
    - Add resource requirement evaluation from experiment tasks
    - Create resource matching algorithm based on specifications
    - _Requirements: 5.1, 5.3_
  
  - [ ] 8.2 Implement task queue with priority-based scheduling
    - Create priority queue for experiment tasks
    - Implement task selection algorithm (highest priority first)
    - Add GPU vs non-GPU task separation logic
    - _Requirements: 5.4, 5.6_
  
  - [ ] 8.3 Write property tests for scheduling (Properties 14, 15, 16)
    - **Property 14: Resource Requirement Evaluation** (Requirements 5.1)
    - **Property 15: Priority-Based Task Ordering** (Requirements 5.6)
    - **Property 16: Local Resource Preference** (Requirements 5.2)

- [ ] 9. Implement SSH execution manager
  - [ ] 9.1 Create SSH connection pool and command executor
    - Implement SSH connection pooling with paramiko/fabric (max 10 connections per server)
    - Create remote command execution with stdout/stderr capture
    - Add file transfer capabilities (SCP/SFTP) for code and results
    - Implement execution monitoring and status tracking
    - _Requirements: 5.3_

- [ ] 10. Build sandbox execution environment
  - [ ] 10.1 Implement sandbox security restrictions
    - Create `SandboxExecutor` with file system path validation
    - Implement network access allowlist (academic databases only)
    - Add resource limits using Python `resource` module (RLIMIT_CPU, RLIMIT_AS)
    - Create blocked operation detection and prevention
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5_
  
  - [ ] 10.2 Implement full permission execution mode
    - Create `FullPermissionExecutor` with extended access
    - Add dangerous operation prevention (disk wiping, kernel mods)
    - Implement comprehensive operation logging for audit
    - Add user approval workflow for permission escalation
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5_
  
  - [ ] 10.3 Write property tests for sandbox execution (Properties 25-28)
    - **Property 25: File System Access Restriction** (Requirements 16.2)
    - **Property 26: Network Access Restriction** (Requirements 16.3)
    - **Property 27: Resource Limit Enforcement** (Requirements 16.5)
    - **Property 28: Operation Logging in Full Permission Mode** (Requirements 17.4)

- [ ] 11. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

### Phase 3: Research Pipeline (Weeks 9-14)

- [ ] 12. Implement multi-source literature retrieval
  - [ ] 12.1 Create API clients for academic databases
    - Implement `ArxivClient` using arxiv.py library
    - Implement `SemanticScholarClient` for Semantic Scholar API
    - Implement `DBLPClient` and `PubMedClient` for respective databases
    - Implement `CNKIClient` and `WanFangClient` with web scraping (requests + BeautifulSoup)
    - Add rate limiting per database with configurable limits
    - _Requirements: 9.1, 9.3_
  
  - [ ] 12.2 Implement LiteratureRetriever with parallel search
    - Create `LiteratureRetriever` Fixed Agent class
    - Implement parallel async search across all databases using asyncio.gather
    - Add rate limiting with exponential backoff on errors
    - Implement caching layer to avoid redundant API calls (24-hour cache)
    - _Requirements: 9.2, 9.4_
  
  - [ ] 12.3 Implement deduplication and metadata extraction
    - Create deduplication algorithm based on DOI and title similarity
    - Implement metadata extraction into structured `Paper` dataclass
    - Add missing field handling for incomplete metadata
    - _Requirements: 9.5, 9.6_
  
  - [ ] 12.4 Write property tests for literature retrieval (Properties 23, 24)
    - **Property 23: Deduplication Correctness** (Requirements 9.5)
    - **Property 24: Metadata Completeness** (Requirements 9.6)

- [ ] 13. Implement web content retrieval
  - [ ] 13.1 Add GitHub and web page scraping capabilities
    - Implement GitHub repository content extraction (README, docs)
    - Create web page HTML parser with main content extraction
    - Add robots.txt compliance checking
    - Implement web content caching
    - Add error handling and fallback logic
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

- [ ] 14. Build Summarizer Fixed Agent
  - [ ] 14.1 Implement paper summarization and classification
    - Create `SummarizerAgent` Fixed Agent class
    - Implement abstract summarization using LLM
    - Add key innovation point extraction
    - Create research category classification logic
    - Implement method and dataset extraction from papers
    - Store summaries in Knowledge Base with links to original papers
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

- [ ] 15. Implement research direction generation
  - [ ] 15.1 Create scheduled research direction discovery
    - Implement daily scheduled task execution (configurable intervals)
    - Create literature trend analysis from recent papers
    - Implement research gap identification by comparing literature with Knowledge Base
    - Generate `ResearchCandidate` items with novelty/feasibility/impact scores
    - Rank candidates and present top options to user
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

- [ ] 16. Build Project Agent for preliminary investigation
  - [ ] 16.1 Implement ProjectAgent with investigation capabilities
    - Create `ProjectAgent` class with project-specific scope
    - Implement comprehensive literature search for selected direction
    - Add state-of-the-art method analysis
    - Create dataset and benchmark identification
    - Generate preliminary investigation report
    - Add user approval workflow before proceeding
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_

- [ ] 17. Implement research idea generation
  - [ ] 17.1 Generate and evaluate research ideas
    - Implement research idea generation based on identified gaps
    - Add novelty assessment via literature comparison
    - Create technical feasibility evaluation
    - Implement resource and time estimation
    - Rank ideas and present top options with justifications
    - Initialize full project execution on user approval
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6_

- [ ] 18. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

### Phase 4: Execution and Results (Weeks 15-18)

- [ ] 19. Implement experiment code generation
  - [ ] 19.1 Create code generator for experiment tasks
    - Implement task decomposition into executable `ExperimentTask` items
    - Create Python code generator with structured project layout
    - Add logging, checkpointing, and result saving to generated code
    - Generate configuration files (YAML) for hyperparameters
    - Create requirements.txt with dependencies
    - Generate README documentation
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6_

- [ ] 20. Build experiment execution pipeline
  - [ ] 20.1 Implement concurrent experiment execution
    - Create experiment deployment to remote servers
    - Implement concurrent execution across multiple SSH servers
    - Add execution status monitoring for all tasks
    - Create log collection and aggregation from concurrent runs
    - Implement failure isolation (one failure doesn't stop others)
    - Support up to 10 concurrent experiments
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6_

- [ ] 21. Implement result collection and analysis
  - [ ] 21.1 Create automated result collector
    - Implement output file collection (logs, metrics, checkpoints)
    - Create metrics extraction from experiment logs
    - Generate visualization charts (training curves, comparison tables)
    - Implement baseline comparison against literature
    - Store results in project directory in Knowledge Base
    - Generate structured summary for paper generation
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6_
  
  - [ ] 21.2 Write property tests for result collection (Properties 29, 30)
    - **Property 29: Output File Collection** (Requirements 19.1)
    - **Property 30: Metrics Extraction** (Requirements 19.2)

- [ ] 22. Implement version control integration
  - [ ] 22.1 Add Git repository management
    - Initialize Git repositories for project code
    - Create commits for generated code with descriptive messages
    - Implement tagging for experiment runs with unique IDs
    - Add branching support for parallel variations
    - Generate .gitignore for large files and temporary outputs
    - _Requirements: 27.1, 27.2, 27.3, 27.4, 27.5, 27.6_
  
  - [ ] 22.2 Implement document versioning
    - Add file-based version history for Knowledge Base Markdown files
    - Create version comparison and diff functionality
    - Implement rollback to previous versions
    - Add automatic backup system (configurable intervals)
    - _Requirements: 28.1, 28.2, 28.3, 28.4, 28.5, 28.6_
  
  - [ ] 22.3 Write property tests for version control (Properties 31, 32)
    - **Property 31: Git Tracking for Code Changes** (Requirements 27.3)
    - **Property 32: Git Tag Association** (Requirements 27.4)

- [ ] 23. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

### Phase 5: Paper Generation and Quality Control (Weeks 19-22)

- [ ] 24. Build paper generation pipeline
  - [ ] 24.1 Implement LaTeX paper generator
    - Create `PaperGenerator` Fixed Agent class
    - Implement section generation (abstract, intro, related work, methodology, experiments, results, conclusion)
    - Add experiment results and figure insertion
    - Generate BibTeX bibliography from cited papers
    - Apply conference/journal LaTeX templates
    - Validate LaTeX compilation and produce PDF
    - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.5, 20.6_
  
  - [ ] 24.2 Write property test for LaTeX compilation (Property 33)
    - **Property 33: LaTeX Compilation Validation** (Requirements 20.6)

- [ ] 25. Implement template management system
  - [ ] 25.1 Create template repository and manager
    - Build `TemplateManager` class with template storage
    - Implement template download from conference websites and Overleaf
    - Add custom template import and validation
    - Extract required fields and formatting rules from templates
    - Create template selection interface with metadata
    - Handle missing template fields gracefully with warnings
    - _Requirements: 21.1, 21.2, 21.3, 21.4, 21.5, 21.6_
  
  - [ ] 25.2 Write property test for template field handling (Property 34)
    - **Property 34: Template Field Handling** (Requirements 21.4, 21.6)

- [ ] 26. Build figure generation system
  - [ ] 26.1 Implement automated figure generator
    - Create `FigureGenerator` class for scientific visualizations
    - Implement training curve line charts with matplotlib
    - Add bar charts and comparison tables
    - Create confusion matrices and heatmaps
    - Apply consistent color schemes and styling
    - Generate vector format PDFs for publication quality
    - Add journal-specific figure formatting
    - _Requirements: 22.1, 22.2, 22.3, 22.4, 22.5, 22.6_
  
  - [ ] 26.2 Write property test for figure format consistency (Property 35)
    - **Property 35: Figure Format Consistency** (Requirements 22.4, 22.5)

- [ ] 27. Implement presentation and poster generation
  - [ ] 27.1 Create slide deck and poster generators
    - Implement HTML-based slide generation from paper content
    - Extract key points for slide content
    - Include experiment visualizations in slides
    - Generate LaTeX beamer posters with appropriate layout
    - Create both digital PDF and print-ready versions
    - _Requirements: 23.1, 23.2, 23.3, 23.4, 23.5, 23.6_

- [ ] 28. Build Review Simulator Agent
  - [ ] 28.1 Implement simulated peer review system
    - Create `ReviewSimulatorAgent` Fixed Agent class
    - Implement scientific soundness evaluation
    - Add novelty and significance assessment
    - Create technical feasibility checking
    - Evaluate writing clarity and organization
    - Check experimental completeness
    - Generate review reports with scores and comments
    - _Requirements: 24.1, 24.2, 24.3, 24.4, 24.5, 24.6_
  
  - [ ] 28.2 Add venue-specific review criteria
    - Load venue-specific evaluation criteria
    - Apply venue scoring rubrics and thresholds
    - Check formatting requirement compliance
    - Verify venue content policies (ethics, reproducibility)
    - Use general standards as fallback for missing criteria
    - Allow custom criteria definition
    - _Requirements: 25.1, 25.2, 25.3, 25.4, 25.5, 25.6_
  
  - [ ] 28.3 Implement CCF-B quality assessment
    - Apply CCF-B level quality criteria
    - Compare against recently published CCF-B papers
    - Evaluate experimental rigor
    - Assess presentation quality
    - Provide improvement recommendations when below threshold
    - Suggest target venues when quality threshold met
    - _Requirements: 29.1, 29.2, 29.3, 29.4, 29.5, 29.6_

- [ ] 29. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

### Phase 6: Advanced Features and Integration (Weeks 23-24)

- [ ] 30. Implement AutoDL cloud integration
  - [ ] 30.1 Create AutoDL rental automation
    - Integrate computer-use capability for AutoDL web interface
    - Implement GPU instance availability checking
    - Create automatic instance rental with specification matching
    - Add SSH connection establishment to rented instances
    - Implement automatic instance release after task completion
    - Add failure notification and manual rental instructions
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_
  
  - [ ] 30.2 Integrate AutoDL with compute scheduler
    - Add cloud resource as fallback when local insufficient
    - Implement GPU queue wait time monitoring
    - Create automatic AutoDL rental trigger (wait time > threshold)
    - Add cost tracking and optimization
    - _Requirements: 5.5_

- [ ] 31. Build mobile notification system
  - [ ] 31.1 Implement Feishu and WeChat integration
    - Create Feishu webhook notification client
    - Implement WeChat API integration
    - Send notifications for approvals, confirmations, and errors
    - Add mobile response handling for approval requests
    - Implement text-based command interface for mobile
    - Gracefully skip when no platforms configured
    - _Requirements: 26.1, 26.2, 26.3, 26.4, 26.5, 26.6_

- [ ] 32. Implement agent learning and evolution
  - [ ] 32.1 Create execution recording and analysis system
    - Implement execution outcome and feedback recording
    - Create experience accumulation for Fixed Agents
    - Add failure analysis with context capture
    - Implement skill extraction from completed tasks
    - Store learned skills in Knowledge Base
    - Create skill retrieval for similar tasks
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_
  
  - [ ] 32.2 Write property tests for agent learning (Properties 5-9)
    - **Property 5: Execution Recording** (Requirements 2.1)
    - **Property 6: Experience Accumulation** (Requirements 2.2)
    - **Property 7: Failure Analysis Trigger** (Requirements 2.4)
    - **Property 8: Skill Storage** (Requirements 2.5)
    - **Property 9: Skill Retrieval for Similar Tasks** (Requirements 2.6)

- [ ] 33. Implement knowledge base evolution
  - [ ] 33.1 Add automatic knowledge organization
    - Implement clustering analysis based on content similarity
    - Create usage statistics tracking for knowledge entries
    - Add consolidation and restructuring suggestions
    - Extract reusable skills from completed tasks
    - Create skill entries with usage examples
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

- [ ] 34. Build CLI interface and system integration
  - [ ] 34.1 Create command-line interface
    - Implement CLI using Click or argparse for all major operations
    - Add progress reporting for long-running tasks
    - Create clear error messages with resolution steps
    - Add interactive mode for user decisions
    - _Requirements: Non-functional: Usability 1, 2, 3_
  
  - [ ] 34.2 Implement security features
    - Add credential encryption using cryptography library (Fernet)
    - Implement input validation to prevent injection attacks
    - Create security event audit logging
    - Add comprehensive error handling with retry logic
    - _Requirements: Non-functional: Security 1, 2, 3; Reliability 2_

- [ ] 35. Final testing and optimization
  - [ ] 35.1 Complete property-based test suite
    - Ensure all 36 properties have comprehensive test coverage
    - Run full test suite with 100+ iterations per property
    - Verify 80% coverage of core logic
    - _Requirements: All properties 1-36_
  
  - [ ] 35.2 Write integration tests for external services
    - Test literature retrieval with real APIs
    - Test SSH execution with test servers
    - Test Knowledge Base file operations
    - Test Git operations
    - Test LaTeX compilation
  
  - [ ] 35.3 Performance optimization and monitoring
    - Implement caching strategy (literature results, templates)
    - Add connection pooling (SSH, database)
    - Optimize parallelization (literature retrieval, experiments)
    - Create health check system
    - Add metrics and logging
    - _Requirements: Non-functional: Performance 1, 2, 3; Reliability 1, 3_

- [ ] 36. Final checkpoint and documentation
  - Ensure all tests pass, verify system meets all requirements, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional property-based and integration tests that can be skipped for faster MVP
- Each task references specific requirements for traceability via _Requirements: X.Y_ notation
- Property tests validate universal correctness properties defined in the design document
- Checkpoints ensure incremental validation at major phase boundaries
- Implementation uses **Python 3.10+** with LangGraph, Obsidian, Hypothesis, and standard scientific Python libraries
- The system requires external integrations: SSH servers, academic APIs, AutoDL (optional), mobile platforms (optional)
- Security is built-in with sandbox execution, credential encryption, and audit logging
- All property tests should run with minimum 100 iterations using Hypothesis
- Core implementation tasks (non-test) must be completed; test tasks provide quality assurance

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1", "5.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "3.1", "5.2", "5.3"] },
    { "id": 3, "tasks": ["3.2", "4.1"] },
    { "id": 4, "tasks": ["7.1", "7.2"] },
    { "id": 5, "tasks": ["8.1", "9.1"] },
    { "id": 6, "tasks": ["8.2", "8.3", "10.1"] },
    { "id": 7, "tasks": ["10.2", "10.3"] },
    { "id": 8, "tasks": ["12.1"] },
    { "id": 9, "tasks": ["12.2", "13.1"] },
    { "id": 10, "tasks": ["12.3", "12.4", "14.1"] },
    { "id": 11, "tasks": ["15.1", "16.1"] },
    { "id": 12, "tasks": ["17.1"] },
    { "id": 13, "tasks": ["19.1"] },
    { "id": 14, "tasks": ["20.1"] },
    { "id": 15, "tasks": ["21.1", "21.2", "22.1"] },
    { "id": 16, "tasks": ["22.2", "22.3"] },
    { "id": 17, "tasks": ["24.1", "24.2", "25.1"] },
    { "id": 18, "tasks": ["25.2", "26.1", "26.2"] },
    { "id": 19, "tasks": ["27.1", "28.1"] },
    { "id": 20, "tasks": ["28.2"] },
    { "id": 21, "tasks": ["28.3", "30.1"] },
    { "id": 22, "tasks": ["30.2", "31.1", "32.1"] },
    { "id": 23, "tasks": ["32.2", "33.1", "34.1"] },
    { "id": 24, "tasks": ["34.2", "35.1", "35.2", "35.3"] }
  ]
}
```
