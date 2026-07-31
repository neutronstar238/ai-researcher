---
title: Task 263.6.5 DiscoveryBench Socratic inventory stop
date: 2026-07-31
status: completed-stopped-at-inventory
task: "263.6.5"
tags:
  - autoresearch
  - ai-scientist
  - discoverybench
  - provenance
  - pseudoreplication
  - licensing
  - negative-result
---

# Task 263.6.5 DiscoveryBench Socratic Inventory Stop

## Outcome

Task 263.6.5 completed at its first prospective stop gate. The selected
DiscoveryBench Socratic route does not have enough independent source groups
for the frozen design, so no evaluator, fault generator, baseline, model
configuration, Research Question Certificate, or confirmation panel was
created.

The formal decision is:

`stopped-at-inventory → return-to-objective-data-opportunity-tournament`.

This is a valid task outcome, not an incomplete model experiment.

## Result-blind boundary

The inventory froze:

- `allenai/discoverybench`;
- revision `e54ec033049d3a0fd95d3c746919cc8c01c25781`;
- 987 tree entries;
- answer-key dataset names and key columns only;
- DiscoveryBench database-license evidence;
- AstaBench software-license evidence;
- seven primary research sources;
- the prospective `30 development + 84 untouched reserve` gate.

The frozen replay input excludes gold-hypothesis text, data contents, metadata
bodies, development outcomes, critic outputs, and model outputs. It ran with
zero retry in two distinct clean interpreter installations.

## Independent-unit audit

| Quantity | Observed |
|---|---:|
| Provisional folders | 189 |
| Real / synthetic folders | 14 / 175 |
| Train / test folders | 104 / 85 |
| Conservative real source groups | 8 |
| Conservative synthetic semantic-tree groups | 99 |
| Conservative source groups | 107 |
| Conservative train groups | 67 |
| Conservative test groups | 41 |
| Cross-split groups | 1 |
| Maximum reserve after 30 development groups | 41 |
| Optimistic development upper bound | 103 |
| Optimistic reserve upper bound | 81 |

The primary gate requires 84 untouched reserve groups. Both the conservative
result (`41`) and optimistic upper bound (`81`) fail.

The key methodological correction is that multiple difficulty datasets from
one synthetic semantic tree, and raw/processed/subset folders from one real
source, are not new scientific units. Seeds, repeats, interpreters, and agents
also cannot replace missing source groups.

## Answer-key and license audit

All 85 test folders have answer-key dataset-key lineage:

- real key: 239 rows across 10 dataset names, strict `utf-8-sig`;
- synthetic key: 200 rows across 75 dataset names, strict
  `windows-1252`;
- retained gold-hypothesis text: none.

DiscoveryBench's ODC-By evidence supports attributed database use but does not
license software or independently clear rights in individual contents.
AstaBench's Apache-2.0 evidence applies to software only. Public content
redistribution remains human-review gated.

## Formal artifacts

The formal live run is retained at:

`runs/manual-live/task26365-socratic-inventory-v3/`

Hashes:

- report:
  `a01303685e1aa4ee2d6ef19f75b5ca01cf3694bc58075008d78840d9bab1d75e`;
- manifest contract:
  `8253096b08a8c44c6ec99ea9286872efe76b23f376ce63097ebebb561b6e7ed2`;
- manifest file:
  `e5eb5aec6f22c6c7d661dc7c154aa97a90ab0d5f7c6d54fe729faa289135fd1e`;
- projection:
  `8ec78def64fcdc4934d69cc8371d9c05a95c21299cde19ad8e00650bc46474f3`;
- replay certificate:
  `02af0e8a089104da4f77e65ad9a90055aacc46e6e47d4736ebc08fa8fb2edc9b`;
- replay input:
  `01cb2537f55a28a39f6a7174a6b772391ab5f9682a5b1d39bf9698ace54f4545`;
- frozen inventory runner:
  `efe05a01434bffae461a2e2facf8afd25b085052c184ba291ebaf13e54131238`.

Both interpreters produced the exact same projection with no retry and no
development-outcome access.

## Fail-closed boundaries

The report fixes all of the following to false:

- independent-unit gate passed;
- fault generator implemented;
- objective evaluator implemented;
- evaluator construction authorized;
- baseline execution authorized;
- provider configuration collected;
- Research Question Certificate issued;
- confirmatory panel created or read;
- public content release gate passed;
- public release authorized;
- external submission authorized.

## Next task

Task 263.6.6 must run a replacement objective-data opportunity tournament
before any model experiment. Candidate sources include AutoSDT-5K,
ScienceAgentBench, CORE-Bench, and QRData, but no winner is preselected.

Every candidate must first prove:

1. at least 30 disjoint development source groups and 84 sealed reserve source
   groups after repository/publication/data-lineage clustering;
2. per-task or per-source license evidence without assuming that an
   unlicensed public repository permits reuse;
3. executable deterministic primary labels;
4. a coherent single construct and clean strong baseline;
5. bounded local workload feasibility.

ScienceAgentBench's 44 publication groups and CORE-Bench's 90 paper groups are
individually below the 114-unit design. AutoSDT has enough apparent
repository diversity, but its official card records 317 repositories without
license information; those records must be excluded unless independent
permission evidence is recovered. QRData's 411 questions still require
source-sheet provenance and license clustering.

No provider credential, evaluator, critic, new RQ, or panel may be introduced
until one candidate passes this inventory gate.

## Related notes

- [[../../../exploration/licensed-objective-socratic-inventory-gate-2026]]
- [[../../../exploration/workload-qualified-ai-scientist-opportunity-tournament-2026]]
- [[task-263-6-4-workload-qualified-opportunity]]
- [[../index]]
