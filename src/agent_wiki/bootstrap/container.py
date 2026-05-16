from pathlib import Path

from agent_wiki.application.authority import AuthorityService
from agent_wiki.application.compile_suggest import CompileSuggestService
from agent_wiki.application.fast_feedback import FastFeedbackService
from agent_wiki.application.relations import RelationsService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.infrastructure.identity.gates import GateService
from agent_wiki.infrastructure.identity.permissions import PermissionService
from agent_wiki.infrastructure.identity.resolver import IdentityResolver
from agent_wiki.infrastructure.storage.purpose_reader import PurposeReader


class Container:
    def __init__(self) -> None:
        self.registry_loader = RegistryLoader()
        self.identity_resolver = IdentityResolver()
        self.permission_service = PermissionService()
        self.gate_service = GateService()
        self.compile_suggest_service = CompileSuggestService()
        self.fast_feedback_service = FastFeedbackService()
        self.relations_service = RelationsService()
        self.authority_service = AuthorityService()
        self.purpose_reader_factory = PurposeReader
