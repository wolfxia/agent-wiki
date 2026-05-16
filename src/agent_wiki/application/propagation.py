from pathlib import Path

from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.domain.models import CaptureRawInput, CaptureResult, CompileResult, CompileUpdateInput
from agent_wiki.infrastructure.retrieval.retrieval_index import RetrievalIndexRepository
from agent_wiki.infrastructure.runtime.operation_log import OperationLogRepository
from agent_wiki.infrastructure.runtime.pending_state import PendingStateRepository
from agent_wiki.infrastructure.runtime.review_queue import ReviewQueueRepository
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository


class PropagationService:
    def __init__(self, wiki_root: Path) -> None:
        self.wiki_root = wiki_root
        self.manifest_repository = ManifestRepository(wiki_root)
        self.retrieval_index_repository = RetrievalIndexRepository(wiki_root)
        self.pending_state_repository = PendingStateRepository(wiki_root)
        self.operation_log_repository = OperationLogRepository(wiki_root)
        self.review_queue_repository = ReviewQueueRepository(wiki_root)

    def propagate_capture_raw(self, wiki: WikiConfig, actor: ResolvedActor, data: CaptureRawInput) -> CaptureResult:
        page_path = self.wiki_root / "pages" / f"{data.doc_id}.md"
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(data.content, encoding="utf-8")

        self.manifest_repository.append(
            {
                "wiki_id": wiki.wiki_id,
                "doc_id": data.doc_id,
                "page_type": "raw",
                "topic": data.topic,
                "canonical_uri": f"pages/{data.doc_id}.md",
                "last_writer": actor.actor_id,
                "problem_cluster": data.problem_cluster,
            }
        )
        self.retrieval_index_repository.append_raw_card(wiki.wiki_id, data)

        log_path = self.wiki_root / "log.md"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"- capture_raw {data.doc_id} by {actor.actor_id}\n")

        return CaptureResult(status="committed", doc_id=data.doc_id, page_path=str(page_path))

    def record_pending_capture_raw(self, wiki: WikiConfig, actor: ResolvedActor, data: CaptureRawInput) -> CaptureResult:
        self.pending_state_repository.append_pending_manifest(
            {
                "wiki_id": wiki.wiki_id,
                "doc_id": data.doc_id,
                "page_type": "raw",
                "canonical_uri": f"pages/{data.doc_id}.md",
                "last_writer": actor.actor_id,
                "status": "pending",
            }
        )
        return CaptureResult(status="pending", doc_id=data.doc_id, page_path=f"pages/{data.doc_id}.md")

    def propagate_compile_update(self, wiki: WikiConfig, actor: ResolvedActor, data: CompileUpdateInput) -> CompileResult:
        page_path = self.wiki_root / "pages" / f"{data.doc_id}.md"
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(data.content, encoding="utf-8")

        self.manifest_repository.upsert(
            {
                "wiki_id": wiki.wiki_id,
                "doc_id": data.doc_id,
                "page_type": data.page_type,
                "topic": data.topic,
                "canonical_uri": f"pages/{data.doc_id}.md",
                "last_writer": actor.actor_id,
                "problem_cluster": data.problem_cluster,
                "source_refs": data.source_refs,
                "review_status": data.review_status,
                "dispute_reason": data.dispute_reason,
            }
        )
        self.retrieval_index_repository.append_compiled_card(wiki.wiki_id, data)
        self.operation_log_repository.append(
            {
                "operation": "compile_update",
                "doc_id": data.doc_id,
                "page_type": data.page_type,
                "actor_id": actor.actor_id,
            }
        )
        if data.evidence_note:
            self.review_queue_repository.append(
                {
                    "item_type": "missing_evidence",
                    "doc_id": data.doc_id,
                    "reason": data.evidence_note,
                    "status": "open",
                }
            )

        log_path = self.wiki_root / "log.md"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"- compile_update {data.doc_id} by {actor.actor_id}\n")

        return CompileResult(status="committed", doc_id=data.doc_id, page_path=str(page_path))
