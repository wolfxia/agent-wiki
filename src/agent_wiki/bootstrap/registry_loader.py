from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from agent_wiki.domain.enums import ActorType, GateLevel, Operation, PageType


class PermissionConfig(BaseModel):
    actor_type: ActorType
    actor_id: str
    allowed_operations: list[Operation] = Field(default_factory=list)
    max_gate: GateLevel
    allowed_page_types: list[PageType] = Field(default_factory=list)


class RetrievalConfig(BaseModel):
    coarse_provider: str
    optional_providers: list[str] = Field(default_factory=list)
    route_priority: int


class PushViewRoutingConfig(BaseModel):
    direction_folders: dict[str, str] = Field(default_factory=dict)
    fallback_folders: dict[str, str] = Field(default_factory=dict)
    graph_index_folder: str = "knowledge-graph"
    graph_index_title: str = "Knowledge Graph Index"


class ExternalViewConfig(BaseModel):
    adapter: str
    mode: str
    path: str | None = None
    push_view_routing: PushViewRoutingConfig = Field(default_factory=PushViewRoutingConfig)


class LLMConfig(BaseModel):
    base_url: str
    api_key_env: str
    model: str
    max_tokens: int = 4096
    timeout_seconds: int = 120


class CompileConfig(BaseModel):
    llm: LLMConfig | None = None


class WikiConfig(BaseModel):
    wiki_id: str
    type: str
    workspace_path: str
    purpose_path: str
    config_path: str
    allowed_page_types: list[PageType] = Field(default_factory=list)
    external_views: list[ExternalViewConfig] = Field(default_factory=list)
    pending_query_policy: dict[str, str] = Field(default_factory=dict)
    retrieval: RetrievalConfig
    compile: CompileConfig = Field(default_factory=CompileConfig)
    permissions: list[PermissionConfig] = Field(default_factory=list)


class RegistryConfig(BaseModel):
    version: int
    default_route_policy: str
    wikis: list[WikiConfig] = Field(default_factory=list)


class RegistryLoader:
    def load(self, path: Path) -> RegistryConfig:
        data = yaml.safe_load(path.read_text())
        return RegistryConfig.model_validate(data)
