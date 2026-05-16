import json
from pathlib import Path

from agent_wiki.bootstrap.registry_loader import WikiConfig
from agent_wiki.domain.contracts import ResolvedActor
from agent_wiki.infrastructure.identity.permissions import PermissionService
from agent_wiki.infrastructure.storage.manifest_repo import ManifestRepository


class AuthorityService:
    def promote(self, wiki: WikiConfig, actor: ResolvedActor, doc_id: str) -> dict:
        wiki_root = Path(wiki.workspace_path)
        manifest = ManifestRepository(wiki_root)
        entry = manifest.find(doc_id)
        if entry is None:
            return {"status": "blocked", "reason": "doc_id not found in manifest", "doc_id": doc_id}

        page_type = entry.get("page_type", "raw")
        operation = "promote_principle" if page_type == "principle" else "compile_update"
        permission_service = PermissionService()
        decision = permission_service.check(actor, operation, wiki, page_type)
        if not decision.allowed:
            self._append_authority_log(wiki_root, {
                "status": "blocked",
                "doc_id": doc_id,
                "reason": decision.reason,
                "actor_id": actor.actor_id,
            })
            return {"status": "blocked", "doc_id": doc_id, "reason": decision.reason}

        self._append_authority_log(wiki_root, {
            "status": "promoted",
            "doc_id": doc_id,
            "page_type": page_type,
            "actor_id": actor.actor_id,
        })
        return {"status": "promoted", "doc_id": doc_id, "page_type": page_type}

    def _append_authority_log(self, wiki_root: Path, entry: dict) -> None:
        path = wiki_root / "authority_log.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
