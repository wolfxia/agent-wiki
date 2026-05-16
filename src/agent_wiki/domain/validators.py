import re

_DOC_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_PROPOSAL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_doc_id(doc_id: str) -> None:
    if not _DOC_ID_PATTERN.fullmatch(doc_id):
        raise ValueError(f"invalid doc_id: {doc_id}")


def validate_proposal_id(proposal_id: str) -> None:
    if not _PROPOSAL_ID_PATTERN.fullmatch(proposal_id):
        raise ValueError(f"invalid proposal_id: {proposal_id}")
