from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.application.query import QueryInput, QueryService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.infrastructure.retrieval.fuzzy import fuzzy_match
from agent_wiki.infrastructure.retrieval.tokenizer import tokenize


def test_query_returns_relevant_hit_from_lexical_index(temp_wiki_root: Path) -> None:
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
            doc_id="raw-query-2",
            topic="testing",
            problem_cluster="cluster-q2",
            content="# Raw query two",
            source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="synthesis-query-2",
            page_type="synthesis",
            topic="testing",
            problem_cluster="cluster-q2",
            content="# Synthesis query two\n\nLexical retrieval is the baseline provider.",
            source_refs=["personal-1:raw-query-2"],
        ),
    )

    result = query_service.execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="lexical retrieval baseline"),
    )

    assert result.hits[0].doc_id == "synthesis-query-2"
    assert result.hits[0].wiki_id == "personal-1"


def test_tokenize_splits_cjk_and_latin() -> None:
    tokens = tokenize("Python部署策略")

    assert "python" in tokens
    assert "部署" in tokens
    assert "策略" in tokens
    assert len(tokens) >= 3


def test_lexical_search_finds_chinese_content(temp_wiki_root: Path) -> None:
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
            doc_id="raw-query-cjk-1",
            topic="部署",
            problem_cluster="策略",
            content="# 原始记录",
            source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="synthesis-query-cjk-1",
            page_type="synthesis",
            topic="部署",
            problem_cluster="策略",
            content="# 综合\n\nPython部署策略需要灰度发布。",
            source_refs=["personal-1:raw-query-cjk-1"],
        ),
    )

    result = query_service.execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="Python部署策略"),
    )

    assert result.hits[0].doc_id == "synthesis-query-cjk-1"


def test_fuzzy_match_finds_near_miss_terms() -> None:
    assert fuzzy_match("deployability", "deployablity")
    assert not fuzzy_match("deployability", "runtime")


def test_lexical_search_returns_fuzzy_hits(temp_wiki_root: Path) -> None:
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
            doc_id="raw-query-fuzzy-1",
            topic="testing",
            problem_cluster="cluster-fuzzy",
            content="# Raw query fuzzy",
            source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="synthesis-query-fuzzy-1",
            page_type="synthesis",
            topic="testing",
            problem_cluster="cluster-fuzzy",
            content="# Synthesis query fuzzy\n\nDeployability depends on release automation.",
            source_refs=["personal-1:raw-query-fuzzy-1"],
        ),
    )

    result = query_service.execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="deployablity"),
    )

    assert result.hits[0].doc_id == "synthesis-query-fuzzy-1"
