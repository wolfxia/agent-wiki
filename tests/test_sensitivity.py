import json
from pathlib import Path

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.domain.enums import Sensitivity
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository


def test_sensitivity_enum_values() -> None:
    assert Sensitivity.PUBLIC == "public"
    assert Sensitivity.INTERNAL == "internal"
    assert Sensitivity.CONFIDENTIAL == "confidential"
    assert len(Sensitivity) == 3


def test_compile_update_preserves_sensitivity_in_manifest(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    capture_service.execute(
        wiki=wiki, actor=actor,
        data=CaptureRawInput(
            doc_id="raw-sens-1", topic="secrets", problem_cluster="cluster-sens",
            content="# Raw sens", source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-sens-1", page_type="atom", topic="secrets",
            problem_cluster="cluster-sens",
            content="# Confidential atom\n\nSensitive content.",
            source_refs=["personal-1:raw-sens-1"],
            sensitivity="confidential",
        ),
    )

    manifest = ManifestRepository(temp_wiki_root)
    entry = manifest.find("atom-sens-1")
    assert entry is not None
    assert entry["sensitivity"] == "confidential"


def test_query_filters_confidential_pages_by_sensitivity(temp_wiki_root: Path) -> None:
    from agent_wiki.application.query import QueryInput, QueryService

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    query_service = QueryService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    capture_service.execute(
        wiki=wiki, actor=actor,
        data=CaptureRawInput(
            doc_id="raw-sens-q1", topic="secrets", problem_cluster="cluster-sq",
            content="# Raw sens query", source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-sens-public", page_type="atom", topic="secrets",
            problem_cluster="cluster-sq",
            content="# Public atom\n\nPublic secret handling patterns.",
            source_refs=["personal-1:raw-sens-q1"],
            sensitivity="public",
        ),
    )
    compile_service.apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-sens-conf", page_type="atom", topic="secrets",
            problem_cluster="cluster-sq",
            content="# Confidential atom\n\nConfidential secret handling patterns.",
            source_refs=["personal-1:raw-sens-q1"],
            sensitivity="confidential",
        ),
    )

    # Default query (max_sensitivity=internal) should exclude confidential
    result = query_service.execute(
        wiki=wiki, actor=actor,
        data=QueryInput(query="secret handling patterns", max_sensitivity="internal"),
    )

    doc_ids = [h.doc_id for h in result.hits]
    assert "atom-sens-public" in doc_ids
    assert "atom-sens-conf" not in doc_ids

    # Query with max_sensitivity=confidential should include both
    result_all = query_service.execute(
        wiki=wiki, actor=actor,
        data=QueryInput(query="secret handling patterns", max_sensitivity="confidential"),
    )

    doc_ids_all = [h.doc_id for h in result_all.hits]
    assert "atom-sens-public" in doc_ids_all
    assert "atom-sens-conf" in doc_ids_all



def test_query_defaults_to_internal_sensitivity_and_excludes_confidential(temp_wiki_root: Path) -> None:
    from agent_wiki.application.query import QueryInput, QueryService

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    capture_service = CaptureRawService()
    compile_service = CompileUpdateService()
    query_service = QueryService()
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    capture_service.execute(
        wiki=wiki, actor=actor,
        data=CaptureRawInput(
            doc_id="raw-sens-default-1", topic="secrets", problem_cluster="cluster-sd",
            content="# Raw sens default", source_refs=[],
        ),
    )
    compile_service.apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-sens-default-public", page_type="atom", topic="secrets",
            problem_cluster="cluster-sd",
            content="# Public\n\nDefault sensitivity query sees this.",
            source_refs=["personal-1:raw-sens-default-1"],
            sensitivity="public",
        ),
    )
    compile_service.apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-sens-default-conf", page_type="atom", topic="secrets",
            problem_cluster="cluster-sd",
            content="# Confidential\n\nDefault sensitivity query must not see this.",
            source_refs=["personal-1:raw-sens-default-1"],
            sensitivity="confidential",
        ),
    )

    result = query_service.execute(
        wiki=wiki, actor=actor,
        data=QueryInput(query="default sensitivity query"),
    )

    doc_ids = [hit.doc_id for hit in result.hits]
    assert "atom-sens-default-public" in doc_ids
    assert "atom-sens-default-conf" not in doc_ids


def test_query_tolerates_invalid_manifest_sensitivity_values(temp_wiki_root: Path) -> None:
    from agent_wiki.application.query import QueryInput, QueryService

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-sens-invalid-1",
            topic="secrets",
            problem_cluster="cluster-invalid",
            content="# Raw invalid sensitivity",
            source_refs=[],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-sens-invalid-1",
            page_type="atom",
            topic="secrets",
            problem_cluster="cluster-invalid",
            content="# Invalid sensitivity\n\nLegacy sensitivity should not crash query.",
            source_refs=["personal-1:raw-sens-invalid-1"],
            sensitivity="public",
        ),
    )

    manifest_path = temp_wiki_root / "MANIFEST.jsonl"
    manifest_entries = [
        json.loads(line)
        for line in manifest_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for entry in manifest_entries:
        if entry.get("doc_id") == "atom-sens-invalid-1":
            entry["sensitivity"] = "normal"
    manifest_path.write_text(
        "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in manifest_entries),
        encoding="utf-8",
    )

    result = QueryService().execute(
        wiki=wiki,
        actor=actor,
        data=QueryInput(query="legacy sensitivity"),
    )

    assert "atom-sens-invalid-1" in [hit.doc_id for hit in result.hits]
