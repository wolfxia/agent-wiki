from __future__ import annotations

from pathlib import Path

_ALLOWED_SEPARATORS = {"-", "_"}


def slugify_doc_id(value: str) -> str:
    parts: list[str] = []
    previous_separator = False
    for char in value.replace("\\", "/"):
        if char == "/":
            separator = "_"
        elif char.isalnum() or char in _ALLOWED_SEPARATORS:
            parts.append(char)
            previous_separator = False
            continue
        else:
            separator = "-"

        if parts and not previous_separator:
            parts.append(separator)
            previous_separator = True

    slug = "".join(parts).strip("-_")
    return slug or "untitled"


def doc_id_from_relative_path(relative_path: str | Path) -> str:
    path = Path(str(relative_path))
    without_suffix = path.with_suffix("")
    return slugify_doc_id(without_suffix.as_posix())
