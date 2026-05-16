# Agent Wiki Phase 1 Design Spec

- Status: Draft for implementation approval
- Date: 2026-05-16
- Scope: Personal multi-agent knowledge system, with Phase 2 team collaboration interfaces designed but mostly unimplemented
- Baseline sources: `README.md`, `core/schema.md`, `docs/design.md`, `docs/agent-differences.md`, `docs/requirements-and-architecture.md`

## 1. Purpose

This spec converts the approved brainstorming and architecture baseline into an implementation-grade Phase 1 contract for Agent Wiki.

Phase 1 must deliver a daily usable personal knowledge workflow with one shared core engine and three transports:

- MCP Server: primary agent interface
- CLI `aw`: deterministic local/operator interface
- REST API: local dashboard/programmatic interface

The required Phase 1 loop is:

```text
capture_raw → compile_update → query → lint → sync → weekly-review
```

This spec is the handoff point between design and implementation. It defines what is in scope for Phase 1, what must be smoke-tested in Phase 1, and what is reserved as interface-only design for Phase 2+.

## 2. Phase Boundary

### 2.1 Implement in Phase 1

1. One local `aw-agent` process managing multiple wikis.
2. One Python package `agent_wiki` exposing shared core logic.
3. One CLI named `aw`.
4. One MCP server named `agent-wiki`.
5. One REST service process named `aw-agent`, bound to `127.0.0.1` only.
6. Multi-wiki registry and routing.
7. Git-authority storage model with local workspace runtime state.
8. Raw capture workflow.
9. Truth-zone compile analyze/apply workflow for atom and synthesis updates.
10. Query pipeline using lexical retrieval baseline over `retrieval_index.jsonl`.
11. Lint and gate-check for A/B/C levels.
12. Obsidian read/write adapter and plain Markdown read/write adapter.
13. Reverse sync from external view to workspace, then gate to Git authority.
14. Query outcome logging, feedback intake, and weekly review report generation.
15. Local SQLite runtime support where structured runtime state is useful.
16. Proposal/approval path for C-level operations over MCP.

### 2.2 Smoke-test in Phase 1

1. Multi-wiki management.
2. Shared wiki write path.
3. Cross-wiki retrieval.
4. C-level principle promotion proposal/approval loop.

Smoke tests only need to prove the interface and data model are correct. They do not need Phase 2 operational maturity.

### 2.3 Reserved for Phase 2+

1. Team RBAC and OIDC.
2. Public/networked deployment.
3. Notion full reverse sync.
4. Logseq full reverse sync.
5. S3 or remote object stores as primary storage.
6. Git LFS/annex attachment support.
7. Explicit locking beyond no-op interfaces.
8. Louvain/community detection automation.
9. Multi-tenant service hardening.

## 3. Product Requirements

### 3.1 Core operating model

The authority chain is fixed:

```text
Git authority → Local workspace compile/index/staging → External view/edit layer
```

Rules:

- Git is the only committed authority.
- Local workspace contains runtime, pending, proposals, indexes, and conflict state.
- External tools are view/edit layers, not the authority of record.
- Gate failure blocks Git commit only; it does not block workspace visibility.

### 3.2 Supported page types

Phase 1 must support the canonical page taxonomy from `core/schema.md`:

- `raw`
- `atom`
- `synthesis`
- `principle`

Operational rules:

- `raw` is append-only and immutable as source capture.
- `atom` and `synthesis` are revisable truth-zone artifacts.
- `principle` is high-risk and must go through proposal/approval.
- Shared wiki storage in Phase 1 is limited to `synthesis` and `principle` pages.

### 3.3 Capability tiers

Phase 1 must preserve three capability tiers:

- T1 Full: may use the full workflow including sync automation.
- T2 Standard: may use `capture_raw`, `compile_update`, `query`, `lint`; sync is externally triggered.
- T3 Minimal: may use `capture_raw` and `query`; cannot mutate the truth zone.

### 3.4 Risk gates

Every mutation maps to a risk gate:

- A-level: raw/source capture
- B-level: atom/synthesis updates, dispute changes
- C-level: principle promotion/demotion, dispute adjudication, cross-wiki merge, shared high-risk writes

Approval rules:

- A-level: automatic if validation passes
- B-level: no human confirmation required, but analyze output must be recorded
- C-level: must use MCP proposal/approval or an equivalent human confirmation path that resolves through the same approval API

## 4. System Architecture

## 4.1 Top-level components

```text
agent_wiki/
├── core domain models and contracts
├── services for capture, compile, query, lint, sync, review, approval
├── storage providers
├── retrieval providers
├── content adapters
├── transports
│   ├── CLI `aw`
│   ├── MCP server `agent-wiki`
│   └── REST app served by `aw-agent`
└── runtime support for local SQLite state and workspace bookkeeping
```

All transports call the same service layer. No transport may own business logic.

### 4.2 Process model

`aw-agent` is the single local process boundary for Phase 1. It is responsible for:

- loading `registry.yaml`
- resolving actor identity
- routing requests to the correct wiki
- enforcing permissions and gate level
- calling shared service logic
- exposing MCP and REST interfaces

CLI `aw` is a thin local client that calls the same internal service layer directly when run in-process.

### 4.3 Package and executable names

The implementation must use the user-approved names:

- Python package: `agent_wiki`
- CLI command: `aw`
- service process: `aw-agent`
- MCP server name: `agent-wiki`

## 5. Repository and Runtime Layout

### 5.1 Code repository layout

Phase 1 implementation must standardize the code repository around:

```text
pyproject.toml
src/agent_wiki/
tests/
Makefile
Dockerfile
```

Within `src/agent_wiki/`, the implementation should separate:

- domain models
- service layer
- transport layer
- provider/adapters
- persistence/runtime helpers

### 5.2 Knowledge root layout

The runtime must support a global root that contains `registry.yaml` and one or more wiki roots.

Each wiki root must support:

```text
purpose.md
config.yaml
pages/
MANIFEST.jsonl
retrieval_index.jsonl
review_queue.jsonl
query_outcomes.jsonl
approval_log.jsonl
operation_log.jsonl
log.md
.agent-wiki/
```

`.agent-wiki/` is local runtime state and must remain Git-ignored.

### 5.3 Pending runtime files

Phase 1 must use local runtime files under `.agent-wiki/` for at least:

- `pending_manifest.jsonl`
- `pending_retrieval_index.jsonl` for raw pending support
- `proposals/`
- conflict snapshots
- any local SQLite database files

## 6. Canonical Data Contracts

### 6.1 Registry

`registry.yaml` is the multi-wiki authority.

Minimum required semantics:

- global version
- default route policy
- wiki descriptors with `wiki_id`
- repo/workspace mapping
- purpose/config paths
- allowed page types
- external view configuration
- pending query policy
- retrieval provider configuration
- permissions binding actor identity to operations and gate ceilings

### 6.2 Identity

All references must use `wiki_id:doc_id` as the cross-wiki identity form.

Rules:

- `doc_id` is unique only within a wiki
- path is not identity
- rename/move preserves `doc_id`
- retrieval and source references must resolve through identity, not path text

### 6.3 Frontmatter and manifest

Phase 1 implementation must validate pages against the existing schema baseline.

Minimum rules:

- all pages require the common frontmatter contract
- `source_refs` must resolve to Git-tracked raw pages via `wiki_id:doc_id`
- `query_types` cannot be empty
- `load_policy` must be legal for the page type
- manifest must remain 1:1 with committed authority files

### 6.4 Retrieval index

`retrieval_index.jsonl` is the textual coarse retrieval substrate and must be committed to Git.

Granularity rules:

- `raw`: page-level cards
- `atom`, `synthesis`, `principle`: section/claim-level cards

Every retrieval hit must normalize back to `wiki_id:doc_id` plus section or span metadata when relevant.

### 6.5 Runtime SQLite

Phase 1 may use SQLite for local runtime state that benefits from structured querying or mutation, but SQLite is not the authority for knowledge pages.

Allowed uses include:

- local token/session or resolved identity cache
- local query analytics materialization
- sync bookkeeping
- optional vector plugin storage

Disallowed uses:

- replacing Git authority for pages
- storing committed truth-zone state as the primary source of record

## 7. Service Contracts

### 7.1 `capture_raw`

Purpose:

- ingest raw notes, source excerpts, references, and attachment metadata
- create a committed or pending raw page without mutating the truth zone

Requirements:

- available to all capability tiers
- A-level gate only
- may reference local/object-store attachments by URI, hash, and recovery location
- must update manifest, retrieval index, and logs through propagation

### 7.2 `compile_update`

Purpose:

- modify the truth zone by revising or creating `atom`/`synthesis` pages
- optionally prepare principle proposals without directly promoting them

Phase 1 contract is split into two steps:

1. `analyze`
   - choose target wiki
   - choose target page or create intent
   - classify change type
   - produce evidence chain
   - assign risk level and gate plan
2. `apply`
   - write page updates
   - propagate dependent artifacts
   - write operation audit records

Requirements:

- raw pages never become principle directly
- prefer revise over create when problem cluster already exists
- B-level apply does not need human approval
- failed or unexecuted analyze results stay local, not committed to Git

### 7.3 `query`

Purpose:

- answer one of six query types using the fixed retrieval pipeline

Required query types:

- `fact_lookup`
- `concept_explain`
- `trend_scan`
- `compare_tradeoff`
- `decision_support`
- `proof_trace`

Required result layering:

- L1: direct answer
- L2: reasoning/context pages with dispute and relevance metadata
- L3: proof chain with raw evidence references and snippets when needed

### 7.4 `lint`

Purpose:

- validate schema, identity, references, and anti-island propagation health

Phase 1 lint must check:

- frontmatter completeness
- `doc_id` uniqueness
- `source_refs` validity
- `query_types` non-empty
- legal `load_policy`
- review queue consistency
- dependency chain integrity
- retrieval index correspondence
- dispute metadata completeness
- manifest/file 1:1 alignment
- stale markers such as `index_stale` and `mirror_pending`

### 7.5 `sync`

Phase 1 sync modes:

- `pull-view`
- `push-view`
- `status`

Rules:

- external edits apply to workspace first
- gate validates before Git commit
- failing changes remain pending locally
- Obsidian reverse sync is in scope
- other external adapters may remain read-only or interface-only

### 7.6 `weekly-review`

Purpose:

- summarize maintenance signals without mutating authority state automatically

Required inputs:

- query outcomes
- feedback records
- review queue state
- 4-signal candidates
- raw backlog

Required output classes:

- new signals
- queue status
- suggested actions

### 7.7 `feedback`

Purpose:

- capture user/agent feedback on query quality

Requirements:

- available via CLI and MCP
- supports `approved`, `missing_evidence`, `rewrite_targets`, `notes`
- must generate review queue items when evidence gaps or rewrites are indicated
- must not auto-edit pages

## 8. Provider and Adapter Contracts

### 8.1 Storage provider

Phase 1 default provider stack:

- `GitStorage`
- `LocalWorkspace`

The storage layer must preserve:

- committed authority files in Git-backed workspace
- pending local overlays
- reversible file-oriented operations suitable for review and diffing

### 8.2 Retrieval providers

Phase 1 default provider:

- lexical retrieval over `retrieval_index.jsonl`

Optional provider:

- local vector plugin

Rules:

- retrieval providers share one normalized hit shape
- retrieval providers do not change query semantics
- lexical retrieval must remain sufficient for minimum viable query capability

### 8.3 Content adapters

Phase 1 must implement:

- `ObsidianAdapter` read/write
- `PlainMarkdownAdapter` read/write

Rules:

- adapters normalize external format into the canonical internal representation
- format-specific details may be preserved in `adapter_metadata`
- `adapter_metadata` is for round-trip/debug, not default ranking logic

## 9. Identity, Permissions, and Approval

### 9.1 Identity resolution

Identity must be resolved by the Knowledge Agent, not caller-provided request fields.

Allowed identity sources:

- MCP client metadata/config binding
- CLI identity profile
- REST token

Audit logs must record:

- resolved actor identity
- actor type
- transport
- operation
- wiki
- gate level

Secrets must never be written to Git logs, markdown logs, or error output.

### 9.2 Permissions

Permissions bind:

- `actor_type`
- actor identity
- wiki
- page type
- operation
- max gate level

Enforcement must happen before mutation planning is applied.

### 9.3 C-level approval

C-level operations must support:

1. proposal creation
2. proposal inspection with diff/evidence/gate report
3. explicit approval path
4. approval logging into Git-backed audit files after execution

In Phase 1, this path is required over MCP. REST may propose but may not approve directly.

## 10. Propagation and Anti-Island Rules

Every write must flow through a propagation contract equivalent to the approved matrix.

Minimum downstream artifacts:

- manifest
- retrieval/provider index
- review queue when conditionally required
- operation log/log summary
- external mirror state

Failure rules:

- page write + manifest update must be atomic
- provider/retrieval refresh may degrade to stale markers instead of rollback
- mirror push may degrade to pending marker instead of rollback
- lint must detect degraded markers and surface repair work

## 11. Query and Review Feedback Loop

Phase 1 must create a behavior-improvement loop, not only a storage system.

Required loop:

```text
query → outcome log → feedback/review queue → compile candidate → weekly review suggestions
```

Interpretation rules:

- query outcomes are append-only
- feedback creates work items, not silent rewrites
- weekly review suggests but does not execute changes
- disputed pages must produce caveated query output

## 12. Testing and Acceptance

### 12.1 Test strategy

Implementation after this spec must follow TDD.

Minimum test layers:

- unit tests for domain validation and routing logic
- service tests for capture/compile/query/lint/sync behavior
- transport tests for CLI, REST, and MCP contract surfaces where practical
- file-system integration tests around propagation and pending state
- smoke tests for multi-wiki, cross-wiki query, shared wiki, and C-level proposal/approval

### 12.2 Acceptance criteria by milestone

#### Milestone A: substrate and project scaffold
- package/build/test tooling in place
- core models and config parsing implemented
- sample registry and wiki fixture loading works

#### Milestone B: capture and propagate raw
- `capture_raw` writes pages and propagates manifest/index/logs
- A-level gate passes/fails correctly

#### Milestone C: compile and query baseline
- `compile_update analyze/apply` works for atom/synthesis
- lexical retrieval query path works for six query types
- layered L1/L2/L3 output works

#### Milestone D: lint, sync, feedback
- lint catches schema and anti-island issues
- Obsidian/plain markdown sync path works
- feedback creates review queue items
- weekly review report renders from stored signals

#### Milestone E: approvals and smoke tests
- C-level proposal/approval over MCP works
- multi-wiki and shared wiki smoke tests pass
- cross-wiki retrieval is demonstrated

## 13. Implementation Constraints

1. Use Python with `Typer`, `FastAPI`, Python MCP SDK, `pydantic`, and SQLite.
2. Keep core interfaces pluggable and separate from default implementations.
3. Prefer file-visible, reviewable state over opaque runtime-only state.
4. Do not store `vectors.db` or binary raw attachments in Git.
5. Keep runtime service local-only in Phase 1.
6. Keep adapter code thin; no duplicated business logic in transports.
7. Preserve document and code clarity so external reviewers can audit decisions without hidden context.

## 14. Out-of-Scope Clarifications

These are intentionally not required for Phase 1 completion:

- production-ready team collaboration workflows
- network-exposed auth service
- non-local distributed locking
- automatic graph-driven restructuring
- high-scale optimization beyond a correct local baseline

## 15. Implementation Entry Decision

This spec marks the approved transition from brainstorming into implementation planning and TDD delivery.

The next required step after approval of this document is:

1. write implementation plan(s) under `.hermes/plans/`
2. scaffold project engineering files
3. implement Phase 1 milestone-by-milestone with TDD
4. run code review before claiming completion
