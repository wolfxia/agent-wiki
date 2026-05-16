# wiki-schema.md — Agent-Agnostic Operation Contract

> This file is the **Schema Layer** — it defines HOW any agent should ingest, compile, route, lint, promote, and maintain the wiki.
> It is NOT a directional manifesto. It is an **operation contract**.

---

## 0. Scope and Role

This file constrains the following executors:
- `wiki-ingest` (any agent's ingest adapter)
- `wiki-query` (any agent's query adapter)
- `wiki-lint` (any agent's lint adapter)
- `dream-cycle` (scheduled maintenance)
- Human editors (before triggering automated maintenance)

It does NOT govern:
- Domain-specific business logic
- Vector store implementation details
- Editor UI / plugin configuration

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
3. Path changes must be recorded in `legacy_paths[]`.
4. `canonical_uri` points to the authoritative location in the workspace.
5. External store mirror paths do not participate in identity.
6. Retrieval units must reference `doc_id`, not path alone.

### 3.1 Change Rules
- Rename: keep `doc_id`, update `canonical_uri`, old path → `legacy_paths[]`
- Merge: keep surviving page's `doc_id`, merged page gets `superseded_by`
- Split: original page downgraded to parent/archived, new pages get new `doc_id`

---

## 4. Frontmatter Contract

### 4.1 Common Fields (all pages must have)
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

### 4.2 raw-specific Fields
- `evidence_strength`
- `superseded_by`
- `when_to_use`
- `compiled_into`
- `ingest_origin`

### 4.3 atom-specific Fields
- `solves`
- `applicable_when`
- `not_for`
- `depends_on`
- `source_coverage`
- `supports`

### 4.4 synthesis-specific Fields
- `answers`
- `preferred_for`
- `related_principles`
- `freshness_sla_days`
- `depends_on`
- `related_pages`

### 4.5 principle-specific Fields
- `principle_scope`
- `applies_to_topics`
- `use_for`
- `misuse_risks`
- `counterexamples`
- `promotion_basis`
- `review_required`

### 4.6 Field Consistency Rules
- `query_types` cannot be empty.
- `route_priority` must be in predefined enum.
- `load_policy` must match page_type.
- `review_status` must not be missing.
- `source_refs` must point to existing source in manifest.

---

## 5. Ingest Contract

New source enters the system via Two-Step ingest:

### Step 1: Analyze
Must answer:
1. Which `topic` does it belong to?
2. Which `problem_cluster`?
3. Which existing atom/synthesis is it related to?
4. Is it supplementing evidence, structure, or introducing new problems?
5. Does it conflict with existing claims?

### Step 2: Decide
Only four options:
- `append_raw`
- `update_atom`
- `update_synthesis`
- `create_review_item`

### Step 3: Record
Must update the following artifacts:
- `MANIFEST.jsonl`
- `retrieval_index.jsonl`
- configured retrieval provider indexes (Phase 1 default: lexical index; optional: local vector index)
- `log.md`
- `review_queue.jsonl` (if conflict/dispute)

### 5.1 Prohibited Actions
- No writing raw content directly into principle truth zone.
- No creating synthesis without analysis when new source arrives.
- No writing compiled page without updating manifest.

---

## 6. Update vs Create Rules

### 6.1 Prefer Revision When
- Problem cluster already exists
- New source only supplements evidence
- New source strengthens existing conclusion
- New source only brings section-level increment

### 6.2 Create New atom When
- Stable problem cluster appears within same topic
- Similar to existing atom but not equivalent
- At least 2-3 raw sources can support it

### 6.3 Create New synthesis When
- Cross-atom/problem-cluster integration needed
- Problem has reached trend/comparison/decision level
- Atom alone cannot fully answer high-level question

### 6.4 Promote to principle When (ALL must hold)
- Has explanatory power in 2+ topics
- Not overturned by existing evidence
- Has clear applicability boundaries and counterexample
- Preferably human-validated

### 6.5 Judgment Matrix Principles
- "Same topic" ≠ "same problem cluster"
- "High similarity" ≠ "mergeable"
- "High frequency" ≠ "principle-worthy"

---

## 7. Contradiction and Provenance Rules

### 7.1 Provenance Enum
- `extracted`: Directly verifiable extraction from source
- `inferred`: Inductive inference from multiple sources
- `ambiguous`: Insufficient evidence or conflicting

### 7.2 What Must Enter Review Queue
- New source clearly overturns existing compiled claim
- Same concept has conflicting conclusions in different synthesis
- Principle lacks supporting page backlinks
- Same problem cluster has two mutually exclusive answers

### 7.3 Disputed Rules
- `disputed` must include `dispute_reason`
- Query hitting disputed page must include caveat in output
- Disputed items cannot be promoted to principle before resolution

### 7.4 No-Provenance Prohibition
- Claims without `source_refs` cannot enter compiled truth zone
- Unverified insights can enter timeline but must be marked `inferred` or `ambiguous`

---

## 8. Retrieval Contract

### 8.1 Query Types
Six fixed types:
- `fact_lookup`
- `concept_explain`
- `trend_scan`
- `compare_tradeoff`
- `decision_support`
- `proof_trace`

### 8.2 Fixed Retrieval Pipeline
1. classify `query_type`
2. coarse retrieve through the configured retrieval provider over `retrieval_index`
3. aggregate by `doc_id`
4. load by `load_policy`
5. assemble layered context
6. answer + log outcome

### 8.2.1 Retrieval Provider Baseline
- Retrieval is provider-based, not vector-mandatory.
- Phase 1 default provider is lexical search over `retrieval_index.jsonl`.
- Vector retrieval is an optional enhancement provider and must not be required for minimum query capability.
- Provider outputs must use the same normalized retrieval hit shape and must reference `wiki_id:doc_id`.

### 8.3 Layered Presentation
- **L1 Answer layer**: Directly usable answer entries
- **L2 Reasoning layer**: Why relevant, any disputes, which pages are dependencies
- **L3 Proof layer**: Original evidence, source_refs, raw snippet

### 8.4 Load Budget
- First round: max 3 full-page compiled pages
- Raw evidence: max 2 groups, unless `proof_trace`
- Principle: cannot be sole context source

### 8.5 Dispute-aware Rule
When hitting disputed page:
- Output must indicate dispute
- Reason field must be visible
- No strong conclusions without proof layer

---

## 9. Review Queue Contract

### 9.1 Queue Item Minimum Fields
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

### 9.2 Status Flow
- `open` → `assigned` → `in_progress` → `resolved` → `archived`

### 9.3 Content State
`content_state` describes the knowledge claim state independently from queue workflow status:
- `stub`
- `ambiguous`
- `disputed`
- `resolved`
- `stale`
- `pending_gate_fix`

Dispute handling is represented as `item_type=dispute` plus the appropriate `content_state`; it is not the global queue status machine.

### 9.4 Item Types
Common `item_type` values:
- `conflict`
- `missing_evidence`
- `pending_gate_fix`
- `signal_candidate`
- `feedback_issue`
- `principle_proposal`
- `dispute`

### 9.5 Close Rules
- Only close when evidence is complete or conflict is adjudicated
- Principle-related disputed close should include human confirmation

### 9.6 Reopen Rules
- Auto-reopen when new source overturns resolved conclusion
- Can reopen when stale page is highly hit by new queries

---

## 10. Lifecycle and Promotion Rules

### 10.1 Page Lifecycle
- `raw` → `compiled` → `verified` → `disputed` / `stale` → `archived`

### 10.2 Stale Rules
- Stale is a **computed derived property**, not manual state
- Computed via `last_referenced` and `freshness_sla_days`

### 10.3 Promotion Rules
- raw → atom/synthesis: enter compiled coverage
- compiled → verified: route tests stable, evidence sufficient, disputes closed
- synthesis/atom → principle: meets transfer explanatory power conditions

### 10.4 Demotion Rules
- Principle with strong counterexample → demote to synthesis scaffold or disputed
- Verified page with conflict → demote to disputed

---

## 11. Lint Rules

Must check:
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

### 11.1 Data Flow Integrity Checks (Anti-Island)

| Check | Detects | On Failure |
|-------|---------|-----------|
| manifest doc_id ↔ actual files 1:1 | Page changed but index doesn't know | Alert + repair |
| vectors all have `doc_id` + unified `model` | Page changed but search can't find | Alert + mark `index_stale` |
| retrieval_index has cards for all compiled pages | Coarse search has no data source | Alert + trigger rebuild |
| No `index_stale` markers >24h | Index out of sync with pages | Alert + trigger rebuild |
| No `mirror_pending` markers >24h | External store out of sync | Alert + trigger sync |
| query_outcomes consumed within 7 days | Knowledge used but no feedback | Alert |
| External store ↔ workspace diff < 5% | Human edits not reflected | Alert + trigger reverse propagation |

When lint fails:
- Block entry to next phase gate
- Block auto-publish to external store
- Data flow break items must be fixed before continuing

---

## 12. Logging and Audit

### 12.1 log.md Records
- ingest, revise, merge, promote, dispute, archive, notable query outcome

### 12.2 query_outcomes.jsonl Minimum Fields
- `query`, `query_type`, `hit_docs`, `used_sources`, `needed_external_search`, `approved`, `missing_evidence`, `rewrite_targets`, `timestamp`

### 12.3 Append-only Principle
- Query outcomes: append only, never rewrite history
- log.md: can archive but never rewrite historical events

---

## 13. Human Override Rules

### 13.1 Must Have Human Confirmation
- Principle promotion / demotion
- Cross-topic large-scale merge
- Disputed adjudication (high-impact conclusions)
- Workspace ↔ External store conflict merge

### 13.2 Can Auto-Execute
- Raw ingest
- Atom/synthesis timeline append
- Retrieval view rebuild
- Vector re-embedding
- Review item creation
- Lint and route test execution

### 13.3 Human Edit Backflow Rules
- Human edits in external store are treated as upstream changes
- Must pass lint before merging back to workspace
- If conflicts with compiled truth zone → enter review queue, no direct overwrite

---

## 14. Worked Examples

### Example 1: New raw note enters, updates existing atom
- New source belongs to `edge-ai-imaging`
- Analyze finds it belongs to `lcm-lora-engineering`
- Decision: `update_atom`
- Actions: raw saved, atom truth zone revised, timeline appended, retrieval_index cards rebuilt, log.md records one revise

### Example 2: New source overturns old synthesis claim
- New source conflicts with a claim in `synthesis/imaging-os.md`
- Decision: `create_review_item` + `update_synthesis`
- Actions: original claim marked `ambiguous` or `disputed`, review_queue item added, query hits auto-include caveat, log.md records dispute

### Example 3: Cross-topic insight promoted to principle
- "Constraint pre-positioning" has explanatory power in both imaging-os and ai-harness
- Recent query outcomes repeatedly link back to this insight
- Human confirms applicability boundaries and counterexamples
- Decision: promote to principle
- Actions: new principle page created, backlinks to related synthesis/atom, `promotion_basis` noted, added to route policy but cannot replace proof layer

---

*This file is an operation contract. If it conflicts with rules scattered in agent-specific skill prompts, this file takes precedence.*
