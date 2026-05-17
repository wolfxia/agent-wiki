from pydantic import BaseModel

from agent_wiki.domain.enums import GateLevel, PageType, Sensitivity


class RegistryContext(BaseModel):
    registry_path: str


class IdentityContext(BaseModel):
    transport: str
    actor_type: str | None = None
    actor_id: str | None = None
    metadata: dict[str, str] | None = None


class CaptureRawInput(BaseModel):
    doc_id: str
    topic: str | None = None
    problem_cluster: str | None = None
    summary: str | None = None
    content: str
    source_refs: list[str]


class CaptureResult(BaseModel):
    status: str
    doc_id: str
    page_path: str


class CompileUpdateInput(BaseModel):
    doc_id: str
    page_type: PageType | str
    topic: str
    problem_cluster: str
    content: str
    source_refs: list[str]
    evidence_note: str | None = None
    review_status: str | None = None
    dispute_reason: str | None = None
    sensitivity: Sensitivity | None = None
    allow_shared_write_without_sources: bool = False


class CompileAnalysis(BaseModel):
    target_doc_id: str
    change_type: str
    gate: GateLevel | str


class CompileResult(BaseModel):
    status: str
    doc_id: str
    page_path: str


class QueryInput(BaseModel):
    query: str
    include_pending: bool = False
    max_sensitivity: Sensitivity | None = None


class QueryResult(BaseModel):
    query_type: str
    l1_answer: str
    l2_context: list[dict]
    l3_proof: list[dict]
    hits: list
    hit_count: int = 0
    miss_signal: bool = False


class ProposalInput(BaseModel):
    proposal_id: str
    doc_id: str
    page_type: PageType | str
    topic: str
    problem_cluster: str
    content: str
    source_refs: list[str]


class ProposalResult(BaseModel):
    status: str
    proposal_id: str


class ApprovalResult(BaseModel):
    status: str
    doc_id: str
