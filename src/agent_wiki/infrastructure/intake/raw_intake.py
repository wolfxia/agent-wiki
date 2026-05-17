from __future__ import annotations


def _first_heading_or_doc_id(content: str, doc_id: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        return stripped.lstrip("# ").strip() or doc_id
    return doc_id


def _infer_summary(content: str, title: str) -> str:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if len(lines) >= 2:
        return lines[1].lstrip("# ").strip() or title
    if lines:
        return lines[0].lstrip("# ").strip() or title
    return title


def _infer_topic(payload: dict, content: str) -> str:
    source_type = str(payload.get("source_type") or "raw")
    title = _first_heading_or_doc_id(content, payload["doc_id"])
    token = title.split()[0] if title.split() else payload["doc_id"]
    return f"{source_type}:{token}"[:120]


def _infer_problem_cluster(payload: dict, content: str) -> str:
    title = _first_heading_or_doc_id(content, payload["doc_id"])
    token = title.split()[0] if title.split() else payload["doc_id"]
    return f"cluster:{token}"[:120]


def normalize_raw_intake(payload: dict) -> dict:
    content = str(payload.get("content") or "")
    doc_id = str(payload["doc_id"])
    title = str(payload.get("title") or _first_heading_or_doc_id(content, doc_id))
    topic = str(payload.get("topic") or _infer_topic(payload, content))
    problem_cluster = str(payload.get("problem_cluster") or _infer_problem_cluster(payload, content))
    summary = str(payload.get("summary") or _infer_summary(content, title))
    classification_method = "explicit" if payload.get("topic") and payload.get("problem_cluster") else "rule_based"
    classification_confidence = str(payload.get("classification_confidence") or ("high" if classification_method == "explicit" else "low"))
    metadata_state = str(payload.get("metadata_state") or ("classified" if classification_confidence == "high" else "low_confidence"))

    return {
        **payload,
        "source_type": str(payload.get("source_type") or "capture_raw"),
        "source_uri": str(payload.get("source_uri") or f"capture_raw:{doc_id}"),
        "title": title,
        "topic": topic,
        "problem_cluster": problem_cluster,
        "summary": summary,
        "classification_method": classification_method,
        "classification_confidence": classification_confidence,
        "metadata_state": metadata_state,
        "adapter_metadata": payload.get("adapter_metadata") or {},
        "frontmatter": payload.get("frontmatter") or {},
    }
