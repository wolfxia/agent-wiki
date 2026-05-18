# Agent-Wiki Architecture Design

> Universal Knowledge System for Multi-Agent Environments  
> v0.2.0 — 2026-05-17  
> Status: Design baseline aligned against the current Phase 1 implementation, including real FastMCP transport, shared access policy, explicit Obsidian push-view, and the unified knowledge-system architecture spec

> Authority note: `docs/specs/knowledge-system-architecture.md` is the authoritative end-state architecture spec. This document must distinguish current baseline from target design explicitly.

---

## 0. First Principles

**"Getting smarter" is not about accumulating more knowledge, but about improving behavior.**

In cybernetic terms: knowledge base is the controlled object, agent behavior is the output, feedback loop is the controller. Without feedback, no open-loop system gets better at anything regardless of internal complexity.

**Core question: Where is the closed loop from knowledge to behavior improvement?**

### Four Core Judgments

1. **Compile before retrieve** — Correct. But compiled products must be maintainable, traceable, reusable knowledge artifacts, not fancy summaries.
2. **Skillify is a design principle, not a post-hoc feature** — Knowledge must carry routing semantics from entry into the system.
3. **Hybrid retrieval is the calling skeleton, not an optimization** — A configured coarse retrieval provider finds candidate pages, full-page/section loading provides understanding, and layered presentation controls context cost. Phase 1/v0.2 defaults to FTS5+jieba when `.agent-wiki/retrieval.db` exists, merges structured `topic_index.md` hits, and falls back to JSONL lexical retrieval; vector retrieval is an optional provider.
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
- `src/agent_wiki/application/retrieval_router.py`
- `src/agent_wiki/application/migration.py`
- `src/agent_wiki/application/maintenance.py`
- `src/agent_wiki/application/relations.py`
- `src/agent_wiki/infrastructure/storage/manifest_repo.py`
- `src/agent_wiki/infrastructure/retrieval/retrieval_index.py`
- `src/agent_wiki/infrastructure/retrieval/sqlite_fts.py`
- `src/agent_wiki/infrastructure/retrieval/topic_index.py`
- `src/agent_wiki/infrastructure/retrieval/index_consistency.py`
- `src/agent_wiki/infrastructure/runtime/*`

v0.2 also adds `aw migrate --normalize-doc-ids` for lowercase/hyphen `doc_id` normalization and the `knowledge-graph.html` visualizer backed by sigma.js and ForceAtlas2.

### Phase 1 transport baseline

The current runtime now exposes a real FastMCP stdio server and workflow-complete transport set. The codebase includes:

- `aw serve` as the primary stdio service entrypoint
- `aw-agent` as an alias for the same service identity
- a real FastMCP stdio server named `agent-wiki`
- a six-tool MCP surface: `wiki.query`, `wiki.capture_raw`, `wiki.compile_prepare`, `wiki.compile_update`, `wiki.lint`, `wiki.sync`
- workflow-complete CLI and REST surfaces over the same shared core
- explicit `sync` separation so `compile_update` still writes only internal authority/workspace state

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

### 2.2A Current baseline vs target design

Current baseline:

- raw capture can fall back to pending on invalid `doc_id`
- imported raw content can still arrive with weak metadata continuity
- propagation updates authority and runtime artifacts, but does not yet guarantee compile-ready raw metadata on every intake path

Target design:

- pending is failure or blocked-promotion state only
- accepted raw evidence belongs in `MANIFEST.jsonl` even when metadata confidence is low
- compile-ready metadata continuity is part of the propagation contract, not a later cleanup step

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

### 2.5 Compile pipeline from raw to truth zone

The compile pipeline is the Phase 1 path from accumulated raw evidence into maintainable `atom` and `synthesis` truth-zone pages. The primary consumer is the next AI agent, not a human reader. Humans can read the compiled artifacts, but their main value is improving agent retrieval, reasoning, and second-order curation. The runtime must not treat a large raw cluster as a single prompt-sized unit, and it must not embed an LLM inside the core service.

Chosen Phase 1 combination:

- **Granularity: sub-cluster first.** A large `(topic, problem_cluster)` is split into deterministic sub-clusters. Each sub-cluster is prepared as an `atom` candidate; atoms can later support a synthesis for the broader cluster.
- **Trigger: maintain prepares and queues.** `maintain` detects compile-ready clusters and writes review queue work items that contain enough raw doc ids for an agent to act. It does not directly create truth-zone pages.
- **Content generation: agent-driven.** `wiki.compile_prepare` returns an agent-facing evidence packet: bounded raw evidence, extracted claim candidates, relationship hints, contradiction markers, source refs, and proposed output metadata. `aw compile-execute` bridges the queue to external cron workers: it claims suggestions and emits JSON packets, then accepts generated content through `--input-file` and applies `wiki.compile_update`. Hermes, Claude Code, or another agent owns the actual LLM generation outside Agent Wiki.
- **Incremental strategy: delta atom plus later synthesis revision.** New raw evidence creates additional atom candidates. Synthesis revision remains a separate B-level compile update, not an automatic side effect.
- **Source refs: automatic from prepared raw pages.** Prepared items expose `wiki_id:doc_id` refs, and compile suggestions carry the same doc ids so compiled pages stay traceable to Git-tracked raw pages.

This design answers the current backlog problem without making `maintain` fabricate truth-zone content. `maintain` remains a deterministic queue producer; agents remain responsible for semantic synthesis. Compiled output should read like working memory: concise claims, applicability boundaries, evidence links, conflicts, and retrieval cues, not a blog post.

Implementation boundaries for Phase 1:

- `wiki.compile_prepare` is a read-only MCP tool over the shared service layer.
- `aw compile-execute` is a CLI-only executor bridge for cron workers; it does not contain an LLM dependency.
- CLI/REST may expose the same service for operator and dashboard use, but MCP is the primary agent interface.
- Review queue consumption changes state (`open -> assigned -> in_progress -> resolved -> archived`) and records the consumer; it does not execute compile content generation by itself.
- `compile_update.analyze()` stays a baseline revise/create heuristic. Automatic compile preparation should pass explicit proposed doc ids and source refs rather than relying on analyze alone for batching decisions.
### 2.6 Typed knowledge graph

Phase 1 also maintains a deterministic typed knowledge graph for agent reasoning. The graph is not a human navigation feature first; it is a compact relation layer that helps agents answer questions such as who founded a project, which companies compete, or which technology depends on another technology without asking an LLM to infer every relation at query time.

Implemented flow:

```text
relation_schema.yaml
  -> regex RelationExtractor over raw pages
  -> knowledge_graph.jsonl
  -> RetrievalRouter graph hits
  -> wiki.query hybrid ranking with graph_score
```

`relation_schema.yaml` lives in the wiki root and is intentionally user-configurable. If it is missing, maintain skips graph extraction and query falls back to existing FTS/lexical/structured retrieval. `knowledge_graph.jsonl` stores one relation per line with subject, relation, object, entity types, `source_doc_id`, confidence, and extraction timestamp. Symmetric relation types write both directions so query can traverse either side.

A template is available at `templates/relation_schema.yaml`; domains should copy and edit it rather than hardcoding personal topics or entity vocabularies in source code.


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
- `PermissionService` now enforces required operation gate versus per-rule `max_gate` for matched permissions.
- The full gate engine is still incomplete:
  - no workflow-complete route-test execution
  - no content-quality gate execution for C-level decisions
  - no single end-to-end gate orchestration layer spanning every transport and approval path

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
- CLI commands in `src/agent_wiki/transports/cli/app.py` including `info`, `serve`, `query`, `capture-raw`, `compile-update`, `lint`, `sync`, `feedback`, `weekly-review`, `approvals`, and `maintain`
- workflow-complete REST app in `src/agent_wiki/transports/rest/app.py` covering query, capture, compile, lint, sync, feedback, weekly review, and approvals
- real FastMCP stdio MCP server in `src/agent_wiki/transports/mcp/server.py`
- `aw-agent` alias entrypoint bound to the same service identity as `aw`

### Current architecture guarantees

The current Phase 1 baseline keeps the same layered architecture and now standardizes the service boundary more clearly:

- `aw serve` is the primary stdio service entrypoint
- `aw-agent` is an alias for the same service identity
- FastMCP hosts the real MCP server named `agent-wiki`
- trusted identity is resolved by transport context, not caller-supplied tool params, for MCP and REST; CLI prefers explicit local identity/config over metadata fallback
- shared registry permissions explicitly cover `hermes`, `openclaw`, `claude-code`, with `codex` reserved as a lower-trust profile
- Obsidian `push-view` remains explicit `sync`, not an implicit side effect of `compile_update`

### 4.3 Agent identity and permissions

Current implemented components:

- `src/agent_wiki/infrastructure/identity/resolver.py`
- `src/agent_wiki/infrastructure/identity/permissions.py`
- `src/agent_wiki/infrastructure/identity/gates.py`

### Important divergence

- The target design says request parameters must not override resolved identity. The current implementation now enforces transport-trusted metadata precedence for MCP and REST, while CLI prefers explicit local identity/config over metadata fallback. This closes the main caller-override risk for remote/shared transports.
- `max_gate` enforcement now exists in `PermissionService`, but the full workflow gate engine is still incomplete. Stronger content-quality and route-test style gates remain governance work beyond the current baseline.

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

## 6. Query Quality as a First-Class Concern

### Why this must be explicit

The prior design emphasis on governance, authority, and risk gates remains valid, but Tao’s critique is directionally correct for the actual Phase 1 operating context: **Phase 1 is one person with five agents, not five people sharing one governed platform.**

That changes the priority order.

A knowledge system that cannot reliably return useful answers is not saved by having a stronger gate model. For the real Phase 1 workflow, **query quality is the lifeline**:

- if retrieval is weak, the knowledge base is not trusted
- if the knowledge base is not trusted, agents and humans bypass it
- if it is bypassed, governance and audit paths become irrelevant because the system is no longer in the loop

### Combined position from the three reviews

- **Codex is right** that identity, `max_gate`, provenance, and deployment truthfulness are real architectural gaps.
- **CC is right** that those gaps must be documented as blockers rather than glossed over.
- **Tao is right** that, for Phase 1 usefulness, retrieval quality and adoption paths rank above governance completeness.

The combined architectural position is therefore:

1. **Usability-first for Phase 1** — retrieval quality and Obsidian-connected workflow are P0 because they determine whether the system is used at all.
2. **Governance-hardening for Phase 1.5 / stronger claims** — content-quality gates, complete `access_policy` handling, transport-aware filtering, and authority promotion remain blockers before stronger multi-agent governance claims.
3. **Do not collapse these into one priority bucket** — “must be usable” and “must be governable” are both real, but they matter at different points in the adoption curve.

### Target retrieval quality requirements

Phase 1 retrieval should no longer be described merely as a lexical baseline. It should be described as a **usable local retrieval baseline** with concrete quality expectations:

- stronger Chinese lexical handling through FTS5+jieba where available, with JSONL lexical fallback
- fuzzy keyword matching for near-miss query terms
- weighted ranking for title/topic/problem-cluster/keyword overlap
- hit/miss instrumentation on every query path
- explicit tracking of repeated low-value queries as maintenance signals

### Phase 1 implementation status

Implemented today:

- FTS5+jieba primary retrieval when `.agent-wiki/retrieval.db` exists; JSONL lexical fallback remains
- CJK tokenization in `src/agent_wiki/infrastructure/retrieval/tokenizer.py`
- simple fuzzy matching in `src/agent_wiki/infrastructure/retrieval/fuzzy.py`
- weighted lexical scoring across topic, problem cluster, and content
- implemented routing through `StructuredIndexProvider`, `TopicIndexRepository`, `SQLiteFTSIndexProvider`, and `RetrievalRouter`
- heuristic query classification
- layered L1/L2/L3 response assembly
- dispute caveats in query output
- optional pending truth-zone inclusion

Not yet implemented, but still promoted in architectural priority:

- load-policy-aware context assembly and budget enforcement
- vector retrieval plugin integration
- drift detection when hit quality degrades over time

### Design implication

This means the design should stop treating query quality as an implementation detail beneath governance. For Phase 1, retrieval quality is part of the core architecture because it determines whether the feedback loop ever receives meaningful usage.

---

## 7. Knowledge Lifecycle Automation

### Why automation matters

The current raw → atom/synthesis compile chain is architecturally sound, but Tao’s criticism is correct: the practical threshold for `compile_update` is too high for the actual agent mix.

In the current Phase 1 reality:

- T3 agents can capture raw but not compile
- Hermes now shares the same MCP workflow surface as the other T1/T2 agents
- Claude Code is capable but session-ephemeral
- humans are unlikely to manually curate the compile boundary consistently

Without automation, the most likely failure mode is:

```text
raw accumulates → compile_update is under-triggered → atom/synthesis stay sparse → query quality stagnates
```

That would reproduce the same failure pattern the project was created to solve.

### Target lifecycle automation model

Phase 1 should therefore include a **lightweight automation layer** for knowledge evolution, even before full governance hardening lands.

#### 7.1 Auto-compile suggestions

When raw pages on the same `topic` or `problem_cluster` accumulate past a threshold, the system should automatically create a compile suggestion.

Target behavior:

- threshold rule such as “N raw pages on the same topic”
- create review queue / suggestion entry rather than blindly mutating truth-zone pages
- route the suggestion to a T2+ executor or approval path

This keeps the compile chain active without requiring full autonomy.

#### 7.2 Fast feedback loop

Weekly review remains useful for trend analysis, but it is too slow to be the only control loop.

Target behavior:

- three consecutive low-score or low-value query outcomes trigger a compile suggestion
- sustained drop in hit rate triggers lint + reindex or retrieval-quality investigation
- weekly review becomes the slow loop for trends, while fast feedback handles immediate drift

#### 7.2.1 Quality evaluation and self-evolution loop

The lightweight automation layer above is governed by a separate quality-evaluation design. See `docs/superpowers/specs/2026-05-16-quality-evaluation-design.md` for the full three-layer six-dimension framework, the three-loop architecture (fast / slow / reporting), and the explicit scope for the current iteration (`MaintenanceService`, `QualityReportService`, `aw maintain`). The quality-evaluation design is the authoritative source for what dimensions are tracked, what triggers fire, and what is intentionally deferred. This section only summarizes its placement in the lifecycle.

Two non-negotiable rules govern that design:

- **Helping agents get stronger, not producing reports.** Every metric must trigger an action, otherwise the metric is removed.
- **No fake precision.** The framework returns trends, counts, and ratios. There is no aggregate health score. Decisions stay with the agent.

#### 7.3 Purpose-driven knowledge evolution

Tao is also correct that `purpose.md` is currently underweighted.

`purpose.md` should be treated as the intent anchor for the whole wiki, not just metadata:

- influences query priority and ranking
- influences compile direction when multiple raw clusters compete for attention
- influences archival or de-prioritization of irrelevant content
- anchors C-level judgment about whether a principle belongs in this wiki

Without that, the system risks becoming a gated file manager rather than a purpose-shaped knowledge system.

#### 7.4 Obsidian-connected adoption path

For Phase 1 adoption, Obsidian sync should not be framed as a nice-to-have external integration. It is the practical human entry path.

That means Phase 1 should aim for:

- ObsidianAdapter as a real deliverable, not only a design placeholder
- external edits flowing back into workspace in a way the lifecycle loop can see
- at minimum: Obsidian edit → raw capture path → compile suggestion / compile trigger

The approved next milestone sharpens that design boundary further:

- `compile_update` still writes only internal authority/workspace artifacts
- Obsidian export happens only through explicit `sync`
- `push-view` for Obsidian gains adapter-aware export plus a configurable derived graph index page; the default is `knowledge-graph/index.md`

#### 7.5 Candidate relations as differentiator

The 4-Signal relation system should also be reframed.

Without relation discovery, the system is structurally close to a governed file store. Candidate relations are part of what makes it a knowledge engine.

Phase 1 should therefore aim for at least:

- co-occurrence signal
- cross-reference signal

These can write to a suggestions artifact without mutating authoritative relationships until reviewed.

### Phase 1 implementation status

Implemented today:

- raw capture path
- manual/explicit compile update path
- feedback capture
- weekly review summary

Not yet implemented, but now promoted in priority:

- auto-compile suggestions
- fast feedback triggers from repeated low-value queries
- purpose-driven ranking / compile prioritization
- ObsidianAdapter-backed reverse flow beyond file copy
- low-cost candidate relation discovery

---

## 8. Retrieval Runtime

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
- retrieval through `RetrievalRouter`: FTS5+jieba primary when `.agent-wiki/retrieval.db` exists, JSONL lexical fallback when FTS returns no hits, and structured `topic_index.md` merge
- optional pending truth-zone scan when `include_pending=True`
- filtering via manifest/pending manifest and `QueryInput.max_sensitivity`
- score-based ordering with `lexical_score`, `structured_score`, `page_type_boost`, `purpose_boost`, `freshness`, and `manifest_priority`
- L1 answer from `topic_index.md` summary first, then manifest summary, then top page content
- L2 context with dispute caveat when `review_status=disputed`
- L3 proof using manifest `source_refs`
- cross-wiki fan-out via `CrossWikiQueryService`

### Phase 1 simplification

Not yet implemented in the current runtime:

- vector retrieval plugin integration
- explicit load-policy execution
- query budget enforcement

Query outcomes are now recorded directly by `QueryService`, while feedback appends additional human-evaluation records into the same `query_outcomes.jsonl` stream.

---

## 9. Sync and External Views

### Target design

The target Phase 1 architecture still assumes:

- external views are human-facing layers
- external edits flow back into workspace first
- gate-check blocks Git commit, not visibility
- adapters normalize external formats

### Implemented baseline

The current implementation in `src/agent_wiki/application/sync.py` supports:

- `status` listing markdown pages in the workspace
- `pull-view` import through adapter-aware external view handling, recursive `rglob`, `.obsidian` / trash-folder ignores, vault-relative-path-based `doc_id` generation, and frontmatter date sanitization
- `push-view` export through adapter-aware external view handling
- optional `doc_ids` for incremental export
- Obsidian frontmatter preservation on push-view
- retrieval index, FTS, and `topic_index.md` updates on imported pages
- category-routed Obsidian export using `external_views[].push_view_routing`; generic defaults are `raw`, `atoms`, `synthesis`, `principles`, and `knowledge-graph`
- derived graph index export at configurable `graph_index_folder/index.md`, defaulting to `knowledge-graph/index.md`

### Current boundary guarantee

The implemented design does **not** merge sync into compile. Instead it upgrades the sync boundary itself:

- `wiki.sync` is a first-class MCP tool alongside CLI `aw sync`
- `push-view` remains explicit and may optionally target `doc_ids` for incremental export
- Obsidian `push-view` exports a derived graph index page to the configured graph index folder
- the graph index remains an external-view artifact, not a new authority page type

### Deviation note

This remains a **Phase 1 sync simplification** in one narrower sense: there is still no full gate-to-commit authority promotion path for external synchronization. The architecture direction and current runtime behavior are already aligned on the key boundaries: `compile_update` and external export stay decoupled, and Obsidian-specific graph material belongs to the view layer only.

---

## 10. Review Queue, Feedback, and Weekly Review

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

## 11. Shared Wiki and Cross-Wiki Behavior

### Implemented smoke coverage

The current code and tests already demonstrate the following Phase 1 smoke-path behavior:

- multi-wiki registry loading
- shared wiki `allowed_page_types` restrictions
- cross-wiki lexical query aggregation
- C-level proposal/approval write path

The approved next milestone formalizes the shared-agent registry baseline for one personal multi-agent workspace:

- `hermes`: T1, `max_gate=C`
- `openclaw`: T1, `max_gate=C`
- `claude-code`: T2, `max_gate=B`
- `codex`: T3 reserve profile, `max_gate=A`

These are validated by:

- `tests/test_multi_wiki.py`
- `tests/test_shared_wiki.py`
- `tests/test_cross_wiki_query.py`
- `tests/test_approvals.py`

### Design note

This smoke coverage proves the interface direction is workable, but it is not yet the full transport- and policy-complete system described in the original protocol-centered design.

The shared-wiki approval bypass for raw-backed provenance should be treated as a temporary smoke-path exception only. It must not be read as a relaxation of the normal truth-zone evidence rule, and it should be removed or explicitly blocked before any production-style C-level governance claim.

---

## 12A. Known Divergences from Design v1.0

| Area | Design target | Current implementation | Status |
|---|---|---|---|
| Transport surface | MCP + CLI + REST | real FastMCP stdio MCP server + workflow-complete CLI + workflow-complete REST | Implemented |
| Identity resolution | caller cannot override resolved identity | MCP/REST metadata precedence fixed; CLI uses env/local config | Implemented for remote/shared transports |
| Gate enforcement | operation risk + `max_gate` policy | per-rule `max_gate` enforcement exists; full workflow gate engine still incomplete | Partial |
| Authority promotion | gate-checked commit orchestration to Git authority | Git-visible file writes only, no full orchestrator yet | Divergence to fix |
| Propagation failure handling | rollback + stale markers + mirror state | direct append/write only | Phase 1 Simplification |
| Retrieval runtime | provider-pluggable, load-policy aware | FTS5+jieba primary, structured `topic_index.md` merge, JSONL lexical fallback, layered output | Partial |
| Sync | explicit adapter-driven sync boundary with view-specific artifacts | adapter-driven sync with explicit Obsidian graph index export; no authority-promotion orchestrator yet | Partial |
| Review queue | rich workflow schema | minimal append-only queue items | Phase 1 Simplification |
| Query outcome loop | query service logs outcomes directly | query service appends `query_outcomes.jsonl` and `query_hits.jsonl`; feedback adds human-evaluation records | Implemented baseline |
| Page sensitivity | schema-backed page access policy with query filtering | basic sensitivity filtering via `QueryInput.max_sensitivity` and manifest filter; `access_policy` incomplete | Partial |

---

## 12B. Recommendation for Readers

When using this document:

- treat the architecture sections as the intended long-lived system shape
- treat the implementation notes as the current Phase 1 baseline delivered in `src/agent_wiki/`
- treat the divergence table as the authoritative map of what still needs to catch up

This keeps the design stable without pretending the current implementation is already the full target system.

---

*Design v0.1 baseline archived and updated for v0.2.0 implementation status. Use with `core/schema.md`, `docs/requirements-and-architecture.md`, and the tests for current-state review.*

---

### Phase 1 synthesis of priorities

The three review perspectives imply a more nuanced Phase 1 priority stack than either a pure governance-first or pure convenience-first reading.

#### P0 — Must be usable

These determine whether the system is actually used:

- compilation foundation repair
  - source intake must produce authority raw entries with non-null critical metadata
  - low-confidence metadata is acceptable; null metadata is not
  - pending should represent failure state, not uncategorized accepted state
- query quality improvements to the lexical baseline
  - Chinese tokenization
  - fuzzy matching
  - weighted keyword/topic ranking
  - hit/miss tracking in the query path
- Obsidian-connected workflow
  - ObsidianAdapter as a real Phase 1 deliverable
  - reverse flow visible to the knowledge lifecycle loop

#### P1 — Must keep knowledge evolving

These prevent raw capture from becoming a dead-end:

- auto-compile suggestions when raw pages accumulate by topic/problem cluster
- fast feedback triggers from repeated low-value queries
- purpose-driven ranking, compile direction, and health evaluation
- low-cost candidate relations, especially co-occurrence and cross-reference signals

#### P2 — Must support stronger governance claims

These remain required before stronger multi-agent governance or broader deployment claims:

- trusted identity precedence
- end-to-end transport-complete gate enforcement
- page-level sensitivity policy and filtering
- richer review queue lifecycle records

#### P3 — Must complete the authority and service story

These deepen operational maturity:

- authority-promotion / commit orchestration
- `aw serve` and real service deployment path
- broader DFX readiness criteria and operational runbooks

### Design implication

This is not a rejection of Codex or CC. It is a synthesis:

- **Codex/CC correctly identify the governance blockers for stronger claims.**
- **Tao correctly identifies the adoption blockers for actual Phase 1 usefulness.**

The design should therefore present both truths clearly: governance matters, but if query quality and Obsidian-connected workflow fail, the rest of the system will never become the user’s real knowledge loop.

---

## 12. DFX Design

> Deployability, Reliability, Security, Observability, Performance, Maintainability, and Extensibility for Agent Wiki  
> v1.0 — 2026-05-16  
> Status: Design target aligned against the current Phase 1 implementation baseline

### 12.1 Scope and Reading Guide

This section complements:

- `README.md`
- `core/schema.md`
- `docs/design.md`
- `docs/agent-differences.md`

It defines the non-functional system design for Agent Wiki across seven DFX dimensions. Each section distinguishes between:

- the **design target** that should remain stable as the architecture evolves
- the **current Phase 1 baseline** already implemented or clearly supportable in the repository
- the **Phase 2 direction** where stronger multi-agent and networked operation becomes necessary

The same rule used elsewhere in the repo applies here:

**Do not collapse target architecture and current implementation into one story.** The target explains where the system is going; the implementation notes explain what exists today.

---

### 12.2 Deployability

#### Design goal

Agent Wiki should be easy to install, run, upgrade, and roll back across three deployment shapes:

1. local single-user knowledge service
2. containerized self-hosted service
3. network-exposed multi-user service

Deployment must preserve the core architecture: one shared `aw-agent` process, Git as authority, local workspace as runtime state, and thin MCP / CLI / REST interfaces over the same core.

#### Key decisions

##### Decision: run as an independent agent process, not an embedded library

**Rationale:** the project’s architecture assumes one shared knowledge engine serving multiple clients and transports. A long-running process fits MCP service hosting, approval routing, background maintenance, and identity resolution better than per-client embedded logic.

**Alternative considered:** embedding wiki logic directly in each agent adapter or client library.

**Why rejected:** that would duplicate core behavior, weaken identity and gate enforcement, and make propagation, audit, and transport consistency harder.

##### Decision: make local deployment the primary Phase 1 operating mode

**Rationale:** the current project target is personal multi-agent knowledge on one machine. Local install and local process management minimize operational complexity while preserving the architecture.

**Alternative considered:** start with a network service first.

**Why rejected:** Phase 1 does not need full remote auth, reverse proxy, or shared-team operational posture.

##### Decision: use registry YAML + environment variables + `.env` in a 12-factor style

**Rationale:** Agent Wiki needs explicit multi-wiki configuration plus environment-specific overrides. Registry config expresses knowledge topology; environment variables express deployment concerns such as ports, tokens, and storage paths.

**Alternative considered:** hard-coded per-agent config or one monolithic config file.

**Why rejected:** that would couple transport/runtime concerns to knowledge topology and make container or host deployment less portable.

##### Decision: use Git branch isolation as the main release and rollback boundary for knowledge state

**Rationale:** Git is already the authority of record. Branch-based rollout aligns deployment safety with the repository’s core authority model and allows quick rollback of committed knowledge state.

**Alternative considered:** database-native migration/version rollout as the primary release boundary.

**Why rejected:** it would demote Git from the authority role and complicate the Phase 1 operational story.

#### Phase 1 implementation status

Implemented or directly aligned with the current baseline:

- Python package install flow exists through `pyproject.toml` and local editable install patterns already documented in `README.md`.
- CLI surface exists as a workflow-complete command surface in `src/agent_wiki/transports/cli/app.py`.
- Registry-driven configuration loading exists in `src/agent_wiki/bootstrap/registry_loader.py`.
- The runtime model already separates committed Git artifacts from local runtime state under `.agent-wiki/`.
- Dockerfile exists at the repository root, which supports the single-package deployment direction.

Not yet implemented in the current repository baseline:

- service-manager examples for `launchd` / `systemd`
- docker-compose packaging for optional retrieval providers
- REST deployment with reverse proxy, TLS, and OIDC

#### Phase 1 release-readiness note

The current baseline is package-installable and architecture-aligned, and it now ships the documented long-running `aw-agent` MCP stdio service surface. It should still be treated as a Phase 1 baseline rather than a production-hardened deployment package, because service management, network hardening, and broader operational packaging remain incomplete.

#### Phase 2 plan

Phase 2 should add:

- a more production-ready long-running `aw-agent` service with MCP and REST enabled
- reverse-proxied HTTPS deployment via nginx or caddy
- OIDC-backed remote identity and session handling
- clearer release packaging for host installs and containers
- network-safe configuration layering for tokens, certificates, and per-wiki policy

#### Relation to other DFX dimensions

- **Reliability:** deployment shape determines restart behavior and rollback speed.
- **Security:** network deployment expands the auth and transport security surface.
- **Observability:** service packaging should expose health checks and structured logs.
- **Maintainability:** one deployable core process is easier to evolve than multiple embedded implementations.
- **Extensibility:** deployment should not depend on one transport or one adapter.

---

### 12.3 Reliability

#### Design goal

Agent Wiki should preserve knowledge integrity across crashes, partial propagation, and retrieval degradation. The system must fail in ways that are observable, repairable, and consistent with Git-first authority.

#### Key decisions

##### Decision: treat write propagation completeness as the core reliability boundary

**Rationale:** in this system, a write is not just a page edit. It must update downstream artifacts such as manifest, retrieval index, logs, and queue state. Reliability therefore centers on whether propagation completed coherently.

**Alternative considered:** define success as “page file written successfully.”

**Why rejected:** that would create knowledge islands and silent divergence between page content and retrieval/audit state.

##### Decision: use a layered rollback model: pending state, stale markers, then Git revert

**Rationale:** not every failure should force destructive rollback. Pending state is a pre-commit buffer, stale markers are a soft rollback signal, and Git revert remains the hard authority-level recovery path.

**Alternative considered:** immediate hard rollback for any propagation failure.

**Why rejected:** it is too coarse, throws away recoverable work, and does not match the workspace-versus-authority split.

##### Decision: degrade queries gracefully when optional retrieval components fail

**Rationale:** Phase 1 query capability must not depend on vector infrastructure. Lexical retrieval is the required baseline, so the system can remain usable when optional retrieval providers fail.

**Alternative considered:** fail closed when vector or richer retrieval is unavailable.

**Why rejected:** it would make an optional enhancement a single point of operational failure.

##### Decision: rely on Git remotes and text-recoverable JSONL artifacts for backup and recovery

**Rationale:** this matches the Git-first model and keeps core recovery human-auditable. JSONL manifests and indexes are inspectable and reconstructable.

**Alternative considered:** only database-native recovery.

**Why rejected:** Phase 1 should remain file-first and recoverable without specialized storage tooling.

#### Phase 1 implementation status

Implemented or partially implemented today:

- Propagation orchestration exists in `src/agent_wiki/application/propagation.py`.
- Pending fallback exists for invalid raw capture through `.agent-wiki/pending_manifest.jsonl`.
- Lexical retrieval provides an operational degraded mode in `src/agent_wiki/application/query.py` and `src/agent_wiki/infrastructure/retrieval/retrieval_index.py`.
- JSONL-backed artifacts such as `MANIFEST.jsonl`, `retrieval_index.jsonl`, `operation_log.jsonl`, and `review_queue.jsonl` align with text-recoverable recovery.
- The current repo design already assumes Git remote as the natural backup boundary.

Design target not yet fully implemented:

- explicit seven-check F1-F7 health model
- automatic stale markers on propagation failure
- automatic retry orchestration with pause after two consecutive failures
- transactional rollback between downstream propagation stages
- restart supervision documentation for long-running server processes

#### Phase 2 plan

Phase 2 should add:

- explicit propagation integrity states and stale-marker lifecycle
- retry controller with bounded retry and pause behavior
- richer crash recovery for long-running MCP / REST service processes
- explicit coordination for concurrent multi-writer updates
- stronger integrity validation across mirrors and external views

#### Relation to other DFX dimensions

- **Deployability:** restart and rollback strategy depends on deployment packaging.
- **Security:** auditability and reliable rollback reduce the blast radius of bad writes.
- **Observability:** reliability failures must become visible as health signals and alerts.
- **Performance:** retries and rebuilds must not starve normal query/write flows.
- **Maintainability:** clear failure states simplify repair and operator reasoning.

---

### 12.4 Security

#### Design goal

Agent Wiki should protect sensitive knowledge, constrain agent behavior by identity and capability, and ensure that high-risk operations require stronger approval paths. Security must match the project’s trust model: local-first in Phase 1, stronger remote and team controls in Phase 2.

#### Key decisions

##### Decision: separate authentication, authorization, and operation risk gates

**Rationale:** the architecture already distinguishes who the caller is, what capability tier they have, and what risk level the operation represents. This keeps low-risk usage easy while preserving a hard boundary for high-risk writes.

**Alternative considered:** one flat allow/deny permission system.

**Why rejected:** it would not express the project’s A/B/C gate model or the T1/T2/T3 capability model clearly enough.

##### Decision: Phase 1 uses loopback-local trust with local token; Phase 2 moves to OIDC

**Rationale:** local-only deployment minimizes exposure while still requiring explicit caller identity. OIDC becomes necessary only when the service is network-exposed or team-shared.

**Alternative considered:** require full remote-style auth from the start.

**Why rejected:** it adds unnecessary operational burden to the Phase 1 personal workflow.

##### Decision: sensitivity must be represented at page level and enforced at query time

**Rationale:** the repo is expected to hold API keys, internal notes, and other sensitive knowledge. Filtering only at repository or wiki level is too coarse; page-level sensitivity makes retrieval and output safer.

**Alternative considered:** treat the whole wiki as uniformly trusted.

**Why rejected:** it fails the multi-agent and mixed-sensitivity use case.

##### Decision: preserve auditable text logs for every material operation

**Rationale:** operations that change knowledge state must remain attributable by agent identity, target document, and timestamp.

**Alternative considered:** transient runtime-only audit events.

**Why rejected:** they are insufficient for review, debugging, and trust restoration after incidents.

##### Decision: isolate content adapter execution and validate system-boundary inputs

**Rationale:** adapters ingest external content and are the most likely place for malformed or malicious input to enter the system.

**Alternative considered:** trust all markdown/content inputs as safe internal data.

**Why rejected:** external content is a boundary and should be treated as untrusted.

#### Phase 1 implementation status

Implemented or partially represented today:

- Identity and permission helpers exist in `src/agent_wiki/infrastructure/identity/resolver.py`, `permissions.py`, and `gates.py`.
- MCP/REST metadata precedence is fixed; CLI uses environment/local config for actor resolution.
- `PermissionService.check()` enforces per-rule `max_gate`.
- Basic query sensitivity filtering exists via `QueryInput.max_sensitivity` and manifest sensitivity values.
- A/B/C separation is reflected by service boundaries across raw capture, compile update, and approvals.
- Approval audit exists through `approval_log.jsonl` and compile operations are logged to `operation_log.jsonl`.
- Input validation already exists in limited form for `doc_id`, `allowed_page_types`, and `source_refs`.
- The project instructions already preserve the rule that high-risk approval should go through MCP or an equivalent confirmation path.

Important gaps relative to the design target:

- identity override risk is fixed for MCP/REST; CLI fallback/dev behavior still needs operational hardening and clear warnings
- no full content-quality gate engine or route-test gate execution yet
- `access_policy` and transport-aware sensitivity filtering are incomplete
- no git-crypt workflow or encrypted content handling in the current baseline
- no transport-level TLS / mTLS because network service is not yet implemented
- no adapter sandbox runtime yet
#### Phase 2 plan

Phase 2 should add:

- OIDC-based authentication for remote access
- transport security via TLS and mTLS for service-to-service trust where needed
- enforced page-level sensitivity filtering at retrieval and response assembly time
- stronger high-risk approval routing that always uses the canonical approval path
- encrypted repository patterns where confidential content requires protected storage workflows
- hardened content-adapter sandboxing and validation profiles

#### Relation to other DFX dimensions

- **Deployability:** remote deployment widens the security boundary.
- **Reliability:** audit logs and safe rollback help contain bad or unauthorized changes.
- **Observability:** suspicious access and repeated gate failures should become visible signals.
- **Maintainability:** security rules should live in shared core policy, not in per-agent wrappers.
- **Extensibility:** every new adapter and transport must plug into the same identity and policy system.

---

### 12.5 Observability

#### Design goal

Agent Wiki should make knowledge operations diagnosable by both machines and humans. Operators should be able to answer:

- what happened
- why a query or propagation failed
- whether knowledge integrity is drifting
- which maintenance actions deserve attention

#### Key decisions

##### Decision: keep both structured machine logs and human-readable logs

**Rationale:** JSONL logs support automation and inspection tooling; markdown logs support quick human review in Git-native workflows.

**Alternative considered:** only human-readable logs or only structured logs.

**Why rejected:** one format alone would weaken either tooling or operator readability.

##### Decision: health reporting should reflect propagation integrity, not only process liveness

**Rationale:** a running process is not the same as a healthy knowledge system. Health must describe whether downstream artifacts remain in sync.

**Alternative considered:** only expose “server up/down” checks.

**Why rejected:** it misses the system’s actual correctness boundary.

##### Decision: weekly review is part of observability, not just maintenance

**Rationale:** observability for a knowledge system includes whether the system is being used effectively. Low-signal queries, stale queue items, and missing evidence are operational signals.

**Alternative considered:** treat weekly review as a purely human governance workflow.

**Why rejected:** it hides actionable behavioral feedback from the operational picture.

#### Phase 1 implementation status

Implemented today:

- human-readable `log.md` writes through propagation
- structured `operation_log.jsonl` for compile operations
- structured `approval_log.jsonl` for approvals
- structured `query_outcomes.jsonl` and `query_hits.jsonl` through `QueryService`, with feedback submission appending additional outcome records
- weekly review summary generation in `src/agent_wiki/application/weekly_review.py`
- minimal lint and consistency checks in `src/agent_wiki/application/linting.py`
- basic `aw health` covering registry load, actor resolution, and tool-list self-check

Not yet implemented relative to the target design:

- formal seven-check health report spanning propagation, manifest, retrieval, FTS, topic index, pending state, and external sync drift
- latency, hit-rate, propagation-success, and stale-count metrics export
- threshold-based alerting for repeated propagation failures or stale buildup
- richer observability dashboards over queue pressure, external sync drift, and retrieval provider health

#### Phase 2 plan

Phase 2 should add:

- a first-class health endpoint / command
- durable metrics collection for latency, hit quality, propagation integrity, and queue health
- alerting hooks for repeated propagation failure and stale accumulation
- stronger traceability across MCP, CLI, and REST calls
- better operator summaries linking usage patterns to maintenance actions

#### Relation to other DFX dimensions

- **Reliability:** observability is how propagation and recovery problems become actionable.
- **Security:** audit logs and access traces are part of the security model.
- **Performance:** latency and retrieval metrics drive tuning decisions.
- **Maintainability:** clear diagnostics reduce debugging cost.
- **Extensibility:** pluggable providers must expose comparable health and usage signals.

---

### 12.6 Performance

#### Design goal

Agent Wiki should remain fast enough for local agent workflows while preserving correctness and traceability. Performance targets should be shaped by the actual Phase 1 operating model: file-backed, local, mostly single-user, and retrieval-provider pluggable.

#### Key decisions

##### Decision: local retrieval is the required baseline and should be optimized first

**Rationale:** v0.2 uses FTS5+jieba plus structured `topic_index.md` routing as the normal fast path, while JSONL lexical retrieval remains the guaranteed fallback when richer retrieval fails. The combined local path must be fast enough for routine local use.

**Alternative considered:** optimize only vector retrieval because it may provide better recall.

**Why rejected:** vector retrieval is optional in Phase 1 and cannot be the only performance story.

##### Decision: keep raw capture and compile update lightweight and file-oriented in Phase 1

**Rationale:** most Phase 1 operations write a bounded set of markdown and JSONL artifacts. That should keep the core write path predictable and low-latency.

**Alternative considered:** eagerly introduce heavier persistence and distributed coordination.

**Why rejected:** it would overfit Phase 2 needs and complicate the current baseline.

##### Decision: Phase 1 uses optimistic concurrency; explicit locks are reserved for Phase 2

**Rationale:** single-user or loosely coordinated use is sufficient for the current project scope. Strong locking would add complexity before there is a real multi-writer need.

**Alternative considered:** implement explicit locking from day one.

**Why rejected:** premature coordination overhead for a local-first baseline.

#### Phase 1 implementation status

Current baseline characteristics:

- Query path routes through FTS5+jieba when `.agent-wiki/retrieval.db` exists, merges structured `topic_index.md` hits, and falls back to file-backed lexical retrieval over `retrieval_index.jsonl`.
- Writes are bounded filesystem and JSONL append/update flows.
- Cross-wiki query exists but remains a simple fan-out baseline.
- No vector or heavyweight remote retrieval provider is required for minimum functionality.

Target numbers from this design task:

- lexical retrieval under 100ms for local JSONL-backed queries
- vector retrieval under 500ms when optional provider is enabled
- `capture_raw` under 50ms for pure file operations
- `compile_update` under 200ms for bounded propagation work

Not yet implemented for measurement or enforcement:

- benchmark harnesses tied to these SLO-like targets
- explicit query/load budgets in the runtime
- segmented retrieval index loading for large repositories
- vector-store LRU caching and provider budgeting
- lock-aware concurrent write controls for team-scale operation

#### Phase 2 plan

Phase 2 should add:

- explicit performance benchmarks and regression checks
- segmented indexes and larger-repo retrieval strategies
- provider-aware cache and query budget controls
- stronger concurrency control for multi-writer scenarios
- metrics-backed tuning across retrieval, propagation, and cross-wiki fan-out

#### Relation to other DFX dimensions

- **Reliability:** degraded-mode retrieval must stay usable under provider failure.
- **Observability:** performance claims need metrics to be credible.
- **Maintainability:** simpler data paths are easier to tune and reason about.
- **Extensibility:** new providers must fit the same normalized hit and budget model.

---

### 12.7 Maintainability

#### Design goal

Agent Wiki should remain easy to evolve without losing architectural clarity. Maintainability depends on a stable shared core, explicit boundaries, strong tests, and documentation that distinguishes current behavior from target design.

#### Key decisions

##### Decision: keep a layered architecture with one-way dependencies

**Rationale:** the existing structure already separates application, domain, infrastructure, bootstrap, and transports. That keeps core policy separate from adapters and deployment surfaces.

**Alternative considered:** feature-first modules that mix transport, storage, and domain decisions.

**Why rejected:** that would blur the core/adapter boundary central to the project.

##### Decision: preserve design docs as living architecture documents, not retrospective marketing

**Rationale:** future contributors and reviewers need to understand both the target architecture and the current implementation gaps.

**Alternative considered:** rewrite docs to describe only what is implemented today.

**Why rejected:** it would erase the intended system shape and make Phase 2 decisions harder to evaluate consistently.

##### Decision: validate with milestone-oriented tests and structural linting

**Rationale:** the repository already uses milestone coverage across M1-M6. Structural integrity checks match the file-backed architecture.

**Alternative considered:** rely mainly on ad hoc manual testing.

**Why rejected:** it would not scale as propagation, approvals, and multi-wiki behavior become richer.

##### Decision: schema versioning and migrations should be explicit

**Rationale:** file-backed schemas and runtime metadata will evolve. Versioned migrations preserve continuity without hiding format changes.

**Alternative considered:** silent format drift.

**Why rejected:** that makes old knowledge artifacts ambiguous and harder to repair.

#### Phase 1 implementation status

Implemented today:

- layered code organization under `src/agent_wiki/`
- milestone-backed regression suite across the current Phase 1 workflow set
- core documentation set across README, schema, design, requirements, and agent-difference docs
- minimal lint checks for manifest/page and manifest/index consistency

Not yet fully implemented relative to the target design:

- full schema migration framework
- richer lint coverage for broken references, orphan pages, and frontmatter completeness
- broader cross-transport parity and end-to-end workflow tests
- broader documentation for operator runbooks and deployment procedures

#### Phase 2 plan

Phase 2 should add:

- explicit schema versioning and migration utilities
- expanded structural and semantic lint suites
- stronger contract tests shared across transports
- more complete operator documentation for deployment, recovery, and approval workflows
- clearer extension author guidance for adapters and retrieval providers

#### Relation to other DFX dimensions

- **Deployability:** maintainable packaging and config reduce operational burden.
- **Reliability:** clear structure makes failure recovery easier to implement correctly.
- **Security:** policy logic is safer when centralized and testable.
- **Extensibility:** maintainability is what keeps plugin points from turning into forks.

---

### 12.8 Extensibility

#### Design goal

Agent Wiki should grow by adding transports, adapters, retrieval providers, and agent profiles without changing the core knowledge model. Extensibility must preserve shared contracts rather than creating parallel implementations.

#### Key decisions

##### Decision: all major integrations depend on interfaces over the shared core

**Rationale:** the project already states that storage, content adapters, retrieval, embeddings, and external views should remain pluggable. A stable core contract keeps feature growth from fragmenting behavior.

**Alternative considered:** implement integrations directly inside each transport or agent adapter.

**Why rejected:** it would duplicate propagation, permissions, and query semantics.

##### Decision: make content adapters the normalization boundary

**Rationale:** Obsidian, Plain Markdown, Notion, and future views should map into one internal representation while preserving format-specific metadata only as adapter metadata.

**Alternative considered:** let each external system define its own internal semantics.

**Why rejected:** retrieval, propagation, and policy logic would become system-specific.

##### Decision: keep transports interchangeable over one approval and policy path

**Rationale:** MCP, CLI, and REST should be transport alternatives, not independent policy engines.

**Alternative considered:** let each transport own its own approval and permission behavior.

**Why rejected:** that would make risk handling inconsistent and harder to verify.

#### Phase 1 implementation status

Already aligned in the design and partially in code:

- registry-driven multi-wiki model provides a natural extension point
- transport boundary now exists concretely, with CLI, REST, and MCP code paths under `src/agent_wiki/transports/`
- retrieval provider abstraction is present at the design level, with lexical retrieval as the Phase 1 baseline
- agent adaptation strategy is documented in `docs/agent-differences.md`
- the approved next milestone fixes the MCP service shape without changing the shared-core contract

Not yet implemented in the current repository baseline:

- first-class `ContentAdapter` plugin runtime
- multiple retrieval provider implementations behind a common registry
- explicit agent-profile registration flow for T1/T2/T3 templates

#### Phase 2 plan

Phase 2 should add:

- formal adapter interfaces and registration mechanisms
- multiple retrieval providers behind one normalized hit contract
- stronger shared contract coverage across the implemented MCP / CLI / REST surfaces
- stronger agent identity profiles with reusable tier templates
- extension guidance that keeps external integrations thin

#### Relation to other DFX dimensions

- **Maintainability:** extensibility only works if the shared core remains coherent.
- **Security:** every extension must inherit the same identity, policy, and gate rules.
- **Performance:** provider plugins need normalized budgets and metrics.
- **Deployability:** extension packaging must work in local and networked deployments.

---

### 12.9 Cross-DFX Summary

The seven DFX dimensions are intentionally coupled:

- **Deployability** defines where the core runs.
- **Reliability** defines when writes and queries remain trustworthy.
- **Security** defines who can see or change what.
- **Observability** defines how operators detect drift and failure.
- **Performance** defines whether the system is usable in live agent workflows.
- **Maintainability** defines whether the architecture can evolve without losing clarity.
- **Extensibility** defines whether new tools can join the system without forking the core.

For Agent Wiki, these are not secondary concerns layered on top of the product. They are part of the product definition itself, because the system’s value depends on trusted multi-agent knowledge operations rather than simple file storage.
