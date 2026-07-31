---
title: Task 263.6.7.2 benchmark-validity Harness
date: 2026-07-31
status: completed-capability-only
task: "263.6.7.2"
tags:
  - ai-scientist
  - benchmark-validity
  - harness
  - result-blind
  - open-science
---

# Task 263.6.7.2 benchmark-validity Harness

## Completed result

The project now has deterministic bibliographic adapters for arXiv, OpenAlex,
Crossref, and DBLP; content-addressed raw-response and bibliographic stores;
chained append-only PRISMA-S logs; exact paper deduplication; explicit
family/revision pseudoreplication controls; frozen screening forms; 16-sentinel
recall evaluation; and a 42-field empty Benchmark Admission Card packet.

The successful real capability package contains four API responses and four
bibliographic records. It contains no formal census, screening decision,
Admission Card, benchmark outcome, model output, or human identity. The formal
status is `ready-for-capability-only`.

## Verification

- Eight deterministic unit tests passed.
- A real four-source opt-in capability smoke passed after retaining and fixing
  one fail-closed Crossref cursor-initialization attempt.
- Two distinct clean interpreters reproduced the exact projection.
- Ruff and focused Mypy passed.
- Raw/log/artifact/projection tamper and result-bearing runner payloads are
  rejected.

Formal package:

`runs/manual-live/task263672-benchmark-validity-harness-v2/`

- report: `fbb2a633bb57f0bb9f9f1471b58e8b4b8367098923f07c052d712758cbef9a10`;
- projection: `30bdad36006badccca89f335ff092e34c2c7f3a5a4586e5aba982689c7ba8b2d`;
- replay: `29ed35c21eeeea9abf3e6256b717d963d3b8fd797326cd56acd17069b31b77f8`;
- manifest: `688599b0b46c1502c79e9046f53dd96183989f6fcba8134bc8491d26eef18b3f`.

## Remaining gates

Task `263.6.7.2.1` must freeze a pre-extraction additive erratum for Crossref
short-page termination and exact DBLP year-split bindings. Task `263.6.7.3`
then still needs two real independent reviewers and one distinct adjudicator.
Until both gates pass, formal search, coding, field-wide claims, public release,
and submission remain blocked.

## Related

- [[../../../exploration/benchmark-validity-result-blind-harness-2026]]
- [[../../../exploration/benchmark-validity-systematic-mapping-protocol-2026]]
- [[task-263-6-7-1-benchmark-validity-protocol-freeze]]
- [[../index]]
