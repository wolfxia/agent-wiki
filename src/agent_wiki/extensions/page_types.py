from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from agent_wiki.domain.enums import GateLevel


@dataclass(frozen=True)
class PageTypeDefinition:
    name: str
    default_gate: str = "B"
    requires_source_refs: bool = False
    truth_zone: bool = False


class PageTypeRegistry:
    def __init__(self) -> None:
        self._lock = RLock()
        self._definitions: dict[str, PageTypeDefinition] = {}

    def register(
        self,
        name: str,
        *,
        default_gate: GateLevel | str = "B",
        requires_source_refs: bool = False,
        truth_zone: bool = False,
    ) -> PageTypeDefinition:
        normalized = normalize_page_type(name)
        gate = GateLevel(default_gate).value
        definition = PageTypeDefinition(
            name=normalized,
            default_gate=gate,
            requires_source_refs=requires_source_refs,
            truth_zone=truth_zone,
        )
        with self._lock:
            existing = self._definitions.get(normalized)
            if existing is not None and existing != definition:
                raise ValueError(f"page type {normalized} is already registered with different metadata")
            self._definitions[normalized] = definition
        return definition

    def get(self, name: str) -> PageTypeDefinition:
        normalized = normalize_page_type(name)
        with self._lock:
            try:
                return self._definitions[normalized]
            except KeyError as exc:
                raise ValueError(f"unknown page type: {normalized}") from exc

    def is_registered(self, name: str) -> bool:
        normalized = normalize_page_type(name)
        with self._lock:
            return normalized in self._definitions

    def names(self) -> set[str]:
        with self._lock:
            return set(self._definitions)


def normalize_page_type(name: object) -> str:
    value = str(getattr(name, "value", name)).strip()
    if not value:
        raise ValueError("page type must not be empty")
    return value


_PAGE_TYPE_REGISTRY = PageTypeRegistry()


def register_page_type(
    name: str,
    *,
    default_gate: GateLevel | str = "B",
    requires_source_refs: bool = False,
    truth_zone: bool = False,
) -> PageTypeDefinition:
    return _PAGE_TYPE_REGISTRY.register(
        name,
        default_gate=default_gate,
        requires_source_refs=requires_source_refs,
        truth_zone=truth_zone,
    )


def get_page_type_registry() -> PageTypeRegistry:
    return _PAGE_TYPE_REGISTRY


def is_registered_page_type(name: str) -> bool:
    return _PAGE_TYPE_REGISTRY.is_registered(name)


register_page_type("raw", default_gate="A", requires_source_refs=False, truth_zone=False)
register_page_type("atom", default_gate="B", requires_source_refs=True, truth_zone=True)
register_page_type("synthesis", default_gate="B", requires_source_refs=True, truth_zone=True)
register_page_type("principle", default_gate="C", requires_source_refs=True, truth_zone=True)
