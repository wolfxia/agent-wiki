from __future__ import annotations

_EXPORT_MODULES = {
    "AzureOpenAIEmbeddingProvider": "agent_wiki.extensions.embedding",
    "EmbeddingProvider": "agent_wiki.extensions.embedding",
    "OpenAICompatibleEmbeddingProvider": "agent_wiki.extensions.embedding",
    "OpenAIEmbeddingProvider": "agent_wiki.extensions.embedding",
    "create_embedding_provider": "agent_wiki.extensions.embedding",
    "register_embedding_provider": "agent_wiki.extensions.embedding",
    "MCPToolContext": "agent_wiki.extensions.mcp",
    "MCPToolSpec": "agent_wiki.extensions.mcp",
    "PageTypeDefinition": "agent_wiki.extensions.page_types",
    "PageTypeRegistry": "agent_wiki.extensions.page_types",
    "get_page_type_registry": "agent_wiki.extensions.page_types",
    "is_registered_page_type": "agent_wiki.extensions.page_types",
    "register_page_type": "agent_wiki.extensions.page_types",
}

__all__ = [
    "AzureOpenAIEmbeddingProvider",
    "EmbeddingProvider",
    "MCPToolContext",
    "MCPToolSpec",
    "OpenAICompatibleEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "PageTypeDefinition",
    "PageTypeRegistry",
    "create_embedding_provider",
    "get_page_type_registry",
    "is_registered_page_type",
    "register_embedding_provider",
    "register_page_type",
]


def __getattr__(name: str):
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
