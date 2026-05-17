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
