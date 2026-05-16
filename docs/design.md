# Agent-Wiki Architecture Design

> Universal Knowledge System for Multi-Agent Environments  
> v1.1 — 2026-05-16  
> Status: Design target aligned against the current Phase 1 implementation baseline

---

## 0. First Principles

**"Getting smarter" is not about accumulating more knowledge, but about improving behavior.**

In cybernetic terms: knowledge base is the controlled object, agent behavior is the output, feedback loop is the controller. Without feedback, no open-loop system gets better at anything regardless of internal complexity.

**Core question: Where is the closed loop from knowledge to behavior improvement?**

### Four Core Judgments

1. **Compile before retrieve** — Correct. But compiled products must be maintainable, traceable, reusable knowledge artifacts, not fancy summaries.
2. **Skillify is a design principle, not a post-hoc feature** — Knowledge must carry routing semantics from entry into the system.
3. **Hybrid retrieval is the calling skeleton, not an optimization** — A configured coarse retrieval provider finds candidate pages, full-page/section loading provides understanding, and layered presentation controls context cost. Phase 1 defaults to lexical retrieval; vector retrieval is an optional provider.
4. **Schema must be an operation contract, not a directional manifesto** — It must explicitly tell LLM/Agent: which pages to update on new source, what contradictions to mark, when to create vs revise.

---

## 1. Architecture

```text
Git authority
  → local workspace and runtime state
  → capture_raw / compile_update / query / lint / sync / feedback / weekly-review / approvals
  → reviewable JSONL artifacts and markdown pages
  → thin agent transports and adapters
```

### Architecture intent

The target system remains a protocol-centered `aw-agent` with shared core services behind MCP, CLI, and REST. The repository design still assumes:

- one shared core engine
- pluggable storage, retrieval, and content adapters
- Git-first authority
- explicit propagation, maintenance, and approval flows
- multi-agent access through thin clients

### Current Phase 1 implementation baseline

The current implementation in `src/agent_wiki/` delivers a filesystem- and JSONL-backed baseline with the following active subsystems:

- `src/agent_wiki/bootstrap/registry_loader.py`
- `src/agent_wiki/application/capture_raw.py`
- `src/agent_wiki/application/compile_update.py`
- `src/agent_wiki/application/query.py`
- `src/agent_wiki/application/linting.py`
- `src/agent_wiki/application/sync.py`
- `src/agent_wiki/application/feedback.py`
- `src/agent_wiki/application/weekly_review.py`
- `src/agent_wiki/application/approvals.py`
- `src/agent_wiki/application/propagation.py`
- `src/agent_wiki/infrastructure/storage/manifest_repo.py`
- `src/agent_wiki/infrastructure/retrieval/retrieval_index.py`
- `src/agent_wiki/infrastructure/runtime/*`

### Phase 1 simplification

The current runtime does **not** yet expose full MCP or REST transports. The implemented transport surface is still a minimal CLI stub in `src/agent_wiki/transports/cli/app.py`. The design below keeps MCP/REST as target architecture, but all implementation references in this document are explicitly limited to the current `src/agent_wiki/` baseline.

---

## 2. Data Flow Integrity (Anti-Island)

**Design principle: Write = Propagate. A write is not complete until all downstream artifacts are updated.**

### 2.1 Target propagation model

Target propagation still includes:

- page write
- manifest update
- retrieval/provider index update
- conditional review queue creation
- logs and audit trails
- eventual external mirror/sync handling

### 2.2 Implemented propagation model

The current implementation in `src/agent_wiki/application/propagation.py` supports:

- raw page write to `pages/{doc_id}.md`
- manifest append/upsert
- retrieval index append
- `log.md` append
- `operation_log.jsonl` append for compile updates
- `review_queue.jsonl` append for evidence-related cases
- pending raw fallback to `.agent-wiki/pending_manifest.jsonl`

### 2.3 Current write flows

#### A-level raw capture

Implemented in:
- `src/agent_wiki/application/capture_raw.py`
- `src/agent_wiki/application/propagation.py`

Flow:

```text
capture_raw
  → validate allowed page type
  → validate doc_id shape
  → committed path: page + manifest + retrieval_index + log
  → invalid doc_id path: pending_manifest only
```

#### B-level compile update

Implemented in:
- `src/agent_wiki/application/compile_update.py`
- `src/agent_wiki/application/propagation.py`

Flow:

```text
compile_update
  → analyze existing doc_id / problem_cluster
  → validate allowed page type
  → validate source_refs against raw manifest entries
  → write page
  → upsert manifest
  → append retrieval card
  → append operation log
  → optionally append review queue item
  → append log.md
```

#### C-level proposal / approval smoke path

Implemented in:
- `src/agent_wiki/application/approvals.py`

Flow:

```text
propose
  → write .agent-wiki/proposals/{proposal_id}.json
approve
  → load proposal
  → propagate compiled write
  → append approval_log.jsonl
```

### 2.4 Divergence from the target design

The following propagation features are still design targets, not current implementation:

- explicit rollback between page write and manifest write
- `index_stale` markers
- `mirror_pending` markers
- provider-index refresh separate from retrieval index
- mirror push and retry logic
- conflict snapshots and automated reverse-propagation queueing

These are **not contradictions**; they are Phase 1 simplifications of the fuller anti-island design.

---

## 3. Phase Gate System

The architecture still assumes phased gates A/B/C/D.

### Target gate intent

- **A** — raw/source capture validation
- **B** — truth-zone atom/synthesis/dispute changes
- **C** — principle promotion, shared high-risk writes, adjudication
- **D** — long-cycle maintenance and evolution quality

### Current implementation status

- Gate classification exists in `src/agent_wiki/infrastructure/identity/gates.py`.
- A/B/C behavior is partially reflected by service boundaries:
  - raw capture path
  - compile update path
  - approvals path
- Full gate policy enforcement is **not yet implemented**:
  - `max_gate` from permissions is not enforced
  - no central gate-check service exists yet
  - no route-test or content-quality gate execution exists yet

### Design note

Keep the gate model in the design docs. The current code should be read as a baseline that matches the direction of A/B/C separation without yet implementing the full gate engine.

---

## 4. Protocol-Centered Agent Access

### 4.1 Target transport architecture

The design target remains:

```text
Knowledge Agent / aw-agent
├─ MCP Server
├─ CLI / aw
├─ REST API
└─ Shared core services
```

### 4.2 Current implementation status

Current implemented surfaces:

- Python package `agent_wiki`
- minimal CLI stub in `src/agent_wiki/transports/cli/app.py`

Not yet implemented in the current codebase:

- MCP transport package and server
- REST transport package and app
- CLI command surface for the full workflow

### 4.3 Agent identity and permissions

Current implemented components:

- `src/agent_wiki/infrastructure/identity/resolver.py`
- `src/agent_wiki/infrastructure/identity/permissions.py`
- `src/agent_wiki/infrastructure/identity/gates.py`

### Important divergence

The target design says request parameters must not override resolved identity. The current implementation still accepts explicit actor fields in `IdentityContext` and prefers them over metadata. This is a **real implementation gap**, not a design change, and the design docs should continue treating caller override as disallowed target behavior.

---

## 5. Core Engine Mapping to `src/agent_wiki/`

### 5.1 Bootstrap and config

- `src/agent_wiki/bootstrap/registry_loader.py` — YAML registry parsing into `RegistryConfig`, `WikiConfig`, and related models
- `src/agent_wiki/bootstrap/container.py` — minimal service wiring

### 5.2 Capture and compile

- `src/agent_wiki/application/capture_raw.py`
- `src/agent_wiki/application/compile_update.py`
- `src/agent_wiki/application/propagation.py`

### 5.3 Retrieval and query

- `src/agent_wiki/application/query.py`
- `src/agent_wiki/infrastructure/retrieval/retrieval_index.py`

### 5.4 Maintenance loop

- `src/agent_wiki/application/linting.py`
- `src/agent_wiki/application/sync.py`
- `src/agent_wiki/application/feedback.py`
- `src/agent_wiki/application/weekly_review.py`

### 5.5 Approvals and high-risk path

- `src/agent_wiki/application/approvals.py`

### 5.6 Persistence and runtime artifacts

- `src/agent_wiki/infrastructure/storage/manifest_repo.py`
- `src/agent_wiki/infrastructure/runtime/pending_state.py`
- `src/agent_wiki/infrastructure/runtime/review_queue.py`
- `src/agent_wiki/infrastructure/runtime/operation_log.py`

---

## 6. Retrieval Runtime

### Target retrieval design

The target runtime remains:

1. classify query type
2. coarse retrieval through configured provider
3. aggregate by `wiki_id:doc_id`
4. load by policy
5. assemble layered L1/L2/L3 context
6. return with dispute awareness

### Implemented baseline

The current query baseline in `src/agent_wiki/application/query.py` implements:

- heuristic query-type classification
- lexical retrieval over `retrieval_index.jsonl`
- optional pending truth-zone scan when `include_pending=True`
- filtering via manifest/pending manifest
- simple score-based ordering with manifest priority
- L1 answer from top page content
- L2 context with dispute caveat when `review_status=disputed`
- L3 proof using manifest `source_refs`
- cross-wiki fan-out via `CrossWikiQueryService`

### Phase 1 simplification

Not yet implemented in the current runtime:

- provider routing beyond lexical baseline
- vector retrieval plugin integration
- explicit load-policy execution
- query budget enforcement
- query_outcome logging inside the query service itself

Query outcomes are currently recorded through the separate feedback workflow, not automatically by `QueryService`.

---

## 7. Sync and External Views

### Target design

The target Phase 1 architecture still assumes:

- external views are human-facing layers
- external edits flow back into workspace first
- gate-check blocks Git commit, not visibility
- adapters normalize external formats

### Implemented baseline

The current implementation in `src/agent_wiki/application/sync.py` is intentionally minimal:

- `status` lists markdown pages in the workspace
- `pull-view` copies `*.md` files from configured external paths into `pages/`
- `push-view` copies `pages/*.md` to configured external paths

### Deviation note

This is a **simplified Phase 1 filesystem sync**, not full adapter-driven reverse sync. The design should continue to describe richer adapter-based sync as the target model, but must explicitly note that the current implementation is a copy-based placeholder with no gate-to-commit path yet.

---

## 8. Review Queue, Feedback, and Weekly Review

### Target design

The review loop should connect query usage, missing evidence, maintenance pressure, and high-risk knowledge evolution.

### Implemented baseline

Feedback and weekly review are currently implemented as simple JSONL flows:

- `src/agent_wiki/application/feedback.py`
  - appends feedback to `query_outcomes.jsonl`
  - creates `feedback_issue` queue items when evidence is missing or rewrite targets exist
- `src/agent_wiki/application/weekly_review.py`
  - reads `review_queue.jsonl` and `query_outcomes.jsonl`
  - summarizes queue count and feedback count
  - emits suggested actions from queue reasons

### Phase 1 simplification

The current queue items are much smaller than the target review queue contract. They do not yet include the full state machine, assignment metadata, priorities, or conflict snapshots described in the original design.

---

## 9. Shared Wiki and Cross-Wiki Behavior

### Implemented smoke coverage

The current code and tests already demonstrate the following Phase 1 smoke-path behavior:

- multi-wiki registry loading
- shared wiki `allowed_page_types` restrictions
- cross-wiki lexical query aggregation
- C-level proposal/approval write path

These are validated by:

- `tests/test_multi_wiki.py`
- `tests/test_shared_wiki.py`
- `tests/test_cross_wiki_query.py`
- `tests/test_approvals.py`

### Design note

This smoke coverage proves the interface direction is workable, but it is not yet the full transport- and policy-complete system described in the original protocol-centered design.

---

## 10. Known Divergences from Design v1.0

| Area | Design target | Current implementation | Status |
|---|---|---|---|
| Transport surface | MCP + CLI + REST | minimal CLI stub only | Not Yet Implemented |
| Identity resolution | caller cannot override resolved identity | explicit actor fields still override metadata | Divergence to fix |
| Gate enforcement | operation risk + `max_gate` policy | gate classification exists, full enforcement missing | Partial |
| Propagation failure handling | rollback + stale markers + mirror state | direct append/write only | Phase 1 Simplification |
| Retrieval runtime | provider-pluggable, load-policy aware | lexical baseline with layered output | Phase 1 Simplification |
| Sync | adapter-driven reverse sync + gate/commit path | copy-based markdown sync | Phase 1 Simplification |
| Review queue | rich workflow schema | minimal append-only queue items | Phase 1 Simplification |
| Query outcome loop | query service logs outcomes directly | feedback service records outcomes | Simplified |

---

## 11. Recommendation for Readers

When using this document:

- treat the architecture sections as the intended long-lived system shape
- treat the implementation notes as the current Phase 1 baseline delivered in `src/agent_wiki/`
- treat the divergence table as the authoritative map of what still needs to catch up

This keeps the design stable without pretending the current implementation is already the full target system.

---

*Design v1.1 aligned against the current implementation baseline. Use with `core/schema.md`, `docs/requirements-and-architecture.md`, and the tests for current-state review.*
