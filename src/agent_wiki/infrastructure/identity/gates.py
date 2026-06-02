from __future__ import annotations
from agent_wiki.domain.enums import GateLevel, Operation, PageType
from agent_wiki.extensions.page_types import get_page_type_registry, normalize_page_type

_GATE_ORDER = {GateLevel.A: 0, GateLevel.B: 1, GateLevel.C: 2}


def gate_at_least(actor_gate: GateLevel, required: GateLevel) -> bool:
    return _GATE_ORDER[actor_gate] >= _GATE_ORDER[required]


def _max_gate(*gates: GateLevel) -> GateLevel:
    return max(gates, key=lambda gate: _GATE_ORDER[gate])


class GateService:
    def required_gate(self, operation: Operation | str, page_type: PageType | str) -> GateLevel:
        operation = Operation(operation)
        page_type_value = normalize_page_type(page_type)
        if page_type_value == PageType.PRINCIPLE.value or operation in {Operation.PROMOTE_PRINCIPLE, Operation.APPROVE_PROPOSAL, Operation.CROSS_WIKI_MERGE}:
            return GateLevel.C
        if operation in {Operation.QUERY, Operation.CAPTURE_RAW, Operation.SYNC, Operation.LINT}:
            return GateLevel.A
        if operation in {Operation.COMPILE_UPDATE, Operation.MARK_DISPUTED}:
            return _max_gate(GateLevel.B, GateLevel(get_page_type_registry().get(page_type_value).default_gate))
        return GateLevel(get_page_type_registry().get(page_type_value).default_gate)
