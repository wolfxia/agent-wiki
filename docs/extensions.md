# Agent Wiki Extensions

Agent Wiki v0.5.0 exposes `agent_wiki.extensions` as the supported public API for downstream packages. Use this module when a project such as `knowledge-agent` depends on `agent-wiki` through pip and needs custom MCP tools, page types, or embedding providers.

Internal modules under `agent_wiki.transports`, `agent_wiki.application`, and `agent_wiki.infrastructure` remain implementation details unless a symbol is explicitly re-exported from `agent_wiki.extensions`.

## MCP Tools

Downstream code can register tools without replacing the built-in `wiki.*` surface. Custom handlers receive the same resolved wiki and actor context as built-in tools.

```python
from agent_wiki.extensions import MCPToolContext, MCPToolSpec
from agent_wiki.transports.mcp.server import build_fastmcp_server


def ingest_document(ctx: MCPToolContext) -> dict:
    decision = ctx.check_permission(operation="capture_raw", page_type="document")
    if not decision.allowed:
        raise PermissionError(decision.reason)
    return {
        "status": "accepted",
        "wiki_id": ctx.wiki.wiki_id,
        "actor_id": ctx.actor.actor_id,
        "doc_id": ctx.params["doc_id"],
    }


server = build_fastmcp_server(
    registry_path="/path/to/registry.yaml",
    extra_tools=[
        MCPToolSpec(
            name="ka.ingest_document",
            description="Ingest a knowledge-agent document",
            handler=ingest_document,
            required_operation="capture_raw",
            required_page_type="document",
        )
    ],
)
```

The dispatcher resolves identity from MCP metadata, environment, or registry fallback before calling the handler. Request payloads still cannot override actor identity.

## Page Types

The built-in page types remain `raw`, `atom`, `synthesis`, and `principle`. Register custom types before loading a registry that references them.

```python
from agent_wiki.extensions import register_page_type

register_page_type(
    "document",
    default_gate="B",
    requires_source_refs=True,
    truth_zone=True,
)
```

Then allow the type in the wiki and permission config:

```yaml
wikis:
  - wiki_id: enterprise
    allowed_page_types: [raw, atom, synthesis, principle, document]
    permissions:
      - actor_type: agent
        actor_id: knowledge-agent
        allowed_operations: [query, capture_raw, compile_update, lint, sync]
        max_gate: B
        allowed_page_types: [raw, document]
```

Permission checks, gate calculation, compile updates, and linting compare page types as governed strings. Unknown page types fail during registry loading.

## Embedding Providers

Agent Wiki includes `openai` and `azure_openai` providers in the core extension module. Other providers are enabled by registering a module from wiki configuration, an environment variable, or a package entry point. All providers implement the `EmbeddingProvider` Protocol:

```python
from agent_wiki.extensions import create_embedding_provider

provider = create_embedding_provider("openai", wiki.retrieval.embedding)
vectors = provider.embed_texts(["query text"])
```

OpenAI-compatible registry example:

```yaml
retrieval:
  coarse_provider: lexical
  optional_providers: [embedding]
  route_priority: 80
  embedding:
    provider: openai
    api_key_env: OPENAI_API_KEY
    model: text-embedding-3-small
    dimension: 1536
    batch_size: 32
    timeout_seconds: 30
```

Custom provider example:

```python
from agent_wiki.extensions import register_embedding_provider


class KnowledgeAgentEmbeddingProvider:
    dimension = 768

    def __init__(self, config, **kwargs):
        self.config = config

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dimension for _ in texts]


register_embedding_provider("knowledge-agent", KnowledgeAgentEmbeddingProvider)
```

After registration, set `retrieval.embedding.provider: knowledge-agent` in the registry. If the provider registration lives in a module that is not imported elsewhere, declare it in the wiki registry so agents can load it without changing `agent-wiki` code:

```yaml
retrieval:
  coarse_provider: lexical
  optional_providers: [embedding]
  route_priority: 80
  embedding:
    provider: knowledge-agent
    provider_module: knowledge_agent.embedding_provider
    api_key_env: KNOWLEDGE_AGENT_EMBEDDING_KEY
    model: custom-semantic-model
    dimension: 768
```

Multiple registration modules can be listed with `provider_modules`. Operators can also set `AGENT_WIKI_EMBEDDING_PROVIDER_MODULES=module.one,module.two` for process-level registration.

SiliconFlow is provided as `agent_wiki.infrastructure.retrieval.embedding` and can be enabled by configuration instead of being hardcoded in the core factory:

```yaml
retrieval:
  coarse_provider: lexical
  optional_providers: [embedding]
  route_priority: 80
  embedding:
    provider: siliconflow
    provider_module: agent_wiki.infrastructure.retrieval.embedding
    base_url: https://api.siliconflow.cn/v1
    api_key_env: SILICONFLOW_API_KEY
    model: BAAI/bge-m3
    dimension: 1024
```
