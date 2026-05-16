# Context

The approved Phase 1 design is ahead of the current runtime baseline in `src/agent_wiki/`. The code already has a working file-backed core with 32 passing tests across bootstrap, raw capture, compile/update, lexical query, lint, sync, feedback, weekly review, approvals, and multi-wiki/shared-wiki/cross-wiki smoke paths. The design now requires turning that baseline into a usable, self-evolving, governance-aware local knowledge system without changing the locked architecture decisions.

Locked decisions that this plan preserves:
- Git remains the authority of record.
- One shared `aw-agent` core serves all transports.
- `registry.yaml` remains authoritative for multi-wiki config.
- Cross-wiki identity remains `wiki_id:doc_id`.
- MCP is the primary agent interface; CLI and REST are alternatives.
- Adapters and transports stay thin; retrieval/ingest/gating stay in the shared core.
- Truth-zone `source_refs` must point to Git-tracked raw pages.
- External edits flow to workspace first; gate failure blocks Git commit, not visibility.
- `review_queue` is a general task queue, not only a dispute queue.

Verified current gaps:
- `src/agent_wiki/application/query.py` does heuristic classification + lexical substring search + simple score sorting + pending opt-in + L1/L2/L3, but no Chinese tokenization, fuzzy matching, weighted ranking, provider routing, budgets, or query-side outcome logging.
- `src/agent_wiki/application/sync.py` only supports `status` / `pull-view` / `push-view` as markdown file copying; there are no concrete content adapters.
- `src/agent_wiki/infrastructure/identity/resolver.py` still prefers caller-supplied actor fields over metadata.
- `src/agent_wiki/infrastructure/identity/permissions.py` ignores `max_gate`.
- `src/agent_wiki/infrastructure/runtime/review_queue.py` is append-only and current queue shape is minimal.
- `src/agent_wiki/transports/cli/app.py` is still a stub with `info` only; no `aw serve`, no MCP/REST.
- `src/agent_wiki/application/propagation.py` writes directly to files with no authority-promotion / rollback / stale-marker lifecycle.

This plan keeps the design priority order intact:
- **P0** usable retrieval + Obsidian-connected workflow
- **P1** lifecycle automation + purpose-driven evolution
- **P2** governance hardening
- **P3** authority / service / DFX maturity

Each task below is intentionally tiny: one failing test, minimal implementation, full test pass, one commit.

---

# Recommended approach

Implement Phase 1 as four milestones aligned to P0→P3. Each milestone is decomposed into TDD tasks small enough to be independently committable. Build on existing service-level filesystem tests rather than inventing a new testing style.

## Existing code and tests to reuse

### Runtime files to extend
- `src/agent_wiki/application/query.py`
- `src/agent_wiki/application/sync.py`
- `src/agent_wiki/application/feedback.py`
- `src/agent_wiki/application/weekly_review.py`
- `src/agent_wiki/application/compile_update.py`
- `src/agent_wiki/application/capture_raw.py`
- `src/agent_wiki/application/propagation.py`
- `src/agent_wiki/infrastructure/retrieval/retrieval_index.py`
- `src/agent_wiki/infrastructure/storage/manifest_repo.py`
- `src/agent_wiki/infrastructure/runtime/review_queue.py`
- `src/agent_wiki/infrastructure/runtime/pending_state.py`
- `src/agent_wiki/infrastructure/identity/resolver.py`
- `src/agent_wiki/infrastructure/identity/permissions.py`
- `src/agent_wiki/infrastructure/identity/gates.py`
- `src/agent_wiki/bootstrap/container.py`
- `src/agent_wiki/domain/contracts.py`
- `src/agent_wiki/domain/models.py`
- `src/agent_wiki/domain/enums.py`
- `src/agent_wiki/transports/cli/app.py`

### Existing tests to extend
- `tests/test_retrieve.py`
- `tests/test_query_classification.py`
- `tests/test_query_output.py`
- `tests/test_query_pending.py`
- `tests/test_sync.py`
- `tests/test_feedback.py`
- `tests/test_weekly_review.py`
- `tests/test_identity_resolution.py`
- `tests/test_permissions.py`
- `tests/test_compile_apply.py`
- `tests/test_ingest.py`
- `tests/test_approvals.py`
- `tests/test_cross_wiki_query.py`
- `tests/test_shared_wiki.py`
- `tests/test_bootstrap.py`
- `tests/test_cli_smoke.py`

### New modules that should stay thin and local to one concern
- `src/agent_wiki/infrastructure/retrieval/tokenizer.py`
- `src/agent_wiki/infrastructure/retrieval/fuzzy.py`
- `src/agent_wiki/infrastructure/adapters/plain_markdown.py`
- `src/agent_wiki/infrastructure/adapters/obsidian.py`
- `src/agent_wiki/application/compile_suggest.py`
- `src/agent_wiki/application/fast_feedback.py`
- `src/agent_wiki/application/relations.py`
- `src/agent_wiki/infrastructure/storage/purpose_reader.py`
- `src/agent_wiki/application/authority.py`
- `src/agent_wiki/transports/mcp/server.py`
- `src/agent_wiki/transports/rest/app.py`

---

# Milestone P0 — Must be usable

## Goal
Improve query quality enough that the wiki stays in the loop, and replace raw copy-based sync with a real Obsidian-connected adapter flow.

## Current gap
- No Chinese-aware tokenization
- No fuzzy matching
- No weighted ranking
- No query-side hit/miss logging
- No real `ContentAdapter` implementations
- No reverse sync flow visible to the lifecycle loop

## Ordered tasks

### P0-01 Add CJK-aware tokenizer
- **Failing test focus:** Chinese + Latin mixed text tokenizes into useful search terms.
- **Likely files:** `tests/test_retrieve.py`, `src/agent_wiki/infrastructure/retrieval/tokenizer.py`
- **Depends on:** none
- **Parallelizable:** yes
- **Commit scope:** tokenizer utility only

### P0-02 Use tokenizer in lexical search
- **Failing test focus:** Chinese content becomes retrievable through `lexical_search`.
- **Likely files:** `tests/test_retrieve.py`, `src/agent_wiki/infrastructure/retrieval/retrieval_index.py`
- **Depends on:** P0-01
- **Parallelizable:** no
- **Commit scope:** retrieval tokenization integration

### P0-03 Add fuzzy matching helper
- **Failing test focus:** near-miss terms score as related.
- **Likely files:** `tests/test_retrieve.py`, `src/agent_wiki/infrastructure/retrieval/fuzzy.py`
- **Depends on:** none
- **Parallelizable:** yes
- **Commit scope:** fuzzy utility only

### P0-04 Add fuzzy matching to lexical search
- **Failing test focus:** typo/near-miss query still returns a hit.
- **Likely files:** `tests/test_retrieve.py`, `src/agent_wiki/infrastructure/retrieval/retrieval_index.py`
- **Depends on:** P0-02, P0-03
- **Parallelizable:** no
- **Commit scope:** retrieval fuzzy integration

### P0-05 Add weighted ranking by topic/problem_cluster/content
- **Failing test focus:** topic/problem-cluster matches outrank body-only matches.
- **Likely files:** `tests/test_retrieve.py`, `src/agent_wiki/infrastructure/retrieval/retrieval_index.py`
- **Depends on:** P0-02
- **Parallelizable:** no
- **Commit scope:** ranking improvements only

### P0-06 Log query outcomes during query execution
- **Failing test focus:** `QueryService.execute()` appends one `query_outcomes.jsonl` record per query.
- **Likely files:** `tests/test_query_output.py`, `src/agent_wiki/domain/models.py`, `src/agent_wiki/application/query.py`
- **Depends on:** none
- **Parallelizable:** yes
- **Commit scope:** query outcome logging only

### P0-07 Expose hit/miss metrics in QueryResult
- **Failing test focus:** query result includes hit count / miss signal fields.
- **Likely files:** `tests/test_query_output.py`, `src/agent_wiki/domain/models.py`, `src/agent_wiki/application/query.py`
- **Depends on:** P0-06
- **Parallelizable:** no
- **Commit scope:** result shape + population

### P0-08 Implement PlainMarkdownAdapter read
- **Failing test focus:** reading a plain markdown file produces normalized document data.
- **Likely files:** new `tests/test_sync.py` case, `src/agent_wiki/infrastructure/adapters/plain_markdown.py`
- **Depends on:** none
- **Parallelizable:** yes
- **Commit scope:** plain adapter read

### P0-09 Implement PlainMarkdownAdapter write
- **Failing test focus:** writing normalized document data produces a markdown file.
- **Likely files:** `tests/test_sync.py`, `src/agent_wiki/infrastructure/adapters/plain_markdown.py`
- **Depends on:** P0-08
- **Parallelizable:** no
- **Commit scope:** plain adapter write

### P0-10 Implement ObsidianAdapter read with frontmatter parsing
- **Failing test focus:** Obsidian file frontmatter lands in normalized metadata / adapter metadata.
- **Likely files:** new `tests/test_sync.py` case, `src/agent_wiki/infrastructure/adapters/obsidian.py`
- **Depends on:** none
- **Parallelizable:** yes
- **Commit scope:** Obsidian read path

### P0-11 Implement ObsidianAdapter write with frontmatter preservation
- **Failing test focus:** normalized document writes back to Obsidian-compatible markdown with frontmatter.
- **Likely files:** `tests/test_sync.py`, `src/agent_wiki/infrastructure/adapters/obsidian.py`
- **Depends on:** P0-10
- **Parallelizable:** no
- **Commit scope:** Obsidian write path

### P0-12 Replace copy-based sync with adapter dispatch
- **Failing test focus:** `SyncService` chooses adapter from `external_views[].adapter` instead of raw `copy2` behavior.
- **Likely files:** `tests/test_sync.py`, `src/agent_wiki/application/sync.py`, adapter registry/factory helper
- **Depends on:** P0-08, P0-09, P0-10, P0-11
- **Parallelizable:** no
- **Commit scope:** adapter dispatch only

### P0-13 Make reverse sync create workspace-visible lifecycle input
- **Failing test focus:** pulling a new external file creates a raw capture or pending workspace entry visible to later lifecycle steps.
- **Likely files:** `tests/test_sync.py`, `src/agent_wiki/application/sync.py`, possibly `src/agent_wiki/application/capture_raw.py`
- **Depends on:** P0-12
- **Parallelizable:** no
- **Commit scope:** reverse sync lifecycle visibility

### P0-14 Preserve existing plain markdown sync behavior through adapters
- **Failing test focus:** existing `test_sync_pull_view_imports_external_markdown` and `test_sync_push_view_exports_workspace_markdown` still pass after adapter dispatch.
- **Likely files:** `tests/test_sync.py`, `src/agent_wiki/application/sync.py`
- **Depends on:** P0-12
- **Parallelizable:** no
- **Commit scope:** compatibility fix only

### P0-15 End-to-end retrieval quality integration test
- **Failing test focus:** Chinese + fuzzy + weighted ranking + query logging work together in one flow.
- **Likely files:** new integration-style test in `tests/test_query_output.py` or `tests/test_retrieve.py`
- **Depends on:** P0-02, P0-04, P0-05, P0-06
- **Parallelizable:** no
- **Commit scope:** integration test only

---

# Milestone P1 — Must keep knowledge evolving

## Goal
Add lightweight automation so raw capture does not stagnate: compile suggestions, fast feedback triggers, purpose-driven prioritization, and low-cost candidate relations.

## Current gap
- No automatic compile suggestions from raw accumulation
- No fast trigger from repeated low-value queries
- `purpose.md` is never read by runtime services
- No relation discovery at all
- Weekly review only counts queue items and feedback entries

## Ordered tasks

### P1-01 Detect raw accumulation by topic/problem_cluster
- **Failing test focus:** N raw pages in same cluster create a compile suggestion candidate.
- **Likely files:** new `tests/test_compile_suggestions.py`, new `src/agent_wiki/application/compile_suggest.py`
- **Depends on:** none
- **Parallelizable:** yes
- **Commit scope:** detection only

### P1-02 Write compile suggestions into review queue
- **Failing test focus:** accumulation detector appends `compile_suggestion` item.
- **Likely files:** `tests/test_compile_suggestions.py`, `src/agent_wiki/application/compile_suggest.py`, `src/agent_wiki/infrastructure/runtime/review_queue.py`
- **Depends on:** P1-01
- **Parallelizable:** no
- **Commit scope:** queue write only

### P1-03 Detect repeated low-value queries from query outcomes
- **Failing test focus:** 3 consecutive zero-hit outcomes trigger a quality signal.
- **Likely files:** new `tests/test_fast_feedback.py`, new `src/agent_wiki/application/fast_feedback.py`
- **Depends on:** P0-06
- **Parallelizable:** yes
- **Commit scope:** detection only

### P1-04 Write fast feedback signals into review queue
- **Failing test focus:** low-value query detector appends `quality_signal` item.
- **Likely files:** `tests/test_fast_feedback.py`, `src/agent_wiki/application/fast_feedback.py`
- **Depends on:** P1-03
- **Parallelizable:** no
- **Commit scope:** queue write only

### P1-05 Add purpose reader
- **Failing test focus:** `purpose.md` can be parsed into structured runtime intent.
- **Likely files:** new `tests/test_purpose_reader.py`, new `src/agent_wiki/infrastructure/storage/purpose_reader.py`
- **Depends on:** none
- **Parallelizable:** yes
- **Commit scope:** purpose reader only

### P1-06 Boost query ranking using purpose alignment
- **Failing test focus:** pages aligned to `purpose.md` outrank equally-scored non-aligned pages.
- **Likely files:** `tests/test_query_output.py`, `src/agent_wiki/application/query.py`, `src/agent_wiki/infrastructure/storage/purpose_reader.py`
- **Depends on:** P0-05, P1-05
- **Parallelizable:** no
- **Commit scope:** purpose-aware ranking

### P1-07 Prioritize compile suggestions using purpose alignment
- **Failing test focus:** purpose-aligned clusters sort ahead of non-aligned clusters.
- **Likely files:** `tests/test_compile_suggestions.py`, `src/agent_wiki/application/compile_suggest.py`, `src/agent_wiki/infrastructure/storage/purpose_reader.py`
- **Depends on:** P1-02, P1-05
- **Parallelizable:** no
- **Commit scope:** suggestion prioritization only

### P1-08 Detect co-occurrence relation candidates
- **Failing test focus:** repeated page co-occurrence across query outcomes produces a candidate relation.
- **Likely files:** new `tests/test_relations.py`, new `src/agent_wiki/application/relations.py`
- **Depends on:** P0-06
- **Parallelizable:** yes
- **Commit scope:** co-occurrence detection only

### P1-09 Write co-occurrence suggestions into review queue
- **Failing test focus:** co-occurrence detector appends `signal_candidate` item.
- **Likely files:** `tests/test_relations.py`, `src/agent_wiki/application/relations.py`
- **Depends on:** P1-08
- **Parallelizable:** no
- **Commit scope:** queue write only

### P1-10 Detect cross-reference relation candidates
- **Failing test focus:** page references through `source_refs` generate relation candidates.
- **Likely files:** `tests/test_relations.py`, `src/agent_wiki/application/relations.py`
- **Depends on:** none
- **Parallelizable:** yes
- **Commit scope:** cross-reference detection only

### P1-11 Write cross-reference suggestions into review queue
- **Failing test focus:** cross-reference detector appends `signal_candidate` item.
- **Likely files:** `tests/test_relations.py`, `src/agent_wiki/application/relations.py`
- **Depends on:** P1-10
- **Parallelizable:** no
- **Commit scope:** queue write only

### P1-12 Extend weekly review with raw backlog + purpose summary
- **Failing test focus:** weekly review includes raw backlog counts and purpose alignment notes.
- **Likely files:** `tests/test_weekly_review.py`, `src/agent_wiki/application/weekly_review.py`, `src/agent_wiki/infrastructure/storage/purpose_reader.py`
- **Depends on:** P1-05
- **Parallelizable:** no
- **Commit scope:** weekly review expansion

### P1-13 Extend weekly review with quality signals and compile suggestions
- **Failing test focus:** weekly review surfaces `quality_signal` and `compile_suggestion` items explicitly.
- **Likely files:** `tests/test_weekly_review.py`, `src/agent_wiki/application/weekly_review.py`
- **Depends on:** P1-04
- **Parallelizable:** no
- **Commit scope:** weekly review signal summary

---

# Milestone P2 — Must support stronger governance claims

## Goal
Fix identity precedence, enforce `max_gate`, add page-level sensitivity policy, and upgrade the review queue lifecycle.

## Current gap
- Caller-supplied identity still overrides metadata
- `max_gate` is loaded but ignored
- No sensitivity field or query-time filtering
- Review queue shape is minimal and append-only

## Ordered tasks

### P2-01 Add gate ordering helper
- **Failing test focus:** A < B < C ordering is defined in code, not implied by strings.
- **Likely files:** new `tests/test_gates.py`, `src/agent_wiki/domain/enums.py` or helper module
- **Depends on:** none
- **Parallelizable:** yes
- **Commit scope:** gate comparison only

### P2-02 Resolve identity from metadata before explicit actor fields
- **Failing test focus:** metadata wins over explicit fields when both are present.
- **Likely files:** `tests/test_identity_resolution.py`, `src/agent_wiki/infrastructure/identity/resolver.py`
- **Depends on:** none
- **Parallelizable:** yes
- **Commit scope:** resolver precedence only

### P2-03 Update identity tests to the new design target
- **Failing test focus:** existing precedence test asserts metadata-first behavior.
- **Likely files:** `tests/test_identity_resolution.py`
- **Depends on:** P2-02
- **Parallelizable:** no
- **Commit scope:** test alignment only

### P2-04 Enforce `max_gate` in PermissionService
- **Failing test focus:** actor with `max_gate=B` cannot execute a C-level operation.
- **Likely files:** `tests/test_permissions.py`, `src/agent_wiki/infrastructure/identity/permissions.py`, `src/agent_wiki/infrastructure/identity/gates.py`
- **Depends on:** P2-01
- **Parallelizable:** no
- **Commit scope:** permission gating only

### P2-05 Include gate level in PermissionDecision
- **Failing test focus:** permission decision exposes required gate for debugging and transport responses.
- **Likely files:** `tests/test_permissions.py`, `src/agent_wiki/domain/contracts.py`, `src/agent_wiki/infrastructure/identity/permissions.py`
- **Depends on:** P2-04
- **Parallelizable:** no
- **Commit scope:** decision shape only

### P2-06 Add sensitivity enum
- **Failing test focus:** `public` / `internal` / `confidential` values exist as first-class domain vocabulary.
- **Likely files:** new `tests/test_sensitivity.py`, `src/agent_wiki/domain/enums.py`
- **Depends on:** none
- **Parallelizable:** yes
- **Commit scope:** enum only

### P2-07 Propagate sensitivity through manifest writes
- **Failing test focus:** compiled/raw entries preserve sensitivity in manifest.
- **Likely files:** `tests/test_manifest.py` or `tests/test_compile_apply.py`, `src/agent_wiki/application/propagation.py`
- **Depends on:** P2-06
- **Parallelizable:** no
- **Commit scope:** propagation only

### P2-08 Filter query results by sensitivity policy
- **Failing test focus:** restricted actor cannot retrieve confidential pages.
- **Likely files:** `tests/test_query_output.py`, `src/agent_wiki/application/query.py`, possibly permission helper
- **Depends on:** P2-07
- **Parallelizable:** no
- **Commit scope:** query filtering only

### P2-09 Support richer review queue item shape
- **Failing test focus:** queue item stores `item_id`, `wiki_id`, `priority`, `created_at`, `content_state`, etc.
- **Likely files:** `tests/test_review_queue.py`, `src/agent_wiki/infrastructure/runtime/review_queue.py`
- **Depends on:** none
- **Parallelizable:** yes
- **Commit scope:** repository read/write shape support

### P2-10 Add review queue status transitions
- **Failing test focus:** `open → assigned → in_progress → resolved → archived` works and invalid transitions fail.
- **Likely files:** `tests/test_review_queue.py`, `src/agent_wiki/infrastructure/runtime/review_queue.py`
- **Depends on:** P2-09
- **Parallelizable:** no
- **Commit scope:** status transition support

### P2-11 Make propagation write enriched queue items
- **Failing test focus:** evidence-related queue items include `wiki_id`, `priority`, `created_at`, and richer state fields.
- **Likely files:** `tests/test_review_queue.py`, `src/agent_wiki/application/propagation.py`
- **Depends on:** P2-09
- **Parallelizable:** no
- **Commit scope:** propagation queue enrichment

### P2-12 Enforce permission + gate checks in compile_update
- **Failing test focus:** B-level compile update fails for actor capped below B.
- **Likely files:** `tests/test_compile_apply.py`, `src/agent_wiki/application/compile_update.py`
- **Depends on:** P2-04
- **Parallelizable:** no
- **Commit scope:** compile gate enforcement

### P2-13 Enforce permission + gate checks in capture_raw
- **Failing test focus:** raw capture fails without matching A-level permission.
- **Likely files:** `tests/test_ingest.py`, `src/agent_wiki/application/capture_raw.py`
- **Depends on:** P2-04
- **Parallelizable:** no
- **Commit scope:** capture gate enforcement

---

# Milestone P3 — Must complete authority / service / DFX story

## Goal
Add authority-promotion / commit orchestration, real `aw serve`, MCP + REST transport scaffolding, and minimal operational integrity signals.

## Current gap
- No gate-to-Git authority promotion flow
- No stale-marker / failure recovery signaling
- No MCP transport
- No REST transport
- No `aw serve`
- Container is only partially wired

## Ordered tasks

### P3-01 Add authority promotion service
- **Failing test focus:** gate-passing change can be promoted into a Git commit.
- **Likely files:** new `tests/test_authority.py`, new `src/agent_wiki/application/authority.py`
- **Depends on:** P2-04, P2-12, P2-13
- **Parallelizable:** no
- **Commit scope:** authority promotion only

### P3-02 Block authority promotion on gate failure
- **Failing test focus:** failing gate prevents commit and keeps local/pending state intact.
- **Likely files:** `tests/test_authority.py`, `src/agent_wiki/application/authority.py`
- **Depends on:** P3-01
- **Parallelizable:** no
- **Commit scope:** gate-failure block only

### P3-03 Add stale marker runtime support
- **Failing test focus:** failed downstream propagation can write a stale marker file.
- **Likely files:** new `tests/test_lint.py` or `tests/test_runtime_state.py`, `src/agent_wiki/infrastructure/runtime/pending_state.py`
- **Depends on:** none
- **Parallelizable:** yes
- **Commit scope:** stale marker support only

### P3-04 Make lint detect stale markers
- **Failing test focus:** lint reports stale markers as issues.
- **Likely files:** `tests/test_lint.py`, `src/agent_wiki/application/linting.py`
- **Depends on:** P3-03
- **Parallelizable:** no
- **Commit scope:** lint extension only

### P3-05 Scaffold MCP server with tool registry
- **Failing test focus:** MCP server starts and lists expected tools.
- **Likely files:** new `tests/test_mcp_server.py`, new `src/agent_wiki/transports/mcp/server.py`
- **Depends on:** none
- **Parallelizable:** yes
- **Commit scope:** MCP scaffold only

### P3-06 Implement MCP `wiki.query`
- **Failing test focus:** MCP query tool delegates to `QueryService` and returns structured data.
- **Likely files:** `tests/test_mcp_server.py`, `src/agent_wiki/transports/mcp/server.py`
- **Depends on:** P3-05
- **Parallelizable:** yes
- **Commit scope:** MCP query tool only

### P3-07 Implement MCP `wiki.capture_raw`
- **Failing test focus:** MCP capture tool delegates to `CaptureRawService` and writes a page.
- **Likely files:** `tests/test_mcp_server.py`, `src/agent_wiki/transports/mcp/server.py`
- **Depends on:** P3-05
- **Parallelizable:** yes
- **Commit scope:** MCP capture tool only

### P3-08 Implement MCP `wiki.compile_update`
- **Failing test focus:** MCP compile tool delegates to `CompileUpdateService` and writes a compiled page.
- **Likely files:** `tests/test_mcp_server.py`, `src/agent_wiki/transports/mcp/server.py`
- **Depends on:** P3-05
- **Parallelizable:** yes
- **Commit scope:** MCP compile tool only

### P3-09 Resolve MCP identity from session/client metadata
- **Failing test focus:** MCP transport does not trust request-supplied actor fields.
- **Likely files:** `tests/test_mcp_server.py`, `src/agent_wiki/transports/mcp/server.py`, `src/agent_wiki/infrastructure/identity/resolver.py`
- **Depends on:** P3-05, P2-02
- **Parallelizable:** no
- **Commit scope:** MCP identity path only

### P3-10 Scaffold REST app with `/health`
- **Failing test focus:** REST health endpoint returns 200 with basic status payload.
- **Likely files:** new `tests/test_rest_app.py`, new `src/agent_wiki/transports/rest/app.py`
- **Depends on:** none
- **Parallelizable:** yes
- **Commit scope:** REST scaffold only

### P3-11 Add REST query and capture endpoints
- **Failing test focus:** REST query/capture endpoints delegate to core services.
- **Likely files:** `tests/test_rest_app.py`, `src/agent_wiki/transports/rest/app.py`
- **Depends on:** P3-10
- **Parallelizable:** no
- **Commit scope:** REST query/capture only

### P3-12 Add CLI `aw serve`
- **Failing test focus:** `aw serve` starts the long-running service path.
- **Likely files:** `tests/test_cli_smoke.py` or new CLI test file, `src/agent_wiki/transports/cli/app.py`
- **Depends on:** P3-05, P3-10
- **Parallelizable:** no
- **Commit scope:** serve command only

### P3-13 Add CLI `query`, `capture-raw`, `compile-update`, `lint`
- **Failing test focus:** CLI command surface delegates to core services and returns deterministic output.
- **Likely files:** new CLI command tests, `src/agent_wiki/transports/cli/app.py`
- **Depends on:** P3-12
- **Parallelizable:** no
- **Commit scope:** operational CLI commands only

### P3-14 Wire all new services in Container
- **Failing test focus:** container exposes new runtime/application services needed by transports and maintenance flows.
- **Likely files:** `tests/test_bootstrap.py`, `src/agent_wiki/bootstrap/container.py`
- **Depends on:** P1-01, P1-03, P1-05, P1-08, P3-01
- **Parallelizable:** no
- **Commit scope:** container wiring only

---

# Cross-milestone dependencies

## Critical path
- Retrieval quality: `P0-01 → P0-02 → P0-04 → P0-15`
- Obsidian path: `P0-10 → P0-11 → P0-12 → P0-13`
- Purpose-driven evolution: `P1-05 → P1-06 / P1-07 / P1-12`
- Governance gate path into authority promotion: `P2-01 → P2-04 → P2-12/P2-13 → P3-01`
- Transport maturity: `P3-05 → P3-06/P3-07/P3-08/P3-09` and `P3-10 → P3-11`, then `P3-12 → P3-13`

## Parallelizable clusters
These can be worked in parallel once their prerequisite foundation exists:

### P0 parallel cluster
- P0-01 and P0-03
- P0-08 and P0-10

### P1 parallel cluster
- P1-01, P1-03, P1-05, P1-08, P1-10

### P2 parallel cluster
- P2-01, P2-02, P2-06, P2-09

### P3 parallel cluster
- P3-03, P3-05, P3-10
- After P3-05: P3-06, P3-07, P3-08 can split

---

# Verification strategy

## Per-task verification
Every task must follow the same loop:
1. Add one failing test.
2. Run that test and confirm failure.
3. Implement the minimum code to pass.
4. Run the touched test file.
5. Run the full suite.
6. Commit only the files needed for that task.

## End-of-milestone verification

### P0 complete when
- Chinese content is retrievable.
- Near-miss queries return useful hits.
- Ranking prefers topic/problem-cluster matches.
- Query execution writes hit/miss outcomes automatically.
- Obsidian read/write works via adapters.
- Reverse sync creates workspace-visible lifecycle input.

### P1 complete when
- Raw accumulation creates compile suggestions.
- Repeated low-value queries create quality signals.
- `purpose.md` influences ranking and suggestion priority.
- Co-occurrence and cross-reference relations appear as suggestions.
- Weekly review includes backlog, purpose, and signal summaries.

### P2 complete when
- Identity precedence matches the design target.
- `max_gate` is enforced.
- Sensitivity policy filters query results.
- Review queue supports richer lifecycle metadata and transitions.

### P3 complete when
- Gate-passing changes can be promoted to Git authority.
- Lint detects stale markers.
- MCP and REST transport scaffolds are live.
- `aw serve` exists.
- CLI operational commands exist.
- Container wiring reflects the new runtime shape.

## Commands to run during implementation
- `python3 -m pytest`
- Targeted pytest runs for the touched test file during each tiny TDD loop
- CLI smoke as new commands land:
  - `python3 -m agent_wiki.transports.cli.app --help`
  - `python3 -m agent_wiki.transports.cli.app info`
  - later `python3 -m agent_wiki.transports.cli.app serve --help`

## Notes for execution
- Keep tasks surgical; do not batch multiple unrelated behaviors into one commit.
- Where behavior changes intentionally break current tests, update the failing expectation in the same task commit.
- Reuse current file-backed service test style; do not introduce mocks where existing tests already validate real filesystem behavior.
- Do not let transport layers own policy or retrieval logic; they should delegate into the shared core.
