import re
from pathlib import Path

import yaml


_FRONTMATTER_RE = re.compile(r"\A---\n(.*?\n)---\n", re.DOTALL)


class ObsidianAdapter:
    def read(self, source: str) -> dict:
        path = Path(source)
        raw = path.read_text(encoding="utf-8")
        frontmatter: dict = {}
        content = raw

        match = _FRONTMATTER_RE.match(raw)
        if match:
            frontmatter = yaml.safe_load(match.group(1)) or {}
            content = raw[match.end():]

        return {
            "content": content,
            "adapter_metadata": {
                "path": str(path),
                "stem": path.stem,
                "frontmatter": frontmatter,
            },
        }

    def write(self, target: str, document: dict) -> None:
        path = Path(target)
        frontmatter = document.get("adapter_metadata", {}).get("frontmatter", {})
        parts = []
        if frontmatter:
            parts.append("---\n")
            parts.append(yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False))
            parts.append("---\n")
        parts.append(document["content"])
        path.write_text("".join(parts), encoding="utf-8")

    def render_graph_index(self, manifest_entries: list[dict]) -> str:
        grouped = {"atom": [], "synthesis": [], "raw": []}
        for entry in manifest_entries:
            page_type = entry.get("page_type")
            if page_type in grouped:
                grouped[page_type].append(entry)

        lines = ["# 知识图谱索引", ""]
        for title, key in (("Atom", "atom"), ("Synthesis", "synthesis"), ("Raw", "raw")):
            lines.append(f"## {title}")
            for entry in sorted(grouped[key], key=lambda item: item["doc_id"]):
                lines.append(
                    f"- [[{entry['doc_id']}]] · topic: {entry.get('topic', '')} · problem_cluster: {entry.get('problem_cluster', '')}"
                )
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"
