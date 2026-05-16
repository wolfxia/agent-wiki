# DFX Design

> Deployability, Reliability, Security, Observability, Performance, Maintainability, and Extensibility for Agent Wiki  
> v1.0 — 2026-05-16  
> Status: Design target aligned against the current Phase 1 implementation baseline

---

## 0. Scope and Reading Guide

This document complements:

- `README.md`
- `core/schema.md`
- `docs/design.md`
- `docs/agent-differences.md`

It defines the non-functional system design for Agent Wiki across seven DFX dimensions. Each section distinguishes between:

- the **design target** that should remain stable as the architecture evolves
- the **current Phase 1 baseline** already implemented or clearly supportable in the repository
- the **Phase 2 direction** where stronger multi-agent and networked operation becomes necessary

The same rule used elsewhere in the repo applies here:

**Do not collapse target architecture and current implementation into one story.** The target explains where the system is going; the implementation notes explain what exists today.

---

## 1. Deployability

### Design goal

Agent Wiki should be easy to install, run, upgrade, and roll back across three deployment shapes:

1. local single-user knowledge service
2. containerized self-hosted service
3. network-exposed multi-user service

Deployment must preserve the core architecture: one shared `aw-agent` process, Git as authority, local workspace as runtime state, and thin MCP / CLI / REST interfaces over the same core.

### Key decisions

#### Decision: run as an independent agent process, not an embedded library

**Rationale:** the project’s architecture assumes one shared knowledge engine serving multiple clients and transports. A long-running process fits MCP service hosting, approval routing, background maintenance, and identity resolution better than per-client embedded logic.

**Alternative considered:** embedding wiki logic directly in each agent adapter or client library.

**Why rejected:** that would duplicate core behavior, weaken identity and gate enforcement, and make propagation, audit, and transport consistency harder.

#### Decision: make local deployment the primary Phase 1 operating mode

**Rationale:** the current project target is personal multi-agent knowledge on one machine. Local install and local process management minimize operational complexity while preserving the architecture.

**Alternative considered:** start with a network service first.

**Why rejected:** Phase 1 does not need full remote auth, reverse proxy, or shared-team operational posture.

#### Decision: use registry YAML + environment variables + `.env` in a 12-factor style

**Rationale:** Agent Wiki needs explicit multi-wiki configuration plus environment-specific overrides. Registry config expresses knowledge topology; environment variables express deployment concerns such as ports, tokens, and storage paths.

**Alternative considered:** hard-coded per-agent config or one monolithic config file.

**Why rejected:** that would couple transport/runtime concerns to knowledge topology and make container or host deployment less portable.

#### Decision: use Git branch isolation as the main release and rollback boundary for knowledge state

**Rationale:** Git is already the authority of record. Branch-based rollout aligns deployment safety with the repository’s core authority model and allows quick rollback of committed knowledge state.

**Alternative considered:** database-native migration/version rollout as the primary release boundary.

**Why rejected:** it would demote Git from the authority role and complicate the Phase 1 operational story.

### Phase 1 implementation status

Implemented or directly aligned with the current baseline:

- Python package install flow exists through `pyproject.toml` and local editable install patterns already documented in `README.md`.
- CLI surface exists as a minimal stub in `src/agent_wiki/transports/cli/app.py`.
- Registry-driven configuration loading exists in `src/agent_wiki/bootstrap/registry_loader.py`.
- The runtime model already separates committed Git artifacts from local runtime state under `.agent-wiki/`.
- Dockerfile exists at the repository root, which supports the single-package deployment direction.

Not yet implemented in the current repository baseline:

- production-grade MCP server process
- full `aw serve` long-running process surface
- service-manager examples for `launchd` / `systemd`
- docker-compose packaging for optional retrieval providers
- REST deployment with reverse proxy, TLS, and OIDC

### Phase 2 plan

Phase 2 should add:

- a first-class long-running `aw-agent` service with MCP and REST enabled
- reverse-proxied HTTPS deployment via nginx or caddy
- OIDC-backed remote identity and session handling
- clearer release packaging for host installs and containers
- network-safe configuration layering for tokens, certificates, and per-wiki policy

### Relation to other DFX dimensions

- **Reliability:** deployment shape determines restart behavior and rollback speed.
- **Security:** network deployment expands the auth and transport security surface.
- **Observability:** service packaging should expose health checks and structured logs.
- **Maintainability:** one deployable core process is easier to evolve than multiple embedded implementations.
- **Extensibility:** deployment should not depend on one transport or one adapter.

---

## 2. Reliability

### Design goal

Agent Wiki should preserve knowledge integrity across crashes, partial propagation, and retrieval degradation. The system must fail in ways that are observable, repairable, and consistent with Git-first authority.

### Key decisions

#### Decision: treat write propagation completeness as the core reliability boundary

**Rationale:** in this system, a write is not just a page edit. It must update downstream artifacts such as manifest, retrieval index, logs, and queue state. Reliability therefore centers on whether propagation completed coherently.

**Alternative considered:** define success as “page file written successfully.”

**Why rejected:** that would create knowledge islands and silent divergence between page content and retrieval/audit state.

#### Decision: use a layered rollback model: pending state, stale markers, then Git revert

**Rationale:** not every failure should force destructive rollback. Pending state is a pre-commit buffer, stale markers are a soft rollback signal, and Git revert remains the hard authority-level recovery path.

**Alternative considered:** immediate hard rollback for any propagation failure.

**Why rejected:** it is too coarse, throws away recoverable work, and does not match the workspace-versus-authority split.

#### Decision: degrade queries gracefully when optional retrieval components fail

**Rationale:** Phase 1 query capability must not depend on vector infrastructure. Lexical retrieval is the required baseline, so the system can remain usable when optional retrieval providers fail.

**Alternative considered:** fail closed when vector or richer retrieval is unavailable.

**Why rejected:** it would make an optional enhancement a single point of operational failure.

#### Decision: rely on Git remotes and text-recoverable JSONL artifacts for backup and recovery

**Rationale:** this matches the Git-first model and keeps core recovery human-auditable. JSONL manifests and indexes are inspectable and reconstructable.

**Alternative considered:** only database-native recovery.

**Why rejected:** Phase 1 should remain file-first and recoverable without specialized storage tooling.

### Phase 1 implementation status

Implemented or partially implemented today:

- Propagation orchestration exists in `src/agent_wiki/application/propagation.py`.
- Pending fallback exists for invalid raw capture through `.agent-wiki/pending_manifest.jsonl`.
- Lexical retrieval provides an operational degraded mode in `src/agent_wiki/application/query.py` and `src/agent_wiki/infrastructure/retrieval/retrieval_index.py`.
- JSONL-backed artifacts such as `MANIFEST.jsonl`, `retrieval_index.jsonl`, `operation_log.jsonl`, and `review_queue.jsonl` align with text-recoverable recovery.
- The current repo design already assumes Git remote as the natural backup boundary.

Design target not yet fully implemented:

- explicit seven-check F1-F7 health model
- automatic stale markers on propagation failure
- automatic retry orchestration with pause after two consecutive failures
- transactional rollback between downstream propagation stages
- restart supervision documentation for long-running server processes

### Phase 2 plan

Phase 2 should add:

- explicit propagation integrity states and stale-marker lifecycle
- retry controller with bounded retry and pause behavior
- richer crash recovery for long-running MCP / REST service processes
- explicit coordination for concurrent multi-writer updates
- stronger integrity validation across mirrors and external views

### Relation to other DFX dimensions

- **Deployability:** restart and rollback strategy depends on deployment packaging.
- **Security:** auditability and reliable rollback reduce the blast radius of bad writes.
- **Observability:** reliability failures must become visible as health signals and alerts.
- **Performance:** retries and rebuilds must not starve normal query/write flows.
- **Maintainability:** clear failure states simplify repair and operator reasoning.

---

## 3. Security

### Design goal

Agent Wiki should protect sensitive knowledge, constrain agent behavior by identity and capability, and ensure that high-risk operations require stronger approval paths. Security must match the project’s trust model: local-first in Phase 1, stronger remote and team controls in Phase 2.

### Key decisions

#### Decision: separate authentication, authorization, and operation risk gates

**Rationale:** the architecture already distinguishes who the caller is, what capability tier they have, and what risk level the operation represents. This keeps low-risk usage easy while preserving a hard boundary for high-risk writes.

**Alternative considered:** one flat allow/deny permission system.

**Why rejected:** it would not express the project’s A/B/C gate model or the T1/T2/T3 capability model clearly enough.

#### Decision: Phase 1 uses loopback-local trust with local token; Phase 2 moves to OIDC

**Rationale:** local-only deployment minimizes exposure while still requiring explicit caller identity. OIDC becomes necessary only when the service is network-exposed or team-shared.

**Alternative considered:** require full remote-style auth from the start.

**Why rejected:** it adds unnecessary operational burden to the Phase 1 personal workflow.

#### Decision: sensitivity must be represented at page level and enforced at query time

**Rationale:** the repo is expected to hold API keys, internal notes, and other sensitive knowledge. Filtering only at repository or wiki level is too coarse; page-level sensitivity makes retrieval and output safer.

**Alternative considered:** treat the whole wiki as uniformly trusted.

**Why rejected:** it fails the multi-agent and mixed-sensitivity use case.

#### Decision: preserve auditable text logs for every material operation

**Rationale:** operations that change knowledge state must remain attributable by agent identity, target document, and timestamp.

**Alternative considered:** transient runtime-only audit events.

**Why rejected:** they are insufficient for review, debugging, and trust restoration after incidents.

#### Decision: isolate content adapter execution and validate system-boundary inputs

**Rationale:** adapters ingest external content and are the most likely place for malformed or malicious input to enter the system.

**Alternative considered:** trust all markdown/content inputs as safe internal data.

**Why rejected:** external content is a boundary and should be treated as untrusted.

### Phase 1 implementation status

Implemented or partially represented today:

- Identity and permission helpers exist in `src/agent_wiki/infrastructure/identity/resolver.py`, `permissions.py`, and `gates.py`.
- A/B/C separation is reflected by service boundaries across raw capture, compile update, and approvals.
- Approval audit exists through `approval_log.jsonl` and compile operations are logged to `operation_log.jsonl`.
- Input validation already exists in limited form for `doc_id`, `allowed_page_types`, and `source_refs`.
- The project instructions already preserve the rule that high-risk approval should go through MCP or an equivalent confirmation path.

Important gaps relative to the design target:

- resolved identity can still be overridden by explicit actor fields in the current implementation path described in `docs/design.md`
- no full `max_gate` enforcement engine yet
- no implemented page-level `sensitivity` schema and query filtering yet
- no git-crypt workflow or encrypted content handling in the current baseline
- no transport-level TLS / mTLS because network service is not yet implemented
- no adapter sandbox runtime yet

### Phase 2 plan

Phase 2 should add:

- OIDC-based authentication for remote access
- transport security via TLS and mTLS for service-to-service trust where needed
- enforced page-level sensitivity filtering at retrieval and response assembly time
- stronger high-risk approval routing that always uses the canonical approval path
- encrypted repository patterns where confidential content requires protected storage workflows
- hardened content-adapter sandboxing and validation profiles

### Relation to other DFX dimensions

- **Deployability:** remote deployment widens the security boundary.
- **Reliability:** audit logs and safe rollback help contain bad or unauthorized changes.
- **Observability:** suspicious access and repeated gate failures should become visible signals.
- **Maintainability:** security rules should live in shared core policy, not in per-agent wrappers.
- **Extensibility:** every new adapter and transport must plug into the same identity and policy system.

---

## 4. Observability

### Design goal

Agent Wiki should make knowledge operations diagnosable by both machines and humans. Operators should be able to answer:

- what happened
- why a query or propagation failed
- whether knowledge integrity is drifting
- which maintenance actions deserve attention

### Key decisions

#### Decision: keep both structured machine logs and human-readable logs

**Rationale:** JSONL logs support automation and inspection tooling; markdown logs support quick human review in Git-native workflows.

**Alternative considered:** only human-readable logs or only structured logs.

**Why rejected:** one format alone would weaken either tooling or operator readability.

#### Decision: health reporting should reflect propagation integrity, not only process liveness

**Rationale:** a running process is not the same as a healthy knowledge system. Health must describe whether downstream artifacts remain in sync.

**Alternative considered:** only expose “server up/down” checks.

**Why rejected:** it misses the system’s actual correctness boundary.

#### Decision: weekly review is part of observability, not just maintenance

**Rationale:** observability for a knowledge system includes whether the system is being used effectively. Low-signal queries, stale queue items, and missing evidence are operational signals.

**Alternative considered:** treat weekly review as a purely human governance workflow.

**Why rejected:** it hides actionable behavioral feedback from the operational picture.

### Phase 1 implementation status

Implemented today:

- human-readable `log.md` writes through propagation
- structured `operation_log.jsonl` for compile operations
- structured `approval_log.jsonl` for approvals
- structured `query_outcomes.jsonl` through feedback submission
- weekly review summary generation in `src/agent_wiki/application/weekly_review.py`
- minimal lint and consistency checks in `src/agent_wiki/application/linting.py`

Not yet implemented relative to the target design:

- dedicated `aw health` surface with a formal seven-check report
- latency, hit-rate, propagation-success, and stale-count metrics export
- threshold-based alerting for repeated propagation failures or stale buildup
- automated query-outcome capture directly in the query path
- richer observability dashboards over queue pressure, external sync drift, and retrieval provider health

### Phase 2 plan

Phase 2 should add:

- a first-class health endpoint / command
- durable metrics collection for latency, hit quality, propagation integrity, and queue health
- alerting hooks for repeated propagation failure and stale accumulation
- stronger traceability across MCP, CLI, and REST calls
- better operator summaries linking usage patterns to maintenance actions

### Relation to other DFX dimensions

- **Reliability:** observability is how propagation and recovery problems become actionable.
- **Security:** audit logs and access traces are part of the security model.
- **Performance:** latency and retrieval metrics drive tuning decisions.
- **Maintainability:** clear diagnostics reduce debugging cost.
- **Extensibility:** pluggable providers must expose comparable health and usage signals.

---

## 5. Performance

### Design goal

Agent Wiki should remain fast enough for local agent workflows while preserving correctness and traceability. Performance targets should be shaped by the actual Phase 1 operating model: file-backed, local, mostly single-user, and retrieval-provider pluggable.

### Key decisions

#### Decision: lexical retrieval is the required baseline and should be optimized first

**Rationale:** lexical retrieval is the guaranteed Phase 1 path and the fallback mode when richer retrieval fails. It must be fast enough for routine local use.

**Alternative considered:** optimize only vector retrieval because it may provide better recall.

**Why rejected:** vector retrieval is optional in Phase 1 and cannot be the only performance story.

#### Decision: keep raw capture and compile update lightweight and file-oriented in Phase 1

**Rationale:** most Phase 1 operations write a bounded set of markdown and JSONL artifacts. That should keep the core write path predictable and low-latency.

**Alternative considered:** eagerly introduce heavier persistence and distributed coordination.

**Why rejected:** it would overfit Phase 2 needs and complicate the current baseline.

#### Decision: Phase 1 uses optimistic concurrency; explicit locks are reserved for Phase 2

**Rationale:** single-user or loosely coordinated use is sufficient for the current project scope. Strong locking would add complexity before there is a real multi-writer need.

**Alternative considered:** implement explicit locking from day one.

**Why rejected:** premature coordination overhead for a local-first baseline.

### Phase 1 implementation status

Current baseline characteristics:

- Query path is file-backed lexical retrieval over `retrieval_index.jsonl`.
- Writes are bounded filesystem and JSONL append/update flows.
- Cross-wiki query exists but remains a simple fan-out baseline.
- No heavyweight retrieval provider is required for minimum functionality.

Target numbers from this design task:

- lexical retrieval under 100ms for local JSONL-backed queries
- vector retrieval under 500ms when optional provider is enabled
- `capture_raw` under 50ms for pure file operations
- `compile_update` under 200ms for bounded propagation work

Not yet implemented for measurement or enforcement:

- benchmark harnesses tied to these SLO-like targets
- explicit query/load budgets in the runtime
- segmented retrieval index loading for large repositories
- vector-store LRU caching and provider budgeting
- lock-aware concurrent write controls for team-scale operation

### Phase 2 plan

Phase 2 should add:

- explicit performance benchmarks and regression checks
- segmented indexes and larger-repo retrieval strategies
- provider-aware cache and query budget controls
- stronger concurrency control for multi-writer scenarios
- metrics-backed tuning across retrieval, propagation, and cross-wiki fan-out

### Relation to other DFX dimensions

- **Reliability:** degraded-mode retrieval must stay usable under provider failure.
- **Observability:** performance claims need metrics to be credible.
- **Maintainability:** simpler data paths are easier to tune and reason about.
- **Extensibility:** new providers must fit the same normalized hit and budget model.

---

## 6. Maintainability

### Design goal

Agent Wiki should remain easy to evolve without losing architectural clarity. Maintainability depends on a stable shared core, explicit boundaries, strong tests, and documentation that distinguishes current behavior from target design.

### Key decisions

#### Decision: keep a layered architecture with one-way dependencies

**Rationale:** the existing structure already separates application, domain, infrastructure, bootstrap, and transports. That keeps core policy separate from adapters and deployment surfaces.

**Alternative considered:** feature-first modules that mix transport, storage, and domain decisions.

**Why rejected:** that would blur the core/adapter boundary central to the project.

#### Decision: preserve design docs as living architecture documents, not retrospective marketing

**Rationale:** future contributors and reviewers need to understand both the target architecture and the current implementation gaps.

**Alternative considered:** rewrite docs to describe only what is implemented today.

**Why rejected:** it would erase the intended system shape and make Phase 2 decisions harder to evaluate consistently.

#### Decision: validate with milestone-oriented tests and structural linting

**Rationale:** the repository already uses milestone coverage across M1-M6. Structural integrity checks match the file-backed architecture.

**Alternative considered:** rely mainly on ad hoc manual testing.

**Why rejected:** it would not scale as propagation, approvals, and multi-wiki behavior become richer.

#### Decision: schema versioning and migrations should be explicit

**Rationale:** file-backed schemas and runtime metadata will evolve. Versioned migrations preserve continuity without hiding format changes.

**Alternative considered:** silent format drift.

**Why rejected:** that makes old knowledge artifacts ambiguous and harder to repair.

### Phase 1 implementation status

Implemented today:

- layered code organization under `src/agent_wiki/`
- milestone-backed test baseline with 32 passing tests across M1-M6, as documented in `README.md`
- core documentation set across README, schema, design, requirements, and agent-difference docs
- minimal lint checks for manifest/page and manifest/index consistency

Not yet fully implemented relative to the target design:

- full schema migration framework
- richer lint coverage for broken references, orphan pages, and frontmatter completeness
- complete CLI / MCP / REST parity tests
- broader documentation for operator runbooks and deployment procedures

### Phase 2 plan

Phase 2 should add:

- explicit schema versioning and migration utilities
- expanded structural and semantic lint suites
- stronger contract tests shared across transports
- more complete operator documentation for deployment, recovery, and approval workflows
- clearer extension author guidance for adapters and retrieval providers

### Relation to other DFX dimensions

- **Deployability:** maintainable packaging and config reduce operational burden.
- **Reliability:** clear structure makes failure recovery easier to implement correctly.
- **Security:** policy logic is safer when centralized and testable.
- **Extensibility:** maintainability is what keeps plugin points from turning into forks.

---

## 7. Extensibility

### Design goal

Agent Wiki should grow by adding transports, adapters, retrieval providers, and agent profiles without changing the core knowledge model. Extensibility must preserve shared contracts rather than creating parallel implementations.

### Key decisions

#### Decision: all major integrations depend on interfaces over the shared core

**Rationale:** the project already states that storage, content adapters, retrieval, embeddings, and external views should remain pluggable. A stable core contract keeps feature growth from fragmenting behavior.

**Alternative considered:** implement integrations directly inside each transport or agent adapter.

**Why rejected:** it would duplicate propagation, permissions, and query semantics.

#### Decision: make content adapters the normalization boundary

**Rationale:** Obsidian, Plain Markdown, Notion, and future views should map into one internal representation while preserving format-specific metadata only as adapter metadata.

**Alternative considered:** let each external system define its own internal semantics.

**Why rejected:** retrieval, propagation, and policy logic would become system-specific.

#### Decision: keep transports interchangeable over one approval and policy path

**Rationale:** MCP, CLI, and REST should be transport alternatives, not independent policy engines.

**Alternative considered:** let each transport own its own approval and permission behavior.

**Why rejected:** that would make risk handling inconsistent and harder to verify.

### Phase 1 implementation status

Already aligned in the design and partially in code:

- registry-driven multi-wiki model provides a natural extension point
- transport boundary already exists conceptually, with current CLI stub under `src/agent_wiki/transports/cli/app.py`
- retrieval provider abstraction is present at the design level, with lexical retrieval as the Phase 1 baseline
- agent adaptation strategy is documented in `docs/agent-differences.md`

Not yet implemented in the current repository baseline:

- first-class `ContentAdapter` plugin runtime
- multiple retrieval provider implementations behind a common registry
- MCP and REST transport implementations
- explicit agent-profile registration flow for T1/T2/T3 templates

### Phase 2 plan

Phase 2 should add:

- formal adapter interfaces and registration mechanisms
- multiple retrieval providers behind one normalized hit contract
- transport-complete MCP / CLI / REST surfaces
- stronger agent identity profiles with reusable tier templates
- extension guidance that keeps external integrations thin

### Relation to other DFX dimensions

- **Maintainability:** extensibility only works if the shared core remains coherent.
- **Security:** every extension must inherit the same identity, policy, and gate rules.
- **Performance:** provider plugins need normalized budgets and metrics.
- **Deployability:** extension packaging must work in local and networked deployments.

---

## 8. Cross-DFX Summary

The seven DFX dimensions are intentionally coupled:

- **Deployability** defines where the core runs.
- **Reliability** defines when writes and queries remain trustworthy.
- **Security** defines who can see or change what.
- **Observability** defines how operators detect drift and failure.
- **Performance** defines whether the system is usable in live agent workflows.
- **Maintainability** defines whether the architecture can evolve without losing clarity.
- **Extensibility** defines whether new tools can join the system without forking the core.

For Agent Wiki, these are not secondary concerns layered on top of the product. They are part of the product definition itself, because the system’s value depends on trusted multi-agent knowledge operations rather than simple file storage.

---

*DFX Design v1.0 aligned against the current implementation baseline. Use with `docs/design.md` and `core/schema.md` when evaluating non-functional architecture decisions.*
