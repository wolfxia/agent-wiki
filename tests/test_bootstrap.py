from agent_wiki.bootstrap.container import Container


def test_container_exposes_core_services(container: Container) -> None:
    assert container.registry_loader is not None
    assert container.identity_resolver is not None
    assert container.permission_service is not None
    assert container.gate_service is not None


def test_container_exposes_phase1_services(container: Container) -> None:
    assert container.compile_suggest_service is not None
    assert container.fast_feedback_service is not None
    assert container.relations_service is not None
    assert container.purpose_reader_factory is not None
    assert container.authority_service is not None
