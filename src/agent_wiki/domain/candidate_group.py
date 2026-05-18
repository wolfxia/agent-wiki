from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CandidateGroup:
    atom_ids: list[str]
    shared_keywords: list[str]
    graph_relations: list[str]
    strength: float

    def to_dict(self) -> dict:
        return asdict(self)
