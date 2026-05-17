from pathlib import Path
import json
import uuid

from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.contracts import ResolvedActor, RetrievalHit
from agent_wiki.domain.enums import PageType, Sensitivity
from agent_wiki.domain.models import QueryInput, QueryResult
from agent_wiki.application.retrieval_router import RetrievalRouter
from agent_wiki.infrastructure.query.classifier import RuleBasedQueryClassifier
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository
from agent_wiki.infrastructure.storage.purpose_reader import PurposeReader
from agent_wiki.infrastructure.retrieval.topic_index import TopicIndexRepository


class QueryService:
    def __init__(self) -> None:
        self._classifier = RuleBasedQueryClassifier()

    def execute(self, wiki: WikiConfig, actor: ResolvedActor, data: QueryInput, *, write_outcome: bool = True) -> QueryResult:
        query_type = self._classifier.classify(data.query)
        wiki_root = Path(wiki.workspace_path)
        manifest = ManifestRepository(wiki_root)
        router = RetrievalRouter(wiki_root, wiki_id=wiki.wiki_id)

        hits = router.search(data.query)
        if data.include_pending:
            hits.extend(self._search_pending_truth_zone(wiki_root, wiki.wiki_id, data.query))

        filtered_hits = [hit for hit in hits if self._include_hit(manifest, wiki_root, hit, data.include_pending)]
        max_sensitivity = data.max_sensitivity or Sensitivity.INTERNAL
        filtered_hits = [hit for hit in filtered_hits if self._sensitivity_allowed(manifest, hit.doc_id, max_sensitivity)]
        purpose_reader = PurposeReader(wiki_root)
        filtered_hits = self._apply_ranking(manifest, purpose_reader, filtered_hits)
        l2_context = self._build_l2_context(manifest, filtered_hits)
        l3_proof = self._build_l3_proof(manifest, filtered_hits)
        l1_answer = self._build_l1_answer(filtered_hits, wiki_root, manifest)
        if write_outcome:
            self._append_query_outcome(wiki_root, actor, data, filtered_hits)

        return QueryResult(
            query_type=query_type,
            l1_answer=l1_answer,
            l2_context=l2_context,
            l3_proof=l3_proof,
            hits=filtered_hits,
            hit_count=len(filtered_hits),
            miss_signal=len(filtered_hits) == 0,
        )

    def _include_hit(self, manifest: ManifestRepository, wiki_root: Path, hit: RetrievalHit, include_pending: bool) -> bool:
        entry = manifest.find(hit.doc_id)
        if entry is not None:
            return True
        pending_manifest_path = wiki_root / ".agent-wiki" / "pending_manifest.jsonl"
        if not pending_manifest_path.exists():
            return False
        for line in pending_manifest_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            pending_entry = json.loads(line)
            if pending_entry.get("doc_id") != hit.doc_id:
                continue
            if pending_entry.get("page_type") == PageType.RAW.value:
                return True
            return include_pending
        return False

    def _search_pending_truth_zone(self, wiki_root: Path, wiki_id: str, query: str) -> list[RetrievalHit]:
        pending_manifest_path = wiki_root / ".agent-wiki" / "pending_manifest.jsonl"
        if not pending_manifest_path.exists():
            return []
        terms = [term.lower() for term in query.split() if term.strip()]
        hits: list[RetrievalHit] = []
        for line in pending_manifest_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            pending_entry = json.loads(line)
            if pending_entry.get("page_type") == PageType.RAW.value:
                continue
            page_path = wiki_root / "pages" / f"{pending_entry['doc_id']}.md"
            if not page_path.exists():
                continue
            content = page_path.read_text(encoding="utf-8").lower()
            score = sum(1 for term in terms if term in content)
            if score:
                hits.append(RetrievalHit(wiki_id=wiki_id, doc_id=pending_entry["doc_id"], score=float(score)))
        return hits

    def _manifest_priority(self, manifest: ManifestRepository, doc_id: str) -> int:
        entry = manifest.find(doc_id)
        if entry is None:
            return 0
        if entry.get("review_status") == "disputed":
            return 3
        if entry.get("page_type") in {PageType.ATOM.value, PageType.SYNTHESIS.value, PageType.PRINCIPLE.value}:
            return 2
        return 1

    def _purpose_boost(self, manifest: ManifestRepository, purpose_reader: PurposeReader, doc_id: str) -> float:
        entry = manifest.find(doc_id)
        if entry is None:
            return 0.0
        topic = entry.get("topic", "")
        if topic and purpose_reader.is_aligned(topic):
            return 1.5
        return 0.0

    def _apply_ranking(self, manifest: ManifestRepository, purpose_reader: PurposeReader, hits: list[RetrievalHit]) -> list[RetrievalHit]:
        ranked: list[RetrievalHit] = []
        for hit in hits:
            manifest_entry = manifest.find(hit.doc_id) or {}
            page_type_boost = 0.0
            if manifest_entry.get("page_type") in {PageType.ATOM.value, PageType.SYNTHESIS.value, PageType.PRINCIPLE.value}:
                page_type_boost = 2.0
            purpose_boost = self._purpose_boost(manifest, purpose_reader, hit.doc_id)
            freshness = float(manifest_entry.get("updated_at_score") or 0.0)
            manifest_priority = float(self._manifest_priority(manifest, hit.doc_id))
            final_score = hit.score + page_type_boost + purpose_boost + freshness + manifest_priority
            metadata = {
                **hit.metadata,
                "page_type_boost": page_type_boost,
                "purpose_boost": purpose_boost,
                "freshness": freshness,
                "manifest_priority": manifest_priority,
                "final_score": final_score,
            }
            ranked.append(hit.model_copy(update={"score": final_score, "metadata": metadata}))
        ranked.sort(key=lambda hit: hit.score, reverse=True)
        return ranked

    _SENSITIVITY_ORDER = {Sensitivity.PUBLIC: 0, Sensitivity.INTERNAL: 1, Sensitivity.CONFIDENTIAL: 2}

    def _sensitivity_allowed(self, manifest: ManifestRepository, doc_id: str, max_sensitivity: Sensitivity) -> bool:
        entry = manifest.find(doc_id)
        if entry is None:
            return True
        doc_sensitivity = Sensitivity(entry.get("sensitivity") or Sensitivity.PUBLIC)
        max_level = self._SENSITIVITY_ORDER[max_sensitivity]
        doc_level = self._SENSITIVITY_ORDER[doc_sensitivity]
        return doc_level <= max_level

    def _build_l2_context(self, manifest: ManifestRepository, hits: list[RetrievalHit]) -> list[dict]:
        context = []
        for hit in hits[:3]:
            entry = manifest.find(hit.doc_id) or {}
            caveat = ""
            if entry.get("review_status") == "disputed":
                dispute_reason = entry.get("dispute_reason", "unknown dispute")
                caveat = f"disputed: {dispute_reason}"
            context.append({"wiki_id": hit.wiki_id, "doc_id": hit.doc_id, "score": hit.score, "caveat": caveat})
        return context

    def _build_l3_proof(self, manifest: ManifestRepository, hits: list[RetrievalHit]) -> list[dict]:
        proof = []
        for hit in hits[:3]:
            entry = manifest.find(hit.doc_id) or {}
            proof.append({"doc_id": hit.doc_id, "source_refs": entry.get("source_refs", [])})
        return proof

    def _build_l1_answer(self, hits: list[RetrievalHit], wiki_root: Path, manifest: ManifestRepository) -> str:
        if not hits:
            return "No matching knowledge found."
        top_hit = hits[0]
        topic_index_entry = TopicIndexRepository(wiki_root).find(top_hit.doc_id)
        if topic_index_entry and topic_index_entry.get("summary"):
            return topic_index_entry["summary"]
        manifest_entry = manifest.find(top_hit.doc_id) or {}
        if manifest_entry.get("summary"):
            return str(manifest_entry["summary"])
        page_path = wiki_root / "pages" / f"{top_hit.doc_id}.md"
        if not page_path.exists():
            return f"Top match: {top_hit.doc_id}"
        lines = [line.strip() for line in page_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(lines) >= 2:
            return lines[1]
        return lines[0] if lines else f"Top match: {top_hit.doc_id}"

    def _append_query_outcome(
        self,
        wiki_root: Path,
        actor: ResolvedActor,
        data: QueryInput,
        hits: list[RetrievalHit],
    ) -> None:
        path = wiki_root / "query_outcomes.jsonl"
        query_id = str(uuid.uuid4())
        entry = {
            "query_id": query_id,
            "query": data.query,
            "hit_count": len(hits),
            "actor_id": actor.actor_id,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

        hits_path = wiki_root / "query_hits.jsonl"
        with hits_path.open("a", encoding="utf-8") as handle:
            for hit in hits:
                handle.write(json.dumps({"query_id": query_id, "doc_id": hit.doc_id}, ensure_ascii=False) + "\n")


class CrossWikiQueryService:
    def execute(self, wikis: list[WikiConfig], actor: ResolvedActor, data: QueryInput) -> QueryResult:
        combined_hits: list[RetrievalHit] = []
        l2_context: list[dict] = []
        l3_proof: list[dict] = []
        query_service = QueryService()
        query_type = query_service._classifier.classify(data.query)
        l1_answer = "No matching knowledge found."

        for wiki in wikis:
            result = query_service.execute(wiki, actor, data, write_outcome=False)
            if result.hits and l1_answer == "No matching knowledge found.":
                l1_answer = result.l1_answer
            combined_hits.extend(result.hits)
            l2_context.extend(result.l2_context)
            l3_proof.extend(result.l3_proof)

        if wikis:
            primary_root = Path(wikis[0].workspace_path)
            outcomes_path = primary_root / "query_outcomes.jsonl"
            query_id = str(uuid.uuid4())
            with outcomes_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "query_id": query_id,
                    "query": data.query,
                    "hit_count": len(combined_hits),
                    "actor_id": actor.actor_id,
                    "cross_wiki": True,
                }, ensure_ascii=False) + "\n")

        combined_hits.sort(key=lambda hit: hit.score, reverse=True)
        return QueryResult(
            query_type=query_type,
            l1_answer=l1_answer,
            l2_context=l2_context[:3],
            l3_proof=l3_proof[:3],
            hits=combined_hits,
            hit_count=len(combined_hits),
            miss_signal=len(combined_hits) == 0,
        )
