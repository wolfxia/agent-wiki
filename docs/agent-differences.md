# Agent Differences & Adaptation Strategy

> How agent-wiki adapts to each agent's unique capabilities

---

## Capability Matrix

| Capability | Hermes | Claude Code | Codex | OpenClaw | OpenCode |
|-----------|--------|-------------|-------|----------|----------|
| **Execution Model** | Skill (SKILL.md) | CLAUDE.md + Bash | CLI `aw` + identity profile | Skill prompt | CLI `opencode run` |
| **Scheduling** | Built-in cronjob | External cron/launchd | None | Built-in cron | External cron |
| **File I/O** | terminal + file tools | Bash commands | CLI commands | Skill prompt | `-f` file attach |
| **Vector Search** | `memory_search` built-in | ❌ Needs adapter | ❌ Needs adapter | ❌ Needs adapter | ❌ Needs adapter |
| **Semantic Memory** | `memory` tool built-in | ❌ None | ❌ None | ❌ None | ❌ None |
| **Human Interface** | Feishu/WeChat native | Terminal | Terminal | Feishu native | Terminal |
| **Editor Sync** | Obsidian sync cron | None (code-focused) | None | Obsidian sync cron | None |
| **Knowledge Path** | `~/hermes-projects/knowledge/` | `~/workspace/code/` | Project-scoped | `~/.openclaw/workspace/` | Project-scoped |
| **Config Format** | config.yaml | settings.local.json | identity profile / config.yaml | agents/*.json | config.yaml |
| **Background Tasks** | Built-in (cronjob) | Manual | Manual | Built-in (cron) | Manual |
| **Multi-tool** | Rich (browser, web, etc.) | Terminal only | Terminal only | Rich (browser, web) | Terminal only |
| **Context Injection** | Memory + Skills + .env | CLAUDE.md + hooks | aw CLI + identity profile | Skills + identity | Config + flags |

---

## Per-Agent Adaptation Strategy

All agents call the same `aw-agent` core. Agent-specific code must be a thin client: MCP connection config, CLI profile, cron trigger, or message-channel wrapper. No agent adapter owns retrieval, ingest, lint, sync, propagation, or gate logic.

### Hermes (Most Capable — Full Feature)

**Leverage**: Built-in cron, memory_search, rich toolset, Feishu integration

**Adapter approach**: 
- Hermes skills call `aw-agent` MCP tools such as `wiki.query`, `wiki.capture_raw`, `wiki.compile_analyze`, and `wiki.sync`
- PropagationEngine runs inside `aw-agent`, not inside Hermes skills
- cronjob triggers `aw-agent` sync, lint, and weekly-review jobs
- Obsidian sync as built-in cron
- Feishu alerts for lint failures and gate status

**Unique optimization**:
- `memory_search` can supplement vector search for semantic recall
- `memory_search` can be an optional signal, but `aw-agent` Phase 1 query must still work through lexical retrieval baseline
- `cronjob` enables automated Phase D maintenance
- `send_message` for human-in-the-loop on principle promotion

**Limitation**: Memory 5000-char cap; knowledge must live in files, not memory

---

### Claude Code (Code-Focused — Minimal Adapter)

**Leverage**: CLAUDE.md injection, Bash execution, git integration, strong code reasoning

**Adapter approach**:
- CLAUDE.md appendix with wiki usage instructions
- Bash wrapper scripts call CLI `aw` or MCP tools exposed by `aw-agent`
- No built-in scheduling — rely on Hermes cron or external launchd
- No built-in vector search — rely on `aw-agent` lexical baseline or optional retrieval provider

**Unique optimization**:
- CC excels at code-related knowledge (architecture decisions, API contracts)
- Can directly modify wiki files with high confidence
- Git integration means wiki changes are tracked
- Code review can be augmented with wiki-query for context

**Limitation**: 
- No persistent memory across sessions
- No built-in vector search — `aw-agent` provides lexical baseline and optional vector plugin
- No scheduling — must be triggered externally

**CC Adapter Structure**:
```
adapters/claude-code/
├── CLAUDE.md.append          ← Append to project CLAUDE.md
├── hooks/
│   ├── post-write.sh         ← Trigger aw sync/gate after allowed wiki file write
│   └── pre-query.sh          ← Call aw query before answering
├── commands/
│   ├── wiki-query.sh         ← /wiki-query slash command wrapper
│   ├── wiki-ingest.sh        ← /wiki-ingest slash command wrapper
│   └── wiki-lint.sh          ← /wiki-lint slash command wrapper
└── README.md
```

---

### OpenClaw (Closest to Hermes — Skill-Based)

**Leverage**: Skill system, built-in cron, Feishu integration, existing knowledge-base structure

**Adapter approach**:
- Skills in OpenClaw format call `aw-agent` MCP tools
- Cron for scheduled maintenance
- Existing SCHEMA.md in ~/.openclaw/workspace/knowledge-base/ can be upgraded
- Feishu alerts same as Hermes

**Unique optimization**:
- OpenClaw already has a knowledge-base structure with SCHEMA.md, resolvers, topics
- Can reuse existing resolver mechanism as the "hot layer" in agent-wiki
- lcm.db (SQLite) can be queried for conversation history → auto-ingest source

**Key difference from Hermes**:
- OpenClaw skills are prompt-based, not code-based
- Less flexible execution model (no arbitrary Python in skills)
- Different config format (agents/*.json not config.yaml)

**OpenClaw Adapter Structure**:
```
adapters/openclaw/
├── skills/
│   ├── wiki-query/SKILL.md       ← Query skill in OpenClaw format
│   ├── wiki-ingest/SKILL.md      ← Ingest skill in OpenClaw format
│   └── wiki-lint/SKILL.md        ← Lint skill in OpenClaw format
├── cron/
│   └── wiki-maintenance.json     ← Cron config
├── config.yaml
└── README.md
```

### Codex (CLI Agent — Minimal)

**Leverage**: `aw` CLI, identity profile, short-lived runs, provider-agnostic execution

**Adapter approach**:
- Codex calls the same `aw` CLI as other minimal agents
- Identity comes from a Codex-specific profile that resolves `actor_type=agent` and `actor_id=codex`
- No MCP capability in Phase 1
- No persistent state or scheduler; all state lives in Git/workspace only

**Unique optimization**:
- Good for one-shot knowledge work and code-heavy capture/query tasks
- Can run without a dedicated background service
- Reuses the same low-risk CLI contract as OpenCode, but with a separate identity profile

**Limitation**:
- No MCP tool access
- No background memory
- No built-in scheduling
- Must use the shared `aw-agent` core through CLI transport only

**Codex Adapter Structure**:
```
adapters/codex/
├── commands/
│   ├── wiki-query.sh          ← aw query wrapper
│   ├── wiki-capture.sh        ← aw capture-raw wrapper
│   └── wiki-lint.sh           ← aw lint wrapper
├── config.yaml
└── README.md
```

---

### OpenCode (CLI Agent — Script Wrappers)

**Leverage**: `opencode run` for one-shot tasks, `-f` for file context, provider-agnostic

**Adapter approach**:
- Shell script wrappers call CLI `aw` with an OpenCode identity profile
- No persistent state — each invocation is independent
- No scheduling — external trigger only
- No built-in vector search — `aw-agent` provides lexical baseline and optional provider

**Unique optimization**:
- Good for code-heavy knowledge tasks (refactoring patterns, architecture decisions)
- Can run in isolated worktrees for safe knowledge operations
- Provider-agnostic — can use any model

**Limitation**:
- No persistence between sessions
- No memory/search
- Must be triggered externally
- Slow for interactive knowledge work (each `opencode run` is a cold start)

**OpenCode Adapter Structure**:
```
adapters/opencode/
├── commands/
│   ├── wiki-query.sh          ← opencode run 'query wiki...' -f schema.md
│   ├── wiki-ingest.sh         ← opencode run 'ingest...' -f source.md
│   └── wiki-lint.sh           ← opencode run 'lint wiki...'
├── config.yaml
└── README.md
```

---

## Shared vs Agent-Specific

| Component | Shared (core/) | Agent-Specific (adapters/) |
|-----------|----------------|---------------------------|
| Page taxonomy | ✅ | — |
| Frontmatter schema | ✅ | — |
| Manifest schema | ✅ | — |
| Query profiles | ✅ | — |
| Retrieval pipeline logic | ✅ | — |
| Propagation engine | ✅ | — |
| Lint rules | ✅ | — |
| Retrieval providers | ✅ | — |
| **Invocation method** | — | ✅ per-agent |
| **Scheduling config** | — | ✅ per-agent |
| **Human interface** | — | ✅ per-agent |
| **External store sync** | — | ✅ per-agent |
| **Alert routing** | — | ✅ per-agent |

---

## Multi-Agent Write Conflict Strategy

When multiple agents write to the same wiki:

1. **Optimistic concurrency in Phase 1** — Write flow runs `git pull --rebase` before commit.
2. **manifest as coordination point** — manifest records `last_writer` and `last_write_at`.
3. **Conflict detection** — Rebase/file conflicts enter `review_queue` with conflict snapshots in `.agent-wiki/`.
4. **Human adjudication** — High-impact C-level conflicts require MCP/message-channel confirmation.
5. **Agent identity** — Each committed operation records resolved `actor_type` and `agent_id` for traceability.
6. **Lock interface reserved** — Explicit doc/topic locks are Phase 2 interfaces; Phase 1 lock implementation is no-op.

---

## Recommended Priority

1. **Hermes adapter first** — Most capable, already has most pieces
2. **OpenClaw adapter second** — Similar architecture, can reuse patterns
3. **Claude Code adapter third** — Different model, but high value (code knowledge)
4. **OpenCode adapter last** — Most limited, can use same scripts as CC
