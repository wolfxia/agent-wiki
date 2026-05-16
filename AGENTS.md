# Agent Wiki Project Instructions

Last updated: 2026-05-16

## Project Scope

This repository defines and implements **Agent Wiki**: a universal, agent-agnostic knowledge system for multi-agent collaboration.

The current work is in **Superpowers Phase 1: Brainstorming / Requirements and Architecture Design**. Do not start implementation work until the design spec is written, reviewed, and explicitly approved.

## Current Design Goal

Create a complete Phase 1 architecture specification for a personal multi-agent knowledge system, while designing interfaces with Phase 2 team collaboration in mind.

Core direction:

- Design from the Phase 2 end state, implement Phase 1 incrementally.
- Use a global `Knowledge Agent` process that manages multiple knowledge repositories.
- Expose three interfaces over one shared core: MCP Server, CLI, and REST API.
- Treat Git as the authority of record; local workspaces are compile/index/staging areas; external tools such as Obsidian, Notion, and Logseq are view/edit layers.
- Keep core systems pluggable: storage, content adapters, retrieval, embedding models, and external views must depend on interfaces rather than concrete implementations.

## Required Context for Agents

Before changing design docs, implementation plans, or code, read these files:

1. `README.md` — repository overview and initial architecture sketch.
2. `core/schema.md` — current operation contract and schema layer.
3. `docs/design.md` — current architecture notes and phase gate model.
4. `docs/agent-differences.md` — existing agent capability comparison.
5. Any active spec under `docs/superpowers/specs/` once created.

Claude Code reviewers should use these files plus the final Phase 1 spec to evaluate architectural consistency before proposing implementation changes.

## Superpowers Workflow Rules

Follow the installed Superpowers workflow when applicable:

- Use `brainstorming` before creative design or feature work.
- During brainstorming, ask one clarifying question at a time.
- Do not implement code, scaffold modules, or alter runtime behavior before a design is presented and approved.
- After design approval, write the spec to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`.
- After spec approval, transition to implementation planning with the appropriate planning workflow.
- Before claiming work is complete, verify with fresh command evidence.

## Architecture Decisions Already Agreed

These decisions are part of the active requirements baseline:

- Authority model: `Git authority → Local workspace compile/index/staging → External view/edit layer`.
- Multi-repo model: a global `registry.yaml` is authoritative; each wiki also has local config.
- Identity model: use `wiki_id:doc_id` for cross-wiki identity.
- Agent process: one global `aw-agent` manages multiple wikis.
- Interfaces: MCP Server is the primary agent interface; CLI `aw` and REST API are transport alternatives.
- CLI and REST expose low/medium-risk operations; C-level high-risk approval must go through MCP or a message-channel confirmation that calls the same approval path.
- Permissions bind `actor_type`, agent identity, wiki, page type, operation, and A/B/C risk gate.
- Agent identity is resolved by the Knowledge Agent from MCP client, CLI config, or token; callers must not override it with request parameters.
- Content adapters normalize external formats into one internal representation and preserve format-specific data in `adapter_metadata` for round-trip/debug only.
- Phase 1 default implementation: Python, `Typer`, `FastAPI`, Python MCP SDK, `pydantic`, and SQLite.
- Phase 1 default adapters/providers: `GitStorage`, `LocalWorkspace`, `ObsidianAdapter` read/write, `PlainMarkdownAdapter` read/write, lexical search baseline, optional local vector plugin.
- Notion, Logseq, S3, Git LFS/annex, alternate embedding models, and team RBAC/OIDC are interface-level designs only unless explicitly scoped later.

## Risk Gates

Gate strength follows operation risk:

- **A-level**: low-risk raw/source capture. Check schema, frontmatter, manifest, identity, and index consistency.
- **B-level**: truth-zone atom/synthesis/dispute updates. Add route tests, query profile coverage, and dispute caveats.
- **C-level**: principle promotion, dispute adjudication, cross-wiki merge, and other high-risk operations. Add content-quality checks, evidence sufficiency, duplicate/empty synthesis checks, and human confirmation.

Raw capture is available to all agents. Truth-zone compile updates require at least standard capability and B-level gates. C-level operations require MCP proposal/approval.

## Data and State Rules

- Git stores committed knowledge pages, `purpose.md`, config, `MANIFEST.jsonl`, `retrieval_index.jsonl`, logs, approval logs, operation logs, and review queue records.
- Git must not store `vectors.db` or large binary raw attachments in Phase 1.
- Raw pages in Git reference local/object-store attachments by URI, hash, and recovery location.
- Truth-zone `source_refs` must reference Git-tracked raw pages by `wiki_id:doc_id`, not arbitrary URLs or attachments.
- Local runtime state lives under each wiki's `.agent-wiki/` directory and is ignored by Git.
- Git `MANIFEST.jsonl` only represents committed authority state; pending state belongs in `.agent-wiki/pending_manifest.jsonl`.
- Raw pending content may be queryable through a local pending index; truth-zone pending content is excluded by default unless `include_pending=true`.

## Review Queue and Feedback

- `review_queue` is a general task queue, not only a dispute queue.
- Use states `open → assigned → in_progress → resolved → archived`.
- Use `item_type` for conflict, missing evidence, pending gate fix, signal candidate, feedback issue, principle proposal, dispute, and future task classes.
- `wiki.feedback` must create review queue items when feedback indicates missing evidence or rewrite targets.
- `weekly-review` consumes query outcomes, feedback, 4-signal candidates, raw backlog, and review queue state; it suggests actions but does not execute them.

## External View Rules

- Workspace is the agent staging area; external views and message channels are human interfaces.
- Obsidian reverse sync is in Phase 1 scope; other external adapters can be read-only/interface-only unless explicitly expanded.
- External edits apply to workspace first. Gate failure blocks Git commit, not workspace visibility.
- Failed gate state is represented as local pending state until fixed and committed.
- Conflict details may be stored in workspace for agents, but humans should see summaries in Obsidian inbox pages or message channels.

## Coding and Documentation Standards

- Prefer small, surgical changes that preserve existing document style.
- Keep design documents coherent enough for Claude Code or another agent to continue the work without hidden context.
- When recording decisions, include the rationale and the phase boundary: implemented in Phase 1, smoke-tested in Phase 1, or reserved for Phase 2+.
- Do not introduce implementation files, package scaffolding, or generated code during brainstorming unless the user explicitly moves the project into implementation planning.
- Do not commit changes unless explicitly requested.

