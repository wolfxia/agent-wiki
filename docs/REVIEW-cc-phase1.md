# Phase 1 Code Review — Independent (CC)

> Reviewer: Claude Code (Opus 4.7)
> Date: 2026-05-16
> Scope: full Phase 1 baseline in `src/agent_wiki/` plus transports and tests
> Method: independent walk of source + tests, no other reviews consulted

This review is structured as a P0/P1/P2 punch list. Every item cites concrete file/line evidence. The framing throughout is: *does this match the contract in `core/schema.md` and the architecture in `docs/design.md`, and would I trust this if it shipped?*

---

## TL;DR

Phase 1 is functionally green (103 tests passing) and the architecture matches the design **at the seams**: thin transports, shared core, file-backed runtime, manifest as authority surrogate. The closed loop from query → maintenance → review queue → weekly review actually runs end-to-end.

But there are **real holes**, and most of them cluster around governance and deployment:

- **The transports lie about identity.** CLI and REST hardcode `actor_id="claude-code"` and never resolve through `IdentityResolver`. This makes every governance test on `PermissionService` and `max_gate` decorative for those transports.
- **The transports cannot run outside the test fixture directory.** Both CLI and REST hardcode `Path("tests/fixtures/registry.yaml")`. `aw query` from any other working directory will fail.
- **The slow-loop orchestrator is not idempotent.** `MaintenanceService.run` re-enqueues the same `compile_suggestion` / `quality_signal` / `signal_candidate` items every invocation, growing `review_queue.jsonl` without bound.
- **`ApprovalService` and `SyncService` bypass `PermissionService` entirely.** Approvals route around the gate engine via `allow_shared_write_without_sources=True`, and sync writes pages without a permission check at all.
- **Domain enums exist but are barely used.** `Sensitivity`, `PageType`, `ActorType` ship as `StrEnum` but every service compares raw string literals.

These are mostly P0/P1 fixes — none invalidate the architecture, but several are required before the system can credibly claim governance enforcement, before `aw maintain` can run on a real cron, and before the CLI is usable outside `pytest`.

---

## P0 — must fix before anyone uses this for real

### P0-1. Transports hardcode actor identity, bypassing `IdentityResolver`

**Evidence**
- `src/agent_wiki/transports/cli/app.py:27-28` — `_actor()` returns `ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")`.
- `src/agent_wiki/transports/rest/app.py:46` and `src/agent_wiki/transports/rest/app.py:67` — both endpoints hardcode the same actor.
- `src/agent_wiki/infrastructure/identity/resolver.py:5-10` — `IdentityResolver.resolve()` exists and is correct (metadata-first), but is never called from CLI or REST.

**Why this is P0**

The whole P2 governance story (P2-02, P2-04, P2-12, P2-13) depends on the actor that reaches `PermissionService` being a real, transport-resolved actor. The CLI and REST transports inject a constant `claude-code` identity that happens to pass the fixture's permission check. This is not a Phase 1 simplification — it is the exact "callers must not override identity" violation called out in `core/schema.md` and in `CLAUDE.md`.

A user running `aw query` as a non-`claude-code` agent gets implicit elevation to the fixture's permissions. Any test that asserts permission/gate denial on REST or CLI is currently passing because there are no such tests.

**Fix direction**
- Add `IdentityResolver` calls at both transport entry points.
- For CLI: read identity from env/`~/.config/agent-wiki/identity.yaml` (which `settings.py:4` already references but nothing reads).
- For REST: derive from request headers / session.
- Drop `_actor()` and the constant strings.

---

### P0-2. CLI and REST cannot run outside the test fixtures directory

**Evidence**
- `src/agent_wiki/transports/cli/app.py:20` — `RegistryLoader().load(Path("tests/fixtures/registry.yaml"))`.
- `src/agent_wiki/transports/rest/app.py:33` — same hardcoded relative path.
- `src/agent_wiki/settings.py:3` — `DEFAULT_REGISTRY_PATH = Path("registry.yaml")` is defined but never imported anywhere.

**Why this is P0**

`aw serve`, `aw query`, `aw capture-raw`, `aw maintain` only work when CWD is the repo root. From any other directory, `RegistryLoader().load(...)` raises `FileNotFoundError` before the command does anything. This means none of the deployment flows from `docs/design.md` §4 ("Protocol-Centered Agent Access") are actually deployable.

Verified empirically: running CLI from `/tmp` fails with `ModuleNotFoundError`/`FileNotFoundError`; the transports are coupled to the repo layout.

**Fix direction**
- Use `settings.DEFAULT_REGISTRY_PATH` and an env var override (`AGENT_WIKI_REGISTRY`).
- Add a `--registry` CLI option mirroring `--workspace`.
- For REST, accept `registry_path` as a `create_app` argument and resolve at app startup, not per-request.

---

### P0-3. `MaintenanceService.run` is not idempotent — review queue grows unbounded

**Evidence**
- `src/agent_wiki/application/maintenance.py:8-20` — calls four `detect_and_enqueue_*` methods unconditionally.
- `src/agent_wiki/application/compile_suggest.py:38-53` — `detect_and_enqueue` always appends every detected candidate. No deduplication against the existing queue.
- Same shape in `src/agent_wiki/application/fast_feedback.py:37-51` and both methods of `src/agent_wiki/application/relations.py:78-108`.

**Why this is P0**

`aw maintain` is the user-facing slow-loop entry point. Running it twice on the same data creates duplicate `compile_suggestion`, `quality_signal`, and `signal_candidate` entries. Running it on a cron creates daily duplicates forever. The `quality_report` `orphan_count` is computed correctly, but the queue surface that the agent reads becomes garbage within a week.

This is structurally the same defect as the `_VALID_TRANSITIONS` map in `review_queue.py:4-9` — there is no concept of "this signal already exists, skip." The transition machinery is wired, but no detector ever sets `item_id`, so transitions cannot apply to detector-emitted items either.

**Fix direction**

Two options, in order of preference:

1. **Deterministic `item_id` per (item_type, key fields).** Compile suggestion: `compile-{topic}-{cluster}`. Quality signal: `quality-{query_hash}`. Co-occurrence: `cooc-{sorted-doc-id-pair}`. Append-and-dedupe by `item_id`, or upsert. This also unlocks the `transition()` API for these items.

2. **Read existing queue, skip duplicates by content hash.** Lower-quality but immediate.

Whichever path you pick, the right place is inside each `detect_and_enqueue` — `MaintenanceService` should remain a thin sequencer.

---

### P0-4. `ApprovalService` bypasses gate enforcement on principle promotion

**Evidence**
- `src/agent_wiki/application/approvals.py:36-49` — calls `propagation.propagate_compile_update` directly with `allow_shared_write_without_sources=True` and **never** invokes `PermissionService`.
- `src/agent_wiki/application/compile_update.py:29-32` — gate check lives in `CompileUpdateService.apply`, which `ApprovalService` skips.
- `src/agent_wiki/infrastructure/identity/gates.py:16` — `approve_proposal` is mapped to gate C, but no code path ever asks for that gate.

**Why this is P0**

The C-level approval flow is the *one* place where Phase 1 explicitly enforces high-risk human-confirmation gates (per `core/schema.md` §13 and `docs/design.md` §3 Phase Gate System). The current `ApprovalService.approve` writes the page, manifest, retrieval index, and approval log without ever consulting `PermissionService`. Any actor that can call `approve` can elevate any proposal to a committed page, regardless of `max_gate` or `actor_type`.

This is also what makes the fixture's `permissions[].max_gate=B` setting deceptively passing tests: there are no `actor_id=claude-code` C-level operations *outside* the approval path.

**Fix direction**
- Have `ApprovalService.approve` call `PermissionService.check(actor, "approve_proposal", wiki, proposal["page_type"])` before propagation.
- Reject the approval (and write to a denied-approvals log) if the gate fails.
- Add an explicit test that a B-capped agent cannot approve a principle proposal.

---

### P0-5. `SyncService` performs no permission/gate check

**Evidence**
- `src/agent_wiki/application/sync.py:26-80` — every mode (`status`, `pull-view`, `push-view`) runs unconditionally.
- `src/agent_wiki/application/sync.py:42-61` — `_pull_view` writes pages and pending manifest entries on behalf of any caller.
- `src/agent_wiki/application/sync.py:63-80` — `_push_view` writes to external paths without checking the actor.

**Why this is P0**

Reverse sync creates pending raw entries (P0-13) that downstream queries can opt into via `include_pending=True`. There is currently no actor argument on `SyncService.execute` at all — the Pydantic `SyncInput` only has a `mode` string. This means anyone with code reach can drop content into the pending truth zone without identity, gate, or sensitivity propagating with it.

The forward path (`push-view`) also overwrites external view content, including frontmatter — and `_push_view` reads the existing target file on every push to preserve frontmatter (`sync.py:74-77`), which is fine for round-trip but means a malicious external file gets read and parsed (yaml.safe_load) without consent.

**Fix direction**
- Add `actor: ResolvedActor` to `SyncService.execute` (and `SyncInput`).
- Permission-check `sync` as its own operation in `GateService.required_gate`. Pull/push are A-level by default; gate elevates if writing to truth-zone external paths.
- Pending entries written from sync should carry `last_writer = actor.actor_id` (currently they don't — `sync.py:56-60`).

---

### P0-6. `aw maintain` and authority promotion ignore C-level operations entirely

**Evidence**
- `src/agent_wiki/application/authority.py:19` — `operation = "promote_principle" if page_type == "principle" else "compile_update"`. Hardcoded, no other C-level operations covered.
- `src/agent_wiki/application/maintenance.py` — runs detectors but never produces or consumes `principle_proposal` items, despite `core/schema.md:364` listing it as a queue item type.
- `src/agent_wiki/infrastructure/identity/gates.py:16` — `cross_wiki_merge` is gate C, but `CrossWikiQueryService` (`query.py:177`) is read-only and the write side is unimplemented.

**Why this is P0** (lower urgency than P0-1..5, but still required for the design's claims)

The Phase 1 spec says C-level gates exist and are enforced. In practice, only `compile_update` and `capture_raw` are checked. Authority promotion via `AuthorityService.promote` is reachable, but it is the only C-level surface, and nothing in the runtime ever calls it — there is no test that ties `promote_principle` to a real workflow.

**Fix direction**
- Wire `ApprovalService.approve` into `AuthorityService.promote` for principle pages: approval is the gate-checked path that writes; promotion is the audit/authority log layer above it.
- Or: explicitly mark principle promotion as Phase 2 in the design and remove the dead `AuthorityService` from Container wiring (`bootstrap/container.py:23`).

---

## P1 — must fix before next iteration

### P1-1. Domain enums exist but are bypassed everywhere

**Evidence**
- `src/agent_wiki/domain/enums.py:23-26` — `Sensitivity` enum is defined.
- `src/agent_wiki/application/query.py:112` — `_SENSITIVITY_ORDER = {"public": 0, "internal": 1, "confidential": 2}` uses raw strings, not the enum.
- `src/agent_wiki/application/query.py:118-121` — `entry.get("sensitivity") or "public"` and `_SENSITIVITY_ORDER.get(max_sensitivity, 1)` fall back to magic numbers when the input is invalid.
- `src/agent_wiki/application/quality_report.py:7` — `_COMPILED_PAGE_TYPES = {"atom", "synthesis", "principle"}` instead of `PageType.ATOM`, etc.
- `src/agent_wiki/application/query.py:99` — same string set hardcoded again in `_manifest_priority`.
- `src/agent_wiki/infrastructure/identity/gates.py:14-16` — operations are bare strings (`"capture_raw"`, `"compile_update"`, `"mark_disputed"`, `"promote_principle"`, `"approve_proposal"`, `"cross_wiki_merge"`); there is no `Operation` enum.
- `src/agent_wiki/domain/models.py:39` — `CompileUpdateInput.sensitivity: str | None`. Should be `Sensitivity | None`.

**Why this is P1**

Three concrete consequences:

1. A typo in `max_sensitivity="confdential"` silently degrades to default level 1 (internal) — `query.py:119` falls back via `dict.get(default=1)`. That's a security-adjacent bug: callers can mistype and quietly get *more* than they asked for.
2. The compile rate, page-type priority, and pending filter logic each hold their own copy of "what counts as compiled." If anyone adds a new `page_type` (e.g. `dispute`), every set must be updated. There is no single source of truth despite the enum existing.
3. Adding an `Operation` enum and using it in `GateService` and `PermissionConfig.allowed_operations` would make every governance check exhaustively type-checkable. Right now a permission rule with `allowed_operations: [querie]` (typo) loads silently and never matches.

**Fix direction**
- Replace string sets with enum sets across services.
- Make `QueryInput.max_sensitivity: Sensitivity | None`. Fail fast on invalid values via Pydantic.
- Add `Operation` enum; use it in `GateService.required_gate`, `PermissionConfig`.

---

### P1-2. `CrossWikiQueryService` does not log query outcomes per-wiki

**Evidence**
- `src/agent_wiki/application/query.py:177-200` — `CrossWikiQueryService.execute` calls `QueryService().execute(wiki, ...)` per wiki. Each call writes its own `query_outcomes.jsonl` entry (line 152-174). The cross-wiki entry itself is not aggregated.
- `src/agent_wiki/application/quality_report.py:30-45` — reads `query_outcomes.jsonl` from `wiki.workspace_path`. There is no cross-wiki quality report.

**Why this is P1**

Per-wiki outcome rows record a query was executed, but a 3-wiki cross-wiki search of "deployment strategy" creates 3 outcome rows in 3 different files, each tagged with the same query string. `FastFeedbackService.detect_low_value_queries` (`fast_feedback.py:18-24`) counts zero-hits *per wiki*, so a query that finds zero hits in wiki A but plenty in wikis B and C will trigger a `quality_signal` in wiki A. That's wrong — the user got an answer, the framework should not flag it as missing knowledge.

**Fix direction**
- Aggregate cross-wiki outcomes: write only to one of the wikis (or to a shared registry log), and tag the row with `cross_wiki: true`.
- Or: have `FastFeedbackService` exclude rows that came from a cross-wiki call (requires a `cross_wiki` flag on the outcome record).

---

### P1-3. `query.py:170` recounts the entire outcomes file on every query

**Evidence**
- `src/agent_wiki/application/query.py:168-174`:
  ```python
  hits_path = wiki_root / "query_hits.jsonl"
  outcomes_count = sum(1 for _ in path.read_text(encoding="utf-8").splitlines() if _.strip())
  query_idx = outcomes_count - 1
  with hits_path.open("a", encoding="utf-8") as handle:
      for hit in hits:
          handle.write(json.dumps({"query_idx": query_idx, "doc_id": hit.doc_id}, ensure_ascii=False) + "\n")
  ```

**Why this is P1**

This is O(N) per query, where N is total queries ever executed. After 10k queries the read+split scans 10k lines for every new query. Worse, the `query_idx` derivation is racy — two near-simultaneous queries can produce two outcome rows but mismatched indices in `query_hits.jsonl` if the code is ever run concurrently.

The root issue is that `query_hits.jsonl` shouldn't reference an external row index at all. It should embed the join key directly (timestamp, query string, or a UUID per outcome).

**Fix direction**
- Replace `query_idx` with a `query_id` (uuid4) generated once per `execute()` and written to both files.
- `RelationsService.detect_co_occurrences` (`relations.py:22-28`) groups by `query_idx`; switch to grouping by `query_id`.
- `query_outcomes.jsonl` schema gains `query_id`; downstream readers ignore the extra field if absent.

---

### P1-4. Capture/compile path uses `doc_id` directly as filename — path traversal risk

**Evidence**
- `src/agent_wiki/application/propagation.py:23` — `page_path = self.wiki_root / "pages" / f"{data.doc_id}.md"`.
- `src/agent_wiki/application/capture_raw.py:11` — `_DOC_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")`.
- `src/agent_wiki/application/compile_update.py:24` — `apply` does **not** validate `doc_id` against the pattern. `_source_refs_are_valid` only checks the prefix `wiki_id`.
- `src/agent_wiki/application/propagation.py:60` — `propagate_compile_update` writes `pages/{doc_id}.md` directly with no validation.

**Why this is P1**

`CaptureRawService` validates `doc_id` and routes invalid IDs to pending. `CompileUpdateService.apply` (and therefore the MCP/REST `wiki.compile_update` tool) does not. A `doc_id` like `../../../etc/passwd` reaches `propagation.py:60` and writes outside the pages directory. The `_source_refs_are_valid` check only validates that source refs are well-formed — it does not validate the new doc's own ID.

In practice this is mitigated by `wiki.workspace_path` being the test fixture, but for production this is a real path-traversal hole on the compile side.

**Fix direction**
- Move `_DOC_ID_PATTERN` to a shared module (`domain/validators.py` or similar).
- Validate `doc_id` in `CompileUpdateService.apply` before propagation; raise `ValueError` on mismatch.
- Same validation in `ApprovalService.approve` for the proposal's `doc_id`.

---

### P1-5. `_view_path(view)` returns wiki-root-relative path; `external_views` in fixture has no `path`

**Evidence**
- `tests/fixtures/registry.yaml:13-14`:
  ```yaml
  external_views:
    - adapter: plain_markdown
      mode: read_write
  ```
  No `path` is set.
- `src/agent_wiki/bootstrap/registry_loader.py:24` — `path: str | None = None`.
- `src/agent_wiki/application/sync.py:87-90`:
  ```python
  def _view_path(self, view: object) -> str:
      if isinstance(view, dict):
          return str(view["path"])
      return str(view.path)
  ```

**Why this is P1**

If the fixture-style config (`path` omitted) flows into `_view_path`, the `view.path` attribute is `None`, which `str()` converts to the literal string `"None"`. Then `Path("None").glob("*.md")` happily returns nothing — sync silently does nothing. Tests don't catch this because all `test_sync.py` cases override `external_views` with explicit `path` values.

**Fix direction**
- Make `ExternalViewConfig.path` non-optional (or default to `wiki_root / "external"`).
- Validate `path` is set in `_view_path`; raise on missing.
- Add a regression test that the fixture's default config doesn't silently no-op.

---

### P1-6. `ManifestRepository.read_all()` re-reads the file on every call

**Evidence**
- `src/agent_wiki/infrastructure/storage/manifest_repo.py:11-12` — `append()` calls `read_all()`.
- `src/agent_wiki/application/query.py:27` — sort key calls `_purpose_boost` and `_manifest_priority`, each of which calls `manifest.find()`, each of which calls `read_all()`. For N hits, that's 2N file reads.

**Why this is P1**

For a 1000-page wiki with 100 query hits, this is 200 reads of `MANIFEST.jsonl` per query. The lint service has the same shape: `lint.py:22` iterates `read_all()`, and `lint.py:37` calls `manifest.find()` (which re-reads) inside the retrieval-index loop.

**Fix direction**
- Cache `read_all()` per repository instance. Invalidate on `append`/`upsert`.
- Or pass a single pre-read entry list down through `QueryService` and `LintService`.

---

### P1-7. `PurposeReader._cache` is request-scoped but reader is recreated per query

**Evidence**
- `src/agent_wiki/infrastructure/storage/purpose_reader.py:8` — `self._cache: dict | None = None` is per-instance.
- `src/agent_wiki/application/query.py:26` — `purpose_reader = PurposeReader(wiki_root)` constructs a new reader inside `execute()`.
- Same in `compile_suggest.py:16` and `weekly_review.py:34`.

**Why this is P1**

The cache is dead code — every consumer instantiates a fresh reader, and `is_aligned` is called once or a few times before the reader is discarded. The `_get_cached` indirection adds nothing.

**Fix direction**
- Either thread a single `PurposeReader` through `Container` (the factory exists at `container.py:24` but no service uses it), or remove the caching.

---

### P1-8. Sensitivity filter happens *after* fuzzy/lexical retrieval, leaking signal in scores

**Evidence**
- `src/agent_wiki/application/query.py:19-25`:
  ```python
  hits = retrieval_index.lexical_search(data.query)
  if data.include_pending:
      hits.extend(self._search_pending_truth_zone(...))
  filtered_hits = [hit for hit in hits if self._include_hit(...)]
  if data.max_sensitivity:
      filtered_hits = [... if self._sensitivity_allowed(...)]
  ```

**Why this is P1**

The `lexical_search` reads `retrieval_index.jsonl` directly — every confidential page's content is loaded and tokenized for every query, regardless of caller clearance. The L1 answer is built from whichever hit ranks first, but the score itself is computed from confidential content. That score then influences the sort. Even though confidential hits are filtered out before `l2_context`/`l3_proof`/`l1_answer`, **`query_outcomes.jsonl` records the unfiltered count** because `_append_query_outcome` is called on `filtered_hits` after sensitivity filtering — actually wait, line 31 confirms it's filtered. Good.

But the side effect is still wrong: a lower-cleared actor's outcome row records `hit_count = 0` even though the underlying corpus had hits. `FastFeedbackService` then counts those as "low value" and creates a `quality_signal`. The signal misattributes a clearance gap to a knowledge gap.

**Fix direction**
- Filter sensitivity in the retrieval index path itself (read manifest first, build allowed `doc_id` set, only score those).
- Or: tag outcomes with a `filtered_by_sensitivity` flag and have `FastFeedbackService` exclude those.

---

### P1-9. Container exposes services but no service consumes the Container

**Evidence**
- `src/agent_wiki/bootstrap/container.py:14-24` — wires 9 services.
- `grep -rn "Container()" src/agent_wiki/` — only `transports/cli/app.py:38` instantiates it, and only to call `__class__.__name__` (the `info` command). Nothing else uses it.
- `src/agent_wiki/transports/mcp/server.py:14-20`, `src/agent_wiki/transports/rest/app.py:28-37`, all CLI commands — every one news up its own service.

**Why this is P1**

The Container is theater. It exists for tests to assert that services can be constructed, but no production code path goes through it. This means there's no single place to inject mocks, no DI lifecycle, and no shared instance reuse. Per-call instantiation is also why the `PurposeReader._cache` is dead.

**Fix direction**
- Either delete the Container and stop pretending DI exists, or make the transports consume it (`mcp_server = MCPServer(container)`, etc.).
- The "delete" path is fine for Phase 1; it just shouldn't be wired up only to be ignored.

---

### P1-10. `IdentityResolver` quietly defaults to `actor_type="human", actor_id="unknown"`

**Evidence**
- `src/agent_wiki/infrastructure/identity/resolver.py:7-10`:
  ```python
  metadata = context.metadata or {}
  actor_type = metadata.get("actor_type") or context.actor_type or "human"
  actor_id = metadata.get("actor_id") or context.actor_id or "unknown"
  ```

**Why this is P1**

If neither metadata nor explicit fields supply identity, the resolver fabricates `human:unknown`. That actor will never match any permission rule, so all subsequent calls fail with `"no matching permission rule"` — but they fail at the *permission* layer, not at the identity layer. This buries the real problem ("no identity provided") under a generic permission denial.

**Fix direction**
- Raise `IdentityResolutionError` when both metadata and explicit fields are empty.
- Tests on permission denials should use real identities, not the silent default.

---

## P2 — quality issues, schema drift, dead code

### P2-1. `wiki.allowed_page_types` and `permission.allowed_page_types` overlap

**Evidence**
- `src/agent_wiki/application/capture_raw.py:16` — `if "raw" not in wiki.allowed_page_types`.
- `src/agent_wiki/application/compile_update.py:26` — `if data.page_type not in wiki.allowed_page_types`.
- `src/agent_wiki/infrastructure/identity/permissions.py:19` — `if page_type not in permission.allowed_page_types`.

These checks happen in series, with the same page_type, but one is wiki-level and one is per-actor. The wiki-level check rejects with `ValueError`; the permission check returns a `PermissionDecision`. Two failure shapes for one logical concept.

**Why P2**

It works, but the call sites raise different exception types for the same conceptual denial. `CompileUpdateService.apply` raises `ValueError` for page-type-not-allowed-by-wiki and `PermissionError` for page-type-not-allowed-by-actor. Hard to handle uniformly upstream.

**Fix direction**
- Fold the wiki-level check into `PermissionService` (or a new `PolicyService`).
- Standardize on `PermissionError`.

---

### P2-2. `CompileUpdateService.apply` has a dead Milestone-3 branch

**Evidence**
- `src/agent_wiki/application/compile_update.py:37-38`:
  ```python
  if actor.actor_type == "agent" and data.page_type not in {"atom", "synthesis"}:
      raise ValueError("compile_update only supports atom and synthesis in Milestone 3")
  ```

**Why P2**

We're past Milestone 3, and this branch reduplicates page-type policy that is now covered by the registry's `allowed_page_types`. Also, the registry currently allows `principle` for `claude-code`, so this check would conflict with the registry policy if `principle` were ever requested.

**Fix direction**
- Delete. Page-type allow-listing already lives in registry config.

---

### P2-3. `CompileUpdateService.analyze` is unused

**Evidence**
- `src/agent_wiki/application/compile_update.py:12-22` — defined.
- `grep -rn "compile_service.analyze\|CompileUpdateService().analyze" src/agent_wiki/ tests/` — zero call sites in production code, only `tests/test_compile_analyze.py` exercises it directly.

**Why P2**

The "analyze before apply" flow described in `core/schema.md` §5.1 (Two-Step ingest) is only half-implemented. `analyze` returns a `CompileAnalysis` but no caller does anything with it. `apply` does not consult `analyze`'s output. Either delete `analyze` (and the test) until the two-step flow is real, or wire it into the MCP/CLI entry points.

---

### P2-4. `RelationsService.detect_cross_references` has O(P×R²) shared-ref scan

**Evidence**
- `src/agent_wiki/application/relations.py:69`:
  ```python
  shared = [r for r, docs in ref_to_docs.items() if a in docs and b in docs]
  ```
  Inside a nested loop over `combinations(sorted(doc_ids), 2)` for every `ref` in `ref_to_docs`.

**Why P2**

For P refs and R doc-pairs sharing each ref, the inner comprehension iterates the full `ref_to_docs` for every pair. Quadratic in the number of refs. On a small wiki it's fine; on a 1000-page wiki it will start to hurt.

**Fix direction**
- Build `doc_to_refs: dict[str, set[str]]` once, then `shared = doc_to_refs[a] & doc_to_refs[b]`.

---

### P2-5. `WeeklyReviewService` mixes "outcomes" and "feedback events" in its summary

**Evidence**
- `src/agent_wiki/application/weekly_review.py:38`:
  ```python
  parts.append(f"{len(queue_items)} review_queue items, {len(outcomes)} feedback events")
  ```
- `src/agent_wiki/application/feedback.py:25-27` — `FeedbackService.record` writes feedback to `query_outcomes.jsonl`.
- `src/agent_wiki/application/query.py:159-166` — `QueryService.execute` also writes to `query_outcomes.jsonl`.

**Why P2**

Two unrelated concerns share one file. Feedback events and query outcomes have different schemas (`approved`, `missing_evidence`, `rewrite_targets` vs. `query`, `hit_count`, `actor_id`) and different writers. The weekly-review summary calls all of them "feedback events," which is wrong — `query_outcomes.jsonl` is dominated by query rows after maintenance starts running.

**Fix direction**
- Split: `feedback_events.jsonl` for `FeedbackService`, `query_outcomes.jsonl` for `QueryService`.
- Update `QualityReportService._query_metrics` and `FastFeedbackService` accordingly.

---

### P2-6. `feedback.py:34` rewrite-targets length-zero handling is fragile

**Evidence**
- `src/agent_wiki/application/feedback.py:34`:
  ```python
  "doc_id": data.rewrite_targets[0] if data.rewrite_targets else data.query_id,
  ```

**Why P2**

A `feedback_issue` queue item with `doc_id = query_id` is a category error: `query_id` is not a `doc_id`. Anything reading the queue and treating `doc_id` as a manifest key will fail to look up the entry. The workaround silently mislabels.

**Fix direction**
- Make `doc_id` optional on the queue item; populate `query_id` separately if available.

---

### P2-7. `Sync.push_view` reads target file twice on every page

**Evidence**
- `src/agent_wiki/application/sync.py:74-78`:
  ```python
  if target.exists():
      existing = adapter.read(str(target))
      adapter_metadata = existing.get("adapter_metadata", {})
      document["adapter_metadata"] = adapter_metadata
  adapter.write(str(target), document)
  ```

**Why P2**

For Obsidian adapter this means every push reads, parses YAML frontmatter, then immediately writes. Fine for now, but cumulative on large vaults. Worse, the read is unconditional — even when the workspace page itself contains frontmatter the user wants to push (which `PlainMarkdownAdapter.write` would just write directly). So Obsidian frontmatter in workspace pages is silently lost on push.

**Fix direction**
- Workspace pages should themselves carry frontmatter (or a dedicated metadata file), and the adapter should preserve workspace metadata on push, not external metadata.

---

### P2-8. Test coverage gaps

The suite is at 103 tests and exercises happy paths well, but several important paths are untested:

| Path | Evidence | Risk |
|---|---|---|
| MCP/REST identity resolution end-to-end | No test that a forged `actor_id` in the request body is overridden by session identity | P0-1 holes go unnoticed |
| `aw maintain` idempotency | `tests/test_maintenance.py:79-89` only tests no-signal idempotency; no test that running twice with signals doesn't double the queue | P0-3 |
| `ApprovalService.approve` gate enforcement | `tests/test_approvals.py` exercises happy path; no denial test | P0-4 |
| `SyncService` actor handling | `tests/test_sync.py` uses no actor at all | P0-5 |
| `CompileUpdateService.apply` doc_id validation | `tests/test_compile_apply.py` doesn't pass a path-traversal ID | P1-4 |
| Concurrent query writes | No test for parallel `query_hits.jsonl` / `query_outcomes.jsonl` | P1-3 |
| Cross-wiki query outcome aggregation | `tests/test_cross_wiki_query.py` likely covers happy path; no test for outcome correctness across wikis | P1-2 |
| CLI/REST run from non-repo CWD | Implicit assumption that CWD is repo | P0-2 |
| Manifest entry with missing `topic` | `propagation.py:32` writes topic; older entries without topic will trip `compile_suggest.py:22` (defaults to `""`) and pollute the empty-topic cluster bucket | Subtle bug |

---

### P2-9. `query.py:144` reads page file from `pages/{doc_id}.md` directly, bypassing `canonical_uri`

**Evidence**
- `src/agent_wiki/application/query.py:144`:
  ```python
  page_path = wiki_root / "pages" / f"{hits[0].doc_id}.md"
  ```

**Why P2**

`core/schema.md` §3.1 says path is not identity. Right now the L1 builder reconstructs the path from `doc_id`, which works as long as the convention `pages/{doc_id}.md` holds — but it duplicates what `canonical_uri` is for. If `canonical_uri` ever diverges (e.g. nested directories), L1 silently fails.

**Fix direction**
- Read `canonical_uri` from manifest, fallback to convention if missing.

---

### P2-10. `tokenizer.py` CJK regex range looks suspect

**Evidence**
- `src/agent_wiki/infrastructure/retrieval/tokenizer.py:6` — `_CJK = re.compile(r"[㐀-䶿一-鿿]+")`.

**Why P2**

This covers CJK Unified Ideographs Extension A (U+3400-U+4DBF) and the basic block (U+4E00-U+9FFF), but misses Extension B+ (U+20000-U+2A6DF and beyond). Most modern Chinese text is fine; rare or historical characters are not. Also, `len(segment) <= 2` (line 34) means single-char CJK terms are tokenized whole, which is a reasonable bigram heuristic for short tokens but can over-fragment in queries.

**Fix direction**
- Defer until you have a complaint or a bug report. Document the limitation.

---

### P2-11. `_VALID_TRANSITIONS` allows skipping states implicitly

**Evidence**
- `src/agent_wiki/infrastructure/runtime/review_queue.py:4-9` — only forward transitions defined; `archived` has no entry, so you can't transition out of `archived` (good), but also `transition()` returns False silently for unknown current states.

**Why P2**

Silent `False` return rather than raising on invalid transitions means callers must remember to check the boolean. Tests catch the happy path; nothing prevents `transition("rq-001", "open")` from quietly no-opping in production code.

**Fix direction**
- Raise `InvalidTransitionError` instead of returning `False`. Update tests accordingly.

---

### P2-12. `MCPServer.resolve_identity` claims session metadata wins, but uses `{**request, **session}`

**Evidence**
- `src/agent_wiki/transports/mcp/server.py:35-42`:
  ```python
  return IdentityResolver().resolve(
      IdentityContext(
          transport="mcp",
          metadata={**request_metadata, **session_metadata},
      )
  )
  ```

**Why P2**

The merge order is correct (`session_metadata` wins on key collision because it's last in `**`). But: if `request_metadata` carries an `actor_id` and `session_metadata` carries a different one, the request's `actor_id` is *fully overwritten*. Good. But if `request_metadata` carries `actor_id` and `session_metadata` carries `actor_type` (different keys), the merged dict keeps both. So a forged `actor_id` from the request slips through unless session also overrides `actor_id`.

**Fix direction**
- Whitelist what comes from `request_metadata`. The right pattern is to ignore request identity fields entirely and only use `session_metadata`.

---

## Architecture & Design Conformance

### What matches the design well
- **Layered structure.** `domain` / `application` / `infrastructure` / `bootstrap` / `transports` is clean. No infrastructure imports in domain, no transport imports in application. Verified by walking the imports.
- **Git-as-authority placeholder.** Workspace-first, manifest-as-surrogate is consistently applied.
- **Append-only logs.** `log.md`, `operation_log.jsonl`, `approval_log.jsonl`, `query_outcomes.jsonl`, `authority_log.jsonl`, `review_queue.jsonl` all append, no in-place rewrites except review_queue's `transition()` and manifest's `upsert()`.
- **Pydantic at boundaries.** `domain/models.py` covers most service IO. The few remaining `dict` returns (`MaintenanceService.run`, `QualityReportService.generate`, `MCPServer.invoke`) are the right ones to leave loose.

### What drifts from the design
- **Schema drift.** `core/schema.md` §4.3 lists `query_types`, `route_priority`, `load_policy`, `confidence`, `freshness_sla_days`, `access_policy`, `query_types not empty` as required manifest/frontmatter fields. None of these reach the manifest. `propagation.py:27-37` writes `wiki_id, doc_id, page_type, topic, canonical_uri, last_writer, problem_cluster` only. The rest are intentionally Phase 1 simplification, but the design doc should explicitly say so (it does in §14).
- **Schema vs. enum mismatch.** `core/schema.md` §4.3 says `sensitivity` must be in `{public, internal, confidential}`. The enum exists. The propagation writes `data.sensitivity` (any string). No validation. Pydantic would catch this for free if `CompileUpdateInput.sensitivity: Sensitivity | None`.
- **Dead `KnowledgeStore` and `RetrievalProvider` Protocols.** `domain/contracts.py:18-32` defines them but no class implements them. `RetrievalIndexRepository` does the retrieval but does not declare it implements `RetrievalProvider`. The Protocol contracts exist as documentation only. Either implement (use `@runtime_checkable` + assert in tests) or remove.
- **`AuthorityService.promote` writes `authority_log.jsonl` but never makes Git commits.** This is fine as Phase 1 stub, but the design says Git is authority. The current authority log does not satisfy that — it's just a workspace artifact. The design doc should reflect "Phase 1 stubs Git commits as authority_log.jsonl entries."

---

## Deployment readiness

| Question | Answer | Evidence |
|---|---|---|
| Can `aw serve` start a real server? | **No.** | `transports/cli/app.py:42-45` — `serve` only `typer.echo`s a string. |
| Can `aw query` be run from a user's project dir? | **No.** | Hardcoded fixture path (P0-2). |
| Does `aw maintain` produce stable output across runs? | **No.** | Re-enqueues every signal (P0-3). |
| Can a non-`claude-code` agent use the CLI? | **No.** | Hardcoded actor (P0-1). |
| Can the REST app run with a real registry? | **No.** | Hardcoded fixture path (P0-2). |
| Does the MCP server have a transport binding (stdio/HTTP)? | **No.** | `MCPServer` is a class with `invoke()`; no MCP wire protocol. |

---

## Recommended order of fixes

1. **P0-1 + P0-2 together.** Real identity resolution and real registry path resolution. These unlock everything else.
2. **P0-3.** Maintenance idempotency. One day of cron will produce a corrupt queue otherwise.
3. **P0-4.** Approval gate. Closes the worst governance hole.
4. **P0-5.** Sync actor + permission.
5. **P1-4.** Path-traversal validation in compile.
6. **P1-1.** Enum migration.
7. **P0-6 + P1-2.** Authority/cross-wiki cleanup.
8. **P1-3.** `query_id` instead of index counting.
9. The rest (P2) can wait for a quiet week.

---

## What this review didn't cover

- I didn't run a fuzzer on `doc_id`, paths, or query strings.
- I didn't measure performance on >100-page wikis.
- I didn't audit the test fixtures for completeness against `core/schema.md` §4.
- I didn't check what happens when `MANIFEST.jsonl` is corrupted mid-write.
- I didn't validate the YAML safety surface beyond confirming `safe_load`.

These are worth a follow-up pass once the P0/P1 list lands.

---

## Bottom line

The bones are good. The seams are real. The runtime composes. The closed loop runs.

What I'd be uncomfortable shipping right now is anything that *claims* governance enforcement: the P0 list above is what stands between "we have a permission system" and "we actually use it everywhere it matters." The P1 list is what stands between "Phase 1 functionally green" and "Phase 1 has earned its complexity."

Once P0-1 through P0-5 land, this becomes a deployable internal tool. Once the P1 list lands, it becomes a credible Phase 2 starting point.
