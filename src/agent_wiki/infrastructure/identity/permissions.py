from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.contracts import PermissionDecision, ResolvedActor
from agent_wiki.domain.enums import GateLevel
from agent_wiki.infrastructure.identity.gates import GateService, gate_at_least


class PermissionService:
    def __init__(self) -> None:
        self._gate_service = GateService()

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
            required_gate = self._gate_service.required_gate(operation, page_type)
            actor_max = GateLevel(permission.max_gate)
            if not gate_at_least(actor_max, required_gate):
                return PermissionDecision(
                    allowed=False,
                    reason=f"max_gate {actor_max} insufficient for required gate {required_gate}",
                )
            return PermissionDecision(allowed=True, reason="allowed")
        return PermissionDecision(allowed=False, reason="no matching permission rule")
