---
title: Task 263.6.6 replacement objective-data tournament
date: 2026-07-31
status: completed-all-candidates-rejected
task: "263.6.6"
tags:
  - autoresearch
  - ai-scientist
  - benchmark-validity
  - provenance
  - licensing
  - objective-evaluation
  - reproducibility
  - negative-result
---

# Task 263.6.6 Replacement Objective-Data Tournament

## Outcome

Task 263.6.6 completed before any candidate model call. Four official
candidate releases were audited with no hardcoded winner, and all four failed
the same prospective conjunction:

`all-candidates-rejected → freeze benchmark-validity mapping protocol`.

No evaluator or critic construction, provider credential, Research Question
Certificate, confirmation panel, publication claim, public release, or
external submission was authorized.

## Frozen candidates and revisions

| Candidate | Official dataset revision | Official repository revision |
|---|---|---|
| AutoSDT-5K | `659b60f3fabdfc5d6b80ef08176f602f4cfb24a6` | `744a3c70a49c6e53effae65a93d2a7ad9ce923ba` |
| ScienceAgentBench | `9c6e96c9e74572e979b0930ee735041cef528cb7` | `c26e151ed601ba109dc4d35e057ff8e73fec469d` |
| CORE-Bench | `18ac8edf2532d9edb9d13ae71f715410de6ee5a0` | `e32a2980e72fe6eb04ee04eb749458f570625663` |
| QRData | `de450af45ff7101b328bb064c6b475f73414a7ed` | `de450af45ff7101b328bb064c6b475f73414a7ed` |

Every downloaded artifact was checked against its frozen byte count and
SHA-256. The formal runner received only lineage group identifiers, capacities,
and pre-outcome gates. Prompt, answer, reference program, model output,
evaluator output, and reserve result values were not projected.

## Candidate audit

| Candidate | Technical tasks | Independent upper bound | Dev | Potential reserve | Sealed reserve | Passed gates | Decision |
|---|---:|---:|---:|---:|---:|---:|---|
| AutoSDT-5K | 5,148 | 1,002 license-labelled repositories | 30 | 972 | 0 | 2/8 | reject |
| ScienceAgentBench | 102 | 44 publications | 30 | 14 | 0 | 3/8 | reject |
| CORE-Bench | 270 | 90 papers | 45 | 45 | 45 | 5/8 | reject |
| QRData | 411 | 190 shared data-file sets | 30 | 160 | 0 | 5/8 | reject |

The required capacity is 30 disjoint development plus 84 completely sealed
reserve source groups.

### AutoSDT-5K

- The frozen release contains 5,148 rows and 1,317 normalized repositories,
  rather than relying on the paper/card headline counts.
- Excluding 315 `None` license labels leaves 1,002 capacity groups, but no
  source-specific license objects were recovered.
- Source URLs point to mutable branches, no frozen per-task scorer is packaged,
  reference programs are public, and no reserve is sealed.

### ScienceAgentBench

- The release contains 102 tasks and 30 directly lineaged repositories; the
  paper-level upper bound is 44 publications.
- Official baseline surfaces exist, but full evaluation mixes execution with
  a GPT-4o visualization judge and best-of-three attempts.
- Redistribution and six special upstream-license cases are not cleared at
  source level. Potential reserve is only 14 and none is sealed.

### CORE-Bench

- Ninety papers produce 270 difficulty variants; the paper, not difficulty,
  is the independent unit.
- The public train split exposes 45 papers and the encrypted test retains 45.
  The encrypted result payload was not decrypted or read.
- The deterministic endpoint and official baseline pass, but 45 reserve
  papers are below 84, capsule rights are unbound, and privileged
  Docker/GPU/cloud requirements fail bounded local compute.

### QRData

- Four hundred eleven questions collapse to 190 shared data-file-set groups;
  the archive contains exactly 195 referenced files.
- The numeric/multiple-choice scorer is deterministic and local workload is
  bounded.
- The global CC-BY-NC-4.0 file does not bind the 195 upstream source sheets,
  official baseline inference code is absent, and answers are co-located with
  questions. The current public release is not a fresh sealed reserve.

## Exact replay

The formal output is retained at:

`runs/manual-live/task26366-replacement-objective-data-tournament-v1/`

Hashes:

- report contract:
  `292899ec660d38490fd95dd40c832e304f6c816a1dd5f9f401b19f6615eea89a`;
- report file:
  `299d7f884e9983b7d72e7c38e3da3b8ca6f7e1307baa539f46342c0bd29e203d`;
- tournament projection:
  `265d8c1b1195f6ad488a2d2fe12dd5133afaeadfd18d109fff56edefd11c7491`;
- decision:
  `ca0697f34a8b70e81beb67bc2960fa5c121615cba556c372307f9209a7bd9d36`;
- replay certificate:
  `40370c725a9450ea3886ce0c72ad658100c27eea5f7a5c5e1a4eafbc08fced99`;
- replay input:
  `a78bdecce72a7e28aa6c30f64a11a69c1435815daaacacd98a2659b3b9f1b1df`;
- frozen runner:
  `a34a4ab5ec95fa5e37fd3f0b03c64830c18cb1449a9bc10788b5266f0707a396`;
- manifest contract:
  `4e4a47495d23f44c3df72cb3005cb4846d5f356f65b606a9677fd1c80013fc9a`.

Clean environments `clean-venv-a` and `clean-venv-b` produced the exact same
projection with zero retry. Their environment hashes are distinct.

## Why the real system is not yet a new method paper

Graph, Harness, Loop, manifests, model calls, experiments, and a compiled PDF
prove that work happened and can be replayed. They do not prove:

- an independent scientific sample;
- legal reuse and redistribution of every source;
- a coherent objective construct;
- a same-budget strongest-baseline effect;
- one-use confirmation on unseen evidence;
- novelty beyond AstaBench, POPPER, Socratic Agents, Kosmos, and
  AI Scientist-v2;
- human responsibility for authorship and release.

This task therefore treats stopping before model execution as the correct
scientific outcome.

## Next task

Task 263.6.7 will freeze a distinct, prospective AI-scientist benchmark-validity
systematic mapping protocol. The four candidates above are pilot/calibration
records and cannot be relabelled as a confirmatory sample.

The next protocol must:

1. define search strings, databases, dates, inclusion/exclusion, release-level
   unit, extraction fields, and stopping rules before extracting new benchmark
   records;
2. target at least 20 independent fixed-revision benchmark releases;
3. code task-to-source compression, four rights scopes, primary endpoint,
   judge role, strong baseline, compute, split seal, and contamination policy;
4. use dual independent human coding for ambiguous license and lineage fields;
5. publish descriptive and sensitivity analyses without changing them into a
   mechanism-effect claim;
6. retain all unknowns and failures in a machine-readable Benchmark Admission
   Card and Open Science package.

Task 260 Route B remains a separate systems-paper candidate for independent
human submission review. New critic/mechanism experiments remain blocked until
a future fresh single-construct panel passes every admission gate.

## Related notes

- [[../../../exploration/replacement-objective-data-tournament-2026]]
- [[../../../exploration/licensed-objective-socratic-inventory-gate-2026]]
- [[../../../exploration/graph-harness-loop-open-science-2026]]
- [[task-263-6-5-socratic-inventory-stop]]
- [[../index]]
