# Codex Phase 1 Implementation Code Review

> Scope: entire Phase 1 implementation under `src/agent_wiki/`, tests, packaging, and deployment entry points.  
> Review basis: current code plus alignment against `docs/design.md` and `core/schema.md`.  
> Test evidence: `python3 -m pytest` passed locally with `103 passed in 2.44s`.

---

## Executive Summary

The Phase 1 implementation is a useful file-backed baseline with broad test coverage for happy-path services. It now covers many conceptual pieces: raw capture, compile updates, lexical query, sensitivity filtering, sync adapters, maintenance, review queue transitions, MCP/REST stubs, and CLI commands.

However, it is not yet safe or realistic as the documented `aw-agent` architecture. The largest gaps are security and authority enforcement: MCP and REST can bypass the intended identity model, CLI/REST still hard-code test fixtures and actors, compile/proposal paths lack doc/path validation, writes do not go through Git authority promotion, and C-level approval bypasses source provenance checks. These are not cosmetic; they undermine the core design promises in `docs/design.md` and `core/schema.md`.

## Overall Assessment

| Area | Rating | Summary |
|---|---:|---|
| Architecture consistency | 3/5 | Service boundaries mostly match the docs, but transport and authority paths violate the protocol-centered, identity-resolved, Git-authority design. |
| Code quality | 3/5 | Code is small and readable, but lacks transactional writes, central validation, robust error handling, and has stale/legacy `engine/` code. |
| Domain model integrity | 3/5 | Domain models exist, but enums are not consistently used and many cross-layer contracts are still untyped dicts/string literals. |
| Test coverage | 3/5 | 103 tests pass and cover many happy paths, but major security, failure, deployment, and malformed-input paths are untested. |
| Security | 2/5 | Permissions and gates improved, but transport identity bypass, REST no-auth, path traversal, and provenance bypass remain serious. |
| Deployment readiness | 2/5 | `aw query` and `aw maintain` run in fixture-driven local mode; `aw serve` is only an echo scaffold and REST/MCP are not deployable services. |

---

## P0 — Must Fix Before Any Real Multi-Agent Use

### P0-1: MCP tool invocation accepts caller-supplied `wiki` and `actor`, bypassing resolved identity

`MCPServer.resolve_identity()` exists and claims session metadata wins (`src/agent_wiki/transports/mcp/server.py:35`), but the actual tools do not call it. They directly trust `params["actor"]` and `params["wiki"]` (`src/agent_wiki/transports/mcp/server.py:44`, `src/agent_wiki/transports/mcp/server.py:64`, `src/agent_wiki/transports/mcp/server.py:78`).

This violates the target design that identity is resolved by the Knowledge Agent, not caller-controlled request parameters. It also lets a caller pass a forged `ResolvedActor` with a higher privilege actor ID or a forged wiki config.

Recommended fix:
- Change MCP `invoke()` to accept trusted session metadata separately from tool params.
- Resolve actor inside `invoke()` or per tool, never from `params["actor"]`.
- Resolve `wiki_id` through `registry.yaml`; do not accept raw `WikiConfig` objects from the caller.
- Add a negative test where request params spoof `actor_id=claude-code` but session identity is T3/low-gate, and verify compile is denied.

### P0-2: REST API has no authentication/token handling and hard-codes privileged actor identity

`create_app()` exposes `/query` and `/capture-raw` without any token or auth dependency (`src/agent_wiki/transports/rest/app.py:39`, `src/agent_wiki/transports/rest/app.py:43`, `src/agent_wiki/transports/rest/app.py:64`). Both endpoints hard-code `ResolvedActor(actor_type="agent", actor_id="claude-code", transport="rest")` (`src/agent_wiki/transports/rest/app.py:46`, `src/agent_wiki/transports/rest/app.py:67`).

This conflicts with the security model described in the docs: REST should use a local token and resolved identity, not a fixed privileged actor. It also means any process that can reach the REST app can write raw pages as `claude-code`.

Recommended fix:
- Add a local token dependency before any mutating endpoint.
- Resolve actor from token-bound identity/profile, not a hard-coded `claude-code` value.
- Return 401/403 for missing token, unknown token, insufficient permission, and gate failures.
- Add tests for unauthenticated REST capture denial and token identity separation.

### P0-3: CLI and REST load `tests/fixtures/registry.yaml` in runtime paths

The CLI `_load_wiki()` always loads `tests/fixtures/registry.yaml` (`src/agent_wiki/transports/cli/app.py:19`). REST `_resolve_wiki()` does the same (`src/agent_wiki/transports/rest/app.py:32`). This is a deployment blocker: installed packages or containers should not depend on the test tree, and real users cannot select a registry or wiki ID.

It also creates a security flaw because the fixture grants `claude-code` permissions (`tests/fixtures/registry.yaml:22`) and transports hard-code that same actor.

Recommended fix:
- Add `--registry` and `--wiki-id` to CLI commands.
- Add `AGENT_WIKI_REGISTRY` / config path support for REST and service startup.
- Never load `tests/fixtures/*` from production code.
- Add packaging tests that run the CLI against a temp registry outside `tests/fixtures`.

### P0-4: `aw serve` does not start `aw-agent`; it only prints a scaffold message

The CLI `serve` command only echoes `agent-wiki serve scaffolded on ...` (`src/agent_wiki/transports/cli/app.py:42`). `pyproject.toml` maps both `aw` and `aw-agent` to the same CLI main (`pyproject.toml:29`). The Dockerfile runs `aw --help`, not a service (`Dockerfile:10`).

This means deployment docs and command names imply a long-running agent process, but no service is actually started.

Recommended fix:
- Implement `aw serve` using the REST app and/or MCP server with loopback binding by default.
- Add health endpoint integration in `serve` mode.
- Make `aw-agent` entrypoint call the service command by default or document it as an alias only.
- Add an end-to-end test that starts the service and queries `/health`.

### P0-5: `compile_update` allows path traversal via `doc_id`

Raw capture validates `doc_id` with `_DOC_ID_PATTERN` (`src/agent_wiki/application/capture_raw.py:11`, `src/agent_wiki/application/capture_raw.py:24`). `CompileUpdateService.apply()` does not validate `data.doc_id` before propagation (`src/agent_wiki/application/compile_update.py:24`). Propagation writes directly to `pages/{doc_id}.md` (`src/agent_wiki/application/propagation.py:59`). A malicious `doc_id` such as `../../outside` can escape `pages/` and potentially the wiki root depending on the path.

Recommended fix:
- Centralize doc ID validation in a domain validator and use it for all write paths: raw, compile, proposal, approval, sync import, queue references.
- Resolve and verify output paths stay under `wiki.workspace_path/pages`.
- Add path traversal tests for `compile_update`, `approval.propose`, and sync import.

### P0-6: Proposal IDs are path-joined unsafely

`ApprovalService.propose()` writes `.agent-wiki/proposals/{proposal_id}.json` directly from user input (`src/agent_wiki/application/approvals.py:11`, `src/agent_wiki/application/approvals.py:14`). `approve()` reads the same unchecked path (`src/agent_wiki/application/approvals.py:33`).

This is the same traversal class as `doc_id`, but on the high-risk C-level path.

Recommended fix:
- Validate `proposal_id` with the same safe identifier policy.
- Resolve and enforce that proposal paths stay under `.agent-wiki/proposals`.
- Add tests for `../` proposal ID rejection.

### P0-7: C-level approval bypasses source provenance validation

`ApprovalService.approve()` constructs `CompileUpdateInput(... allow_shared_write_without_sources=True)` unconditionally (`src/agent_wiki/application/approvals.py:37`, `src/agent_wiki/application/approvals.py:47`). `CompileUpdateService.apply()` skips source ref validation when that flag is true (`src/agent_wiki/application/compile_update.py:34`).

This violates the schema principle that truth-zone pages must trace back to raw pages. It is especially risky because approvals are the C-level path for principle/shared writes.

Recommended fix:
- Remove the unconditional bypass.
- If a smoke-test bypass remains, gate it behind explicit test-only configuration, not production input.
- Add tests that approval fails with missing or non-raw `source_refs`.

### P0-8: There is no Git authority promotion or commit orchestration in write paths

`PropagationService` writes page, manifest, retrieval index, log, and queue files directly (`src/agent_wiki/application/propagation.py:22`, `src/agent_wiki/application/propagation.py:59`). There is no `git pull --rebase`, staging, commit, rollback, or conflict handling. This conflicts with the Git authority and gate-to-commit model in the design.

Impact: the implementation can create workspace artifacts, but it does not actually enforce “Git authority” as an operation boundary.

Recommended fix:
- Introduce an `AuthorityPromotionService` or `CommitOrchestrator` that owns gate result, staging, commit, rebase conflict handling, stale markers, and review queue creation.
- Keep file writes in propagation, but only report `committed` after Git authority promotion succeeds.
- Add tests for commit success, commit failure, rebase conflict, and partial propagation failure.

---

## P1 — Important Before Expanding Feature Surface

### P1-1: Application services instantiate infrastructure directly instead of using container-injected dependencies

`CaptureRawService` creates `PermissionService` and `PropagationService` directly (`src/agent_wiki/application/capture_raw.py:19`, `src/agent_wiki/application/capture_raw.py:24`). `CompileUpdateService` creates `ManifestRepository`, `PermissionService`, and `PropagationService` directly (`src/agent_wiki/application/compile_update.py:24`, `src/agent_wiki/application/compile_update.py:29`, `src/agent_wiki/application/compile_update.py:40`). `QueryService` creates repositories/readers directly (`src/agent_wiki/application/query.py:15`).

This is a layer/architecture smell: the code has a `Container`, but most application services bypass it. This makes policy substitution, test doubles, alternate storage providers, and future provider plugins harder.

Recommended fix:
- Use constructor injection for repositories/providers/policy services.
- Have `Container` own wiring for production defaults.
- Keep simple no-arg constructors only as convenience wrappers if needed.

### P1-2: Domain enums exist but models and services mostly use raw strings

`ActorType`, `GateLevel`, `PageType`, and `Sensitivity` are defined (`src/agent_wiki/domain/enums.py:4`). But domain models use `str` for `page_type`, `sensitivity`, `query_type`, status fields, and gate strings (`src/agent_wiki/domain/models.py:29`, `src/agent_wiki/domain/models.py:43`, `src/agent_wiki/domain/models.py:55`). Registry configs also use strings for actor type, max gate, wiki type, external view mode, and providers (`src/agent_wiki/bootstrap/registry_loader.py:7`, `src/agent_wiki/bootstrap/registry_loader.py:15`, `src/agent_wiki/bootstrap/registry_loader.py:21`, `src/agent_wiki/bootstrap/registry_loader.py:27`).

Impact: invalid values are accepted until some service happens to compare string literals. This weakens domain integrity and makes cross-layer behavior inconsistent.

Recommended fix:
- Use enums in Pydantic models and registry configs.
- Add validators for query type, review status, item type, sync mode, external view mode, and retrieval provider.
- Replace string literals in services with enums.

### P1-3: MCP implementation is not a real MCP SDK server

`src/agent_wiki/transports/mcp/server.py` defines a local `MCPServer` class with `list_tools()` and `invoke()` (`src/agent_wiki/transports/mcp/server.py:14`). It does not use the `mcp` dependency from `pyproject.toml` (`pyproject.toml:21`) and has no process entrypoint.

Impact: this is a useful unit-test facade, but agents cannot discover or call it as a real MCP server.

Recommended fix:
- Implement actual MCP server registration using the SDK.
- Add an executable entrypoint or `aw serve --mcp` mode.
- Add an integration smoke test at the protocol boundary, not just direct method calls.

### P1-4: REST response omits L2/L3 evidence and wiki IDs

REST `/query` returns `query_type`, `l1_answer`, hit count, miss signal, and hits containing only `doc_id` and score (`src/agent_wiki/transports/rest/app.py:56`). It omits `l2_context`, `l3_proof`, and `wiki_id`, which are core parts of the query contract.

Impact: REST is not transport-parity with the query result model, and cross-wiki traceability is lost.

Recommended fix:
- Return the same L1/L2/L3 structure as MCP.
- Include `wiki_id` for every hit.
- Add REST tests asserting proof/context presence.

### P1-5: Review queue rich schema is inconsistently populated

The repository supports transitions on `item_id` (`src/agent_wiki/infrastructure/runtime/review_queue.py:25`), but many producers do not set `item_id`, `wiki_id`, `content_state`, `priority`, `created_at`, or assignment fields. Examples: propagation missing-evidence item (`src/agent_wiki/application/propagation.py:88`), feedback issue (`src/agent_wiki/application/feedback.py:31`), compile suggestions (`src/agent_wiki/application/compile_suggest.py:45`), and relation signals (`src/agent_wiki/application/relations.py:84`).

Impact: queue transition and weekly governance cannot work reliably across item types.

Recommended fix:
- Centralize queue item creation in `ReviewQueueRepository.append()` or a factory that fills required fields.
- Generate stable `item_id`, include `wiki_id`, timestamps, default priority, and valid status/content state.
- Add tests that every queue producer writes the full target schema.

### P1-6: Manifest and retrieval index updates append duplicates and are not transactional

Raw capture appends a manifest entry and a raw retrieval card (`src/agent_wiki/application/propagation.py:27`, `src/agent_wiki/application/propagation.py:38`). Compile updates upsert the manifest but always append a compiled retrieval card (`src/agent_wiki/application/propagation.py:64`, `src/agent_wiki/application/propagation.py:79`). Repeated updates will leave stale duplicate index cards.

Impact: retrieval can surface stale content even when the manifest points to the latest page. Partial failures can leave page/manifest/index out of sync.

Recommended fix:
- Upsert retrieval cards by `wiki_id:doc_id` and unit ID.
- Make propagation staged: write temp files, update all artifacts, then atomically replace.
- Add tests for repeated compile updates and partial write failures.

### P1-7: Sensitivity filtering is opt-in and defaults can leak confidential pages

`QueryInput.max_sensitivity` defaults to `None` (`src/agent_wiki/domain/models.py:55`). `QueryService.execute()` only filters sensitivity when that value is provided (`src/agent_wiki/application/query.py:23`). If callers forget to set it, confidential pages are included.

Impact: sensitivity is not actor-driven or permission-driven. It depends on callers voluntarily providing a limit.

Recommended fix:
- Derive max sensitivity from actor permissions or wiki policy.
- Default to the least privilege level for unknown actors.
- Add tests that confidential pages are excluded without an explicit high-trust actor.

### P1-8: Sync ignores `external_view.mode` and always pulls/pushes all configured views

`SyncService._pull_view()` loops over all `wiki.external_views` and imports markdown (`src/agent_wiki/application/sync.py:41`). `_push_view()` similarly exports to all views (`src/agent_wiki/application/sync.py:63`). Neither checks whether `view.mode` is `read_only` or `read_write`.

Impact: a read-only external view can be mutated by `push-view`, and a write-only/future restricted view would not be respected.

Recommended fix:
- Enforce mode semantics: `pull-view` only for readable views, `push-view` only for writable views.
- Add tests for read-only view not being written.

### P1-9: Approval path is not restricted to MCP/human confirmation

`ApprovalService.approve()` accepts any `ResolvedActor` and does not check transport or operation permissions (`src/agent_wiki/application/approvals.py:33`). The test uses `transport="mcp"` but enforcement is not in the service (`tests/test_approvals.py:15`).

Impact: a CLI or REST caller could call the service directly if exposed later, bypassing the C-level confirmation boundary.

Recommended fix:
- Check `operation="approve_proposal"` through `PermissionService`.
- Require trusted confirmation context, not just an actor object.
- Add tests that CLI/REST actors cannot approve C-level proposals.

### P1-10: Lint coverage is much smaller than the schema contract

`LintService` checks canonical URI existence, page existence, retrieval index references, and stale markers (`src/agent_wiki/application/linting.py:22`). It does not enforce most target checks in `core/schema.md`: frontmatter completeness, `doc_id` uniqueness beyond manifest writes, `source_refs` validity globally, query types, load policy, disputed reason, dependency chains, and compiled/superseded chains.

Impact: docs describe lint/gate as the anti-island safety net, but current lint will miss many schema violations.

Recommended fix:
- Add lint checks matching `core/schema.md` target items incrementally.
- Add fixture-based negative tests for each schema violation class.

---

## P2 — Quality, Maintainability, and Coverage Improvements

### P2-1: Top-level `engine/` appears to be legacy dead code

The tracked repo still contains `engine/*.py` files, but README points current runtime to `src/agent_wiki/` (`README.md:92`). `git ls-files` shows `engine/compile.py`, `engine/ingest.py`, `engine/lint.py`, `engine/manifest.py`, `engine/promote.py`, `engine/propagation.py`, `engine/retrieve.py`, `engine/sync.py`, and `engine/vectorstore.py` are tracked.

Recommendation:
- Remove `engine/` if obsolete, or add a README/deprecation note.
- Prevent future work from landing in the wrong implementation tree.

### P2-2: Bytecode and cache artifacts exist in the working tree

The source inventory showed `src/agent_wiki/**/__pycache__/*.pyc` files in the filesystem. `git ls-files` did not list them as tracked, but they are present locally.

Recommendation:
- Ensure `.gitignore` covers `__pycache__/`, `.pytest_cache/`, and `*.pyc`.
- Clean local caches before packaging/release.

### P2-3: Many JSONL readers assume valid JSON and required keys

Examples include retrieval index parsing (`src/agent_wiki/infrastructure/retrieval/retrieval_index.py:43`), linting (`src/agent_wiki/application/linting.py:33`), weekly review (`src/agent_wiki/application/weekly_review.py:23`), feedback analysis (`src/agent_wiki/application/fast_feedback.py:19`), and relation detection (`src/agent_wiki/application/relations.py:23`). A single malformed line can crash maintenance or query.

Recommendation:
- Add safe JSONL parsing helper with line-numbered error reporting.
- Make lint surface malformed JSONL rather than crashing.
- Add tests with malformed JSONL lines.

### P2-4: Query result model uses untyped `hits: list`

`QueryResult.hits` is typed as raw `list` (`src/agent_wiki/domain/models.py:61`) even though the rest of the system expects `RetrievalHit` objects.

Recommendation:
- Type it as `list[RetrievalHit]` or a response DTO.
- Use `from __future__ import annotations` or move models/contracts to avoid circular imports.

### P2-5: `QualityReportService._orphan_count()` counts compiled pages as orphaned too

The orphan calculation adds all `source_refs` doc IDs to a referenced set, then counts every manifest entry not in that set (`src/agent_wiki/application/quality_report.py:58`). This will count compiled pages as orphans unless another page cites them, which may not match the intended “raw orphan” or “uncompiled raw” metric.

Recommendation:
- Define whether orphan means raw not compiled, page not referenced, or dependency without backlinks.
- Rename metric or scope it to raw pages.

### P2-6: Query writes outcomes on every execution without policy controls

`QueryService.execute()` always appends to `query_outcomes.jsonl` (`src/agent_wiki/application/query.py:31`). The design previously called for query-type-configured logging policy. Current code also logs `actor_id` but not `actor_type`, `transport`, `query_type`, `wiki_id`, or sensitivity level (`src/agent_wiki/application/query.py:159`).

Recommendation:
- Add query outcome logging policy.
- Include actor type, transport, query type, wiki ID, hit docs, and sensitivity limit.
- Add privacy controls for query logging.

### P2-7: Cross-wiki query does fan-out, not purpose/topic routing

`CrossWikiQueryService.execute()` loops through every wiki and merges hits (`src/agent_wiki/application/query.py:185`). This works for smoke tests but does not implement purpose/topic routing from the design.

Recommendation:
- Add route selection using `purpose.md`, registry `route_priority`, and topic matching.
- Keep fan-out as fallback or debug mode.

### P2-8: Adapter normalization is very shallow

`ObsidianAdapter` preserves frontmatter and content, but does not normalize wikilinks, backlinks, or cross refs (`src/agent_wiki/infrastructure/adapters/obsidian.py:17`). `PlainMarkdownAdapter` is a thin file reader/writer (`src/agent_wiki/infrastructure/adapters/plain_markdown.py:4`).

Recommendation:
- Add normalized fields for `cross_refs`, `source_refs`, and adapter metadata.
- Add tests for Obsidian `[[wikilinks]]` and Markdown links.

### P2-9: Tests are numerous but mostly service-level happy paths

The suite is strong for basic service behavior and currently passes. Missing important paths include:

- path traversal rejection for compile/proposal/sync
- REST auth/token denial
- MCP actor spoofing through tool params
- read-only external view sync enforcement
- repeated compile updates replacing retrieval cards
- Git commit/rebase conflict behavior
- malformed JSONL handling
- real `aw serve` process startup
- real registry selection outside `tests/fixtures`
- source provenance rejection in approval path

Recommendation:
- Add security regression tests first, then deployment and failure-mode tests.

---

## Deployment Readiness Check

| Command / surface | Current state | Evidence | Assessment |
|---|---|---|---|
| `aw serve` | Prints scaffold message only | `src/agent_wiki/transports/cli/app.py:42` | Not end-to-end |
| `aw query` | Runs against hard-coded fixture registry plus optional workspace override | `src/agent_wiki/transports/cli/app.py:48`, `src/agent_wiki/transports/cli/app.py:19` | Demo-only |
| `aw capture-raw` | Runs, but actor and registry are hard-coded | `src/agent_wiki/transports/cli/app.py:61`, `src/agent_wiki/transports/cli/app.py:27` | Demo-only |
| `aw compile-update` | Runs, but no doc ID validation and hard-coded actor/registry | `src/agent_wiki/transports/cli/app.py:80` | Unsafe for real use |
| `aw lint` | Runs basic checks only | `src/agent_wiki/transports/cli/app.py:102`, `src/agent_wiki/application/linting.py:22` | Partial |
| `aw maintain` | Runs local detectors and quality report | `src/agent_wiki/transports/cli/app.py:114` | Useful local smoke path |
| REST | FastAPI app exists but no auth, hard-coded registry/actor | `src/agent_wiki/transports/rest/app.py:28` | Not production-ready |
| MCP | Local facade exists but not SDK server; trusts params actor/wiki | `src/agent_wiki/transports/mcp/server.py:14`, `src/agent_wiki/transports/mcp/server.py:44` | Not production-ready |

---

## Recommended Next Work Order

1. Fix transport identity and registry resolution: no hard-coded actors, no fixture registry in runtime, no caller-supplied actor/wiki in MCP.
2. Centralize identifier/path validation for `doc_id`, `proposal_id`, and sync imports.
3. Remove C-level source provenance bypass or make it test-only.
4. Implement real `aw serve` and token-bound REST identity.
5. Add authority/commit orchestration or change result labels from `committed` to `workspace_written` until Git commit exists.
6. Fill rich review queue item schema through a central factory.
7. Replace raw string fields with enums and Pydantic validators.
8. Add failure/security tests listed in P2-9.

---

## Final Judgment

Phase 1 is a solid prototype baseline and the passing 103-test suite is useful. It is not yet a secure or deployable multi-agent knowledge service. The biggest mismatch with the docs is that the code currently implements local service primitives, while the architecture requires a trusted `aw-agent` authority boundary. The immediate engineering bar should be to make that boundary real: resolved identity, registry-based wiki lookup, gate/permission enforcement at every transport, safe path validation, and Git authority promotion.

