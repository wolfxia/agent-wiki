from pathlib import Path

from agent_wiki.bootstrap.registry_loader import RegistryLoader


def test_registry_loader_reads_registry_fixture() -> None:
    loader = RegistryLoader()

    registry = loader.load(Path("tests/fixtures/registry.yaml"))

    assert registry.version == 1
    assert registry.default_route_policy == "purpose_then_topic"
    assert len(registry.wikis) == 1
    assert registry.wikis[0].wiki_id == "personal-1"



def test_registry_loader_rejects_invalid_enum_values(tmp_path: Path) -> None:
    bad_registry = tmp_path / "bad-registry.yaml"
    bad_registry.write_text(
        """
version: 1
default_route_policy: purpose_then_topic
wikis:
  - wiki_id: personal-1
    type: personal
    workspace_path: ./tmp
    purpose_path: purpose.md
    config_path: config.yaml
    allowed_page_types: [raw, wrong_type]
    external_views:
      - adapter: plain_markdown
        mode: invalid_mode
    pending_query_policy: {}
    retrieval:
      coarse_provider: lexical
      optional_providers: []
      route_priority: 80
    permissions:
      - actor_type: robot
        actor_id: broken
        allowed_operations: [query]
        max_gate: Z
        allowed_page_types: [raw]
""",
        encoding="utf-8",
    )

    loader = RegistryLoader()

    try:
        loader.load(bad_registry)
    except Exception as error:
        message = str(error)
        assert "wrong_type" in message or "invalid_mode" in message or "robot" in message or "Z" in message
    else:
        raise AssertionError("expected invalid enum registry validation failure")


def test_registry_loader_reads_compile_llm_config(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry-llm.yaml"
    registry_path.write_text(
        """
version: 1
default_route_policy: purpose_then_topic
wikis:
  - wiki_id: personal-1
    type: personal
    workspace_path: ./tmp
    purpose_path: purpose.md
    config_path: config.yaml
    allowed_page_types: [raw, atom, synthesis]
    external_views: []
    pending_query_policy: {}
    retrieval:
      coarse_provider: lexical
      optional_providers: []
      route_priority: 80
    compile:
      llm:
        base_url: https://openrouter.ai/api/v1
        api_key_env: OPENROUTER_API_KEY
        model: deepseek/deepseek-chat-v3-0324
        max_tokens: 2048
        timeout_seconds: 20
    permissions: []
""",
        encoding="utf-8",
    )

    wiki = RegistryLoader().load(registry_path).wikis[0]

    assert wiki.compile.llm is not None
    assert wiki.compile.llm.base_url == "https://openrouter.ai/api/v1"
    assert wiki.compile.llm.api_key_env == "OPENROUTER_API_KEY"
    assert wiki.compile.llm.model == "deepseek/deepseek-chat-v3-0324"
    assert wiki.compile.llm.max_tokens == 2048
    assert wiki.compile.llm.timeout_seconds == 20


def test_registry_loader_defaults_compile_llm_timeout_to_120(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry-llm-default-timeout.yaml"
    registry_path.write_text(
        """
version: 1
default_route_policy: purpose_then_topic
wikis:
  - wiki_id: personal-1
    type: personal
    workspace_path: ./tmp
    purpose_path: purpose.md
    config_path: config.yaml
    allowed_page_types: [raw, atom, synthesis]
    external_views: []
    pending_query_policy: {}
    retrieval:
      coarse_provider: lexical
      optional_providers: []
      route_priority: 80
    compile:
      llm:
        base_url: https://openrouter.ai/api/v1
        api_key_env: OPENROUTER_API_KEY
        model: deepseek/deepseek-chat-v3-0324
        max_tokens: 2048
    permissions: []
""",
        encoding="utf-8",
    )

    wiki = RegistryLoader().load(registry_path).wikis[0]

    assert wiki.compile.llm.timeout_seconds == 120


def test_registry_loader_reads_embedding_config(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry-embedding.yaml"
    registry_path.write_text(
        """
version: 1
default_route_policy: purpose_then_topic
wikis:
  - wiki_id: personal-1
    type: personal
    workspace_path: ./tmp
    purpose_path: purpose.md
    config_path: config.yaml
    allowed_page_types: [raw, atom, synthesis]
    external_views: []
    pending_query_policy: {}
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
        batch_size: 32
    permissions: []
""",
        encoding="utf-8",
    )

    wiki = RegistryLoader().load(registry_path).wikis[0]

    assert wiki.retrieval.embedding is not None
    assert wiki.retrieval.embedding.provider == "siliconflow"
    assert wiki.retrieval.embedding.provider_module == "agent_wiki.infrastructure.retrieval.embedding"
    assert wiki.retrieval.embedding.model == "BAAI/bge-m3"
    assert wiki.retrieval.embedding.dimension == 1024
