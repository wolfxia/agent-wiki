from enum import StrEnum


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
