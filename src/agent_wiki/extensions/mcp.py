from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_wiki.bootstrap.registry_loader import WikiConfig
    from agent_wiki.domain.contracts import ResolvedActor


@dataclass(frozen=True)
class MCPToolSpec:
    name: str
    description: str
    handler: Any  # runtime callback; typed Any to avoid Pydantic CallableSchema error
    required_operation: str | None = None
    required_page_type: str | None = None
    input_schema: dict[str, Any] | None = None  # JSON Schema for tool parameters; if None, accepts any dict


@dataclass
class MCPToolContext:
    dispatcher: Any
    wiki: "WikiConfig"
    actor: "ResolvedActor"
    params: dict[str, Any]

    def check_permission(self, operation: str, page_type: str) -> Any:
        from agent_wiki.infrastructure.identity.permissions import PermissionService

        return PermissionService().check(self.actor, operation, self.wiki, page_type)
