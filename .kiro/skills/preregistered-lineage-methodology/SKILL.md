---
name: preregistered-lineage-methodology
description: Run a preregistered, budget-bounded search lineage whose result cannot be selected after the fact. Use when a model must author and measure its own method against a fixed baseline and the outcome has to survive scrutiny, including when the outcome is null or negative.
---

# Preregistered lineage methodology

A lineage is one bounded attempt to measure a method against a fixed baseline, where
every choice that could bias the result is committed BEFORE any number is visible.

This skill is domain-agnostic on purpose. It says nothing about what the systems,
cohorts, or strata are. Domain specifics belong in a separate skill or in the panel
data. The lesson that produced this file: an earlier implementation hardcoded one
benchmark's taxonomy into field names like `pilot_ode_count`, which made the general
rule unusable anywhere else.

## Stage order, and why the order is the point

    freeze -> preregister -> plan -> approve -> generate -> smoke -> pilot
        -> revise -> baseline -> full -> adjudicate

* **freeze** pins the runtime, the data hashes, and the runner bytes. A lineage that
  can silently change its substrate mid-flight measures nothing.
* **preregister** commits panel exclusions and per-stage breadth while the numeric
  payload is still unopened. Verify this by FILE ORDERING, not by the artifact's own
  claim that it was written first. A self-declaration is not a proof.
* **approve** is a gate that must refuse in three states: no record, valid record,
  and record-that-no-longer-matches-the-plan. Test all three; a gate only proven in
  the happy state is not a gate.
* **smoke** proves each candidate can execute at all, per stratum, before the
  expensive stage. See "Promotion gates" below.
* **adjudicate** evaluates every frozen check and issues a receipt only if all pass.

## Invariants worth enforcing in code, not prose

**Exclusions must bind to what executes.** A preregistered exclusion that only
appears in the plan is decorative. If a coverage check requires every baseline cell to
succeed, and an excluded member's cells still run and still fail, the check stays
false and the exclusion accomplished nothing. Enforce the exclusion at the point where
work units are built.

**Preregistered breadth may only shrink.** Otherwise a "new preregistration" becomes a
way to buy more budget than the frozen parent allowed.

**A stratum may never be dropped to zero.** Reducing a stratum to no members is a
change of question, not a narrowing of breadth. Refuse it.

**Never rewrite a frozen parent.** When a frozen parameter turns out to be
unsatisfiable, supersede it with a child artifact that BINDS the parent's numbers as
evidence, and leave the parent byte-identical. Assert the parent file is unchanged.

**A budget ledger must span stages.** Per-stage accounting lets a lineage overspend
across stages while every individual stage looks conformant.

**Retain every failure.** A discarded failure is a silently selected result.

## Promotion gates

Rank-then-promote is not enough. If an earlier stage runs a candidate's PREVIOUS
version, a revised version can reach the expensive stage having never executed once,
and one unconditional crash then dominates the measurement.

Gate promotion on execution EVIDENCE, and cover every stratum:

* Take one representative work unit per `(candidate, stratum)` pair. Keying on
  candidate alone silently covers only whichever stratum sorts first.
* A qualifying candidate's smoke units are real units of that stage. Merge them into
  the record instead of re-running them, so a healthy candidate pays nothing.
* Keep refusal ALL-OR-NOTHING per candidate. Refusing only the stratum a candidate
  fails would let it dodge the members it loses on, which is cherry-picking.
* REPORT the per-stratum outcome before the remaining units run, including a warning
  when a candidate cannot run a whole stratum.

Measured effect of getting this right: refusing one crashing candidate after 6 units
instead of 72 saved 66 units; a stratum-blind version of the same gate let a candidate
pass on one stratum and then fail all 12 units of the other.

## Verify a result before reporting it

A negative is easy to dismiss as a bug, and a positive is easy to accept too readily.
Check all four before writing either down:

1. **No unit sits at the failure-loss cap.** Otherwise the effect is partly a crash
   penalty rather than a measurement.
2. **The losses vary.** A single repeated value, or a metric pinned at exactly its
   normalisation constant, usually means a constant predictor rather than a fit.
3. **Complexity is real.** Term or parameter counts should span a range.
4. **A shuffled-target control changes the artifact.** If shuffling the training
   target leaves the fitted artifact identical, the method never read its target and
   the number is meaningless.

## Stopping, and honest negatives

Decide the stop rule before you see the numbers, and record stopping as a DECISION
with its reasoning, not as something that merely happened.

Drawing further lineages until a favourable number appears is selecting the outcome.
If independent candidates converge on the same near-zero or negative effect, that
convergence IS the finding. A tight interval that lies mostly below zero is an
informative null, not an underpowered shrug, and it is publishable as such.

Separate two things in every report, because they diverge:

* **Structural claims**: did the machinery work, reproducibly?
* **Scientific claims**: did the method beat the baseline?

A lineage can succeed completely on the first and return a negative on the second.
Reporting them as one number hides both.

## Who authors what, and why the boundary matters

If the system produces the numbers but a human writes the framing, the deliverable is a
hybrid presented as one artifact. Check this explicitly rather than assuming: grep the
plan and report generators for a model call. A generator with no model call is a
template, and its prose is whoever wrote the template.

Have the system author every prose field. Keep deterministic only what is not science:

* **Identifiers** are not science.
* **Evidence references must be derived from artifacts that exist on disk.** If the
  model supplies them it can cite a package that was never written, and a plan citing
  non-existent evidence is worse than one citing none.
* **Frozen constraints are passed in as context, never re-authored.**

Then grade what comes back, and make each refusal actionable.

## Build graders that teach, and validate the graders themselves

A grader that only says "no" teaches nothing. Return the exact finding that caused the
refusal, and tell the model to change only what the findings name. Bound the attempts so
a non-conforming model fails loudly instead of spinning, and never quietly downgrade a
refused artifact into an accepted one.

Guards worth having on authored prose:

* **Numeric traceability.** Every number in the prose must exist in the supplied
  evidence, registered at full precision and at several decimal roundings. This is what
  makes "system-authored" mean something rather than "fluent narrative around invented
  numbers".
* **Falsifiability.** The expectation must state what observation would REFUTE it and
  acknowledge that a null result is valid. A plan describing only success is an
  announcement.
* **No result before observation.** Match only PAST-TENSE assertions. "is expected to
  outperform" is a correct expectation; "the results showed" is a claimed outcome.
* **An adversarial field must be adversarial.** If you ask for the strongest argument
  against the conclusion, require it to cite a quantity that WEAKENS the reading, and
  refuse it if it cites only the same quantities as the supporting section. Otherwise
  the field is satisfied by fluent restatement, which is what happened on the first
  live run.

**Validate a guard against real system output before trusting it.** Every guard defect
found here was invisible until a live run: a number pattern that allowed a trailing
decimal point extracted "7." from a sentence ending, and an achieved-result regex
flagged "outperforms" inside a legitimate expectation. A guard that refuses correct work
teaches the system to avoid correct behaviour, and to anyone reading the logs it is
indistinguishable from a broken system.

**Teach the standard before enforcing it.** If a grader looks for specific literal
tokens, say so in the prompt. Penalising a requirement the system was never told is
noise, not signal.

**Relax narrowly.** A plan legitimately performs budget arithmetic, so products and sums
of evidence integers should be reachable there. That same relaxation must NOT apply to
result interpretation, where every number is a measured value and must match exactly.

## Provenance rules that keep an audit honest

* Reasoning traces are process provenance, never evidence. Flag them so they can never
  satisfy an evidence gate or a publication claim.
* An agent-signed approval is not a human review. If an agent exercises delegated
  authority, record the delegation, the exact authorized scope, and the explicit
  non-authorizations, so nobody reads it as scientific endorsement.
* Never combine two candidates' per-member results into one reported effect. That
  fabricates a result neither produced.
* Never hand-repair the code being measured. The moment you fix the candidate's logic
  yourself, the measured effect is yours rather than the system's.
