import json
from pathlib import Path

import numpy as np

from agent_wiki.application.dream_cycle import DreamCycleService
from agent_wiki.bootstrap.registry_loader import RegistryLoader
from agent_wiki.infrastructure.retrieval.vector_index import SQLiteVectorIndexProvider
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository


def _wiki(temp_wiki_root: Path):
    return RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )


def _write_atom(wiki_root: Path, doc_id: str, *, topic: str, problem_cluster: str, content: str, keywords: list[str]) -> None:
    pages = wiki_root / "pages"
    pages.mkdir(exist_ok=True)
    (pages / f"{doc_id}.md").write_text(content, encoding="utf-8")
    ManifestRepository(wiki_root).upsert(
        {
            "wiki_id": "personal-1",
            "doc_id": doc_id,
            "page_type": "atom",
            "topic": topic,
            "problem_cluster": problem_cluster,
            "summary": content.splitlines()[0].lstrip("# "),
            "canonical_uri": f"pages/{doc_id}.md",
            "keywords": keywords,
            "source_refs": [],
        }
    )


def test_cross_reference_groups_atoms_with_shared_keywords(temp_wiki_root: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    _write_atom(
        temp_wiki_root,
        "atom-constraint-a",
        topic="3dgs",
        problem_cluster="constraint-first",
        keywords=["constraint", "mobile", "schedule"],
        content="# Constraint First Rendering\n\nConstraint first planning keeps mobile rendering predictable.",
    )
    _write_atom(
        temp_wiki_root,
        "atom-constraint-b",
        topic="npu",
        problem_cluster="constraint-first",
        keywords=["constraint", "npu", "schedule"],
        content="# Constraint First Scheduling\n\nConstraint first planning keeps NPU scheduling predictable.",
    )

    groups = DreamCycleService().cross_reference(wiki)

    assert len(groups) == 1
    assert groups[0].atom_ids == ["atom-constraint-a", "atom-constraint-b"]
    assert set(groups[0].shared_keywords) >= {"constraint", "schedule"}
    assert groups[0].strength >= 0.3


def test_cross_reference_uses_graph_relations_to_boost_related_atoms(temp_wiki_root: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    _write_atom(
        temp_wiki_root,
        "atom-graph-a",
        topic="vision",
        problem_cluster="sensor-fusion",
        keywords=["event", "camera"],
        content="# Event Camera Fusion\n\nEvent camera fusion depends on temporal constraints.",
    )
    _write_atom(
        temp_wiki_root,
        "atom-graph-b",
        topic="robotics",
        problem_cluster="latency-budget",
        keywords=["latency", "planner"],
        content="# Latency Planner\n\nPlanner latency depends on temporal constraints.",
    )
    (temp_wiki_root / "knowledge_graph.jsonl").write_text(
        json.dumps(
            {
                "subject": "event camera",
                "relation": "depends_on",
                "object": "temporal constraints",
                "source_doc_id": "atom-graph-a",
            }
        )
        + "\n"
        + json.dumps(
            {
                "subject": "planner latency",
                "relation": "depends_on",
                "object": "temporal constraints",
                "source_doc_id": "atom-graph-b",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    groups = DreamCycleService().cross_reference(wiki)

    assert len(groups) == 1
    assert groups[0].atom_ids == ["atom-graph-a", "atom-graph-b"]
    assert groups[0].graph_relations == ["depends_on:temporal constraints"]
    assert groups[0].strength >= 0.3


def test_cross_reference_filters_weak_keyword_overlap(temp_wiki_root: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    _write_atom(
        temp_wiki_root,
        "atom-weak-a",
        topic="security",
        problem_cluster="auth",
        keywords=["token", "session"],
        content="# Token Sessions\n\nToken sessions expire quickly.",
    )
    _write_atom(
        temp_wiki_root,
        "atom-weak-b",
        topic="graphics",
        problem_cluster="rendering",
        keywords=["mesh", "shader"],
        content="# Mesh Shaders\n\nMesh shaders organize rendering work.",
    )

    groups = DreamCycleService().cross_reference(wiki)

    assert groups == []


def test_cross_reference_uses_hybrid_embedding_strength_and_limits_candidates(temp_wiki_root: Path) -> None:
    wiki = _wiki(temp_wiki_root)
    _write_atom(
        temp_wiki_root,
        "atom-hybrid-a",
        topic="agent-os",
        problem_cluster="pc-a",
        keywords=["constraint", "schedule"],
        content="# Atom hybrid A\n\nconstraint schedule",
    )
    _write_atom(
        temp_wiki_root,
        "atom-hybrid-b",
        topic="ai-harness",
        problem_cluster="pc-b",
        keywords=["constraint", "schedule"],
        content="# Atom hybrid B\n\nconstraint schedule",
    )
    _write_atom(
        temp_wiki_root,
        "atom-hybrid-c",
        topic="imaging-os",
        problem_cluster="pc-c",
        keywords=["mesh", "shader"],
        content="# Atom hybrid C\n\nmesh shader",
    )

    vector = SQLiteVectorIndexProvider(temp_wiki_root, wiki_id="personal-1", dimension=4)
    vector.upsert(
        "atom-hybrid-a",
        {"wiki_id": "personal-1", "page_type": "atom", "embedding": np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)},
    )
    vector.upsert(
        "atom-hybrid-b",
        {"wiki_id": "personal-1", "page_type": "atom", "embedding": np.array([0.99, 0.01, 0.0, 0.0], dtype=np.float32)},
    )
    vector.upsert(
        "atom-hybrid-c",
        {"wiki_id": "personal-1", "page_type": "atom", "embedding": np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)},
    )

    groups = DreamCycleService().cross_reference(wiki)

    assert len(groups) == 1
    assert groups[0].atom_ids == ["atom-hybrid-a", "atom-hybrid-b"]
    assert groups[0].strength >= 0.95
