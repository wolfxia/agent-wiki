# Retrieval Architecture Design

- Status: Approved for implementation planning
- Date: 2026-05-17
- Scope: End-state-first retrieval architecture for agent-wiki, with phased implementation boundaries that preserve a usable closed loop at every phase
- Baseline sources: `README.md`, `core/schema.md`, `docs/design.md`, `src/agent_wiki/domain/contracts.py`, `src/agent_wiki/application/query.py`, `src/agent_wiki/infrastructure/retrieval/*`

## 1. First Principles

### 1.1 What retrieval is for

Retrieval in agent-wiki is not "search documents".

It is the system that maps an agent question into the smallest set of trusted, reusable knowledge units needed to improve behavior.

In a compiled knowledge system, retrieval exists to:

- route questions toward compiled knowledge before raw material
- return knowledge units that can be acted on, not just text snippets that look similar
- preserve evidence traceability back to `source_refs` and raw pages
- expose gaps where compilation or source coverage is insufficient
- close the loop from question -> answer -> feedback -> compilation improvement

The retrieval problem is therefore not primarily string matching. It is controlled access to compiled knowledge under a Git-first authority model.

### 1.2 Closed loop from knowledge to behavior improvement

The required closed loop is:

```text
source capture
  -> compilation into atom/synthesis/principle units
  -> retrieval returns those compiled units for real queries
  -> operator or agent accepts/rejects usefulness
  -> misses and low-confidence results trigger compile/rewrite work
  -> knowledge structure improves
  -> future behavior improves
```

A retrieval layer that only returns top textual matches without gap signaling or evidence routing does not close the loop. It only performs search.

### 1.3 Core architectural principles

The retrieval architecture must preserve these principles:

1. Architecture is designed for the end state, implementation is phased.
2. Every phase must close the loop end-to-end. No phase ships as an inert partial stub.
3. Authority artifacts live in Git-visible, reviewable formats. Runtime acceleration artifacts live under `.agent-wiki/` and must be rebuildable.
4. Retrieval is layered routing, not one monolithic search function.
5. Compilation and retrieval are co-designed: compilation defines retrieval units; retrieval defines what compilation must emit.

## 2. End-State Model

### 2.1 Expected scale

The architecture must be valid for a personal multi-agent knowledge system at approximately:

- 500-5000 committed pages per wiki
- multiple wikis under one registry
- mixed page types with raw dominating volume and compiled pages dominating query value
- multi-source ingestion, not Obsidian-only

This scale target is architectural, not an immediate implementation target.

### 2.2 End-state page types

The retrieval system must treat page types differently.

Authority page classes:

- `raw`: captured source material, evidence layer, highest volume, lowest direct answer value
- `atom`: smallest reusable compiled knowledge unit, primary retrieval target for operational queries
- `synthesis`: topic-level compiled conclusions across multiple atoms/sources
- `principle`: higher-stability guidance or policy-level knowledge

Supporting structural artifacts:

- `topic_index.md`: curated per-wiki index of retrievable units and summaries
- manifest metadata (`MANIFEST.jsonl`)
- frontmatter and adapter metadata needed for routing and explainability
- optional cross-reference graph / wikilinks projection

### 2.3 End-state sources

The retrieval architecture must assume multiple source classes:

- Obsidian Vault content
- RSS or RSS-derived feeds such as `wewe-rss`
- local markdown/doc imports
- web captures and manual notes
- agent-generated proposals and compiled outputs

Retrieval must not assume that the source system defines the retrieval structure. Source systems feed capture and compile; compiled authority pages define the primary retrieval surface.

### 2.4 End-state query patterns

The architecture must support at least these query shapes:

- fact lookup: "What is X?"
- procedure recall: "How did we handle Y before?"
- evidence trace: "What sources justify this claim?"
- comparison: "How does A differ from B?"
- topic navigation: "What do we know about this topic cluster?"
- gap detection: "Why can we not answer this well yet?"
- semantic reformulation: different wording for the same operational concept

### 2.5 Five must-have retrieval capabilities at scale

The end-state system must provide these capabilities:

1. Structured candidate narrowing
   - The system must narrow candidate scope by `topic`, `problem_cluster`, `page_type`, `purpose.md`, and metadata before broad search.

2. Indexed lexical retrieval
   - The system must support non-linear full-text lookup with proper Chinese segmentation and deduplication. O(n) linear scan over all entries is not acceptable at scale.

3. Semantic recall
   - The system must recover meaning across wording variation. This may be provided by vector search, richer compile-time aliases/summaries, or both. Semantic recall is required; a specific implementation is not.

4. Evidence-preserving answer assembly
   - Returned answers must preserve `source_refs`, caveats, confidence/contested state, and page identity. Retrieval must support trust, not only relevance.

5. Gap signaling
   - Retrieval must surface misses, weak hits, and undercompiled clusters in a way that feeds the maintenance and compilation loops.

## 3. Architecture

### 3.1 End-state layered routing model

The retrieval architecture is defined as three layers coordinated by one router.

```text
QueryService
  -> QueryClassifier
  -> RetrievalRouter
     -> Layer 1 StructuredIndexProvider
     -> Layer 2 LexicalRetrievalProvider
     -> Layer 3 SemanticRetrievalProvider
  -> AnswerAssembler
  -> outcome logging / feedback loop
```

Layer intent:

- Layer 1: structure-first routing over curated catalog/index artifacts
- Layer 2: indexed lexical retrieval over compiled/runtime projections
- Layer 3: semantic fallback or enhancement when layers 1 and 2 miss or produce weak confidence

This is not three unrelated search backends. It is one routed retrieval stack.

### 3.2 Authority/runtime split

The architecture must explicitly separate authority artifacts from runtime acceleration artifacts.

Authority artifacts in Git:

- `pages/*.md`
- `MANIFEST.jsonl`
- `topic_index.md`
- frontmatter / summary / alias / confidence / contested metadata embedded in authority pages
- reviewable structural links such as `[[wikilinks]]` when enabled

Runtime artifacts under `.agent-wiki/`:

- SQLite FTS database
- vector store such as `.agent-wiki/vectors.db`
- graph projections and caches
- rebuildable derivative indexes

Rule:

- Runtime artifacts are projections, not sources of truth.
- If deleted, they must be reconstructable from authority artifacts.

### 3.3 Provider contracts

Current domain contracts already define:

- `RetrievalProvider`
- `EmbeddingProvider`
- `IndexProvider`

from `src/agent_wiki/domain/contracts.py`.

The end-state architecture keeps these abstractions but constrains their usage more clearly.

#### 3.3.1 Retrieval providers

Recommended provider shapes:

- `StructuredIndexProvider`
- `FTS5RetrievalProvider`
- `VectorRetrievalProvider`
- `ProgressiveRetrievalRouter`

Required behavior contract:

```python
class RetrievalProvider(Protocol):
    def search(self, query: str, top_k: int, filters: dict | None = None) -> list[RetrievalHit]: ...
```

Implementation rule:

- Providers may be instantiated per wiki/runtime context.
- `filters` must be used to carry at least `page_types`, `topics`, `problem_clusters`, `include_pending`, and route hints.
- `RetrievalHit` remains the common normalized output shape.

#### 3.3.2 Index providers

`IndexProvider` should represent runtime index mutation, not authority mutation.

```python
class IndexProvider(Protocol):
    def upsert(self, doc_id: str, payload: dict) -> None: ...
    def delete(self, doc_id: str) -> None: ...
```

Examples:

- FTS5 row upsert/delete
- vector row upsert/delete
- graph adjacency projection upsert/delete

Authority artifacts such as `topic_index.md` are not managed through `IndexProvider`; they are maintained through application/infrastructure services operating on Git-visible files.

#### 3.3.3 Embedding providers

`EmbeddingProvider` is reserved for Layer 3 and remains optional in Phase 1.

### 3.4 Query contract

The current `QueryInput` in `src/agent_wiki/domain/models.py` is too thin for the end state.

The end-state query contract must support:

- raw query text
- `include_pending`
- `max_sensitivity`
- requested retrieval mode or route hints
- allowed `page_types`
- topic narrowing hints
- evidence mode vs answer mode

Phase 1 may keep the current `QueryInput` shape, but query orchestration must be refactored so a richer contract can be introduced without rewriting the retrieval stack again.

### 3.5 Query routing rules

End-state routing must behave like this:

1. classify query intent
2. derive route hints from `purpose.md`, topic metadata, and query type
3. call Layer 1 structured index first
4. if Layer 1 returns high-confidence candidate pages, assemble answer from those candidates
5. if Layer 1 is empty or weak, call Layer 2 lexical retrieval
6. if Layer 2 is empty or weak, call Layer 3 semantic retrieval
7. assemble final answer with evidence, caveats, and confidence metadata
8. log the outcome for maintenance and quality measurement

Important rule:

- This is routed fallback, not unconditional multi-layer merge-and-rerank.
- Merge should be limited to bounded candidate supplementation, not global blended ranking across all providers.

### 3.6 Answer assembly

The current L1 answer in `src/agent_wiki/application/query.py` truncates the first non-empty line from the top page. This is not acceptable in the end state.

End-state answer assembly requires:

- summary-first L1 answer
- topic/problem-cluster framing
- caveat propagation (`disputed`, low confidence, pending state)
- L2 context as selected candidate metadata
- L3 proof as evidence references and source trace

The retrieval architecture therefore requires compile-time summary fields and review state metadata.

## 4. Compile-Retrieval Closed Loop

### 4.1 Relationship between compilation and retrieval

Compilation and retrieval are not separable stages.

They are co-designed:

- compilation defines the units retrieval can return
- retrieval defines the schema compiled units must emit

If compilation does not emit retrievable summaries and metadata, retrieval quality degrades no matter how strong the index is.

If retrieval does not target compiled units first, the system collapses back into a raw-note search engine.

### 4.2 Retrieval units

Primary retrieval units at scale:

- `atom`
- `synthesis`
- `principle`

Secondary retrieval units:

- `raw` for evidence trace and fallback

Rule:

- Retrieval should prefer compiled units by default.
- Raw pages remain queryable, but are not the primary answer surface for mature clusters.

### 4.3 Required compiled-page schema

Compiled pages must emit enough structure to support Layer 1 and strong Layer 2/3 retrieval.

Minimum required fields for `atom`, `synthesis`, and `principle` pages:

- `doc_id`
- `page_type`
- `topic`
- `problem_cluster`
- `summary`
- `source_refs`
- `review_status` / contested indicator
- `confidence` or equivalent reliability field
- optional `aliases`
- optional `wikilinks` / related-doc references
- optional `tags`

These fields may live in frontmatter, manifest fields, or a normalized compile artifact, but they must be authority-visible and consistently indexable.

### 4.4 Required raw-page schema

Raw pages must emit enough metadata to support backlog routing and evidence trace:

- `doc_id`
- `topic`
- `problem_cluster`
- source identity / capture provenance
- optional `vault_relative_path` for Obsidian-derived content
- optional adapter metadata for round-trip fidelity

### 4.5 Structured index requirements

`topic_index.md` must be buildable from authority state and must expose at least:

- `doc_id`
- `page_type`
- `topic`
- `problem_cluster`
- one-line summary
- optional confidence / contested marker

This file is not a convenience export. It is an authority-visible retrieval artifact.

## 5. Phased Implementation

Each phase must be usable as a complete loop, not an incomplete scaffold.

### 5.1 Phase 1: Structured retrieval backbone

Scope:

- introduce Layer 1 structured index as the primary retrieval architecture backbone
- keep current lexical retrieval as compatibility fallback
- improve answer assembly enough to stop first-line truncation from being the primary answer rule

Required implementation outcomes:

- add `topic_index.md` generation/update on `capture_raw`, `compile_update`, and `pull-view`
- introduce `StructuredIndexProvider`
- refactor `QueryService` to depend on routed retrieval orchestration rather than directly on `RetrievalIndexRepository`
- keep `retrieval_index.jsonl` functional so existing behavior and tests remain stable
- update L1 answer to prefer summary/topic/problem-cluster metadata over raw first-line truncation when available

Phase 1 closed loop:

```text
capture/compile/pull
  -> authority artifacts updated
  -> topic_index updated
  -> query consults structured index first
  -> answer/logging/feedback still work
```

No Phase 1 stub is allowed where `topic_index.md` exists but query does not use it.

### 5.2 Phase 2: Indexed lexical retrieval

Scope:

- replace linear scan as the main lexical path with a runtime FTS index
- replace bigram tokenization with proper Chinese segmentation
- keep structure-first routing from Phase 1

Required implementation outcomes:

- add SQLite FTS5 runtime index under `.agent-wiki/retrieval.db`
- add `FTS5RetrievalProvider`
- add tokenizer abstraction and a `jieba`-based implementation
- keep `retrieval_index.jsonl` only as fallback/debug/rebuild input during migration
- dedupe duplicate `doc_id` hits and preserve normalized `RetrievalHit`

Phase 2 closed loop:

```text
authority write
  -> structured index update
  -> FTS runtime index update/rebuild
  -> query uses Layer 1 then Layer 2
  -> misses and weak hits are measurable
```

### 5.3 Phase 3: Semantic enhancement

Scope:

- add semantic retrieval as optional plugin for miss recovery or weak-hit enhancement

Required implementation outcomes:

- add `VectorRetrievalProvider`
- add one local `EmbeddingProvider` implementation
- store vectors in `.agent-wiki/vectors.db`
- invoke Layer 3 only when Layer 1 and Layer 2 are empty or below confidence threshold

Phase 3 closed loop:

```text
compile emits summary/aliases/links
  -> runtime vector projection updated
  -> semantic fallback fires only on miss/weak hit
  -> accepted answers and misses inform compile quality
```

## 6. Migration from Current State

### 6.1 Current state

Current retrieval implementation characteristics:

- `src/agent_wiki/infrastructure/retrieval/tokenizer.py` uses Latin token extraction plus CJK bigrams
- `src/agent_wiki/infrastructure/retrieval/retrieval_index.py` performs JSONL-backed linear scan lexical search
- `src/agent_wiki/application/query.py` directly calls `RetrievalIndexRepository`
- L1 answer is derived from the first non-empty line of the top page

### 6.2 Migration rules

Migration must preserve existing behavior and keep the current regression floor stable. The current verified floor is 179 passing tests.

Rules:

1. Do not delete `retrieval_index.jsonl` in Phase 1.
2. Do not move business logic into transports.
3. Do not make runtime indexes authoritative.
4. Add the new routing layer behind compatibility wrappers first.
5. Every new runtime index must have a rebuild path from authority artifacts.

### 6.3 Recommended migration steps

1. Add retrieval router and Layer 1 provider without removing the current lexical code.
2. Make `QueryService` call the router.
3. Keep the current lexical repository as `LegacyLexicalProvider` behavior inside the router.
4. Add `topic_index.md` update paths on write operations.
5. Add summary-first answer assembly.
6. Introduce Phase 2 FTS provider only after Phase 1 routing is stable.

### 6.4 Expected file changes

Phase 1 target file changes:

- modify `src/agent_wiki/application/query.py`
- add `src/agent_wiki/application/retrieval_router.py`
- add `src/agent_wiki/infrastructure/retrieval/topic_index.py`
- optionally add `src/agent_wiki/infrastructure/retrieval/legacy_provider.py`
- modify `src/agent_wiki/application/propagation.py`
- modify `src/agent_wiki/application/sync.py`
- modify `src/agent_wiki/domain/contracts.py` only if filter semantics need clarification
- add tests for structured routing and answer assembly

Phase 2 target file changes:

- add `src/agent_wiki/infrastructure/retrieval/tokenizer_jieba.py`
- add `src/agent_wiki/infrastructure/retrieval/fts5_index.py`
- add `src/agent_wiki/infrastructure/retrieval/fts5_provider.py`
- modify router integration and write-side rebuild/update paths

Phase 3 target file changes:

- add `src/agent_wiki/infrastructure/retrieval/vector_provider.py`
- add embedding provider implementation under `src/agent_wiki/infrastructure/retrieval/`
- modify router fallback thresholds

## 7. Measurement

Measurement must be phase-specific and outcome-oriented.

### 7.1 Measurement principles

Do not treat process metrics as usefulness metrics.

Process metrics remain necessary for health monitoring, but usefulness must be measured through answer quality, reuse, and compile-improvement conversion.

### 7.2 Phase 1 metrics

Track at least:

- structured-route hit rate: fraction of queries satisfied by Layer 1
- answer accept rate: fraction of query answers accepted without immediate negative feedback
- query-to-page-read count: how many pages had to be read after index routing
- miss-to-compile conversion: how many misses lead to new atom/synthesis within a review window
- compiled coverage by cluster: fraction of active raw clusters with at least one compiled page

### 7.3 Phase 2 metrics

Track at least:

- lexical query latency p50/p95
- Layer 2 recovery rate after Layer 1 miss
- duplicate-hit suppression rate
- zero-hit repeat rate
- false-positive feedback rate for lexical hits

### 7.4 Phase 3 metrics

Track at least:

- semantic recovery rate after Layer 1+2 miss
- acceptance rate of semantic-only hits
- semantic fallback invocation rate
- vector index rebuild time
- drift rate between semantic hits and later negative feedback

### 7.5 Cross-phase outcome metrics

The end-state measurement set should include:

- answer accept rate
- answer reuse rate in downstream compile/update work
- time to trusted answer
- miss-to-compile conversion rate
- raw-to-compiled latency
- compiled cluster coverage
- stale-answer / negative-feedback rate
- repeated-miss rate by query intent family

These metrics are the real signal for whether retrieval is improving behavior rather than only improving internal mechanics.

## 8. Non-Negotiable Constraints

The implementation of this spec must preserve these constraints:

- design for the end state, implement in phases
- every phase must close the loop end-to-end
- authority remains Git-visible and rebuildable
- retrieval providers remain pluggable through shared contracts
- compile/retrieval schema must remain explicit and testable
- no phase may ship as a dead abstraction layer unused by the query path
