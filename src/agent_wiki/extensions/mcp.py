from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from agent_wiki.domain.contracts import ResolvedActor

if TYPE_CHECKING:
    from agent_wiki.bootstrap.registry_loader import WikiConfig


class MCPToolHandler(Protocol):
    def __call__(self, ctx: "MCPToolContext") -> Any:
        ...


@dataclass(frozen=True)
class MCPToolSpec:
    name: str
    description: str
    handler: MCPToolHandler
    required_operation: str | None = None
    required_page_type: str | None = None


@dataclass
class MCPToolContext:
    dispatcher: Any
    wiki: "WikiConfig"
    actor: ResolvedActor
    params: dict[str, Any]

    def check_permission(self, operation: str, page_type: str) -> Any:
        from agent_wiki.infrastructure.identity.permissions import PermissionService

        return PermissionService().check(self.actor, operation, self.wiki, page_type)
