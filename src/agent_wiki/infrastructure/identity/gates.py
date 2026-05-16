from agent_wiki.domain.enums import GateLevel, Operation, PageType

_GATE_ORDER = {GateLevel.A: 0, GateLevel.B: 1, GateLevel.C: 2}


def gate_at_least(actor_gate: GateLevel, required: GateLevel) -> bool:
    return _GATE_ORDER[actor_gate] >= _GATE_ORDER[required]


class GateService:
    def required_gate(self, operation: Operation | str, page_type: PageType | str) -> GateLevel:
        operation = Operation(operation)
        page_type = PageType(page_type)
        if operation in {Operation.QUERY, Operation.CAPTURE_RAW, Operation.SYNC, Operation.LINT}:
            return GateLevel.A
        if operation in {Operation.COMPILE_UPDATE, Operation.MARK_DISPUTED}:
            return GateLevel.B
        if page_type == PageType.PRINCIPLE or operation in {Operation.PROMOTE_PRINCIPLE, Operation.APPROVE_PROPOSAL, Operation.CROSS_WIKI_MERGE}:
            return GateLevel.C
        return GateLevel.B
