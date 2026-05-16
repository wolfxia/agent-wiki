from pathlib import Path


class PlainMarkdownAdapter:
    def read(self, source: str) -> dict:
        path = Path(source)
        return {
            "content": path.read_text(encoding="utf-8"),
            "adapter_metadata": {
                "path": str(path),
                "stem": path.stem,
            },
        }

    def write(self, target: str, document: dict) -> None:
        path = Path(target)
        path.write_text(document["content"], encoding="utf-8")
