from pathlib import Path

from typer.testing import CliRunner

from agent_wiki.transports.cli.app import app


def test_migrate_slugify_doc_ids_updates_indexes_and_is_idempotent(temp_wiki_root: Path) -> None:
    (temp_wiki_root / "pages").mkdir(exist_ok=True)
    (temp_wiki_root / "pages" / "old-note.md").write_text("# Old", encoding="utf-8")
    (temp_wiki_root / "MANIFEST.jsonl").write_text(
        '{"wiki_id":"personal-1","doc_id":"old-note","page_type":"raw","canonical_uri":"pages/old-note.md","vault_relative_path":"agent-os/old-note.md","topic":"agent-os","problem_cluster":"agent-os","summary":"Old summary"}\n',
        encoding="utf-8",
    )
    (temp_wiki_root / "retrieval_index.jsonl").write_text(
        '{"wiki_id":"personal-1","doc_id":"old-note","page_type":"raw","topic":"agent-os","problem_cluster":"agent-os","content":"Old content"}\n',
        encoding="utf-8",
    )
    (temp_wiki_root / "topic_index.md").write_text(
        "| doc_id | page_type | topic | problem_cluster | summary |\n| --- | --- | --- | --- | --- |\n| old-note | raw | agent-os | agent-os | Old summary |\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["migrate", "--slugify-doc-ids", "--workspace", str(temp_wiki_root)])
    second = runner.invoke(app, ["migrate", "--slugify-doc-ids", "--workspace", str(temp_wiki_root)])

    assert result.exit_code == 0
    assert second.exit_code == 0
    assert (temp_wiki_root / "MANIFEST.jsonl.pre-migration").exists()
    assert (temp_wiki_root / "pages" / "agent-os_old-note.md").exists()
    assert not (temp_wiki_root / "pages" / "old-note.md").exists()
    manifest = (temp_wiki_root / "MANIFEST.jsonl").read_text(encoding="utf-8")
    retrieval_index = (temp_wiki_root / "retrieval_index.jsonl").read_text(encoding="utf-8")
    topic_index = (temp_wiki_root / "topic_index.md").read_text(encoding="utf-8")
    assert '"doc_id": "agent-os_old-note"' in manifest
    assert '"canonical_uri": "pages/agent-os_old-note.md"' in manifest
    assert '"doc_id": "agent-os_old-note"' in retrieval_index
    assert "| agent-os_old-note | raw | agent-os | agent-os | Old summary |" in topic_index
    assert manifest.count("agent-os_old-note") == (temp_wiki_root / "MANIFEST.jsonl").read_text(encoding="utf-8").count("agent-os_old-note")


def test_migrate_normalize_doc_ids_updates_authority_indexes_pages_and_refs(temp_wiki_root: Path) -> None:
    import json

    from agent_wiki.infrastructure.retrieval.sqlite_fts import SQLiteFTSIndexProvider

    pages = temp_wiki_root / "pages"
    pages.mkdir(exist_ok=True)
    (pages / "AI Agent Notes.md").write_text(
        "# AI Agent Notes\n\nsource_refs: [personal-1:Raw Source Note]\nSee personal-1:Raw Source Note.",
        encoding="utf-8",
    )
    (pages / "Raw Source Note.md").write_text("# Raw Source Note\n\nEvidence body.", encoding="utf-8")
    manifest_entries = [
        {
            "wiki_id": "personal-1",
            "doc_id": "Raw Source Note",
            "page_type": "raw",
            "topic": "AI Agents",
            "problem_cluster": "Source Notes",
            "summary": "Source summary",
            "canonical_uri": "pages/Raw Source Note.md",
        },
        {
            "wiki_id": "personal-1",
            "doc_id": "AI Agent Notes",
            "page_type": "atom",
            "topic": "AI Agents",
            "problem_cluster": "Agent Notes",
            "summary": "Atom summary",
            "canonical_uri": "pages/AI Agent Notes.md",
            "source_refs": ["personal-1:Raw Source Note"],
        },
    ]
    (temp_wiki_root / "MANIFEST.jsonl").write_text(
        "\n".join(json.dumps(entry, ensure_ascii=False) for entry in manifest_entries) + "\n",
        encoding="utf-8",
    )
    (temp_wiki_root / "retrieval_index.jsonl").write_text(
        json.dumps({"wiki_id": "personal-1", "doc_id": "AI Agent Notes", "page_type": "atom", "content": "AI Agent Notes content"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (temp_wiki_root / "topic_index.md").write_text(
        "| doc_id | page_type | topic | problem_cluster | summary |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| AI Agent Notes | atom | AI Agents | Agent Notes | Atom summary |\n",
        encoding="utf-8",
    )
    SQLiteFTSIndexProvider(temp_wiki_root, wiki_id="personal-1").upsert(
        "AI Agent Notes",
        {"wiki_id": "personal-1", "doc_id": "AI Agent Notes", "page_type": "atom", "content": "AI Agent Notes content"},
    )

    runner = CliRunner()
    result = runner.invoke(app, ["migrate", "--normalize-doc-ids", "--workspace", str(temp_wiki_root)])
    second = runner.invoke(app, ["migrate", "--normalize-doc-ids", "--workspace", str(temp_wiki_root)])

    assert result.exit_code == 0
    assert second.exit_code == 0
    assert "changed_count=2" in result.stdout
    assert "changed_count=0" in second.stdout
    assert (temp_wiki_root / "MANIFEST.jsonl.pre-doc-id-normalization").exists()
    assert (pages / "ai-agent-notes.md").exists()
    assert (pages / "raw-source-note.md").exists()
    assert not (pages / "AI Agent Notes.md").exists()
    manifest = (temp_wiki_root / "MANIFEST.jsonl").read_text(encoding="utf-8")
    retrieval_index = (temp_wiki_root / "retrieval_index.jsonl").read_text(encoding="utf-8")
    topic_index = (temp_wiki_root / "topic_index.md").read_text(encoding="utf-8")
    page_text = (pages / "ai-agent-notes.md").read_text(encoding="utf-8")
    fts_hits = SQLiteFTSIndexProvider(temp_wiki_root, wiki_id="personal-1").search("Agent", top_k=5)

    assert '"doc_id": "ai-agent-notes"' in manifest
    assert '"canonical_uri": "pages/ai-agent-notes.md"' in manifest
    assert '"source_refs": ["personal-1:raw-source-note"]' in manifest
    assert '"doc_id": "ai-agent-notes"' in retrieval_index
    assert "| ai-agent-notes | atom | AI Agents | Agent Notes | Atom summary |" in topic_index
    assert "personal-1:raw-source-note" in page_text
    assert "Raw Source Note" not in page_text
    assert any(hit.doc_id == "ai-agent-notes" for hit in fts_hits)


def test_normalize_doc_id_uses_lowercase_hyphen_style() -> None:
    from agent_wiki.infrastructure.doc_id import normalize_doc_id
    from agent_wiki.domain.validators import validate_doc_id

    assert normalize_doc_id("2026-04-06-AI-inference-optimization-notes") == "2026-04-06-ai-inference-optimization-notes"
    normalized_chinese = normalize_doc_id("IoT OS - 辩证讨论核心结论 2026-04-25")
    normalized_mixed = normalize_doc_id("agent-os_2026-04-15_MCP协议")

    assert normalized_chinese.startswith("iot-os-")
    assert normalized_chinese.endswith("-2026-04-25")
    assert normalized_chinese.isascii()
    assert normalized_mixed.startswith("agent-os-2026-04-15-mcp-")
    assert normalized_mixed.isascii()
    validate_doc_id(normalized_chinese)
    validate_doc_id(normalized_mixed)


def test_normalize_doc_id_handles_chinese_compile_suggestion_ids() -> None:
    from agent_wiki.infrastructure.doc_id import normalize_doc_id
    from agent_wiki.domain.validators import validate_doc_id

    doc_id = f"atom-{normalize_doc_id('external_sync')}-{normalize_doc_id('AI推理优化:cluster:AI推理优化')}-0009"

    assert doc_id.isascii()
    assert "推理" not in doc_id
    validate_doc_id(doc_id)
