# Transport, Shared Access, and Obsidian Workflows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved Phase 1 milestone as three implementation workflows: a real FastMCP stdio server, a shared registry permission model for Phase 1 agents, and explicit Obsidian push-view with graph index export.

**Architecture:** Keep `src/agent_wiki/application/*` as the business layer and keep transports thin. Resolve trusted identity in the transport boundary, authorize through the shared registry permission path, let `compile_update` mutate only internal authority/workspace state, and let explicit `sync` own all external view writes.

**Tech Stack:** Python 3.11, Typer, FastMCP from `mcp`, FastAPI test client, Pydantic, PyYAML, pytest, filesystem-backed wiki fixtures.

---

## Scope and Execution Order

This plan intentionally splits the approved spec into three workflows that can be executed mostly independently.

1. **Workflow 2: Shared registry permissions** goes first because trusted identity resolution and `sync` authorization are prerequisites for the other two workflows.
2. **Workflow 1: FastMCP stdio server** can start after Workflow 2 Task 2 is complete.
3. **Workflow 3: Obsidian push-view** can start after Workflow 2 Task 3 is complete.
4. **Workflow 1 Task 4** must wait for **Workflow 3 Task 3**, because the final `wiki.sync` tool contract must expose `doc_ids` and the Obsidian graph-index side effect.

## File Map

### Workflow 1: FastMCP rewrite
- Create: `src/agent_wiki/transports/mcp/dispatcher.py`
- Modify: `src/agent_wiki/transports/mcp/server.py`
- Modify: `src/agent_wiki/transports/cli/app.py`
- Modify: `tests/test_mcp_server.py`
- Modify: `tests/test_cli_smoke.py`
- Modify: `pyproject.toml` only if the console entrypoints need to be clarified, not renamed

### Workflow 2: Shared registry permissions
- Modify: `src/agent_wiki/infrastructure/identity/resolver.py`
- Modify: `src/agent_wiki/infrastructure/identity/gates.py`
- Modify: `src/agent_wiki/infrastructure/identity/permissions.py`
- Modify: `src/agent_wiki/application/sync.py`
- Modify: `tests/fixtures/registry.yaml`
- Modify: `tests/fixtures/registry_multi.yaml`
- Modify: `tests/test_identity_resolution.py`
- Modify: `tests/test_permissions.py`
- Modify: `tests/test_sync.py`
- Modify: `tests/test_rest_app.py`
- Modify: `tests/test_cli_smoke.py`
- Modify: `tests/test_mcp_server.py`

### Workflow 3: Obsidian push-view
- Modify: `src/agent_wiki/application/sync.py`
- Modify: `src/agent_wiki/infrastructure/adapters/obsidian.py`
- Modify: `src/agent_wiki/infrastructure/storage/manifest_repo.py` only if a helper is needed to read filtered manifest rows cleanly
- Modify: `tests/test_sync.py`
- Modify: `tests/test_compile_apply.py` if a transport-independent decoupling regression test fits better there

## Verification Gate

Every workflow ends with:

- targeted pytest for the touched area
- transport regression tests for CLI, REST, and MCP when identity or permissions are changed
- full suite run with a regression floor of `125 passed`

Recommended full-suite command at the end of each workflow:

```bash
pytest -q
```

Expected:

```text
125 passed or more, 0 failed
```

---

## Workflow 2: Shared Registry Permissions

### Task 1: Expand the registry fixture baseline for shared agents and `sync`

**Files:**
- Modify: `tests/fixtures/registry.yaml`
- Modify: `tests/fixtures/registry_multi.yaml`
- Test: `tests/test_permissions.py`

- [ ] **Step 1: Write the failing test**

```python
def test_permission_service_allows_phase1_shared_agent_profiles() -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0]
    service = PermissionService()

    hermes = service.check(
        ResolvedActor(actor_type="agent", actor_id="hermes", transport="mcp"),
        operation="sync",
        wiki=wiki,
        page_type="raw",
    )
    claude = service.check(
        ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        operation="compile_update",
        wiki=wiki,
        page_type="atom",
    )
    codex = service.check(
        ResolvedActor(actor_type="agent", actor_id="codex", transport="cli"),
        operation="compile_update",
        wiki=wiki,
        page_type="atom",
    )

    assert hermes.allowed is True
    assert claude.allowed is True
    assert codex.allowed is False
    assert codex.required_gate == "B"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_permissions.py::test_permission_service_allows_phase1_shared_agent_profiles -v`
Expected: FAIL because the fixture registry does not yet define `hermes`, `openclaw`, `sync`, or the reserved `codex` profile.

- [ ] **Step 3: Write the minimal implementation**

```yaml
permissions:
  - actor_type: agent
    actor_id: hermes
    allowed_operations: [query, capture_raw, compile_update, lint, sync]
    max_gate: C
    allowed_page_types: [raw, atom, synthesis]
  - actor_type: agent
    actor_id: openclaw
    allowed_operations: [query, capture_raw, compile_update, lint, sync]
    max_gate: C
    allowed_page_types: [raw, atom, synthesis]
  - actor_type: agent
    actor_id: claude-code
    allowed_operations: [query, capture_raw, compile_update, lint, sync]
    max_gate: B
    allowed_page_types: [raw, atom, synthesis]
  - actor_type: agent
    actor_id: codex
    allowed_operations: [query, capture_raw]
    max_gate: A
    allowed_page_types: [raw]
```

Apply the same Phase 1 profile shape to `tests/fixtures/registry_multi.yaml`, keeping the shared wiki restricted to the page types already allowed by that wiki.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_permissions.py::test_permission_service_allows_phase1_shared_agent_profiles -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/registry.yaml tests/fixtures/registry_multi.yaml tests/test_permissions.py
git commit -m "test: add shared agent registry fixture coverage"
```

### Task 2: Harden trusted identity precedence in the shared resolver

**Files:**
- Modify: `src/agent_wiki/infrastructure/identity/resolver.py`
- Modify: `tests/test_identity_resolution.py`
- Test: `tests/test_mcp_server.py`
- Test: `tests/test_rest_app.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_identity_resolver_uses_trusted_metadata_for_mcp() -> None:
    actor = IdentityResolver().resolve(
        IdentityContext(
            transport="mcp",
            actor_type="agent",
            actor_id="spoofed",
            metadata={"actor_type": "agent", "actor_id": "hermes"},
        )
    )
    assert actor.actor_id == "hermes"


def test_identity_resolver_uses_explicit_cli_identity_when_metadata_missing() -> None:
    actor = IdentityResolver().resolve(
        IdentityContext(
            transport="cli",
            actor_type="agent",
            actor_id="claude-code",
        )
    )
    assert actor.actor_id == "claude-code"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_identity_resolution.py -v`
Expected: FAIL because the resolver currently uses one precedence rule for every transport and does not document the transport-specific trust boundary clearly.

- [ ] **Step 3: Write the minimal implementation**

```python
class IdentityResolver:
    _TRUST_METADATA = {"mcp", "rest"}

    def resolve(self, context: IdentityContext) -> ResolvedActor:
        metadata = context.metadata or {}
        if context.transport in self._TRUST_METADATA:
            actor_type = metadata.get("actor_type") or context.actor_type
            actor_id = metadata.get("actor_id") or context.actor_id
        else:
            actor_type = context.actor_type or metadata.get("actor_type")
            actor_id = context.actor_id or metadata.get("actor_id")
        if not actor_type or not actor_id:
            raise IdentityResolutionError("actor_type and actor_id are required")
        return ResolvedActor(actor_type=actor_type, actor_id=actor_id, transport=context.transport)
```

Keep the MCP and REST request body payloads unable to override the transport-bound identity. Do not add a caller-supplied `actor` parameter anywhere in service input models.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_identity_resolution.py tests/test_mcp_server.py tests/test_rest_app.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_wiki/infrastructure/identity/resolver.py tests/test_identity_resolution.py tests/test_mcp_server.py tests/test_rest_app.py
git commit -m "feat: enforce trusted transport identity precedence"
```

### Task 3: Route `sync` through the shared gate and permission path

**Files:**
- Modify: `src/agent_wiki/infrastructure/identity/gates.py`
- Modify: `src/agent_wiki/infrastructure/identity/permissions.py`
- Modify: `src/agent_wiki/application/sync.py`
- Modify: `tests/test_permissions.py`
- Modify: `tests/test_sync.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_permission_service_reports_required_gate_for_sync() -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0]
    decision = PermissionService().check(
        ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        operation="sync",
        wiki=wiki,
        page_type="raw",
    )
    assert decision.allowed is True
    assert decision.required_gate == "A"


def test_sync_push_view_requires_sync_permission(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    with pytest.raises(PermissionError):
        SyncService().execute(
            wiki,
            ResolvedActor(actor_type="agent", actor_id="codex", transport="cli"),
            SyncInput(mode="push-view"),
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_permissions.py tests/test_sync.py -v`
Expected: FAIL because `GateService` does not classify `sync` explicitly and `SyncService` still maps `status` to `query` and `pull-view`/`push-view` to `capture_raw`.

- [ ] **Step 3: Write the minimal implementation**

```python
class GateService:
    def required_gate(self, operation: Operation | str, page_type: PageType | str) -> GateLevel:
        operation = Operation(operation)
        page_type = PageType(page_type)
        if operation in {Operation.QUERY, Operation.CAPTURE_RAW, Operation.SYNC, Operation.LINT}:
            return GateLevel.A
        if operation in {Operation.COMPILE_UPDATE, Operation.MARK_DISPUTED}:
            return GateLevel.B
        if page_type == PageType.PRINCIPLE or operation in {
            Operation.PROMOTE_PRINCIPLE,
            Operation.APPROVE_PROPOSAL,
            Operation.CROSS_WIKI_MERGE,
        }:
            return GateLevel.C
        return GateLevel.B
```

```python
class SyncService:
    def _check_permission(self, actor: ResolvedActor, wiki: WikiConfig) -> None:
        decision = PermissionService().check(actor, "sync", wiki, "raw")
        if not decision.allowed:
            raise PermissionError(decision.reason)
```

Call `_check_permission()` once per `execute()` path instead of mapping sync modes to unrelated operations.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_permissions.py tests/test_sync.py tests/test_cli_smoke.py tests/test_rest_app.py tests/test_mcp_server.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_wiki/infrastructure/identity/gates.py src/agent_wiki/infrastructure/identity/permissions.py src/agent_wiki/application/sync.py tests/test_permissions.py tests/test_sync.py tests/test_cli_smoke.py tests/test_rest_app.py tests/test_mcp_server.py
git commit -m "feat: authorize sync through shared registry gates"
```

---

## Workflow 1: FastMCP Rewrite

### Task 1: Introduce a thin MCP dispatcher and complete the five-tool facade contract

**Files:**
- Create: `src/agent_wiki/transports/mcp/dispatcher.py`
- Modify: `src/agent_wiki/transports/mcp/server.py`
- Modify: `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_mcp_server_lists_expected_tools() -> None:
    server = MCPServer()
    tool_names = {tool["name"] for tool in server.list_tools()}
    assert tool_names == {
        "wiki.query",
        "wiki.capture_raw",
        "wiki.compile_update",
        "wiki.lint",
        "wiki.sync",
    }


def test_mcp_lint_tool_returns_structured_issue_payload(temp_wiki_root: Path) -> None:
    server = MCPServer(registry_path="tests/fixtures/registry.yaml")
    result = server.invoke(
        "wiki.lint",
        {"wiki_id": "personal-1"},
        session_metadata={"actor_type": "agent", "actor_id": "claude-code"},
        wiki_workspace_overrides={"personal-1": str(temp_wiki_root)},
    )
    assert set(result) == {"ok", "issues", "issue_count"}


def test_mcp_sync_tool_supports_status_mode(temp_wiki_root: Path) -> None:
    server = MCPServer(registry_path="tests/fixtures/registry.yaml")
    result = server.invoke(
        "wiki.sync",
        {"wiki_id": "personal-1", "mode": "status"},
        session_metadata={"actor_type": "agent", "actor_id": "claude-code"},
        wiki_workspace_overrides={"personal-1": str(temp_wiki_root)},
    )
    assert result["mode"] == "status"
    assert "changed_files" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp_server.py -v`
Expected: FAIL because the current facade exposes only three tools and has no reusable dispatcher boundary.

- [ ] **Step 3: Write the minimal implementation**

```python
class MCPDispatcher:
    def __init__(self, registry_path: str | None = None) -> None:
        self._registry_path = Path(registry_path) if registry_path else DEFAULT_REGISTRY_PATH

    def dispatch(
        self,
        tool_name: str,
        params: dict,
        identity_metadata: dict[str, str],
        wiki_workspace_overrides: dict[str, str] | None = None,
    ) -> dict:
        actor = IdentityResolver().resolve(IdentityContext(transport="mcp", metadata=identity_metadata))
        wiki = self._resolve_wiki(params["wiki_id"], wiki_workspace_overrides or {})
        if tool_name == "wiki.lint":
            result = LintService().run(wiki)
            return {"ok": result.ok, "issues": result.issues, "issue_count": len(result.issues)}
        if tool_name == "wiki.sync":
            result = SyncService().execute(wiki, actor, SyncInput(mode=params["mode"], doc_ids=params.get("doc_ids")))
            return {"mode": result.mode, "changed_files": result.changed_files}
        raise ValueError(f"unknown tool: {tool_name}")
```

Keep `MCPServer.invoke()` as a local test harness over the dispatcher so the direct invocation tests stay fast and do not require a real stdio client.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_server.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_wiki/transports/mcp/dispatcher.py src/agent_wiki/transports/mcp/server.py tests/test_mcp_server.py
git commit -m "feat: add thin mcp dispatcher and five-tool facade"
```

### Task 2: Wrap the dispatcher in a real FastMCP stdio host

**Files:**
- Modify: `src/agent_wiki/transports/mcp/server.py`
- Modify: `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_build_fastmcp_server_registers_agent_wiki_tools() -> None:
    app = build_fastmcp_server(registry_path="tests/fixtures/registry.yaml")
    tools = {tool.name for tool in app.list_tools()}
    assert app.name == "agent-wiki"
    assert tools == {
        "wiki.query",
        "wiki.capture_raw",
        "wiki.compile_update",
        "wiki.lint",
        "wiki.sync",
    }


def test_run_stdio_server_uses_stdio_transport(monkeypatch) -> None:
    captured = {}

    class FakeFastMCP:
        def run(self, transport: str = "stdio") -> None:
            captured["transport"] = transport

    monkeypatch.setattr("agent_wiki.transports.mcp.server.build_fastmcp_server", lambda **_: FakeFastMCP())
    run_stdio_server(registry_path="tests/fixtures/registry.yaml")
    assert captured["transport"] == "stdio"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp_server.py::test_build_fastmcp_server_registers_agent_wiki_tools tests/test_mcp_server.py::test_run_stdio_server_uses_stdio_transport -v`
Expected: FAIL because no FastMCP host builder or stdio runner exists yet.

- [ ] **Step 3: Write the minimal implementation**

```python
def build_fastmcp_server(registry_path: str | None = None) -> FastMCP:
    dispatcher = MCPDispatcher(registry_path=registry_path)
    server = FastMCP(name="agent-wiki")

    @server.tool(name="wiki.query", structured_output=True)
    def query_tool(wiki_id: str, query: str, include_pending: bool = False, max_sensitivity: str | None = None, ctx: Context | None = None) -> dict:
        metadata = _metadata_from_context(ctx)
        return dispatcher.dispatch(
            "wiki.query",
            {
                "wiki_id": wiki_id,
                "query": query,
                "include_pending": include_pending,
                "max_sensitivity": max_sensitivity,
            },
            metadata,
        )

    return server


def run_stdio_server(registry_path: str | None = None) -> None:
    build_fastmcp_server(registry_path=registry_path).run(transport="stdio")
```

Extract `_metadata_from_context()` into the same module. Use `ctx.client_id` plus trusted request metadata if available, but never merge caller tool parameters into identity.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_server.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_wiki/transports/mcp/server.py tests/test_mcp_server.py
git commit -m "feat: add fastmcp stdio host"
```

### Task 3: Repoint `aw serve` and the `aw-agent` alias to the stdio MCP process

**Files:**
- Modify: `src/agent_wiki/transports/cli/app.py`
- Modify: `tests/test_cli_smoke.py`
- Modify: `pyproject.toml` only if the console-script comments need to be clarified

- [ ] **Step 1: Write the failing tests**

```python
def test_cli_serve_runs_stdio_mcp_server(monkeypatch, temp_wiki_root) -> None:
    captured = {}

    def fake_run_stdio_server(registry_path: str | None = None) -> None:
        captured["registry_path"] = registry_path

    monkeypatch.setattr("agent_wiki.transports.cli.app.run_stdio_server", fake_run_stdio_server)

    result = CliRunner().invoke(
        app,
        ["serve", "--registry", "tests/fixtures/registry.yaml", "--workspace", str(temp_wiki_root)],
    )

    assert result.exit_code == 0
    assert captured["registry_path"] == "tests/fixtures/registry.yaml"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli_smoke.py::test_cli_serve_runs_stdio_mcp_server -v`
Expected: FAIL because `serve` still launches `uvicorn` instead of the MCP stdio host.

- [ ] **Step 3: Write the minimal implementation**

```python
@app.command("serve")
def serve(
    workspace: str | None = typer.Option(None, "--workspace"),
    registry: str | None = typer.Option(None, "--registry"),
) -> None:
    if workspace:
        os.environ["AGENT_WIKI_WORKSPACE"] = workspace
    run_stdio_server(registry_path=registry)
```

If CLI workspace overrides are still needed for tests, thread them into `run_stdio_server(workspace_overrides={wiki_id: workspace})` and let the MCP dispatcher own wiki override resolution, instead of reintroducing REST-style serve flags or moving wiki selection into tool payloads. Keep `aw-agent` mapped to the same `main()` entrypoint in `pyproject.toml`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli_smoke.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_wiki/transports/cli/app.py tests/test_cli_smoke.py pyproject.toml
git commit -m "feat: point aw serve at stdio mcp server"
```

### Task 4: Finalize the `wiki.sync` MCP contract against the new sync shape

**Files:**
- Modify: `src/agent_wiki/transports/mcp/dispatcher.py`
- Modify: `src/agent_wiki/transports/mcp/server.py`
- Modify: `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing test**

```python
def test_mcp_sync_tool_accepts_doc_ids(temp_wiki_root: Path) -> None:
    server = MCPServer(registry_path="tests/fixtures/registry.yaml")
    result = server.invoke(
        "wiki.sync",
        {"wiki_id": "personal-1", "mode": "push-view", "doc_ids": ["atom-1"]},
        session_metadata={"actor_type": "agent", "actor_id": "claude-code"},
        wiki_workspace_overrides={"personal-1": str(temp_wiki_root)},
    )
    assert result["mode"] == "push-view"
    assert isinstance(result["changed_files"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mcp_server.py::test_mcp_sync_tool_accepts_doc_ids -v`
Expected: FAIL until Workflow 3 exposes `doc_ids` in `SyncInput` and `SyncService`.

- [ ] **Step 3: Write the minimal implementation**

```python
@server.tool(name="wiki.sync", structured_output=True)
def sync_tool(wiki_id: str, mode: str, doc_ids: list[str] | None = None, ctx: Context | None = None) -> dict:
    metadata = _metadata_from_context(ctx)
    return dispatcher.dispatch(
        "wiki.sync",
        {"wiki_id": wiki_id, "mode": mode, "doc_ids": doc_ids},
        metadata,
    )
```

Use the existing dispatcher serialization shape:

```python
{"mode": result.mode, "changed_files": result.changed_files}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_server.py tests/test_cli_smoke.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_wiki/transports/mcp/dispatcher.py src/agent_wiki/transports/mcp/server.py tests/test_mcp_server.py tests/test_cli_smoke.py
git commit -m "feat: expose final sync contract through mcp"
```

---

## Workflow 3: Obsidian Push-View

### Task 1: Add explicit `doc_ids` filtering to `SyncInput` and `push-view`

**Files:**
- Modify: `src/agent_wiki/application/sync.py`
- Modify: `tests/test_sync.py`

- [ ] **Step 1: Write the failing test**

```python
def test_sync_push_view_exports_only_requested_doc_ids(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    pages_dir = temp_wiki_root / "pages"
    pages_dir.mkdir(exist_ok=True)
    (pages_dir / "one.md").write_text("# One", encoding="utf-8")
    (pages_dir / "two.md").write_text("# Two", encoding="utf-8")
    external_dir = temp_wiki_root / "vault"
    external_dir.mkdir(exist_ok=True)
    wiki = wiki.model_copy(update={"external_views": [{"adapter": "plain_markdown", "mode": "read_write", "path": str(external_dir)}]})

    result = SyncService().execute(
        wiki,
        ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli"),
        SyncInput(mode="push-view", doc_ids=["one"]),
    )

    assert (external_dir / "one.md").exists()
    assert not (external_dir / "two.md").exists()
    assert any(path.endswith("one.md") for path in result.changed_files)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sync.py::test_sync_push_view_exports_only_requested_doc_ids -v`
Expected: FAIL because `SyncInput` does not yet accept `doc_ids` and `push-view` exports every page unconditionally.

- [ ] **Step 3: Write the minimal implementation**

```python
class SyncInput(BaseModel):
    mode: str
    doc_ids: list[str] | None = None
```

```python
def _iter_export_sources(self, wiki_root: Path, doc_ids: list[str] | None) -> list[Path]:
    if not doc_ids:
        return sorted((wiki_root / "pages").glob("*.md"))
    return [wiki_root / "pages" / f"{doc_id}.md" for doc_id in doc_ids if (wiki_root / "pages" / f"{doc_id}.md").exists()]
```

Use `_iter_export_sources()` inside `_push_view()` so the filter stays transport-neutral.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sync.py::test_sync_push_view_exports_only_requested_doc_ids -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_wiki/application/sync.py tests/test_sync.py
git commit -m "feat: add explicit sync doc id filtering"
```

### Task 2: Lock the compile/sync decoupling boundary with tests

**Files:**
- Modify: `tests/test_sync.py`
- Modify: `tests/test_compile_apply.py` if the regression belongs with compile tests

- [ ] **Step 1: Write the failing test**

```python
def test_compile_update_does_not_push_external_view(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    external_dir = temp_wiki_root / "vault"
    external_dir.mkdir(exist_ok=True)
    wiki = wiki.model_copy(update={"external_views": [{"adapter": "obsidian", "mode": "read_write", "path": str(external_dir)}]})
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")

    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(
            doc_id="raw-decouple-1",
            topic="testing",
            problem_cluster="cluster-decouple",
            content="# Raw decouple",
            source_refs=[],
        ),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(
            doc_id="atom-decouple-1",
            page_type="atom",
            topic="testing",
            problem_cluster="cluster-decouple",
            content="# Atom decouple",
            source_refs=["personal-1:raw-decouple-1"],
        ),
    )

    assert not (external_dir / "atom-decouple-1.md").exists()
```

- [ ] **Step 2: Run test to verify it fails or prove the boundary already holds**

Run: `pytest tests/test_sync.py::test_compile_update_does_not_push_external_view -v`
Expected: PASS immediately if the decoupling already holds. If it passes immediately, keep the test and move to Step 5 without changing implementation.

- [ ] **Step 3: Write the minimal implementation only if needed**

```python
# No implementation change if the regression test already passes.
# If any convenience hook exists, remove the implicit SyncService call.
```

- [ ] **Step 4: Run the relevant test file**

Run: `pytest tests/test_sync.py tests/test_compile_apply.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_sync.py tests/test_compile_apply.py
git commit -m "test: lock compile and sync decoupling"
```

### Task 3: Generate the Obsidian graph index page on every push-view

**Files:**
- Modify: `src/agent_wiki/application/sync.py`
- Modify: `src/agent_wiki/infrastructure/adapters/obsidian.py`
- Modify: `tests/test_sync.py`

- [ ] **Step 1: Write the failing test**

```python
def test_sync_push_view_rebuilds_obsidian_graph_index(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    external_dir = temp_wiki_root / "obsidian-vault"
    external_dir.mkdir(exist_ok=True)
    wiki = wiki.model_copy(update={"external_views": [{"adapter": "obsidian", "mode": "read_write", "path": str(external_dir)}]})

    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(doc_id="raw-graph-1", topic="retrieval", problem_cluster="cluster-graph", content="# Raw graph", source_refs=[]),
    )
    CaptureRawService().execute(
        wiki=wiki,
        actor=actor,
        data=CaptureRawInput(doc_id="raw-graph-2", topic="retrieval", problem_cluster="cluster-graph", content="# Raw graph 2", source_refs=[]),
    )
    CompileUpdateService().apply(
        wiki=wiki,
        actor=actor,
        data=CompileUpdateInput(doc_id="atom-graph-1", page_type="atom", topic="retrieval", problem_cluster="cluster-graph", content="# Atom graph", source_refs=["personal-1:raw-graph-1"]),
    )

    SyncService().execute(wiki, actor, SyncInput(mode="push-view"))

    index_path = external_dir / "04-知识图谱" / "知识图谱索引.md"
    text = index_path.read_text(encoding="utf-8")
    assert "## Atom" in text
    assert "## Synthesis" in text
    assert "## Raw" in text
    assert "[[atom-graph-1]]" in text
    assert "topic: retrieval" in text
    assert "problem_cluster: cluster-graph" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sync.py::test_sync_push_view_rebuilds_obsidian_graph_index -v`
Expected: FAIL because `push-view` currently writes pages only and does not create `04-知识图谱/知识图谱索引.md`.

- [ ] **Step 3: Write the minimal implementation**

```python
def _write_obsidian_graph_index(self, wiki: WikiConfig, external_path: Path) -> str:
    manifest_entries = ManifestRepository(Path(wiki.workspace_path)).read_all()
    index_path = external_path / "04-知识图谱" / "知识图谱索引.md"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    content = ObsidianAdapter().render_graph_index(manifest_entries)
    index_path.write_text(content, encoding="utf-8")
    return str(index_path)
```

```python
class ObsidianAdapter:
    def render_graph_index(self, manifest_entries: list[dict]) -> str:
        grouped = {"atom": [], "synthesis": [], "raw": []}
        for entry in manifest_entries:
            page_type = entry.get("page_type")
            if page_type in grouped:
                grouped[page_type].append(entry)
        lines = ["# 知识图谱索引", ""]
        for title, key in [("Atom", "atom"), ("Synthesis", "synthesis"), ("Raw", "raw")]:
            lines.append(f"## {title}")
            for entry in grouped[key]:
                lines.append(
                    f"- [[{entry['doc_id']}]] · topic: {entry.get('topic', '')} · problem_cluster: {entry.get('problem_cluster', '')}"
                )
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"
```

Call `_write_obsidian_graph_index()` from `_push_view()` only for views whose adapter is `obsidian`. Always rebuild the index on every push, even when `doc_ids` is filtered.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sync.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent_wiki/application/sync.py src/agent_wiki/infrastructure/adapters/obsidian.py tests/test_sync.py
git commit -m "feat: rebuild obsidian graph index on push view"
```

### Task 4: Finalize push-view compatibility and run the full regression gate

**Files:**
- Modify: `tests/test_sync.py`
- Modify: `src/agent_wiki/application/sync.py` only if compatibility gaps are exposed

- [ ] **Step 1: Write the failing compatibility test**

```python
def test_obsidian_push_view_preserves_frontmatter_and_reports_index_file(temp_wiki_root: Path) -> None:
    wiki = RegistryLoader().load(Path("tests/fixtures/registry.yaml")).wikis[0].model_copy(
        update={"workspace_path": str(temp_wiki_root)}
    )
    actor = ResolvedActor(actor_type="agent", actor_id="claude-code", transport="cli")
    external_dir = temp_wiki_root / "obsidian-vault"
    external_dir.mkdir(exist_ok=True)
    (external_dir / "existing.md").write_text("---\ntags:\n  - wiki\n---\n# Existing\n", encoding="utf-8")
    (temp_wiki_root / "pages").mkdir(exist_ok=True)
    (temp_wiki_root / "pages" / "existing.md").write_text("# Existing\n\nNew content.", encoding="utf-8")
    wiki = wiki.model_copy(update={"external_views": [{"adapter": "obsidian", "mode": "read_write", "path": str(external_dir)}]})

    result = SyncService().execute(wiki, actor, SyncInput(mode="push-view", doc_ids=["existing"]))

    assert any(path.endswith("04-知识图谱/知识图谱索引.md") for path in result.changed_files)
    assert "tags:" in (external_dir / "existing.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sync.py::test_obsidian_push_view_preserves_frontmatter_and_reports_index_file -v`
Expected: FAIL until `changed_files` includes the derived index artifact and the filtered export path still preserves existing frontmatter.

- [ ] **Step 3: Write the minimal implementation**

```python
if self._view_adapter(view) == "obsidian":
    changed_files.append(self._write_obsidian_graph_index(wiki, external_path))
```

Do not break the existing frontmatter preservation branch:

```python
if target.exists():
    existing = adapter.read(str(target))
    document["adapter_metadata"] = existing.get("adapter_metadata", {})
```

- [ ] **Step 4: Run verification**

Run: `pytest tests/test_sync.py tests/test_mcp_server.py tests/test_cli_smoke.py -v`
Expected: PASS

Run: `pytest -q`
Expected: `125 passed` or more and `0 failed`

- [ ] **Step 5: Commit**

```bash
git add src/agent_wiki/application/sync.py tests/test_sync.py tests/test_mcp_server.py tests/test_cli_smoke.py
git commit -m "test: verify push view compatibility and regression gate"
```

---

## Workflow 1 Final Regression Gate

Run after Workflow 1 Task 4 and Workflow 3 Task 4 are both merged.

- [ ] `pytest tests/test_mcp_server.py tests/test_cli_smoke.py tests/test_permissions.py tests/test_identity_resolution.py -v`
- [ ] `pytest -q`

Expected:

```text
125 passed or more, 0 failed
```

## Workflow 2 Final Regression Gate

- [ ] `pytest tests/test_identity_resolution.py tests/test_permissions.py tests/test_sync.py tests/test_rest_app.py tests/test_cli_smoke.py tests/test_mcp_server.py -v`
- [ ] `pytest -q`

Expected:

```text
125 passed or more, 0 failed
```

## Self-Review

### Spec coverage

- FastMCP stdio server with `aw serve` and `aw-agent` alias: covered by Workflow 1 Tasks 1-3.
- Five MCP tools `wiki.query`, `wiki.capture_raw`, `wiki.compile_update`, `wiki.lint`, `wiki.sync`: covered by Workflow 1 Tasks 1, 2, and 4.
- Trusted identity resolution and no caller override: covered by Workflow 2 Task 2 and transport regression tests.
- Shared registry permissions for `hermes`, `openclaw`, `claude-code`, reserved `codex`: covered by Workflow 2 Task 1.
- Shared gate enforcement including `sync`: covered by Workflow 2 Task 3.
- `compile_update` writes internal state only and does not push Obsidian: covered by Workflow 3 Task 2.
- Explicit `push-view` with incremental `doc_ids` filter: covered by Workflow 3 Task 1.
- Obsidian graph index at `04-知识图谱/知识图谱索引.md`: covered by Workflow 3 Tasks 3 and 4.
- TDD and regression floor of 125 passing tests: enforced in every workflow verification gate.

### Placeholder scan

This document intentionally avoids `TODO`, `TBD`, and "write tests for the above" placeholders. Each task names exact files, a concrete failing test, a concrete command, and a minimal implementation sketch.

### Type consistency

- `SyncInput` ends as `mode: str` plus `doc_ids: list[str] | None = None`.
- The MCP `wiki.sync` tool forwards `wiki_id`, `mode`, and optional `doc_ids` only.
- `PermissionService.check()` continues to receive `operation`, `wiki`, and `page_type`, with `sync` authorized against page type `raw`.

