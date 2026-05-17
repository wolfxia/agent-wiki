from agent_wiki.domain.models import CompileUpdateInput


def test_compile_update_input_supports_retrieval_ready_fields() -> None:
    schema = CompileUpdateInput.model_json_schema()

    for field in ["summary", "aliases", "confidence", "contested", "wikilinks"]:
        assert field in schema["properties"]
