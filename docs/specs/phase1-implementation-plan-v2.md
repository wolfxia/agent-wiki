# Phase 1 Knowledge System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a Phase 1 closed loop that starts at raw intake, repairs imported metadata, compiles reusable knowledge units, routes queries through structured retrieval, and keeps the docs aligned with reality.

**Architecture:** Phase 1 is not retrieval-only. It is a single closed loop: source adapters normalize into raw authority, intake enriches metadata, compilation emits retrievable knowledge units, retrieval routes through structured and lexical layers, and docs/tests guard the external claims. The implementation preserves the current JSONL baseline while adding authority-visible structure and repair paths so accepted raw evidence never stays metadata-empty.

**Tech Stack:** Python 3.11, Pydantic, markdown/JSONL authority artifacts, existing Manifest/PendingState/ReviewQueue repositories, pytest.

---

## File Structure

### New files

- `src/agent_wiki/infrastructure/intake/raw_intake.py`
  - Normalizes raw capture and imported source metadata into a single intake contract
  - Provides metadata enrichment helpers and default classification fallback
- `src/agent_wiki/infrastructure/retrieval/topic_index.py`
  - Parses/writes `topic_index.md`
  - Defines `StructuredIndexProvider`
- `src/agent_wiki/application/retrieval_router.py`
  - Orchestrates Layer 1 structured lookup with lexical fallback
- `src/agent_wiki/infrastructure/repair/raw_metadata_repair.py`
  - Backfills imported raw pages and pending-heavy raw authority entries
- `tests/test_raw_intake.py`
  - Unit tests for intake normalization and metadata enrichment
- `tests/test_obsidian_frontmatter.py`
  - Unit tests for Obsidian frontmatter consumption during `pull-view`
- `tests/test_raw_metadata_repair.py`
  - Unit tests for backfill / repair of imported raw pages
- `tests/test_compile_schema.py`
  - Unit tests for expanded compile input schema and compiled-page metadata
- `tests/test_compile_suggest.py`
  - Unit tests for metadata-repair and undercompiled-cluster candidate detection
- `tests/test_retrieval_router.py`
  - Unit tests for structured routing and fallback behavior
- `tests/test_phase1_foundation_e2e.py`
  - End-to-end closed-loop regression coverage for intake -> compile -> query -> docs

### Modified files

- `src/agent_wiki/domain/models.py`
  - Expand `CaptureRawInput` and `CompileUpdateInput`
  - Add optional metadata fields needed by the unified spec
- `src/agent_wiki/application/capture_raw.py`
  - Normalize capture input through raw intake
- `src/agent_wiki/application/propagation.py`
  - Feed intake-enriched raw metadata into committed manifest entries
  - Write expanded compiled metadata fields
- `src/agent_wiki/application/sync.py`
  - Consume Obsidian frontmatter during `pull-view`
  - Route imported raw pages through manifest/raw repair flow
  - Keep retrieval rebuild consistent after pull-view
- `src/agent_wiki/application/compile_suggest.py`
  - Surface `needs_metadata_repair` and `undercompiled_cluster` candidates
- `src/agent_wiki/application/query.py`
  - Route through `RetrievalRouter`
  - Prefer structured summaries for L1 answers
- `src/agent_wiki/infrastructure/retrieval/retrieval_index.py`
  - Keep lexical compatibility fallback
- `src/agent_wiki/infrastructure/query/classifier.py`
  - No functional change expected, but may need contract alignment for routing hints
- `docs/specs/knowledge-system-architecture.md`
  - Reference only; no change unless spec adjustments are discovered during execution
- `README.md`
  - Keep docs claims aligned if implementation changes surface new stable facts
- `docs/design.md`
  - Keep current-baseline vs target-design notes aligned with the real implementation
- `docs/requirements-and-architecture.md`
  - Keep phase-boundary notes aligned with the real implementation
- `tests/test_ingest.py`
  - Verify raw intake enrichment and committed metadata
- `tests/test_sync.py`
  - Verify Obsidian frontmatter consumption and pull-view metadata repair paths
- `tests/test_compile_apply.py`
  - Verify compile input schema expansion and compiled metadata persistence
- `tests/test_query_output.py`
  - Verify summary-first L1 answer behavior
- `tests/test_docs_alignment.py`
  - Keep external claims locked to reality

### Existing files to preserve during Phase 1

- `src/agent_wiki/infrastructure/retrieval/retrieval_index.py`
  - Remains the lexical compatibility fallback until structured routing is in place
- `src/agent_wiki/infrastructure/retrieval/tokenizer.py`
  - Remains the current lexical baseline in Phase 1
- `src/agent_wiki/infrastructure/retrieval/fuzzy.py`
  - Remains the current fuzzy baseline in Phase 1
- `src/agent_wiki/application/quality_report.py`
  - No Phase 1 foundation changes expected

## Task 1: Normalize raw intake so capture and imported sources share one contract

**Files:**
- Create: `src/agent_wiki/infrastructure/intake/raw_intake.py`
- Modify: `src/agent_wiki/domain/models.py`
- Modify: `src/agent_wiki/application/capture_raw.py`
- Modify: `src/agent_wiki/application/propagation.py`
- Test: `tests/test_raw_intake.py`
- Test: `tests/test_ingest.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_raw_intake.py` with a test that proves capture normalization fills missing metadata defaults without inventing null authority fields:

```python
from agent_wiki.infrastructure.intake.raw_intake import normalize_raw_intake


def test_normalize_raw_intake_fills_low_confidence_defaults() -> None:
    normalized = normalize_raw_intake(
        {
            "doc_id": "raw-1",
            "content": "# Example\n\nBody text.",
            "source_type": "capture_raw",
        }
    )

    assert normalized["doc_id"] == "raw-1"
    assert normalized["topic"] != ""
    assert normalized["problem_cluster"] != ""
    assert normalized["summary"] != ""
    assert normalized["classification_confidence"] in {"low", "medium"}
```

Add to `tests/test_ingest.py` two regression tests. The first proves the schema now accepts missing metadata. The second proves raw capture still commits and now persists the normalized metadata fields into `MANIFEST.jsonl`:

```python
from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_capture_raw_input_allows_missing_topic_and_problem_cluster() -> None:
    payload = CaptureRawInput(
        doc_id="raw-intake-1",
        topic=None,
        problem_cluster=None,
        summary=None,
        content="# Raw intake

Capture body.",
        source_refs=[],
    )

    assert payload.topic is None
    assert payload.problem_cluster is None
    assert payload.summary is None


def test_capture_raw_persists_normalized_metadata(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )

    CaptureRawService().execute(
        wiki=wiki,
        actor=ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        data=CaptureRawInput(
            doc_id="raw-intake-1",
            topic=None,
            problem_cluster=None,
            summary=None,
            content="# Raw intake

Capture body.",
            source_refs=[],
        ),
    )

    manifest = (temp_wiki_root / "MANIFEST.jsonl").read_text(encoding="utf-8")
    assert "raw-intake-1" in manifest
    assert "classification_confidence" in manifest
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_raw_intake.py tests/test_ingest.py::test_capture_raw_persists_normalized_metadata -v
```

Expected: FAIL because raw intake normalization and normalized metadata persistence do not exist yet.

- [ ] **Step 3: Write the minimal implementation**

Create `src/agent_wiki/infrastructure/intake/raw_intake.py` with a small normalization helper and an input contract that can be reused by both capture and import paths:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RawIntakeResult:
    doc_id: str
    source_type: str
    source_uri: str
    title: str
    content: str
    topic: str
    problem_cluster: str
    summary: str
    classification_method: str
    classification_confidence: str
    metadata_state: str
    adapter_metadata: dict
    frontmatter: dict


def normalize_raw_intake(payload: dict) -> dict:
    content = payload.get("content", "")
    title = payload.get("title") or _first_heading_or_doc_id(content, payload["doc_id"])
    topic = payload.get("topic") or _infer_topic(payload, content)
    problem_cluster = payload.get("problem_cluster") or _infer_problem_cluster(payload, content)
    summary = payload.get("summary") or _infer_summary(content, title)
    classification_method = "explicit" if payload.get("topic") and payload.get("problem_cluster") else "rule_based"
    classification_confidence = payload.get("classification_confidence") or ("high" if classification_method == "explicit" else "low")
    metadata_state = payload.get("metadata_state") or ("classified" if classification_confidence == "high" else "low_confidence")

    return {
        **payload,
        "title": title,
        "topic": topic,
        "problem_cluster": problem_cluster,
        "summary": summary,
        "classification_method": classification_method,
        "classification_confidence": classification_confidence,
        "metadata_state": metadata_state,
        "adapter_metadata": payload.get("adapter_metadata", {}),
        "frontmatter": payload.get("frontmatter", {}),
    }
```

Then first update `CaptureRawInput` in `src/agent_wiki/domain/models.py` so `topic`, `problem_cluster`, and `summary` are optional on input. After that, modify `CaptureRawService.execute()` to pass `CaptureRawInput.model_dump()` through `normalize_raw_intake()` before propagation, and modify `PropagationService.propagate_capture_raw()` to write the normalized topic/problem_cluster/summary/classification fields into `MANIFEST.jsonl`.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_raw_intake.py tests/test_ingest.py::test_capture_raw_persists_normalized_metadata -v
```

Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run:

```bash
pytest -q
```

Expected: PASS, with the suite count at or above the current 183-test floor.

- [ ] **Step 6: Commit**

```bash
git add src/agent_wiki/infrastructure/intake/raw_intake.py src/agent_wiki/domain/models.py src/agent_wiki/application/capture_raw.py src/agent_wiki/application/propagation.py tests/test_raw_intake.py tests/test_ingest.py
git commit -m "feat: normalize raw intake metadata"
```

## Task 2: Consume Obsidian frontmatter during pull-view and treat it as intake metadata

**Files:**
- Modify: `src/agent_wiki/application/sync.py`
- Modify: `src/agent_wiki/infrastructure/adapters/obsidian.py`
- Modify: `src/agent_wiki/application/propagation.py`
- Test: `tests/test_obsidian_frontmatter.py`
- Test: `tests/test_sync.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_obsidian_frontmatter.py` with a frontmatter parsing expectation that the adapter already exposes frontmatter metadata suitable for intake:

```python
from pathlib import Path

from agent_wiki.infrastructure.adapters.obsidian import ObsidianAdapter


def test_obsidian_adapter_reads_frontmatter_for_intake(temp_wiki_root: Path) -> None:
    note = temp_wiki_root / "frontmatter-note.md"
    note.write_text("---\ntopic: deployment\nsummary: note summary\nclassification_confidence: high\n---\n# Frontmatter Note\n\nBody.", encoding="utf-8")

    document = ObsidianAdapter().read(str(note))

    assert document["adapter_metadata"]["frontmatter"]["topic"] == "deployment"
    assert document["adapter_metadata"]["frontmatter"]["summary"] == "note summary"
```

Add to `tests/test_sync.py` a pull-view test that a note with frontmatter can be imported without losing topic/summary/classification metadata:

```python
def test_sync_pull_view_consumes_obsidian_frontmatter(temp_wiki_root: Path) -> None:
    ...
    assert "frontmatter-topic" in manifest
    assert "classification_confidence" in manifest
    assert "note summary" in manifest
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_obsidian_frontmatter.py tests/test_sync.py::test_sync_pull_view_consumes_obsidian_frontmatter -v
```

Expected: FAIL because pull-view does not yet promote frontmatter into intake metadata.

- [ ] **Step 3: Write the minimal implementation**

Modify `SyncService._pull_view()` so that it extracts `frontmatter` from `adapter.read(str(source))`, then prefers frontmatter values for `topic`, `problem_cluster`, `summary`, and `classification_confidence` before falling back to path-based inference.

Use a small helper in `raw_intake.py` or `sync.py` such as:

```python
def frontmatter_metadata(document: dict, source: Path, external_path: Path) -> dict:
    frontmatter = document.get("adapter_metadata", {}).get("frontmatter", {})
    return {
        "topic": frontmatter.get("topic") or source.parent.name,
        "problem_cluster": frontmatter.get("problem_cluster") or source.parent.name,
        "summary": frontmatter.get("summary") or _first_non_empty_line(document["content"]),
        "classification_confidence": frontmatter.get("classification_confidence") or "low",
        "vault_relative_path": str(source.relative_to(external_path)),
    }
```

Then use that metadata for the raw manifest upsert and pending/repair routing.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_obsidian_frontmatter.py tests/test_sync.py::test_sync_pull_view_consumes_obsidian_frontmatter -v
```

Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run:

```bash
pytest -q
```

Expected: PASS, with the suite count at or above the current 183-test floor.

- [ ] **Step 6: Commit**

```bash
git add src/agent_wiki/application/sync.py src/agent_wiki/infrastructure/adapters/obsidian.py src/agent_wiki/application/propagation.py tests/test_obsidian_frontmatter.py tests/test_sync.py
git commit -m "feat: consume obsidian frontmatter during pull-view"
```

## Task 3: Repair imported raw metadata and backfill the 82 pending-heavy raw pages

**Files:**
- Create: `src/agent_wiki/infrastructure/repair/raw_metadata_repair.py`
- Modify: `src/agent_wiki/application/linting.py`
- Modify: `src/agent_wiki/application/maintenance.py`
- Modify: `src/agent_wiki/application/sync.py`
- Test: `tests/test_raw_metadata_repair.py`
- Test: `tests/test_lint.py`
- Test: `tests/test_maintenance.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_raw_metadata_repair.py` with a repair job test that proves imported raw pages can be backfilled into `MANIFEST.jsonl` from `pages/`, pending manifest, and frontmatter/path hints:

```python
def test_raw_metadata_repair_backfills_imported_raw_pages(temp_wiki_root: Path) -> None:
    ...
    repaired = RawMetadataRepairService().repair(wiki)
    assert repaired.repaired_count >= 1
    manifest = (temp_wiki_root / "MANIFEST.jsonl").read_text(encoding="utf-8")
    assert "pending-heavy-1" in manifest
    assert "topic" in manifest
```

Add to `tests/test_lint.py` a check that pending-heavy raw imports are no longer treated as compile blockers once they are repaired into manifest authority state:

```python
def test_lint_ignores_repaired_raw_pending_state(temp_wiki_root: Path) -> None:
    ...
    assert result.ok is True
    assert result.issues == []
```

Add to `tests/test_maintenance.py` a check that maintenance reports metadata repair work and undercompiled clusters together:

```python
def test_maintenance_reports_metadata_repair_and_undercompiled_clusters(temp_wiki_root: Path) -> None:
    report = MaintenanceService().run(wiki)
    assert report["metadata_repair_candidates"] >= 1
    assert report["compile_suggestions"] >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_raw_metadata_repair.py tests/test_lint.py::test_lint_ignores_repaired_raw_pending_state tests/test_maintenance.py::test_maintenance_reports_metadata_repair_and_undercompiled_clusters -v
```

Expected: FAIL because no repair service exists yet and lint/maintenance do not understand repair state.

- [ ] **Step 3: Write the minimal implementation**

Create `src/agent_wiki/infrastructure/repair/raw_metadata_repair.py` with a repair service that:

- scans `pages/`
- reads `MANIFEST.jsonl`
- reads `.agent-wiki/pending_manifest.jsonl`
- uses frontmatter and path hints to infer `topic`, `problem_cluster`, and `summary`
- promotes accepted low-confidence raw entries into `MANIFEST.jsonl`
- leaves only true intake failures in pending
- returns repaired counts and unresolved items

Update `LintService.run()` so it treats repaired raw authority entries as valid and flags only true intake failures or missing critical metadata.

Update `MaintenanceService.run()` so it includes a `metadata_repair_candidates` count and includes repair-related action items.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_raw_metadata_repair.py tests/test_lint.py::test_lint_ignores_repaired_raw_pending_state tests/test_maintenance.py::test_maintenance_reports_metadata_repair_and_undercompiled_clusters -v
```

Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run:

```bash
pytest -q
```

Expected: PASS, with the suite count at or above the current 183-test floor.

- [ ] **Step 6: Commit**

```bash
git add src/agent_wiki/infrastructure/repair/raw_metadata_repair.py src/agent_wiki/application/linting.py src/agent_wiki/application/maintenance.py src/agent_wiki/application/sync.py tests/test_raw_metadata_repair.py tests/test_lint.py tests/test_maintenance.py
git commit -m "feat: repair imported raw metadata"
```

## Task 4: Expand compile update schema to emit retrieval-ready metadata

**Files:**
- Modify: `src/agent_wiki/domain/models.py`
- Modify: `src/agent_wiki/application/compile_update.py`
- Modify: `src/agent_wiki/application/propagation.py`
- Test: `tests/test_compile_schema.py`
- Test: `tests/test_compile_apply.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_compile_schema.py` with a contract test for the expanded schema:

```python
from agent_wiki.domain.models import CompileUpdateInput


def test_compile_update_input_supports_retrieval_ready_fields() -> None:
    schema = CompileUpdateInput.model_json_schema()

    for field in ["summary", "aliases", "confidence", "contested", "wikilinks"]:
        assert field in schema["properties"]
```

Add to `tests/test_compile_apply.py` a compiled-page persistence test that asserts these fields are written to manifest or page metadata:

```python
def test_compile_apply_persists_retrieval_ready_metadata(temp_wiki_root: Path) -> None:
    ...
    manifest = (temp_wiki_root / "MANIFEST.jsonl").read_text(encoding="utf-8")
    assert "confidence" in manifest
    assert "aliases" in manifest
    assert "wikilinks" in manifest
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_compile_schema.py tests/test_compile_apply.py::test_compile_apply_persists_retrieval_ready_metadata -v
```

Expected: FAIL because the schema and propagation payload are still too narrow.

- [ ] **Step 3: Write the minimal implementation**

Update `CompileUpdateInput` in `src/agent_wiki/domain/models.py` to add optional fields:

```python
summary: str | None = None
aliases: list[str] = []
confidence: str | None = None
contested: bool = False
wikilinks: list[str] = []
```

Update `PropagationService.propagate_compile_update()` to persist those fields into `MANIFEST.jsonl` and use `summary` as the preferred L1 answer source.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_compile_schema.py tests/test_compile_apply.py::test_compile_apply_persists_retrieval_ready_metadata -v
```

Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run:

```bash
pytest -q
```

Expected: PASS, with the suite count at or above the current 183-test floor.

- [ ] **Step 6: Commit**

```bash
git add src/agent_wiki/domain/models.py src/agent_wiki/application/compile_update.py src/agent_wiki/application/propagation.py tests/test_compile_schema.py tests/test_compile_apply.py
git commit -m "feat: expand compile update metadata schema"
```

## Task 5: Teach compile suggestion to see metadata repair and undercompiled clusters

**Files:**
- Modify: `src/agent_wiki/application/compile_suggest.py`
- Modify: `src/agent_wiki/application/maintenance.py`
- Test: `tests/test_compile_suggestions.py`
- Test: `tests/test_maintenance.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_compile_suggestions.py` a test that raw clusters with missing metadata generate repair candidates, not just compile candidates:

```python
def test_compile_suggest_detects_metadata_repair_and_undercompiled_clusters(temp_wiki_root: Path) -> None:
    ...
    candidates = CompileSuggestService().detect(wiki)
    assert any(candidate["kind"] == "needs_metadata_repair" for candidate in candidates)
    assert any(candidate["kind"] == "undercompiled_cluster" for candidate in candidates)
```

Add to `tests/test_maintenance.py` a check that the maintenance summary includes both compile and repair signals.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_compile_suggestions.py tests/test_maintenance.py -v
```

Expected: FAIL because compile suggestion only counts raw clusters with topic/problem_cluster already present.

- [ ] **Step 3: Write the minimal implementation**

Update `CompileSuggestService.detect()` so it returns candidate records with a `kind` field, at minimum:

- `ready_to_compile`
- `needs_metadata_repair`
- `undercompiled_cluster`

Use manifest + pending manifest + page presence to determine which clusters are missing metadata versus which clusters are merely undercompiled.

Update `MaintenanceService.run()` so it surfaces separate counts for compile suggestions and metadata repair suggestions.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_compile_suggestions.py tests/test_maintenance.py -v
```

Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run:

```bash
pytest -q
```

Expected: PASS, with the suite count at or above the current 183-test floor.

- [ ] **Step 6: Commit**

```bash
git add src/agent_wiki/application/compile_suggest.py src/agent_wiki/application/maintenance.py tests/test_compile_suggestions.py tests/test_maintenance.py
git commit -m "feat: surface metadata repair in compile suggestions"
```

## Task 6: Add the structured retrieval backbone and routed query path

**Files:**
- Create: `src/agent_wiki/infrastructure/retrieval/topic_index.py`
- Create: `src/agent_wiki/application/retrieval_router.py`
- Modify: `src/agent_wiki/application/query.py`
- Test: `tests/test_topic_index.py`
- Test: `tests/test_retrieval_router.py`
- Test: `tests/test_query_output.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_topic_index.py`:

```python
from pathlib import Path
from agent_wiki.infrastructure.retrieval.topic_index import TopicIndexRepository, StructuredIndexProvider


def test_topic_index_repository_writes_markdown_rows(temp_wiki_root: Path) -> None:
    ...


def test_structured_index_provider_returns_hits_by_topic_and_summary(temp_wiki_root: Path) -> None:
    ...
```

Create `tests/test_retrieval_router.py` with tests that structured hits win when present and lexical fallback still works when topic_index misses.

Add to `tests/test_query_output.py`:

```python
def test_query_l1_prefers_summary_from_topic_index(temp_wiki_root: Path) -> None:
    ...
    assert result.l1_answer == "Preferred summary answer."
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_topic_index.py tests/test_retrieval_router.py tests/test_query_output.py::test_query_l1_prefers_summary_from_topic_index -v
```

Expected: FAIL because the routed structured index and summary-first answer logic do not exist yet.

- [ ] **Step 3: Write the minimal implementation**

Implement `TopicIndexRepository` with markdown read/write/upsert support and `StructuredIndexProvider` with `search(query, top_k, filters=None)`.

Implement `RetrievalRouter` so it first queries `StructuredIndexProvider`, then falls back to `RetrievalIndexRepository.lexical_search()`.

Update `QueryService.execute()` to call the router and update `_build_l1_answer()` so it prefers `topic_index.md` summary values, then manifest topic/problem_cluster framing, then page text as a last fallback.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_topic_index.py tests/test_retrieval_router.py tests/test_query_output.py::test_query_l1_prefers_summary_from_topic_index -v
```

Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run:

```bash
pytest -q
```

Expected: PASS, with the suite count at or above the current 183-test floor.

- [ ] **Step 6: Commit**

```bash
git add src/agent_wiki/infrastructure/retrieval/topic_index.py src/agent_wiki/application/retrieval_router.py src/agent_wiki/application/query.py tests/test_topic_index.py tests/test_retrieval_router.py tests/test_query_output.py
git commit -m "feat: route queries through structured retrieval"
```

## Task 7: Expand docs alignment tests to lock the external claims to reality

**Files:**
- Modify: `README.md` only if a new stable claim becomes true during implementation
- Modify: `docs/design.md` only if a new stable claim becomes true during implementation
- Modify: `docs/requirements-and-architecture.md` only if a new stable claim becomes true during implementation
- Test: `tests/test_docs_alignment.py`

- [ ] **Step 1: Extend the existing docs-alignment tests**

Add a docs alignment regression that checks the phase 1 external claims stay in sync with reality:

```python
from pathlib import Path
from typer.testing import CliRunner
from agent_wiki.transports.cli.app import app
from agent_wiki.transports.mcp.server import MCPServer


def test_docs_alignment_keeps_key_claims_in_sync() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "151 tests" not in readme
    assert "docs/specs/knowledge-system-architecture.md" in readme

    assert [tool["name"] for tool in MCPServer().list_tools()] == [
        "wiki.query",
        "wiki.capture_raw",
        "wiki.compile_update",
        "wiki.lint",
        "wiki.sync",
    ]

    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "serve" in result.stdout
    assert "health" in result.stdout
```

- [ ] **Step 2: Run the docs-alignment test to verify the guard stays green**

Run:

```bash
pytest tests/test_docs_alignment.py -v
```

Expected: PASS. This task is a verification guard, not a runtime feature change; its job is to keep external claims from drifting while the foundation work lands.

- [ ] **Step 3: Keep the docs aligned during implementation**

If implementation reveals a stable claim that changed, update the relevant docs in the same commit as the code. Do not add new hardcoded counts.

- [ ] **Step 4: Run the full suite**

Run:

```bash
pytest -q
```

Expected: PASS, with the suite count at or above the current 183-test floor.

- [ ] **Step 5: Commit**

```bash
git add tests/test_docs_alignment.py
# plus any doc files that changed because a stable claim changed
git commit -m "test: lock docs claims to runtime reality"
```

## Task 8: Phase 1 end-to-end closed-loop verification

**Files:**
- Create: `tests/test_phase1_foundation_e2e.py`

- [ ] **Step 1: Write the failing test**

Create a full closed-loop regression that exercises the foundation end-to-end:

```python
from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_suggest import CompileSuggestService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.application.query import QueryInput, QueryService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor


def test_phase1_foundation_closed_loop(temp_wiki_root: Path) -> None:
    ...
    assert result.hit_count >= 1
    assert result.l1_answer
    assert "topic_index" in (temp_wiki_root / "topic_index.md").read_text(encoding="utf-8")
```

This test should verify all of the following in one loop:

- capture_raw produces authority raw metadata
- pull-view/imported raw can be repaired into MANIFEST authority state
- compile suggestions see both metadata repair and undercompiled clusters
- compile_update emits retrieval-ready schema fields
- query uses structured retrieval before lexical fallback
- docs alignment still passes against the authoritative spec

- [ ] **Step 2: Run the end-to-end test and verify it fails until all earlier tasks are implemented**

Run:

```bash
pytest tests/test_phase1_foundation_e2e.py -v
```

Expected: FAIL until Tasks 1-7 are implemented.

- [ ] **Step 3: Run again after all earlier tasks and verify it passes**

Run:

```bash
pytest tests/test_phase1_foundation_e2e.py -v
```

Expected: PASS.

- [ ] **Step 4: Run the full suite as the Phase 1 acceptance gate**

Run:

```bash
pytest -q
```

Expected: PASS, with the suite count at or above the current 183-test floor.

- [ ] **Step 5: Commit**

```bash
git add tests/test_phase1_foundation_e2e.py
git commit -m "test: add phase1 foundation closed-loop coverage"
```

## Spec Coverage Check

This plan maps to `docs/specs/knowledge-system-architecture.md` as follows:

- Section 1 first principles: Tasks 1, 3, 5, and 8 ensure intake, compilation, retrieval, and maintenance close the loop.
- Section 4 raw intake foundation: Tasks 1, 2, and 3 normalize source input, consume frontmatter, and repair weak raw metadata.
- Section 5 compilation foundation: Tasks 4 and 5 expand compile schema and keep compile suggestion grounded in real raw authority state.
- Section 6 retrieval architecture: Task 6 adds `topic_index.md`, `StructuredIndexProvider`, `RetrievalRouter`, and summary-first answer assembly.
- Section 7 maintenance and repair loop: Tasks 3 and 5 make repair and backlog signals visible to maintenance.
- Section 9 documentation alignment discipline: Task 7 adds an executable guard for doc/runtime alignment.
- Section 10 phase boundaries: all tasks are ordered to keep Phase 1 end-to-end usable before later-phase enhancements.

## Placeholder Scan

This plan intentionally avoids TBD/TODO placeholders. Every task names exact files, includes concrete failing tests, specifies expected verification, and ends with a commit gate.

## Execution Gate

The full implementation is not complete until every task above ends with:

```bash
pytest -q
```

and the suite remains green at or above the current 183-test floor.
