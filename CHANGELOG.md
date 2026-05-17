# Changelog

## [0.2.0] - 2025-05-17

### Added
- FTS5 full-text search with jieba CJK tokenization (`SQLiteFTSIndexProvider`, `.agent-wiki/retrieval.db`)
- `RetrievalRouter`: FTS5 primary with JSONL lexical fallback
- `StructuredIndexProvider` + `TopicIndexRepository` for topic-based routing
- `doc_id` normalization migration (`aw migrate --normalize-doc-ids`)
- Knowledge graph visualizer (`knowledge-graph.html`, sigma.js + ForceAtlas2)
- Obsidian push-view with category routing (`raw -> 00-收件箱`, `atom + learn -> 01-学习笔记`, `synthesis -> 02-行业洞察`, `graph -> 04-知识图谱`)
- Index consistency health checks (T10)
- Query ranking with debug scores, `page_type_boost`, `purpose_boost`, freshness (T11)
- REST API (`src/agent_wiki/transports/rest/app.py`)
- Multi-wiki registry support
- Query outcome logging (`query_outcomes.jsonl`, `query_hits.jsonl`)
- `max_gate` enforcement in `PermissionService`
- Identity metadata precedence fix for MCP/REST

### Fixed
- `capture_raw` MCP tool bug (parameter dict had `compile_update` fields)
- Obsidian frontmatter date serialization (yaml date -> isoformat string)
- `doc_id` case inconsistency (208 uppercase doc_ids, migration available)

### Changed
- Workspace = SSOT, Obsidian = display view (architecture decision)
- Test count: 235 passed
- Data: 1472 workspace pages, 383 indexed topics

### Known Limitations
- `pending_manifest` has 1689 rows / 808 unique doc_ids needing cleanup
- MANIFEST (1488) vs pages/index/FTS (1472) have 16-entry drift; run `aw maintain` to repair
- `access_policy` / transport-aware sensitivity filtering not yet implemented
- `aw approvals reject` is placeholder only

## v0.1.0 (2026-05-17) — Phase 1 Foundation: Single Wiki Closed Loop

### Core Features
- **Single wiki knowledge base**: 433 pages unified from 3 sources (84 Obsidian + 330 learning + 21 knowledge)
- **Structured retrieval**: Lexical baseline (topic + keyword) + topic_index routing
- **MCP server**: `wiki.query`, `wiki.capture_raw`, `wiki.compile_update`, `wiki.lint`, `wiki.sync`
- **CLI**: `aw query`, `aw capture-raw`, `aw maintain`, `aw lint`, `aw sync`, `aw weekly-review`
- **External views**: Obsidian adapter (read-write) + PlainMarkdown adapter × 2 (read-only)
- **Registry-based actor identity fallback**: MCP server resolves default actor from registry.yaml when env vars are missing
- **Fallback scripts**: `aw-ops-safe.sh` with retry + graceful degradation for cron resilience
- **Data integrity**: 433 MANIFEST entries / 433 retrieval_index / 433 topic_index / 0 lint issues

### Architecture Decisions
- `wiki_id:doc_id` composite identity for future multi-wiki support
- Authority/runtime separation: Markdown + MANIFEST = truth (Git), indices = projection (.agent-wiki/)
- Lexical retrieval as baseline, vector as pluggable enhancement
- Pull-view sync: external_views → pages/ with automatic MANIFEST/retrieval_index/topic_index update

### Fixed In v0.2.0
- Same-name file conflicts in pull-view fixed with `slug(relative_path)` plus migration

### Known Limitations
- `aw maintain` does not auto-clean MANIFEST orphan entries (pages/ file deleted but MANIFEST entry persists)
- No semantic/vector retrieval yet

Note: FTS5/jieba Chinese-aware tokenization, REST API support, and multi-wiki support were v0.1.0 limitations resolved in v0.2.0.

### Test Coverage
- 201 tests passing (identity, retrieval, MCP, sync, compile, lint, maintenance)
