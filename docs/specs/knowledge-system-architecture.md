# Agent Wiki Knowledge System Architecture

- Status: Authoritative architecture spec for Step 1
- Date: 2026-05-17
- Supersedes: `docs/specs/retrieval-architecture.md`
- Scope: Unified end-state architecture for knowledge intake, compilation, retrieval, maintenance, and documentation discipline
- Baseline sources: `README.md`, `core/schema.md`, `docs/design.md`, `docs/requirements-and-architecture.md`, `src/agent_wiki/domain/contracts.py`, `src/agent_wiki/domain/models.py`, `src/agent_wiki/application/*`, `src/agent_wiki/infrastructure/*`

## 1. First Principles

### 1.1 What the system is for

Agent Wiki is not a document store and not a search wrapper.

It is a compiled knowledge system whose job is to turn source material into reusable knowledge units that improve future agent behavior.

The system exists to do four things reliably:

- ingest source material into authority-tracked raw evidence
- compile that evidence into reusable knowledge units
- retrieve the right compiled units for real work
- feed misses, weak answers, and conflicts back into maintenance and recompilation

If any one of those four breaks, the loop is broken.

### 1.2 The closed loop

The required end-state loop is:

```text
source ingestion
  -> raw authority intake
  -> metadata classification and repair
  -> compile into atom/synthesis/principle units
  -> retrieval for real agent queries
  -> feedback / misses / disputes / maintenance signals
  -> reclassification / recompilation / promotion
  -> better future behavior
```

This means compilation and retrieval are one architecture, not two features.

### 1.3 Non-negotiable system rules

1. Architecture is designed for the end state and implemented in phases.
2. Every phase must close the loop end-to-end. No inert stubs.
3. Compilation is the foundation. If intake is broken, everything above it is untrustworthy.
4. `pending` means failure or blocked promotion state, not “uncategorized but accepted.”
5. “Rough but continuous” beats “empty but pure.” Low-confidence metadata is allowed; null critical metadata is not.
6. Git-visible artifacts are authority. Runtime acceleration artifacts are rebuildable projections.

## 2. End-State Model

### 2.1 Scale target

The architecture must remain valid at approximately:

- 500-5000 committed pages per wiki
- multiple wikis under one registry
- mixed sources, not only Obsidian
- raw pages dominating volume
- compiled pages dominating answer value

### 2.2 Authority page classes

- `raw`: evidence units captured from source systems
- `atom`: smallest reusable compiled knowledge unit and default retrieval target
- `synthesis`: topic-level or cluster-level compiled conclusions across multiple atoms and raw sources
- `principle`: higher-stability guidance and high-risk governance knowledge

### 2.3 Supporting authority artifacts

- `MANIFEST.jsonl`: authority metadata ledger
- `topic_index.md`: Git-visible structured retrieval catalog
- page frontmatter / embedded metadata: retrieval, explainability, and round-trip fields
- `purpose.md`: topic guidance and routing hints
- review/audit artifacts: review queue, approval logs, operation logs, query outcomes

### 2.4 Runtime projection artifacts

Under `.agent-wiki/` only:

- FTS or alternate retrieval indexes
- vector stores such as `.agent-wiki/vectors.db`
- caches and graph projections
- pending state and stale markers

Rule: deleting runtime projections must never destroy authority state.

## 3. Unified Intake-Compile-Retrieve Architecture

### 3.1 End-state flow

```text
Source Adapter
  -> Raw Intake Pipeline
     -> Manifest authority raw entry
     -> Topic/problem-cluster classification
     -> Metadata repair / review queue if weak
  -> Compile Pipeline
     -> atom / synthesis / principle outputs
     -> topic_index.md + retrieval projections
  -> Query Pipeline
     -> QueryClassifier
     -> RetrievalRouter
        -> Layer 1 StructuredIndexProvider
        -> Layer 2 LexicalRetrievalProvider
        -> Layer 3 SemanticRetrievalProvider
     -> AnswerAssembler
  -> Feedback / Weekly Review / Maintenance
```

### 3.2 Why compilation and retrieval are co-designed

Compilation defines the units retrieval can return.

Retrieval defines the metadata compilation must emit.

If raw intake does not classify source material into usable authority raw entries, compile suggestion cannot form clusters.
If compiled pages do not emit summaries, aliases, confidence, and links, retrieval cannot produce useful L1 answers or structured routing.

## 4. Raw Intake Foundation

### 4.1 Source systems

All source systems must converge on one intake contract. Phase boundaries can change which adapters exist, but not the intake shape.

Expected sources:

- Obsidian Vault
- `capture_raw` direct submissions
- RSS / `wewe-rss`
- local markdown/doc imports
- web capture or manual notes

### 4.2 Intake contract

Every source enters the system as one normalized raw intake unit with at least:

- `doc_id`
- `source_type`
- `source_uri`
- `title`
- `content`
- `captured_at` or source timestamp when available
- `adapter_metadata`
- `frontmatter`
- optional caller-provided or adapter-provided metadata hints

Adapters read source systems. Intake decides authority metadata.

### 4.3 Raw authority contract

Every committed raw entry in `MANIFEST.jsonl` must include at least:

- `doc_id`
- `page_type=raw`
- `canonical_uri`
- `source_type`
- `source_uri`
- `title`
- `summary`
- `topic`
- `problem_cluster`
- `classification_method`
- `classification_confidence`
- `metadata_state`
- `last_writer`

Important rule:

- `topic`, `problem_cluster`, and `summary` must not be null for committed raw entries.
- low-confidence placeholders are acceptable
- null critical metadata is not acceptable

### 4.4 Metadata discipline

Allowed metadata states for raw entries:

- `classified`
- `low_confidence`
- `needs_review`
- `intake_failed`

`pending_manifest` is reserved for `intake_failed` or blocked promotion states only.

`needs_review` raw entries still belong in `MANIFEST.jsonl` if they are accepted as authority raw evidence.

### 4.5 Metadata sources and precedence

Preferred precedence for raw classification:

1. trusted explicit operator or transport-provided metadata
2. adapter-level metadata such as Obsidian frontmatter
3. path-derived or source-derived hints such as folder names, tags, or feed names
4. rule-based content inference
5. fallback low-confidence placeholder values

This preserves continuity without pretending certainty.

## 5. Compilation Foundation

### 5.1 Compilation units

Primary compiled retrieval units:

- `atom`
- `synthesis`
- `principle`

Raw pages remain evidence and fallback material, not the preferred answer surface for mature topics.

### 5.2 Required compiled-page schema

Every compiled authority page must provide at least:

- `doc_id`
- `page_type`
- `topic`
- `problem_cluster`
- `summary`
- `aliases`
- `source_refs`
- `confidence`
- `contested`
- `wikilinks`

Recommended additional fields:

- `review_status`
- `dispute_reason`
- `sensitivity`
- `updated_at`

### 5.3 Source reference rule

Truth-zone `source_refs` must resolve to authority-tracked raw pages using `wiki_id:doc_id`.

Do not relax this rule to accept `pending_manifest` sources. If compilation is blocked, fix intake or repair raw authority state.

### 5.4 Compile candidate formation

The compile backlog must represent more than “clusters with enough perfect metadata.”

The maintenance system must be able to identify:

- `ready_to_compile` raw clusters
- `needs_metadata_repair` raw clusters
- `undercompiled_cluster` situations where many raw sources exist but few compiled outputs exist
- `high_traffic_raw_only` topics where queries hit evidence but not compiled knowledge

## 6. Retrieval Architecture

### 6.1 Layered routing model

```text
QueryService
  -> QueryClassifier
  -> RetrievalRouter
     -> Layer 1 StructuredIndexProvider
     -> Layer 2 LexicalRetrievalProvider
     -> Layer 3 SemanticRetrievalProvider
  -> AnswerAssembler
  -> outcome logging
```

### 6.2 Layer responsibilities

- Layer 1: `topic_index.md` and other structured authority artifacts for routing and candidate narrowing
- Layer 2: indexed lexical retrieval over authority/runtime projections
- Layer 3: semantic fallback or enhancement when Layer 1 and Layer 2 are weak or empty

This is routed fallback, not unrestricted blended reranking.

### 6.3 Provider contracts

The end-state architecture uses existing contracts from `src/agent_wiki/domain/contracts.py`:

- `RetrievalProvider`
- `EmbeddingProvider`
- `IndexProvider`
- `QueryClassifier`

Required retrieval provider behavior:

```python
class RetrievalProvider(Protocol):
    def search(self, query: str, top_k: int, filters: dict | None = None) -> list[RetrievalHit]: ...
```

`filters` must be able to carry at least:

- `page_types`
- `topics`
- `problem_clusters`
- `include_pending`
- route hints from `purpose.md` or query classification

### 6.4 Query and answer contract

End-state query behavior requires:

- structure-first candidate narrowing
- summary-first L1 answers
- evidence-preserving L2/L3 layers
- caveat propagation for low confidence, disputed state, and pending state
- gap signaling when compilation or metadata quality is insufficient

## 7. Maintenance and Repair Loop

### 7.1 Repair is part of the architecture

Repair is not a migration-only concern.

Because source quality is uneven, the system must continuously detect and repair:

- raw entries with weak metadata
- clusters with insufficient compilation
- compiled pages with weak evidence or missing schema
- query misses that indicate classification or compilation gaps

### 7.2 Required maintenance signals

Maintenance must surface at least:

- zero-hit queries
- low-confidence raw classification backlog
- raw clusters with high accumulation and low compile coverage
- raw pages missing from compile suggestions
- atom pages not referenced by synthesis pages or graph relations
- compiled pages missing summary/aliases/source_refs
- contradictions, disputes, and stale reviewed content

### 7.3 Dream Cycle deep maintenance

Dream Cycle is the long-cycle maintenance pass that complements the fast compile and feedback loops.

```text
aw dream-cycle
  -> orphan_scan
  -> cross_reference
  -> synthesis_generate
  -> quality_review
```

`orphan_scan` reads `MANIFEST.jsonl`, `review_queue.jsonl`, and `knowledge_graph.jsonl` to report raw pages that are not in compile suggestions and atom pages that are not referenced by synthesis or graph relations. The report is runtime state under `.agent-wiki/dream_cycle_orphans.jsonl`.

`cross_reference` is deterministic. It extracts atom keywords from manifest fields, page frontmatter, titles, problem clusters, and graph relations, then emits candidate groups above a configured strength threshold.

`synthesis_generate` is the only LLM-eligible step. It writes synthesis pages through the shared propagation path after B-level permission validation, and its `source_refs` must resolve to existing atom pages in the current wiki.

`quality_review` scans atom and synthesis pages for missing frontmatter/schema, stale timestamps, broken source refs, and very short content, then writes `quality_review` tasks to `review_queue.jsonl`.

### 7.4 Historical repair strategy

When earlier imports created low-quality or pending-heavy raw state, the repair path is:

1. scan `pages/`, `MANIFEST.jsonl`, and `.agent-wiki/pending_manifest.jsonl`
2. recover adapter/frontmatter/path metadata where available
3. classify `topic`, `problem_cluster`, and `summary` with confidence labels
4. promote accepted raw entries into `MANIFEST.jsonl`
5. leave only true intake failures in `pending_manifest`
6. enqueue `metadata_repair` items for unresolved cases

## 8. Current Baseline vs Target Design

### 8.1 Current baseline reality

As of the current Phase 1 baseline:

- transport parity exists for MCP, CLI, and REST
- lexical retrieval exists through `retrieval_index.jsonl`
- `pull-view` can import content and preserve Obsidian frontmatter metadata in adapter metadata
- compile suggestion currently depends on raw manifest metadata quality
- `CompileUpdateInput` is narrower than the target compiled schema
- the current intake path does not yet guarantee non-null `topic/problem_cluster/summary` for every authority raw entry

### 8.2 Target design gap

The main architectural gap is not “better search.”

It is the absence of a fully reliable raw intake and metadata classification foundation that can continuously feed compilation and, through compilation, retrieval.

## 9. Documentation Alignment Discipline

### 9.1 Documentation authority boundaries

- `docs/specs/knowledge-system-architecture.md` is the authoritative end-state architecture spec.
- `docs/design.md` describes the architecture baseline and must separate current baseline from target design explicitly.
- `docs/requirements-and-architecture.md` summarizes requirements and phase boundaries and must distinguish target vs current.
- `README.md` describes the repository and current reality. It must not carry volatile claims that drift quickly.

### 9.2 Rules for preventing doc drift

1. Do not hardcode volatile values such as test counts in `README.md`.
2. Do not describe target behavior as implemented behavior without a clear label.
3. Every transport surface, tool count, and command claim should be testable from code.
4. Architecture docs must use explicit labels such as `Current baseline` and `Target design`.
5. When a runtime surface or contract changes, docs and tests must be updated in the same change.

### 9.3 Alignment tests

The repository should maintain tests for key externally visible claims, including:

- MCP tool count and names
- CLI workflow surface
- presence of the authoritative knowledge-system spec
- absence of hardcoded test-count marketing in `README.md`

## 10. Phase Boundaries

### Phase 1

Closed-loop requirement:

- usable authority raw intake
- compile-ready metadata discipline
- structured retrieval foundation design
- lexical baseline retained as the default runtime retrieval path
- maintenance able to detect metadata and compilation gaps

### Phase 2

- stronger index routing and richer compile schema enforcement
- improved compile candidate formation
- richer review queue lifecycle and governance behavior

### Phase 3

- optional semantic/vector enhancement
- broader production hardening and operations maturity

## 11. Supersession Note

`docs/specs/retrieval-architecture.md` remains useful historical context, but this document is now the authoritative spec for both compilation foundation and retrieval architecture.
