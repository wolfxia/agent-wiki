# Enterprise Extensions Design

## Goal

Expose stable extension APIs so downstream packages such as `knowledge-agent` can depend on `agent-wiki` through pip without importing private transport or infrastructure internals.

## Scope

This design covers three public extension surfaces for v0.5.0:

- MCP tool registration for downstream tool namespaces such as `ka.ingest_document`.
- Runtime page type registration for governed custom types such as `document` and `slide_deck`.
- Embedding provider factory and provider registry for OpenAI-compatible, Azure OpenAI, SiliconFlow, and custom providers.

Entry point discovery, package auto-loading, new RBAC models, and semantic automation for custom page types are reserved for later releases.

## Public API

Create `agent_wiki.extensions` as the supported downstream import surface. It exposes:

- `MCPToolSpec` and `MCPToolContext` for custom MCP tools.
- `register_page_type()`, `get_page_type_registry()`, and `PageTypeDefinition` for page taxonomy extensions.
- `EmbeddingProvider`, `register_embedding_provider()`, and `create_embedding_provider()` for embedding providers.

Internal modules may use these APIs, but downstream packages should not import from `agent_wiki.transports.*` or `agent_wiki.infrastructure.*` unless explicitly documented.

## MCP Tool Registration

`build_fastmcp_server()` and `MCPServer` accept `extra_tools`. Each extra tool is an `MCPToolSpec` with a unique name, description, handler, and optional required operation/page type. The dispatcher resolves identity and wiki context before calling the handler. Handlers receive `MCPToolContext`, which includes the dispatcher, wiki config, resolved actor, params, and a `check_permission()` helper using the same permission path as built-in tools.

Existing `wiki.*` tools remain unchanged. Duplicate tool names are rejected early.

## Page Type Extensions

Page types are governed strings, not a closed enum at configuration boundaries. The four built-ins stay available as `PageType` enum values for backwards compatibility, and they are registered by default in the page type registry.

Custom types are registered at runtime with metadata: `name`, `default_gate`, `requires_source_refs`, and `truth_zone`. Registry loading, permission checks, lint, and compile update paths compare string values so custom types can pass through normal gates. Unknown page types in registry config are rejected unless registered first.

## Embedding Providers

Define an `EmbeddingProvider` Protocol with `embed_texts(texts: list[str]) -> list[list[float]]`. Provide built-in providers:

- `siliconflow`, preserving current behavior.
- `openai`, defaulting to `https://api.openai.com/v1`.
- `azure_openai`, using configured Azure endpoint and deployment path.

`create_embedding_provider(provider_type, config)` constructs providers from registry config. `RetrievalRouter` uses the factory instead of hardcoding SiliconFlow. Unknown provider types fail with a clear `ValueError` unless registered through `register_embedding_provider()`.

## Compatibility

Existing registry files with `raw`, `atom`, `synthesis`, and `principle` continue to parse. Existing SiliconFlow embedding config continues to work. Built-in MCP tool names, signatures, and structured responses stay compatible.

## Tests And Docs

Tests must cover custom MCP tool dispatch and permission access, custom page type registry/config/permission/lint compatibility, OpenAI embedding provider requests, embedding factory selection, and retrieval router provider selection. Documentation goes in `docs/extensions.md`, with a `knowledge-agent` style example.
