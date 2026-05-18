from __future__ import annotations

import hashlib
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


def normalize_doc_id(value: str) -> str:
    parts: list[str] = []
    previous_separator = False
    non_ascii_buffer: list[str] = []

    def flush_non_ascii() -> None:
        nonlocal previous_separator
        if not non_ascii_buffer:
            return
        digest = hashlib.md5("".join(non_ascii_buffer).encode("utf-8")).hexdigest()[:10]
        if parts and not previous_separator:
            parts.append("-")
        parts.append(f"u{digest}")
        previous_separator = False
        non_ascii_buffer.clear()

    for char in value.replace("\\", "/"):
        lowered = char.lower()
        if lowered.isascii() and lowered.isalnum():
            flush_non_ascii()
            parts.append(lowered)
            previous_separator = False
            continue
        if lowered.isalnum():
            non_ascii_buffer.append(char)
            continue
        flush_non_ascii()
        if parts and not previous_separator:
            parts.append("-")
            previous_separator = True
    flush_non_ascii()
    normalized = "".join(parts).strip("-")
    return normalized or "untitled"
