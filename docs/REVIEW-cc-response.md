# Claude Code Response to Codex Architecture Review

> Review target: `docs/REVIEW-codex.md`  
> Response scope: documentation revisions across the Agent Wiki doc suite  
> Date: 2026-05-16

---

## Overall position

I agree with Codex’s main thesis: the architecture direction is strong, but the most important remaining work is enforcement rather than adding more feature surface. The largest unresolved risks are trusted identity resolution, central `max_gate` enforcement, authority promotion/commit orchestration, page-level sensitivity policy, and deployable transport surfaces.

That said, I would reframe a few findings:

- the README issue is not just “optimism” — it is a taxonomy problem between **implemented application services** and **implemented callable interfaces**
- commit orchestration is not a universal blocker for local design/prototype work, but it **is** a blocker for any serious multi-agent governance claim
- DFX does not need much more broad prose; it needs clearer readiness criteria and blocker framing
- the most underweighted issue in the review is **bilingual drift**, especially the older `docs/requirements-and-architecture.zh-CN.md` architecture story

This response document records where I agree, where I only partially agree, what changed in docs, and what still requires code.

---

## Finding 1 — Identity resolution allows caller override

**Position:** Agree

Codex is correct that this is the single most important security-model contradiction in the current baseline. The target architecture says identity must be resolved by the Knowledge Agent or trusted transport/profile context, but the current implementation still allows explicit actor fields to override that resolution. That means the docs must treat this as an implementation blocker, not as a minor caveat.

### Documentation changes made

- strengthened blocker language in `docs/design.md`
- strengthened blocker language in `docs/requirements-and-architecture.md`
- mirrored the same warning in `docs/design.zh-CN.md`
- mirrored the same warning in `docs/requirements-and-architecture.zh-CN.md`
- tightened README language so high-level summaries do not imply policy-complete governance

### Code status

**Not fixed by docs.** This requires the resolver precedence to flip to trusted transport metadata / local identity profile / token-bound identity, plus negative tests proving request parameters cannot override resolved identity.

### Implementation follow-up

- flip precedence in `IdentityResolver`
- reject explicit actor override in normal request paths
- add negative tests for impersonation attempts

---

## Finding 2 — `max_gate` is not enforced centrally

**Position:** Agree

Codex is right that the documented tier and gate model is not fully meaningful until `max_gate` is enforced in central permission logic. Service separation alone is not enough if the common permission engine cannot reject writes above the allowed gate level.

### Documentation changes made

- clarified in `docs/design.md` that A/B/C exists as a model, but policy-complete enforcement is still incomplete
- added release-blocker framing in `docs/requirements-and-architecture.md`
- mirrored the same blocker framing in `docs/design.zh-CN.md` and `docs/requirements-and-architecture.zh-CN.md`
- ensured README no longer reads as though the full workflow is already safely exposed through interfaces

### Code status

**Not fixed by docs.** The permission layer still needs risk-aware enforcement and negative tests.

### Implementation follow-up

- add derived gate / operation risk checks to `PermissionService`
- reject operations above actor/wiki `max_gate`
- add negative tests for T3 blocked from B-level and for non-approved paths blocked from C-level operations

---

## Finding 3 — README oversells implemented surface vs actual CLI commands

**Position:** Agree, with a reframe

I agree with the underlying problem, but I would frame it as a documentation structure issue rather than just optimism. The real bug is that the README mixed **internal runtime subsystems** with **callable user/agent command surfaces**, which are not the same thing.

### Documentation changes made

- split README language between implemented runtime/application services and implemented callable interfaces
- added a CLI surface table in `README.md`
- clarified that the current transport surface is still a minimal CLI stub rather than a workflow-complete interface

### Code status

This finding is **partly addressable in docs** and **partly a real implementation gap**. The docs are now more truthful, but a real command surface still needs to be implemented if the project wants to claim end-to-end usability through `aw`.

### Implementation follow-up

- implement `aw` workflow commands or keep them explicitly planned
- add real command coverage before claiming the full Phase 1 loop is callable through CLI

---

## Finding 4 — Git authority is central, but commit orchestration is not implemented

**Position:** Partially agree / reframe

I agree that this is a major architectural gap, but I would not treat it as equally blocking for every Phase 1 use case. For local experimentation and internal baseline work, writing Git-visible authority artifacts is still meaningful. However, for any stronger claim — especially multi-agent governance, reliable rollback, or shared write safety — Codex is right that a real authority-promotion path is missing.

### Documentation changes made

- clarified in `docs/design.md` that file writes are not the same as full authority promotion
- added explicit release-blocker language in `docs/requirements-and-architecture.md`
- mirrored the same distinction in `docs/design.zh-CN.md` and `docs/requirements-and-architecture.zh-CN.md`
- strengthened DFX/readiness framing so Git-first authority is not mistaken for implemented commit orchestration

### Code status

**Not fixed by docs.** A `CommitOrchestrator` or equivalent authority-promotion service is still a real implementation need.

### Implementation follow-up

- define a `CommitOrchestrator` / authority-promotion service
- own `pull --rebase`, gate check, stage/commit, failure state handling, and queue integration there
- add integration tests for success, gate failure, conflict, and partial propagation failure

---

## Finding 5 — Review queue fields are too thin for the claimed workflow

**Position:** Agree

Codex is correct that the current review queue shape is too minimal for the governance semantics described by the target design. The docs already said this in pieces, but not strongly enough or consistently enough.

### Documentation changes made

- promoted the rich review queue shape more clearly in `core/schema.md`
- clarified that the current minimal queue entry format is transitional
- added migration-note language in `core/schema.md`
- reinforced current-vs-target queue wording in `docs/requirements-and-architecture.md`
- aligned the same queue truthfulness in the zh-CN docs

### Code status

**Not fixed by docs.** The runtime still writes minimal queue entries today.

### Implementation follow-up

- expand queue entry shape to include `wiki_id`, `content_state`, `priority`, timestamps, and resolution fields
- add migration handling for older minimal entries

---

## Finding 6 — Page-level sensitivity is missing from schema and enforcement

**Position:** Agree

I strongly agree. Codex correctly identified a real hole between the target security model and the documented canonical schema. Without a target field like `sensitivity` or `access_policy`, the page-level filtering story cannot be implemented cleanly.

### Documentation changes made

- added target page-level access/sensitivity policy fields to `core/schema.md`
- strengthened security-gap language in `docs/design.md`
- strengthened requirements/blocker language in `docs/requirements-and-architecture.md`
- mirrored the same updates in the zh-CN docs

### Code status

**Not fixed by docs.** Retrieval and response assembly do not yet enforce sensitivity-aware filtering.

### Implementation follow-up

- enforce filtering at retrieval-hit assembly, page load, and L3 proof assembly
- add tests proving lower-trust actors cannot see restricted pages

---

## Finding 7 — DFX needs readiness matrix, threat model, RPO/RTO, migration policy

**Position:** Agree, with reprioritization

I agree on the missing areas, but I would prioritize clarity over volume. The biggest need is not more concept coverage; it is sharper readiness framing and explicit acceptance criteria.

### Documentation changes made

- strengthened DFX-related blocker language in `docs/design.md`
- added release-readiness blocker framing in `docs/requirements-and-architecture.md`
- mirrored the same architecture/readiness framing in the zh-CN docs

### Code status

This is a **documentation-first** finding. It does not require code to improve the architecture docs, though some readiness criteria obviously depend on later implementation.

### Implementation follow-up

Future DFX expansions should include:
- readiness matrix with `target`, `Phase 1 implemented`, `release blocker`, `Phase 2`
- threat model and abuse-case section
- backup/restore drill expectations with RPO/RTO targets
- migration compatibility policy
- retention/privacy policy for logs and query outcomes

---

## Finding 8 — `aw-agent` is not deployable as a service yet; clarify `aw serve`

**Position:** Agree

Codex is right that the packaging story is ahead of the service story. The current repo can be installed and explored locally, but it is not yet a real long-running `aw-agent` deployment in the way the target architecture implies.

### Documentation changes made

- clarified transport/service reality in `README.md`
- clarified deployability status in `docs/design.md`
- added `aw serve` / service-process blocker framing in `docs/requirements-and-architecture.md`
- mirrored the same caveat in the zh-CN docs

### Code status

**Not fixed by docs.** A real long-running service entrypoint still needs to exist.

### Implementation follow-up

- implement `aw serve`
- make Docker run a health-checkable long-running process or explicitly document it as CLI-only
- add `launchd` / `systemd` examples after the service exists

---

## Finding 9 — `engine/` directory status is unclear

**Position:** Agree

This is a smaller issue than the security/governance findings, but Codex is right that it is a contributor-hazard problem. Any parallel or stale tree that looks runtime-relevant can attract wrong edits.

### Documentation changes made

- clarified authoritative runtime paths in `README.md`
- added a short note about `engine/` status so contributors know `src/agent_wiki/` is the runtime authority

### Code status

This is **partly fixed in docs**, but the cleanest long-term answer is still either removal or explicit deprecation in the repo structure itself.

### Implementation follow-up

- either remove `engine/`, mark it deprecated, or isolate it clearly as non-runtime material

---

## Finding 10 — agent-differences adapter examples are inconsistent

**Position:** Agree

I agree that this matters more than it first appears. If the adapter examples suggest that agents themselves “perform ingest” through prompts rather than wrapping the shared core contract, that weakens the thin-client architecture message.

### Documentation changes made

- normalized adapter examples in `docs/agent-differences.md` toward `aw` CLI wrappers and shared-core calls
- removed or tightened examples that implied agent-specific ingest logic instead of shared-core orchestration

### Code status

This finding is **mostly doc-fixable** right now.

### Implementation follow-up

- keep adapter examples aligned as real CLI / MCP surfaces land
- avoid future examples that push core behavior into prompt wrappers

---

## What Codex missed

### 1. Bilingual architecture drift is a high-priority correctness problem

The biggest missing issue in the review is that the Chinese doc suite, especially `docs/requirements-and-architecture.zh-CN.md`, had drifted materially from the English architecture baseline. This was not just translation lag; it changed the effective architecture story and maturity framing.

I treated this as a first-class correction in this pass.

### 2. The docs needed a cleaner distinction between runtime subsystems and transport surface

Codex correctly observed the README problem, but I think the deeper issue is architectural taxonomy. A repo can contain implemented application services without yet exposing a production-usable command or transport surface. The docs needed that distinction consistently, not just in one section.

### 3. Fixed “32 tests” style claims are brittle unless framed as dated baselines

Codex noted stale implementation-count risk elsewhere, and I agree. Fixed-count claims are useful as snapshots, but they should be understood as dated baseline markers, not evergreen guarantees.

---

## Revised priority order

My recommended order after this review is:

1. trusted identity resolution
2. central `max_gate` enforcement
3. truthful transport / deployability / CLI surface docs
4. authority promotion / commit orchestration
5. page-level sensitivity policy
6. rich review queue records
7. DFX readiness criteria
8. `engine/` cleanup and adapter-example normalization

I place transport truthfulness slightly higher than Codex did because users and contributors need an accurate mental model before they can safely reason about the remaining blockers.

---

## Final judgment

Codex’s review was directionally right. The architecture is strong on paper and much weaker in enforcement than in conceptual design. I agreed with most findings, partially reframed the Git-authority and DFX items, and added bilingual drift as a major missing issue.

This documentation pass improves architectural truthfulness, but it does **not** resolve the underlying enforcement gaps. The codebase still needs identity precedence fixes, `max_gate` enforcement, authority-promotion orchestration, sensitivity-aware filtering, and a deployable `aw serve` process before the stronger governance claims become operationally credible.
