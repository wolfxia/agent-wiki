# Quality Evaluation and Self-Evolution Design

> Agent Wiki Phase 1.5 — Quality Evaluation Framework
> 2026-05-16
> Status: Design approved, implementation in progress (Phase 1 + maintenance/quality bootstrap)

---

## 0. Purpose and Principle

**The goal is helping agents get stronger, not producing reports.**

A knowledge system that produces dashboards but never changes agent behavior is decoration. The closed loop must run from query/capture → metric drift → automated action → improved retrieval. Every metric in this design must trigger an automated action; otherwise the metric is removed.

This document defines:

- A three-layer six-dimension quality evaluation framework.
- A three-loop self-evolution mechanism (fast / slow / reporting).
- The minimum viable scope for the current iteration.
- What is intentionally out of scope and why.

---

## 1. Three-Layer Six-Dimension Quality Framework

The framework is layered by lifecycle role. Each dimension owns one concrete trigger; without a trigger, the dimension does not enter the system.

### Layer 1 — Usability (can the system be used?)

**1. Retrieval Quality**
- Signals: `hit_rate`, `miss_rate` derived from `query_outcomes.jsonl`.
- Trigger: 3 consecutive zero-hit results for the same query → `quality_signal` review queue item via `FastFeedbackService`.
- `relevance_score` is intentionally dropped from this design. Without ground-truth labels, any relevance score in a single-user wiki is fake precision.

**2. Coverage**
- Signals: number of raw pages per `purpose.md` declared focus topic.
- Trigger: focus topic with zero raw pages → capture reminder surfaced in weekly review.
- Coverage is checked against `purpose.md`, not against an absolute taxonomy.

### Layer 2 — Evolvability (is knowledge growing?)

**3. Compile Rate (cluster-over-threshold, not aggregate ratio)**
- Signal: count of `(topic, problem_cluster)` pairs whose raw page count is above the accumulation threshold but lacks a compiled atom or synthesis.
- Trigger: any such cluster → `compile_suggestion` review queue item via `CompileSuggestService`.
- The aggregate `compiled / raw` ratio is recorded for trend visibility only. It is not a trigger by itself, because a healthy wiki may have many low-importance raw pages that should never be compiled. Acting on the aggregate ratio causes drive-by compilation; acting on per-cluster threshold breaches causes useful compilation.

**4. Connectivity**
- Signals: pages with shared `source_refs` (cross-reference candidates), pages co-occurring in successful queries (co-occurrence candidates), orphan count (pages with zero incoming references).
- Trigger:
  - Cross-reference candidate → `signal_candidate` review queue item via `RelationsService.detect_and_enqueue_cross_references`.
  - Co-occurrence candidate → `signal_candidate` review queue item via `RelationsService.detect_and_enqueue_co_occurrences`.
  - Orphans are reported as a count for trend tracking; no automated trigger because spurious link suggestions are worse than missing links.

### Layer 3 — Health (is knowledge rotting?)

**5. Freshness — Phase 1.5, not now**
- Intended signals: pages exceeding `freshness_sla_days`, last-referenced time per page.
- Reason for deferring: requires a per-page `last_referenced` clock and a configured SLA window per topic, neither of which exists in the manifest yet. Adding it now bloats the baseline. Deferring it does not block any active loop.

**6. Purpose Alignment**
- Signal: ratio of pages whose topic appears in `purpose.md`.
- Trigger: ratio drop surfaced as a weekly review note. No queue item is created because purpose drift is a slow, judgment-driven concern, not a per-day automation target.

### Future dimensions (deliberately deferred)

- **Authority drift** — divergence between Git-authoritative pages and the local workspace beyond pending state. Requires a real Git authority service to be meaningful.
- **Queue velocity** — rate at which review queue items move through `open → assigned → in_progress → resolved → archived`. Requires meaningful traffic; premature on a single-user Phase 1 baseline.

---

## 2. Self-Evolution Loop Architecture

Three loops run at three different cadences. Each loop has a distinct trigger source, a distinct latency target, and a distinct output.

### 2.1 Fast loop — per query (latency: milliseconds)

- Trigger: every call to `QueryService.execute`.
- Action: write a `query_outcomes.jsonl` entry with `query`, `hit_count`, `actor_id`, and one `query_hits.jsonl` row per hit.
- Output: a feedback substrate for the slow loop. The fast loop does not, and must not, raise queue items by itself. Per-query queue churn is noise.

### 2.2 Slow loop — `MaintenanceService` (latency: minutes to hours, on demand or scheduled)

- Trigger: explicit `aw maintain` invocation, or a scheduled tick by an external orchestrator.
- Action: orchestrate existing detectors in deterministic sequence:
  1. `CompileSuggestService.detect_and_enqueue` — raw accumulation per cluster.
  2. `FastFeedbackService.detect_and_enqueue` — repeated zero-hit queries.
  3. `RelationsService.detect_and_enqueue_co_occurrences` — query co-occurrence pairs.
  4. `RelationsService.detect_and_enqueue_cross_references` — shared `source_refs` pairs.
- Output: review queue items (`compile_suggestion`, `quality_signal`, `signal_candidate`) and a `MaintenanceService` summary dictionary.
- No new detectors are added in this iteration. The slow loop wires already-existing code so it actually runs.
- Co-occurrence signal enqueueing is idempotent by `(doc_id_a, doc_id_b)` and rate-limited per maintenance run. Repeated `aw maintain` runs should not keep appending the same `signal_candidate` pairs to `review_queue.jsonl`.

### 2.3 Reporting loop — weekly review + quality report (latency: weekly or on demand)

- Trigger: `aw weekly-review` or `aw maintain --report`.
- Action: read-only aggregation of:
  - `query_outcomes.jsonl` → `query_count`, `hit_rate`.
  - `MANIFEST.jsonl` → `raw_count`, `compiled_count`, `compile_rate`, `orphan_count`.
  - `review_queue.jsonl` → counts per `item_type`.
- Output: a structured `quality_report` dictionary printed by the CLI and returnable via the MCP tool surface.
- The reporting loop does not write to the queue and does not score the wiki. It exposes the state that the slow loop already produced.

### 2.4 Loop boundaries

- Fast loop writes to `query_outcomes.jsonl` and `query_hits.jsonl`.
- Slow loop reads those files plus `MANIFEST.jsonl`, writes to `review_queue.jsonl`.
- Reporting loop reads `query_outcomes.jsonl`, `MANIFEST.jsonl`, and `review_queue.jsonl`. It writes nothing.

This separation guarantees the loops compose without read/write races and that any loop can be replaced independently.

---

## 3. Codex (CC) Feedback Incorporated

The original "three-layer six-dimension" sketch went through implementation review. The following adjustments came out of that review and are now part of this design:

- **Compile rate is per-cluster, not aggregate.** Aggregate ratios penalize healthy wikis with intentionally uncompiled raw archives. Per-cluster threshold breaches map directly to user-actionable suggestions.
- **`relevance_score` dropped from Layer 1.** A single-user wiki has no labels. A computed relevance score is theater.
- **Freshness deferred to Phase 1.5.** No `last_referenced` clock today; adding one to satisfy the framework is over-engineering.
- **Authority drift and queue velocity reserved as future dimensions.** They become meaningful only after authority promotion and multi-actor traffic exist.
- **Reporting is structured data, not a score.** No "health score 85". The framework returns trends, counts, and ratios. Decisions stay with the agent, not a fabricated single number.

---

## 4. Scope of This Iteration

**In scope:**
- `application/maintenance.py` — `MaintenanceService` orchestrator over existing detectors.
- `application/quality_report.py` — read-only aggregator over existing JSONL artifacts.
- `aw maintain` CLI command — runs the slow loop and prints the quality report.
- TDD per piece, separate commits.

**Explicitly out of scope:**
- New detectors of any kind.
- New review queue item types.
- Freshness signals.
- Authority drift signals.
- Queue velocity signals.
- Any visual dashboard or score.
- Any automatic action beyond surfacing queue items the existing detectors already produce.

The first delivery is the smallest closed loop that helps agents get stronger. Anything else is decoration.

---

## 5. Module Boundaries

```text
fast loop:
  QueryService.execute  →  query_outcomes.jsonl, query_hits.jsonl

slow loop:
  MaintenanceService.run
    ├─ CompileSuggestService.detect_and_enqueue
    ├─ FastFeedbackService.detect_and_enqueue
    ├─ RelationsService.detect_and_enqueue_co_occurrences
    └─ RelationsService.detect_and_enqueue_cross_references
                                                  →  review_queue.jsonl

reporting loop:
  QualityReportService.generate
    ├─ reads query_outcomes.jsonl
    ├─ reads MANIFEST.jsonl
    └─ reads review_queue.jsonl
                                                  →  structured dict
```

`MaintenanceService` is a thin composition; it does not encapsulate detection logic. `QualityReportService` is read-only; it does not encapsulate triggers. Both stay small on purpose so future loops can replace them without unwinding policy.

---

## 6. Verification

- `MaintenanceService.run` is verified by an integration test that seeds raw accumulation, zero-hit queries, and shared `source_refs`, then asserts that all four detectors produced queue items.
- `QualityReportService.generate` is verified by per-metric tests against fixture data: hit_rate, compile_rate, orphan_count.
- `aw maintain` is verified by a CLI smoke test that exercises the command and inspects stdout for the structured report.
- The full suite must remain green after each commit.

---

## 7. Decision Boundaries Reaffirmed

- Git remains the authority of record. `MaintenanceService` and `QualityReportService` never write authoritative pages.
- Sensitivity policy still applies. `QualityReportService` does not bypass `max_sensitivity` filtering when reading manifest entries that surface in any agent-visible response.
- `purpose.md` remains the source of focus topics; the reporting loop reads it via `PurposeReader`, not by re-parsing.
- Review queue stays a general task queue, not a quality-only queue. Adding a quality dashboard would have implied a new private queue, which is rejected.
