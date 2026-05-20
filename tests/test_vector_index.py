from pathlib import Path

import numpy as np

from agent_wiki.infrastructure.retrieval.vector_index import SQLiteVectorIndexProvider


def test_vector_index_upsert_search_and_delete(temp_wiki_root: Path) -> None:
    provider = SQLiteVectorIndexProvider(temp_wiki_root, wiki_id="personal-1", dimension=4)

    provider.upsert(
        "atom-vector-1",
        {
            "wiki_id": "personal-1",
            "doc_id": "atom-vector-1",
            "page_type": "atom",
            "embedding": np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
            "updated_at": "2026-05-20T00:00:00Z",
        },
    )
    provider.upsert(
        "raw-vector-2",
        {
            "wiki_id": "personal-1",
            "doc_id": "raw-vector-2",
            "page_type": "raw",
            "embedding": np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32),
            "updated_at": "2026-05-20T00:00:00Z",
        },
    )

    hits = provider.search(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32), top_k=5)

    assert hits
    assert hits[0].doc_id == "atom-vector-1"
    assert hits[0].section == "vector"
    assert hits[0].metadata["semantic_score"] > 0.99

    raw_only = provider.search(
        np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32),
        top_k=5,
        filters={"page_types": ["raw"]},
    )
    assert [hit.doc_id for hit in raw_only] == ["raw-vector-2"]

    provider.delete("raw-vector-2")
    after_delete = provider.search(
        np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32),
        top_k=5,
    )
    assert all(hit.doc_id != "raw-vector-2" for hit in after_delete)


def test_vector_index_get_embedding_returns_array_or_none(temp_wiki_root: Path) -> None:
    provider = SQLiteVectorIndexProvider(temp_wiki_root, wiki_id="personal-1", dimension=4)

    provider.upsert(
        "atom-vector-get-1",
        {
            "wiki_id": "personal-1",
            "doc_id": "atom-vector-get-1",
            "page_type": "atom",
            "embedding": np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32),
            "updated_at": "2026-05-20T00:00:00Z",
        },
    )

    embedding = provider.get_embedding("atom-vector-get-1")
    missing = provider.get_embedding("missing-doc")

    assert embedding is not None
    assert embedding.dtype == np.float32
    assert np.allclose(embedding, np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32))
    assert missing is None
