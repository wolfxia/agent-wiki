# wiki-schema.md — Agent-Agnostic Operation Contract

> This file is the **Schema Layer** — it defines HOW any agent should ingest, compile, route, lint, promote, and maintain the wiki.  
> It is NOT a directional manifesto. It is an **operation contract**.
>
> Status note: this contract remains the target operational model. The current `src/agent_wiki/` implementation only enforces a subset of this contract and is explicitly called out below as the **Phase 1 Implementation Profile (Current)**.

---

## 0. Scope and Role

This file constrains the following executors:
- `wiki-ingest` (any agent's ingest adapter)
- `wiki-query` (any agent's query adapter)
- `wiki-lint` (any agent's lint adapter)
- `dream-cycle` (scheduled maintenance)
- Human editors (before triggering automated maintenance)

It does NOT govern:
- domain-specific business logic
- vector store implementation details
- editor UI / plugin configuration

If `purpose.md` answers "what matters", then `wiki-schema.md` answers:
**"How should the system maintain these knowledge objects?"**

---

## 1. Core Philosophy

1. **Compile before retrieve** — organize upfront at ingest/compile time, not at query time.
2. **Raw immutable, compiled mutable** — raw is immutable原料; atom/synthesis/principle are maintainable artifacts.
3. **Skillified knowledge** — every knowledge object must carry routing semantics from creation, not retrofitted later.
4. **Prefer revise over create** — new material should revise existing compiled pages before creating new ones.
5. **Proof beats fluency** — no provenance-less fluent claims in the compiled truth zone.
6. **Rollback beats drift** — when runtime or compile chain is unstable, roll back to last stable state.
7. **Write = propagate** — a write is not complete until all downstream artifacts are updated (anti-island).

---

## 2. Page Taxonomy

### 2.1 raw
- Purpose: Original notes, learning output, external material excerpts
- Lifecycle: immutable
- Default write mode: append-only
- Default query role: `proof_only`
- Default `load_policy`: `proof_only`

### 2.2 atom
- Purpose: Converged knowledge for a single problem cluster
- Lifecycle: revisable, cognitive evolution timeline can be appended
- Default query role: `fact_lookup` / `concept_explain`
- Default `load_policy`: `section_then_page`

### 2.3 synthesis
- Purpose: Structured synthesis across problem clusters
- Lifecycle: rewritable, prefer revision
- Default query role: `trend_scan` / `compare_tradeoff` / `decision_support`
- Default `load_policy`: `full_page`

### 2.4 principle
- Purpose: Meta-principles, decision frameworks, cross-topic judgment rules
- Lifecycle: strict promotion / demotable
- Default query role: reasoning scaffold, should not be sole evidence source
- Default `load_policy`: `full_page`

### 2.5 Taxonomy Principles
- raw is never deleted.
- compiled pages must be traceable to raw.
- principle must link back to atom or synthesis.
- **Problem cluster** is the convergence unit, NOT topic name.

---

## 3. Canonical Identity Contract

1. Every page must have a stable `doc_id`.
2. Path is NOT identity; rename/move does not change `doc_id`.
3. Path changes should be recorded in `legacy_paths[]`.
4. `canonical_uri` points to the authoritative location in the workspace.
5. External store mirror paths do not participate in identity.
6. Retrieval units must reference `doc_id`, not path alone.

### Important current-state note

The current implementation still writes and reads pages as `pages/{doc_id}.md` in multiple services. That is a **Phase 1 implementation simplification**, not a change to the contract. The contract continues to treat path and identity as separate concerns.

---

## 4. Frontmatter and Manifest Contract

### 4.1 Full target common fields
All pages should eventually carry:
- `doc_id`
- `page_type`
- `topic`
- `problem_cluster`
- `query_types`
- `route_priority`
- `load_policy`
- `review_status`
- `confidence`
- `updated`
- `source_refs`
- `sensitivity`
- `access_policy`

### 4.2 Type-specific target fields

#### raw
- `evidence_strength`
- `superseded_by`
- `when_to_use`
- `compiled_into`
- `ingest_origin`

#### atom
- `solves`
- `applicable_when`
- `not_for`
- `depends_on`
- `source_coverage`
- `supports`

#### synthesis
- `answers`
- `preferred_for`
- `related_principles`
- `freshness_sla_days`
- `depends_on`
- `related_pages`

#### principle
- `principle_scope`
- `applies_to_topics`
- `use_for`
- `misuse_risks`
- `counterexamples`
- `promotion_basis`
- `review_required`

### 4.3 Field consistency rules
- `query_types` cannot be empty.
- `route_priority` must be in predefined enum.
- `load_policy` must match page type.
- `review_status` must not be missing.
- `source_refs` must point to existing source in manifest.
- `sensitivity` must be in a documented enum such as `public`, `internal`, `confidential`.
- `access_policy` must be present when page-level access differs from the wiki default.

---

## 5. Ingest and Compile Contract

### 5.1 Target ingest model
New source enters the system via Two-Step ingest:

#### Step 1: Analyze
Must answer:
1. Which `topic` does it belong to?
2. Which `problem_cluster`?
3. Which existing atom/synthesis is it related to?
4. Is it supplementing evidence, structure, or introducing new problems?
5. Does it conflict with existing claims?

#### Step 2: Decide
Only four options:
- `append_raw`
- `update_atom`
- `update_synthesis`
- `create_review_item`

#### Step 3: Record
Must update the following artifacts:
- `MANIFEST.jsonl`
- `retrieval_index.jsonl`
- configured retrieval provider indexes
- `log.md`
- `review_queue.jsonl` (if conflict/dispute)

### 5.2 Prohibited actions
- No writing raw content directly into principle truth zone.
- No creating synthesis without analysis when new source arrives.
- No writing compiled page without updating manifest.

### 5.3 Current implementation profile

Implemented today in `src/agent_wiki/`:
- `capture_raw` writes a raw page, manifest entry, retrieval card, and `log.md` entry.
- Invalid raw `doc_id` values fall back to `.agent-wiki/pending_manifest.jsonl`.
- `compile_update.analyze` currently uses simple `doc_id` / `problem_cluster` heuristics to decide create vs revise.
- `compile_update.apply` currently supports `atom` and `synthesis` writes, validates `allowed_page_types`, validates `source_refs`, and writes operation log entries.
- C-level principle writes currently use proposal + approval flow rather than direct compile.

Not yet implemented from the full contract:
- full evidence-chain analysis output
- route/gate planning artifacts from analyze
- deeper contradiction resolution logic
- manifest/frontmatter parity enforcement beyond the current simplified fields

---

## 6. Update vs Create Rules

### 6.1 Prefer revision when
- problem cluster already exists
- new source only supplements evidence
- new source strengthens existing conclusion
- new source only brings section-level increment

### 6.2 Create new atom when
- stable problem cluster appears within same topic
- similar to existing atom but not equivalent
- at least 2-3 raw sources can support it

### 6.3 Create new synthesis when
- cross-atom/problem-cluster integration needed
- problem has reached trend/comparison/decision level
- atom alone cannot fully answer high-level question

### 6.4 Promote to principle when
- has explanatory power in 2+ topics
- not overturned by existing evidence
- has clear applicability boundaries and counterexample
- preferably human-validated

### 6.5 Current implementation note

The current `CompileUpdateService.analyze()` only distinguishes create vs revise using `doc_id` and `problem_cluster`. That behavior should be treated as a baseline heuristic, not the final judgment matrix.

---

## 7. Contradiction and Provenance Rules

### 7.1 Provenance enum
- `extracted`
- `inferred`
- `ambiguous`

### 7.2 What must enter review queue
- new source clearly overturns existing compiled claim
- same concept has conflicting conclusions in different synthesis
- principle lacks supporting page backlinks
- same problem cluster has two mutually exclusive answers

### 7.3 Disputed rules
- `disputed` must include `dispute_reason`
- query hitting disputed page must include caveat in output
- disputed items cannot be promoted to principle before resolution

### 7.4 No-provenance prohibition
- claims without `source_refs` cannot enter compiled truth zone
- unverified insights can enter timeline but must be marked `inferred` or `ambiguous`

### Current implementation profile

Implemented today:
- `compile_update.apply` rejects compiled writes whose `source_refs` do not resolve to existing raw manifest entries, unless a shared-wiki approval path explicitly bypasses the raw-source requirement.
- `query` surfaces dispute caveats when manifest entries carry `review_status=disputed` and `dispute_reason`.

Not yet implemented:
- richer contradiction-state transitions
- dispute lifecycle management in queue workflow
- automatic contradiction discovery

---

## 8. Retrieval Contract

### 8.1 Query types
Six fixed types:
- `fact_lookup`
- `concept_explain`
- `trend_scan`
- `compare_tradeoff`
- `decision_support`
- `proof_trace`

### 8.2 Fixed retrieval pipeline
1. classify `query_type`
2. coarse retrieve through the configured retrieval provider over `retrieval_index`
3. aggregate by `wiki_id:doc_id`
4. load by `load_policy`
5. assemble layered context
6. answer + log outcome

### 8.2.1 Retrieval provider baseline
- Retrieval is provider-based, not vector-mandatory.
- Phase 1 default provider is lexical search over `retrieval_index.jsonl`.
- Vector retrieval is an optional enhancement provider and must not be required for minimum query capability.
- Provider outputs must use the same normalized retrieval hit shape and must reference `wiki_id:doc_id`.

### 8.3 Layered presentation
- **L1** Answer layer: directly usable answer entries
- **L2** Reasoning layer: why relevant, any disputes, which pages are dependencies
- **L3** Proof layer: original evidence, `source_refs`, raw snippet

### 8.4 Load budget
- first round: max 3 full-page compiled pages
- raw evidence: max 2 groups, unless `proof_trace`
- principle: cannot be sole context source

### 8.5 Dispute-aware rule
When hitting disputed page:
- output must indicate dispute
- reason field must be visible
- no strong conclusions without proof layer

### Current implementation profile

Implemented today in `src/agent_wiki/application/query.py`:
- heuristic query-type classification
- lexical retrieval over `retrieval_index.jsonl`
- optional pending truth-zone inclusion through `include_pending=True`
- simple hit sorting by lexical score and manifest-derived priority
- L1/L2/L3 result assembly
- cross-wiki aggregation through `CrossWikiQueryService`

Not yet implemented:
- explicit `load_policy` execution
- retrieval budgets
- vector-provider dispatch
- automatic query outcome logging during query execution

---

## 9. Review Queue Contract

### 9.1 Target queue item minimum fields
- `item_id`
- `wiki_id`
- `doc_id`
- `item_type`
- `status`
- `content_state`
- `priority`
- `reason`
- `created_at`
- `source_refs`
- `assigned_to`
- `resolved_by`
- `resolved_at`

### 9.2 Status flow
- `open` → `assigned` → `in_progress` → `resolved` → `archived`

### 9.3 Content state
`content_state` describes the knowledge claim state independently from queue workflow status:
- `stub`
- `ambiguous`
- `disputed`
- `resolved`
- `stale`
- `pending_gate_fix`

### 9.4 Item types
Common `item_type` values:
- `conflict`
- `missing_evidence`
- `pending_gate_fix`
- `signal_candidate`
- `feedback_issue`
- `principle_proposal`
- `dispute`

### Current implementation profile

The current implementation writes a **minimal** review queue shape only:
- `item_type`
- `doc_id`
- `reason`
- `status`

This is currently produced from:
- `src/agent_wiki/application/propagation.py`
- `src/agent_wiki/application/feedback.py`

This minimal shape should be treated as a **transitional Phase 1 simplification**, not the long-term queue contract. The richer queue contract remains the implementation target for serious multi-wiki governance, assignment, conflict handling, and review lifecycle tracking.

When the runtime adopts the richer queue shape, migration or compatibility handling will be required for older minimal JSONL entries.

---

## 10. Lifecycle and Promotion Rules

### Target lifecycle
- `raw` → `compiled` → `verified` → `disputed` / `stale` → `archived`

### Target stale rules
- stale is a computed derived property, not manual state
- computed via `last_referenced` and `freshness_sla_days`

### Target promotion rules
- raw → atom/synthesis: enter compiled coverage
- compiled → verified: route tests stable, evidence sufficient, disputes closed
- synthesis/atom → principle: meets transfer explanatory power conditions

### Current implementation note

The current runtime only implements a smoke-path principle proposal/approval flow. It does not yet implement the full promotion/demotion lifecycle semantics described above.

---

## 11. Lint Rules

### Target lint checks
Must eventually check:
1. frontmatter completeness
2. `doc_id` uniqueness
3. `source_refs` validity
4. `query_types` not empty
5. `load_policy` legality
6. `review_status` consistency with review_queue
7. dependency no broken chain
8. retrieval_index entries correspond to compiled pages
9. disputed has `dispute_reason`
10. `compiled_into / superseded_by` chain consistency

### 11.1 Data flow integrity checks (target)

| Check | Detects | On Failure |
|-------|---------|-----------|
| manifest doc_id ↔ actual files 1:1 | Page changed but index doesn't know | Alert + repair |
| vectors all have `doc_id` + unified `model` | Page changed but search can't find | Alert + mark `index_stale` |
| retrieval_index has cards for all compiled pages | Coarse search has no data source | Alert + trigger rebuild |
| No `index_stale` markers >24h | Index out of sync with pages | Alert + trigger rebuild |
| No `mirror_pending` markers >24h | External store out of sync | Alert + trigger sync |
| query_outcomes consumed within 7 days | Knowledge used but no feedback | Alert |
| External store ↔ workspace diff < 5% | Human edits not reflected | Alert + trigger reverse propagation |

### Current implementation profile

The current `LintService` in `src/agent_wiki/application/linting.py` checks only:
- every manifest entry has a `canonical_uri`
- every manifest `canonical_uri` points to an existing page
- every retrieval index entry has a matching manifest entry

This is a deliberately small Phase 1 baseline. The larger lint contract remains the target.

---

## 12. Logging and Audit

### Target logging
- `log.md` records ingest, revise, merge, promote, dispute, archive, notable query outcome
- `query_outcomes.jsonl` keeps append-only feedback/effect history
- approval operations write durable audit records

### Current implementation profile

Current runtime artifacts:
- `log.md` from propagation writes
- `operation_log.jsonl` from compile updates
- `approval_log.jsonl` from approvals
- `query_outcomes.jsonl` from feedback submission

The append-only principle still applies to these artifacts even though the runtime shape is currently minimal.

---

## 13. Human Override Rules

### Must have human confirmation
- principle promotion / demotion
- cross-topic large-scale merge
- disputed adjudication (high-impact conclusions)
- workspace ↔ external store conflict merge

### Can auto-execute
- raw ingest
- atom/synthesis timeline append
- retrieval view rebuild
- vector re-embedding
- review item creation
- lint and route test execution

### Current implementation note

The current code only implements a local proposal/approval smoke path for high-risk principle writes. Broader human-override routing remains a design target.

---

## 14. Phase 1 Implementation Profile (Current)

The current implementation baseline in `src/agent_wiki/` enforces the following subset of the contract:

### Implemented today
- registry-driven multi-wiki loading
- raw capture with committed and pending paths
- compile update for `atom` and `synthesis`
- lexical retrieval with L1/L2/L3 output
- dispute caveats during query
- pending truth-zone opt-in querying
- minimal manifest persistence
- minimal lint checks
- minimal sync file-copy modes
- feedback → review queue creation
- weekly review summary generation
- proposal/approval smoke path for principle writes
- shared wiki page-type restrictions
- cross-wiki query smoke behavior

### Not yet implemented from the full contract
- full frontmatter coverage
- full queue item schema
- MCP/REST transport parity
- gate engine with `max_gate` enforcement
- vector-provider routing
- adapter-driven reverse sync and gate-to-Git flow
- stale marker and mirror marker recovery
- rich contradiction workflow

---

*This file remains the operation contract. When the current implementation is smaller than the contract, the contract still describes the intended architecture and behavior boundary.*
