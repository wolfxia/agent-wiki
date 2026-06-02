try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        """Compatibility shim for Python 3.10 (StrEnum added in 3.11)."""

        def __str__(self) -> str:
            return str(self.value)


class ActorType(StrEnum):
    AGENT = "agent"
    HUMAN = "human"
    SERVICE = "service"


class GateLevel(StrEnum):
    A = "A"
    B = "B"
    C = "C"


class PageType(StrEnum):
    RAW = "raw"
    ATOM = "atom"
    SYNTHESIS = "synthesis"
    PRINCIPLE = "principle"


class Sensitivity(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"


class Operation(StrEnum):
    QUERY = "query"
    CAPTURE_RAW = "capture_raw"
    COMPILE_UPDATE = "compile_update"
    LINT = "lint"
    SYNC = "sync"
    APPROVE_PROPOSAL = "approve_proposal"
    PROMOTE_PRINCIPLE = "promote_principle"
    MARK_DISPUTED = "mark_disputed"
    CROSS_WIKI_MERGE = "cross_wiki_merge"
