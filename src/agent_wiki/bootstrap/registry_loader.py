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
    max_retries: int = 3
    retry_delays: list[int] = Field(default_factory=lambda: [10, 30, 60])
    concurrency: int = 1


class CompileConfig(BaseModel):
    llm: LLMConfig | None = None


class DreamCycleSynthesisConfig(BaseModel):
    min_atoms: int = 2
    max_synthesis_per_run: int = 10
    strength_threshold: float = 0.3


class DreamCycleQualityConfig(BaseModel):
    min_score: int = 50
    staleness_days: int = 30


class DreamCycleOrphanConfig(BaseModel):
    report_path: str = ".agent-wiki/dream_cycle_orphans.jsonl"


class DreamCycleConfig(BaseModel):
    enabled: bool = True
    schedule: str = "0 3 * * *"
    synthesis: DreamCycleSynthesisConfig = Field(default_factory=DreamCycleSynthesisConfig)
    quality: DreamCycleQualityConfig = Field(default_factory=DreamCycleQualityConfig)
    orphan: DreamCycleOrphanConfig = Field(default_factory=DreamCycleOrphanConfig)


class QueryRankingTuningConfig(BaseModel):
    atom_page_type_boost: float = 4.0
    synthesis_page_type_boost: float = 4.0
    principle_page_type_boost: float = 2.0
    purpose_boost: float = 1.5
    topic_alignment_boost: float = 5.0
    topic_seed_score: float = 8.0
    rerank_candidate_multiplier: int = 3


class RuntimeTuningConfig(BaseModel):
    query_ranking: QueryRankingTuningConfig = Field(default_factory=QueryRankingTuningConfig)


class FreshnessConfig(BaseModel):
    default_stale_days: int | None = 30
    volatile_topics: dict[str, int | None] = Field(default_factory=dict)
    freshness_class_thresholds: dict[str, int | None] = Field(default_factory=lambda: {"volatile": 14, "evergreen": 90})


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
    dream_cycle: DreamCycleConfig = Field(default_factory=DreamCycleConfig)
    tuning_defaults: RuntimeTuningConfig = Field(default_factory=RuntimeTuningConfig)
    freshness: FreshnessConfig = Field(default_factory=FreshnessConfig)
    permissions: list[PermissionConfig] = Field(default_factory=list)


class RegistryConfig(BaseModel):
    version: int
    default_route_policy: str
    wikis: list[WikiConfig] = Field(default_factory=list)


class RegistryLoader:
    def load(self, path: Path) -> RegistryConfig:
        data = yaml.safe_load(path.read_text())
        return RegistryConfig.model_validate(data)
