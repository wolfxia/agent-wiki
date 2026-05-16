from agent_wiki.domain.enums import GateLevel, PageType

_GATE_ORDER = {GateLevel.A: 0, GateLevel.B: 1, GateLevel.C: 2}


def gate_at_least(actor_gate: GateLevel, required: GateLevel) -> bool:
    return _GATE_ORDER[actor_gate] >= _GATE_ORDER[required]


class GateService:
    def required_gate(self, operation: str, page_type: str) -> GateLevel:
        if operation == "capture_raw":
            return GateLevel.A
        if operation in {"compile_update", "mark_disputed"}:
            return GateLevel.B
        if page_type == PageType.PRINCIPLE.value or operation in {"promote_principle", "approve_proposal", "cross_wiki_merge"}:
            return GateLevel.C
        return GateLevel.B
