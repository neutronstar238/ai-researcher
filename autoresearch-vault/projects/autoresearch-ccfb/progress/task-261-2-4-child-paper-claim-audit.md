---
title: Task 261.2.4 child paper and claim-evidence audit
entry_id: task-261-2-4-child-paper-claim-audit
entry_type: project_progress
project_id: autoresearch-ccfb
created_at: 2026-07-29T06:01:06Z
updated_at: 2026-07-29T06:01:06Z
status: completed-negative-paper
tags:
  - negative-result
  - claim-evidence
  - citations
  - scientific-figures
  - pdf
  - reproducibility
  - submission-gate
related_run_ids:
  - task2612-mechanism-foundation-live-v3
  - task2612-mechanism-development-live-v12
  - task2612-mechanism-confirmatory-live-v1
  - task2612-mechanism-paper-live-v1
links:
  - task-261-2-3-confirmatory-adjudication
  - task-261-2-generated-mechanism-evidence-survey-2026
---

# Task 261.2.4 child paper and claim-evidence audit

Task 261.2.4 built a reproducible paper dossier from the immutable negative confirmatory endpoint.
It did not rerun the six-task panel, alter the model-authored mechanism, change a threshold, or
turn the coverage failure into a positive claim.

## Frozen identity

- Authoritative paper package:
  `runs/manual-live/task2612-mechanism-paper-live-v1/`
- Independent paper rebuild:
  `runs/manual-live/task2612-mechanism-paper-reproduction-live-v1/`
- Confirmatory manifest:
  `3086eba1a11e7b98cd8cc5faeb3f5a0d140adf80c283a637ff9b7c52b4ba011c`
- Negative endpoint:
  `d449343654e28a4da877d0ab7a3bd07e334ac8cad310385996c635bacbae165d`
- Scientific projection:
  `fed38ff7a08f12562eae1488bbc951561d3279d1e181f3b89a830e13d2ddf6f9`
- Paper manifest:
  `462c428dc1c863407042ae48ad1cb2245a942ba0af93744a0022804eeb26bcc8`
- Manuscript:
  `c33b915bb762a4d3d1dabe44bf4be5a13fc100d1ad63d6c45e3e6b67fd964b30`
- PDF:
  `e3d2ae122d096e960ae78bac5d045974399790c175190740599278cf2b38e22e`

The child round report retains 28 accepted claims, 20 abstentions, one unsupported accept,
coverage `0.5833` with task-bootstrap interval `[0.4792, 0.6875]`, and unsupported-accept rate
`0.0357` with interval `[0.00, 0.10]`. Its only scientific failure code remains
`minimum_coverage_met`.

## Claim and citation audit

The manuscript has 51 material paragraphs. Every paragraph appears exactly once in the rendered
manuscript and is registered as one of:

- named prior work;
- method;
- experiment;
- result;
- limitation;
- figure description.

The registry contains 26 verified evidence records and 77 supporting links. Every claim resolves
to the required evidence kinds, every referenced artifact digest matches, and there are no
unsupported or unregistered material claims. Claim-evidence audit hash is
`d7fe0bfd032071240e30d1ad0c7c3f4edc08370d9810cd18a4cd04a25e18cd63`;
independent entailment report hash is
`74fcdf8c6678fb89336d4dc69ef4f1a45ca1dacf75857eda6dbf8c1605de4cc9`.

All 14 frozen primary or official sources appear in three places: a named-work paragraph, an inline
source token, and the reference list. A live check returned HTTP 200 and at least 1,000 bytes for
every source. The four evidence areas contain 4 selective-factuality sources, 3 scientific-Agent
evaluation sources, 3 generated-code security sources, and 5 claim-evidence alignment sources.
Citation audit hash is
`520a8d2a493642705a7bc7de97b60dbe12c1bd9016881f4109d9d5af4edfc0a5`.

## Figures, table, and PDF

Five deterministic displays are generated from frozen JSON or result contracts:

1. graphical abstract;
2. confirmatory Control Graph flow;
3. endpoint values against frozen thresholds;
4. task-level coverage;
5. literature-area coverage.

The six-task table is generated from all primary task-result contracts. Figure files, captions,
manuscript descriptions, task ordering, counts, coverage values, and endpoint values agree.
Display audit hash is
`a940452068a194ea463b1dfa2f51e4cc7f45f7f4f6d1247d7c44ec82e4bed184`.

The primary manuscript has 2,512 words, 16 tracked technical terms, 5 figures, 1 table, 14
references, 13 pages, and zero overfull boxes. All 13 pages were rendered to PNG and visually
inspected: no clipping, overlap, unreadable display, malformed URL, or unresolved reference marker
was found.

## Independent reproduction and decision

The clean rebuild matched all 24 deterministic manuscript, data, vector/raster figure, table, and
audit sources and independently compiled a second 13-page quality-passing PDF. Reproduction report
hash is `22671bf025c000dd382c3d168f6964fa6abe0bf5a53f05e74d561a63740c2a6b`.

The final audit faithfully reports the negative endpoint and passes claim, citation, display, PDF,
and reproduction checks. It deliberately fails:

- `scientific_submission_gate`;
- `authorship_review`;
- `license_review`;
- `explicit_human_approval`.

Final audit hash is
`4cc7ff4c37ef85959aaf48e7e980d06be76bc0086c28d4c1fe705d452ffc4838`.
Positive contribution, submission readiness, public release, and external submission remain false.
Any later mechanism change requires a new development partition and a newly frozen independent
confirmatory panel.

## Related knowledge

- [[task-261-2-3-confirmatory-adjudication|Task 261.2.3 confirmatory adjudication]]
- [[task-261-2-generated-mechanism-evidence-survey-2026|Generated mechanism evidence survey]]
