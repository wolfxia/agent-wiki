# Agent Wiki

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

![System overview](docs/architecture/system-overview.png)

### Write propagation

![Write propagation](docs/architecture/write-propagation.png)

### Query and retrieval flow

![Query retrieval flow](docs/architecture/query-retrieval.png)

> Note: the diagrams above are part of the repository architecture assets under `docs/architecture/`. They reflect the current Phase 1 implementation direction, with some future MCP/REST and richer propagation behaviors still documented as design targets.

## What Agent Wiki does

### Implemented in the current Phase 1 baseline

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
- shared wiki restrictions and cross-wiki query smoke coverage
- 32 passing tests covering M1-M6

### Designed but not yet fully implemented

- MCP transport surface
- REST transport surface
- full gate enforcement against `max_gate`
- rollback/stale-marker propagation recovery model
- richer schema/frontmatter validation
- richer review queue workflow fields
- vector provider routing and load-budget enforcement
- adapter-specific reverse sync semantics beyond copy-based Phase 1 behavior

## Core design principles

- **Git is the authority** — committed knowledge lives in Git-visible artifacts.
- **Workspace is runtime state** — local pending state, proposals, and maintenance metadata live under `.agent-wiki/`.
- **Write = propagate** — writes are not just page edits; they update manifest, retrieval, logs, and queue state.
- **Compile before retrieve** — raw sources feed compiled artifacts, then retrieval operates over those artifacts.
- **Agent adapters stay thin** — core behavior belongs to the shared engine, not individual agent integrations.

## Agent capability matrix

| Agent | Tier | Transport | Current Phase 1 capability | Constraints |
|---|---|---|---|---|
| Hermes | T1 Full | MCP / CLI design target | design target for full workflow | strongest integration target, not implemented in this repo yet |
| Claude Code | T2 Standard | CLI today, MCP later | capture, compile, query, lint, sync-triggered workflows | no built-in scheduler or vector search |
| Codex | T3 Minimal | CLI `aw` + identity profile | query, capture_raw | no MCP, no persistent state |
| OpenClaw | T1 Full | MCP / CLI design target | design target for full workflow | prompt-based skill environment |
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

- `src/agent_wiki/transports/cli/app.py` — current CLI stub surface

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
```

Or, after installing the package locally:

```bash
pip install -e .
aw --help
aw info
```

### 3. Review the design baseline

Start here if you want the design and implementation context:

- `docs/design.md`
- `docs/requirements-and-architecture.md`
- `core/schema.md`
- `docs/agent-differences.md`
- `docs/superpowers/specs/2026-05-16-phase-1-design.md`

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

- `docs/design.md` — architecture design and implementation alignment
- `docs/requirements-and-architecture.md` — requirements baseline and phase-boundary decisions
- `core/schema.md` — operation contract and schema expectations
- `docs/agent-differences.md` — per-agent adaptation notes

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

### Near-term documentation and alignment

- align architecture docs to the current implementation baseline
- keep design intent explicit where implementation is still partial
- expand README and architecture materials for external reviewability

### Near-term implementation gaps

- flesh out the `aw` CLI beyond the current minimal stub
- add MCP transport surface
- add REST transport surface
- enforce `max_gate` and richer permission checks
- deepen lint and sync behavior to match the target design

### Phase 2 direction

- stronger multi-writer coordination
- team-facing RBAC/OIDC
- richer external adapters
- deeper retrieval providers and graph-assisted workflows

## Honest status note

This repository now has a working, tested **Phase 1 baseline implementation**, but it is not yet the full end-state architecture described in the design docs. In particular, MCP/REST, richer propagation guarantees, and deeper schema enforcement remain design targets rather than fully implemented runtime features.

That split is intentional: the project is being built from the Phase 2 target architecture, but landed incrementally in Phase 1.

## License

MIT
