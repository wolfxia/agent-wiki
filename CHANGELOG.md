# Changelog

## v0.1.0 (2026-05-17) — Phase 1 Foundation: Single Wiki Closed Loop

### Core Features
- **Single wiki knowledge base**: 433 pages unified from 3 sources (84 Obsidian + 330 learning + 21 knowledge)
- **Structured retrieval**: Lexical baseline (topic + keyword) + topic_index routing
- **MCP server**: `wiki.query`, `wiki.capture_raw`, `wiki.compile_update`, `wiki.lint`, `wiki.sync`
- **CLI**: `aw query`, `aw capture_raw`, `aw maintain`, `aw lint`, `aw sync`, `aw weekly-review`
- **External views**: Obsidian adapter (read-write) + PlainMarkdown adapter × 2 (read-only)
- **Registry-based actor identity fallback**: MCP server resolves default actor from registry.yaml when env vars are missing
- **Fallback scripts**: `aw-ops-safe.sh` with retry + graceful degradation for cron resilience
- **Data integrity**: 433 MANIFEST entries / 433 retrieval_index / 433 topic_index / 0 lint issues

### Architecture Decisions
- `wiki_id:doc_id` composite identity for future multi-wiki support
- Authority/runtime separation: Markdown + MANIFEST = truth (Git), indices = projection (.agent-wiki/)
- Lexical retrieval as baseline, vector as pluggable enhancement
- Pull-view sync: external_views → pages/ with automatic MANIFEST/retrieval_index/topic_index update

### Known Limitations
- Same-name files across subdirectories get overwritten in pull-view (3 files affected: `2026-04-15_MCP协议.md`, `README.md`, `learn-2026-05-16-google-astra*`)
- `aw maintain` does not auto-clean MANIFEST orphan entries (pages/ file deleted but MANIFEST entry persists)
- No semantic/vector retrieval yet
- No FTS5/jieba Chinese-aware tokenization yet
- No multi-wiki support yet
- No REST API yet

### Test Coverage
- 201 tests passing (identity, retrieval, MCP, sync, compile, lint, maintenance)
