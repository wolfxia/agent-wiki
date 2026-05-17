from pathlib import Path

from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.domain.models import CaptureRawInput, CaptureResult
from agent_wiki.application.propagation import PropagationService
from agent_wiki.infrastructure.identity.permissions import PermissionService
from agent_wiki.domain.validators import validate_doc_id
from agent_wiki.infrastructure.intake.raw_intake import normalize_raw_intake


class CaptureRawService:
    def execute(self, wiki: WikiConfig, actor: ResolvedActor, data: CaptureRawInput) -> CaptureResult:
        if "raw" not in wiki.allowed_page_types:
            raise ValueError("page type raw is not allowed")

        permission_service = PermissionService()
        decision = permission_service.check(actor, "capture_raw", wiki, "raw")
        if not decision.allowed:
            raise PermissionError(decision.reason)

        propagation_service = PropagationService(Path(wiki.workspace_path))
        normalized = CaptureRawInput.model_validate(normalize_raw_intake(data.model_dump()))
        try:
            validate_doc_id(normalized.doc_id)
        except ValueError:
            return propagation_service.record_pending_capture_raw(wiki=wiki, actor=actor, data=normalized)
        return propagation_service.propagate_capture_raw(wiki=wiki, actor=actor, data=normalized)
