# Enterprise Extensions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build v0.5.0 public extension APIs for MCP tools, page types, and embedding providers.

**Architecture:** Add `agent_wiki.extensions` as the stable public surface. Keep transports thin by routing custom MCP tools through the existing dispatcher identity/wiki resolution path, convert page type config and permission checks to governed strings, and route embedding provider creation through a registry-backed factory.

**Tech Stack:** Python 3.11, Pydantic v2, FastMCP, pytest, httpx.

---

### Task 1: MCP Extension API

**Files:**
- Create: `src/agent_wiki/extensions/__init__.py`
- Create: `src/agent_wiki/extensions/mcp.py`
- Modify: `src/agent_wiki/transports/mcp/dispatcher.py`
- Modify: `src/agent_wiki/transports/mcp/server.py`
- Test: `tests/test_extensions_mcp.py`

- [ ] Write failing tests for custom MCP tool list/invoke and permission helper access.
- [ ] Run `pytest tests/test_extensions_mcp.py -v` and verify failure is due to missing extension API.
- [ ] Implement `MCPToolSpec`, `MCPToolContext`, dispatcher extra tool support, and `MCPServer`/`build_fastmcp_server` registration.
- [ ] Run `pytest tests/test_extensions_mcp.py tests/test_mcp_server.py -v`.

### Task 2: Page Type Registry

**Files:**
- Create: `src/agent_wiki/extensions/page_types.py`
- Modify: `src/agent_wiki/bootstrap/registry_loader.py`
- Modify: `src/agent_wiki/infrastructure/identity/permissions.py`
- Modify: `src/agent_wiki/infrastructure/identity/gates.py`
- Modify: `src/agent_wiki/application/compile_update.py`
- Modify: `src/agent_wiki/application/linting.py`
- Test: `tests/test_extensions_page_types.py`

- [ ] Write failing tests for registering `document`, loading it from registry config, permission checks, compile update, and lint compatibility.
- [ ] Run `pytest tests/test_extensions_page_types.py -v` and verify failure is due to enum-closed page type handling.
- [ ] Implement registry-backed page type definitions and string-based validation at config/permission/gate boundaries.
- [ ] Run `pytest tests/test_extensions_page_types.py tests/test_permissions.py tests/test_lint.py -v`.

### Task 3: Embedding Provider Factory

**Files:**
- Create: `src/agent_wiki/extensions/embedding.py`
- Modify: `src/agent_wiki/infrastructure/retrieval/embedding.py`
- Modify: `src/agent_wiki/application/retrieval_router.py`
- Test: `tests/test_extensions_embedding.py`
- Test: `tests/test_embedding_provider.py`

- [ ] Write failing tests for `EmbeddingProvider` Protocol availability, OpenAI request shape, factory selection, custom provider registration, and retrieval router use of the factory.
- [ ] Run `pytest tests/test_extensions_embedding.py -v` and verify failure is due to missing factory/API.
- [ ] Implement OpenAI-compatible provider classes, provider registry, factory, and router integration.
- [ ] Run `pytest tests/test_extensions_embedding.py tests/test_embedding_provider.py tests/test_retrieval_router.py -v`.

### Task 4: Docs, Version, Verification, Push

**Files:**
- Create: `docs/extensions.md`
- Modify: `README.md`
- Modify: `pyproject.toml`
- Modify: `src/agent_wiki/__init__.py`

- [ ] Document public API examples for `knowledge-agent` integration.
- [ ] Upgrade package/documented version to `0.5.0`.
- [ ] Run targeted tests and full pytest if feasible.
- [ ] Commit and push after fresh verification.
