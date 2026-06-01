# Agent Wiki

> Version: v0.5.0
> Date: 2026-06-01
> Status: working multi-agent knowledge system with MCP, CLI, REST, Obsidian sync, FTS5 retrieval, graph visualization, compile quality gate, diagnosis engine, controlled self-evolution, and public extension APIs.
>
> One knowledge base, many agent frontends: Hermes, Claude Code, Codex, OpenClaw, and other agents can query, capture, compile, lint, and sync through shared core services.

Agent Wiki is an agent-agnostic knowledge system for long-lived AI memory. It treats the workspace as the single source of truth, exposes a real FastMCP stdio server for agents, and keeps human-facing tools such as Obsidian as read-write views over the same authority model.

For downstream integration and extension patterns, see [docs/extensions.md](docs/extensions.md).

Current data baseline: **5204 workspace pages**, **4724 manifest entries**, **4723 indexed entries**, and **387 passing tests**.

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

Obsidian routing example:

```yaml
external_views:
  - adapter: obsidian
    mode: read_write
    path: /path/to/vault
    push_view_routing:
      direction_folders:
        agent-os: Agent OS
      fallback_folders:
        raw: raw
        atom: atoms
        synthesis: synthesis
        principle: principles
      graph_index_folder: knowledge-graph
      graph_index_title: Knowledge Graph Index
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

### System Overview

![v0.5 System Overview](docs/architecture/system-overview.svg)

### Compile Pipeline & Self-Evolution

![v0.4 Compile Pipeline and Self-Evolution](docs/architecture/v0.4-compile-pipeline-and-self-evolution.svg)

The compile pipeline turns raw evidence into agent working memory. v0.4 adds a 4-layer quality gate with retry pipeline, and feeds compiled results into the self-evolution loop: eval → diagnosis → tuning → verify → compile strategy → value metrics → next cycle.

### Write Propagation

![Write Propagation](docs/architecture/write-propagation.png)

### Query and Retrieval

![Query and Retrieval](docs/architecture/query-retrieval.png)

## Architecture Decisions

Agent Wiki follows this authority chain:

```text
workspace SSOT -> local runtime indexes -> external human views
```

Core decisions in v0.4.0:

- **Workspace = SSOT**: committed pages, `MANIFEST.jsonl`, `retrieval_index.jsonl`, `topic_index.md`, logs, and review records live in the workspace.
- **Obsidian = display/read-write view**: Obsidian is for humans. `pull-view` imports edits into the workspace; `push-view` exports workspace pages back to the vault.
- **Thin transports**: MCP, CLI, and REST call the same application services and permission gates.
- **Trusted identity resolution**: actor identity comes from MCP metadata, CLI env, token/env, or registry fallback. Callers do not set their own identity in tool payloads.
- **Team expansion model**: the architecture supports N personal workspaces plus M team workspaces, with permission tiers per actor, wiki, operation, page type, and A/B/C gate.
- **Compile and retrieval are one loop**: intake metadata feeds compile candidates, compiled schema feeds retrieval, query misses feed feedback and weekly review.
- **Typed graph is configurable**: `relation_schema.yaml` defines zero-LLM relation extraction, `maintain` rebuilds `knowledge_graph.jsonl`, graph relations carry `confidence_label` / `confidence_score` / `source_refs`, ambiguous relations are routed to `relation_review` items, and query ranking weights extracted vs inferred relations when graph hits are available.
- **v0.4 Compile quality gate**: 4-layer gate (schema validation → required sections → claim coverage → source fidelity) with retry pipeline (transport retry → output repair → quality rewrite → human review).
- **v0.4 Diagnosis engine**: pure-rule attribution (5 types: `parameter_drift`, `retrieval_ranking_shift`, `compile_quality_degradation`, `coverage_gap`, `staleness`) — no LLM dependency.
- **v0.4 Runtime tuning**: two-layer config (`registry.yaml` stable defaults + `runtime_tuning.json` dynamic overrides) with `param_history.jsonl` audit trail and `frozen_baseline.json` for auto-rollback.
- **v0.4 Controlled self-evolution**: `auto_tune` (whitelist, single-variable, step constraint, recall-drop rollback), `compile_strategy` (Light/Standard/Deep via `priority_score`), `value_metrics` (post-compile query uplift, atom reference rate), `staleness_governance`.

### Compile Pipeline

The compile pipeline turns raw evidence into agent working memory. Its primary goal is better agent retrieval and reasoning; human-readable presentation is a secondary benefit.

```text
raw intake
  -> review_queue compile_suggestion
       -> priority ordered open work items
  -> aw compile-execute
       -> claims compile_suggestion and emits compile_prepare JSON
       -> external agent writes content and calls back with --input-file
  -> compile quality gate (v0.4)
       -> 4-layer check: schema, sections, claim coverage, source fidelity
       -> retry: transport → output repair → quality rewrite → human review
  -> agent-authored compile_update
       -> atom / synthesis truth zone
  -> retrieval indexes
       -> better query answers and second-order curation
```

`wiki.compile_prepare` is read-only. It prepares bounded raw batches and traceable source refs, but it does not generate truth-zone prose inside Agent Wiki. `aw compile-execute` is the CLI bridge for cron workers: without `--input-file` or `--apply` it claims suggestions and prints evidence packets as JSON; with `--input-file` it applies generated content through `compile_update`; with `--apply` it runs the full loop in one command: prepare, call an OpenAI-compatible chat completions API, apply the generated atom page, and resolve or fail the queue item. `--apply --concurrency N` parallelizes only LLM generation; authority writes to pages, `MANIFEST.jsonl`, `review_queue.jsonl`, FTS, and `topic_index.md` remain serialized by the executor.

LLM compile output is requested as structured JSON with `content`, `summary`, `aliases`, `confidence`, `wikilinks`, `claims`, `open_questions`, and `evidence_coverage`. `content` remains the Markdown page body, while supported metadata fields are written through `CompileGeneratedInput` into `MANIFEST.jsonl`, FTS, and `topic_index.md`. Plain Markdown responses still fall back to the previous compatible path.

Each compile attempt records operational telemetry in the related `review_queue` item's `content_state`: `latency_seconds`, `attempts`, `error_type`, and `token_usage` when the provider returns usage data. This lets `aw maintain` and `QualityReportService` report failure rate, failure breakdown, average compile latency, metadata completeness, and raw-cluster coverage without changing the authority model.

`--apply` requires per-wiki registry config:

```yaml
compile:
  llm:
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY
    model: deepseek/deepseek-chat-v3-0324
    max_tokens: 4096
    timeout_seconds: 30
    max_retries: 3
    retry_delays: [10, 30, 60]
    concurrency: 1
```

## What Is New In v0.4.0

### Phase A: Evaluation Baseline
- `aw eval` / `aw eval-retrieval` now computes strict recall, loose recall, must-not violation, MRR, and compiled hit ratio against `eval/retrieval_queries.jsonl`.
- `eval_history.jsonl` records each eval run with full metrics, per-query results, and runtime tuning snapshot for regression detection.
- `quality_report` extended: `atom_field_completeness`, `section_structure_compliance`, `source_ref_coverage`, `eval_baseline`.
- Real baseline: strict_recall@5=0.479, loose_recall@5=0.542, must_not_violation@5=0.0, MRR=0.371.

### Phase B: Compile Quality Gate
- New `CompileQualityGate` service: 4-layer checks on every compile output (schema → required sections → claim coverage → source fidelity).
- `compile_prepare` enhanced: dynamic token budget, existing atom context injection, sentence-level evidence extraction.
- Retry pipeline: invalid output → output repair; quality rejected → quality rewrite; then human review.

### Phase C: Diagnosis and Tuning Loop
- New `DiagnosisService`: pure-rule attribution engine with 5 types — `parameter_drift`, `retrieval_ranking_shift`, `compile_quality_degradation`, `coverage_gap`, `staleness`.
- New `RuntimeTuningService`: two-layer config (`registry.yaml` defaults + `runtime_tuning.json` overrides). All param changes recorded in `param_history.jsonl`.
- `frozen_baseline.json`: snapshot of eval metrics at baseline time, used for rollback detection.
- Negative feedback creates `feedback_issue` items in review queue and back-writes to `query_outcomes.jsonl`.
- Duplicate atom detection in maintain: near-duplicate atoms flagged as warnings.

### Phase D: Controlled Automation
- `compile_strategy`: Light (summary only), Standard (default), Deep (3-round) — selected by `priority_score`.
- `auto_tune`: single-variable, whitelist-constrained, step-limited. Rollback when recall drops >2%. Disabled by default; requires `--auto-tune`.
- `value_metrics`: post-compile query uplift, atom reference rate, staleness governance.
- `staleness_governance`: hot stale docs auto-queued for refresh.

### Infrastructure Improvements
- `aw rebuild-index`: removes orphan index entries, rebuilds FTS from manifest.
- `aw maintain` performance: 5min+ → 8s (batch writes, FTS transactions, O(n²)→O(n) relations).
- Atomic manifest writes (temp+fsync+rename), NUL-tolerant reads, read cache.

### v0.2.0 Features (retained)
- FTS5 full-text search, query ranking debug scores, query outcome logging.
- Index consistency health checks, doc_id migration, Obsidian push-view routing, knowledge graph visualizer.

## Runtime Surfaces

### CLI

| Command | Purpose |
|---|---|
| `aw info` | Show package/runtime info |
| `aw health` | Registry load, actor resolution, and tool-list self-check |
| `aw serve` | Start FastMCP stdio server |
| `aw query` | Query the knowledge base |
| `aw eval` / `aw eval-retrieval` | Run retrieval quality evals with strict/loose recall, must-not violation, MRR metrics |
| `aw rebuild-index` | Remove orphan index entries and rebuild FTS from manifest (v0.4) |
| `aw capture-raw` | Capture raw source or learning note |
| `aw compile-prepare` | Prepare agent-facing raw evidence packets for compilation |
| `aw compile-execute` | Claim compile suggestions, emit JSON packets, apply generated content from `--input-file`, or run one-command LLM compile with `--apply` |
| `aw compile-update` | Create or revise compiled truth-zone pages |
| `aw review-queue-consume` | Assign the next open review queue item of a given type |
| `aw review-relations` | Resolve, reject, or reclassify a typed graph relation review item |
| `aw lint` | Run consistency checks |
| `aw sync status` | Inspect external view sync status |
| `aw sync pull-view` | Import external view edits into workspace |
| `aw sync push-view` | Export workspace pages to external views |
| `aw feedback` | Record query or content feedback |
| `aw weekly-review` | Produce maintenance review summary |
| `aw dream-cycle` | Run deep maintenance: orphan scan, cross-reference analysis, synthesis generation, and quality review |
| `aw approvals propose/approve/reject` | C-level proposal workflow; `reject` is currently a placeholder and exits with code 1 |
| `aw migrate --slugify-doc-ids` | Preserve vault relative path in doc ids |
| `aw migrate --normalize-doc-ids` | Normalize doc ids to lowercase hyphen form |
| `aw maintain` | Run self-evolution loop: repair, compile suggestions, relations, quality report, diagnosis, tuning (v0.4: `--auto-tune` flag) |
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

Retrieval currently combines typed graph hits from `knowledge_graph.jsonl`, FTS5 field-weighted matching, structured metadata from `topic_index.md`, JSONL lexical fallback, purpose-aware ranking, page type boosts, and freshness. Structured and lexical fallback paths prefilter obvious non-candidates before token/fuzzy scoring so historical large indexes remain usable. Typed graph hits are confidence-weighted: `EXTRACTED` is full weight, `INFERRED` is down-weighted, and `AMBIGUOUS` relations are excluded from retrieval and sent to review. Vector search remains a plugin-level enhancement rather than the baseline. A wiki can opt into typed relation extraction by adding `relation_schema.yaml`; `templates/relation_schema.yaml` provides a configurable starting point.

Note: `registry.yaml` `coarse_provider` is design/configuration metadata today; it is not yet the runtime switch that selects the active retrieval provider.

## Obsidian Workflow

Obsidian is a human editing and reading surface, not the authority. The workspace remains authoritative.

- `aw sync pull-view` reads Markdown files recursively, ignores `.obsidian` and trash folders, preserves vault-relative paths, sanitizes frontmatter, and imports successful raw pages into manifest and retrieval indexes.
- `aw sync push-view` exports workspace pages to the vault with configurable category routing and preserves frontmatter where possible.
- Obsidian graph index output defaults to `knowledge-graph/index.md`; vault-specific folders and titles belong in `external_views[].push_view_routing`.

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

Current verified suite: **387 passed**.

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
- `docs/superpowers/specs/2026-05-19-v0.4-compile-quality-and-self-evolution-design.md` — v0.4 compile quality gate and self-evolution design spec.
- `docs/deployment/hermes-mcp.md` — Hermes MCP sidecar configuration.
- `core/schema.md` — operation and schema contract.

## License

MIT
