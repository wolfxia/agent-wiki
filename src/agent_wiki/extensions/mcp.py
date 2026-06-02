from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from agent_wiki.domain.contracts import ResolvedActor

if TYPE_CHECKING:
    from agent_wiki.bootstrap.registry_loader import WikiConfig


@dataclass(frozen=True)
class MCPToolSpec:
    name: str
    description: str
    handler: Callable[["MCPToolContext"], Any]
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
