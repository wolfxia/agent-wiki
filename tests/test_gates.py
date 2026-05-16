from agent_wiki.domain.enums import GateLevel
from agent_wiki.infrastructure.identity.gates import GateService, gate_at_least


def test_gate_ordering_a_less_than_b_less_than_c() -> None:
    assert gate_at_least(GateLevel.A, GateLevel.A) is True
    assert gate_at_least(GateLevel.B, GateLevel.A) is True
    assert gate_at_least(GateLevel.C, GateLevel.A) is True
    assert gate_at_least(GateLevel.A, GateLevel.B) is False
    assert gate_at_least(GateLevel.B, GateLevel.B) is True
    assert gate_at_least(GateLevel.C, GateLevel.B) is True
    assert gate_at_least(GateLevel.A, GateLevel.C) is False
    assert gate_at_least(GateLevel.B, GateLevel.C) is False
    assert gate_at_least(GateLevel.C, GateLevel.C) is True


def test_gate_service_returns_correct_levels() -> None:
    gate_service = GateService()
    assert gate_service.required_gate("capture_raw", "raw") == GateLevel.A
    assert gate_service.required_gate("compile_update", "atom") == GateLevel.B
    assert gate_service.required_gate("promote_principle", "principle") == GateLevel.C
