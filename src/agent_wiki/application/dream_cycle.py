from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from itertools import combinations
from pathlib import Path
from typing import Any

import yaml

from agent_wiki.application.compile_apply import CompileApplyService
from agent_wiki.application.propagation import PropagationService
from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.candidate_group import CandidateGroup
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.domain.models import CompileUpdateInput
from agent_wiki.domain.validators import validate_doc_id
from agent_wiki.infrastructure.doc_id import normalize_doc_id
from agent_wiki.infrastructure.identity.permissions import PermissionService
from agent_wiki.infrastructure.retrieval.knowledge_graph import KnowledgeGraphRepository
from agent_wiki.infrastructure.retrieval.tokenizer import tokenize
from agent_wiki.infrastructure.retrieval.vector_index import SQLiteVectorIndexProvider
from agent_wiki.infrastructure.runtime.review_queue import ReviewQueueRepository
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository


_REQUIRED_COMPILED_FIELDS = ("doc_id", "page_type", "topic", "problem_cluster", "summary", "source_refs")
_DEFAULT_STALENESS_DAYS = 30
_DEFAULT_STRENGTH_THRESHOLD = 0.3
_DEFAULT_MAX_SYNTHESIS = 3
_DEFAULT_REPORT_PATH = ".agent-wiki/dream_cycle_orphans.jsonl"
_DEFAULT_MAX_CANDIDATES = 500
_DEFAULT_EMBEDDING_COSINE_THRESHOLD = 0.5


class DreamCycleService:
    def __init__(self, llm_generate: Callable[[WikiConfig, CandidateGroup, dict[str, str]], str] | None = None) -> None:
        self._llm_generate = llm_generate

    def run(
        self,
        wiki: WikiConfig,
        actor: ResolvedActor,
        *,
        step: str | None = None,
        dry_run: bool = False,
    ) -> dict:
        normalized_step = self._normalize_step(step)
        if normalized_step == "orphan":
            orphans = self.orphan_scan(wiki, dry_run=dry_run)
            return {"orphan_count": len(orphans)}
        if normalized_step == "cross-ref":
            groups = self.cross_reference(wiki)
            return {"candidate_group_count": len(groups), "candidate_groups": [group.to_dict() for group in groups]}
        if normalized_step == "synthesis":
            groups = self.cross_reference(wiki)
            results = self.synthesis_generate(wiki, actor, groups, dry_run=dry_run)
            return {"candidate_group_count": len(groups), "synthesis_count": len(results), "synthesis_results": results}
        if normalized_step == "quality":
            issues = self.quality_review(wiki, dry_run=dry_run)
            return {"quality_issue_count": len(issues)}

        orphans = self.orphan_scan(wiki, dry_run=dry_run)
        groups = self.cross_reference(wiki)
        synthesis = self.synthesis_generate(wiki, actor, groups, dry_run=dry_run)
        quality = self.quality_review(wiki, dry_run=dry_run)
        return {
            "orphan_count": len(orphans),
            "candidate_group_count": len(groups),
            "synthesis_count": len(synthesis),
            "quality_issue_count": len(quality),
        }

    def orphan_scan(self, wiki: WikiConfig, *, dry_run: bool = False) -> list[dict]:
        wiki_root = Path(wiki.workspace_path)
        manifest_entries = ManifestRepository(wiki_root).read_all()
        queue_items = ReviewQueueRepository(wiki_root).read_all()
        graph_entries = KnowledgeGraphRepository(wiki_root, wiki_id=wiki.wiki_id).read_all()

        compile_suggestion_sources = self._compile_suggestion_sources(queue_items)
        synthesis_atom_refs = self._synthesis_atom_refs(manifest_entries)
        graph_doc_ids = {
            str(relation.get("source_doc_id"))
            for relation in graph_entries
            if relation.get("source_doc_id")
        }

        existing_first_seen = self._existing_orphan_first_seen(wiki_root, wiki)
        now = self._now()
        report: list[dict] = []
        for entry in sorted(
            manifest_entries,
            key=lambda item: (self._orphan_sort_rank(item), str(item.get("doc_id") or "")),
        ):
            doc_id = str(entry.get("doc_id") or "")
            if not doc_id:
                continue
            orphan_type = ""
            if entry.get("page_type") == "raw" and doc_id not in compile_suggestion_sources:
                orphan_type = "raw"
            elif entry.get("page_type") == "atom" and doc_id not in synthesis_atom_refs and doc_id not in graph_doc_ids:
                orphan_type = "atom"
            if not orphan_type:
                continue
            first_seen = existing_first_seen.get((orphan_type, doc_id), now)
            report.append(
                {
                    "wiki_id": wiki.wiki_id,
                    "orphan_type": orphan_type,
                    "doc_id": doc_id,
                    "first_seen": first_seen,
                    "last_seen": now,
                }
            )

        if not dry_run:
            self._write_orphan_report(wiki_root, wiki, report)
        return report

    def cross_reference(self, wiki: WikiConfig) -> list[CandidateGroup]:
        wiki_root = Path(wiki.workspace_path)
        manifest_entries = ManifestRepository(wiki_root).read_all()
        atom_entries = [
            entry
            for entry in manifest_entries
            if entry.get("page_type") == "atom"
            and entry.get("doc_id")
            and not str(entry.get("doc_id")).startswith("atom-external-sync-")
        ]
        atom_terms = {str(entry["doc_id"]): self._atom_keywords(wiki_root, entry) for entry in atom_entries}
        vector_index = SQLiteVectorIndexProvider(wiki_root, wiki_id=wiki.wiki_id)
        atom_embeddings = {
            str(entry["doc_id"]): vector_index.get_embedding(str(entry["doc_id"]))
            for entry in atom_entries
        }
        graph_relations = self._graph_relation_index(wiki_root, wiki)
        threshold = self._dream_config_value(wiki, "synthesis", "strength_threshold", _DEFAULT_STRENGTH_THRESHOLD)
        cosine_threshold = float(self._dream_config_value(wiki, "synthesis", "embedding_cosine_threshold", _DEFAULT_EMBEDDING_COSINE_THRESHOLD))
        max_candidates = int(self._dream_config_value(wiki, "synthesis", "max_candidates", _DEFAULT_MAX_CANDIDATES))

        entry_by_doc_id = {str(entry["doc_id"]): entry for entry in atom_entries}
        groups: list[CandidateGroup] = []
        for first, second in combinations(sorted(entry_by_doc_id), 2):
            if entry_by_doc_id[first].get("topic") == entry_by_doc_id[second].get("topic"):
                continue
            first_terms = atom_terms.get(first, set())
            second_terms = atom_terms.get(second, set())
            shared = sorted(first_terms & second_terms)
            jaccard = self._jaccard(first_terms, second_terms)
            first_embedding = atom_embeddings.get(first)
            second_embedding = atom_embeddings.get(second)
            has_embeddings = first_embedding is not None and second_embedding is not None
            cosine_sim = (
                vector_index._cosine_similarity(first_embedding, second_embedding)
                if has_embeddings
                else 0.0
            )
            if has_embeddings and cosine_sim < cosine_threshold:
                continue
            graph_matches = sorted(set(graph_relations.get((first, second), [])))
            strength = (cosine_sim * 0.7 + jaccard * 0.3) if has_embeddings else jaccard
            if graph_matches:
                strength += 0.3
            if self._same_problem_cluster_different_topic(entry_by_doc_id[first], entry_by_doc_id[second]):
                strength += 0.2
            if (
                entry_by_doc_id[first].get("topic") != entry_by_doc_id[second].get("topic")
                and (jaccard > 0.0 or bool(graph_matches))
            ):
                strength += 0.3
            strength = min(round(strength, 4), 1.0)
            if strength < float(threshold):
                continue
            groups.append(
                CandidateGroup(
                    atom_ids=[first, second],
                    shared_keywords=shared,
                    graph_relations=graph_matches,
                    strength=strength,
                )
            )

        groups.sort(key=lambda group: (-group.strength, group.atom_ids))
        return groups[:max_candidates]

    def synthesis_generate(
        self,
        wiki: WikiConfig,
        actor: ResolvedActor,
        candidate_groups: list[CandidateGroup],
        *,
        dry_run: bool = False,
    ) -> list[dict]:
        wiki_root = Path(wiki.workspace_path)
        manifest = ManifestRepository(wiki_root)
        max_synthesis = int(self._dream_config_value(wiki, "synthesis", "max_synthesis_per_run", _DEFAULT_MAX_SYNTHESIS))
        results: list[dict] = []
        for group in candidate_groups[:max_synthesis]:
            doc_id = self._synthesis_doc_id(group)
            source_refs = [f"{wiki.wiki_id}:{atom_id}" for atom_id in group.atom_ids]
            topic, problem_cluster = self._infer_synthesis_metadata(manifest, group.atom_ids)
            if dry_run:
                results.append({
                    "status": "planned",
                    "doc_id": doc_id,
                    "source_refs": source_refs,
                    "topic": topic,
                    "problem_cluster": problem_cluster,
                })
                continue
            atom_pages = self._load_atom_pages(wiki_root, manifest, group.atom_ids)
            if len(atom_pages) < 2:
                continue
            content = self._build_synthesis_page(wiki, manifest, group, atom_pages)

            validate_doc_id(doc_id)
            decision = PermissionService().check(actor, "compile_update", wiki, "synthesis")
            if not decision.allowed:
                raise PermissionError(decision.reason)
            self._validate_atom_source_refs(wiki, manifest, source_refs)
            result = PropagationService(wiki_root).propagate_compile_update(
                wiki=wiki,
                actor=actor,
                data=CompileUpdateInput(
                    doc_id=doc_id,
                    page_type="synthesis",
                    topic=topic,
                    problem_cluster=problem_cluster,
                    summary=f"Dream Cycle synthesis across {len(group.atom_ids)} atom pages",
                    aliases=group.shared_keywords,
                    confidence="medium",
                    contested=False,
                    wikilinks=group.atom_ids,
                    review_status="generated",
                    content=content,
                    source_refs=source_refs,
                ),
            )
            results.append({"status": result.status, "doc_id": result.doc_id, "source_refs": source_refs})
        return results

    def quality_review(self, wiki: WikiConfig, *, dry_run: bool = False) -> list[dict]:
        wiki_root = Path(wiki.workspace_path)
        manifest = ManifestRepository(wiki_root)
        entries = manifest.read_all()
        existing_doc_ids = {str(entry.get("doc_id")) for entry in entries if entry.get("doc_id")}
        staleness_days = int(self._dream_config_value(wiki, "quality", "staleness_days", _DEFAULT_STALENESS_DAYS))
        queue = ReviewQueueRepository(wiki_root)
        issues: list[dict] = []
        for entry in sorted(entries, key=lambda item: str(item.get("doc_id") or "")):
            if entry.get("page_type") not in {"atom", "synthesis"}:
                continue
            doc_id = str(entry.get("doc_id") or "")
            issue_codes = self._quality_issue_codes(wiki_root, entry, existing_doc_ids, staleness_days)
            if not issue_codes:
                continue
            issue = {
                "item_id": f"quality_review:{doc_id}",
                "item_type": "quality_review",
                "wiki_id": wiki.wiki_id,
                "doc_id": doc_id,
                "issue_codes": issue_codes,
                "status": "open",
                "content_state": {"issue_codes": issue_codes},
            }
            issues.append(issue)
            if not dry_run:
                queue.append(issue)
        return issues

    def _normalize_step(self, step: str | None) -> str | None:
        if step is None:
            return None
        normalized = step.strip().lower().replace("_", "-")
        aliases = {"orphan-scan": "orphan", "cross-reference": "cross-ref"}
        normalized = aliases.get(normalized, normalized)
        if normalized not in {"orphan", "cross-ref", "synthesis", "quality"}:
            raise ValueError(f"unknown dream-cycle step: {step}")
        return normalized

    def _orphan_sort_rank(self, entry: dict) -> int:
        if entry.get("page_type") == "raw":
            return 0
        if entry.get("page_type") == "atom":
            return 1
        return 2

    def _compile_suggestion_sources(self, queue_items: list[dict]) -> set[str]:
        sources: set[str] = set()
        for item in queue_items:
            if item.get("item_type") != "compile_suggestion":
                continue
            for doc_id in item.get("raw_doc_ids") or []:
                sources.add(str(doc_id))
            prepare_params = item.get("prepare_params") or {}
            if isinstance(prepare_params, dict):
                for doc_id in prepare_params.get("doc_ids") or []:
                    sources.add(str(doc_id))
        return sources

    def _synthesis_atom_refs(self, entries: list[dict]) -> set[str]:
        refs: set[str] = set()
        for entry in entries:
            if entry.get("page_type") != "synthesis":
                continue
            for ref in entry.get("source_refs") or []:
                _, _, doc_id = str(ref).partition(":")
                if doc_id:
                    refs.add(doc_id)
            for doc_id in entry.get("source_atoms") or []:
                refs.add(str(doc_id))
        return refs

    def _existing_orphan_first_seen(self, wiki_root: Path, wiki: WikiConfig) -> dict[tuple[str, str], str]:
        path = wiki_root / str(self._dream_config_value(wiki, "orphan", "report_path", _DEFAULT_REPORT_PATH))
        first_seen: dict[tuple[str, str], str] = {}
        if not path.exists():
            return first_seen
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = (str(item.get("orphan_type") or ""), str(item.get("doc_id") or ""))
            if all(key):
                first_seen[key] = str(item.get("first_seen") or self._now())
        return first_seen

    def _write_orphan_report(self, wiki_root: Path, wiki: WikiConfig, report: list[dict]) -> None:
        path = wiki_root / str(self._dream_config_value(wiki, "orphan", "report_path", _DEFAULT_REPORT_PATH))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for item in report:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    def _atom_keywords(self, wiki_root: Path, entry: dict) -> set[str]:
        keywords: set[str] = set()
        for field in ("keywords", "aliases"):
            value = entry.get(field) or []
            if isinstance(value, str):
                value = [value]
            for item in value:
                keywords.update(tokenize(str(item).replace("_", " ")))
        canonical_uri = entry.get("canonical_uri")
        if canonical_uri:
            page_path = wiki_root / str(canonical_uri)
            if page_path.exists():
                content = page_path.read_text(encoding="utf-8")
                frontmatter, body = self._split_frontmatter(content)
                for item in frontmatter.get("keywords") or []:
                    keywords.update(tokenize(str(item).replace("_", " ")))
                title = self._title_from_markdown(body)
                keywords.update(tokenize(title.replace("_", " ")))
        if entry.get("problem_cluster"):
            keywords.update(tokenize(str(entry["problem_cluster"]).replace("_", " ")))
        return {keyword for keyword in keywords if len(keyword) > 2}

    def _graph_relation_index(self, wiki_root: Path, wiki: WikiConfig) -> dict[tuple[str, str], list[str]]:
        grouped: dict[tuple[str, str], set[str]] = defaultdict(set)
        object_to_docs: dict[tuple[str, str], set[str]] = defaultdict(set)
        for relation in KnowledgeGraphRepository(wiki_root, wiki_id=wiki.wiki_id).read_all():
            doc_id = str(relation.get("source_doc_id") or "")
            relation_name = str(relation.get("relation") or "")
            relation_object = str(relation.get("object") or "")
            if not doc_id or not relation_name or not relation_object:
                continue
            object_to_docs[(relation_name, relation_object)].add(doc_id)

        for (relation_name, relation_object), doc_ids in object_to_docs.items():
            for first, second in combinations(sorted(doc_ids), 2):
                grouped[(first, second)].add(f"{relation_name}:{relation_object}")
        return {key: sorted(value) for key, value in grouped.items()}

    def _jaccard(self, first: set[str], second: set[str]) -> float:
        if not first or not second:
            return 0.0
        union = first | second
        if not union:
            return 0.0
        return len(first & second) / len(union)

    def _same_problem_cluster_different_topic(self, first: dict, second: dict) -> bool:
        return bool(
            first.get("problem_cluster")
            and first.get("problem_cluster") == second.get("problem_cluster")
            and first.get("topic") != second.get("topic")
        )

    def _load_atom_pages(self, wiki_root: Path, manifest: ManifestRepository, atom_ids: list[str]) -> dict[str, str]:
        pages: dict[str, str] = {}
        for atom_id in atom_ids:
            entry = manifest.find(atom_id)
            if entry is None or entry.get("page_type") != "atom":
                continue
            canonical_uri = entry.get("canonical_uri")
            if not canonical_uri:
                continue
            page_path = wiki_root / str(canonical_uri)
            if page_path.exists() and page_path.is_file():
                pages[atom_id] = page_path.read_text(encoding="utf-8")
        return pages

    def _synthesis_doc_id(self, group: CandidateGroup) -> str:
        seed = "-".join(group.atom_ids[:3])
        return f"synthesis-dream-cycle-{normalize_doc_id(seed)[:80]}"

    def _build_synthesis_page(self, wiki: WikiConfig, manifest: ManifestRepository, group: CandidateGroup, atom_pages: dict[str, str]) -> str:
        generated_at = self._now()
        topic, problem_cluster = self._infer_synthesis_metadata(manifest, group.atom_ids)
        body = self._generate_synthesis_body(wiki, group, atom_pages)
        frontmatter = {
            "page_type": "synthesis",
            "source_atoms": group.atom_ids,
            "topic": topic,
            "problem_cluster": problem_cluster,
            "generated_by": "dream-cycle",
            "generated_at": generated_at,
        }
        return "---\n" + yaml.dump(frontmatter, allow_unicode=True, sort_keys=False) + "---\n" + body.strip() + "\n"

    def _infer_synthesis_metadata(self, manifest: ManifestRepository, atom_ids: list[str]) -> tuple[str, str]:
        entries = [manifest.find(atom_id) or {} for atom_id in atom_ids[:2]]
        topics = [str(entry.get("topic") or "unknown") for entry in entries]
        clusters = [str(entry.get("problem_cluster") or "") for entry in entries]
        topic = "-".join(topics) if len(topics) >= 2 else (topics[0] if topics else "cross-domain")
        problem_cluster = clusters[0] if len(clusters) >= 2 and clusters[0] and clusters[0] == clusters[1] else "cross-domain"
        return topic, problem_cluster

    def _generate_synthesis_body(self, wiki: WikiConfig, group: CandidateGroup, atom_pages: dict[str, str]) -> str:
        if self._llm_generate is not None:
            return self._llm_generate(wiki, group, atom_pages)
        llm = CompileApplyService()
        llm_config = llm._llm_config(wiki)
        if llm_config is None:
            related = "\n".join(f"- [[{atom_id}]]" for atom_id in group.atom_ids)
            return (
                "# Dream Cycle Synthesis\n\n"
                "## Related Knowledge\n"
                f"{related}\n\n"
                "## Synthesis\n"
                "Dream Cycle found a cross-atom relationship. Configure compile.llm to generate a richer synthesis."
            )
        prompt_payload = {
            "candidate_group": group.to_dict(),
            "atom_pages": atom_pages,
        }
        api_key_env = llm._config_value(llm_config, "api_key_env")
        api_key = os.environ.get(str(api_key_env))
        if not api_key:
            raise ValueError(f"missing LLM API key environment variable: {api_key_env}")
        response = llm._post_with_retries(
            llm._chat_completions_url(str(llm._config_value(llm_config, "base_url"))),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": llm._config_value(llm_config, "model"),
                "messages": [
                    {
                        "role": "system",
                        "content": "Create a concise Agent Wiki synthesis page from related atom pages. Return Markdown only.",
                    },
                    {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=False, indent=2)},
                ],
                "max_tokens": llm._config_value(llm_config, "max_tokens", 4096),
                "temperature": 0.2,
            },
            timeout=llm._config_value(llm_config, "timeout_seconds", 120),
        )
        response.raise_for_status()
        return llm._extract_content(response.json())

    def _validate_atom_source_refs(self, wiki: WikiConfig, manifest: ManifestRepository, source_refs: list[str]) -> None:
        if not source_refs:
            raise ValueError("dream-cycle synthesis requires atom source_refs")
        for source_ref in source_refs:
            wiki_id, separator, doc_id = source_ref.partition(":")
            if separator != ":" or wiki_id != wiki.wiki_id:
                raise ValueError("dream-cycle synthesis source_refs must point to this wiki")
            entry = manifest.find(doc_id)
            if entry is None or entry.get("page_type") != "atom":
                raise ValueError("dream-cycle synthesis source_refs must point to existing atom pages")

    def _quality_issue_codes(
        self,
        wiki_root: Path,
        entry: dict,
        existing_doc_ids: set[str],
        staleness_days: int,
    ) -> list[str]:
        issue_codes: list[str] = []
        if any(not entry.get(field) for field in _REQUIRED_COMPILED_FIELDS):
            issue_codes.append("missing_frontmatter")
        if not self._page_frontmatter(wiki_root, entry) and "missing_frontmatter" not in issue_codes:
            issue_codes.append("missing_frontmatter")
        if self._is_stale(entry, staleness_days):
            issue_codes.append("stale")
        if self._has_broken_source_ref(entry, existing_doc_ids):
            issue_codes.append("broken_source_ref")
        if self._page_content_length(wiki_root, entry) < 200:
            issue_codes.append("too_short")
        return issue_codes

    def _is_stale(self, entry: dict, staleness_days: int) -> bool:
        updated = entry.get("updated") or entry.get("updated_at")
        if not updated:
            return False
        try:
            parsed = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
        except ValueError:
            return False
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC) < datetime.now(UTC) - timedelta(days=staleness_days)

    def _has_broken_source_ref(self, entry: dict, existing_doc_ids: set[str]) -> bool:
        for ref in entry.get("source_refs") or []:
            _, _, doc_id = str(ref).partition(":")
            if not doc_id or doc_id not in existing_doc_ids:
                return True
        return False

    def _page_content_length(self, wiki_root: Path, entry: dict) -> int:
        canonical_uri = entry.get("canonical_uri")
        if not canonical_uri:
            return 0
        page_path = wiki_root / str(canonical_uri)
        if not page_path.exists():
            return 0
        _, body = self._split_frontmatter(page_path.read_text(encoding="utf-8"))
        return len(body.strip())

    def _page_frontmatter(self, wiki_root: Path, entry: dict) -> dict:
        canonical_uri = entry.get("canonical_uri")
        if not canonical_uri:
            return {}
        page_path = wiki_root / str(canonical_uri)
        if not page_path.exists():
            return {}
        frontmatter, _ = self._split_frontmatter(page_path.read_text(encoding="utf-8"))
        return frontmatter

    def _split_frontmatter(self, content: str) -> tuple[dict, str]:
        match = re.match(r"\A---\n(.*?\n)---\n", content, flags=re.DOTALL)
        if not match:
            return {}, content
        try:
            frontmatter = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            frontmatter = {}
        body = content[match.end():]
        return frontmatter if isinstance(frontmatter, dict) else {}, body

    def _title_from_markdown(self, content: str) -> str:
        for line in content.splitlines():
            if line.startswith("#"):
                return line.lstrip("#").strip()
        return ""

    def _dream_config_value(self, wiki: WikiConfig, section: str, key: str, default: Any) -> Any:
        dream_cycle = getattr(wiki, "dream_cycle", None)
        if dream_cycle is None:
            return default
        section_config = self._config_get(dream_cycle, section, {})
        return self._config_get(section_config, key, default)

    def _config_get(self, config: Any, key: str, default: Any) -> Any:
        if isinstance(config, dict):
            return config.get(key, default)
        return getattr(config, key, default)

    def _now(self) -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")
