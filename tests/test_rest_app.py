from pathlib import Path
from shutil import copytree

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


def test_rest_compile_update_endpoint_delegates_to_service(temp_wiki_root: Path) -> None:
    from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
    from agent_wiki.bootstrap.registry_loader import RegistryLoader
    from agent_wiki.domain.contracts import ResolvedActor

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="rest")
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-rest-compile-1",
            topic="testing",
            problem_cluster="cluster-rest-compile",
            content="# Raw rest compile",
            source_refs=[],
        ),
    )

    app = create_app(
        wiki_workspace=str(temp_wiki_root),
        registry_path="tests/fixtures/registry.yaml",
        token_identities={"token-claude": {"actor_type": "agent", "actor_id": "claude-code"}},
    )
    client = TestClient(app)

    response = client.post(
        "/compile-update",
        headers={"Authorization": "Bearer token-claude"},
        json={
            "doc_id": "atom-rest-compile-1",
            "page_type": "atom",
            "topic": "testing",
            "problem_cluster": "cluster-rest-compile",
            "content": "# Atom rest compile\n\nREST compile update endpoint.",
            "source_refs": ["personal-1:raw-rest-compile-1"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "committed"
    assert payload["doc_id"] == "atom-rest-compile-1"
    assert (temp_wiki_root / "pages" / "atom-rest-compile-1.md").exists()


def test_rest_compile_prepare_endpoint_returns_agent_packet(temp_wiki_root: Path) -> None:
    from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
    from agent_wiki.domain.contracts import ResolvedActor

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    CaptureRawService().execute(
        wiki=wiki,
        actor=ResolvedActor(actor_type="agent", actor_id="claude-code", transport="rest"),
        data=CaptureRawInput(
            doc_id="raw-rest-prepare-1",
            topic="agents",
            problem_cluster="memory",
            content="# REST Prepare\n\nClaim: Agents need compile packets.",
            source_refs=[],
        ),
    )
    app = create_app(
        wiki_workspace=str(temp_wiki_root),
        registry_path="tests/fixtures/registry.yaml",
        token_identities={"token-claude": {"actor_type": "agent", "actor_id": "claude-code"}},
    )
    client = TestClient(app)

    response = client.post(
        "/compile-prepare",
        headers={"Authorization": "Bearer token-claude"},
        json={"topic": "agents", "problem_cluster": "memory"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_objective"] == "create_retrieval_ready_atom"
    assert payload["source_refs"] == ["personal-1:raw-rest-prepare-1"]
    assert payload["items"][0]["claims"] == ["Claim: Agents need compile packets."]


def test_rest_review_queue_consume_endpoint_assigns_item(temp_wiki_root: Path) -> None:
    from agent_wiki.infrastructure.runtime.review_queue import ReviewQueueRepository

    ReviewQueueRepository(temp_wiki_root).append(
        {"item_id": "compile_suggestion:rest:consume", "item_type": "compile_suggestion", "status": "open"}
    )
    app = create_app(
        wiki_workspace=str(temp_wiki_root),
        registry_path="tests/fixtures/registry.yaml",
        token_identities={"token-claude": {"actor_type": "agent", "actor_id": "claude-code"}},
    )
    client = TestClient(app)

    response = client.post(
        "/review-queue/consume",
        headers={"Authorization": "Bearer token-claude"},
        json={"item_type": "compile_suggestion"},
    )

    assert response.status_code == 200
    assert response.json()["item_id"] == "compile_suggestion:rest:consume"
    assert ReviewQueueRepository(temp_wiki_root).find("compile_suggestion:rest:consume")["assigned_to"] == "claude-code"


def test_rest_lint_endpoint_returns_structured_issues(temp_wiki_root: Path) -> None:
    pages_dir = temp_wiki_root / "pages"
    pages_dir.mkdir(exist_ok=True)
    (pages_dir / "ghost-rest.md").unlink(missing_ok=True)
    (temp_wiki_root / "MANIFEST.jsonl").write_text(
        '{"doc_id":"ghost-rest","page_type":"raw","canonical_uri":"pages/ghost-rest.md"}\n',
        encoding="utf-8",
    )

    app = create_app(
        wiki_workspace=str(temp_wiki_root),
        registry_path="tests/fixtures/registry.yaml",
        token_identities={"token-claude": {"actor_type": "agent", "actor_id": "claude-code"}},
    )
    client = TestClient(app)

    response = client.get("/lint", headers={"Authorization": "Bearer token-claude"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert any("missing page" in issue for issue in payload["issues"])
    assert "kg_coverage" in payload["metrics"]


def test_rest_sync_endpoint_supports_push_view(temp_wiki_root: Path) -> None:
    pages_dir = temp_wiki_root / "pages"
    pages_dir.mkdir(exist_ok=True)
    (pages_dir / "sync-rest-1.md").write_text("# Sync REST", encoding="utf-8")
    external_dir = temp_wiki_root / "rest-vault"
    external_dir.mkdir(exist_ok=True)

    registry_path = temp_wiki_root.parent / "registry-rest-sync.yaml"
    registry_data = yaml.safe_load(Path("tests/fixtures/registry.yaml").read_text())
    registry_data["wikis"][0]["external_views"] = [
        {"adapter": "plain_markdown", "mode": "read_write", "path": str(external_dir)}
    ]
    registry_path.write_text(yaml.safe_dump(registry_data, sort_keys=False), encoding="utf-8")

    app = create_app(
        wiki_workspace=str(temp_wiki_root),
        registry_path=str(registry_path),
        token_identities={"token-claude": {"actor_type": "agent", "actor_id": "claude-code"}},
    )
    client = TestClient(app)

    response = client.post(
        "/sync",
        headers={"Authorization": "Bearer token-claude"},
        json={"mode": "push-view", "doc_ids": ["sync-rest-1"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "push-view"
    assert (external_dir / "sync-rest-1.md").exists()


def test_rest_feedback_endpoint_records_feedback_and_queue(temp_wiki_root: Path) -> None:
    app = create_app(
        wiki_workspace=str(temp_wiki_root),
        registry_path="tests/fixtures/registry.yaml",
        token_identities={"token-claude": {"actor_type": "agent", "actor_id": "claude-code"}},
    )
    client = TestClient(app)

    response = client.post(
        "/feedback",
        headers={"Authorization": "Bearer token-claude"},
        json={
            "query_id": "q-rest-1",
            "approved": False,
            "missing_evidence": True,
            "rewrite_targets": ["atom-rest-feedback-1"],
            "notes": "needs stronger proof",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["created_review_item"] is True
    assert (temp_wiki_root / "feedback_outcomes.jsonl").exists()
    assert (temp_wiki_root / "review_queue.jsonl").exists()


def test_rest_weekly_review_endpoint_returns_summary(temp_wiki_root: Path) -> None:
    from agent_wiki.application.feedback import FeedbackInput, FeedbackService
    from agent_wiki.bootstrap.registry_loader import RegistryLoader

    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    FeedbackService().record(
        wiki,
        FeedbackInput(
            query_id="q-rest-weekly-1",
            approved=False,
            missing_evidence=True,
            rewrite_targets=["atom-rest-weekly-1"],
            notes="backfill evidence",
        ),
    )

    app = create_app(
        wiki_workspace=str(temp_wiki_root),
        registry_path="tests/fixtures/registry.yaml",
        token_identities={"token-claude": {"actor_type": "agent", "actor_id": "claude-code"}},
    )
    client = TestClient(app)

    response = client.get("/weekly-review", headers={"Authorization": "Bearer token-claude"})

    assert response.status_code == 200
    payload = response.json()
    assert "feedback_issue" in payload["summary"]
    assert "backfill evidence" in payload["suggested_actions"][0]


def test_rest_approvals_endpoints_support_propose_and_approve(tmp_path: Path) -> None:
    personal_root = tmp_path / "rest-approval-personal"
    shared_root = tmp_path / "rest-approval-shared"
    copytree(Path("tests/fixtures/sample_wiki"), personal_root)
    copytree(Path("tests/fixtures/shared_wiki"), shared_root)

    registry_path = tmp_path / "registry-rest-approvals.yaml"
    registry_data = yaml.safe_load(Path("tests/fixtures/registry_multi.yaml").read_text())
    registry_data["wikis"][0]["workspace_path"] = str(personal_root)
    registry_data["wikis"][1]["workspace_path"] = str(shared_root)
    registry_path.write_text(yaml.safe_dump(registry_data, sort_keys=False), encoding="utf-8")

    from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
    from agent_wiki.bootstrap.registry_loader import RegistryLoader
    from agent_wiki.domain.contracts import ResolvedActor

    personal_wiki = RegistryLoader().load(registry_path).wikis[0]
    CaptureRawService().execute(
        wiki=personal_wiki,
        actor=ResolvedActor(actor_type="agent", actor_id="claude-code", transport="rest"),
        data=CaptureRawInput(
            doc_id="raw-rest-approval-1",
            topic="testing",
            problem_cluster="cluster-rest-approval",
            content="# Raw rest approval",
            source_refs=[],
        ),
    )

    app = create_app(
        wiki_workspace=None,
        registry_path=str(registry_path),
        token_identities={"token-claude": {"actor_type": "agent", "actor_id": "claude-code"}},
    )
    client = TestClient(app)

    propose = client.post(
        "/approvals/propose",
        headers={"Authorization": "Bearer token-claude"},
        json={
            "wiki_id": "shared-1",
            "proposal_id": "proposal-rest-1",
            "doc_id": "principle-rest-1",
            "page_type": "principle",
            "topic": "testing",
            "problem_cluster": "cluster-rest-approval",
            "content": "# Principle rest\n\nApproved through REST.",
            "source_refs": ["personal-1:raw-rest-approval-1"],
        },
    )

    assert propose.status_code == 200
    assert propose.json()["status"] == "proposed"

    approve = client.post(
        "/approvals/approve",
        headers={"Authorization": "Bearer token-claude"},
        json={"wiki_id": "shared-1", "proposal_id": "proposal-rest-1"},
    )

    assert approve.status_code == 200
    payload = approve.json()
    assert payload["status"] == "approved"
    assert payload["doc_id"] == "principle-rest-1"
    assert (shared_root / "pages" / "principle-rest-1.md").exists()


def test_rest_compile_update_maps_permission_error_to_structured_response(temp_wiki_root: Path) -> None:
    registry_path = temp_wiki_root.parent / "registry-rest-permission.yaml"
    registry_data = yaml.safe_load(Path("tests/fixtures/registry.yaml").read_text())
    registry_data["wikis"][0]["permissions"].append(
        {
            "actor_type": "agent",
            "actor_id": "codex",
            "allowed_operations": ["query", "capture_raw"],
            "max_gate": "A",
            "allowed_page_types": ["raw"],
        }
    )
    registry_path.write_text(yaml.safe_dump(registry_data, sort_keys=False), encoding="utf-8")

    from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
    from agent_wiki.bootstrap.registry_loader import RegistryLoader
    from agent_wiki.domain.contracts import ResolvedActor

    wiki = RegistryLoader().load(registry_path).wikis[0].model_copy(update={"workspace_path": str(temp_wiki_root)})
    CaptureRawService().execute(
        wiki=wiki,
        actor=ResolvedActor(actor_type="agent", actor_id="codex", transport="rest"),
        data=CaptureRawInput(
            doc_id="raw-rest-perm-1",
            topic="testing",
            problem_cluster="cluster-rest-perm",
            content="# Raw rest permission",
            source_refs=[],
        ),
    )

    app = create_app(
        wiki_workspace=str(temp_wiki_root),
        registry_path=str(registry_path),
        token_identities={"token-codex": {"actor_type": "agent", "actor_id": "codex"}},
    )
    client = TestClient(app)

    response = client.post(
        "/compile-update",
        headers={"Authorization": "Bearer token-codex"},
        json={
            "doc_id": "atom-rest-perm-1",
            "page_type": "atom",
            "topic": "testing",
            "problem_cluster": "cluster-rest-perm",
            "content": "# Atom denied",
            "source_refs": ["personal-1:raw-rest-perm-1"],
        },
    )

    assert response.status_code == 403
    payload = response.json()
    assert payload["error"]["type"] == "permission_denied"
