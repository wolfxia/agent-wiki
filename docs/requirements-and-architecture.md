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
- full `max_gate` enforcement and gate-check execution remain incomplete
- the current baseline should not be treated as policy-complete governance yet

---

## 3. Confirmed architecture decisions

### 3.1 Authority and data flow

The following remain the active requirements baseline:

1. **Workspace is the single source of truth (SSOT).** All authoritative knowledge lives in the workspace; external views (including Obsidian) are human-facing read-write presentation layers, not peer data sources.
2. Git stores the persistent authority of the workspace: pages, `purpose.md`, config, `MANIFEST.jsonl`, `retrieval_index.jsonl`, and audit/log artifacts.
3. Workspace holds runtime, pending, proposals, indexes, and conflict state.
4. `.agent-wiki/` holds local runtime state and is not committed.
5. `retrieval_index.jsonl` is the Phase 1 coarse retrieval baseline; FTS5 `retrieval.db` is the v0.2 accelerated index (not in Git, rebuildable).
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
- principle writes currently use a local proposal/approval smoke path
- analyze is currently heuristic, not a full evidence-planning engine
- the current intake path still needs stronger metadata continuity so imported raw pages reliably feed compilation

### 3.6 External views and sync

Target design remains:

- external views are human-facing edit/read layers
- reverse sync should flow into workspace first
- gate failure should block authority promotion, not workspace visibility

Current implementation note:
- current Phase 1 sync is a copy-based markdown sync with `status`, `pull-view`, and `push-view`
- adapter-driven reverse sync and gate-to-Git promotion remain future work

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
- the lexical baseline and layered output are implemented
- the current baseline uses file-backed lexical retrieval with CJK bigram tokenization, simple fuzzy matching, and weighted topic/problem-cluster/content scoring
- vector routing, load budgets, and richer provider orchestration are not yet implemented

### 3.10 Feedback and weekly review loop

Still required:

- query usage should feed maintenance
- feedback should create review work, not auto-edit pages
- weekly review should suggest action, not execute it

Current implementation note:
- `feedback.py` appends `query_outcomes.jsonl` and creates review queue items
- `weekly_review.py` produces a minimal summary and suggested actions from queue reasons
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
- these are implementation gaps to be fixed, not design changes

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
- feedback
- weekly review
- approvals
- manifest/retrieval/pending/review/runtime repositories
- MCP stdio server, REST surface, and shared transport-aligned policy helpers

This means the project now has a **working Phase 1 baseline**, but not yet the full protocol-complete architecture described in the end-state design.

### 4.1 Release-readiness blockers

The following items should be treated as blockers before any stronger claim of production-ready multi-agent governance:

- trusted identity precedence over caller-supplied actor fields
- central `max_gate` enforcement
- authority-promotion / commit orchestration for Git-first governance
- page-level sensitivity schema plus retrieval/response filtering
- stronger compilation foundation: authority raw intake, metadata continuity, and repair of pending-heavy imports

---

## 5. Divergence map: design target vs implementation baseline

| Area | Design target | Current implementation | Status |
|---|---|---|---|
| Transport surface | MCP + CLI + REST | real FastMCP stdio MCP server + workflow-complete CLI + workflow-complete REST | Implemented |
| Gate enforcement | policy-complete A/B/C checks and `max_gate` enforcement | per-rule `max_gate` enforcement exists; full workflow gate engine is still incomplete | Partial |
| Identity safety | caller cannot override resolved identity | trusted transport context is enforced for MCP/REST; CLI still prefers explicit local actor/config | Partial |
| Propagation recovery | rollback + stale markers + mirror handling | direct write/append model only | Phase 1 Simplification |
| Authority promotion | gate-checked commit orchestration to Git authority | Git-visible file writes only, no full orchestrator yet | Divergence |
| Retrieval runtime | provider-pluggable, load-policy aware, budgeted | lexical baseline + layered output; stronger routed retrieval remains future work | Phase 1 Simplification |
| Compilation foundation | compile-ready raw authority intake with metadata continuity | imported raw intake can still produce weak or pending-heavy metadata state | Divergence |
| Sync | adapter-driven reverse sync and gate-to-authority path | adapter-driven markdown sync plus explicit Obsidian graph export | Phase 1 Simplification |
| Review queue | rich workflow schema | minimal queue entries | Phase 1 Simplification |
| Query outcomes | query path logs outcomes directly | query path logs outcomes directly; feedback appends human-evaluation records | Simplified |
| Page sensitivity | schema-backed page access policy with query filtering | no page-level sensitivity enforcement yet | Not Yet Implemented |

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

In particular, compilation-foundation repair, identity precedence, the full workflow gate engine, authority-promotion/commit orchestration, and page-level sensitivity filtering remain the most important unresolved blockers for stronger governance claims.
