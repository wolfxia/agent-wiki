import re
from pathlib import Path

from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.domain.models import CaptureRawInput, CaptureResult
from agent_wiki.application.propagation import PropagationService
from agent_wiki.infrastructure.identity.permissions import PermissionService


_DOC_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class CaptureRawService:
    def execute(self, wiki: WikiConfig, actor: ResolvedActor, data: CaptureRawInput) -> CaptureResult:
        if "raw" not in wiki.allowed_page_types:
            raise ValueError("page type raw is not allowed")

        permission_service = PermissionService()
        decision = permission_service.check(actor, "capture_raw", wiki, "raw")
        if not decision.allowed:
            raise PermissionError(decision.reason)

        propagation_service = PropagationService(Path(wiki.workspace_path))
        if not _DOC_ID_PATTERN.match(data.doc_id):
            return propagation_service.record_pending_capture_raw(wiki=wiki, actor=actor, data=data)
        return propagation_service.propagate_capture_raw(wiki=wiki, actor=actor, data=data)
