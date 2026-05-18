from pathlib import Path

from agent_wiki.infrastructure.retrieval.sqlite_fts import SQLiteFTSIndexProvider


def test_sqlite_fts_upsert_search_and_delete(temp_wiki_root: Path) -> None:
    provider = SQLiteFTSIndexProvider(temp_wiki_root, wiki_id="personal-1")

    provider.upsert(
        "raw-fts-1",
        {
            "wiki_id": "personal-1",
            "doc_id": "raw-fts-1",
            "page_type": "raw",
            "topic": "deployment",
            "problem_cluster": "canary",
            "summary": "Canary rollout checklist",
            "content": "Use staged canary rollout for risky deploys.",
            "sensitivity": "public",
        },
    )

    hits = provider.search("canary rollout", top_k=5)

    assert (temp_wiki_root / ".agent-wiki" / "retrieval.db").exists()
    assert hits
    assert hits[0].doc_id == "raw-fts-1"
    assert hits[0].section == "fts5"

    provider.delete("raw-fts-1")

    assert provider.search("canary rollout", top_k=5) == []


def test_sqlite_fts_upsert_is_idempotent(temp_wiki_root: Path) -> None:
    provider = SQLiteFTSIndexProvider(temp_wiki_root, wiki_id="personal-1")
    payload = {
        "wiki_id": "personal-1",
        "doc_id": "raw-fts-1",
        "page_type": "raw",
        "topic": "ops",
        "problem_cluster": "cleanup",
        "summary": "Old summary",
        "content": "old searchable content",
    }

    provider.upsert("raw-fts-1", payload)
    provider.upsert("raw-fts-1", {**payload, "summary": "New summary", "content": "new searchable content"})

    hits = provider.search("searchable", top_k=10)

    assert [hit.doc_id for hit in hits] == ["raw-fts-1"]


def test_sqlite_fts_batch_upsert_reuses_schema_and_connection(temp_wiki_root: Path, monkeypatch) -> None:
    provider = SQLiteFTSIndexProvider(temp_wiki_root, wiki_id="personal-1")
    ensure_calls = 0
    connect_calls = 0
    original_ensure_schema = provider._ensure_schema
    original_connect = provider._connect

    def counting_ensure_schema() -> None:
        nonlocal ensure_calls
        ensure_calls += 1
        original_ensure_schema()

    def counting_connect():
        nonlocal connect_calls
        connect_calls += 1
        return original_connect()

    monkeypatch.setattr(provider, "_ensure_schema", counting_ensure_schema)
    monkeypatch.setattr(provider, "_connect", counting_connect)

    provider.batch_upsert(
        [
            (
                "raw-batch-1",
                {
                    "wiki_id": "personal-1",
                    "doc_id": "raw-batch-1",
                    "page_type": "raw",
                    "topic": "ops",
                    "problem_cluster": "batch",
                    "content": "first batch searchable",
                },
            ),
            (
                "raw-batch-2",
                {
                    "wiki_id": "personal-1",
                    "doc_id": "raw-batch-2",
                    "page_type": "raw",
                    "topic": "ops",
                    "problem_cluster": "batch",
                    "content": "second batch searchable",
                },
            ),
        ]
    )

    assert ensure_calls == 1
    assert connect_calls == 2
    assert {hit.doc_id for hit in provider.search("batch searchable", top_k=10)} == {"raw-batch-1", "raw-batch-2"}


def test_sqlite_fts_write_normalized_uses_explicit_transaction(temp_wiki_root: Path, monkeypatch) -> None:
    provider = SQLiteFTSIndexProvider(temp_wiki_root, wiki_id="personal-1")
    calls: list[str] = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def execute(self, statement, params=None):
            calls.append(statement)

        def executemany(self, statement, params):
            calls.append(statement)

    monkeypatch.setattr(provider, "_connect", lambda: FakeConnection())

    provider._write_normalized(
        [
            {
                "doc_id": "raw-explicit-txn",
                "wiki_id": "personal-1",
                "page_type": "raw",
                "topic": "ops",
                "problem_cluster": "txn",
                "summary": "",
                "content": "transaction content",
                "tokens": "transaction content",
                "sensitivity": "",
                "updated_at": "1",
            }
        ]
    )

    assert calls[0] == "BEGIN IMMEDIATE"


def test_sqlite_fts_rebuilds_from_manifest_pages(temp_wiki_root: Path) -> None:
    pages = temp_wiki_root / "pages"
    pages.mkdir(exist_ok=True)
    (pages / "raw-keep.md").write_text("# Keep\n\nFTS rebuild content.", encoding="utf-8")
    provider = SQLiteFTSIndexProvider(temp_wiki_root, wiki_id="personal-1")
    provider.upsert("raw-stale", {"wiki_id": "personal-1", "doc_id": "raw-stale", "content": "stale"})

    provider.rebuild_from_manifest([
        {
            "wiki_id": "personal-1",
            "doc_id": "raw-keep",
            "page_type": "raw",
            "topic": "ops",
            "problem_cluster": "cleanup",
            "summary": "keep summary",
            "canonical_uri": "pages/raw-keep.md",
        }
    ])

    assert [hit.doc_id for hit in provider.search("rebuild", top_k=10)] == ["raw-keep"]
    assert provider.search("stale", top_k=10) == []


def test_sqlite_fts_uses_pre_tokenized_text_for_chinese_terms(temp_wiki_root: Path) -> None:
    from agent_wiki.infrastructure.retrieval.tokenizer import JiebaTokenizer

    class FakeTokenizer:
        def tokenize(self, text: str) -> list[str]:
            return ["鸿蒙", "策略"] if "鸿蒙" in text else [text]

    provider = SQLiteFTSIndexProvider(temp_wiki_root, wiki_id="personal-1", tokenizer=FakeTokenizer())
    provider.upsert(
        "raw-harmony",
        {
            "wiki_id": "personal-1",
            "doc_id": "raw-harmony",
            "page_type": "raw",
            "topic": "鸿蒙策略",
            "problem_cluster": "OS",
            "summary": "鸿蒙生态策略",
            "content": "鸿蒙策略不应该被错误切成蒙策。",
        },
    )

    hits = provider.search("鸿蒙", top_k=5)

    assert hits
    assert hits[0].doc_id == "raw-harmony"
    assert isinstance(JiebaTokenizer(), JiebaTokenizer)
