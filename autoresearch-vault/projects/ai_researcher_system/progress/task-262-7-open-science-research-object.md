---
title: Task 262.7 validated Open Science research objects
date: 2026-07-29
status: completed
task: "262.7"
tags:
  - open-science
  - ro-crate
  - workflow-run-crate
  - reproducibility
  - software-supply-chain
---

# Task 262.7 validated Open Science research objects

## Result

AutoResearch now exports a validated research object beside, rather than in place of, the existing
reproducibility package. The exporter consumes a verified provenance-v2 bundle and explicitly
declared artifacts; it does not modify the source bundle, legacy package layout, campaign state, or
scientific endpoint.

Every export has two default views:

- `internal-complete`, which may retain explicitly internal artifacts and the canonical provenance
  bundle;
- `review-reproduction`, which excludes the internal bundle and deterministically sanitizes JSON
  private paths and secret-valued fields.

A third `public` view is materialized only when a human approval names the same object identifier,
at least one artifact is explicitly public, every public artifact has a supported public license,
and the source scan finds no private path or secret-like content. Exporting never publishes,
uploads, mints an identifier, or submits a manuscript.

## Interoperability projections

The object contains:

- RO-Crate 1.3 JSON-LD and the Workflow RO-Crate 1.0 plus Process, Workflow, and Provenance Run
  RO-Crate 0.5 profiles;
- a W3C PROV JSON-LD projection and a separate prospective workflow document;
- CodeMeta 3.1, Citation File Format 1.2.0, CRediT's fourteen roles, and a DataCite 4.7
  field-aligned draft;
- SPDX 3.0.1 Core/Software/SimpleLicensing/Build metadata;
- an in-toto Statement with SLSA provenance-v1 fields for the local export construction;
- a reader-facing `README.md`, export policy, hashes, validation report, and a pure-standard-library
  clean-directory verifier.

Workflow Run RO-Crate 0.5 formally inherits RO-Crate 1.1, while this task targets RO-Crate 1.3.
The metadata descriptor therefore declares 1.3 as the current crate profile and separately
declares the 1.1/Workflow RO-Crate compatibility profiles. The main workflow also declares the
released
[Bioschemas ComputationalWorkflow 1.0 profile](https://bioschemas.org/profiles/ComputationalWorkflow/1.0-RELEASE).

DataCite output remains `depositReady: false` and has no identifier unless a real DOI is supplied.
An intrinsic `swh:1:rev:<git-sha1>` may be recorded only when it equals the declared Git revision;
this does not claim that Software Heritage has archived or can resolve the revision.

The SLSA document describes only how this local research-object view was constructed. Its policy
states `signed: false`, no SLSA level, no trusted-builder claim, and no scientific-result
attestation. Metadata interoperability and hash/assertion replay are not described as scientific
reproduction.

## Integrity and privacy gates

Source artifacts require explicit visibility, media type, license, optional expected SHA-256, and
an allowed deterministic transform. Unsafe crate paths, duplicate paths, source-hash drift,
unknown CRediT roles, malformed DOI/ORCID/SWHID values, secret-like source content, and
publication-scope mismatches fail closed.

Each view cross-checks:

- RO-Crate graph references, payload existence, profile declarations, workflow and run actions;
- PROV graph identifiers and references;
- title, version, license, contributor, DOI, SWHID, and repository consistency across RO-Crate,
  CodeMeta, CFF, contributions, and DataCite;
- SPDX document shape and SLSA subject digests;
- visibility policy, sensitive-content scan, and complete non-report hash-manifest coverage.

The hash manifest intentionally excludes itself and the validation report to avoid a recursive
digest cycle. The clean-directory verifier copies a review crate, runs with `python -I`, recomputes
the declared artifact hashes, and checks frozen JSON pointers. It does not rerun the underlying
experiment.

## Real round characterization

The opt-in smoke exported the existing
`task260-autonomous-ccfb-v1/round-001` negative-result round without rerunning science or calling a
model. The source provenance bundle remained:

`a2e54556b3f6e242deeaff3d7c87400ae23e701ef034983fb6964a3c2df4c782`

Seven existing JSON artifacts were hash-checked before and after export. The review view removed
the internal provenance bundle, contained no repository-private paths, and passed six frozen
negative-result/decision assertions in a new clean directory. No public view was generated:
explicit human approval and publicly licensed artifacts were absent.

Characterization outputs are under the ignored directory
`runs/manual-live/task262-open-science-v6/`. They include both research-object views, the clean
reproduction result, source hashes, validator reports, and a smoke summary.

## External validation

`rocrate-validator` 0.11.2 passed all required checks for:

- Workflow RO-Crate 1.0;
- Process Run Crate 0.5;
- Workflow Run Crate 0.5;
- Provenance Run Crate 0.5.

Workflow RO-Crate also passed every recommended check. The three Run-Crate recommended reports
retain two duplicate advisory findings: their shared validator shape requires every entity typed as
the packaged local workflow's `SoftwareSourceCode` and `ComputationalWorkflow` to use an HTTP
identifier. Changing the local payload ID `workflow/workflow.json` to HTTP would misrepresent a
crate file as a remote resource, so the two advisories are preserved rather than hidden. The
validator currently provides base RO-Crate profiles only through 1.2, so RO-Crate 1.3 is checked by
the exporter against its current profile contract rather than falsely reported as externally
validated by that tool.

The generated citation file passed the official CFF 1.2.0 JSON Schema with zero errors. The
exported SPDX JSON-LD likewise passed the official SPDX 3.0.1 JSON Schema with zero errors. The
SLSA shape and every subject digest passed internal validation; `slsa-verifier` was not used
because the attestation is intentionally unsigned and claims neither a trusted builder nor a SLSA
level.

## Verification

- 8 deterministic Open Science unit tests passed.
- The real-round opt-in smoke passed.
- Independent clean-directory reproduction passed 6 assertions over 4 asserted files.
- Four required RO-Crate profile validations passed; Workflow RO-Crate recommended validation
  passed with zero issues.
- The official CFF 1.2.0 and SPDX 3.0.1 JSON Schemas reported zero errors.
- Full regression passed with 866 tests and 8 opt-in live tests skipped at 86% coverage.
- Full Ruff passed. Mypy passed for 146 source files.

## Frozen boundaries

- Existing reproducibility packages and all legacy Campaign, Competition, and Sprint writers remain
  authoritative and unchanged.
- Existing scientific outcomes, gates, thresholds, and source artifact bytes were not changed.
- No dependency version changed; the external validator lived in a temporary environment outside
  the repository.
- No DOI was invented, no SLSA level was claimed, and no public release or submission occurred.
- Task 262.8 owns parity-gated service migration.

## Links

- [[exploration/graph-harness-loop-open-science-2026|vNext refactor research]]
- [[projects/ai_researcher_system/progress/task-262-6-prov-evidence-v2|Task 262.6 provenance and evidence v2]]
- [[projects/ai_researcher_system/index|AI-Researcher System Project]]
