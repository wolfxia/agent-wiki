from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.application.query import QueryInput, QueryService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import QueryClassifier, ResolvedActor
from agent_wiki.infrastructure.query.classifier import RuleBasedQueryClassifier


def test_rule_based_query_classifier_is_default_classifier() -> None:
    classifier = RuleBasedQueryClassifier()

    assert isinstance(classifier, QueryClassifier)
    assert classifier.classify("why does this work") == "concept_explain"


def test_query_classifies_fact_lookup_from_simple_question(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    query_service = QueryService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    capture_service.execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-query-1",
            topic="testing",
            problem_cluster="cluster-q1",
            content="# Raw query one",
            source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-query-1",
            page_type="atom",
            topic="testing",
            problem_cluster="cluster-q1",
            content="# Atom query one\n\nPytest uses assert rewriting.",
            source_refs=["personal-1:raw-query-1"],
        ),
    )

    result = query_service.execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="What does pytest use?"),
    )

    assert result.query_type == "fact_lookup"
    assert result.l1_answer
