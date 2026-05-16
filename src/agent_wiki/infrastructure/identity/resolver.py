from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.domain.models import IdentityContext


class IdentityResolutionError(ValueError):
    pass


class IdentityResolver:
    def resolve(self, context: IdentityContext) -> ResolvedActor:
        metadata = context.metadata or {}
        actor_type = metadata.get("actor_type") or context.actor_type
        actor_id = metadata.get("actor_id") or context.actor_id
        if not actor_type or not actor_id:
            raise IdentityResolutionError("actor_type and actor_id are required")
        return ResolvedActor(actor_type=actor_type, actor_id=actor_id, transport=context.transport)
