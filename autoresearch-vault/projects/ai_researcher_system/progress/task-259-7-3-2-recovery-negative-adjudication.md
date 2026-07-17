---
entry_type: project_progress
zone: project
project_id: ai_researcher_system
title: "Task 259.7.3.2 recovery negative adjudication"
tags:
  - competition
  - mdbench
  - recovery
  - negative-result
  - gate-a
---

# Task 259.7.3.2 - Recovery Negative Adjudication

## Status

- Task: `259.7.3.2`
- Status: completed
- Completed at: 2026-07-18 01:29:51 +08:00
- Gate A decision: `negative_result`
- Gate B allowed: `false`
- Human interventions: `0`
- Access requests: `0`

## Execution Evidence

The unchanged 252-cell recovery matrix ran in image
`autoresearch-mdbench-gate-a-recovery:c22b9243` with environment hash
`006f047a654fb33296cd849c27cf0f9774ebd0b809780aaca441ae0871b8f7f4`.
All 252 cells reached a terminal state: 241 succeeded, 11 failed, none timed out, and none remained
pending. An identical execution invocation then revalidated and reused all 252 unique result hashes;
no scientific cell was recomputed.

The 11 failures remain evidence. Nine belong to `sindy_or_pdefind`: six noisy-PDE `SympifyError`
records and three clean Lorenz records missing required scientific evidence. Two belong to the
candidate: noisy seed 43 for `chen-lee-attractor` and
`lorenz-equations-complex-periodic` lacked required scientific evidence. Operon completed 84/84.

- Recovery matrix hash: `9dba5411b3ae5244950d8f056008370510009a7b9ba1a1d2fbf60956230cd19e`
- Execution report hash: `c86d8d8e607eecc1e25bd89f1e744894d35a2e6acc079a82f8110ddd4da3373b`
- Result-set hash: `2a9b402c5f0a17410aaff8c0918b5b37021e08cf0c6c2ae46387544c9a55564c`

## Frozen Adjudication

The adjudicator used the hashes committed in
[[projects/ai_researcher_system/progress/task-259-7-3-1-recovery-truth-freeze|Task 259.7.3.1]]:

- Truth registry: `38d549143207b177b6a2c9430e5b68cdd89e4dd80b41eaf04d082f5b255b04dd`
- Analysis policy: `ef60d9a245a7a0937b99361d71ed31d2c79116b25ff45098d9f39c554d9cbd9f`
- Adjudicator SHA-256: `b2037a1c765aa8274205da85c59c35958405abbea81ee5498a515ef8796b7d31`

Operon was the strongest development baseline. The candidate's clean unseen derivative-NMSE
median was `0.0146375294` versus Operon's `0.0914147362`, but the preregistered noisy unseen primary
median was `6.7172942065` versus `0.6980009446`. Candidate success was 82/84 and all-method success
was 241/252. Four of the six failure-aware system effects were negative; their median relative
improvement was `-1.7040611207`. The 20,000-resample system-level bootstrap 95% interval was
`[-4.1162493517, 0.2929116899]`.

Four mandatory checks failed: candidate three-seed success, all-method reproducibility, 5% primary
improvement, and positive bootstrap lower bound. Two unchanged adjudication calls produced the same
file SHA-256 `64b64775d519eb4cf289ad0a1e8bf1e2a5848bc966917dd2c1c5a9fc7c01f6d8`.
The canonical report hash is `4e2c49ec0e3be5bfe482f153468d17496c74d48b8fa17903a89787dadb2b623d`;
the analysis hash is `cc3ebdadc8c56751a6e18ceaa08121feebed7e73415c90172aab4f846ca0f085`.

## Stop Boundary

This sealed evaluation falsifies the weak-form projection plus bootstrap support-stability recovery
hypothesis under the preregistered noisy cross-system gate. The mechanism family is closed without
post-unseen tuning. Gate B, Qwen submission evidence, product expansion, external submission, and
award claims remain blocked. A future Gate A attempt would require a separately justified,
result-blind hypothesis and a newly sealed panel; this task does not open a third cycle.
