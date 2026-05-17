from pathlib import Path

from fastapi.testclient import TestClient
import yaml

from agent_wiki.application.capture_raw import CaptureRawInput, CaptureRawService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.transports.rest.app import create_app


def test_low_gate_actor_compile_chain_returns_gate_blocked(temp_wiki_root: Path) -> None:
    registry_path = temp_wiki_root.parent / "registry-gate-block.yaml"
    registry_data = yaml.safe_load(Path("tests/fixtures/registry.yaml").read_text())
    registry_data["wikis"][0]["permissions"].append(
        {
            "actor_type": "agent",
            "actor_id": "low-gate-agent",
            "allowed_operations": ["query", "capture_raw", "compile_update"],
            "max_gate": "A",
            "allowed_page_types": ["raw", "atom"],
        }
    )
    registry_path.write_text(yaml.safe_dump(registry_data, sort_keys=False), encoding="utf-8")

    wiki = RegistryLoader().load(registry_path).wikis[0].model_copy(update={"workspace_path": str(temp_wiki_root)})
    CaptureRawService().execute(
        wiki=wiki,
        actor=ResolvedActor(actor_type="agent", actor_id="low-gate-agent", transport="rest"),
        data=CaptureRawInput(
            doc_id="raw-gate-block-1",
            topic="gates",
            problem_cluster="gate-block",
            content="# Raw gate block",
            source_refs=[],
        ),
    )

    app = create_app(
        wiki_workspace=str(temp_wiki_root),
        registry_path=str(registry_path),
        token_identities={"token-low-gate": {"actor_type": "agent", "actor_id": "low-gate-agent"}},
    )
    client = TestClient(app)

    response = client.post(
        "/compile-update",
        headers={"Authorization": "Bearer token-low-gate"},
        json={
            "doc_id": "atom-gate-block-1",
            "page_type": "atom",
            "topic": "gates",
            "problem_cluster": "gate-block",
            "content": "# Atom gate block",
            "source_refs": ["personal-1:raw-gate-block-1"],
        },
    )

    assert response.status_code == 403
    payload = response.json()
    assert payload["error"]["type"] == "gate_blocked"
    assert "required gate" in payload["error"]["message"]
