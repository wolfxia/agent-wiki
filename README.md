# Agent Wiki

> Version: v0.2.0
> Date: 2026-05-17
> Status: working multi-agent knowledge system with MCP, CLI, REST, Obsidian sync, FTS5 retrieval, and graph visualization.
>
> One knowledge base, many agent frontends: Hermes, Claude Code, Codex, OpenClaw, and other agents can query, capture, compile, lint, and sync through shared core services.

Agent Wiki is an agent-agnostic knowledge system for long-lived AI memory. It treats the workspace as the single source of truth, exposes a real FastMCP stdio server for agents, and keeps human-facing tools such as Obsidian as read-write views over the same authority model.

Current data baseline: **1472 workspace pages**, **1488 manifest entries**, **383 indexed topics**, and **235 passing tests**.

## Quick Integration Guide

### Connect Through MCP

Hermes and other MCP clients should run Agent Wiki as a stdio sidecar. Always pass explicit actor identity through environment variables; request payloads must not override identity.

```json
{
  "mcpServers": {
    "agent-wiki": {
      "command": "aw",
      "args": ["serve", "--registry", "/Users/chao/agent-wiki-data/registry.yaml"],
      "env": {
        "AGENT_WIKI_ACTOR_TYPE": "agent",
        "AGENT_WIKI_ACTOR_ID": "hermes"
      }
    }
  }
}
```

Available MCP tools:

| Tool | Purpose |
|---|---|
| `wiki.query` | Query the knowledge base with layered results and debug scores |
| `wiki.capture_raw` | Capture raw source or learning notes |
| `wiki.compile_prepare` | Prepare agent-facing raw evidence packets for compilation |
| `wiki.compile_update` | Create or revise `atom` / `synthesis` pages |
| `wiki.lint` | Check manifest, retrieval index, FTS, and consistency health |
| `wiki.sync` | Run explicit `status`, `pull-view`, or `push-view` sync |

### Connect Through CLI

```bash
pip install -e ".[dev]"
export AGENT_WIKI_ACTOR_TYPE=agent
export AGENT_WIKI_ACTOR_ID=hermes

aw health --registry /Users/chao/agent-wiki-data/registry.yaml
aw query "MCP integration" --registry /Users/chao/agent-wiki-data/registry.yaml --wiki-id main
```

Required environment variables:

| Variable | Example | Meaning |
|---|---|---|
| `AGENT_WIKI_ACTOR_TYPE` | `agent` | Identity class used by registry permissions |
| `AGENT_WIKI_ACTOR_ID` | `hermes` | Concrete actor id, for example `hermes`, `claude-code`, or `codex` |

### Add A New Agent To `registry.yaml`

Add a permission entry under the target wiki. T1 agents can use C-level gates; T2 agents normally stop at B; T3 agents should usually be A-level capture/query only.

```yaml
permissions:
  - actor_type: agent
    actor_id: new-agent
    allowed_operations: [query, capture_raw, compile_update, lint, sync]
    max_gate: B
    allowed_page_types: [raw, atom, synthesis]
```

### Capture And Query Example

```bash
aw capture-raw learn-2026-05-17-mcp-integration \
  --topic "agent-os" \
  --problem-cluster "mcp-integration" \
  --content "# MCP integration note\nHermes should run agent-wiki as a stdio MCP sidecar." \
  --registry /Users/chao/agent-wiki-data/registry.yaml \
  --wiki-id main

aw query "How should Hermes connect to agent-wiki?" \
  --registry /Users/chao/agent-wiki-data/registry.yaml \
  --wiki-id main
```

## Architecture Decisions

Agent Wiki follows this authority chain:

```text
workspace SSOT -> local runtime indexes -> external human views
```

Core decisions in v0.2.0:

- **Workspace = SSOT**: committed pages, `MANIFEST.jsonl`, `retrieval_index.jsonl`, `topic_index.md`, logs, and review records live in the workspace.
- **Obsidian = display/read-write view**: Obsidian is for humans. `pull-view` imports edits into the workspace; `push-view` exports workspace pages back to the vault.
- **Thin transports**: MCP, CLI, and REST call the same application services and permission gates.
- **Trusted identity resolution**: actor identity comes from MCP metadata, CLI env, token/env, or registry fallback. Callers do not set their own identity in tool payloads.
- **Team expansion model**: the architecture supports N personal workspaces plus M team workspaces, with permission tiers per actor, wiki, operation, page type, and A/B/C gate.
- **Compile and retrieval are one loop**: intake metadata feeds compile candidates, compiled schema feeds retrieval, query misses feed feedback and weekly review.

### Compile Pipeline

The compile pipeline turns raw evidence into agent working memory. Its primary goal is better agent retrieval and reasoning; human-readable presentation is a secondary benefit.

```text
raw intake
  -> compile_prepare
       -> agent-facing evidence packet
          claims, relationship hints, contradiction markers, source_refs
  -> review_queue compile_suggestion
       -> open -> assigned -> in_progress -> resolved -> archived
  -> agent-authored compile_update
       -> atom / synthesis truth zone
  -> retrieval indexes
       -> better query answers and second-order curation
```

`wiki.compile_prepare` is read-only. It prepares bounded raw batches and traceable source refs, but it does not generate truth-zone prose inside Agent Wiki. Agents such as Hermes or Claude Code consume the packet, write the semantic synthesis, and call `wiki.compile_update`.

## What Is New In v0.2.0

- FTS5 full-text search through `SQLiteFTSIndexProvider`, stored in `.agent-wiki/retrieval.db`.
- Query ranking now exposes debug scores: `page_type_boost`, `lexical_score`, `structured_score`, `purpose_boost`, and `freshness`.
- Index consistency health checks cover manifest, `retrieval_index.jsonl`, FTS, pages, and topic index consistency.
- `aw migrate --normalize-doc-ids` lowercases and hyphenates old `doc_id`s, renames page files, updates source refs, and backs up `MANIFEST.jsonl`.
- Obsidian `push-view` exports workspace pages by category: `raw -> 00-收件箱`, `atom + learning -> 01-学习笔记`, `synthesis -> 02-行业洞察`, `graph -> 04-知识图谱`.
- Obsidian frontmatter dates are sanitized so YAML dates do not break JSON serialization during `pull-view`.
- Knowledge graph visualizer ships as `knowledge-graph.html`, using sigma.js, graphology, and ForceAtlas2.
- MCP `wiki.capture_raw` bug fix prevents the previous `name summary not defined` failure.

## Runtime Surfaces

### CLI

| Command | Purpose |
|---|---|
| `aw info` | Show package/runtime info |
| `aw health` | Registry load, actor resolution, and tool-list self-check |
| `aw serve` | Start FastMCP stdio server |
| `aw query` | Query the knowledge base |
| `aw capture-raw` | Capture raw source or learning note |
| `aw compile-prepare` | Prepare agent-facing raw evidence packets for compilation |
| `aw compile-update` | Create or revise compiled truth-zone pages |
| `aw review-queue-consume` | Assign the next open review queue item of a given type |
| `aw lint` | Run consistency checks |
| `aw sync status` | Inspect external view sync status |
| `aw sync pull-view` | Import external view edits into workspace |
| `aw sync push-view` | Export workspace pages to external views |
| `aw feedback` | Record query or content feedback |
| `aw weekly-review` | Produce maintenance review summary |
| `aw approvals propose/approve/reject` | C-level proposal workflow; `reject` is currently a placeholder and exits with code 1 |
| `aw migrate --slugify-doc-ids` | Preserve vault relative path in doc ids |
| `aw migrate --normalize-doc-ids` | Normalize doc ids to lowercase hyphen form |
| `aw maintain` | Run maintenance checks and queue generation |
| `aw-agent` | Alias entrypoint for the same CLI/service package |

### MCP

The primary agent path is MCP stdio through `aw serve`. The MCP surface intentionally stays small:

```text
wiki.query
wiki.capture_raw
wiki.compile_prepare
wiki.compile_update
wiki.lint
wiki.sync
```

### REST

REST is an auxiliary transport for local tooling and tests. It exposes workflow parity for query, capture, compile prepare/update, review queue consume, lint, sync, feedback, weekly review, approvals, and health, but Hermes integration should prefer MCP stdio.

## Retrieval And Knowledge Flow

```text
capture_raw / pull-view
  -> metadata normalization
  -> pages/*.md + MANIFEST.jsonl
  -> retrieval_index.jsonl + .agent-wiki/retrieval.db
  -> topic_index.md
  -> query ranking + debug scores
  -> feedback / weekly-review / compile backlog
```

Retrieval currently combines structured metadata, lexical matching, FTS5 index health, purpose-aware ranking, page type boosts, and freshness. Vector search remains a plugin-level enhancement rather than the baseline.

Note: `registry.yaml` `coarse_provider` is design/configuration metadata today; it is not yet the runtime switch that selects the active retrieval provider.

## Obsidian Workflow

Obsidian is a human editing and reading surface, not the authority. The workspace remains authoritative.

- `aw sync pull-view` reads Markdown files recursively, ignores `.obsidian` and trash folders, preserves vault-relative paths, sanitizes frontmatter, and imports successful raw pages into manifest and retrieval indexes.
- `aw sync push-view` exports workspace pages to the vault with category routing and preserves frontmatter where possible.
- The graph index and visual graph belong under `04-知识图谱` for human exploration.

## Repository Structure

```text
agent-wiki/
├── README.md
├── AGENTS.md
├── pyproject.toml
├── Dockerfile
├── knowledge-graph.html
├── serve_graph.sh
├── core/
│   └── schema.md
├── docs/
│   ├── ROADMAP.md
│   ├── design.md
│   ├── requirements-and-architecture.md
│   ├── deployment/
│   ├── architecture/
│   └── specs/
├── src/agent_wiki/
│   ├── application/
│   ├── bootstrap/
│   ├── domain/
│   ├── infrastructure/
│   │   ├── adapters/
│   │   ├── identity/
│   │   ├── migrations/
│   │   ├── retrieval/
│   │   ├── runtime/
│   │   └── storage/
│   └── transports/
│       ├── cli/
│       ├── mcp/
│       └── rest/
└── tests/
    ├── fixtures/
    └── test_*.py
```

Run `./serve_graph.sh` to start a local HTTP server for the graph visualizer on `:8765`.

## Development

Install and verify:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

Current verified suite: **235 passed**.

Useful operational checks:

```bash
aw health --registry /Users/chao/agent-wiki-data/registry.yaml
aw lint --registry /Users/chao/agent-wiki-data/registry.yaml --wiki-id main
aw sync status --registry /Users/chao/agent-wiki-data/registry.yaml --wiki-id main
```

## Documentation Map

- `docs/specs/knowledge-system-architecture.md` — authoritative end-state model for intake, compilation, retrieval, and maintenance.
- `docs/design.md` — current baseline vs target design.
- `docs/requirements-and-architecture.md` — requirements, phase boundaries, and architecture constraints.
- `docs/ROADMAP.md` — v0.2+ execution order and known issues.
- `docs/deployment/hermes-mcp.md` — Hermes MCP sidecar configuration.
- `core/schema.md` — operation and schema contract.

## License

MIT
