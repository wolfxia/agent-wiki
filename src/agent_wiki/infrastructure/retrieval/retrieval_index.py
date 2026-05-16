import json
from pathlib import Path

from agent_wiki.domain.contracts import RetrievalHit
from agent_wiki.domain.models import CompileUpdateInput


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
        terms = [term.lower() for term in query.split() if term.strip()]
        hits: list[RetrievalHit] = []
        for line in self.index_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            card = json.loads(line)
            content = " ".join(
                [
                    str(card.get("topic", "")),
                    str(card.get("problem_cluster", "")),
                    str(card.get("content", "")),
                ]
            ).lower()
            score = sum(1 for term in terms if term in content)
            if score:
                hits.append(
                    RetrievalHit(
                        wiki_id=card["wiki_id"],
                        doc_id=card["doc_id"],
                        score=float(score),
                    )
                )
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits
