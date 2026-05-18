# Agent Wiki Requirements and Architecture

> Status: Requirements baseline aligned against the current Phase 1 implementation  
> Date: 2026-05-16  
> Recommended architecture: protocol-centered Knowledge Agent  
> Note: this document remains a requirements and architecture summary, not an implementation plan. The authoritative end-state spec is `docs/specs/knowledge-system-architecture.md`.

---

## 1. Project background and goals

Agent Wiki is a universal, agent-agnostic knowledge system designed so multiple AI agents with different capability boundaries can use the same knowledge assets.

The core problem is not just where documents are stored. The real problem is building a knowledge system that is:

- compilable
- retrievable
- auditable
- evolvable
- usable by multiple agents over time

### 1.1 Core references

The project draws from two major sources:

1. LLM knowledge-system ideas:
   - `Raw Sources → Wiki → Schema`
   - hybrid retrieval through coarse selection and layered presentation
   - skill-driven knowledge workflows
2. `nashsu/llm_wiki`:
   - two-step ingest
   - graph-oriented maintenance inspiration
   - `purpose.md` and review-driven maintenance

### 1.2 Target agents

Phase 1 is designed to support five agent classes:

| Agent | Tier | Key ability | Main limit |
|---|---|---|---|
| Hermes | T1 Full | cron, rich tools, message channels | knowledge must persist in repo/files |
| OpenClaw | T1 Full | cron, skill prompts, message channels | more constrained execution model |
| Claude Code | T2 Standard | code reasoning, workspace persistence, shell tools | no built-in scheduler or vector memory |
| Codex | T3 Minimal | CLI-based short-lived execution | no persistent state |
| OpenCode | T3 Minimal | CLI-based provider-agnostic execution | no persistent state |

### 1.3 Phase 1 objective

The hard Phase 1 objective is a complete personal multi-agent knowledge loop:

```text
capture_raw → compile_update → query → lint → sync → weekly-review
```

Phase 1 also needs smoke coverage for:

- multi-wiki management
- shared wiki behavior
- cross-wiki retrieval
- C-level proposal / approval for principle writes

---

## 2. Design principles

### 2.1 Design from the end state, implement incrementally

Architecture is chosen from the Phase 2 end-state perspective, but Phase 1 only implements the minimum working path.

This is why the design keeps:

- `wiki_id:doc_id` identities
- a global `registry.yaml`
- page-type and gate-aware permissions
- shared wiki concepts
- one shared core behind multiple transports

### 2.2 Core remains pluggable

The architecture still assumes pluggable:

- storage
- content adapters
- retrieval providers
- external views
- attachment storage

### 2.3 Git remains the authority source

The authority chain remains:

```text
Git authority → Local workspace compile/index/staging → External view/edit layer
```

Current implementation note:
- The Phase 1 code already assumes Git-visible files as authority artifacts.
- The current runtime does not yet implement the full gate-to-commit orchestration described in the original design.
- Writing Git-visible files should therefore be read as an authority-aligned baseline, not as a complete authority-promotion pipeline.

### 2.4 Protocol-centered system shape

The target architecture remains a global `aw-agent` that exposes one shared core through:

- MCP Server
- CLI `aw`
- REST API

Current implementation note:
- the shared core services are implemented under `src/agent_wiki/`
- workflow-complete CLI exists in `src/agent_wiki/transports/cli/app.py`
- a real FastMCP stdio MCP server exists in `src/agent_wiki/transports/mcp/server.py`
- a workflow-complete REST surface exists in `src/agent_wiki/transports/rest/app.py`
- `aw serve` and `aw-agent` now expose the MCP stdio service identity

### 2.5 Risk gates scale with truth-zone risk

The design still assumes:

- A-level for raw/source capture
- B-level for atom/synthesis/dispute changes
- C-level for principle and other high-risk writes

Current implementation note:
- gate classification exists
- per-rule `max_gate` enforcement exists in `PermissionService.check()`
- full content-quality gates and workflow-complete gate-check execution remain incomplete
- the current baseline should not be treated as policy-complete governance yet

---

## 3. Confirmed architecture decisions

### 3.1 Authority and data flow

The following remain the active requirements baseline:

1. **Workspace is the single source of truth (SSOT).** All authoritative knowledge lives in the workspace; external views (including Obsidian) are human-facing read-write presentation layers, not peer data sources.
2. Git stores the persistent authority of the workspace: pages, `purpose.md`, config, `MANIFEST.jsonl`, `retrieval_index.jsonl`, and audit/log artifacts.
3. Workspace holds runtime, pending, proposals, indexes, and conflict state.
4. `.agent-wiki/` holds local runtime state and is not committed.
5. v0.2 retrieval uses FTS5+jieba in `.agent-wiki/retrieval.db` as the accelerated local index, merges structured `topic_index.md`, and keeps `retrieval_index.jsonl` as the Git-tracked JSONL lexical fallback. FTS ranking prioritizes topic/problem-cluster/summary over body content and supports page-type filtering.
6. Vector retrieval remains optional.

**Data flow:**

```text
Agent writes → workspace (SSOT)
Human edits in Obsidian → pull-view → workspace
workspace → push-view → Obsidian (full browsable/editable view)
```

**Scaling architecture (end-state design, not Phase 1):**

- N personal workspaces (private, invisible by default)
- M team workspaces (tiered permissions: shared / read-only / read-write)
- Cross-workspace queries preserve source wiki traceability
- Design principle: design from end-state, implement personal closure first

Current implementation note:
- `MANIFEST.jsonl` remains the authority ledger for committed raw and compiled pages.
- `.agent-wiki/pending_manifest.jsonl` exists today, but the target architecture now constrains `pending` to failure or blocked-promotion states only.
- accepted raw entries should ultimately live in `MANIFEST.jsonl` with non-null critical metadata, even when confidence is low.

### 3.2 Multi-wiki and identity

The following remain baseline decisions:

1. A global `registry.yaml` is authoritative.
2. Cross-wiki identity uses `wiki_id:doc_id`.
3. Shared wikis exist and can restrict page types.
4. Cross-wiki retrieval must preserve source wiki traceability.

Current implementation note:
- registry loading is implemented in `src/agent_wiki/bootstrap/registry_loader.py`
- multi-wiki and shared wiki smoke behavior are covered by tests
- cross-wiki query aggregation is implemented in `src/agent_wiki/application/query.py`

### 3.3 Directory and state layout

The design baseline remains:

- `purpose.md`
- `config.yaml`
- `pages/`
- `MANIFEST.jsonl`
- `retrieval_index.jsonl`
- `review_queue.jsonl`
- `query_outcomes.jsonl`
- `operation_log.jsonl`
- `approval_log.jsonl`
- `.agent-wiki/`

Current implementation note:
- these artifacts are used directly by the current runtime
- `pages/` are currently written as `pages/{doc_id}.md`
- path/identity separation remains a design requirement, but is not yet fully implemented in code
- `aw migrate --normalize-doc-ids` is available for lowercase/hyphen `doc_id` normalization; same-name pull-view conflicts are addressed through relative-path-derived ids and migration support

### 3.4 Agent capability tiers

This remains the active tier model:

- T1 Full: ingest/query/lint/sync/cron/propagation target
- T2 Standard: ingest/query/lint, external scheduling
- T3 Minimal: query/capture_raw only

Current implementation note:
- the implemented service boundaries align with this model
- there is still no transport-level policy-complete enforcement across all agents, even though MCP/CLI/REST now exist
- the tier model should therefore be read as the intended policy shape, not a fully enforced runtime perimeter yet

### 3.5 Ingest and compile

Still required:

- `capture_raw` does not mutate the truth zone
- `compile_update` mutates `atom` and `synthesis`
- high-risk principle writes go through proposal/approval
- analyze/apply separation remains the intended pattern

Current implementation note:
- `capture_raw` is implemented
- `compile_update` analyze/apply is implemented in a simplified form
- `aw compile-execute` can claim compile suggestions, print evidence packets, apply generated content from an input file, or run `--apply` through an OpenAI-compatible chat completions endpoint
- `aw compile-execute --apply --concurrency N` parallelizes LLM generation only; apply/write propagation remains serialized through the normal service path
- compile LLM config supports `timeout_seconds`, `max_retries`, `retry_delays`, and default `concurrency`
- consumed compile suggestions record `latency_seconds`, `attempts`, `error_type`, and provider `token_usage` when available in `review_queue.jsonl` `content_state`
- principle writes currently use a local proposal/approval smoke path
- analyze is currently heuristic, not a full evidence-planning engine
- intake code path has improved through `normalize_raw_intake`, Obsidian frontmatter handling, raw metadata repair, and lint checks for missing raw metadata; live data still needs cleanup/migration where old imports remain weak or pending-heavy

### 3.6 External views and sync

Target design remains:

- external views are human-facing edit/read layers
- reverse sync should flow into workspace first
- gate failure should block authority promotion, not workspace visibility

Current implementation note:
- current Phase 1 sync is a copy-based markdown sync with `status`, `pull-view`, and `push-view`
- adapter-driven reverse sync exists for markdown views, including recursive pull-view, `.obsidian` / trash ignores, frontmatter date sanitization, relative-path `doc_id`s, and index updates
- Obsidian `push-view` category routing exists through configurable `push_view_routing`; generic defaults use `raw`, `atoms`, `synthesis`, `principles`, and `knowledge-graph`
- gate-to-Git promotion and commit orchestration remain future work

### 3.7 Pending and query policy

Still required:

- pending represents failure or blocked-promotion state rather than uncategorized accepted state
- raw pending can be queryable only as an explicit failure-path convenience
- truth-zone pending is excluded by default unless `include_pending=true`

Current implementation note:
- truth-zone pending opt-in query behavior is implemented in `src/agent_wiki/application/query.py`
- raw pending indexing remains simplified relative to the fuller design
- the unified architecture direction is to reduce pending-heavy raw intake by promoting accepted low-confidence raw entries into `MANIFEST.jsonl`

### 3.8 Source-of-truth evidence rules

Still required:

- truth-zone `source_refs` must refer to tracked raw pages via `wiki_id:doc_id`
- external URLs and attachments cannot directly serve as truth-zone `source_refs`

Current implementation note:
- this rule is enforced today for standard compile updates
- shared-wiki approval flow currently has a targeted bypass used for smoke-path principle/shared writes
- that bypass should be read as a temporary Phase 1 simplification, not a general relaxation of the design rule
- this bypass should be removed or explicitly blocked before any production-style C-level governance claim

### 3.9 Retrieval and answer format

Still required:

- provider-pluggable retrieval
- lexical baseline as minimum path
- three-layer output:
  - L1 answer
  - L2 reasoning/context
  - L3 proof/evidence

Current implementation note:
- FTS5+jieba primary retrieval, structured `topic_index.md` merge, JSONL lexical fallback, and layered output are implemented
- debug scoring includes lexical/structured scores plus page type, purpose, freshness, and manifest-priority boosts
- `query_outcomes.jsonl` entries include latency, page-type distribution, top-hit score breakdown, and empty accepted/rejected doc id fields for later feedback joins
- `aw eval-retrieval` runs JSONL retrieval evals without mutating query outcome logs and reports recall@k, precision@k, MRR, compiled hit ratio, and latency stats
- Query filters can restrict retrieval to `page_types` such as `atom` and `synthesis`; compiled pages receive the default ranking boost in mixed retrieval
- vector routing, load-policy execution, query budgets, and richer provider orchestration are not yet implemented

### 3.10 Feedback and weekly review loop

Still required:

- query usage should feed maintenance
- feedback should create review work, not auto-edit pages
- weekly review should suggest action, not execute it

Current implementation note:
- `feedback.py` appends `query_outcomes.jsonl` and creates review queue items
- `weekly_review.py` produces a minimal summary and suggested actions from queue reasons
- `quality_report.py` reads query outcomes, manifest entries, and compile queue telemetry to report compile failure rate, failure breakdown, average compile latency, metadata completeness, cluster coverage, and mature-cluster coverage
- richer query-outcome policy and multi-signal review synthesis remain future work

### 3.11 Review queue

The review queue still conceptually supports conflict, missing evidence, pending gate fix, signal candidate, feedback issue, principle proposal, and dispute items.

Current implementation note:
- the current queue item shape is minimal: `item_type`, `doc_id`, `reason`, `status`
- richer lifecycle, assignment, priority, `wiki_id`, and resolution semantics are design targets
- the current queue shape should be treated as transitional rather than sufficient for serious multi-wiki governance

### 3.12 C-level confirmation and audit

Still required:

- proposal before high-risk mutation
- explicit approval path
- approval log written after execution

Current implementation note:
- a minimal local proposal/approval flow is implemented in `src/agent_wiki/application/approvals.py`
- approval logs are written to `approval_log.jsonl`
- the design still expects richer MCP-mediated interaction later

### 3.13 Identity and permissions

The design still requires identity to be resolved by the knowledge agent rather than caller-controlled request parameters.

Current implementation note:
- identity, permission, and gate helper modules exist
- remote/shared transports now resolve trusted identity from transport context; CLI still prefers explicit local actor/config
- per-rule `max_gate` enforcement exists, but the full workflow gate engine is still incomplete
- identity fallback/dev behavior and registry fallback warnings remain operational concerns, not a remaining MCP/REST caller-override blocker

### 3.14 Transports and naming

The naming baseline remains:

- Python package: `agent_wiki`
- CLI: `aw`
- service process: `aw-agent`
- MCP server: `agent-wiki`

Current implementation note:
- package name is implemented
- CLI entry point is configured in `pyproject.toml`
- workflow-complete CLI, MCP, and REST surfaces are implemented
- `aw-agent` is a real alias entrypoint for the same stdio service identity as `aw serve`

---

## 4. Current Phase 1 implementation status

The current implementation baseline covers the following subsystems under `src/agent_wiki/`:

- bootstrap and registry loading
- raw capture
- compile update
- propagation
- lexical query
- cross-wiki query smoke behavior
- lint
- sync status/pull/push
- Obsidian date sanitization and push-view category routing
- doc_id normalization migration
- knowledge graph visualizer and graph index export
- feedback
- weekly review
- approvals
- manifest/retrieval/pending/review/runtime repositories
- MCP stdio server, REST surface, and shared transport-aligned policy helpers

This means the project now has a **working Phase 1 baseline**, but not yet the full protocol-complete architecture described in the end-state design.

### 4.1 Release-readiness blockers

The following items should be treated as blockers before any stronger claim of production-ready multi-agent governance:

- identity fallback/dev behavior and registry fallback warning policy; MCP/REST trusted metadata precedence is fixed
- content-quality gates and the full workflow gate engine; central `max_gate` enforcement already exists
- authority-promotion / commit orchestration for Git-first governance
- complete `access_policy` plus transport-aware sensitivity filtering; basic `QueryInput.max_sensitivity` manifest filtering exists
- live-data cleanup/migration for pending-heavy imports and old weak metadata

---

## 5. Divergence map: design target vs implementation baseline

| Area | Design target | Current implementation | Status |
|---|---|---|---|
| Transport surface | MCP + CLI + REST | real FastMCP stdio MCP server + workflow-complete CLI + workflow-complete REST | Implemented |
| Gate enforcement | policy-complete A/B/C checks and `max_gate` enforcement | per-rule `max_gate` enforcement exists; full workflow gate engine is still incomplete | Partial |
| Identity safety | caller cannot override resolved identity | trusted transport context is enforced for MCP/REST; CLI still prefers explicit local actor/config | Partial |
| Propagation recovery | rollback + stale markers + mirror handling | direct write/append model only | Phase 1 Simplification |
| Authority promotion | gate-checked commit orchestration to Git authority | Git-visible file writes only, no full orchestrator yet | Divergence |
| Retrieval runtime | provider-pluggable, load-policy aware, budgeted | FTS5+structured routing implemented; load_policy/budget/vector not implemented | Partial |
| Compilation foundation | compile-ready raw authority intake with metadata continuity | code path improved through normalization, repair, and lint; live data still needs cleanup/migration | Partial |
| Sync | adapter-driven reverse sync and gate-to-authority path | adapter-driven markdown sync, Obsidian date sanitization, category push-view, and explicit graph export; gate-to-authority path missing | Partial |
| Review queue | rich workflow schema | minimal queue entries | Phase 1 Simplification |
| Query outcomes | query path logs outcomes directly plus offline eval | query path logs outcomes directly; feedback appends human-evaluation records; `aw eval-retrieval` reports retrieval metrics | Partial |
| Page sensitivity | schema-backed page access policy with query filtering | basic sensitivity filtering via `QueryInput.max_sensitivity`; `access_policy` and transport-aware filtering incomplete | Partial |

---

## 6. Recommended reading order

To understand the project as it exists today:

1. `README.md`
2. `docs/design.md`
3. `core/schema.md`
4. `docs/agent-differences.md`
5. `src/agent_wiki/`
6. `tests/`

This order gives you:
- project-facing summary
- architecture intent
- contract expectations
- per-agent differences
- current implementation
- verified behavior

---

## 7. Final note

This document should be read as the **requirements and architecture baseline**, not as a claim that every target capability is already implemented. Where the current implementation is smaller than the design, the design remains authoritative and the current runtime is treated as a Phase 1 baseline or simplification.

In particular, live-data cleanup, identity fallback warning policy, the full workflow gate engine, authority-promotion/commit orchestration, and complete `access_policy` / transport-aware sensitivity filtering remain the most important unresolved blockers for stronger governance claims.
