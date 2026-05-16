# Agent-Wiki Architecture Design

> Universal Knowledge System for Multi-Agent Environments
> v1.0 — 2026-05-16

---

## 0. First Principles

**"Getting smarter" is not about accumulating more knowledge, but about improving behavior.**

In cybernetic terms: knowledge base is the controlled object, agent behavior is the output, feedback loop is the controller. Without feedback, no open-loop system gets "better" at anything regardless of internal complexity.

**Core question: Where is the closed loop from knowledge to behavior improvement?**

### Four Core Judgments

1. **Compile before retrieve** — Correct. But compiled products must be maintainable, traceable, reusable knowledge artifacts, not fancy summaries.
2. **Skillify is a design principle, not a post-hoc feature** — Knowledge must carry routing semantics from entry into the system.
3. **Hybrid retrieval is the calling skeleton, not an optimization** — Vectors for coarse screening, full-page reading for understanding, layered presentation for context cost control.
4. **Schema must be an operation contract, not a directional manifesto** — It must explicitly tell LLM/Agent: which pages to update on new source, what contradictions to mark, when to create vs revise.

---

## 1. Architecture

```
┌────────────────────────────────────────────────────────────┐
│              Behavior Improvement Layer (Closed Loop)       │
│ Query Outcome Loop: hit→effect→feedback→rewrite            │
│ log.md / corrections / principle promotion                 │
├────────────────────────────────────────────────────────────┤
│              Retrieval Runtime Layer                        │
│ query_profiles + wiki-query                                │
│ vector coarse → doc aggregate → full/section → layered     │
├────────────────────────────────────────────────────────────┤
│              Compile & Maintenance Layer                    │
│ raw / atom / synthesis / principle                         │
│ review_queue / provenance / timeline / confidence          │
├────────────────────────────────────────────────────────────┤
│              Contract & Index Layer                         │
│ wiki-schema.md / purpose.md / retrieval_index.jsonl        │
│ manifest / ontology schema / route tests                   │
├────────────────────────────────────────────────────────────┤
│              Storage Substrate Layer                        │
│ knowledge workspace → lint/validate → external mirror      │
│ unified vectors.db + unified MANIFEST + single write path  │
└────────────────────────────────────────────────────────────┘
```

---

## 2. Data Flow Integrity (Anti-Island)

**Design principle: Write = Propagate. A write is not complete until all downstream artifacts are updated.**

### 2.1 Diagnosed Breakage Points

| # | Break Point | Symptom | Island Consequence |
|---|-------------|---------|-------------------|
| F1 | Write page → no manifest update | manifest pages=[] for 77% of entries | Page changed but index doesn't know |
| F2 | Write page → no vector update | 53 metadata key shapes, 147/374 missing source | Page changed but search can't find |
| F3 | Write page → no retrieval_index update | retrieval_index doesn't exist | Coarse search has no data source |
| F4 | query_outcomes → no consumer | Doesn't exist | Knowledge used but no feedback |
| F5 | External edit → no backflow | sync is one-way push only | Human edits not reflected in agent |

### 2.2 Write Propagation Matrix

| Operation | manifest | vectors | retrieval_index | review_queue | log.md | mirror |
|-----------|----------|---------|-----------------|--------------|--------|--------|
| create raw | ✅ insert | ✅ embed | ✅ add snippet | — | ✅ append | ✅ push |
| create atom | ✅ insert | ✅ embed cards | ✅ add cards | — | ✅ append | ✅ push |
| update compiled | ✅ update hash | ✅ re-embed | ✅ rebuild cards | if conflict ✅ | ✅ append | ✅ push |
| mark disputed | ✅ update status | — | ✅ update dispute | ✅ insert | ✅ append | ✅ push |
| promote principle | ✅ insert | ✅ embed cards | ✅ add cards | ✅ insert | ✅ append | ✅ push |
| archive page | ✅ mark archived | ✅ mark stale | ✅ remove cards | — | ✅ append | ✅ archive |

### 2.3 Propagation Failure Handling

```
Step 1: Write page file → fail = abort, no cascade
Step 2: Update manifest → fail = rollback Step 1
Step 3: Update vectors → fail = mark "index_stale", don't rollback Step 1/2
Step 4: Update retrieval_index → fail = mark "index_stale"
Step 5: Update review_queue (if needed) → fail = log warning
Step 6: Write log.md → fail = stderr alert (log can't block main flow)
Step 7: Push mirror → fail = mark "mirror_pending"
```

**Key rules**:
- Step 1-2 must succeed atomically (page + manifest = identity foundation)
- Step 3-4 failure: no rollback, mark `index_stale`, lint fixes on next run
- Step 7 failure: no rollback, mark `mirror_pending`, sync retries next cycle
- Lint must check `index_stale` and `mirror_pending` markers

### 2.4 Reverse Propagation (External Store → Workspace)

```
External edit event (detected by sync adapter)
  ↓
Step 1: diff detect changed files
Step 2: lint changed content (frontmatter compliance)
Step 3: Pass → merge to workspace same path
        Fail → enter review_queue, no auto-overwrite workspace
Step 4: re-embed + update retrieval_index
Step 5: write log.md (record human edit backflow)
```

---

## 3. Phase Gate System

Each phase has: **Entry Gate** (prerequisites) + **Exit Gate** (acceptance) + **Rollback Strategy**.

### Phase A: Skillified Substrate (1-2 weeks)
- Goal: Freeze operation contract, build unified substrate
- Exit: schema complete + unified vectors + manifest has doc_id + skillify fields 100%
- Rollback: Revert to A Freeze Snapshot, keep old vectors read-only

### Phase B: Compiled Wiki (2-4 weeks)
- Goal: Compile high-frequency topics into reusable, routable artifacts
- Exit: compiled coverage + empty-hang rate <30% + route test ≥80% + dependency no break
- Rollback: Revert to A Stable, don't publish unqualified compiled pages

### Phase C: Hybrid Retrieval Runtime (4-8 weeks)
- Goal: Fixed query pipeline, agent no longer ad-hoc decides what to read
- Exit: 5 query types pass + avg steps <3 + route test ≥85% + dispute caveat
- Rollback: Revert to B Stable, use INDEX + compiled page manual priority

### Phase D: Evolution (8-16 weeks)
- Goal: Maintainable, incrementally upgradable, partially self-organizing
- Exit: stale discovery <7d + maintenance coverage >80% + compression >1:10
- Rollback: Revert to C Stable, disable graph/auto-promotion

**Gate rules: Cannot skip. Rollback on failure. Snapshot at every gate.**

---

## 4. Agent Adapter Architecture

### 4.1 Universal Interface

Every agent adapter must implement:

```python
class AgentAdapter(Protocol):
    @property
    def name(self) -> str: ...
    
    def install(self, wiki_root: str) -> None: ...
    def execute_query(self, query: str, query_type: str) -> str: ...
    def execute_ingest(self, source_path: str) -> str: ...
    def execute_lint(self) -> LintReport: ...
    def execute_sync(self, direction: str) -> SyncResult: ...
```

### 4.2 Storage Abstraction

```python
class KnowledgeStore(Protocol):
    def read_page(self, doc_id: str) -> Page: ...
    def write_page(self, page: Page) -> WriteResult: ...
    def search_vectors(self, query: str, top_k: int) -> list[SearchHit]: ...
    def get_manifest(self, doc_id: str) -> ManifestEntry: ...
    def update_manifest(self, entry: ManifestEntry) -> None: ...
```

### 4.3 Per-Agent Differences

| Dimension | Hermes | Claude Code | OpenClaw | OpenCode |
|-----------|--------|-------------|----------|----------|
| **Invocation** | Skill (SKILL.md) | CLAUDE.md instruction + Bash | Skill prompt | `opencode run` |
| **Scheduling** | cronjob (built-in) | External cron / launchd | cron (built-in) | External cron |
| **File Access** | terminal + file tools | Bash commands | Skill prompt | `opencode run` with -f |
| **Vector Search** | memory_search (built-in) | External (needs adapter) | External (needs adapter) | External (needs adapter) |
| **Human Interface** | Feishu/WeChat native | Terminal | Feishu native | Terminal |
| **Editor Sync** | Obsidian sync cron | None (code-focused) | Obsidian sync cron | None |
| **Knowledge Write Path** | ~/hermes-projects/knowledge/ | ~/workspace/code/ | ~/.openclaw/workspace/ | Project-scoped |
| **Config Format** | config.yaml | settings.local.json | agents/*.json | config.yaml |

---

## 5. Core Engine Implementation Notes

### 5.1 PropagationEngine

The anti-island core. Every write goes through this engine:

```python
class PropagationEngine:
    WRITE_PROPAGATION_MATRIX = {
        "create_raw": ["manifest", "vectors", "retrieval_index", "log", "mirror"],
        "create_atom": ["manifest", "vectors", "retrieval_index", "log", "mirror"],
        "update_compiled": ["manifest", "vectors", "retrieval_index", "review_queue?", "log", "mirror"],
        "mark_disputed": ["manifest", "retrieval_index", "review_queue", "log", "mirror"],
        "promote_principle": ["manifest", "vectors", "retrieval_index", "review_queue", "log", "mirror"],
        "archive_page": ["manifest", "vectors", "retrieval_index", "log", "mirror"],
    }
    
    def propagate(self, operation: str, doc_id: str, **kwargs) -> PropagationResult:
        # Step 1-2: atomic (page + manifest)
        # Step 3-4: resilient (mark stale on failure)
        # Step 5-6: best-effort
        # Step 7: async (mark pending on failure)
        ...
```

### 5.2 VectorStore

SQLite-based, agent-agnostic:

```python
class VectorStore:
    def __init__(self, db_path: str, model: str = "BAAI/bge-large-zh-v1.5"):
        ...
    
    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def search(self, query: str, top_k: int, filters: dict = None) -> list[SearchHit]: ...
    def upsert(self, doc_id: str, unit_id: str, text: str, metadata: dict): ...
    def delete(self, doc_id: str): ...
    def health_check(self) -> VectorHealthReport: ...
```

### 5.3 HybridRetriever

```python
class HybridRetriever:
    def retrieve(self, query: str, query_type: str, budget: int = 3) -> RetrievalResult:
        # 1. Classify query intent
        # 2. Vector coarse retrieval on retrieval_index
        # 3. Aggregate by doc_id
        # 4. Load by load_policy (full page or section)
        # 5. Assemble L1/L2/L3 context
        # 6. Return with dispute awareness
        ...
```

---

## 6. Risk Matrix

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| Phase A contract freeze不当, later rework | Medium | High | Validate full A→B chain on one topic first |
| Phase B compiled pages = summaries not artifacts | High | High | route test + dependency check dual constraint |
| Phase C coarse retrieve unstable | Medium | High | retrieval_index before ranking optimization |
| Disputed annotation under-reporting | Medium | High | review_queue + dispute-aware replay script |
| Phase D graph noise | Medium | Medium | Graph offline-only until gate passed |
| Data flow breakage (islands) | High | High | PropagationEngine + lint data flow checks |
| Multi-agent write conflicts | Medium | Medium | Lock by doc_id, review_queue on conflict |

---

*Design v1.0 complete. For execution and review.*
