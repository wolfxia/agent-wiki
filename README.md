# Agent Wiki

> Version: v0.1.0  
> Date: 2026-05-16  
> Status: Repository overview aligned against the current Phase 1 implementation
>
> A universal, agent-agnostic knowledge system for AI agents.
>
> One knowledge asset base, many agent frontends: Hermes can search it, Claude Code can update it, Codex can query it, OpenClaw can maintain it, and OpenCode can reuse it.

Agent Wiki is a Phase 1 implementation of a **personal multi-agent knowledge workflow** built around a shared core, a Git-first authority model, and thin agent adapters.

## Why this exists

Most agent knowledge systems are tightly coupled to one tool, one memory mechanism, or one UI. Agent Wiki takes a different approach:

- **knowledge should outlive the current agent session**
- **multiple agents should operate on the same knowledge base**
- **Git should remain the authority of record**
- **retrieval, compilation, and maintenance should be explicit workflows, not hidden prompt tricks**

The Phase 1 loop is:

```text
capture_raw → compile_update → query → lint → sync → weekly-review
```

## Architecture at a glance

### System overview

![System overview](docs/architecture/system-overview.svg)

### Write propagation

![Write propagation](docs/architecture/write-propagation.svg)

### Query and retrieval flow

![Query retrieval flow](docs/architecture/query-retrieval.svg)

> Note: the diagrams above are part of the repository architecture assets under `docs/architecture/`. They reflect the current Phase 1 implementation direction. Some richer propagation, governance, and deployability behaviors remain design targets beyond the current baseline.

## What Agent Wiki does

### Implemented runtime subsystems in the current Phase 1 baseline

These subsystems exist in the current `src/agent_wiki/` runtime implementation:

- Python package `agent_wiki` with a test-backed Phase 1 core under `src/agent_wiki/`
- registry-driven multi-wiki configuration loading
- raw capture flow with committed write and pending fallback
- compiled update flow for `atom` and `synthesis`
- lexical retrieval over `retrieval_index.jsonl`
- layered query results with L1 / L2 / L3 output
- dispute caveats in query context
- pending truth-zone inclusion only when explicitly requested
- manifest persistence and retrieval index updates
- lint checks for manifest/page and manifest/index consistency
- sync `status`, `pull-view`, and `push-view` filesystem flows
- feedback recording and review queue insertion
- weekly review summary generation
- C-level proposal / approval smoke path
- real FastMCP stdio MCP server process with five workflow tools
- `aw serve` plus `aw-agent` alias entrypoints
- workflow-complete CLI surface for query/capture/compile/lint/sync/feedback/weekly-review/approvals
- transport-parity REST workflow surface for query/capture/compile/lint/sync/feedback/weekly-review/approvals
- shared registry permissions for `hermes`, `openclaw`, and `claude-code`, with reserved low-trust `codex`
- Obsidian `push-view` with frontmatter preservation and derived graph index export
- shared wiki restrictions and cross-wiki query smoke coverage
- regression-tested Phase 1 baseline with the current suite enforced in CI and local pytest runs

### Implemented callable interfaces today

The currently callable user/agent surface includes:

- FastMCP stdio MCP server in `src/agent_wiki/transports/mcp/server.py`
- workflow-complete CLI in `src/agent_wiki/transports/cli/app.py`
- workflow-complete REST surface in `src/agent_wiki/transports/rest/app.py`
- `aw` and `aw-agent` package entrypoints

### Designed but not yet fully implemented

- authority-promotion / commit orchestration for Git-first governance
- rollback/stale-marker propagation recovery model
- richer schema/frontmatter validation
- richer review queue workflow fields
- vector provider routing and load-budget enforcement


## CLI surface today

| Command | Status | Notes |
|---|---|---|
| `aw --help` | Implemented | package/CLI help surface |
| `aw info` | Implemented | minimal runtime info stub |
| `aw capture-raw` | Implemented | raw capture workflow command |
| `aw compile-update` | Implemented | compiled update workflow command |
| `aw query` | Implemented | layered query workflow command |
| `aw lint` | Implemented | lint workflow command |
| `aw sync` | Implemented | `status` / `pull-view` / `push-view` subcommands |
| `aw feedback` | Implemented | feedback intake command |
| `aw weekly-review` | Implemented | weekly review report command |
| `aw approvals` | Implemented | `propose` / `approve` plus explicit Phase 1 `reject` placeholder |
| `aw serve` | Implemented | real FastMCP stdio service entrypoint |
| `aw-agent` | Implemented | alias entrypoint for the same service identity |

## Core design principles

- **Git is the authority** — committed knowledge lives in Git-visible artifacts.
- **Workspace is runtime state** — local pending state, proposals, and maintenance metadata live under `.agent-wiki/`.
- **Write = propagate** — writes are not just page edits; they update manifest, retrieval, logs, and queue state.
- **Compile and retrieve are one closed loop** — intake feeds compilation, compilation defines retrieval units, and misses feed maintenance.
- **Agent adapters stay thin** — core behavior belongs to the shared engine, not individual agent integrations.

## Phase 1 global priorities

The canonical release priority ordering across the doc suite is:

- **P0** — usable retrieval quality and Obsidian-connected workflow
- **P1** — knowledge lifecycle automation and purpose-driven evolution
- **P2** — governance hardening for stronger multi-agent claims
- **P3** — authority/deployability/operational maturity

This ordering reflects the combined synthesis from Codex, Claude Code, and Tao: Phase 1 must be usable first, then self-evolving, then safely governable for stronger claims.

## Gate model

The canonical runtime gate model is:

- **A** — raw/source capture
- **B** — atom/synthesis/dispute updates
- **C** — principle and other high-risk writes

`D` is reserved only as a DFX maintenance/design note and is **not** a formal runtime gate level.

## Agent capability matrix

| Agent | Tier | Transport | Current Phase 1 capability | Constraints |
|---|---|---|---|---|
| Hermes | T1 Full | MCP / CLI | query, capture_raw, compile_update, lint, sync | strongest integration target for shared workflow |
| Claude Code | T2 Standard | MCP / CLI / REST | capture, compile, query, lint, sync, feedback, weekly review, approvals | no built-in scheduler or vector search |
| Codex | T3 Minimal | CLI `aw` + identity profile | query, capture_raw | reserved low-trust profile, no truth-zone writes |
| OpenClaw | T1 Full | MCP / CLI | query, capture_raw, compile_update, lint, sync | prompt-based skill environment |
| OpenCode | T3 Minimal | CLI wrapper | query, capture_raw style flows | no persistent state |

For deeper per-agent notes, see `docs/agent-differences.md`.

## Current implementation map

The current runtime implementation lives under `src/agent_wiki/` and is organized by subsystem.

### Bootstrap and configuration

- `src/agent_wiki/bootstrap/registry_loader.py` — registry and wiki config loading
- `src/agent_wiki/bootstrap/container.py` — minimal service container
- `src/agent_wiki/settings.py` — default paths

### Application services

- `src/agent_wiki/application/capture_raw.py` — A-level raw capture
- `src/agent_wiki/application/compile_update.py` — B-level compiled updates
- `src/agent_wiki/application/query.py` — lexical query pipeline and cross-wiki query
- `src/agent_wiki/application/linting.py` — Phase 1 lint checks
- `src/agent_wiki/application/sync.py` — `status`, `pull-view`, `push-view`
- `src/agent_wiki/application/feedback.py` — feedback intake and queue creation
- `src/agent_wiki/application/weekly_review.py` — weekly summary generation
- `src/agent_wiki/application/approvals.py` — C-level proposal and approval smoke path
- `src/agent_wiki/application/propagation.py` — write propagation orchestration

### Domain and contracts

- `src/agent_wiki/domain/models.py` — typed inputs/outputs
- `src/agent_wiki/domain/contracts.py` — runtime contracts and hit shapes
- `src/agent_wiki/domain/enums.py` — gate, page type, actor enums

### Infrastructure

- `src/agent_wiki/infrastructure/storage/manifest_repo.py` — manifest JSONL persistence
- `src/agent_wiki/infrastructure/retrieval/retrieval_index.py` — retrieval index writes and lexical search
- `src/agent_wiki/infrastructure/runtime/pending_state.py` — pending manifest state
- `src/agent_wiki/infrastructure/runtime/review_queue.py` — review queue JSONL appends
- `src/agent_wiki/infrastructure/runtime/operation_log.py` — operation log JSONL appends
- `src/agent_wiki/infrastructure/identity/*.py` — identity, permission, and gate helpers

### Transport

- `src/agent_wiki/transports/cli/app.py` — workflow-complete CLI surface and `aw` / `aw-agent` entrypoints
- `src/agent_wiki/transports/mcp/server.py` — real FastMCP stdio MCP server with five workflow tools
- `src/agent_wiki/transports/rest/app.py` — workflow-complete REST surface

### Legacy / non-authoritative paths

- `engine/` exists in the repository but is not the authoritative runtime implementation path for the current Phase 1 baseline.
- Contributors should treat `src/agent_wiki/` as the active runtime tree unless or until the repository explicitly reintroduces `engine/` as a supported path.

## Repository structure

```text
agent-wiki/
├── README.md
├── pyproject.toml
├── Makefile
├── Dockerfile
├── src/agent_wiki/
│   ├── application/
│   ├── bootstrap/
│   ├── domain/
│   ├── infrastructure/
│   └── transports/
├── tests/
│   ├── fixtures/
│   └── test_*.py
├── core/
│   └── schema.md
├── docs/
│   ├── design.md
│   ├── requirements-and-architecture.md
│   ├── agent-differences.md
│   └── architecture/
└── .agent-wiki/
    └── plans/
```

## Quick Start

### 1. Clone and run tests

```bash
git clone https://github.com/<your-org>/agent-wiki.git
cd agent-wiki
python3 -m pytest
```

### 2. Inspect the current CLI surface

```bash
python3 -m agent_wiki.transports.cli.app --help
python3 -m agent_wiki.transports.cli.app info
python3 -m agent_wiki.transports.cli.app sync status
```

Or, after installing the package locally:

```bash
pip install -e .
aw --help
aw info
aw-agent --help
```

### 3. Review the design baseline

Start here if you want the design and implementation context:

- `docs/design.md`
- `docs/requirements-and-architecture.md`
- `core/schema.md`
- `docs/agent-differences.md`
- `docs/superpowers/specs/2026-05-16-phase-1-design.md`
- `docs/reviews/`

## Example workflows

### Raw capture

Phase 1 currently implements raw capture in `src/agent_wiki/application/capture_raw.py`.

Conceptually:

```text
raw note/source
  → validate doc_id
  → write pages/{doc_id}.md
  → append MANIFEST.jsonl
  → append retrieval_index.jsonl
  → append log.md
```

Invalid raw doc IDs are not committed; they fall back to pending state in `.agent-wiki/pending_manifest.jsonl`.

### Compile update

Compiled updates currently support `atom` and `synthesis` in `src/agent_wiki/application/compile_update.py`.

Conceptually:

```text
compile_update analyze
  → find existing doc or matching problem cluster
  → classify create vs revise
  → validate source_refs
  → propagate compiled page + manifest + retrieval + logs
```

### Query

The current query path is lexical and file-backed:

```text
query
  → classify query type
  → lexical search over retrieval_index.jsonl
  → optional pending truth-zone inclusion
  → manifest-backed filtering and ranking
  → L1 answer + L2 context + L3 proof
```

## Documentation guide

- `docs/specs/knowledge-system-architecture.md` — authoritative end-state architecture spec for intake, compilation, retrieval, and maintenance
- `docs/design.md` — architecture design and implementation alignment
- `docs/requirements-and-architecture.md` — requirements baseline and phase-boundary decisions
- `core/schema.md` — operation contract and schema expectations
- `docs/agent-differences.md` — per-agent adaptation notes
- `docs/reviews/` — internal review materials and review responses

## Testing status

The current repository baseline includes passing milestone tests for:

- scaffold and bootstrap
- raw capture and propagation
- compile analyze/apply
- lexical query and layered output
- lint, sync, feedback, weekly review
- approvals, shared wiki, multi-wiki, and cross-wiki smoke paths

Run the full suite with:

```bash
python3 -m pytest
```

## Roadmap

### P0 — Must be usable

- make source intake produce compile-ready raw authority entries instead of metadata-empty imports
- enforce metadata continuity: low-confidence raw metadata is acceptable, null critical metadata is not
- strengthen lexical retrieval quality for real use
- replace the current CJK-bigram lexical baseline with stronger structured and indexed retrieval in later phases
- add hit/miss tracking in the query path
- ship Obsidian-connected workflow as a real adoption path

### P1 — Must keep knowledge evolving

- add auto-compile suggestions when raw pages accumulate by topic/problem cluster
- add fast feedback triggers from repeated low-value queries
- make `purpose.md` influence ranking, compile direction, and health evaluation
- add low-cost candidate relations such as co-occurrence and cross-reference

### P2 — Must support stronger governance claims

- enforce trusted identity precedence
- enforce `max_gate` centrally
- add page-level sensitivity policy and filtering
- expand review queue lifecycle records

### P3 — Must complete authority and operational maturity

- add authority-promotion / commit orchestration
- deepen DFX readiness criteria and runbooks

## Honest status note

This repository now has a working, tested **Phase 1 baseline implementation** with real MCP/CLI/REST transport surfaces, shared registry permissions, and explicit Obsidian push-view support. It is still not the full end-state architecture described in the design docs. In particular, richer propagation guarantees, authority-promotion/commit orchestration, deeper schema enforcement, and broader deployability/operations work remain design targets.

That split is intentional: the project is being built from the Phase 2 target architecture, but landed incrementally in Phase 1.

## License

MIT
