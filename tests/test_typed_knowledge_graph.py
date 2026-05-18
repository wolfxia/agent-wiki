import json
from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.maintenance import MaintenanceService
from agent_wiki.application.query import QueryInput, QueryService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.infrastructure.retrieval.knowledge_graph import RelationExtractor, RelationTypeDefinition


def _wiki(temp_wiki_root: Path):
    return RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )


def _actor() -> ResolvedActor:
    return ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")


def test_maintain_extracts_configured_typed_relations_from_raw_pages(temp_wiki_root: Path) -> None:
    (temp_wiki_root / "relation_schema.yaml").write_text(
        """relation_types:
  - name: works_at
    patterns:
      - "(?P<person>.+?) works at (?P<org>.+)"
    subject_type: person
    object_type: organization
  - name: founded
    patterns:
      - "(?P<person>.+?) founded (?P<org>.+)"
    subject_type: person
    object_type: organization
  - name: invested_in
    patterns:
      - "(?P<investor>.+?) invested in (?P<company>.+)"
    subject_type: organization
    object_type: organization
  - name: competes_with
    patterns:
      - "(?P<a>.+?) competes with (?P<b>.+)"
    subject_type: organization
    object_type: organization
    symmetric: true
  - name: depends_on
    patterns:
      - "(?P<a>.+?) depends on (?P<b>.+)"
    subject_type: technology
    object_type: technology
""",
        encoding="utf-8",
    )
    wiki = _wiki(temp_wiki_root)
    CaptureRawService().execute(
        wiki=wiki,
        actor=_actor(),
        data=CaptureRawInput(
            doc_id="raw-typed-graph",
            topic="graph",
            problem_cluster="typed-relations",
            content=(
                "# Typed relations\n"
                "Ada Lovelace works at Analytical Engines Lab.\n"
                "Grace Hopper founded COBOL Tools.\n"
                "YC invested in OpenAI.\n"
                "Huawei competes with Apple.\n"
                "Agent Wiki depends on SQLite.\n"
            ),
            source_refs=[],
        ),
    )

    summary = MaintenanceService().run(wiki)

    assert summary["typed_relations"] == 6
    graph_path = temp_wiki_root / "knowledge_graph.jsonl"
    entries = [json.loads(line) for line in graph_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    relation_keys = {(entry["subject"], entry["relation"], entry["object"]) for entry in entries}
    assert ("Ada Lovelace", "works_at", "Analytical Engines Lab") in relation_keys
    assert ("Grace Hopper", "founded", "COBOL Tools") in relation_keys
    assert ("YC", "invested_in", "OpenAI") in relation_keys
    assert ("Huawei", "competes_with", "Apple") in relation_keys
    assert ("Apple", "competes_with", "Huawei") in relation_keys
    assert ("Agent Wiki", "depends_on", "SQLite") in relation_keys
    assert all(entry["source_doc_id"] == "raw-typed-graph" for entry in entries)


def test_query_uses_typed_graph_hits_when_knowledge_graph_exists(temp_wiki_root: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    CaptureRawService().execute(
        wiki=wiki,
        actor=_actor(),
        data=CaptureRawInput(
            doc_id="raw-graph-query",
            topic="graph",
            problem_cluster="query",
            content="# Graph Query\nOpenAI evidence lives here.",
            source_refs=[],
        ),
    )
    (temp_wiki_root / "knowledge_graph.jsonl").write_text(
        json.dumps(
            {
                "subject": "YC",
                "relation": "invested_in",
                "object": "OpenAI",
                "subject_type": "organization",
                "object_type": "organization",
                "source_doc_id": "raw-graph-query",
                "confidence": 1.0,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = QueryService().execute(wiki=wiki, actor=_actor(), data=QueryInput(query="YC invested in OpenAI"))

    assert result.hits[0].doc_id == "raw-graph-query"
    assert result.hits[0].section == "knowledge_graph"
    assert result.hits[0].metadata["graph_relation"] == "invested_in"


def test_query_can_use_each_configured_relation_type(temp_wiki_root: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    for doc_id in ["raw-works", "raw-founded", "raw-invested", "raw-competes", "raw-depends"]:
        CaptureRawService().execute(
            wiki=wiki,
            actor=_actor(),
            data=CaptureRawInput(
                doc_id=doc_id,
                topic="graph",
                problem_cluster="query-types",
                content=f"# {doc_id}\nGraph source {doc_id}",
                source_refs=[],
            ),
        )
    graph_entries = [
        {"subject": "Ada Lovelace", "relation": "works_at", "object": "Analytical Engines Lab", "source_doc_id": "raw-works"},
        {"subject": "Grace Hopper", "relation": "founded", "object": "COBOL Tools", "source_doc_id": "raw-founded"},
        {"subject": "YC", "relation": "invested_in", "object": "OpenAI", "source_doc_id": "raw-invested"},
        {"subject": "Huawei", "relation": "competes_with", "object": "Apple", "source_doc_id": "raw-competes"},
        {"subject": "Agent Wiki", "relation": "depends_on", "object": "SQLite", "source_doc_id": "raw-depends"},
    ]
    (temp_wiki_root / "knowledge_graph.jsonl").write_text(
        "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in graph_entries),
        encoding="utf-8",
    )

    query_to_doc = {
        "Ada Lovelace works at Analytical Engines Lab": "raw-works",
        "Grace Hopper founded COBOL Tools": "raw-founded",
        "YC invested in OpenAI": "raw-invested",
        "Huawei competes with Apple": "raw-competes",
        "Agent Wiki depends on SQLite": "raw-depends",
    }
    for query, expected_doc_id in query_to_doc.items():
        result = QueryService().execute(wiki=wiki, actor=_actor(), data=QueryInput(query=query))
        assert result.hits[0].doc_id == expected_doc_id
        assert result.hits[0].section == "knowledge_graph"


def _extractor(*definitions: RelationTypeDefinition) -> RelationExtractor:
    return RelationExtractor(list(definitions))


def test_relation_extractor_ignores_markdown_table_rows() -> None:
    extractor = _extractor(
        RelationTypeDefinition(
            name="depends_on",
            patterns=(r"(?P<a>.+?) depends on (?P<b>.+)",),
            subject_type="technology",
            object_type="technology",
        )
    )

    relations = extractor.extract(
        text="| **路径规划** | depends on SLAM 地图的路径规划 |",
        source_doc_id="raw-markdown-table",
        extracted_at="2026-05-18T00:00:00Z",
    )

    assert relations == []


def test_relation_extractor_ignores_list_markers_as_entities() -> None:
    extractor = _extractor(
        RelationTypeDefinition(
            name="depends_on",
            patterns=(r"(?P<a>.+?) depends on (?P<b>.+)",),
            subject_type="technology",
            object_type="technology",
        )
    )

    relations = extractor.extract(
        text=(
            "- token depends on h\n"
            "1. **系统定位** - depends on Android 16\n"
            "TensorRT depends on CUDA\n"
        ),
        source_doc_id="raw-list-markers",
        extracted_at="2026-05-18T00:00:00Z",
    )

    assert [(relation["subject"], relation["object"]) for relation in relations] == [("TensorRT", "CUDA")]


def test_relation_extractor_filters_empty_single_character_and_symbol_entities() -> None:
    extractor = _extractor(
        RelationTypeDefinition(
            name="works_at",
            patterns=(r"(?P<person>.*?) works at (?P<org>.+)",),
            subject_type="person",
            object_type="organization",
        )
    )

    relations = extractor.extract(
        text=(
            " works at OpenAI\n"
            "A works at OpenAI\n"
            "> works at A\n"
            "Ada Lovelace works at Analytical Engines Lab\n"
        ),
        source_doc_id="raw-short-entities",
        extracted_at="2026-05-18T00:00:00Z",
    )

    assert [(relation["subject"], relation["object"]) for relation in relations] == [
        ("Ada Lovelace", "Analytical Engines Lab")
    ]


def test_relation_extractor_keeps_meaningful_chinese_relations() -> None:
    extractor = _extractor(
        RelationTypeDefinition(
            name="competes_with",
            patterns=(r"(?P<a>[\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9 ._-]*?) (?:与|和) (?P<b>[\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9 ._-]*?) (?:竞争|对标)",),
            subject_type="organization",
            object_type="organization",
            symmetric=True,
        ),
        RelationTypeDefinition(
            name="depends_on",
            patterns=(r"(?P<a>[\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9 ._-]*?) (?:依赖|基于) (?P<b>[\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9 ._-]*)",),
            subject_type="technology",
            object_type="technology",
        ),
    )

    relations = extractor.extract(
        text="华为 与 苹果 竞争\n鸿蒙 依赖 Linux",
        source_doc_id="raw-chinese-relations",
        extracted_at="2026-05-18T00:00:00Z",
    )

    relation_keys = {(relation["subject"], relation["relation"], relation["object"]) for relation in relations}
    assert ("华为", "competes_with", "苹果") in relation_keys
    assert ("苹果", "competes_with", "华为") in relation_keys
    assert ("鸿蒙", "depends_on", "Linux") in relation_keys
