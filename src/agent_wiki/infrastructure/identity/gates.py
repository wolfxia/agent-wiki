from agent_wiki.domain.enums import GateLevel, PageType


class GateService:
    def required_gate(self, operation: str, page_type: str) -> GateLevel:
        if operation == "capture_raw":
            return GateLevel.A
        if operation in {"compile_update", "mark_disputed"}:
            return GateLevel.B
        if page_type == PageType.PRINCIPLE.value or operation in {"promote_principle", "approve_proposal", "cross_wiki_merge"}:
            return GateLevel.C
        return GateLevel.B
