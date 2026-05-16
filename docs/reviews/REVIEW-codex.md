# Codex Architecture Review

> Review scope: `README.md`, `core/schema.md`, `docs/design.md`, `docs/requirements-and-architecture.md`, `docs/agent-differences.md`, and `docs/dfx.md`.
> Focus: architectural consistency, gaps/contradictions, DFX completeness, security model adequacy, and deployment realism.

---

## Executive Summary

Agent Wiki has a coherent target architecture: Git authority, local workspace/runtime state, protocol-centered `aw-agent`, thin agent adapters, lexical retrieval baseline, optional vector providers, and explicit A/B/C risk gates. The newer docs also do a useful job separating target design from the current Phase 1 implementation baseline.

The main risk is not conceptual direction; it is the gap between strong architectural claims and the current enforcement/deployment surface. The design depends heavily on identity resolution, gate enforcement, Git commit orchestration, review queue lifecycle, and transport consistency, but the docs explicitly state several of those are not implemented yet. That is acceptable for a Phase 1 baseline only if the project treats those gaps as release blockers before claiming production-ready multi-agent governance.

## Ratings

| Dimension | Rating | Rationale |
|---|---:|---|
| Architectural consistency across docs | 4/5 | The major prior conflicts have been resolved: provider-based retrieval, `wiki_id:doc_id`, thin adapters, and workspace-first pending sync are consistent across the main docs. Remaining issues are mostly target-vs-current gaps and a few stale implementation references. |
| Gaps or contradictions | 3/5 | The docs clearly disclose many gaps, but several are central to the architecture: identity override, `max_gate`, Git commit orchestration, rich review queue lifecycle, page sensitivity, and transport surfaces. |
| DFX completeness vs industry standards | 3/5 | `docs/dfx.md` covers the right dimensions and names many gaps, but lacks concrete runbooks, SLO enforcement, backup/restore drills, threat model, schema migration plan, and operational readiness criteria. |
| Security model adequacy | 2/5 | The target model is reasonable, but the current baseline allows caller-supplied identity override, lacks `max_gate` enforcement, lacks page-level sensitivity filtering, and has no token/transport implementation yet. |
| Deployment realism | 2/5 | Local packaging exists, but `aw-agent`, MCP, REST, service management, and real CLI workflow commands are not yet deployable. Docker currently runs help, not a service. |

Overall rating: **3/5**. The architecture is directionally strong, but it is not yet operationally enforceable.

---

## Strengths

- The authority model is consistent: Git is the committed source of truth, while `.agent-wiki/` holds runtime state. This appears in the README principles and requirements baseline (`README.md:72`, `docs/requirements-and-architecture.md:88`).
- The target-vs-current distinction is explicit. `core/schema.md` says the schema is the target operational model and current code enforces only a subset (`core/schema.md:6`), while `docs/design.md` makes the same point for MCP/REST and the current CLI stub (`docs/design.md:64`).
- Retrieval direction is now coherent: target query flow aggregates by `wiki_id:doc_id` (`docs/design.md:281`) and the schema uses the same identity key (`core/schema.md:246`).
- Thin adapter architecture is consistently stated in the agent differences doc (`docs/agent-differences.md:28`) and requirements (`docs/requirements-and-architecture.md:100`).
- DFX coverage is broad. `docs/dfx.md` covers deployability, reliability, security, observability, performance, maintainability, and extensibility (`docs/dfx.md:1`).

---

## Findings

### 1. Critical: identity resolution violates the target security model

The requirements state that identity must be resolved by the Knowledge Agent rather than caller-controlled request parameters (`docs/requirements-and-architecture.md:285`). The same document explicitly notes that explicit actor fields are still accepted and preferred in the current resolver (`docs/requirements-and-architecture.md:289`). `docs/design.md` also calls this a real implementation gap (`docs/design.md:231`).

The implementation confirms the risk: `IdentityResolver.resolve()` prefers `context.actor_type` and `context.actor_id` over metadata (`src/agent_wiki/infrastructure/identity/resolver.py:5`), and the test suite currently locks in that behavior (`tests/test_identity_resolution.py:5`).

Impact: any transport or CLI path that allows explicit actor fields can impersonate a higher-privilege actor unless another layer blocks it. This undermines the A/B/C gate model and the `actor_type + actor_id` permission design.

Recommendation:
- Flip resolver precedence to trusted transport metadata / local identity profile / token-bound identity.
- Treat explicit actor request fields as invalid or debug-only in tests.
- Add negative tests proving request parameters cannot override resolved identity.

### 2. Critical: authorization is incomplete because `max_gate` is not enforced

The design depends on gate strength by operation risk (`docs/requirements-and-architecture.md:113`) and explicitly says full `max_gate` enforcement remains incomplete (`docs/requirements-and-architecture.md:121`). `docs/design.md` confirms `max_gate` is not enforced and no central gate-check service exists yet (`docs/design.md:185`).

The current `PermissionService` checks actor type, actor ID, operation, and page type, but not operation risk or `max_gate` (`src/agent_wiki/infrastructure/identity/permissions.py:5`).

Impact: T3/T2 boundary claims are not enforceable through the central permission engine. The system can document “T3 only capture_raw,” but enforcement must be in code before multi-agent writes are safe.

Recommendation:
- Add `operation_risk` or derived gate classification to permission decisions.
- Make `PermissionService.check()` reject operations above actor/wiki `max_gate`.
- Add tests for T3 blocked from B-level and all non-MCP paths blocked from C-level approval.

### 3. High: README implementation claims are more optimistic than the actual transport surface

`README.md` says the current Phase 1 baseline includes raw capture, compile update, query, sync, feedback, weekly review, approvals, shared wiki restrictions, and cross-wiki smoke coverage (`README.md:42`). It later states that MCP and REST are not fully implemented (`README.md:61`). `docs/design.md` is more precise: the current implemented transport surface is still a minimal CLI stub (`docs/design.md:64`, `docs/design.md:210`). The CLI file only exposes `info` (`src/agent_wiki/transports/cli/app.py:13`).

Impact: a reader may expect `aw capture`, `aw query`, `aw sync`, or `aw approve` to exist because application services exist. In deployment terms, application services are not equivalent to a usable multi-agent interface.

Recommendation:
- In `README.md`, split “implemented application services” from “implemented user/agent commands.”
- Add a command coverage table for `aw` showing `implemented`, `planned`, and `not started`.
- Avoid calling the Phase 1 loop “implemented” until the CLI or MCP exposes it end-to-end.

### 4. High: Git authority is central, but commit orchestration is not implemented

The architecture’s authority chain is Git-first (`README.md:74`, `docs/requirements-and-architecture.md:88`). The requirements also admit the current runtime does not implement full gate-to-commit orchestration (`docs/requirements-and-architecture.md:96`). `docs/design.md` lists rollback, stale markers, mirror handling, provider-index refresh, retry, and conflict snapshots as not implemented (`docs/design.md:152`).

Impact: the system can write Git-visible files, but the stronger claim “write must pass gate then commit authority” is not yet real. This affects reliability, auditability, and external edit safety.

Recommendation:
- Define one `CommitOrchestrator` or equivalent service that owns `pull --rebase`, gate check, staging, commit, failure states, and review queue creation.
- Keep application services file-oriented, but route authority promotion through this orchestrator.
- Add integration tests for success, gate failure, rebase conflict, and partial propagation failure.

### 5. High: review queue target is strong, but implementation shape is too thin for the claimed workflow

The target queue requires `wiki_id`, `item_type`, `status`, `content_state`, `priority`, assignment, source refs, and resolution fields (`core/schema.md:326`). The current implementation only writes `item_type`, `doc_id`, `reason`, and `status` (`core/schema.md:363`). Requirements also call richer lifecycle, assignment, and priority design targets (`docs/requirements-and-architecture.md:264`).

Impact: weekly review, conflict repair, feedback triage, and C-level proposal tracking cannot yet operate with the governance semantics described in the design.

Recommendation:
- Promote the rich queue item schema to the implemented JSONL shape early.
- Include `wiki_id` immediately; otherwise multi-wiki queue aggregation is ambiguous.
- Add migration behavior for old minimal queue entries.

### 6. High: page-level sensitivity is a security requirement but missing from schema and enforcement

`docs/dfx.md` correctly says sensitivity must be represented at page level and enforced at query time (`docs/dfx.md:216`). It also lists the lack of page-level sensitivity schema and query filtering as a gap (`docs/dfx.md:250`). However, the target common frontmatter fields in `core/schema.md` do not include `sensitivity`, `access_policy`, or equivalent (`core/schema.md:93`).

Impact: the security design cannot be implemented cleanly if the canonical schema has no field for sensitivity. Retrieval can leak sensitive pages to lower-trust agents even if wiki-level permissions are correct.

Recommendation:
- Add target fields such as `sensitivity`, `allowed_actor_types`, or `access_policy` to the schema.
- Filter at retrieval hit assembly, full-page load, and L3 proof assembly.
- Add tests proving sensitive pages are excluded from T3 and lower-trust actors.

### 7. Medium: source provenance has a documented smoke-path bypass

The requirements state truth-zone `source_refs` must refer to tracked raw pages via `wiki_id:doc_id` (`docs/requirements-and-architecture.md:224`). The same section says the shared-wiki approval flow currently has a targeted bypass for smoke-path principle/shared writes (`docs/requirements-and-architecture.md:231`).

Impact: this is acceptable as a smoke shortcut, but dangerous if it survives into normal C-level approval. C-level artifacts have the highest reasoning blast radius.

Recommendation:
- Mark this bypass with an explicit expiration criterion.
- Add a failing test or TODO gate that blocks production mode C-level approval without raw-backed `source_refs`.

### 8. Medium: DFX is broad but not yet industry-grade operationally

`docs/dfx.md` covers the right dimensions, but many industry-standard controls remain future work: service-manager examples, compose packaging, reverse proxy/TLS/OIDC (`docs/dfx.md:86`), stale markers and retry controller (`docs/dfx.md:164`), health metrics and alerting (`docs/dfx.md:328`), benchmarks and budgets (`docs/dfx.md:404`), and schema migrations/runbooks (`docs/dfx.md:480`).

Missing or under-specified areas:
- threat model and abuse cases
- backup/restore drills with RPO/RTO
- incident response and audit review workflow
- capacity assumptions for number of wikis/pages/index cards
- migration compatibility policy
- privacy/data retention policy for query outcomes and logs
- secret scanning and leak prevention for Git-backed knowledge

Recommendation:
- Add a DFX readiness matrix with `target`, `Phase 1 implemented`, `release blocker`, and `Phase 2` columns.
- Add minimum operational acceptance criteria before any “production-ready” label.

### 9. Medium: deployment packaging exists, but `aw-agent` is not deployable as a service yet

`pyproject.toml` defines both `aw` and `aw-agent` entry points, but both point to the same CLI app (`pyproject.toml:29`). The Dockerfile installs the package and runs `aw --help` (`Dockerfile:10`). `docs/dfx.md` states production-grade MCP server, `aw serve`, service-manager examples, docker-compose, and REST deployment are not implemented (`docs/dfx.md:86`).

Impact: the deployment story is currently package/demo-level, not service-level. That is fine for a local library baseline but not for the documented `aw-agent` process model.

Recommendation:
- Add `aw serve` as the explicit process entrypoint before claiming `aw-agent` deployment.
- Make Docker run a health-checkable long-running process or document it as a CLI image only.
- Add launchd/systemd examples once `aw serve` exists.

### 10. Medium: legacy or parallel structure may confuse contributors

The README says the current runtime implementation lives under `src/agent_wiki/` (`README.md:92`) and its repository structure omits `engine/` (`README.md:133`). The repository still contains top-level `engine/*.py` files.

Impact: new contributors may not know whether `engine/` is legacy, scaffold, or planned architecture. This is a maintainability risk because future patches could land in the wrong tree.

Recommendation:
- Either remove `engine/`, mark it deprecated, or document it explicitly as legacy/non-runtime.
- Add a short note to `README.md` or `docs/design.md` clarifying authoritative runtime paths.

### 11. Medium: agent-differences still has a few implementation-shape ambiguities

The agent differences doc correctly states all agents are thin clients (`docs/agent-differences.md:28`). But some adapter sections still describe structures such as `wiki-ingest.sh` wrappers around `opencode run 'ingest...'` (`docs/agent-differences.md:176`) rather than direct `aw` CLI calls, while Codex has cleaner `aw` wrapper naming (`docs/agent-differences.md:142`).

Impact: minor, but it weakens the thin-client message and can lead adapter authors to re-implement behavior in agent prompts.

Recommendation:
- Normalize all adapter examples to `aw query`, `aw capture-raw`, `aw compile-*`, and `aw lint` wrappers.
- Avoid examples where the model itself is asked to “ingest” independently of `aw-agent`.

---

## Dimension-by-Dimension Review

### A. Architectural Consistency Across Docs — 4/5

The target architecture is mostly consistent: protocol-centered `aw-agent`, thin adapters, pluggable retrieval, Git authority, and `wiki_id:doc_id` identity are repeated across the main docs. The strongest consistency evidence is `docs/design.md:36`, `docs/requirements-and-architecture.md:100`, and `docs/agent-differences.md:28`.

Remaining coherence issues are mainly stale or incomplete implementation references: `engine/` exists but is not documented in the current runtime map, OpenCode wrappers are less clean than Codex wrappers, and several target contracts are not reflected in implemented schemas.

### B. Gaps or Contradictions — 3/5

Most contradictions are now disclosed as “current implementation profile” or “Phase 1 simplification,” which is good. The major unresolved gaps are not hidden: identity override (`docs/design.md:231`), incomplete gate enforcement (`docs/design.md:185`), minimal queue shape (`core/schema.md:363`), and no full transport surface (`docs/design.md:217`).

The remaining risk is that the README’s implemented baseline can be read as more complete than the actual callable surface. Tighten this wording before external users rely on it.

### C. DFX Completeness vs Industry Standards — 3/5

DFX is comprehensive at the category level, but it is closer to an architectural intent document than an operational readiness spec. It should add concrete acceptance criteria for deployment, recovery, security, observability, and performance. The current DFX document itself lists many missing controls across deployability (`docs/dfx.md:86`), reliability (`docs/dfx.md:164`), security (`docs/dfx.md:250`), observability (`docs/dfx.md:328`), performance (`docs/dfx.md:404`), and maintainability (`docs/dfx.md:480`).

### D. Security Model Adequacy — 2/5

The target security model has the right concepts: actor identity, permissions, A/B/C gates, local-first trust, future OIDC, page-level sensitivity, and audit logs. The current adequacy score is low because the most important controls are not enforced yet: identity can be overridden, `max_gate` is not enforced, page-level sensitivity is not in schema/enforcement, and MCP/REST/token handling is not implemented.

Security should be treated as a Phase 1 blocker before exposing anything beyond a trusted local development workflow.

### E. Deployment Realism — 2/5

The project can be installed as a Python package and tested locally. It does not yet deploy as the documented long-running `aw-agent` service. The current Dockerfile is a packaging smoke test, not a deployable agent service (`Dockerfile:10`). `aw-agent` points to the same minimal CLI app as `aw` (`pyproject.toml:29`). MCP and REST are dependencies/design targets but not implemented transports.

Deployment realism improves substantially once `aw serve`, health checks, service-manager configs, and real CLI workflow commands exist.

---

## Recommended Priority Fixes

1. **Fix identity resolution precedence** so request fields cannot override trusted transport/profile identity.
2. **Enforce `max_gate` centrally** and add T3/T2/C-level negative tests.
3. **Implement or clearly label the CLI command surface** for `capture_raw`, `query`, `compile`, `sync`, `feedback`, and `weekly-review`.
4. **Add `sensitivity` or equivalent access fields to schema** and enforce filtering in retrieval and response assembly.
5. **Implement rich `review_queue` fields** at least for `wiki_id`, `item_type`, `status`, `content_state`, `priority`, and timestamps.
6. **Create a real `aw serve` process** before claiming `aw-agent` deployment.
7. **Clarify `engine/` status** to prevent contributors from modifying stale architecture paths.
8. **Add DFX readiness gates** for backup/restore, health checks, threat model, migration policy, and benchmark targets.

---

## Final Assessment

The project is architecturally promising and has improved significantly: the docs now mostly agree on the core model, and the current-vs-target distinction is explicit. The next bar is enforcement. A multi-agent knowledge system is only as credible as its identity, permission, gate, provenance, and audit paths. Those paths are well-designed on paper but only partially implemented today.

The practical recommendation is to avoid adding more feature surface until the core governance path is enforceable: trusted identity resolution, `max_gate`, Git commit orchestration, rich review queue records, and sensitivity-aware query filtering.

