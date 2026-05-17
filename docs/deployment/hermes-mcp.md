# Hermes MCP Deployment

Agent Wiki should be mounted into Hermes as a stdio MCP sidecar. This is the primary Phase 1 deployment path.

## Goal

After this setup, Hermes can call these five MCP tools directly:

- `wiki.query`
- `wiki.capture_raw`
- `wiki.compile_update`
- `wiki.lint`
- `wiki.sync`

The runtime boundary stays the same as the rest of Phase 1:

- `Git authority -> workspace runtime state -> external view`
- Hermes identity is resolved by the MCP session metadata path
- callers do not override identity through tool parameters

## Prerequisites

- `agent-wiki` is installed in the same runtime environment Hermes can launch
- `aw-agent --help` works
- the target machine has a valid `registry.yaml`
- the registry contains a permission profile for Hermes, for example `actor_id: hermes`

A local preflight looks like this:

```bash
aw health --registry /abs/path/to/registry.yaml
aw-agent --help
```

## Hermes MCP servers config

Use `aw-agent serve` as the command Hermes launches.

```json
{
  "mcpServers": {
    "agent-wiki": {
      "command": "aw-agent",
      "args": [
        "serve",
        "--registry",
        "/abs/path/to/registry.yaml"
      ],
      "env": {
        "AGENT_WIKI_WORKSPACE": "/abs/path/to/wiki-workspace",
        "AGENT_WIKI_ACTOR_TYPE": "agent",
        "AGENT_WIKI_ACTOR_ID": "hermes"
      }
    }
  }
}
```

## Identity and permissions

Hermes should be bound to a registry permission profile instead of passing `actor_id` in tool arguments.

Example registry rule:

```yaml
permissions:
  - actor_type: agent
    actor_id: hermes
    allowed_operations:
      - query
      - capture_raw
      - compile_update
      - lint
      - sync
    max_gate: C
    allowed_page_types:
      - raw
      - atom
      - synthesis
      - principle
```

The important constraint is architectural, not cosmetic:

- Hermes session metadata identifies the caller
- Agent Wiki resolves that metadata into the runtime actor
- tool payloads stay focused on wiki inputs such as `wiki_id`, `query`, `doc_id`, and `source_refs`

## Tool expectations

Use the MCP tools this way:

- `wiki.query`: read path for L1/L2/L3 answers over committed knowledge, with optional pending inclusion when explicitly requested
- `wiki.capture_raw`: low-risk raw capture into Git-tracked pages or pending runtime state
- `wiki.compile_update`: truth-zone compile step that writes internal authority state only
- `wiki.lint`: authority/workspace consistency checks
- `wiki.sync`: explicit external-view sync, including Obsidian push-view

`wiki.compile_update` and `wiki.sync` stay decoupled by design. If Hermes wants a convenience workflow, it can call compile first and then sync, but the underlying architecture remains two separate operations.

## Operational notes

- Keep Hermes on the MCP stdio path for normal agent workflows. REST is auxiliary.
- Point `--registry` at the shared registry that defines the accessible wikis and agent permissions.
- Use `aw health` before attaching the sidecar to Hermes or after rotating registry/config.
- If Hermes runs under a supervisor or container, make sure the same environment can resolve `aw-agent` and read the registry path.

## Troubleshooting

If Hermes cannot discover the server:

- verify `aw-agent --help`
- verify `aw serve --registry /abs/path/to/registry.yaml` starts without argument errors
- verify the registry path is readable from the Hermes runtime

If Hermes can connect but writes are denied:

- verify the registry has a matching `actor_id: hermes` permission rule
- verify the rule allows the requested operation and page type
- verify the rule has sufficient `max_gate`

If query works but external views do not update:

- this is usually expected unless Hermes also calls `wiki.sync`
- `compile_update` changes internal authority/workspace state only
- external propagation is triggered by explicit sync
