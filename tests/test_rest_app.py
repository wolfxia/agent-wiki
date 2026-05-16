from pathlib import Path

from fastapi.testclient import TestClient
import yaml

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

    app = create_app(wiki_workspace=str(temp_wiki_root), registry_path="tests/fixtures/registry.yaml", token_identities={"token-claude": {"actor_type": "agent", "actor_id": "claude-code"}})
    client = TestClient(app)

    response = client.post("/query", headers={"Authorization": "Bearer token-claude"}, json={"query": "REST endpoint delegation"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["hit_count"] >= 1


def test_rest_capture_endpoint_delegates_to_capture_service(temp_wiki_root: Path) -> None:
    app = create_app(wiki_workspace=str(temp_wiki_root), registry_path="tests/fixtures/registry.yaml", token_identities={"token-claude": {"actor_type": "agent", "actor_id": "claude-code"}})
    client = TestClient(app)

    response = client.post(
        "/capture-raw",
        headers={"Authorization": "Bearer token-claude"},
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



def test_rest_capture_requires_token_and_uses_bound_identity(temp_wiki_root: Path) -> None:
    registry_path = temp_wiki_root.parent / "registry-rest.yaml"
    registry_data = yaml.safe_load(Path("tests/fixtures/registry.yaml").read_text())
    registry_data["wikis"][0]["permissions"].append(
        {
            "actor_type": "agent",
            "actor_id": "codex",
            "allowed_operations": ["query", "capture_raw", "compile_update", "lint"],
            "max_gate": "B",
            "allowed_page_types": ["raw", "atom", "synthesis"],
        }
    )
    registry_path.write_text(yaml.safe_dump(registry_data, sort_keys=False), encoding="utf-8")

    app = create_app(
        wiki_workspace=str(temp_wiki_root),
        registry_path=str(registry_path),
        token_identities={"token-codex": {"actor_type": "agent", "actor_id": "codex"}},
    )
    client = TestClient(app)

    unauthorized = client.post(
        "/capture-raw",
        json={
            "doc_id": "raw-rest-auth-1",
            "topic": "testing",
            "problem_cluster": "cluster-rest-auth",
            "content": "# REST auth",
            "source_refs": [],
        },
    )
    assert unauthorized.status_code == 401

    authorized = client.post(
        "/capture-raw",
        headers={"Authorization": "Bearer token-codex"},
        json={
            "doc_id": "raw-rest-auth-1",
            "topic": "testing",
            "problem_cluster": "cluster-rest-auth",
            "content": "# REST auth",
            "source_refs": [],
        },
    )

    assert authorized.status_code == 200
    assert (temp_wiki_root / "pages" / "raw-rest-auth-1.md").exists()



def test_rest_query_returns_l1_l2_l3_and_wiki_ids(temp_wiki_root: Path) -> None:
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
            doc_id="raw-rest-layers-1", topic="testing", problem_cluster="cluster-rest-layers",
            content="# Raw rest layers", source_refs=[],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki, actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-rest-layers-1", page_type="atom", topic="testing",
            problem_cluster="cluster-rest-layers",
            content="# Atom rest layers\n\nREST returns layered query payloads.",
            source_refs=["personal-1:raw-rest-layers-1"],
        ),
    )

    app = create_app(
        wiki_workspace=str(temp_wiki_root),
        registry_path="tests/fixtures/registry.yaml",
        token_identities={"token-claude": {"actor_type": "agent", "actor_id": "claude-code"}},
    )
    client = TestClient(app)
    response = client.post(
        "/query",
        headers={"Authorization": "Bearer token-claude"},
        json={"query": "layered query payloads"},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["l1_answer"]
    assert payload["l2_context"]
    assert payload["l3_proof"]
    assert payload["hits"][0]["wiki_id"] == "personal-1"
