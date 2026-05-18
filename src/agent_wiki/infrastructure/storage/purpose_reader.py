import re
from pathlib import Path


_HEADING_ALIASES = {
    "Topics": ["Topics", "主题", "主题范围"],
    "Goals": ["Goals", "目标"],
}


class PurposeReader:
    def __init__(self, wiki_root: Path) -> None:
        self.purpose_path = wiki_root / "purpose.md"
        self._cache: dict | None = None

    def read(self) -> dict:
        if not self.purpose_path.exists():
            return {"topics": [], "goals": []}

        content = self.purpose_path.read_text(encoding="utf-8")
        topics = self._extract_list_section(content, "Topics")
        goals = self._extract_list_section(content, "Goals")
        return {"topics": topics, "goals": goals}

    def is_aligned(self, topic: str) -> bool:
        purpose = self._get_cached()
        lowered = topic.lower()
        return any(lowered == t.lower() or lowered in t.lower() for t in purpose["topics"])

    def _get_cached(self) -> dict:
        if self._cache is None:
            self._cache = self.read()
        return self._cache

    def _extract_list_section(self, content: str, heading: str) -> list[str]:
        for alias in _HEADING_ALIASES.get(heading, [heading]):
            items = self._extract_list_section_by_heading(content, alias)
            if items:
                return items
        return []

    def _extract_list_section_by_heading(self, content: str, heading: str) -> list[str]:
        pattern = rf"##\s+{re.escape(heading)}\s*\n(.*?)(?=\n##|\Z)"
        match = re.search(pattern, content, re.DOTALL)
        if not match:
            return []
        items = []
        for line in match.group(1).splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                items.append(stripped[2:].strip())
        return items
