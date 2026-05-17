from agent_wiki.application.compile_suggest import CompileSuggestService
from agent_wiki.application.fast_feedback import FastFeedbackService
from agent_wiki.application.relations import RelationsService
from agent_wiki.bootstrap.registry_loader import WikiConfig


class MaintenanceService:
    def run(self, wiki: WikiConfig) -> dict:
        compile_suggestions = CompileSuggestService().detect_and_enqueue(wiki)
        quality_signals = FastFeedbackService().detect_and_enqueue(wiki)
        relations = RelationsService()
        co_occurrences = relations.detect_and_enqueue_co_occurrences(wiki)
        cross_references = relations.detect_and_enqueue_cross_references(wiki)

        action_items: list[str] = []
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
            "compile_suggestions": len(compile_suggestions),
            "quality_signals": len(quality_signals),
            "co_occurrence_candidates": len(co_occurrences),
            "cross_reference_candidates": len(cross_references),
            "action_items": action_items,
        }
