from pathlib import Path

from agent_wiki.infrastructure.storage.purpose_reader import PurposeReader


def test_purpose_reader_parses_structured_intent(temp_wiki_root: Path) -> None:
    purpose_path = temp_wiki_root / "purpose.md"
    purpose_path.write_text(
        "# Purpose\n\n"
        "## Topics\n\n"
        "- deployment\n"
        "- observability\n"
        "- testing\n\n"
        "## Goals\n\n"
        "- Capture deployment best practices\n"
        "- Track observability patterns\n",
        encoding="utf-8",
    )

    reader = PurposeReader(temp_wiki_root)
    purpose = reader.read()

    assert purpose["topics"] == ["deployment", "observability", "testing"]
    assert len(purpose["goals"]) == 2
    assert "deployment" in purpose["goals"][0].lower()


def test_purpose_reader_returns_empty_when_no_file(temp_wiki_root: Path) -> None:
    reader = PurposeReader(temp_wiki_root)
    purpose = reader.read()

    assert purpose["topics"] == []
    assert purpose["goals"] == []


def test_purpose_reader_topic_alignment_check(temp_wiki_root: Path) -> None:
    purpose_path = temp_wiki_root / "purpose.md"
    purpose_path.write_text(
        "# Purpose\n\n## Topics\n\n- deployment\n- security\n",
        encoding="utf-8",
    )

    reader = PurposeReader(temp_wiki_root)

    assert reader.is_aligned("deployment")
    assert reader.is_aligned("security")
    assert not reader.is_aligned("unrelated-topic")
