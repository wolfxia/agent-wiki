import json
from pathlib import Path

from agent_wiki.domain.contracts import RetrievalHit
from agent_wiki.domain.models import CompileUpdateInput
from agent_wiki.infrastructure.retrieval.fuzzy import fuzzy_match
from agent_wiki.infrastructure.retrieval.tokenizer import tokenize


class RetrievalIndexRepository:
    def __init__(self, wiki_root: Path) -> None:
        self.index_path = wiki_root / "retrieval_index.jsonl"

    def append_raw_card(self, wiki_id: str, data: CompileUpdateInput | object) -> None:
        card = {
            "wiki_id": wiki_id,
            "doc_id": data.doc_id,
            "page_type": "raw",
            "topic": data.topic,
            "problem_cluster": data.problem_cluster,
            "content": data.content,
        }
        with self.index_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(card, ensure_ascii=False) + "\n")

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

    def lexical_search(self, query: str) -> list[RetrievalHit]:
        if not self.index_path.exists():
            return []
        terms = tokenize(query)
        hits: list[RetrievalHit] = []
        for line in self.index_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            card = json.loads(line)
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
                hits.append(
                    RetrievalHit(
                        wiki_id=card["wiki_id"],
                        doc_id=card["doc_id"],
                        score=score,
                    )
                )
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits
