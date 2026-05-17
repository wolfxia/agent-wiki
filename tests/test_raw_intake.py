from agent_wiki.infrastructure.intake.raw_intake import normalize_raw_intake


def test_normalize_raw_intake_fills_low_confidence_defaults() -> None:
    normalized = normalize_raw_intake(
        {
            "doc_id": "raw-1",
            "content": "# Example\n\nBody text.",
            "source_type": "capture_raw",
        }
    )

    assert normalized["doc_id"] == "raw-1"
    assert normalized["topic"] != ""
    assert normalized["problem_cluster"] != ""
    assert normalized["summary"] != ""
    assert normalized["classification_confidence"] in {"low", "medium"}
