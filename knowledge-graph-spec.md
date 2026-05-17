# Knowledge Graph HTML Visualizer — Spec

## Goal
Build a standalone HTML file that visualizes the agent-wiki knowledge graph interactively, served via a simple HTTP server.

## Data Source
- File: `wiki-graph-data.json` (already in project root)
- Stats: 63 entities, 204 entity relations, 1034 pages, 382 topics

## Data Structure

```json
{
  "entities": {
    "ent_a2a_protocol": {"name": "A2A Protocol", "category": "概念", "desc": ""},
    "ent_boss": {"name": "老板", "category": "人物", "desc": "..."}
  },
  "relations": [
    {"source": "老板", "rel": "works_at", "target": "vivo"},
    {"source": "A2A Protocol", "rel": "cross_references", "target": "MCP Protocol"}
  ],
  "pages": [
    {"doc_id": "2026-05-17-npu-microarchitecture", "topic": "ai-harness", "page_type": "raw", "problem_cluster": "ai-harness"},
    {"doc_id": "imaging-os", "topic": "imaging-os", "page_type": "raw", "problem_cluster": "imaging-os"}
  ],
  "topics": ["ai-harness", "agent-os", "edge-ai-imaging", ...],
  "stats": {"entity_count": 63, "relation_count": 204, "page_count": 1034, "topic_count": 382}
}
```

## Architecture Decision: Two-Layer Graph

**Layer 1 — Topic Clusters** (top-level view):
- Nodes = topics (382 topics, but filter to top 30-50 by page count)
- Node size = number of pages in that topic
- Edges = shared pages between topics (pages that have source_refs crossing topics, or entity relations crossing topics)
- Color = topic category grouping

**Layer 2 — Entity Relationship Graph** (detail view):
- Nodes = entities (63 entities)
- Node color = category (人物/概念/设备/组织/项目/学习主题/爱好/报告)
- Node size = number of relations
- Edges = 204 explicit relations with labeled edge types
- Hover shows entity name + description
- Click highlights connected subgraph

**Toggle between layers** with tabs or button.

## Tech Stack (reference: llm_wiki approach)
- **sigma.js v2** + **graphology** for graph rendering (CDN)
- **ForceAtlas2** layout algorithm (built into graphology-layout-forceatlas2)
- Pure HTML + JS, no build step, single file
- Dark theme (matches Obsidian dark theme aesthetic)

## Visual Design Requirements

1. **Dark theme** — background #1a1b26, nodes colorful, edges semi-transparent
2. **Node colors by category** — each category gets a distinct color
3. **Node size** = sqrt(link_count) scaling
4. **Edge styling**:
   - Thickness by relation importance
   - Color: green=strong, gray=weak
   - Hover shows edge label (relation type)
5. **Interactions**:
   - Hover node → highlight neighbors, dim non-neighbors
   - Click node → show detail panel (name, category, relations)
   - Drag nodes to reposition
   - Zoom/pan with mouse wheel
   - Search box to find entities by name
6. **Controls**: Zoom In, Zoom Out, Fit-to-screen, Reset layout
7. **Legend**: shows category → color mapping, switchable between layers
8. **Stats bar**: total nodes, edges, filtered count

## HTTP Server

Create a simple Python HTTP server script (`serve_graph.py`):
```python
# serve_graph.py — serve knowledge-graph.html on port 8765
python -m http.server 8765 --directory .
```
Or embed it in the HTML file with a comment about how to serve.

Actually, simplest approach: **embed data directly in the HTML** so it's a single self-contained file. Then just `python3 -m http.server 8765` in the project dir.

## Output Files
1. `knowledge-graph.html` — single self-contained HTML file (embed JS libs via CDN, embed data inline)
2. `serve_graph.sh` — one-liner to start HTTP server: `python3 -m http.server 8765`

## Acceptance Criteria
1. Open `http://localhost:8765/knowledge-graph.html` in browser → see interactive graph
2. Two layers toggleable: Topic Clusters + Entity Relations
3. Hover/click interactions work
4. Search box filters nodes
5. ForceAtlas2 layout runs on load
6. All 63 entities + 204 relations render correctly
7. Dark theme, looks good

## Priority: Entity Relations layer first (most interesting), Topic Clusters second.
