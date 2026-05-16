from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.domain.models import IdentityContext


class IdentityResolver:
    def resolve(self, context: IdentityContext) -> ResolvedActor:
        actor_type = context.actor_type or context.metadata.get("actor_type", "human") if context.metadata else context.actor_type or "human"
        actor_id = context.actor_id or context.metadata.get("actor_id", "unknown") if context.metadata else context.actor_id or "unknown"
        return ResolvedActor(actor_type=actor_type, actor_id=actor_id, transport=context.transport)
