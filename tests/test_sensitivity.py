from agent_wiki.domain.enums import Sensitivity


def test_sensitivity_enum_values() -> None:
    assert Sensitivity.PUBLIC == "public"
    assert Sensitivity.INTERNAL == "internal"
    assert Sensitivity.CONFIDENTIAL == "confidential"
    assert len(Sensitivity) == 3
