from pathlib import Path

from agent_wiki.application.compile_suggest import CompileSuggestService
from agent_wiki.application.fast_feedback import FastFeedbackService
from agent_wiki.application.relations import RelationsService
from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.infrastructure.repair.raw_metadata_repair import RawMetadataRepairService
from agent_wiki.infrastructure.retrieval.retrieval_index import RetrievalIndexRepository
from agent_wiki.infrastructure.retrieval.sqlite_fts import SQLiteFTSIndexProvider
from agent_wiki.infrastructure.retrieval.topic_index import TopicIndexRepository
from agent_wiki.infrastructure.runtime.operation_log import OperationLogRepository
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository


class MaintenanceService:
    def run(self, wiki: WikiConfig) -> dict:
        repair_summary = RawMetadataRepairService().repair(wiki)
        orphan_cleanup_count = self._clean_orphan_authority_entries(wiki)
        compile_candidates = CompileSuggestService().detect_and_enqueue(wiki)
        quality_signals = FastFeedbackService().detect_and_enqueue(wiki)
        relations = RelationsService()
        co_occurrences = relations.detect_and_enqueue_co_occurrences(wiki)
        cross_references = relations.detect_and_enqueue_cross_references(wiki)

        metadata_repair_candidates = [c for c in compile_candidates if c["kind"] == "needs_metadata_repair"]
        compile_suggestions = [c for c in compile_candidates if c["kind"] != "needs_metadata_repair"]

        action_items: list[str] = []
        total_repair_candidates = repair_summary["metadata_repair_candidates"] + len(metadata_repair_candidates)
        if total_repair_candidates:
            action_items.append(
                f"Repair raw metadata for {total_repair_candidates} imported raw pages"
            )
        for candidate in compile_suggestions:
            action_items.append(
                f"Compile cluster {candidate['topic']}/{candidate['problem_cluster']} from {candidate['raw_count']} raw pages"
            )
        for signal in quality_signals:
            action_items.append(
                f"Investigate repeated zero-hit query: {signal['query']} ({signal['zero_hit_count']} misses)"
            )
        for relation in co_occurrences:
            action_items.append(
                f"Review co-occurrence candidate: {relation['doc_ids'][0]} <-> {relation['doc_ids'][1]}"
            )
        for relation in cross_references:
            action_items.append(
                f"Review cross-reference candidate: {relation['doc_ids'][0]} <-> {relation['doc_ids'][1]}"
            )

        return {
            "metadata_repair_candidates": total_repair_candidates,
            "orphan_cleanup_count": orphan_cleanup_count,
            "compile_suggestions": len(compile_suggestions),
            "quality_signals": len(quality_signals),
            "co_occurrence_candidates": len(co_occurrences),
            "cross_reference_candidates": len(cross_references),
            "action_items": action_items,
        }

    def _clean_orphan_authority_entries(self, wiki: WikiConfig) -> int:
        wiki_root = Path(wiki.workspace_path)
        manifest = ManifestRepository(wiki_root)
        topic_index = TopicIndexRepository(wiki_root)
        retrieval_index = RetrievalIndexRepository(wiki_root)
        fts_index = SQLiteFTSIndexProvider(wiki_root, wiki_id=wiki.wiki_id)
        operation_log = OperationLogRepository(wiki_root)

        orphan_doc_ids: list[str] = []
        for entry in manifest.read_all():
            canonical_uri = entry.get("canonical_uri")
            if not canonical_uri:
                orphan_doc_ids.append(str(entry.get("doc_id", "")))
                continue
            page_path = wiki_root / str(canonical_uri)
            if not page_path.exists() or not page_path.is_file():
                orphan_doc_ids.append(str(entry.get("doc_id", "")))

        for doc_id in orphan_doc_ids:
            if not doc_id:
                continue
            manifest.delete(doc_id)
            topic_index.delete(doc_id)
            fts_index.delete(doc_id)
            operation_log.append({
                "operation": "orphan_cleanup",
                "wiki_id": wiki.wiki_id,
                "doc_id": doc_id,
            })

        if orphan_doc_ids:
            remaining_entries = manifest.read_all()
            retrieval_index.rebuild_from_manifest(remaining_entries)
            fts_index.rebuild_from_manifest(remaining_entries)

        return len([doc_id for doc_id in orphan_doc_ids if doc_id])
