# Phase 1 Transport, Shared Access, and Obsidian Push-View Design

- Status: Approved for implementation planning
- Date: 2026-05-17
- Scope: FastMCP stdio server, shared registry permissions for Phase 1 agents, explicit Obsidian push-view with graph index export
- Baseline sources: `README.md`, `core/schema.md`, `docs/design.md`, `docs/agent-differences.md`, `docs/superpowers/specs/2026-05-16-phase-1-design.md`

## 1. Purpose

This spec defines one approved Phase 1 milestone that closes three gaps without changing the core architecture:

1. Replace the current MCP facade with a real FastMCP stdio server process.
2. Support shared registry permissions for `hermes`, `openclaw`, and `claude-code`, while reserving `codex` as a lower-trust profile.
3. Extend explicit `push-view` sync for Obsidian so the Vault gets adapter-aware exports plus a derived graph index page under `04-知识图谱/`.

The design keeps the current authority chain unchanged:

```text
Git authority -> local workspace/runtime state -> external views
```

Nothing in this milestone allows external views to become the authority of record.

## 2. Non-Negotiable Constraints

The implementation must preserve these constraints:

- Do not move business logic into transports.
- Do not couple `compile_update` to external sync.
- Do not replace the registry-based identity and permission model.
- Do not weaken the A/B/C gate model.
- Keep existing tests passing; the current regression floor is 125 passing tests.
- If architecture wording changes, update `docs/design.md` and the affected SVG diagrams in `docs/architecture/`, not only this spec.

## 3. Architecture Decisions

### 3.1 Process and entrypoints

Phase 1 adds a real stdio MCP service process using FastMCP.

- Primary entrypoint: `aw serve`
- Alias entrypoint: `aw-agent`
- MCP server name: `agent-wiki`
- Transport mode in this milestone: stdio only

`aw serve` becomes the formal local service entrypoint for agent clients. `aw-agent` is an equivalent alias for the same process identity. This milestone does not expand the networked REST scope; REST remains a separate transport surface and does not define the service identity.

### 3.2 Transport layering

The MCP layer remains thin.

- FastMCP host: owns stdio startup, tool registration, session metadata access, and tool error mapping.
- Reusable dispatcher: owns wiki resolution, trusted identity resolution, service delegation, and result serialization.
- Application services: remain the only place where query, capture, compile, lint, and sync behavior live.

This milestone explicitly rejects a transport-first rewrite where FastMCP registration becomes the business layer.

### 3.3 Tool surface

The MCP surface for this milestone is fixed at five tools:

- `wiki.query`
- `wiki.capture_raw`
- `wiki.compile_update`
- `wiki.lint`
- `wiki.sync`

Rules:

- Every tool requires `wiki_id`.
- No tool accepts trusted actor identity from request parameters.
- All tools return structured results suitable for agent consumption.
- Permission failures and unknown wiki failures must be distinguishable from internal server errors.

### 3.4 Compile and sync separation

`compile_update` remains an internal authority-state mutation only.

- It writes workspace and authority-tracked artifacts.
- It does not write to Obsidian.
- It does not trigger `push-view` automatically.

`push-view` remains an explicit sync operation.

- CLI may trigger it through `aw sync`.
- MCP may trigger it through `wiki.sync`.
- Future convenience flows may compose `compile_update` and `sync`, but only as orchestration above the core service contract.

This separation is a hard architecture boundary for Phase 1.

## 4. Shared Registry Permission Model

### 4.1 Permission source of truth

`registry.yaml` remains the only Phase 1 authority for multi-agent access policy.

Each permission rule stays bound to:

- `actor_type`
- `actor_id`
- `allowed_operations`
- `allowed_page_types`
- `max_gate`

Transports may resolve identity differently, but they must all delegate authorization to the same central permission path.

### 4.2 Trusted identity resolution

Identity continues to be resolved by the knowledge agent, not by caller-supplied payload.

- MCP: resolve from trusted FastMCP session/client metadata.
- CLI: resolve from local config and environment.
- REST: continue using trusted token-derived identity when that transport is used.

Request bodies or tool params must not override the resolved actor identity.

### 4.3 Phase 1 shared agent profiles

The approved Phase 1 shared-agent baseline is:

- `hermes`: T1, `max_gate=C`
- `openclaw`: T1, `max_gate=C`
- `claude-code`: T2, `max_gate=B`
- `codex`: T3, `max_gate=A` reserved profile

Expected operation envelope:

- `hermes`: `query`, `capture_raw`, `compile_update`, `lint`, `sync`
- `openclaw`: `query`, `capture_raw`, `compile_update`, `lint`, `sync`
- `claude-code`: `query`, `capture_raw`, `compile_update`, `lint`, `sync`
- `codex`: `query`, `capture_raw`

Expected page-type envelope:

- T1 and T2: `raw`, `atom`, `synthesis`
- T3 reserve profile: `raw`

Difference between T1 and T2 stays in `max_gate`, not in a separate transport policy engine.

## 5. MCP Tool Contracts

### 5.1 `wiki.query`

Input:

- `wiki_id`
- `query`
- optional `include_pending`
- optional `max_sensitivity`

Behavior:

- delegates to `QueryService`
- returns layered query output

Output contract:

- `query_type`
- `l1_answer`
- `l2_context`
- `l3_proof`
- `hits`
- `hit_count`
- `miss_signal`

### 5.2 `wiki.capture_raw`

Input:

- `wiki_id`
- `doc_id`
- `topic`
- `problem_cluster`
- `content`
- optional `source_refs`

Behavior:

- delegates to `CaptureRawService`

Output contract:

- `status`
- `doc_id`
- `page_path`

### 5.3 `wiki.compile_update`

Input:

- `wiki_id`
- `doc_id`
- `page_type`
- `topic`
- `problem_cluster`
- `content`
- optional `source_refs`

Behavior:

- delegates to `CompileUpdateService.apply`
- does not call sync
- does not write Obsidian Vault files

Output contract:

- `status`
- `doc_id`
- `page_path`

### 5.4 `wiki.lint`

Input:

- `wiki_id`

Behavior:

- delegates to `LintService`

Output contract should expose structured issues, not only terminal text.

Minimum result shape:

- `ok`
- `issues`
- `issue_count`

### 5.5 `wiki.sync`

Input:

- `wiki_id`
- `mode`
- optional `doc_ids`

Supported modes in this milestone:

- `status`
- `pull-view`
- `push-view`

Behavior:

- delegates to `SyncService`
- follows the same central permission and identity path as the other tools

Output contract:

- `mode`
- `changed_files`

## 6. Obsidian Push-View Design

### 6.1 Scope

This milestone upgrades `push-view` for Obsidian views from pure file copy to adapter-aware export plus a derived graph index artifact.

The change applies only to explicit sync. It does not change compile semantics.

### 6.2 Explicit sync trigger

`push-view` remains explicit.

- `compile_update` ends after internal authority/workspace propagation.
- Obsidian export only happens through `sync push-view`.
- MCP may expose that operation through `wiki.sync`, but the architecture remains decoupled.

### 6.3 Incremental export

`push-view` gains optional `doc_ids` filtering.

- If `doc_ids` is present, only those pages are exported.
- If `doc_ids` is omitted, full export remains allowed.

This explicit filter is preferred over implicit “last changed page” inference because it is deterministic, testable, and transport-neutral.

### 6.4 Derived graph index page

For `obsidian` views, `push-view` additionally maintains:

- directory: `04-知识图谱/`
- file: `04-知识图谱/知识图谱索引.md`

This file is a derived external-view artifact.

- It is not a new page type.
- It is not part of Git authority by definition.
- It may be regenerated on every push.

### 6.5 Index page content contract

The first Phase 1 version is intentionally simple.

- human-readable markdown page
- generated timestamp or sync marker
- grouped sections for `atom`, `synthesis`, and `raw`
- each item rendered as an Obsidian wikilink
- each item annotated with basic metadata such as `topic` and `problem_cluster`

The page is intended as a graph/navigation entrypoint, not a knowledge artifact with independent truth value.

### 6.6 Rebuild strategy

The design distinguishes between page export and index generation.

- exported business pages: incremental when `doc_ids` is provided
- graph index page: full regenerate on each `push-view`

Rebuilding one derived index file is simpler and more reliable than incremental markdown patching.

## 7. Required Documentation Sync

Because this milestone changes approved architecture wording, these docs must be updated alongside implementation planning and implementation:

- `docs/design.md`
- affected diagrams under `docs/architecture/`

At minimum the architecture docs must reflect:

- `aw serve` as the primary service entrypoint
- `aw-agent` as an alias
- FastMCP stdio MCP server as the real Phase 1 agent process target
- five-tool MCP surface
- explicit `sync` boundary between internal compile and Obsidian export
- Obsidian graph index generation under `04-知识图谱/`

## 8. TDD Execution Model

Implementation planning must split the work into three workflows.

### Workflow 1: FastMCP stdio server and entrypoints

Red tests first:

- MCP lists five tools
- `wiki.lint` and `wiki.sync` delegate correctly
- `aw serve` and `aw-agent` map to the same MCP server process identity
- a stdio FastMCP server smoke path starts and registers the expected tool surface

Then implement:

- FastMCP host
- reusable MCP dispatcher
- stdio startup wiring
- `aw-agent` alias

### Workflow 2: Shared registry permissions

Red tests first:

- `hermes`, `openclaw`, and `claude-code` share the same wiki within their approved envelopes
- `codex` reserve profile is restricted to `query` and `capture_raw`
- lower-trust actors cannot escalate by caller-supplied payload
- `wiki.sync` is protected by the same central permission model

Then implement:

- registry fixture updates
- transport-to-permission wiring consistency
- any missing negative-path enforcement

### Workflow 3: Obsidian push-view and graph index

Red tests first:

- `compile_update` does not write to the Vault
- explicit `sync push-view` does write to the Vault
- `doc_ids` filtering produces incremental page export
- `04-知识图谱/知识图谱索引.md` is generated for Obsidian views
- repeated incremental sync does not produce duplicate or stale index structure

Then implement:

- `SyncInput.doc_ids`
- Obsidian push export helper
- graph index builder

## 9. Verification Gates

No implementation completion claim is valid without fresh command evidence.

Minimum verification for the eventual implementation phase:

- targeted tests for each workflow
- full `pytest` run
- regression proof that the pre-existing suite still passes
- CLI and MCP smoke verification for the new service entrypoint and tool surface

The regression floor for this milestone is:

- all previously passing tests remain green
- the project baseline of 125 existing tests continues to pass or is exceeded by a larger green suite

## 10. Explicit Non-Goals

This milestone does not include:

- automatic `compile_update` -> `push-view` coupling in the core architecture
- new RBAC or OIDC models
- new authority page types for graph artifacts
- broader REST expansion
- large refactors of the application service layer unrelated to the three approved workflows

## 11. Approval State

This design was validated interactively for the following decisions:

- one unified spec, with three implementation workflows
- FastMCP stdio service process
- `aw serve` primary entrypoint plus `aw-agent` alias
- five-tool MCP surface including `wiki.sync`
- shared registry permissions for T1/T2 agents, with `codex` reserve profile
- explicit `sync` boundary kept separate from `compile_update`
- Obsidian `push-view` incremental export with a derived graph index page

This spec is ready for implementation planning after user review.
