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
