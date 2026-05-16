from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.infrastructure.identity.gates import GateService
from agent_wiki.infrastructure.identity.permissions import PermissionService
from agent_wiki.infrastructure.identity.resolver import IdentityResolver


class Container:
    def __init__(self) -> None:
        self.registry_loader = RegistryLoader()
        self.identity_resolver = IdentityResolver()
        self.permission_service = PermissionService()
        self.gate_service = GateService()
