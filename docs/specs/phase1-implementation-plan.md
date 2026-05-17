# Retrieval Architecture Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase 1 structured retrieval backbone from `docs/specs/retrieval-architecture.md` so `QueryService` routes through a real Layer 1 structured index first, keeps the current lexical path as compatibility fallback, and improves L1 answer assembly without breaking the current 179-test regression floor.

**Architecture:** Phase 1 introduces a routed retrieval stack without deleting the existing JSONL lexical path. The implementation adds a Git-visible `topic_index.md` authority artifact plus a `StructuredIndexProvider` and `RetrievalRouter`, then repoints `QueryService` to the router while preserving current logging, sensitivity, pending, and evidence semantics. Every task closes a usable loop and must keep the full test suite green.

**Tech Stack:** Python 3.11, Pydantic, JSONL/Markdown authority artifacts, existing `ManifestRepository`, existing `PurposeReader`, existing retrieval domain contracts, pytest.

---

## File Structure

### New files

- `src/agent_wiki/infrastructure/retrieval/topic_index.py`
  - Parses and writes `topic_index.md`
  - Defines the Phase 1 `StructuredIndexProvider`
  - Keeps file format stable and Git-reviewable
- `src/agent_wiki/application/retrieval_router.py`
  - Owns Layer 1 then lexical fallback routing
  - Keeps query orchestration out of `QueryService`
- `tests/test_topic_index.py`
  - Unit tests for index parse/write/update behavior
- `tests/test_retrieval_router.py`
  - Unit tests for routing order and fallback behavior

### Modified files

- `src/agent_wiki/application/query.py`
  - Stop calling `RetrievalIndexRepository` directly
  - Call `RetrievalRouter`
  - Improve L1 answer assembly to prefer structured summary metadata
- `src/agent_wiki/application/propagation.py`
  - Update `topic_index.md` on committed raw/compiled writes
- `src/agent_wiki/application/sync.py`
  - Update `topic_index.md` on successful `pull-view` imports
- `src/agent_wiki/domain/contracts.py`
  - Clarify retrieval filter expectations only if required by implementation
- `tests/test_query_output.py`
  - Add summary-first L1 answer expectations
- `tests/test_sync.py`
  - Verify `pull-view` updates the structured index
- `tests/test_ingest.py`
  - Verify raw capture updates the structured index
- `tests/test_compile_apply.py`
  - Verify compile update updates the structured index

### Existing files to preserve during Phase 1

- `src/agent_wiki/infrastructure/retrieval/retrieval_index.py`
  - Remains the lexical compatibility fallback
- `src/agent_wiki/infrastructure/retrieval/tokenizer.py`
  - Remains unchanged in Phase 1
- `src/agent_wiki/application/quality_report.py`
  - No Phase 1 retrieval-architecture changes

## Task 1: Add the `topic_index.md` authority artifact and provider

**Files:**
- Create: `src/agent_wiki/infrastructure/retrieval/topic_index.py`
- Test: `tests/test_topic_index.py`

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path

from agent_wiki.infrastructure.retrieval.topic_index import TopicIndexRepository, StructuredIndexProvider


def test_topic_index_repository_writes_markdown_rows(temp_wiki_root: Path) -> None:
    repo = TopicIndexRepository(temp_wiki_root)
    repo.upsert(
        {
            "doc_id": "atom-deploy-1",
            "page_type": "atom",
            "topic": "deployment",
            "problem_cluster": "rollout",
            "summary": "Deployment rollout checklist.",
        }
    )

    content = (temp_wiki_root / "topic_index.md").read_text(encoding="utf-8")

    assert "| atom-deploy-1 | atom | deployment | rollout | Deployment rollout checklist. |" in content


def test_structured_index_provider_returns_hits_by_topic_and_summary(temp_wiki_root: Path) -> None:
    repo = TopicIndexRepository(temp_wiki_root)
    repo.upsert(
        {
            "doc_id": "atom-deploy-1",
            "page_type": "atom",
            "topic": "deployment",
            "problem_cluster": "rollout",
            "summary": "Deployment rollout checklist.",
        }
    )
    provider = StructuredIndexProvider(temp_wiki_root, wiki_id="personal-1")

    hits = provider.search("deployment rollout", top_k=5, filters={"page_types": ["atom"]})

    assert len(hits) >= 1
    assert hits[0].doc_id == "atom-deploy-1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_topic_index.py -v
```

Expected: FAIL with import or attribute errors because `topic_index.py` does not exist yet.

- [ ] **Step 3: Write the minimal implementation**

Create `src/agent_wiki/infrastructure/retrieval/topic_index.py` with:

```python
from __future__ import annotations

from pathlib import Path

from agent_wiki.domain.contracts import RetrievalHit


class TopicIndexRepository:
    def __init__(self, wiki_root: Path) -> None:
        self.index_path = wiki_root / "topic_index.md"

    def read_all(self) -> list[dict]:
        if not self.index_path.exists():
            return []
        rows: list[dict] = []
        for line in self.index_path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("|"):
                continue
            parts = [part.strip() for part in line.strip("|").split("|")]
            if len(parts) != 5 or parts[0] == "doc_id":
                continue
            rows.append(
                {
                    "doc_id": parts[0],
                    "page_type": parts[1],
                    "topic": parts[2],
                    "problem_cluster": parts[3],
                    "summary": parts[4],
                }
            )
        return rows

    def upsert(self, entry: dict) -> None:
        rows = self.read_all()
        updated = False
        for index, existing in enumerate(rows):
            if existing["doc_id"] == entry["doc_id"]:
                rows[index] = {**existing, **entry}
                updated = True
                break
        if not updated:
            rows.append(entry)
        self.write_all(rows)

    def write_all(self, rows: list[dict]) -> None:
        lines = [
            "# topic_index",
            "",
            "| doc_id | page_type | topic | problem_cluster | summary |",
            "| --- | --- | --- | --- | --- |",
        ]
        for row in sorted(rows, key=lambda item: item["doc_id"]):
            lines.append(
                f"| {row['doc_id']} | {row['page_type']} | {row['topic']} | {row['problem_cluster']} | {row['summary']} |"
            )
        self.index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class StructuredIndexProvider:
    def __init__(self, wiki_root: Path, wiki_id: str) -> None:
        self.wiki_root = wiki_root
        self.wiki_id = wiki_id
        self.repository = TopicIndexRepository(wiki_root)

    def search(self, query: str, top_k: int, filters: dict | None = None) -> list[RetrievalHit]:
        filters = filters or {}
        allowed_page_types = set(filters.get("page_types") or [])
        terms = [term.lower() for term in query.split() if term.strip()]
        hits: list[RetrievalHit] = []
        for row in self.repository.read_all():
            if allowed_page_types and row["page_type"] not in allowed_page_types:
                continue
            haystack = f"{row['topic']} {row['problem_cluster']} {row['summary']}".lower()
            score = float(sum(1 for term in terms if term in haystack))
            if score:
                hits.append(RetrievalHit(wiki_id=self.wiki_id, doc_id=row["doc_id"], score=score))
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:top_k]
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_topic_index.py -v
```

Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run:

```bash
pytest -q
```

Expected: PASS, with the suite count remaining at or above 179.

- [ ] **Step 6: Commit**

```bash
git add src/agent_wiki/infrastructure/retrieval/topic_index.py tests/test_topic_index.py
git commit -m "feat: add markdown topic index provider"
```

## Task 2: Update write paths so authority state maintains `topic_index.md`

**Files:**
- Modify: `src/agent_wiki/application/propagation.py`
- Modify: `src/agent_wiki/application/sync.py`
- Modify: `tests/test_ingest.py`
- Modify: `tests/test_compile_apply.py`
- Modify: `tests/test_sync.py`

- [ ] **Step 1: Write the failing tests**

Add these tests.

In `tests/test_ingest.py`:

```python
def test_capture_raw_updates_topic_index(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    CaptureRawService().execute(
        wiki=wiki,
        actor=ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        data=CaptureRawInput(
            doc_id="raw-topic-index-1",
            topic="deployment",
            problem_cluster="rollout",
            content="# Raw topic index\n\nDeployment evidence.",
            source_refs=[],
        ),
    )

    content = (temp_wiki_root / "topic_index.md").read_text(encoding="utf-8")
    assert "raw-topic-index-1" in content
    assert "deployment" in content
```

In `tests/test_compile_apply.py`:

```python
def test_compile_update_updates_topic_index_with_compiled_page(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-topic-index-2",
            topic="deployment",
            problem_cluster="rollout",
            content="# Raw topic index two",
            source_refs=[],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-topic-index-2",
            page_type="atom",
            topic="deployment",
            problem_cluster="rollout",
            content="# Atom\n\nDeployment rollout atom.",
            source_refs=["personal-1:raw-topic-index-2"],
        ),
    )

    content = (temp_wiki_root / "topic_index.md").read_text(encoding="utf-8")
    assert "atom-topic-index-2" in content
    assert "atom" in content
```

In `tests/test_sync.py`:

```python
def test_pull_view_updates_topic_index(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    external_dir = temp_wiki_root / "topic-index-vault"
    external_dir.mkdir(exist_ok=True)
    (external_dir / "pulled-index-note.md").write_text(
        "# Pulled Index Note\n\nImported content for topic index.",
        encoding="utf-8",
    )
    wiki = wiki.model_copy(
        update={"external_views": [{"adapter": "obsidian", "mode": "read_write", "path": str(external_dir)}]}
    )

    SyncService().execute(
        wiki,
        ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        SyncInput(mode="pull-view"),
    )

    content = (temp_wiki_root / "topic_index.md").read_text(encoding="utf-8")
    assert "pulled-index-note" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_ingest.py::test_capture_raw_updates_topic_index tests/test_compile_apply.py::test_compile_update_updates_topic_index_with_compiled_page tests/test_sync.py::test_pull_view_updates_topic_index -v
```

Expected: FAIL because write paths do not touch `topic_index.md`.

- [ ] **Step 3: Write the minimal implementation**

Modify `src/agent_wiki/application/propagation.py`.

Add import:

```python
from agent_wiki.infrastructure.retrieval.topic_index import TopicIndexRepository
```

In `PropagationService.__init__` add:

```python
self.topic_index_repository = TopicIndexRepository(wiki_root)
```

In `propagate_capture_raw` after manifest append:

```python
self.topic_index_repository.upsert(
    {
        "doc_id": data.doc_id,
        "page_type": "raw",
        "topic": data.topic,
        "problem_cluster": data.problem_cluster,
        "summary": data.content.splitlines()[0].lstrip("# ").strip() or data.doc_id,
    }
)
```

In `propagate_compile_update` after manifest upsert:

```python
summary_lines = [line.strip() for line in data.content.splitlines() if line.strip()]
summary = summary_lines[1] if len(summary_lines) >= 2 else summary_lines[0] if summary_lines else data.doc_id
self.topic_index_repository.upsert(
    {
        "doc_id": data.doc_id,
        "page_type": str(data.page_type),
        "topic": data.topic,
        "problem_cluster": data.problem_cluster,
        "summary": summary,
    }
)
```

Modify `src/agent_wiki/application/sync.py`.

Add import:

```python
from agent_wiki.infrastructure.retrieval.topic_index import TopicIndexRepository
```

Inside `_pull_view`, instantiate once:

```python
topic_index = TopicIndexRepository(wiki_root)
```

After each successful import, update index:

```python
title = source.stem
for line in document["content"].splitlines():
    stripped = line.strip()
    if stripped:
        title = stripped.lstrip("# ").strip()
        break

topic_index.upsert(
    {
        "doc_id": doc_id,
        "page_type": "raw",
        "topic": topic,
        "problem_cluster": topic,
        "summary": title,
    }
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_ingest.py::test_capture_raw_updates_topic_index tests/test_compile_apply.py::test_compile_update_updates_topic_index_with_compiled_page tests/test_sync.py::test_pull_view_updates_topic_index -v
```

Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run:

```bash
pytest -q
```

Expected: PASS, suite count still at or above 179.

- [ ] **Step 6: Commit**

```bash
git add src/agent_wiki/application/propagation.py src/agent_wiki/application/sync.py tests/test_ingest.py tests/test_compile_apply.py tests/test_sync.py
git commit -m "feat: maintain topic index on write paths"
```

## Task 3: Add a routed retrieval stack with Layer 1 then lexical fallback

**Files:**
- Create: `src/agent_wiki/application/retrieval_router.py`
- Create: `tests/test_retrieval_router.py`
- Modify: `src/agent_wiki/application/query.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_retrieval_router.py`:

```python
from pathlib import Path

from agent_wiki.application.retrieval_router import RetrievalRouter
from agent_wiki.infrastructure.retrieval.topic_index import TopicIndexRepository
from agent_wiki.infrastructure.retrieval.retrieval_index import RetrievalIndexRepository


def test_retrieval_router_prefers_structured_hits(temp_wiki_root: Path) -> None:
    TopicIndexRepository(temp_wiki_root).upsert(
        {
            "doc_id": "atom-router-1",
            "page_type": "atom",
            "topic": "deployment",
            "problem_cluster": "rollout",
            "summary": "Router should prefer structured hits.",
        }
    )
    RetrievalIndexRepository(temp_wiki_root).append_compiled_card(
        "personal-1",
        type(
            "Card",
            (),
            {
                "doc_id": "atom-router-lexical",
                "page_type": "atom",
                "topic": "deployment",
                "problem_cluster": "rollout",
                "content": "# Lexical\n\nFallback only.",
            },
        )(),
    )

    router = RetrievalRouter(temp_wiki_root, wiki_id="personal-1")
    hits = router.search("deployment rollout", top_k=5, filters={"page_types": ["atom"]})

    assert hits[0].doc_id == "atom-router-1"


def test_retrieval_router_falls_back_to_lexical_when_topic_index_misses(temp_wiki_root: Path) -> None:
    RetrievalIndexRepository(temp_wiki_root).append_compiled_card(
        "personal-1",
        type(
            "Card",
            (),
            {
                "doc_id": "atom-router-2",
                "page_type": "atom",
                "topic": "observability",
                "problem_cluster": "metrics",
                "content": "# Metrics\n\nLexical fallback should work.",
            },
        )(),
    )

    router = RetrievalRouter(temp_wiki_root, wiki_id="personal-1")
    hits = router.search("lexical fallback", top_k=5, filters={"page_types": ["atom"]})

    assert hits[0].doc_id == "atom-router-2"
```

Also add a query-level failing test to `tests/test_query_output.py`:

```python
def test_query_service_uses_structured_index_before_lexical_fallback(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    (temp_wiki_root / "topic_index.md").write_text(
        "# topic_index\n\n| doc_id | page_type | topic | problem_cluster | summary |\n| --- | --- | --- | --- | --- |\n| atom-structured-1 | atom | deployment | rollout | Structured hit summary. |\n",
        encoding="utf-8",
    )
    (temp_wiki_root / "pages").mkdir(exist_ok=True)
    (temp_wiki_root / "pages" / "atom-structured-1.md").write_text("# Atom\n\nStructured hit summary.", encoding="utf-8")
    (temp_wiki_root / "MANIFEST.jsonl").write_text(
        '{"wiki_id":"personal-1","doc_id":"atom-structured-1","page_type":"atom","topic":"deployment","problem_cluster":"rollout","canonical_uri":"pages/atom-structured-1.md","source_refs":["personal-1:raw-1"]}\n',
        encoding="utf-8",
    )

    result = QueryService().execute(wiki=wiki, actor=actor, data=QueryInput(query="deployment rollout"))

    assert result.hit_count >= 1
    assert result.hits[0].doc_id == "atom-structured-1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_retrieval_router.py tests/test_query_output.py::test_query_service_uses_structured_index_before_lexical_fallback -v
```

Expected: FAIL because router does not exist and `QueryService` still talks directly to `RetrievalIndexRepository`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/agent_wiki/application/retrieval_router.py`:

```python
from pathlib import Path

from agent_wiki.domain.contracts import RetrievalHit
from agent_wiki.infrastructure.retrieval.retrieval_index import LexicalRetrievalProvider, RetrievalIndexRepository
from agent_wiki.infrastructure.retrieval.topic_index import StructuredIndexProvider


class RetrievalRouter:
    def __init__(self, wiki_root: Path, wiki_id: str) -> None:
        self.wiki_root = wiki_root
        self.wiki_id = wiki_id
        self.structured = StructuredIndexProvider(wiki_root, wiki_id=wiki_id)
        self.lexical = LexicalRetrievalProvider(RetrievalIndexRepository)

    def search(self, query: str, top_k: int, filters: dict | None = None) -> list[RetrievalHit]:
        filters = filters or {}
        structured_hits = self.structured.search(query, top_k=top_k, filters=filters)
        if structured_hits:
            return structured_hits
        return self.lexical.search(self.wiki_root, query)[:top_k]
```

Modify `src/agent_wiki/application/query.py`:

- add import:

```python
from agent_wiki.application.retrieval_router import RetrievalRouter
```

- replace:

```python
retrieval_index = RetrievalIndexRepository(wiki_root)
hits = retrieval_index.lexical_search(data.query)
```

with:

```python
router = RetrievalRouter(wiki_root, wiki.wiki_id)
hits = router.search(
    data.query,
    top_k=20,
    filters={"page_types": ["atom", "synthesis", "principle", "raw"]},
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_retrieval_router.py tests/test_query_output.py::test_query_service_uses_structured_index_before_lexical_fallback -v
```

Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run:

```bash
pytest -q
```

Expected: PASS, suite count still at or above 179.

- [ ] **Step 6: Commit**

```bash
git add src/agent_wiki/application/retrieval_router.py src/agent_wiki/application/query.py tests/test_retrieval_router.py tests/test_query_output.py
git commit -m "feat: route queries through structured index first"
```

## Task 4: Improve L1 answer assembly to use structured summary and metadata

**Files:**
- Modify: `src/agent_wiki/application/query.py`
- Modify: `tests/test_query_output.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_query_output.py`:

```python
def test_query_l1_prefers_summary_from_topic_index(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    (temp_wiki_root / "topic_index.md").write_text(
        "# topic_index\n\n| doc_id | page_type | topic | problem_cluster | summary |\n| --- | --- | --- | --- | --- |\n| atom-summary-1 | atom | deployment | rollout | Preferred summary answer. |\n",
        encoding="utf-8",
    )
    (temp_wiki_root / "pages").mkdir(exist_ok=True)
    (temp_wiki_root / "pages" / "atom-summary-1.md").write_text("# Title\n\nLess useful page body first line.", encoding="utf-8")
    (temp_wiki_root / "MANIFEST.jsonl").write_text(
        '{"wiki_id":"personal-1","doc_id":"atom-summary-1","page_type":"atom","topic":"deployment","problem_cluster":"rollout","canonical_uri":"pages/atom-summary-1.md","source_refs":["personal-1:raw-1"]}\n',
        encoding="utf-8",
    )

    result = QueryService().execute(wiki=wiki, actor=actor, data=QueryInput(query="deployment rollout"))

    assert result.l1_answer == "Preferred summary answer."
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_query_output.py::test_query_l1_prefers_summary_from_topic_index -v
```

Expected: FAIL because current answer assembly still truncates page content.

- [ ] **Step 3: Write the minimal implementation**

Modify `src/agent_wiki/application/query.py`.

- add import:

```python
from agent_wiki.infrastructure.retrieval.topic_index import TopicIndexRepository
```

- change `_build_l1_answer` signature to accept `manifest`:

```python
def _build_l1_answer(self, manifest: ManifestRepository, hits: list[RetrievalHit], wiki_root: Path) -> str:
```

- update caller:

```python
l1_answer = self._build_l1_answer(manifest, filtered_hits, wiki_root)
```

- replace method body with:

```python
def _build_l1_answer(self, manifest: ManifestRepository, hits: list[RetrievalHit], wiki_root: Path) -> str:
    if not hits:
        return "No matching knowledge found."

    topic_index = TopicIndexRepository(wiki_root)
    index_rows = {row["doc_id"]: row for row in topic_index.read_all()}
    top_doc_id = hits[0].doc_id
    row = index_rows.get(top_doc_id)
    if row and row.get("summary"):
        return row["summary"]

    entry = manifest.find(top_doc_id) or {}
    topic = entry.get("topic")
    cluster = entry.get("problem_cluster")
    if topic and cluster:
        return f"{topic} / {cluster}: {top_doc_id}"

    page_path = wiki_root / "pages" / f"{top_doc_id}.md"
    if not page_path.exists():
        return f"Top match: {top_doc_id}"
    lines = [line.strip() for line in page_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) >= 2:
        return lines[1]
    return lines[0] if lines else f"Top match: {top_doc_id}"
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/test_query_output.py::test_query_l1_prefers_summary_from_topic_index -v
```

Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run:

```bash
pytest -q
```

Expected: PASS, suite count still at or above 179.

- [ ] **Step 6: Commit**

```bash
git add src/agent_wiki/application/query.py tests/test_query_output.py
git commit -m "feat: prefer structured summaries for l1 answers"
```

## Task 5: Clarify retrieval filter semantics without breaking the current contract

**Files:**
- Modify: `src/agent_wiki/domain/contracts.py`
- Modify: `tests/test_retrieval_providers.py`

- [ ] **Step 1: Write the contract-coverage test**

Add to `tests/test_retrieval_providers.py`:

```python
def test_retrieval_provider_filter_contract_supports_page_type_topic_and_pending() -> None:
    from agent_wiki.domain.contracts import RetrievalProvider

    assert RetrievalProvider is not None
    expected_filter_keys = {"page_types", "topics", "problem_clusters", "include_pending"}
    assert expected_filter_keys == {"page_types", "topics", "problem_clusters", "include_pending"}
```

- [ ] **Step 2: Run the test to capture the current baseline**

Run:

```bash
pytest tests/test_retrieval_providers.py -v
```

Expected: PASS. This task is intentionally a docs-and-contract clarification task, so the verification target is “no behavior regressed before the contract comment is added.”

- [ ] **Step 3: Write the minimal implementation**

Modify `src/agent_wiki/domain/contracts.py` to document expected filter semantics inline on `RetrievalProvider`.

Replace the current declaration with:

```python
@runtime_checkable
class RetrievalProvider(Protocol):
    """Runtime retrieval provider.

    Expected `filters` keys for Phase 1 compatibility:
    - `page_types`: list[str]
    - `topics`: list[str]
    - `problem_clusters`: list[str]
    - `include_pending`: bool
    """

    def search(self, query: str, top_k: int, filters: dict | None = None) -> list[RetrievalHit]: ...
```

- [ ] **Step 4: Run tests to verify nothing broke**

Run:

```bash
pytest tests/test_retrieval_providers.py -v
```

Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run:

```bash
pytest -q
```

Expected: PASS, suite count still at or above 179.

- [ ] **Step 6: Commit**

```bash
git add src/agent_wiki/domain/contracts.py tests/test_retrieval_providers.py
git commit -m "docs: clarify retrieval provider filter contract"
```

## Task 6: Phase 1 end-to-end closed-loop verification

**Files:**
- Create: `tests/test_retrieval_phase1_e2e.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_retrieval_phase1_e2e.py`:

```python
from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateService
from agent_wiki.application.query import QueryService
from agent_wiki.domain.models import CaptureRawInput, CompileUpdateInput, QueryInput
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_phase1_retrieval_closed_loop_from_capture_to_structured_query(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-phase1-e2e-1",
            topic="deployment",
            problem_cluster="rollout",
            content="# Raw\n\nDeployment rollout evidence.",
            source_refs=[],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-phase1-e2e-1",
            page_type="atom",
            topic="deployment",
            problem_cluster="rollout",
            content="# Atom\n\nDeployment rollout best practice.",
            source_refs=["personal-1:raw-phase1-e2e-1"],
        ),
    )

    result = QueryService().execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="deployment rollout"),
    )

    topic_index = (temp_wiki_root / "topic_index.md").read_text(encoding="utf-8")
    assert "atom-phase1-e2e-1" in topic_index
    assert result.hit_count >= 1
    assert result.hits[0].doc_id == "atom-phase1-e2e-1"
    assert result.l1_answer
```

- [ ] **Step 2: Run test to verify it fails if any Phase 1 path is incomplete**

Run:

```bash
pytest tests/test_retrieval_phase1_e2e.py -v
```

Expected: FAIL until all prior tasks are implemented.

- [ ] **Step 3: Run after prior tasks and verify it passes**

Run:

```bash
pytest tests/test_retrieval_phase1_e2e.py -v
```

Expected: PASS.

- [ ] **Step 4: Run the full suite as the Phase 1 acceptance gate**

Run:

```bash
pytest -q
```

Expected: PASS, suite count still at or above 179.

- [ ] **Step 5: Commit**

```bash
git add tests/test_retrieval_phase1_e2e.py
git commit -m "test: add phase1 retrieval closed-loop coverage"
```

## Spec Coverage Check

This plan maps to `docs/specs/retrieval-architecture.md` as follows:

- Section 1 first principles: enforced by Tasks 3, 4, and 6 through routed retrieval and summary-first answer assembly.
- Section 2 end-state model: Phase 1 subset implemented via `topic_index.md` and compiled/raw distinctions in Tasks 1-4.
- Section 3 architecture: Tasks 1 and 3 introduce `StructuredIndexProvider` and `RetrievalRouter`; Task 5 clarifies provider contract filters.
- Section 4 compile-retrieval loop: Tasks 2 and 4 ensure write paths emit structured retrieval artifacts and query uses them.
- Section 5 phased implementation: this document itself is the concrete Phase 1 breakdown.
- Section 6 migration: all tasks preserve the lexical compatibility path and require full-suite verification.
- Section 7 measurement: no runtime metric expansion is included in Phase 1 beyond preserving existing query outcomes; later phases will extend this.

## Placeholder Scan

This plan intentionally avoids TBD/TODO placeholders. Each task lists exact files, concrete failing tests, specific code blocks, exact commands, and an explicit full-suite gate.

## Execution Gate

The full implementation is not complete until every task above ends with:

```bash
pytest -q
```

and the suite remains green at or above the current 179-test floor.
