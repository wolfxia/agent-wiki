import json
from pathlib import Path

from agent_wiki.domain.contracts import RetrievalHit
from agent_wiki.domain.models import CompileUpdateInput
from agent_wiki.infrastructure.retrieval.fuzzy import fuzzy_match
from agent_wiki.infrastructure.retrieval.tokenizer import tokenize


class LexicalRetrievalProvider:
    def __init__(self, repository_cls: type["RetrievalIndexRepository"]) -> None:
        self.repository_cls = repository_cls

    def build(self, wiki_root: Path) -> "RetrievalIndexRepository":
        return self.repository_cls(wiki_root)

    def search(self, wiki_root: Path, query: str) -> list[RetrievalHit]:
        return self.build(wiki_root).lexical_search(query)


class RetrievalIndexRepository:
    def __init__(self, wiki_root: Path) -> None:
        self.index_path = wiki_root / "retrieval_index.jsonl"

    def append_raw_card(self, wiki_id: str, data: CompileUpdateInput | object) -> None:
        self.append_raw_cards(wiki_id, [data])

    def append_raw_cards(self, wiki_id: str, items: list[CompileUpdateInput | object]) -> None:
        if not items:
            return
        with self.index_path.open("a", encoding="utf-8") as handle:
            for data in items:
                handle.write(json.dumps(self._raw_card(wiki_id, data), ensure_ascii=False) + "\n")

    def _raw_card(self, wiki_id: str, data: CompileUpdateInput | object) -> dict:
        card = {
            "wiki_id": wiki_id,
            "doc_id": data.doc_id,
            "page_type": "raw",
            "topic": data.topic,
            "problem_cluster": data.problem_cluster,
            "content": data.content,
        }
        return card

    def append_compiled_card(self, wiki_id: str, data: CompileUpdateInput) -> None:
        card = {
            "wiki_id": wiki_id,
            "doc_id": data.doc_id,
            "page_type": data.page_type,
            "topic": data.topic,
            "problem_cluster": data.problem_cluster,
            "content": data.content,
        }
        with self.index_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(card, ensure_ascii=False) + "\n")

    def rebuild_from_manifest(self, manifest_entries: list[dict]) -> None:
        wiki_root = self.index_path.parent
        with self.index_path.open("w", encoding="utf-8") as handle:
            for entry in manifest_entries:
                canonical_uri = entry.get("canonical_uri")
                if not canonical_uri:
                    continue
                page_path = wiki_root / str(canonical_uri)
                if not page_path.exists() or not page_path.is_file():
                    continue
                card = {
                    "wiki_id": entry.get("wiki_id"),
                    "doc_id": entry.get("doc_id"),
                    "page_type": entry.get("page_type"),
                    "topic": entry.get("topic"),
                    "problem_cluster": entry.get("problem_cluster"),
                    "summary": entry.get("summary"),
                    "content": page_path.read_text(encoding="utf-8"),
                }
                if entry.get("sensitivity") is not None:
                    card["sensitivity"] = entry.get("sensitivity")
                handle.write(json.dumps(card, ensure_ascii=False) + "\n")

    def lexical_search(self, query: str) -> list[RetrievalHit]:
        if not self.index_path.exists():
            return []
        terms = tokenize(query)
        lowercase_terms = [term.lower() for term in terms if term]
        hits: list[RetrievalHit] = []
        for line in self.index_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            card = json.loads(line)
            searchable_text = " ".join(
                str(card.get(field, ""))
                for field in ("topic", "problem_cluster", "summary", "content")
            ).lower()
            if lowercase_terms and not self._might_match(searchable_text, lowercase_terms):
                continue
            topic_tokens = tokenize(str(card.get("topic", "")))
            problem_cluster_tokens = tokenize(str(card.get("problem_cluster", "")))
            content_tokens = tokenize(str(card.get("content", "")))
            score = 0.0
            for term in terms:
                if term in topic_tokens:
                    score += 3.0
                    continue
                if term in problem_cluster_tokens:
                    score += 2.0
                    continue
                if term in content_tokens:
                    score += 1.0
                    continue
                if any(fuzzy_match(token, term) for token in topic_tokens):
                    score += 1.5
                    continue
                if any(fuzzy_match(token, term) for token in problem_cluster_tokens):
                    score += 1.0
                    continue
                if any(fuzzy_match(token, term) for token in content_tokens):
                    score += 0.5
            if score:
                doc_id = card.get("doc_id")
                if not doc_id:
                    continue
                hits.append(
                    RetrievalHit(
                        wiki_id=card.get("wiki_id") or "",
                        doc_id=doc_id,
                        score=score,
                    )
                )
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits

    def _might_match(self, searchable_text: str, terms: list[str]) -> bool:
        for term in terms:
            if term in searchable_text:
                return True
            if len(term) >= 5 and term[:5] in searchable_text:
                return True
        return False
