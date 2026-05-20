from pathlib import Path
from datetime import UTC, datetime, timedelta
import json
import re
import time
import uuid

from agent_wiki.bootstrap.registry_loader import QueryRankingTuningConfig, WikiConfig
from agent_wiki.domain.contracts import ResolvedActor, RetrievalHit
from agent_wiki.domain.enums import PageType, Sensitivity
from agent_wiki.domain.models import QueryInput, QueryResult
from agent_wiki.application.retrieval_router import RetrievalRouter
from agent_wiki.application.runtime_tuning import RuntimeTuningService
from agent_wiki.infrastructure.query.classifier import RuleBasedQueryClassifier
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository
from agent_wiki.infrastructure.storage.purpose_reader import PurposeReader
from agent_wiki.infrastructure.retrieval.topic_index import TopicIndexRepository


class QueryService:
    def __init__(self) -> None:
        self._classifier = RuleBasedQueryClassifier()
        self._runtime_tuning = RuntimeTuningService()

    def execute(self, wiki: WikiConfig, actor: ResolvedActor, data: QueryInput, *, write_outcome: bool = True) -> QueryResult:
        start_time = time.monotonic()
        query_type = self._classifier.classify(data.query)
        wiki_root = Path(wiki.workspace_path)
        query_ranking = self._runtime_tuning.load(wiki).query_ranking
        manifest = ManifestRepository(wiki_root)
        manifest_entries = manifest.read_all()
        manifest_by_doc_id = {
            str(entry.get("doc_id")): entry
            for entry in manifest_entries
            if entry.get("doc_id")
        }
        router = RetrievalRouter(wiki_root, wiki_id=wiki.wiki_id)

        filters = {"page_types": data.page_types} if data.page_types else None
        hits = router.search(data.query, top_k=self._rerank_top_k(data, query_ranking.rerank_candidate_multiplier), filters=filters)
        if data.include_pending:
            hits.extend(self._search_pending_truth_zone(wiki_root, wiki.wiki_id, data.query))
        purpose_reader = PurposeReader(wiki_root)
        hits = self._merge_hits(
            hits,
            self._seed_purpose_topic_hits(
                manifest_entries,
                purpose_reader,
                data.query,
                manifest_by_doc_id,
                query_ranking.topic_seed_score,
            ),
        )

        filtered_hits = [
            hit for hit in hits
            if self._include_hit(manifest, wiki_root, hit, data.include_pending, manifest_by_doc_id)
        ]
        if data.page_types:
            allowed_page_types = set(data.page_types)
            filtered_hits = [
                hit for hit in filtered_hits
                if manifest_by_doc_id.get(hit.doc_id, {}).get("page_type") in allowed_page_types
            ]
        max_sensitivity = data.max_sensitivity or Sensitivity.INTERNAL
        filtered_hits = [
            hit for hit in filtered_hits
            if self._sensitivity_allowed(manifest, hit.doc_id, max_sensitivity, manifest_by_doc_id)
        ]
        filtered_hits = self._apply_ranking(manifest, purpose_reader, filtered_hits, manifest_by_doc_id, query_ranking)
        l2_context = self._build_l2_context(manifest, filtered_hits, manifest_by_doc_id, wiki)
        l3_proof = self._build_l3_proof(manifest, filtered_hits, manifest_by_doc_id)
        topic_index_entries = {
            row["doc_id"]: row for row in TopicIndexRepository(wiki_root).read_all()
            if row.get("doc_id")
        }
        l1_answer = self._build_l1_answer(filtered_hits, wiki_root, manifest, manifest_by_doc_id, topic_index_entries)
        if write_outcome:
            self._append_query_outcome(
                wiki_root,
                actor,
                data,
                filtered_hits,
                manifest,
                manifest_by_doc_id,
                latency_ms=round(max(time.monotonic() - start_time, 0.0) * 1000, 3),
            )

        return QueryResult(
            query_type=query_type,
            l1_answer=l1_answer,
            l2_context=l2_context,
            l3_proof=l3_proof,
            hits=filtered_hits,
            hit_count=len(filtered_hits),
            miss_signal=len(filtered_hits) == 0,
        )

    def _include_hit(self, manifest: ManifestRepository, wiki_root: Path, hit: RetrievalHit, include_pending: bool, manifest_by_doc_id: dict[str, dict] | None = None) -> bool:
        entry = (manifest_by_doc_id or {}).get(hit.doc_id) or manifest.find(hit.doc_id)
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

    def _manifest_priority(self, manifest: ManifestRepository, doc_id: str, manifest_by_doc_id: dict[str, dict] | None = None) -> int:
        entry = (manifest_by_doc_id or {}).get(doc_id) or manifest.find(doc_id)
        if entry is None:
            return 0
        if entry.get("review_status") == "disputed":
            return 3
        if entry.get("page_type") in {PageType.ATOM.value, PageType.SYNTHESIS.value, PageType.PRINCIPLE.value}:
            return 2
        return 1

    def _purpose_boost(
        self,
        manifest: ManifestRepository,
        purpose_reader: PurposeReader,
        doc_id: str,
        boost: float,
        manifest_by_doc_id: dict[str, dict] | None = None,
    ) -> float:
        entry = (manifest_by_doc_id or {}).get(doc_id) or manifest.find(doc_id)
        if entry is None:
            return 0.0
        topic = entry.get("topic", "")
        if topic and purpose_reader.is_aligned(topic):
            return boost
        return 0.0

    def _topic_alignment_boost(
        self,
        manifest: ManifestRepository,
        purpose_reader: PurposeReader,
        doc_id: str,
        boost: float,
        manifest_by_doc_id: dict[str, dict] | None = None,
    ) -> float:
        entry = (manifest_by_doc_id or {}).get(doc_id) or manifest.find(doc_id)
        if entry is None:
            return 0.0
        topic = str(entry.get("topic") or "")
        if not topic:
            return 0.0
        if purpose_reader.is_aligned(topic):
            return boost
        return 0.0

    def _apply_ranking(
        self,
        manifest: ManifestRepository,
        purpose_reader: PurposeReader,
        hits: list[RetrievalHit],
        manifest_by_doc_id: dict[str, dict] | None = None,
        query_ranking=None,
    ) -> list[RetrievalHit]:
        query_ranking = query_ranking or QueryRankingTuningConfig()
        ranked: list[RetrievalHit] = []
        for hit in hits:
            manifest_entry = (manifest_by_doc_id or {}).get(hit.doc_id) or manifest.find(hit.doc_id) or {}
            page_type_boost = 0.0
            if manifest_entry.get("page_type") == PageType.ATOM.value:
                page_type_boost = float(query_ranking.atom_page_type_boost)
            elif manifest_entry.get("page_type") == PageType.SYNTHESIS.value:
                page_type_boost = float(query_ranking.synthesis_page_type_boost)
            elif manifest_entry.get("page_type") == PageType.PRINCIPLE.value:
                page_type_boost = float(query_ranking.principle_page_type_boost)
            purpose_boost = self._purpose_boost(
                manifest,
                purpose_reader,
                hit.doc_id,
                float(query_ranking.purpose_boost),
                manifest_by_doc_id,
            )
            topic_alignment_boost = self._topic_alignment_boost(
                manifest,
                purpose_reader,
                hit.doc_id,
                float(query_ranking.topic_alignment_boost),
                manifest_by_doc_id,
            )
            freshness = float(manifest_entry.get("updated_at_score") or 0.0)
            manifest_priority = float(self._manifest_priority(manifest, hit.doc_id, manifest_by_doc_id))
            final_score = hit.score + page_type_boost + purpose_boost + topic_alignment_boost + freshness + manifest_priority
            metadata = {
                **hit.metadata,
                "page_type_boost": page_type_boost,
                "purpose_boost": purpose_boost,
                "topic_alignment_boost": topic_alignment_boost,
                "freshness": freshness,
                "manifest_priority": manifest_priority,
                "final_score": final_score,
            }
            ranked.append(hit.model_copy(update={"score": final_score, "metadata": metadata}))
        ranked.sort(key=lambda hit: hit.score, reverse=True)
        return ranked

    _SENSITIVITY_ORDER = {Sensitivity.PUBLIC: 0, Sensitivity.INTERNAL: 1, Sensitivity.CONFIDENTIAL: 2}

    def _sensitivity_allowed(self, manifest: ManifestRepository, doc_id: str, max_sensitivity: Sensitivity, manifest_by_doc_id: dict[str, dict] | None = None) -> bool:
        entry = (manifest_by_doc_id or {}).get(doc_id) or manifest.find(doc_id)
        if entry is None:
            return True
        doc_sensitivity = Sensitivity(entry.get("sensitivity") or Sensitivity.PUBLIC)
        max_level = self._SENSITIVITY_ORDER[max_sensitivity]
        doc_level = self._SENSITIVITY_ORDER[doc_sensitivity]
        return doc_level <= max_level

    def _build_l2_context(
        self,
        manifest: ManifestRepository,
        hits: list[RetrievalHit],
        manifest_by_doc_id: dict[str, dict] | None = None,
        wiki: WikiConfig | None = None,
    ) -> list[dict]:
        context = []
        for hit in hits[:3]:
            entry = (manifest_by_doc_id or {}).get(hit.doc_id) or manifest.find(hit.doc_id) or {}
            caveats = []
            if entry.get("review_status") == "disputed":
                dispute_reason = entry.get("dispute_reason", "unknown dispute")
                caveats.append(f"disputed: {dispute_reason}")
            freshness = self._freshness_state(entry, wiki)
            if freshness["status"] == "possibly_stale":
                caveats.append("possibly_stale")
            context.append({
                "wiki_id": hit.wiki_id,
                "doc_id": hit.doc_id,
                "score": hit.score,
                "caveat": "; ".join(caveats),
                "freshness": freshness,
                "possibly_stale": freshness["status"] == "possibly_stale",
            })
        return context

    def _freshness_state(self, entry: dict, wiki: WikiConfig | None = None) -> dict:
        threshold_days = self._stale_threshold_days(entry, wiki)
        updated_at = entry.get("updated_at") or entry.get("updated")
        state = {"status": "unknown", "updated_at": updated_at or None, "stale_threshold_days": threshold_days}
        if threshold_days is None:
            state["status"] = "fresh" if updated_at else "unknown"
            return state
        if not updated_at:
            return state
        try:
            parsed = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
        except ValueError:
            return state
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        if parsed.astimezone(UTC) < datetime.now(UTC) - timedelta(days=threshold_days):
            state["status"] = "possibly_stale"
        else:
            state["status"] = "fresh"
        return state

    def _stale_threshold_days(self, entry: dict, wiki: WikiConfig | None = None) -> int | None:
        freshness = getattr(wiki, "freshness", None) if wiki is not None else None
        default = getattr(freshness, "default_stale_days", 30) if freshness is not None else 30
        topic = str(entry.get("topic") or "")
        volatile_topics = getattr(freshness, "volatile_topics", {}) if freshness is not None else {}
        if topic in volatile_topics:
            return volatile_topics[topic]
        freshness_class = str(entry.get("freshness_class") or "")
        thresholds = getattr(freshness, "freshness_class_thresholds", {}) if freshness is not None else {}
        if freshness_class and freshness_class in thresholds:
            return thresholds[freshness_class]
        return default

    def _build_l3_proof(self, manifest: ManifestRepository, hits: list[RetrievalHit], manifest_by_doc_id: dict[str, dict] | None = None) -> list[dict]:
        proof = []
        for hit in hits[:3]:
            entry = (manifest_by_doc_id or {}).get(hit.doc_id) or manifest.find(hit.doc_id) or {}
            proof.append({"doc_id": hit.doc_id, "source_refs": entry.get("source_refs", [])})
        return proof

    def _build_l1_answer(self, hits: list[RetrievalHit], wiki_root: Path, manifest: ManifestRepository, manifest_by_doc_id: dict[str, dict] | None = None, topic_index_entries: dict[str, dict] | None = None) -> str:
        if not hits:
            return "No matching knowledge found."
        top_hit = hits[0]
        topic_index_entry = (topic_index_entries or {}).get(top_hit.doc_id) or TopicIndexRepository(wiki_root).find(top_hit.doc_id)
        if topic_index_entry and topic_index_entry.get("summary"):
            summary = str(topic_index_entry["summary"])
            if self._is_l1_content_line(summary):
                return summary
        manifest_entry = (manifest_by_doc_id or {}).get(top_hit.doc_id) or manifest.find(top_hit.doc_id) or {}
        if manifest_entry.get("summary"):
            summary = str(manifest_entry["summary"])
            if self._is_l1_content_line(summary):
                return summary
        page_path = wiki_root / "pages" / f"{top_hit.doc_id}.md"
        if not page_path.exists():
            return f"Top match: {top_hit.doc_id}"
        lines = [line.strip() for line in page_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        for line in lines:
            if self._is_l1_content_line(line):
                return line
        return f"Top match: {top_hit.doc_id}"

    def _is_l1_content_line(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            return False
        unquoted = stripped.lstrip("> ").strip()
        if stripped.startswith(">") and re.search(r"(学习日期|日期|时间|方向|深度|source|date|tags?)\s*[：:]", unquoted, re.IGNORECASE):
            return False
        return True

    def _append_query_outcome(
        self,
        wiki_root: Path,
        actor: ResolvedActor,
        data: QueryInput,
        hits: list[RetrievalHit],
        manifest: ManifestRepository,
        manifest_by_doc_id: dict[str, dict] | None,
        latency_ms: float,
    ) -> None:
        path = wiki_root / "query_outcomes.jsonl"
        query_id = str(uuid.uuid4())
        entry = {
            "query_id": query_id,
            "query": data.query,
            "hit_count": len(hits),
            "actor_id": actor.actor_id,
            "latency_ms": latency_ms,
            "score_breakdown": self._score_breakdown(hits),
            "page_types": self._page_type_distribution(manifest, hits, manifest_by_doc_id),
            "accepted_doc_ids": [],
            "rejected_doc_ids": [],
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

        hits_path = wiki_root / "query_hits.jsonl"
        with hits_path.open("a", encoding="utf-8") as handle:
            for hit in hits:
                handle.write(json.dumps({"query_id": query_id, "doc_id": hit.doc_id}, ensure_ascii=False) + "\n")

    def _score_breakdown(self, hits: list[RetrievalHit], top_k: int = 10) -> list[dict]:
        breakdown = []
        for hit in hits[:top_k]:
            metadata = hit.metadata
            boost = sum(
                float(metadata.get(key, 0.0) or 0.0)
                for key in ("page_type_boost", "purpose_boost", "topic_alignment_boost", "freshness", "manifest_priority")
            )
            breakdown.append(
                {
                    "doc_id": hit.doc_id,
                    "score": hit.score,
                    "fts_score": float(metadata.get("lexical_score", 0.0) or 0.0),
                    "structured_score": float(metadata.get("structured_score", 0.0) or 0.0),
                    "graph_score": float(metadata.get("graph_score", 0.0) or 0.0),
                    "boost": boost,
                }
            )
        return breakdown

    def _rerank_top_k(self, data: QueryInput, multiplier: int) -> int:
        base = data.page_types and 20 or 30
        return max(30, base * multiplier)

    def _seed_purpose_topic_hits(
        self,
        manifest_entries: list[dict],
        purpose_reader: PurposeReader,
        query: str,
        manifest_by_doc_id: dict[str, dict],
        topic_seed_score: float,
    ) -> list[RetrievalHit]:
        purpose = purpose_reader.read()
        matched_topics = [topic for topic in purpose.get("topics", []) if self._query_mentions_topic(query, str(topic))]
        if not matched_topics:
            return []
        matched_keys = {self._topic_key(topic) for topic in matched_topics if self._topic_key(topic)}
        seeded: list[RetrievalHit] = []
        for entry in manifest_entries:
            if entry.get("page_type") not in {PageType.ATOM.value, PageType.SYNTHESIS.value}:
                continue
            topic = str(entry.get("topic") or "")
            if not topic:
                continue
            if self._topic_key(topic) not in matched_keys:
                continue
            doc_id = str(entry.get("doc_id") or "")
            if not doc_id:
                continue
            if doc_id in manifest_by_doc_id and entry.get("page_type") != manifest_by_doc_id[doc_id].get("page_type"):
                continue
            seeded.append(
                RetrievalHit(
                    wiki_id=str(entry.get("wiki_id") or ""),
                    doc_id=doc_id,
                    score=topic_seed_score,
                    metadata={
                        "lexical_score": topic_seed_score,
                        "structured_score": 0.0,
                        "topic_seeded": True,
                    },
                )
            )
        return seeded

    def _merge_hits(self, hits: list[RetrievalHit], seeded_hits: list[RetrievalHit]) -> list[RetrievalHit]:
        merged: dict[str, RetrievalHit] = {hit.doc_id: hit for hit in hits}
        for hit in seeded_hits:
            existing = merged.get(hit.doc_id)
            if existing is None or hit.score > existing.score:
                merged[hit.doc_id] = hit
        return list(merged.values())

    def _query_mentions_topic(self, query: str, topic: str) -> bool:
        query_key = self._topic_key(query)
        topic_key = self._topic_key(topic)
        return bool(query_key and topic_key and topic_key in query_key)

    def _topic_key(self, value: str) -> str:
        return re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "", value).lower()

    def _page_type_distribution(self, manifest: ManifestRepository, hits: list[RetrievalHit], manifest_by_doc_id: dict[str, dict] | None = None) -> dict[str, int]:
        distribution: dict[str, int] = {}
        for hit in hits:
            entry = (manifest_by_doc_id or {}).get(hit.doc_id) or manifest.find(hit.doc_id) or {}
            page_type = str(entry.get("page_type") or "unknown")
            distribution[page_type] = distribution.get(page_type, 0) + 1
        return distribution


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
