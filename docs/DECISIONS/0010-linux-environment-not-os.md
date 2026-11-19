# ADR 0010 — LoopEnvironment is an agent-oriented Linux environment

**Status:** Accepted product direction
**Date:** 2026-11-18
**Supersedes:** [ADR 0001](0001-os-product-boundaries.md), only regarding the requirement to build a standalone operating system. The other established authority and security decisions remain in force.

## Context

LoopEnvironment was initially envisioned as an independent Linux operating system for agents to work in real graphical applications. Analysis of existing Linux, Hermes, Cua Driver, compositor integrations and sandboxing showed that the core capabilities do not inherently require creating and maintaining a new distribution. An image without proven added value increases maintenance and update costs.

## Decision

1. **Identity:** LoopEnvironment is an open-source **environment for existing Linux systems**, not a new kernel or standalone operating system. Debian is the initial development/test host, not a permanent vendor lock-in.
2. **Core:** LoopBridge is the central service, providing an authenticated, vendor-neutral, structured and permissioned interface for session/resource discovery, observation, operation, state/events and honest results.
3. **Machine-first interaction:** authorized agents prefer reliable native application/system APIs and accessible semantic actions. Visual desktop output remains for humans to observe, intervene and control, and as a separately authorized compatibility fallback. An agent does not need pixels or clicks where structured operations suffice.
4. **Authority preserved:** owner/principal-neutral identity, secure bootstrap, delegation, scoped grants, leases, audit, mandatory isolation for untrusted clients, fail-closed behavior and compositor-plus-semantic enforcement remain hard requirements. Control transfer must not be confirmed before a verified dispatch barrier; a name change does not relax security.
5. **Integration and reuse:** use upstream Linux kernel, libraries, services, compositor and accessibility interfaces with narrowly scoped trusted adapters. Cua Driver's implementation is a study/reuse candidate, **not** a committed dependency or established substitute for the LoopBridge trust boundary.
6. **Deployment:** install the environment on an existing physical or virtual Linux host. A preconfigured VM image may later be offered as a convenience, not a required deliverable or proof of technical advantage.
7. **Interoperability:** any properly authenticated person, AI or software may act behind a principal; no particular agent framework, model, vendor or VM manager is mandatory. LoopTeach remains a planned capability, not a released feature.
8. **Evidence:** historical ADRs and lab results remain preserved. Bounded M1 GO results do not imply a product/security certification, and incomplete experiment/toolchain work must remain explicitly incomplete.

## Consequences

- Update current-facing docs and roadmap to prioritize Cua Driver comparison and **LoopBridge Core V0.1** on existing Linux.
- Keep ADR 0001 and old lab/research documents unchanged as historical records; this ADR resolves conflicting product scope.
- Define installation/packages and updates for the environment itself; optionally evaluate a reproducible VM image after technical and maintenance justification.
- Preserve M1.3B/1.3C gates, no unqualified takeover promise, and no bypass of the trusted compositor/accessibility/input boundary.

## Open questions

Exact Cua reuse, compositor enforcement architecture, trusted semantic dispatcher, stable API/protocol, principal/bootstrap recovery, capture and remote transport, host compatibility, optional VM image costs, and licensing of any imported components require separate validation.
