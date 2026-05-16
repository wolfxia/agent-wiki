from pathlib import Path

from fastapi.testclient import TestClient

from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.transports.rest.app import create_app


def test_rest_health_endpoint_returns_200() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"


def test_rest_query_endpoint_delegates_to_query_service(temp_wiki_root: Path) -> None:
    from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
    from agent_wiki.application.compile_update import CompileUpdateInput, CompileUpdateService
    from agent_wiki.domain.contracts import ResolvedActor

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="rest")

    CaptureRawService().execute(
        wiki=wiki, actor=actor,
        data=CaptureRawInput(
            doc_id="raw-rest-1", topic="testing", problem_cluster="cluster-rest",
            content="# Raw rest", source_refs=[],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-rest-1", page_type="atom", topic="testing",
            problem_cluster="cluster-rest",
            content="# Atom rest\n\nREST endpoint delegation.",
            source_refs=["personal-1:raw-rest-1"],
        ),
    )

    app = create_app(wiki_workspace=str(temp_wiki_root))
    client = TestClient(app)

    response = client.post("/query", json={"query": "REST endpoint delegation"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["hit_count"] >= 1


def test_rest_capture_endpoint_delegates_to_capture_service(temp_wiki_root: Path) -> None:
    app = create_app(wiki_workspace=str(temp_wiki_root))
    client = TestClient(app)

    response = client.post(
        "/capture-raw",
        json={
            "doc_id": "raw-rest-cap-1",
            "topic": "testing",
            "problem_cluster": "cluster-rest-cap",
            "content": "# REST cap",
            "source_refs": [],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "committed"
    assert (temp_wiki_root / "pages" / "raw-rest-cap-1.md").exists()
