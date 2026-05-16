from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.contracts import PermissionDecision, ResolvedActor


class PermissionService:
    def check(self, actor: ResolvedActor, operation: str, wiki: WikiConfig, page_type: str) -> PermissionDecision:
        for permission in wiki.permissions:
            if permission.actor_type != actor.actor_type:
                continue
            if permission.actor_id != actor.actor_id:
                continue
            if operation not in permission.allowed_operations:
                continue
            if page_type not in permission.allowed_page_types:
                continue
            return PermissionDecision(allowed=True, reason="allowed")
        return PermissionDecision(allowed=False, reason="no matching permission rule")
