from pathlib import Path
import json

from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.contracts import ResolvedActor, RetrievalHit
from agent_wiki.domain.models import QueryInput, QueryResult
from agent_wiki.infrastructure.retrieval.retrieval_index import RetrievalIndexRepository
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository


class QueryService:
    def execute(self, wiki: WikiConfig, actor: ResolvedActor, data: QueryInput) -> QueryResult:
        query_type = self._classify_query_type(data.query)
        wiki_root = Path(wiki.workspace_path)
        manifest = ManifestRepository(wiki_root)
        retrieval_index = RetrievalIndexRepository(wiki_root)

        hits = retrieval_index.lexical_search(data.query)
        if data.include_pending:
            hits.extend(self._search_pending_truth_zone(wiki_root, wiki.wiki_id, data.query))

        filtered_hits = [hit for hit in hits if self._include_hit(manifest, wiki_root, hit, data.include_pending)]
        filtered_hits.sort(key=lambda hit: (hit.score, self._manifest_priority(manifest, hit.doc_id)), reverse=True)
        l2_context = self._build_l2_context(manifest, filtered_hits)
        l3_proof = self._build_l3_proof(manifest, filtered_hits)
        l1_answer = self._build_l1_answer(filtered_hits, wiki_root)

        return QueryResult(
            query_type=query_type,
            l1_answer=l1_answer,
            l2_context=l2_context,
            l3_proof=l3_proof,
            hits=filtered_hits,
        )

    def _classify_query_type(self, query: str) -> str:
        lowered = query.lower()
        if any(token in lowered for token in ["proof", "evidence", "source"]):
            return "proof_trace"
        if any(token in lowered for token in ["compare", "tradeoff", "vs"]):
            return "compare_tradeoff"
        if any(token in lowered for token in ["why", "explain", "how"]):
            return "concept_explain"
        if any(token in lowered for token in ["trend", "scan"]):
            return "trend_scan"
        if any(token in lowered for token in ["should", "decision"]):
            return "decision_support"
        return "fact_lookup"

    def _include_hit(self, manifest: ManifestRepository, wiki_root: Path, hit: RetrievalHit, include_pending: bool) -> bool:
        entry = manifest.find(hit.doc_id)
        if entry is not None:
            return True
        pending_manifest_path = wiki_root / ".agent-wiki" / "pending_manifest.jsonl"
        if not include_pending or not pending_manifest_path.exists():
            return False
        for line in pending_manifest_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            pending_entry = json.loads(line)
            if pending_entry.get("doc_id") == hit.doc_id:
                return True
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
            if pending_entry.get("page_type") == "raw":
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
        if entry.get("page_type") in {"atom", "synthesis", "principle"}:
            return 2
        return 1

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

    def _build_l1_answer(self, hits: list[RetrievalHit], wiki_root: Path) -> str:
        if not hits:
            return "No matching knowledge found."
        page_path = wiki_root / "pages" / f"{hits[0].doc_id}.md"
        if not page_path.exists():
            return f"Top match: {hits[0].doc_id}"
        lines = [line.strip() for line in page_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(lines) >= 2:
            return lines[1]
        return lines[0] if lines else f"Top match: {hits[0].doc_id}"


class CrossWikiQueryService:
    def execute(self, wikis: list[WikiConfig], actor: ResolvedActor, data: QueryInput) -> QueryResult:
        combined_hits: list[RetrievalHit] = []
        l2_context: list[dict] = []
        l3_proof: list[dict] = []
        query_type = QueryService()._classify_query_type(data.query)
        l1_answer = "No matching knowledge found."

        for wiki in wikis:
            result = QueryService().execute(wiki, actor, data)
            if result.hits and l1_answer == "No matching knowledge found.":
                l1_answer = result.l1_answer
            combined_hits.extend(result.hits)
            l2_context.extend(result.l2_context)
            l3_proof.extend(result.l3_proof)

        combined_hits.sort(key=lambda hit: hit.score, reverse=True)
        return QueryResult(
            query_type=query_type,
            l1_answer=l1_answer,
            l2_context=l2_context[:3],
            l3_proof=l3_proof[:3],
            hits=combined_hits,
        )
